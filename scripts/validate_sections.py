"""默认以本地回传验证小节合批；--real 才会调用 Codex，不操作 Web 服务。"""

import asyncio
import json
import logging
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.engines import EngineConfig  # noqa: E402
from app.clean_pdf import clean_outputs  # noqa: E402
from app.tasks import TaskManager  # noqa: E402
from pdf2zh_next.high_level import do_translate_async_stream  # noqa: E402
from pdf2zh_next.config.model import PDFSettings, SettingsModel, TranslationSettings  # noqa: E402
from pdf2zh_next.config.translate_engine_model import CLISettings  # noqa: E402

LOCAL_BRIDGE = '''import json, sys
from pathlib import Path
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
text = sys.stdin.read()
with Path(sys.argv[1]).open("a", encoding="utf-8") as log:
    log.write("1\\n")
prefix = "TRANSLATIONPDF_SECTION_V1\\n"
if text.startswith(prefix):
    print(json.dumps(json.loads(text[len(prefix):])))
else:
    print(text)
'''


async def local_validation(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {}
    for mode in ("single", "section"):
        bridge = output / ("codex_cli.py" if mode == "section" else "identity.py")
        bridge.write_text(LOCAL_BRIDGE, encoding="utf-8")
        counter = output / f"{mode}.requests.txt"
        settings = SettingsModel(
            translation=TranslationSettings(output=str(output / mode), lang_in="en", lang_out="zh",
                qps=1, pool_max_workers=1, no_auto_extract_glossary=True, ignore_cache=True),
            pdf=PDFSettings(pages="1-2", watermark_output_mode="no_watermark"),
            translate_engine_settings=CLISettings(clitranslator_command=shlex.join(
                [sys.executable, str(bridge), str(counter)])),
        )
        settings.validate_settings()
        from app.tasks import Task
        task = Task(mode, "attention.pdf")
        manager = TaskManager(output / mode, output / "unused")
        started = time.perf_counter()
        await manager._translate(task, settings, ROOT / "data/samples/attention.pdf")
        if task.status != "done":
            raise RuntimeError(task.error or "pipeline did not finish")
        import pymupdf
        with pymupdf.open(task.mono_path) as document:
            texts = [page.get_text() for page in document]
        report[mode] = {"requests": len(counter.read_text().splitlines()),
                        "seconds": time.perf_counter() - started, "texts": texts,
                        "mono": str(task.mono_path), "dual": str(task.dual_path)}
    if report["section"]["requests"] >= report["single"]["requests"]:
        raise RuntimeError("batching did not reduce requests")
    if report["section"]["texts"] != report["single"]["texts"]:
        raise RuntimeError("paragraph writeback changed extracted PDF text")
    for result in report.values():
        result.pop("texts")
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


async def main():
    import pymupdf

    logging.basicConfig(level=logging.INFO)
    output = ROOT / ".tmp/section-validation" / time.strftime("%Y%m%d-%H%M%S")
    if "--real" not in sys.argv:
        await local_validation(output)
        return
    manager = TaskManager(output / "outputs", output / "uploads")
    settings = manager._build_settings("sample", EngineConfig(type="codex"), "en", "zh", "1")
    settings.validate_settings()
    started = time.perf_counter()
    async for event in do_translate_async_stream(settings, ROOT / "data/samples/attention.pdf"):
        if event.get("type") == "error":
            raise RuntimeError(str(event.get("error")))
        if event.get("type") == "finish":
            result = event["translate_result"]
            await asyncio.to_thread(clean_outputs, result.mono_pdf_path, result.dual_pdf_path)
            files = {}
            for kind in ("mono", "dual"):
                path = Path(getattr(result, f"{kind}_pdf_path"))
                with pymupdf.open(path) as document:
                    text = "".join(page.get_text() for page in document)
                    if not any("\u4e00" <= ch <= "\u9fff" for ch in text):
                        raise RuntimeError("Chinese translation missing")
                    document[0].get_pixmap().save(str(path.with_suffix(".png")))
                    files[kind] = {"path": str(path), "pages": len(document)}
            print(json.dumps({"seconds": time.perf_counter() - started, "files": files}), flush=True)
            return
    raise RuntimeError("PDF pipeline ended without finish event")


if __name__ == "__main__":
    asyncio.run(main())
