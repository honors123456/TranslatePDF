"""本地固定译文验证文字／空白／文字三页 spawn 管线，不调用大模型或重启服务。"""

import asyncio
import json
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.tasks import Task, TaskManager  # noqa: E402
from pdf2zh_next.config.model import PDFSettings, SettingsModel, TranslationSettings  # noqa: E402
from pdf2zh_next.config.translate_engine_model import CLISettings  # noqa: E402


async def main():
    import pymupdf

    output = ROOT / ".tmp/preview-validation" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    source = output / "source.pdf"
    with pymupdf.open() as document:
        for number in range(3):
            page = document.new_page()
            if number == 1:
                continue  # 真实空白分段回归，后续有文字页面必须继续翻译。
            page.insert_text((72, 72), f"Example document page {number + 1}.")
            page.insert_text((72, 110), "This paragraph explains the operation of an embedded system.")
        document.save(source)
    bridge = output / "identity.py"
    bridge.write_text('import sys\nsys.stdin.reconfigure(encoding="utf-8")\n'
                      'sys.stdout.reconfigure(encoding="utf-8")\n'
                      'sys.stdin.read()\nprint("这是本地预览测试译文，用于验证逐页排版输出。")\n', encoding="utf-8")
    settings = SettingsModel(
        translation=TranslationSettings(output=str(output / "task"), lang_in="en", lang_out="zh",
            qps=1, pool_max_workers=1, no_auto_extract_glossary=True, ignore_cache=True),
        pdf=PDFSettings(watermark_output_mode="no_watermark", skip_scanned_detection=True),
        translate_engine_settings=CLISettings(clitranslator_command=shlex.join([sys.executable, str(bridge)])),
    )
    settings.validate_settings()
    task = Task("task", source.name)
    manager = TaskManager(output, output / "uploads")
    job = asyncio.create_task(manager._translate(task, settings, source))
    observed = []
    while not job.done():
        if task.preview_pages and task.preview_pages not in observed:
            assert task.status == "running", "preview first observed after completion"
            observed.append(task.preview_pages)
            print(json.dumps({"ready": task.preview_pages, "status": task.status}), flush=True)
        await asyncio.sleep(0.01)
    await job
    assert observed and observed[0] == 1, observed
    assert task.status == "done", task.error
    assert task.preview_pages == 3, task.snapshot()
    assert task.untranslated_pages == [2], task.snapshot()
    with pymupdf.open(task.mono_path) as document:
        assert len(document) == 3
        assert not document[1].get_text().strip()
        assert all(any("\u4e00" <= char <= "\u9fff" for char in document[index].get_text()) for index in (0, 2))
    report = {"task": task.snapshot(), "observed_before_finish": observed, "output": str(output)}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
