import base64
import importlib
import json
import threading
import time
from pathlib import Path


def test_model_presets_include_requested_models():
    models = importlib.import_module("models")

    keys = {preset.key for preset in models.model_presets()}

    assert {"gpt-image2", "seedream", "nano-banana"} <= keys


def test_seedream_upstream_model_can_be_overridden():
    client = importlib.import_module("client")

    body = client.build_openai_images_body(
        prompt="生成一张图",
        model="custom-seedream-model",
        params={
            "size": "1024x1024",
            "quality": "auto",
            "output_format": "png",
        },
    )

    assert body["model"] == "custom-seedream-model"
    assert body["prompt"] == "生成一张图"
    assert body["n"] == 1
    assert body["size"] == "1024x1024"
    assert body["quality"] == "auto"
    assert body["output_format"] == "png"


def test_chat_body_includes_image_config_and_references():
    client = importlib.import_module("client")

    body = client.build_chat_body(
        prompt="生成一张图",
        model="gemini-3-pro-image-preview",
        params={"aspect_ratio": "9:16", "image_size": "2K", "temperature": 0.7, "max_tokens": 2048},
        reference_images=["data:image/png;base64,aGVsbG8="],
    )

    assert body["model"] == "gemini-3-pro-image-preview"
    assert body["extra_body"]["imageConfig"] == {"aspectRatio": "9:16", "imageSize": "2K"}
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 2048
    assert body["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_extracts_url_and_base64_images():
    client = importlib.import_module("client")

    url_image = client.extract_images({"data": [{"url": "https://cdn.example.com/a.png"}]})[0]
    b64_image = client.extract_images({"data": [{"b64_json": "aGVsbG8="}]})[0]

    assert url_image.kind == "url"
    assert url_image.value == "https://cdn.example.com/a.png"
    assert b64_image.kind == "base64"
    assert b64_image.value == "aGVsbG8="


def test_storage_appends_history_under_image_studio_data(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_DATA_DIR", str(tmp_path))
    storage = importlib.reload(importlib.import_module("storage"))

    record = storage.append_history({
        "id": "rec_1",
        "prompt": "生成一张图",
        "params": {"count": 4},
        "results": [{"relative_path": "outputs/rec_1.png"}],
    })

    history_file = tmp_path / "history.json"
    assert history_file.exists()
    assert record["prompt"] == "生成一张图"
    assert json.loads(history_file.read_text(encoding="utf-8"))[0]["params"]["count"] == 4


def test_save_output_bytes_returns_preview_url(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_DATA_DIR", str(tmp_path))
    storage = importlib.reload(importlib.import_module("storage"))

    result = storage.save_output_bytes("rec_1", 1, b"png-bytes", "png")

    assert result["relative_path"] == "outputs/rec_1_1.png"
    assert result["url"] == "/image-studio-data/outputs/rec_1_1.png"
    assert (tmp_path / result["relative_path"]).read_bytes() == b"png-bytes"


def test_task_progress_aggregates_subtasks():
    app_module = importlib.reload(importlib.import_module("app"))
    task = app_module.create_task_state("task_1", count=4, concurrency=2)

    task["subtasks"][0]["status"] = "completed"
    task["subtasks"][0]["progress"] = 100
    task["subtasks"][1]["status"] = "running"
    task["subtasks"][1]["progress"] = 60
    app_module.update_parent_progress(task)

    assert task["progress"] == 40
    assert task["message"] == "1/4 完成 · 并发 2"


def test_generate_and_store_creates_count_results_with_concurrency(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_DATA_DIR", str(tmp_path))
    app_module = importlib.reload(importlib.import_module("app"))
    client = importlib.import_module("client")

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_generate_image(**kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return (
            [client.ImagePayload("base64", base64.b64encode(b"png").decode())],
            {"model": kwargs["model"], "prompt": kwargs["prompt"], "n": 1},
            {"data": [{"b64_json": base64.b64encode(b"png").decode()}]},
            "https://api.example.com/v1/images/generations",
        )

    monkeypatch.setattr(app_module.client, "generate_image", fake_generate_image)

    result = app_module.generate_and_store(app_module.GenerateImageRequest(
        prompt="生成一张图",
        api_key="sk-test",
        base_url="https://api.example.com",
        model_key="gpt-image2",
        params=app_module.ImageParams(count=4, concurrency=2, output_format="png"),
    ))

    assert result["status"] == "success"
    assert result["prompt"] == "生成一张图"
    assert result["params"]["count"] == 4
    assert result["params"]["concurrency"] == 2
    assert len(result["subtasks"]) == 4
    assert len(result["results"]) == 4
    assert max_active <= 2
    assert all((tmp_path / item["relative_path"]).exists() for item in result["results"])


def test_generate_and_store_records_partial_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_DATA_DIR", str(tmp_path))
    app_module = importlib.reload(importlib.import_module("app"))
    client = importlib.import_module("client")
    calls = {"count": 0}

    def fake_generate_image(**kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("upstream failed")
        return (
            [client.ImagePayload("base64", base64.b64encode(b"png").decode())],
            {"model": kwargs["model"], "prompt": kwargs["prompt"], "n": 1},
            {"data": [{"b64_json": base64.b64encode(b"png").decode()}]},
            "https://api.example.com/v1/images/generations",
        )

    monkeypatch.setattr(app_module.client, "generate_image", fake_generate_image)

    result = app_module.generate_and_store(app_module.GenerateImageRequest(
        prompt="生成一张图",
        api_key="sk-test",
        model_key="gpt-image2",
        params=app_module.ImageParams(count=3, concurrency=2, output_format="png", retry_limit=0),
    ))

    assert result["status"] == "partial"
    assert len(result["results"]) == 2
    assert len([item for item in result["subtasks"] if item["status"] == "failed"]) == 1
    assert "upstream failed" in result["error"]["message"]


def test_generate_and_store_retries_transient_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_STUDIO_DATA_DIR", str(tmp_path))
    app_module = importlib.reload(importlib.import_module("app"))
    client = importlib.import_module("client")
    monkeypatch.setattr(app_module.time, "sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_generate_image(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Response ended prematurely")
        return (
            [client.ImagePayload("base64", base64.b64encode(b"png").decode())],
            {"model": kwargs["model"], "prompt": kwargs["prompt"], "n": 1},
            {"data": [{"b64_json": base64.b64encode(b"png").decode()}]},
            "https://api.example.com/v1/images/generations",
        )

    monkeypatch.setattr(app_module.client, "generate_image", fake_generate_image)

    result = app_module.generate_and_store(app_module.GenerateImageRequest(
        prompt="生成一张图",
        api_key="sk-test",
        model_key="gpt-image2",
        params=app_module.ImageParams(count=1, concurrency=1, output_format="png", retry_limit=2),
    ))

    assert result["status"] == "success"
    assert len(result["results"]) == 1
    assert calls["n"] == 2  # first attempt failed, retried and succeeded
