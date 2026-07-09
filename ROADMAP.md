# ROADMAP

## 当前阶段

阶段 0：管线验证 —— 用 pdf2zh-next 跑通「PDF + DeepSeek Key → 双语 PDF」。此步不通过则重选核心引擎。

## 已完成

- 2026-07-09 方案确定：FastAPI + Next.js，核心管线 pdf2zh-next（BabelDOC 官方入口），BYOK，自用定位（详见 CLAUDE.md）。
- 2026-07-09 核实选型：BabelDOC v0.6.3（2026-06 发布，活跃）；pdf2zh-next v2.6.x 为官方推荐 Python API 入口（`high_level.do_translate_async_stream`）。
- 2026-07-09 仓库初始化：git init（main 分支）、.gitignore、CLAUDE.md、ROADMAP.md。
- 2026-07-09 backend venv 建立，安装 pdf2zh-next 2.9.0（BabelDOC 0.6.2）。
- 2026-07-09 验证脚本 scripts/validate_pipeline.py：配置构造与 validate_settings() 已用 dummy key 跑通（DeepSeekSettings 会 transform 为 OpenAI 兼容配置，指向 https://api.deepseek.com/v1）。
- 2026-07-09 babeldoc 资产预下载完成（DocLayout YOLO onnx、34 字体、146 CMap，缓存于 ~/.cache/babeldoc）。注：pdf2zh_next 2.9.0 的 --warmup 在下载完成后仍断言需要输入文件而退出码 1，属上游小缺陷，资产本身完整。

## 进行中

- 阶段 0 管线验证：等待 DeepSeek API Key 跑真实翻译。

## 待办

- 阶段 1 后端：上传 / 创建任务 / SSE 进度 / 下载 / 取消。
- 阶段 2 翻译适配：DeepSeek → 自定义 OpenAI 兼容 → Claude → Gemini。
- 阶段 3 前端：上传页、设置页（引擎+Key+连通性测试）、进度页、预览下载页。
- 阶段 4 打包：Docker Compose + 端到端验证。

## 阻塞

- 管线验证需要用户提供 DeepSeek API Key（环境变量方式）。

## 最近验证

- 无（尚未运行任何管线）。
