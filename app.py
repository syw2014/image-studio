from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from image_studio import client, models, storage
except ModuleNotFoundError:  # Standalone copy: `cd image_studio && uvicorn app:app`
    import client  # type: ignore
    import models  # type: ignore
    import storage  # type: ignore


PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
TASKS: dict[str, dict[str, Any]] = {}
TASK_LOCK = threading.Lock()

load_dotenv(PACKAGE_DIR / ".env")
load_dotenv()


def _setup_logging() -> logging.Logger:
    log = logging.getLogger("image_studio")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    log.addHandler(stream)
    try:
        log_dir = storage.data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "run.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        log.addHandler(file_handler)
    except Exception:  # logging must never break generation
        pass
    log.propagate = False
    return log


logger = _setup_logging()


class ImageParams(BaseModel):
    count: int = 1
    concurrency: int = 1
    size: str = "1024x1024"
    quality: str = "auto"
    output_format: str = "png"
    aspect_ratio: str = "1:1"
    image_size: str = "1K"
    resolution: str = "1K"
    seed: str = ""
    negative_prompt: str = ""
    temperature: float = 0.8
    max_tokens: int = 4096
    timeout: float = 180
    retry_limit: int = 2


class GenerateImageRequest(BaseModel):
    prompt: str
    api_key: str | None = None
    base_url: str | None = None
    model_key: str = "gpt-image2"
    upstream_model: str | None = None
    protocol: str | None = None
    params: ImageParams = Field(default_factory=ImageParams)
    reference_images: list[str] = Field(default_factory=list)


class UpstreamModelsRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None


def params_dict(params: ImageParams) -> dict[str, Any]:
    return params.model_dump()


def default_base_url() -> str:
    return os.environ.get("IMAGE_STUDIO_API_BASE") or client.DEFAULT_BASE_URL


def create_task_state(task_id: str, count: int, concurrency: int) -> dict[str, Any]:
    safe_count = max(1, int(count))
    safe_concurrency = max(1, min(int(concurrency), safe_count))
    return {
        "task_id": task_id,
        "status": "queued",
        "progress": 5,
        "stage": "queued",
        "message": "已创建本地任务",
        "record": None,
        "error": None,
        "count": safe_count,
        "concurrency": safe_concurrency,
        "subtasks": [
            {"index": index, "status": "queued", "progress": 0, "duration_ms": None, "error": None}
            for index in range(1, safe_count + 1)
        ],
    }


def update_parent_progress(task: dict[str, Any]) -> None:
    subtasks = task["subtasks"]
    count = max(1, len(subtasks))
    completed = len([item for item in subtasks if item["status"] == "completed"])
    failed = len([item for item in subtasks if item["status"] == "failed"])
    running_progress = sum(item.get("progress", 0) for item in subtasks if item["status"] == "running")
    progress = int(((completed * 100) + running_progress) / count)
    task["progress"] = min(99, max(task.get("progress", 5), progress)) if completed + failed < count else 100
    task["message"] = f"{completed}/{count} 完成 · 并发 {task['concurrency']}"
    if completed + failed == count:
        task["status"] = "completed" if failed == 0 else ("failed" if completed == 0 else "partial")
        task["stage"] = task["status"]


def resolve_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get("IMAGE_STUDIO_API_KEY")
    if not key:
        raise RuntimeError("缺少 API Key，请设置 IMAGE_STUDIO_API_KEY 或在页面输入。")
    return key


def record_id() -> str:
    return f"img_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def extension_from_params(params: ImageParams) -> str:
    fmt = (params.output_format or "png").lower()
    return "jpg" if fmt == "jpeg" else fmt


def payload_to_bytes(payload: client.ImagePayload, timeout: float) -> bytes:
    if payload.kind == "base64":
        return client.decode_base64_image(payload.value)
    response = client.requests.get(payload.value, timeout=timeout)
    response.raise_for_status()
    return response.content


