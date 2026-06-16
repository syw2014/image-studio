from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelPreset:
    key: str
    label: str
    upstream_model: str
    protocol: str
    description: str
    defaults: dict[str, Any] = field(default_factory=dict)


def model_presets() -> list[ModelPreset]:
    return [
        ModelPreset(
            key="gpt-image2",
            label="gpt-image2",
            upstream_model="gpt-image-2",
            protocol="openai-images",
            description="GPT Image 2 接口，适合海报、文字和复杂指令。",
            defaults={"size": "1024x1024", "quality": "auto", "output_format": "png", "count": 1, "concurrency": 1},
        ),
        ModelPreset(
            key="seedream",
            label="seedream",
            upstream_model="seedream",
            protocol="openai-images",
            description="Seedream 预设，真实模型名可按中转站要求手动修改。",
            defaults={"size": "1024x1024", "quality": "auto", "output_format": "png", "count": 1, "concurrency": 1},
        ),
        ModelPreset(
            key="nano-banana",
            label="nano-banana",
            upstream_model="gemini-3-pro-image-preview",
            protocol="chat-completions",
            description="Nano Banana / Gemini 图像模型，支持参考图和 imageConfig。",
            defaults={"aspect_ratio": "9:16", "image_size": "2K", "count": 1, "concurrency": 1},
        ),
    ]


def preset_by_key(key: str) -> ModelPreset:
    for preset in model_presets():
        if preset.key == key:
            return preset
    return model_presets()[0]
