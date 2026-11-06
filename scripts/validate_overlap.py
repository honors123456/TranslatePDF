"""对原书页只读取样，用固定中文回传比较隐藏 OCR 层的背景处理。"""

import asyncio
import json
import shlex
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import page_preview, translation_worker  # noqa: E402
from app.tasks import Task, TaskManager  # noqa: E402
from pdf2zh_next import high_level  # noqa: E402
from pdf2zh_next.config.model import PDFSettings, SettingsModel, TranslationSettings  # noqa: E402
from pdf2zh_next.config.translate_engine_model import CLISettings  # noqa: E402


def baseline_worker(*args):
    page_preview.prepare_page = lambda config: False
    return translation_worker.gpu_translation_worker(*args)


async def main():
    import pymupdf

    mode = sys.argv[1]
    source = Path(sys.argv[2])
    output = ROOT / ".tmp/overlap-fix" / f"{time.strftime('%Y%m%d-%H%M%S')}-{mode}"
    output.mkdir(parents=True)
    bridge = output / "fixed.py"
    # 固定回传用于排版验证，不声称是真实模型翻译。
    bridge.write_text('import sys\nsys.stdin.reconfigure(encoding="utf-8")\n'
        'sys.stdout.reconfigure(encoding="utf-8")\n'
        'sys.stdin.read()\nprint("版权所有。未经出版商许可，不得以任何形式复制本书内容。")\n', encoding="utf-8")
    if mode == "baseline":
        high_level._translate_wrapper = baseline_worker
    settings = SettingsModel(
        translation=TranslationSettings(output=str(output / "task"), lang_in="en", lang_out="zh",
            qps=8, pool_max_workers=8, no_auto_extract_glossary=True, ignore_cache=True),
        pdf=PDFSettings(watermark_output_mode="no_watermark", skip_scanned_detection=True),
        translate_engine_settings=CLISettings(clitranslator_command=shlex.join([sys.executable, str(bridge)])),
    )
    settings.validate_settings()
    task = Task("task", source.name)
    await TaskManager(output, output / "unused")._translate(task, settings, source)
    assert task.status == "done", task.error
    with pymupdf.open(task.mono_path) as document:
        assert len(document) == 1
        text = document[0].get_text()
        assert any("\u4e00" <= char <= "\u9fff" for char in text)
        document[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(output / "mono.png")
        report = {"mode": mode, "mono": str(task.mono_path), "preview_pages": task.preview_pages,
                  "text": text, "output": str(output)}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