def generate_and_store(req: GenerateImageRequest, task: dict[str, Any] | None = None) -> dict[str, Any]:
    start = time.monotonic()
    preset = models.preset_by_key(req.model_key)
    upstream_model = req.upstream_model or preset.upstream_model
    protocol = req.protocol or preset.protocol
    base_url = req.base_url or default_base_url()
    params = req.params
    count = max(1, params.count)
    concurrency = max(1, min(params.concurrency, count))
    api_key = resolve_api_key(req.api_key)
    rid = record_id()
    results: list[dict[str, Any]] = []
    subtasks = [
        {"index": index, "status": "queued", "progress": 0, "duration_ms": None, "error": None}
        for index in range(1, count + 1)
    ]
    errors: list[str] = []
    request_snapshot: dict[str, Any] = {"endpoint": None, "body": None}

    logger.info(
        "task start id=%s model=%s protocol=%s count=%s concurrency=%s base=%s prompt=%r",
        rid, upstream_model, protocol, count, concurrency, base_url, (req.prompt or "")[:60],
    )

    if task is not None:
        task.update({"status": "running", "progress": 15, "stage": "building_request", "subtasks": subtasks})

    attempts = max(1, int(params.retry_limit) + 1)
    sub_started: dict[int, float] = {}
    ticker_running = {"on": task is not None}

    def progress_ticker() -> None:
        # Upstream image calls block for a long time without reporting real
        # progress, so creep each running subtask toward ~92% by elapsed time.
        while ticker_running["on"]:
            time.sleep(1.0)
            now = time.monotonic()
            changed = False
            for st in subtasks:
                if st["status"] != "running":
                    continue
                started = sub_started.get(st["index"])
                if started is None:
                    continue
                elapsed = now - started
                target = int(20 + 72 * (elapsed / (elapsed + 22)))
                if target > st.get("progress", 20):
                    st["progress"] = target
                    changed = True
            if changed and task is not None:
                update_parent_progress(task)

    def run_one(index: int) -> tuple[int, list[dict[str, Any]], dict[str, Any], str | None]:
        sub_start = time.monotonic()
        sub_started[index] = sub_start
        subtasks[index - 1].update({"status": "running", "progress": 20})
        if task is not None:
            update_parent_progress(task)
        last_error: str | None = None
        try:
            for attempt in range(1, attempts + 1):
                try:
                    child_params = params_dict(params)
                    child_params["count"] = 1
                    images, body, raw, endpoint = client.generate_image(
                        api_key=api_key,
                        base_url=base_url,
                        model=upstream_model,
                        protocol=protocol,
                        prompt=req.prompt,
                        params=child_params,
                        reference_images=req.reference_images,
                    )
                    saved = []
                    for payload in images[:1]:
                        data = payload_to_bytes(payload, params.timeout)
                        saved.append(storage.save_output_bytes(rid, index, data, extension_from_params(params)))
                    duration_ms = int((time.monotonic() - sub_start) * 1000)
                    subtasks[index - 1].update({
                        "status": "completed",
                        "progress": 100,
                        "duration_ms": duration_ms,
                        "error": None,
                    })
                    logger.info("[%s] #%s ok in %sms (attempt %s/%s) %s", rid, index, duration_ms, attempt, attempts, endpoint)
                    return index, saved, {"endpoint": endpoint, "body": body, "raw": raw}, None
                except Exception as exc:
                    last_error = str(exc)
                    logger.warning("[%s] #%s attempt %s/%s failed: %s", rid, index, attempt, attempts, last_error)
                    if attempt < attempts:
                        time.sleep(min(2.0, 0.6 * attempt))
            subtasks[index - 1].update({
                "status": "failed",
                "progress": 100,
                "duration_ms": int((time.monotonic() - sub_start) * 1000),
                "error": {"message": last_error},
            })
            return index, [], {}, last_error
        finally:
            if task is not None:
                update_parent_progress(task)

    ticker_thread: threading.Thread | None = None
    if task is not None:
        ticker_thread = threading.Thread(target=progress_ticker, daemon=True)
        ticker_thread.start()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(run_one, index) for index in range(1, count + 1)]
        for future in as_completed(futures):
            _, saved_items, request_info, error = future.result()
            results.extend(saved_items)
            if request_info and request_snapshot["endpoint"] is None:
                request_snapshot = request_info
            if error:
                errors.append(error)
            if task is not None:
                update_parent_progress(task)

    ticker_running["on"] = False

    if results and errors:
        status = "partial"
    elif results:
        status = "success"
    else:
        status = "failed"

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info("task done id=%s status=%s results=%s errors=%s duration=%sms", rid, status, len(results), len(errors), duration_ms)
    record = {
        "id": rid,
        "status": status,
        "progress": 100,
        "stage": "completed" if status == "success" else status,
        "prompt": req.prompt,
        "model": {
            "key": req.model_key,
            "label": preset.label,
            "upstream_model": upstream_model,
            "protocol": protocol,
        },
        "provider": {"name": "Custom", "base_url": base_url},
        "params": params_dict(params),
        "request": {"endpoint": request_snapshot.get("endpoint"), "body": request_snapshot.get("body")},
        "subtasks": subtasks,
        "results": sorted(results, key=lambda item: item["filename"]),
        "duration_ms": duration_ms,
        "error": {"message": "; ".join(errors)} if errors else None,
    }
    record = storage.append_history(record)
    if task is not None:
        task.update({
            "status": "completed" if status == "success" else status,
            "progress": 100,
            "stage": record["stage"],
            "record": record,
            "error": record["error"],
            "subtasks": subtasks,
        })
    return record


