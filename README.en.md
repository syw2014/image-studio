# Image Studio

<p align="center">
  <a href="README.md">简体中文</a> · <b>English</b>
</p>

A **local, one-command** text-to-image workbench. Call image models through any OpenAI-compatible image API or relay endpoint, and keep your prompts, parameters, task state, and generated images entirely on your own machine.

No Docker, no database, no accounts — install the deps, start one process, open your browser.

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-blue">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-grey?logo=fastapi">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green">
</p>

## Why

Many people have one or more OpenAI-compatible image APIs / relay endpoints, but no convenient local frontend that keeps a history: hosted web UIs need a login, need to be online, and the generated images don't live on your machine. Image Studio fixes exactly that — drop in your own key and base URL, run image generation locally, and keep every result on your own computer.

## Features

- 🚀 **One-command local launch** — a single `uvicorn` command, usable straight from the browser. No Docker / database / accounts.
- 🔌 **Provider-agnostic** — works with both the OpenAI Images protocol and the Chat Completions image protocol. Just supply your own API key and base URL (OpenAI, OpenRouter, or any relay).
- 🔎 **Upstream model discovery** — pull the relay's `/v1/models` list with one click, auto-filter image-capable models, and guess the protocol each should use.
- 🎛️ **Presets + overridable model name** — built-in `gpt-image2`, `seedream`, and `nano-banana` presets; the real upstream model name can be overridden by hand.
- 🖼️ **Reference images / image-to-image** — upload reference images for use with the Chat Completions protocol (e.g. nano-banana / Gemini).
- 🧮 **Batch & concurrency** — generate multiple images at once (`count`) with concurrent requests (`concurrency`) and automatic retries on failure.
- 📊 **Task progress** — live task status, per-subtask status, and percentage progress.
- 💾 **Local persistence** — prompts, models, parameters, request summaries, failure reasons, and images are all written to a local `data/` directory. The API key is never written to history.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) (install in one line: `curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
git clone https://github.com/syw2014/image-studio.git
cd image-studio

cp .env.example .env          # fill in your API key and base URL (optional)
uv run image-studio
```

`uv run` **creates a virtual environment (`.venv`), installs dependencies, and starts the server** — without ever touching your system Python. On macOS / Linux you can also run `./start.sh` (which just calls `uv run`).

Open in your browser:

```text
http://127.0.0.1:8010
```

Common options:

```bash
uv run image-studio --port 8020     # custom port
uv run image-studio --host 0.0.0.0  # listen on all interfaces
uv run image-studio --reload        # auto-reload on code changes (dev)
```

> You can also skip `.env` and enter the API key and base URL directly in the UI.

<details>
<summary>Without uv (manual venv + pip)</summary>

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app:app --reload --port 8010
```

</details>

## Environment variables

`.env` is read first, then the current shell environment.

```bash
# API key for your image provider / relay endpoint
IMAGE_STUDIO_API_KEY=sk-...

# Base URL of the image API (OpenAI-compatible or a relay)
# e.g. https://api.openai.com | https://openrouter.ai/api | your own relay
IMAGE_STUDIO_API_BASE=https://api.openai.com

# Leave empty to store data under ./data
IMAGE_STUDIO_DATA_DIR=
```

Resolution order: **UI input > `.env` / environment variables > built-in defaults**. The backend never writes the API key into history records.

## Built-in model presets

| Preset key | Default upstream model | Protocol | Notes |
| --- | --- | --- | --- |
| `gpt-image2` | `gpt-image-2` | `openai-images` | Good for posters, text, and complex instructions |
| `seedream` | `seedream` | `openai-images` | Adjust the real model name to match your relay |
| `nano-banana` | `gemini-3-pro-image-preview` | `chat-completions` | Supports reference images and `imageConfig` (aspect ratio / size) |

Presets are just defaults: the real upstream model name and protocol can both be overridden in the UI, so wiring up a new model usually needs no code changes.

## How it works

```text
Browser (web/) ──HTTP──> FastAPI (app.py) ──> client.py ──> your relay / image API
                              │
                              └──> storage.py ──> local data/ (history, images, uploads, logs)
```

- After you submit, the backend creates an **in-memory task** and returns a `task_id` immediately, then generates `count` images across `concurrency` workers (with retries) in a background thread while the frontend polls for progress.
- `client.py` builds the request body per protocol: `openai-images` hits `/v1/images/generations`, `chat-completions` hits `/v1/chat/completions`. Relay responses vary wildly, so it recursively extracts base64 / data-URIs / image URLs from the returned JSON.
- Results are written to `data/`, and history is appended newest-first to `history.json`. **The API key is never written to any history record or request snapshot.**

## Local data

Default directory (created at runtime, excluded via `.gitignore`):

```text
data/
  history.json     # generation history (newest first)
  outputs/         # generated images
  uploads/         # uploaded reference images
  logs/            # run logs
```

Point the data directory elsewhere with `IMAGE_STUDIO_DATA_DIR`.

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/config` | Read default config and model presets |
| GET | `/api/models` | Read the built-in model preset list |
| POST | `/api/models/upstream` | Fetch the relay's `/v1/models` and filter image models |
| GET | `/api/history` | Read local history |
| POST | `/api/upload` | Upload a reference image locally |
| POST | `/api/generate` | Create a generation task, returns `task_id` |
| GET | `/api/tasks/{task_id}` | Poll task status, progress, and the final record |

Core fields of `POST /api/generate`:

```json
{
  "prompt": "A hyper-realistic K-pop style girl, 9:16",
  "api_key": "sk-...",
  "base_url": "https://api.openai.com",
  "model_key": "gpt-image2",
  "upstream_model": "gpt-image-2",
  "protocol": "openai-images",
  "params": {
    "count": 4,
    "concurrency": 2,
    "size": "1024x1024",
    "quality": "auto",
    "output_format": "png"
  },
  "reference_images": []
}
```

## Project structure

```text
app.py        # FastAPI app, endpoints, generation-task orchestration
client.py     # Upstream HTTP: build request bodies, call, extract images, discover upstream models
models.py     # Built-in model presets (key → upstream model + protocol + default params)
storage.py    # Local persistence (history.json / outputs / uploads / logs)
web/          # Plain HTML/CSS/JS frontend (no build step)
tests/        # pytest tests
```

## Tests

```bash
uv run pytest        # without uv: just `pytest` inside the activated venv
```

## Contributing

Issues and PRs are welcome. Suggested flow:

1. Open an issue to discuss direction before large changes.
2. Fork and branch, then `uv sync --extra dev` for dev dependencies.
3. Run `uv run pytest` and verify frontend changes manually in the browser.
4. Open a PR describing what changed and why.

Please respect the project's core constraints: **local-only launch, no Docker / database / account system, and stay provider-agnostic.**

## License

[MIT](LICENSE)
