# TranslationPDF

自用 PDF 翻译工具，FastAPI 后端、Next.js 前端，翻译与排版使用 pdf2zh-next / BabelDOC。

不做用户账号、计费或多租户。后端 Python 3.12，任务状态仅在内存，通过 SSE 推送；前端 TypeScript / Tailwind，使用浏览器内建 PDF 查看器。本机以 `start.bat` 启动，不使用 Docker。

- `backend/app/`：引擎适配、任务管理、PDF 后处理。
- `frontend/`：上传、设置、进度与 PDF 预览。
- `scripts/`：验证与启动脚本；`data/`：运行时上传和输出，Git 忽略。
- 当前状态见 `ROADMAP.md`，使用方式见 `README.md`。
- 云端 API 引擎使用 BYOK，密钥仅在浏览器及后端内存使用，不写日志或配置文件。
- Codex 引擎通过本机 CLI 的 ChatGPT 登录调用，默认 `gpt-6-luna`，不读取或复制登录凭据，不回退 API Key。单个 Codex 任务运行，任务内最多 8 路请求并发，隔离工作目录、只读沙箱。后端可能没有 IDE 的 PATH；找不到原生 CLI 时优先查找已安装的官方 VS Code 扩展内的 CLI，再回退 npm。
- 使用 pdf2zh-next 原生 CLISettings 接入 Codex，不修改虚拟环境中的第三方源码。
- 渐进预览在子进程创建 BabelDOC 配置时安装原生 `PageCountStrategy(max_pages_per_part=1)`；pdf2zh CLI 参数最少 50 页，不经该参数设置单页策略。每页排版完成后发布不可变 PNG，父进程通过 SSE 公布连续就绪页数；最终 PDF 仍由原生分段管线合并。Codex 小节合批以页为边界，不跨预览分段。
- 扫描底图上只有隐藏 OCR 文字的单页，在翻译前启用 BabelDOC 原生 `ocr_workaround` 及关联选项，避免中文与底图英文叠字；判断依据为实际图片与文字渲染状态，不修改原文件、不全局启用、不改变跨页共享上下文。混合可见／隐藏文本页不自动切换。
- Codex 在翻译子进程中按版面标题划分小节并合批；无可靠标题时按长度分批。保留段落 ID 与公式占位符，校验返回后逐段回填；批次失败在当前工作线程内拆分至单段，不额外扩张并发。不把进度段落数当作请求次数。标题分组是启发式，不保证等同 PDF 目录的小节。
- 后端验证使用 `backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests`；静态检查使用 Ruff。前端验证使用 `npm.cmd run build`。
- 服务启动会清理旧上传和输出，验证时直接调用管线，避免为了测试重启服务。
- GPU 版面识别必须在 `translation_worker.py` 的实际 spawn 子进程入口初始化；只在 Web 主进程调用补丁无效。该入口适配 pdf2zh-next 的内部 worker，升级依赖后运行 `scripts/benchmark_layout.py --pipeline` 验证子进程、进度和结果。DirectML Session 必须顺序执行，保留 CPU 回退。
