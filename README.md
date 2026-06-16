# Image Studio

<p align="center">
  <b>简体中文</b> · <a href="README.en.md">English</a>
</p>

一个**本地一键启动**的文生图工作台。通过任意 OpenAI 兼容的图像 API 或中转站调用图像模型，把提示词、参数、任务状态和图片结果全部保存在本地。

无需 Docker、无需数据库、无需账号体系 —— 装好依赖、起一个进程、打开浏览器即可使用。

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-blue">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-grey?logo=fastapi">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green">
</p>

## 为什么用它

很多人手上有一个或多个 OpenAI 兼容的图像 API / 中转站，却没有一个顺手、可留存的本地前端：网页版要登录、要联网、生成的图也不在自己手里。Image Studio 想解决的就是这件事 —— 填上你自己的 Key 和 Base URL，在本地把生图这件事跑起来，结果全部留在你自己机器上。

## 特性

- 🚀 **一键本地启动**：一条 `uvicorn` 命令拉起，浏览器打开就能用，不依赖 Docker / 数据库 / 账号。
- 🔌 **provider 无关**：兼容 OpenAI Images 协议和 Chat Completions 图像协议，填入自己的 API Key 和 Base URL 即可（OpenAI、OpenRouter 或任意中转站）。
- 🔎 **上游模型发现**：一键拉取中转站 `/v1/models` 列表，自动筛出图像模型并猜测应使用的协议。
- 🎛️ **预设 + 可覆盖模型名**：内置 `gpt-image2`、`seedream`、`nano-banana` 预设，上游真实模型名可手动覆盖。
- 🖼️ **参考图 / 图生图**：支持上传参考图，配合 Chat Completions 协议（如 nano-banana / Gemini）使用。
- 🧮 **批量与并发**：支持一次生成多张（`count`）和并发请求（`concurrency`），失败自动重试。
- 📊 **任务进度**：实时显示任务状态、子任务状态和百分比进度。
- 💾 **本地留存**：提示词、模型、参数、请求摘要、失败原因和图片全部写入本地 `data/`，API Key 不会落盘到历史记录。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)（没有就一行装上：`curl -LsSf https://astral.sh/uv/install.sh | sh`）。

```bash
git clone https://github.com/syw2014/image-studio.git
cd image-studio

cp .env.example .env          # 填入你的 API Key 和 Base URL（可选）
uv run image-studio
```

`uv run` 会**自动创建虚拟环境（`.venv`）、安装依赖、再启动服务**，全程不碰你的系统 Python 环境。macOS / Linux 也可以直接 `./start.sh`（内部就是调 `uv run`）。

浏览器打开：

```text
http://127.0.0.1:8010
```

常用参数：

```bash
uv run image-studio --port 8020     # 换端口
uv run image-studio --host 0.0.0.0  # 监听所有网卡
uv run image-studio --reload        # 改代码自动重载（开发用）
```

> 也可以不写 `.env`，直接在页面里临时输入 API Key 和 Base URL。

<details>
<summary>不用 uv（自建 venv + pip）</summary>

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app:app --reload --port 8010
```

</details>

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

配置优先级：**页面输入 > `.env` / 环境变量 > 内置默认值**。后端不会把 API Key 写入历史记录。

## 内置模型预设

| 预设 key | 默认上游模型 | 协议 | 说明 |
| --- | --- | --- | --- |
| `gpt-image2` | `gpt-image-2` | `openai-images` | 适合海报、文字和复杂指令 |
| `seedream` | `seedream` | `openai-images` | 真实模型名可按中转站要求手动修改 |
| `nano-banana` | `gemini-3-pro-image-preview` | `chat-completions` | 支持参考图和 `imageConfig`（宽高比 / 尺寸） |

预设只是默认值：上游真实模型名和协议都可以在页面上覆盖，所以接入新模型通常不需要改代码。

## 工作原理

```text
浏览器 (web/) ──HTTP──> FastAPI (app.py) ──> client.py ──> 你的中转站 / 图像 API
                              │
                              └──> storage.py ──> 本地 data/（历史、图片、上传、日志）
```

- 提交生图后，后端创建一个**内存任务**并立即返回 `task_id`，在后台线程里把 `count` 张图按 `concurrency` 并发执行（带重试），前端轮询任务进度。
- `client.py` 按协议拼请求体：`openai-images` 走 `/v1/images/generations`，`chat-completions` 走 `/v1/chat/completions`。响应结构千差万别，因此会递归从返回 JSON 里抽取 base64 / data-URI / 图片 URL。
- 结果写入 `data/`，历史以最新在前的方式追加到 `history.json`。**API Key 不会写入任何历史记录或请求快照。**

## 本地数据

默认目录（运行时生成，已在 `.gitignore` 中排除）：

```text
data/
  history.json     # 生成历史（新记录在最前）
  outputs/         # 生成的图片
  uploads/         # 上传的参考图
  logs/            # 运行日志
```

通过 `IMAGE_STUDIO_DATA_DIR` 可以把数据目录指到别处。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/config` | 读取默认配置和模型预设 |
| GET | `/api/models` | 读取内置模型预设列表 |
| POST | `/api/models/upstream` | 拉取中转站 `/v1/models` 并筛出图像模型 |
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

## 项目结构

```text
app.py        # FastAPI 应用、接口、生图任务编排
client.py     # 上游 HTTP：拼请求体、调用、从响应里抽取图片、发现上游模型
models.py     # 内置模型预设（key → 上游模型 + 协议 + 默认参数）
storage.py    # 本地持久化（history.json / outputs / uploads / logs）
web/          # 纯 HTML/CSS/JS 前端（无构建步骤）
tests/        # pytest 测试
```

## 测试

```bash
uv run pytest        # 不用 uv 时：在激活的 venv 里直接 pytest
```

## 参与贡献

欢迎 issue 和 PR。建议流程：

1. 提交较大改动前，先开 issue 聊一下方向。
2. Fork 并新建分支，`uv sync --extra dev` 装好开发依赖。
3. 改完跑 `uv run pytest` 确认通过，前端改动请在浏览器里手动验证。
4. 发 PR，说明改了什么、为什么。

请守住项目的核心约束：**纯本地启动、不引入 Docker / 数据库 / 账号体系、保持 provider 无关**。

## License

[MIT](LICENSE)
