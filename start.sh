#!/usr/bin/env bash
# Image Studio launcher for macOS / Linux.
# Uses uv to manage a virtual environment + dependencies, then starts the server.
# All arguments are forwarded, e.g. ./start.sh --port 8020
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "[image-studio] 'uv' is required but was not found on PATH." >&2
  echo "[image-studio] Install it from https://docs.astral.sh/uv/ then re-run ./start.sh" >&2
  echo "[image-studio]   macOS/Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

exec uv run image-studio "$@"
