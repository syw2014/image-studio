# Image Studio

一个**本地一键启动**的生图工作台。通过任意 OpenAI 兼容的图像 API 或中转站调用图像模型，把提示词、参数、任务状态和图片结果全部保存在本地。

无需 Docker、无需数据库、无需账号体系 —— 装好依赖、起一个进程、打开浏览器即可使用。

## 特性

- 🚀 **一键本地启动**：一条 `uvicorn` 命令拉起，浏览器打开就能用。
- 🔌 **provider 无关**：兼容 OpenAI Images 协议和 Chat Completions 图像协议，填入自己的 API Key 和 Base URL 即可（OpenAI、OpenRouter 或任意中转站）。
- 🎛️ **预设 + 可覆盖模型名**：内置 `gpt-image2`、`seedream`、`nano-banana` 预设，上游真实模型名可手动覆盖。
- 🧮 **批量与并发**：支持一次生成多张（`count`）和并发请求（`concurrency`）。
- 📊 **任务进度**：实时显示任务状态、子任务状态和百分比进度。
- 💾 **本地留存**：提示词、模型、参数、请求摘要、失败原因和图片全部写入本地 `data/`，API Key 不会落盘到历史记录。

## 快速开始

需要 Python 3.11+。

```bash
git clone https://github.com/syw2014/image-studio.git
cd image-studio

pip install -e ".[dev]"
cp .env.example .env          # 填入你的 API Key 和 Base URL
uvicorn app:app --reload --port 8010
```

浏览器打开：

```text
http://127.0.0.1:8010
```

> 也可以不写 `.env`，直接在页面里临时输入 API Key 和 Base URL。

## 环境变量

优先读取 `.env`，也会读取当前 shell 环境。

```bash
# 你的图像 provider / 中转站的 API Key
IMAGE_STUDIO_API_KEY=sk-...

# 图像 API 的 Base URL（OpenAI 兼容或中转站）
# 例如：https://api.openai.com | https://openrouter.ai/api | 你自己的中转站
IMAGE_STUDIO_API_BASE=https://api.openai.com

# 留空时默认使用 ./data
IMAGE_STUDIO_DATA_DIR=
```

后端不会把 API Key 写入历史记录。

## 本地数据

默认目录（运行时生成，已在 `.gitignore` 中排除）：

```text
data/
  history.json     # 生成历史（新记录在最前）
  outputs/         # 生成的图片
  uploads/         # 上传的参考图
  logs/            # 运行日志
```

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/config` | 读取默认配置和模型预设 |
| GET | `/api/models` | 读取模型列表 |
| GET | `/api/history` | 读取本地历史 |
| POST | `/api/upload` | 上传参考图到本地 |
| POST | `/api/generate` | 创建生图任务，返回 `task_id` |
| GET | `/api/tasks/{task_id}` | 轮询任务状态、进度和最终记录 |

`POST /api/generate` 核心字段：

```json
{
  "prompt": "一位韩系女团风格女孩，9:16，超写实",
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

## 测试

```bash
pytest
```

## License

[MIT](LICENSE)
