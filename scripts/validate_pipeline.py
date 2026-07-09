"""阶段 0 管线验证：PDF + DeepSeek Key -> 双语 PDF。

用法（在仓库根目录）：
    $env:DEEPSEEK_API_KEY = "sk-..."
    backend\\.venv\\Scripts\\python.exe scripts\\validate_pipeline.py [pdf_path] [pages]

默认翻译 data/samples/attention.pdf 的第 1-2 页，输出到 data/outputs/。
"""

import asyncio
import os
import sys
import time
from pathlib import Path

from pdf2zh_next.config.model import (
    PDFSettings,
    SettingsModel,
    TranslationSettings,
)
from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
from pdf2zh_next.high_level import do_translate_async_stream

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_settings(output_dir: Path, pages: str) -> SettingsModel:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        sys.exit("缺少环境变量 DEEPSEEK_API_KEY")

    return SettingsModel(
        translation=TranslationSettings(
            lang_in="en",
            lang_out="zh",
            output=str(output_dir),
            qps=4,
        ),
        pdf=PDFSettings(
            pages=pages,
            watermark_output_mode="no_watermark",
        ),
        translate_engine_settings=DeepSeekSettings(
            deepseek_model="deepseek-chat",
            deepseek_api_key=api_key,
        ),
    )


async def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "data/samples/attention.pdf"
    pages = sys.argv[2] if len(sys.argv) > 2 else "1-2"
    if not pdf_path.exists():
        sys.exit(f"PDF 不存在：{pdf_path}")

    output_dir = REPO_ROOT / "data/outputs"
    settings = build_settings(output_dir, pages)
    settings.validate_settings()

    start = time.time()
    last_print = 0.0
    async for event in do_translate_async_stream(settings, pdf_path):
        etype = event.get("type")
        if etype in {"progress_start", "progress_update", "progress_end"}:
            now = time.time()
            if etype != "progress_update" or now - last_print > 2:
                last_print = now
                print(
                    f"[{now - start:6.1f}s] {event.get('stage')}: "
                    f"stage {event.get('stage_progress', 0):.0f}% | "
                    f"overall {event.get('overall_progress', 0):.0f}%"
                )
        elif etype == "error":
            sys.exit(f"翻译失败：{event.get('error')}")
        elif etype == "finish":
            result = event["translate_result"]
            print(f"\n完成，耗时 {time.time() - start:.1f}s")
            print(f"  mono: {getattr(result, 'mono_pdf_path', None)}")
            print(f"  dual: {getattr(result, 'dual_pdf_path', None)}")
            break


if __name__ == "__main__":
    asyncio.run(main())
