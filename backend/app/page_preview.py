"""在实际翻译子进程发布已排版的单页预览，不修改第三方文件。"""

import logging
from pathlib import Path

import pymupdf
from babeldoc.format.pdf import high_level
from babeldoc.format.pdf.split_manager import PageCountStrategy
from babeldoc.format.pdf.translation_config import TranslateResult
from babeldoc.babeldoc_exception.BabelDOCException import ExtractTextError
from pdf2zh_next import high_level as pdf2zh_high_level

from .clean_pdf import clean_pdf

logger = logging.getLogger(__name__)
_original_single = high_level._do_translate_single
_original_config = pdf2zh_high_level.create_babeldoc_config


def preserve_page(config, output: Path, page_number: int):
    """无段落页仍参与最终合并，并显式标记为原文页。"""
    config.raise_if_cancelled()
    directory = output.parent / "untranslated" / str(page_number)
    directory.mkdir(parents=True, exist_ok=True)
    mono, dual = directory / "mono.pdf", directory / "dual.pdf"
    with pymupdf.open(str(config.input_file)) as source:
        if len(source) != 1:
            raise ValueError("passthrough requires a single-page input")
        source.save(mono)
        with pymupdf.open() as document:
            if config.use_alternating_pages_dual:
                document.insert_pdf(source)
                document.insert_pdf(source)
            else:
                rect = source[0].rect
                page = document.new_page(width=rect.width * 2, height=rect.height)
                # 空白页没有内容流，show_pdf_page 会报错；空白保留其尺寸即可。
                if source[0].get_contents():
                    page.show_pdf_page(pymupdf.Rect(0, 0, rect.width, rect.height), source, 0)
                    page.show_pdf_page(pymupdf.Rect(rect.width, 0, rect.width * 2, rect.height), source, 0)
            document.save(dual)
    return TranslateResult(mono_pdf_path=mono, dual_pdf_path=dual)


def translate_or_preserve(monitor, config, output: Path):
    try:
        return _original_single(monitor, config), False
    except ExtractTextError as exc:
        if str(exc) != "The document contains no paragraphs.":
            raise
        # 仅渐进预览的单页处理走此分支，不吞掉 CID、扫描检测、网络等错误。
        result = preserve_page(config, output, monitor.part_index + 1)
        logger.warning("page=%s has no paragraphs; preserving original", monitor.part_index + 1)
        return result, True


def publish_page(result, output: Path, page_number: int) -> bool:
    path = getattr(result, "no_watermark_mono_pdf_path", None) or getattr(result, "mono_pdf_path", None)
    if not path:
        return False
    clean_pdf(Path(path))
    output.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(str(path)) as document:
        if len(document) != 1:
            raise ValueError("preview requires a single-page result")
        target = output / f"{page_number}.png"
        temporary = output / f"{page_number}.tmp.png"
        document[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(str(temporary))
        temporary.replace(target)
    return True


def install(settings) -> None:
    if settings is None:
        return
    output = Path(settings.translation.output) / "preview"

    def create_config(*args, **kwargs):
        config = _original_config(*args, **kwargs)
        # pdf2zh CLI 参数限最少 50 页；BabelDOC 原生策略支持单页分段。
        config.split_strategy = PageCountStrategy(max_pages_per_part=1)
        return config

    def translate_page(monitor, config):
        result, untranslated = translate_or_preserve(monitor, config, output)
        # 分段按原页序执行；单页文档的根 monitor 同样使用 part_index=0。
        page_number = monitor.part_index + 1
        try:
            if publish_page(result, output, page_number):
                monitor.progress_change_callback(
                    type="preview_ready", page_number=page_number,
                    total_pages=monitor.total_parts,
                    untranslated=untranslated,
                )
        except Exception:
            logger.exception("page preview failed page=%s", page_number)
        return result

    high_level._do_translate_single = translate_page
    pdf2zh_high_level.create_babeldoc_config = create_config
