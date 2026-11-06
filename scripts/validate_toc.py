"""只读提取原书目录页，以本地中文回传验证排版，不请求翻译服务。"""
import asyncio
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
    source = Path(sys.argv[1])
    output = ROOT / ".tmp/toc-validation" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    fixture = output / "toc.pdf"
    with pymupdf.open(source) as original, pymupdf.open() as subset:
        subset.insert_pdf(original, from_page=5, to_page=6)
        subset.save(fixture)
    bridge = output / "codex_cli.py"
    bridge.write_text('''import sys,json
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
text=sys.stdin.read()
prefix="TRANSLATIONPDF_SECTION_V1\\n"
def translate(text):
    return "目录标题" if any(c.isalpha() for c in text) else text
if text.startswith(prefix):
    rows=json.loads(text[len(prefix):])
    for row in rows: row["text"]=translate(row["text"])
    print(json.dumps(rows,ensure_ascii=False))
else: print(translate(text))
''', encoding="utf-8")
    settings = SettingsModel(
        translation=TranslationSettings(output=str(output / "result"), lang_in="en", lang_out="zh",
            qps=8, pool_max_workers=8, no_auto_extract_glossary=True, ignore_cache=True),
        pdf=PDFSettings(watermark_output_mode="no_watermark"),
        translate_engine_settings=CLISettings(clitranslator_command=shlex.join([sys.executable, str(bridge)])),
    )
    settings.validate_settings()
    task = Task("toc", source.name)
    await TaskManager(output / "result", output / "unused")._translate(task, settings, fixture)
    if task.status != "done":
        raise RuntimeError(task.error or "pipeline failed")
    with pymupdf.open(task.mono_path) as translated:
        for i, page in enumerate(translated):
            page.get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4)).save(str(output / f"page-{i+1}.png"))
            print(page.get_text().encode("ascii", "backslashreplace").decode())
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
