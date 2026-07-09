# ROADMAP

## 当前阶段

MVP 完成，待浏览器人工点验。

## 已完成

- 2026-07-09 方案确定：FastAPI + Next.js，核心管线 pdf2zh-next（BabelDOC 官方入口），BYOK，自用定位（详见 CLAUDE.md）。
- 2026-07-09 核实选型：BabelDOC v0.6.3（2026-06 发布，活跃）；pdf2zh-next v2.6.x 为官方推荐 Python API 入口（`high_level.do_translate_async_stream`）。
- 2026-07-09 仓库初始化：git init（main 分支）、.gitignore、CLAUDE.md、ROADMAP.md。
- 2026-07-09 backend venv 建立，安装 pdf2zh-next 2.9.0（BabelDOC 0.6.2）。
- 2026-07-09 验证脚本 scripts/validate_pipeline.py：配置构造与 validate_settings() 已用 dummy key 跑通（DeepSeekSettings 会 transform 为 OpenAI 兼容配置，指向 https://api.deepseek.com/v1）。
- 2026-07-09 babeldoc 资产预下载完成（DocLayout YOLO onnx、34 字体、146 CMap，缓存于 ~/.cache/babeldoc）。注：pdf2zh_next 2.9.0 的 --warmup 在下载完成后仍断言需要输入文件而退出码 1，属上游小缺陷，资产本身完整。

- 2026-07-09 **阶段 0 管线验证通过**：attention.pdf 前 2 页经 DeepSeek（deepseek-chat）翻译，37.4s 产出 mono + dual 两个 PDF；人工核对双语版排版完整（左右对照、公式/页眉/脚注保留、中文字体正常）。少量段落（作者名等）因译文与原文相同触发 fallback 警告，属正常行为。

- 2026-07-09 **阶段 1 后端 API 完成并端到端验证**：backend/app/{main,tasks,engines}.py。上传+建任务（multipart，100MB 上限）、SSE 进度（轮询快照式，全阶段推送后自动关流）、下载 dual/mono（200，4.2MB/2.1MB）、取消（3 秒内转 cancelled）全部实测通过；uvicorn 日志核查 API Key 零泄漏。
- 2026-07-09 **阶段 2 翻译适配层完成（代码级）**：engines.py 统一四引擎——DeepSeek（已实测）、自定义 OpenAI 兼容、Claude（走 https://api.anthropic.com/v1/ OpenAI 兼容端点，官方文档已核实，默认 claude-opus-4-8）、Gemini（默认 gemini-2.5-flash，待确认）。Claude/Gemini 需真实 Key 才能实测。

- 2026-07-09 后端补充：/api/test-connection（四引擎统一走各自 OpenAI 兼容端点发最小请求，DeepSeek 实测 ok）；下载接口支持 inline=true 供 iframe 预览。
- 2026-07-09 **阶段 3 前端完成**：Next.js 16 + React 19 + Tailwind 4 单页应用（frontend/app/page.tsx + lib/api.ts）——引擎设置（四引擎切换、Key/模型/BaseURL、localStorage 持久化、连通性测试）、上传提交（页码范围、目标语言）、任务列表（SSE 实时进度条、取消、下载 dual/mono、iframe 在线预览）。npm run build 通过；dev 服务 SSR 冒烟验证八项 UI 元素齐全。

- 2026-07-09 **阶段 4 改为启动脚本方案**（本机无 Docker，经主人确认不装）：start.bat → scripts/start.ps1，一键拉起后端 uvicorn + 前端 next start 并打开浏览器；首次运行自动构建前端。实测：双服务启动成功、health ok、页面渲染正常；踩坑记录——PS 5.1 要求 .ps1 为 UTF-8 带 BOM，否则中文注释按 GBK 解析导致语法错误。CLAUDE.md 部署条目已同步修订。

## 进行中

- 无。

## 待办

- 浏览器人工点验前端完整交互流程（上传→进度→预览→下载）。注意：测试用 DeepSeek Key 已作废（实测 401），需在设置页填新 Key。

## 阻塞

- 无。

## 待确认

- Claude / Gemini 引擎映射未用真实 Key 实测（DeepSeek 已实测通过）。
- Gemini 默认模型名 gemini-2.5-flash、其 OpenAI 兼容测试端点 generativelanguage.googleapis.com/v1beta/openai/ 均未核实。
- 在线预览用 iframe + 浏览器内建 PDF 查看器实现，未按 CLAUDE.md 原定的 pdf.js（效果等价、实现更简，需主人确认是否接受并同步修订 CLAUDE.md）。

## 最近验证

- 2026-07-09 后端 API 端到端：POST /api/tasks（attention.pdf 第 1 页 + DeepSeek）→ SSE 进度全阶段推送 → done → 下载 dual/mono 成功 → 第二任务 cancel 成功。
- 2026-07-09 scripts/validate_pipeline.py + DEEPSEEK_API_KEY：2 页翻译 37.4s，产出 data/outputs/attention.no_watermark.zh.{mono,dual}.pdf，双语排版人工核对通过。
