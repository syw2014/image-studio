#!/usr/bin/env python3
"""Image Studio launcher / console entry point.

Dependencies and the virtual environment are managed by uv, so this module
only parses CLI options and starts the server. The recommended way to run it
is `uv run image-studio` (uv creates `.venv`, installs deps, then launches).

Usage:
    uv run image-studio                 # start on 127.0.0.1:8010
    uv run image-studio --port 8020     # custom port
    uv run image-studio --host 0.0.0.0  # listen on all interfaces
    uv run image-studio --reload        # auto-reload on code changes (dev)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="image-studio", description="Start the Image Studio local server.")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8010, help="bind port (default: 8010)")
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "[image-studio] dependencies are not installed.\n"
            "Run via uv:  uv run image-studio\n"
            "or install first:  uv sync   (or  pip install -e .  inside a venv)",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(f"[image-studio] starting on http://{args.host}:{args.port}", flush=True)
    uvicorn.run("app:app", host=args.host, port=args.port, reload=args.reload, app_dir=str(PROJECT_DIR))


if __name__ == "__main__":
    main()
