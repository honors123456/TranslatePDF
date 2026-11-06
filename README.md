# TranslationPDF

自用 PDF 翻译工具站：上传 PDF，使用当前 Codex 账号额度、本地 Ollama 或自有 API Key 翻译，输出双语对照或纯译文 PDF，支持在线预览与下载。灵感来自[沉浸式翻译](https://app.immersivetranslate.com/)。

## 功能

- 上传 PDF，保留原排版翻译（基于 [pdf2zh-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next) / [BabelDOC](https://github.com/funstory-ai/BabelDOC)）
- BYOK：使用自己的 API Key，Key 只存浏览器本地
- PDF 上传不设应用层大小上限，按块写入磁盘。
- 设置页的所有引擎统一从模型下拉列表选择，每 7 天自动刷新；关闭页面期间在下次打开时补刷，也可点击「立即刷新模型列表」。列表刷新不会自动更改已选模型，原模型不在当前列表时提示重新选择。
- Codex：调用本机 CLI 的 ChatGPT 登录，默认 `gpt-6-luna`，无需 API Key
- 双语对照 / 纯译文两种输出
- 翻译进度实时显示，断线自动重连；每页翻译并排版后追加译文预览，其余页面继续后台翻译，完成后下载完整 PDF

## 使用

在运行后端的同一 Windows 用户环境中安装 Codex CLI，执行 `codex.cmd login`，使用 ChatGPT 账号登录。`codex.cmd login status` 应显示 `Logged in using ChatGPT`。

后端优先使用 PATH 中的原生 `codex.exe`；找不到时自动查找已安装的官方 VS Code 扩展内的 CLI，最后尝试 npm 版。IDE 与 npm 安装的 CLI 可能版本不同，某个版本返回模型不可用并不能单独证明账号没有该模型权限。连接失败会显示经过脱敏的具体错误。

运行 `start.bat`，在设置页选择「Codex 账号额度」，模型保留默认 `gpt-6-luna`，先测试连通性，然后上传 PDF。已有浏览器设置会保留原引擎，需要手动切换；首次使用默认选择 Codex。

模型列表：Codex 通过本机 CLI 的 `app-server` / `model/list` 查询；DeepSeek、Claude、Gemini 和 OpenAI 兼容端点使用各自的模型列表接口，需要对应 API Key；Ollama 查询本地已安装模型。浏览器仅缓存列表、更新时间及配置身份摘要，刷新失败会提示并保留旧列表。Codex 列表来源可能受 CLI 版本影响，模型能否实际用于翻译仍需连接测试；自定义端点需支持模型列表查询，无列表时不能选择模型或测试连接。

Codex 翻译使用账号的可用模型权限和额度，连通性测试也会消耗少量额度。PDF 段落文本会发送给 Codex 服务；无需把 PDF 交给代理读取。调用使用隔离临时目录、只读沙箱和临时会话，不复制登录凭据，不回退 API Key。同一时间运行一个 Codex 翻译任务，任务内最多 8 路批次请求并发，QPS 上限为 8；失败拆批在当前线程内执行，不新增并发线程。每次请求超时 240 秒，取消任务会通知所有正在运行的请求终止。实际并发受批次数量、缓存与服务限流影响，不保证 8 倍提速。

Codex 按版面识别的标题划分小节，在当前页内合并多个段落发起请求；这是启发式分组，不保证与 PDF 目录逐节对应。每批最多 24 段、正文累计约 12,000 字符，超长单段单独处理；无标题时按长度与段落数分批。返回结果按段落 ID 和公式占位符校验后逐段回填，失败批次拆小直至单段；单段仍失败时记录警告并保留原文。日志中的 `section request` 记录批次段落数、字符数及耗时，不记录正文。进度仍按段落统计，一批完成时可能一次增加多个段落。

代码更新后需重新构建前端，并重启前后端。后端启动会清理旧上传、旧输出和内存任务，请先保存仍需保留的下载结果。

验证连接：`backend\.venv\Scripts\python.exe scripts\validate_codex.py`。验证公开论文样例第 1 页并生成双语与纯译文 PDF：`backend\.venv\Scripts\python.exe scripts\validate_codex.py --pdf`，结果写入 `.tmp/codex-validation/`，不启动 Web 服务。

进度百分比按管线阶段权重估算，不代表剩余时间；串行翻译期间可能长时间保持相同百分比。任务完成 PDF 后处理后才显示 100% 并开放完整结果下载。进度连接中断时页面提示自动重连；若服务重启或任务过期导致任务丢失，需要重新上传。

前端在当前标签页保存任务 ID，并在预览地址中保留 `?task=<任务ID>`。刷新页面或打开任务地址时，会重新订阅后端任务并显示已发布预览，不提交新的翻译请求。原文文件不会持久化；刷新后可点击「选择原文件恢复对照」，仅在浏览器本地打开所选 PDF。任务恢复要求后端仍保留该任务，不能恢复后端关闭后丢失的内存任务。

译文预览按原页序逐页追加，首个页面翻译并排版后即可阅读，新增页面不重新加载已有页面。预览为页面图片，完整可选取文字的 PDF 在全部完成后下载；取消或失败后已发布预览仍保留到任务过期。管线使用 BabelDOC 原生单页分段并最终合并，增加逐页处理开销，小节合批不再跨页。限定页码时，预览页号仍对应原文件，范围外的页面保留原文。

无段落单页保留原文并继续后续页面，预览下方明确标注“未识别到可翻译段落，保留原页”；这不代表该页已完成翻译。CID、扫描检测及其他管线错误仍正常报出。

渐进预览本地验证：`backend\.venv\Scripts\python.exe scripts\validate_preview.py`，使用生成的文字／空白／文字三页 PDF 和固定中文回传，验证真实 spawn 子进程在完成前发布首屏、保留空白页并继续后续文字页、最终合并三页 PDF；不调用大模型、不重启服务，产物位于 `.tmp/preview-validation/`。

批次日志包含请求编号、开始、段落数、字符数、耗时及失败分类，不记录正文或原始 stderr。JSON、段落 ID、占位符错误与 CLI／请求超时分别记录，识别到明确的额度或限流错误标记时记录对应分类。上游连续 30 分钟未返回进度事件时仍停止任务，错误保留最后阶段、段落计数和无事件时长，避免被清理子进程时的退出码覆盖；这与单次 Codex 请求的 240 秒超时不同。

小节合批本地管线验证：`backend\.venv\Scripts\python.exe scripts\validate_sections.py`。默认使用原文回传，对比样例前两页的单段与合批请求次数及 PDF 文本一致性，不调用 Codex。添加 `--real` 才会通过当前 Codex 登录翻译样例第 1 页并消耗额度。输出写入 `.tmp/section-validation/` 下的新时间目录。

## GPU 版面识别与耗时

目录页包含至少三条带点引导线及页码的目录行时，项目会将目录项拆成独立段落，仅翻译标题，保留行内编号、点引导线及页码的原始字符坐标。支持连续或间隔点线；无点线目录及跨行标题不保证识别。此适配在翻译子进程加载，更新后需要重启后端才能生效。

目录排版本地验证：`backend\.venv\Scripts\python.exe scripts\validate_toc.py "原书完整路径"`。只读提取原书第 6、7 页，以固定中文测试标题运行管线，PDF 和渲染图写入 `.tmp/toc-validation/`；不调用外部翻译服务，不修改原书。测试标题用于检查行结构，不能替代真实翻译质量验证。

安装环境提供 `DmlExecutionProvider` 时，翻译子进程使用 DirectML 执行 DocLayout-YOLO 版面识别；没有 GPU provider 或 GPU Session 初始化失败时使用 CPU。PDF 文字与坐标解析、重新排版、文件保存仍主要使用 CPU；Codex 翻译耗时不受本机 GPU 加速。

后端日志记录版面模型 Session 的请求及实际 provider、进程 PID，以及各阶段开始和完成耗时。任务接口的 `stage_seconds` 返回已完成阶段的累计墙钟时间；不同阶段可能重叠，不能简单相加当作总耗时。

本地基准命令：`backend\.venv\Scripts\python.exe scripts\benchmark_layout.py --pipeline`。默认比较公开样例前三页，分别运行 CPU／DirectML，检查识别框类别和坐标，并验证完整子进程管线。完整管线使用本地原文回传代替翻译，不请求 Codex，不能代表真实翻译质量或云端速度。结果、ONNX profiling 和 PDF 输出位于 `.tmp/gpu-benchmark/`；可传 PDF 路径及 `--pages 3` 指定样例范围。
