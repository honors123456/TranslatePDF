"""验证当前账号的 Codex 翻译及 PDF 管线，不启动或重启 Web 服务。"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.engines import EngineConfig, test_connection  # noqa: E402
from app.tasks import TaskManager  # noqa: E402


async def main():
    engine = EngineConfig(type="codex")
    result = await test_connection(engine)
    print(json.dumps(result, ensure_ascii=True), flush=True)
    if not result["ok"]:
        raise RuntimeError("Codex connection failed")
    if "--pdf" not in sys.argv:
        return
    manager = TaskManager(ROOT / ".tmp/codex-validation/outputs", ROOT / ".tmp/codex-validation/uploads")
    source = ROOT / "data/samples/attention.pdf"
    settings = manager._build_settings("smoke", engine, "en", "zh", "1")
    settings.validate_settings()
    from pdf2zh_next.high_level import do_translate_async_stream

    finished = False
    async for event in do_translate_async_stream(settings, source):
        if event.get("type") == "error":
            raise RuntimeError(str(event.get("error")))
        if event.get("type") == "finish":
            import pymupdf
            result = event["translate_result"]
            for kind in ("mono", "dual"):
                path = Path(getattr(result, f"{kind}_pdf_path"))
                with pymupdf.open(path) as document:
                    text = "".join(page.get_text() for page in document)
                    assert any("\u4e00" <= char <= "\u9fff" for char in text), "Chinese translation missing"
                    document[0].get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(str(path.with_suffix(".png")))
                    print(json.dumps({"kind": kind, "pages": len(document), "path": str(path)}, ensure_ascii=True), flush=True)
            finished = True
            break
    if not finished:
        raise RuntimeError("PDF pipeline ended without finish event")


if __name__ == "__main__":
    asyncio.run(main())
