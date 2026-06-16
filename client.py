from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

import requests

try:
    from image_studio import models
except ModuleNotFoundError:  # Standalone copy: `cd image_studio && uvicorn app:app`
    import models  # type: ignore


DEFAULT_BASE_URL = ""
DATA_URI_RE = re.compile(r"data:image/[^;]+;base64,([A-Za-z0-9+/=\n\r]+)")


@dataclass(frozen=True)
class ImagePayload:
    kind: str
    value: str


def model_presets() -> list[dict[str, str]]:
    return [preset.__dict__ for preset in models.model_presets()]


def preset_by_key(key: str) -> dict[str, str]:
    return models.preset_by_key(key).__dict__


def normalize_base_url(base_url: str | None) -> str:
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }


def build_openai_images_body(prompt: str, model: str, params: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": int(params.get("count") or 1),
    }
    for src, dst in (
        ("size", "size"),
        ("quality", "quality"),
        ("output_format", "output_format"),
        ("negative_prompt", "negative_prompt"),
        ("seed", "seed"),
    ):
        value = params.get(src)
        if value not in (None, ""):
            body[dst] = value
    return body


def build_chat_body(prompt: str, model: str, params: dict[str, Any], reference_images: list[str]) -> dict[str, Any]:
    image_config = {}
    if params.get("aspect_ratio"):
        image_config["aspectRatio"] = params["aspect_ratio"]
    if params.get("image_size"):
        image_config["imageSize"] = params["image_size"]

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for url in reference_images:
        content.append({"type": "image_url", "image_url": {"url": url}})

    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": float(params.get("temperature") or 0.8),
        "max_tokens": int(params.get("max_tokens") or 4096),
    }
    if image_config:
        body["extra_body"] = {"imageConfig": image_config}
        body["messages"].insert(0, {"role": "system", "content": json.dumps({"imageConfig": image_config})})
    return body


def raise_http_error(response: requests.Response, endpoint: str, model: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = getattr(response, "text", "") or ""
        status = getattr(response, "status_code", "unknown")
        raise RuntimeError(f"HTTP {status} calling {endpoint} model={model}: {body[:2000]}") from exc


def collect_images(value: Any, out: list[ImagePayload]) -> None:
    if not value:
        return
    if isinstance(value, str):
        match = DATA_URI_RE.search(value)
        if match:
            out.append(ImagePayload("base64", match.group(1).replace("\n", "").replace("\r", "")))
        elif value.startswith("http://") or value.startswith("https://"):
            out.append(ImagePayload("url", value))
        elif len(value) > 120 and re.match(r"^[A-Za-z0-9+/]+={0,2}$", value[:160]):
            out.append(ImagePayload("base64", value))
        return
    if isinstance(value, list):
        for item in value:
            collect_images(item, out)
        return
    if not isinstance(value, dict):
        return

    for key in ("b64_json", "base64", "image_base64"):
        if isinstance(value.get(key), str):
            out.append(ImagePayload("base64", value[key].replace("\n", "").replace("\r", "")))
    if isinstance(value.get("result"), str):
        collect_images(value["result"], out)
    if isinstance(value.get("image_url"), dict):
        collect_images(value["image_url"].get("url"), out)
    for key in ("url", "dataUrl", "imageUrl"):
        collect_images(value.get(key), out)
    for nested in value.values():
        collect_images(nested, out)


def extract_images(data: Any) -> list[ImagePayload]:
    images: list[ImagePayload] = []
    collect_images(data, images)
    return images


def generate_image(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    protocol: str,
    prompt: str,
    params: dict[str, Any],
    reference_images: list[str] | None = None,
) -> tuple[list[ImagePayload], dict[str, Any], dict[str, Any], str]:
    base = normalize_base_url(base_url)
    reference_images = reference_images or []
    if protocol in ("chat", "chat-completions"):
        endpoint = f"{base}/v1/chat/completions"
        body = build_chat_body(prompt, model, params, reference_images)
    else:
        endpoint = f"{base}/v1/images/generations"
        body = build_openai_images_body(prompt, model, params)

    response = requests.post(endpoint, headers=headers(api_key), json=body, timeout=float(params.get("timeout") or 180))
    raise_http_error(response, endpoint, model)
    data = response.json()
    images = extract_images(data)
    if not images:
        raise RuntimeError(f"No image found in response: {json.dumps(data, ensure_ascii=False)[:2000]}")
    return images, body, data, endpoint


def decode_base64_image(value: str) -> bytes:
    return base64.b64decode(value)


# --- Upstream model discovery -------------------------------------------------

# Substrings that identify an image-capable model id on most relay gateways.
IMAGE_MODEL_HINTS = (
    "image",
    "dall-e",
    "dalle",
    "gpt-image",
    "seedream",
    "seedance",
    "flux",
    "stable-diffusion",
    "sd3",
    "sdxl",
    "midjourney",
    "nano-banana",
    "banana",
    "kolors",
    "wanx",
    "cogview",
    "imagen",
    "ideogram",
    "recraft",
    "playground",
    "grok-2-image",
)

# Models that should be driven through the chat-completions image protocol.
CHAT_PROTOCOL_HINTS = ("gemini", "nano-banana", "banana", "grok")


def is_image_model(model_id: str) -> bool:
    lowered = model_id.lower()
    if "embedding" in lowered or "whisper" in lowered or "tts" in lowered:
        return False
    return any(hint in lowered for hint in IMAGE_MODEL_HINTS)


def guess_protocol(model_id: str) -> str:
    lowered = model_id.lower()
    return "chat-completions" if any(hint in lowered for hint in CHAT_PROTOCOL_HINTS) else "openai-images"


def list_upstream_models(api_key: str, base_url: str | None, timeout: float = 30) -> dict[str, Any]:
    """Fetch the upstream model catalog and surface the image-capable subset.

    Returns a dict with the filtered image models (id + guessed protocol),
    the raw total count, and the endpoint used. Raises on transport/HTTP errors.
    """
    base = normalize_base_url(base_url)
    endpoint = f"{base}/v1/models"
    response = requests.get(endpoint, headers=headers(api_key), timeout=timeout)
    raise_http_error(response, endpoint, "models")
    data = response.json()
    raw = data.get("data") if isinstance(data, dict) else data
    raw = raw if isinstance(raw, list) else []

    ids: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            model_id = item.get("id") or item.get("model") or item.get("name")
        else:
            model_id = item
        if isinstance(model_id, str) and model_id.strip():
            ids.append(model_id.strip())

    seen: set[str] = set()
    image_models: list[dict[str, str]] = []
    for model_id in ids:
        if model_id in seen:
            continue
        seen.add(model_id)
        if is_image_model(model_id):
            image_models.append({"id": model_id, "protocol": guess_protocol(model_id)})

    image_models.sort(key=lambda m: m["id"])
    return {
        "endpoint": endpoint,
        "total": len(ids),
        "image_models": image_models,
    }
