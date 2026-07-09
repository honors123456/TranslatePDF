"""翻译后 PDF 后处理：清除 babeldoc 残留的排版标记字符。

上游 babeldoc 的 IL→PDF 输出阶段可能遗留 \x03（ETX）字符，
来源是 Adobe 标准 glyphlist 中的 controlETX→U+0003 映射。
"""

import logging
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

# 要清除的控制字符列表
DIRTY_CHARS = frozenset(["\x03"])  # ETX


def clean_pdf(path: Path) -> bool:
    """清除 PDF 中残留的控制字符，原地覆盖。

    Returns:
        True 如果有修改并保存，False 如果无需修改或文件不存在。
    """
    if not path or not path.exists():
        return False

    modified = False
    doc = None
    try:
        doc = pymupdf.open(str(path))
        for page in doc:
            raw = page.get_text("rawdict")
            redactions = []
            for block in raw["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        for ch in span.get("chars", []):
                            if ch.get("c") in DIRTY_CHARS:
                                bbox = ch["bbox"]
                                redactions.append(
                                    pymupdf.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
                                )

            if redactions:
                for r in redactions:
                    page.add_redact_annot(r, fill=None, text="")
                page.apply_redactions()
                modified = True

        if modified:
            # 先关文档，再替换文件（Windows 不能打开时替换）
            tmp = path.with_suffix(".clean.tmp.pdf")
            doc.save(str(tmp), deflate=True, garbage=4, incremental=False)
            doc.close()
            doc = None
            tmp.replace(path)
            logger.info("cleaned %d dirty chars from %s", len(redactions), path.name)
            return True
    except Exception as exc:
        logger.warning("clean_pdf failed for %s: %s", path.name, exc)
    finally:
        if doc:
            doc.close()
    return False


def clean_outputs(mono: Path | None, dual: Path | None) -> None:
    """清理 mono 和 dual 两个输出 PDF。"""
    for p in [mono, dual]:
        if p and p.exists():
            clean_pdf(p)
