# ROADMAP

## 当前阶段

阶段 0：管线验证 —— 用 pdf2zh-next 跑通「PDF + DeepSeek Key → 双语 PDF」。此步不通过则重选核心引擎。

## 已完成

- 2026-07-09 方案确定：FastAPI + Next.js，核心管线 pdf2zh-next（BabelDOC 官方入口），BYOK，自用定位（详见 CLAUDE.md）。
- 2026-07-09 核实选型：BabelDOC v0.6.3（2026-06 发布，活跃）；pdf2zh-next v2.6.x 为官方推荐 Python API 入口（`high_level.do_translate_async_stream`）。
- 2026-07-09 仓库初始化：git init（main 分支）、.gitignore、CLAUDE.md、ROADMAP.md。

## 进行中

- 阶段 0 管线验证：安装 pdf2zh-next、编写验证脚本。

## 待办

- 阶段 1 后端：上传 / 创建任务 / SSE 进度 / 下载 / 取消。
- 阶段 2 翻译适配：DeepSeek → 自定义 OpenAI 兼容 → Claude → Gemini。
- 阶段 3 前端：上传页、设置页（引擎+Key+连通性测试）、进度页、预览下载页。
- 阶段 4 打包：Docker Compose + 端到端验证。

## 阻塞

- 管线验证需要用户提供 DeepSeek API Key（环境变量方式）。

## 最近验证

- 无（尚未运行任何管线）。
