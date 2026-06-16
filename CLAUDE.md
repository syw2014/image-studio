# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local, single-process image-generation workbench. A FastAPI backend proxies any OpenAI-compatible image API (or relay/中转站), and a vanilla-JS frontend (`web/`) is served from the same process. Prompts, params, task state, and generated images are all persisted to a local `data/` directory. No Docker, no database, no accounts.

## Commands

Dependencies and the venv are managed by **uv**. The `image-studio` console script is the entry point (defined in `[project.scripts]` → `run:main`).

```bash
cp .env.example .env                          # configure API key + base URL (optional; can also enter in UI)
uv run image-studio                           # create .venv, install deps, start; open http://127.0.0.1:8010
uv run image-studio --port 8020 --reload      # options forwarded to run.py (host/port/reload)
./start.sh                                     # macOS/Linux convenience wrapper around `uv run image-studio`

uv sync --extra dev                           # install incl. dev deps (pytest)
uv run pytest                                 # run all tests
uv run pytest tests/test_image_studio.py::test_chat_body_includes_image_config_and_references  # single test
```

uv installs the project **editable**, which matters: `app.py`/`storage.py` resolve `web/` and `data/` relative to `__file__`, so a non-editable install would break the UI and local storage. There is no separate frontend build step or linter — `web/` is plain HTML/CSS/JS served as static files.

## Architecture

Four top-level modules (flat package — note `pyproject.toml` lists them as `py-modules`, not a package directory):

- **`app.py`** — FastAPI app, request/response models, and the generation orchestrator. Serves the UI at `/`, the JSON API under `/api/*`, static assets under `/static/`, and generated files under `/image-studio-data/`.
- **`client.py`** — All upstream HTTP. Builds request bodies for the two protocols, POSTs to the provider, and extracts images from arbitrarily-shaped responses. Also discovers/filters image-capable models from `/v1/models`.
- **`models.py`** — Built-in `ModelPreset`s (`gpt-image2`, `seedream`, `nano-banana`). Each maps a UI key → upstream model name + protocol + default params.
- **`storage.py`** — Local persistence: `data/history.json`, `data/outputs/`, `data/uploads/`, `data/logs/`. Resolves the data dir from `IMAGE_STUDIO_DATA_DIR`.

### Two upstream protocols

`client.generate_image` branches on `protocol`:
- `openai-images` → `POST {base}/v1/images/generations` (DALL·E / gpt-image style).
- `chat` / `chat-completions` → `POST {base}/v1/chat/completions`, where reference images go in message content and `imageConfig` (aspect ratio, image size) is injected via both `extra_body` and a system message. Used for Gemini / nano-banana style models.

`base_url` is normalized (`/v1` suffix stripped) before endpoints are appended. Responses vary wildly across relays, so `collect_images` recursively walks the JSON looking for base64 fields, data-URIs, and image URLs.

### Async task model

Generation is **not** synchronous to the HTTP request:
1. `POST /api/generate` creates an in-memory task in the module-global `TASKS` dict (guarded by `TASK_LOCK`), spawns a daemon thread, and immediately returns `{task_id}`.
2. The thread runs `generate_and_store`, which fans out `count` subtasks across a `ThreadPoolExecutor` of size `concurrency`, each with retry (`retry_limit`).
3. The frontend polls `GET /api/tasks/{task_id}` for status/progress.

Because upstream image calls block for a long time with no real progress signal, a **progress-ticker thread** creeps each running subtask's progress toward ~92% by elapsed time. Real progress only jumps to 100% on completion. `TASKS` is in-memory only — task state is lost on restart, but finished runs are persisted to `history.json`.

### Persistence model

- `history.json` is a JSON array, newest-first (`append_history` inserts at index 0).
- The **API key is deliberately never written** into history records or request snapshots — only prompt, model, params, endpoint, and result paths are stored.
- Generated images and uploads are written to disk and referenced by relative URL under `/image-studio-data/`.

## Conventions

- **Dual import pattern:** every module starts with `try: from image_studio import ... except ModuleNotFoundError: import ...`. This lets the same files run both as an installed package and as a standalone checkout (`uvicorn app:app` from the repo root). Preserve this when adding cross-module imports.
- **Config resolution order:** API key and base URL come from the request body first, then env (`IMAGE_STUDIO_API_KEY` / `IMAGE_STUDIO_API_BASE`), then the client default. `resolve_api_key` raises if neither request nor env supplies a key.
- **User-facing strings are in Chinese** (log messages, error text, UI). Match the surrounding language when editing.
- **Static asset cache-busting:** `app.py` rewrites `/static/styles.css` and `/static/app.js` with an `mtime` query param and sets `no-cache` on `/static/*`, so plain browser refreshes pick up `web/` edits during iteration.