def run_generation_task(req: GenerateImageRequest, task: dict[str, Any]) -> None:
    try:
        generate_and_store(req, task)
    except Exception as exc:
        task.update({
            "status": "failed",
            "progress": 100,
            "stage": "failed",
            "message": "任务失败",
            "record": None,
            "error": {"message": str(exc)},
        })


app = FastAPI(title="Image Studio")


@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    # During local iteration the UI is edited constantly; force the browser to
    # revalidate static assets so changes show on a normal refresh.
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/")
def root():
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Image Studio UI is not built yet.")
    html = index.read_text(encoding="utf-8")
    # Append a mtime-based version to static assets so a normal browser refresh
    # always fetches the latest CSS/JS instead of a cached copy.
    for asset in ("styles.css", "app.js"):
        path = WEB_DIR / asset
        version = int(path.stat().st_mtime) if path.exists() else 0
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
    return HTMLResponse(html)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/api/config")
def api_config():
    return {
        "api_key_present": bool(os.environ.get("IMAGE_STUDIO_API_KEY")),
        "default_base_url": default_base_url(),
        "models": [preset.__dict__ for preset in models.model_presets()],
    }


@app.get("/api/models")
def api_models():
    return [preset.__dict__ for preset in models.model_presets()]


@app.post("/api/models/upstream")
def api_models_upstream(req: UpstreamModelsRequest):
    try:
        api_key = resolve_api_key(req.api_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    base_url = req.base_url or default_base_url()
    try:
        catalog = client.list_upstream_models(api_key, base_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "base_url": client.normalize_base_url(base_url),
        "fetched_at": storage.now_iso(),
        "total": catalog["total"],
        "image_models": catalog["image_models"],
    }


@app.get("/api/history")
def api_history():
    return storage.load_history()


@app.post("/api/generate")
def api_generate(req: GenerateImageRequest):
    task_id = f"task_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    task = create_task_state(task_id, req.params.count, req.params.concurrency)
    with TASK_LOCK:
        TASKS[task_id] = task
    thread = threading.Thread(target=run_generation_task, args=(req, task), daemon=True)
    thread.start()
    return {"task_id": task_id}


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/api/upload")
def api_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.png").suffix.lower() or ".png"
    filename = f"upload_{uuid.uuid4().hex[:10]}{suffix}"
    path = storage.uploads_dir() / filename
    path.write_bytes(file.file.read())
    relative_path = f"uploads/{filename}"
    return {"filename": filename, "relative_path": relative_path, "url": storage.public_data_url(relative_path)}


WEB_DIR.mkdir(parents=True, exist_ok=True)
storage.data_dir().mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
app.mount("/image-studio-data", StaticFiles(directory=str(storage.data_dir())), name="image-studio-data")
