"""识别扫描底图上的隐藏 OCR 文本，选择 BabelDOC 原生背景遮盖模式。"""

import logging

import pymupdf

logger = logging.getLogger(__name__)


def needs_ocr_background(page) -> bool:
    if not page.get_image_info():
        return False
    hidden = visible = 0
    for span in page.get_texttrace():
        count = sum(1 for char in span["chars"] if char[0] >= 0 and not chr(char[0]).isspace())
        if span["type"] == 3 or span.get("opacity", 1) == 0:
            hidden += count
        else:
            visible += count
    return hidden > 0 and visible == 0


def prepare_page(config) -> bool:
    if config.ocr_workaround:
        return False
    with pymupdf.open(str(config.input_file)) as document:
        if len(document) != 1 or not needs_ocr_background(document[0]):
            return False
    # 与 TranslationConfig(ocr_workaround=True) 的关联选项保持一致。
    # 只修改当前分段，不改变 shared_context，避免影响后续普通文本页。
    config.ocr_workaround = True
    config.skip_scanned_detection = True
    config.disable_rich_text_translate = True
    config.remove_non_formula_lines = False
    logger.info("hidden OCR text over image detected; enabled native OCR background handling")
    return True
