from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = PACKAGE_DIR / "data"


def data_dir() -> Path:
    configured = os.environ.get("IMAGE_STUDIO_DATA_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DATA_DIR.resolve()


def outputs_dir() -> Path:
    path = data_dir() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def uploads_dir() -> Path:
    path = data_dir() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def history_file() -> Path:
    path = data_dir() / "history.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_history() -> list[dict[str, Any]]:
    path = history_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_history(records: list[dict[str, Any]]) -> None:
    history_file().write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def append_history(record: dict[str, Any]) -> dict[str, Any]:
    record = {"created_at": now_iso(), **record}
    records = load_history()
    records.insert(0, record)
    save_history(records)
    return record


def public_data_url(relative_path: str) -> str:
    return f"/image-studio-data/{relative_path.lstrip('/')}"


def save_output_bytes(record_id: str, index: int, data: bytes, ext: str) -> dict[str, Any]:
    safe_ext = ext.lower().lstrip(".") or "png"
    filename = f"{record_id}_{index}.{safe_ext}"
    relative_path = f"outputs/{filename}"
    path = outputs_dir() / filename
    path.write_bytes(data)
    return {
        "filename": filename,
        "relative_path": relative_path,
        "url": public_data_url(relative_path),
        "width": None,
        "height": None,
    }
