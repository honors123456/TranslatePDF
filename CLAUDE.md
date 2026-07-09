# TranslationPDF

自用的 PDF 翻译工具站，模仿沉浸式翻译（app.immersivetranslate.com）的 PDF 翻译功能。

## 项目定位

- **自用**，不做用户账号、计费、多租户。
- BYOK 模式：API Key 只存浏览器 localStorage，随请求传后端，仅内存使用，**不写库、不写日志、不进代码**。

## 技术栈

- 后端：Python 3.12 + FastAPI，PDF 翻译管线基于 `pdf2zh-next`（BabelDOC 官方调用入口），API 用 `high_level.do_translate_async_stream`。
- 前端：Next.js + TypeScript + Tailwind，pdf.js 在线预览。
- 任务：FastAPI BackgroundTask + SSE 推进度，任务状态内存态，不上 Celery/Redis。
- 部署：本机运行，`start.bat` 一键启动前后端（不用 Docker，2026-07-09 决定）。

## 目录结构

- `backend/` — FastAPI 服务，Python venv 在 `backend/.venv`。
- `frontend/` — Next.js 应用。
- `scripts/` — 独立脚本（管线验证等）。
- `data/` — 运行时上传/输出文件（git 忽略）。

## 翻译引擎接入顺序

DeepSeek（OpenAI 兼容）→ 自定义 OpenAI 兼容端点 → Claude → Gemini。统一走 pdf2zh-next 的翻译服务配置层。

## 约定

- 中文注释可用于业务逻辑说明；代码、变量、文件名英文。
- 测试 Key 通过环境变量传入（如 `DEEPSEEK_API_KEY`），不硬编码。
- 每完成一个阶段同步更新 `ROADMAP.md`。
