"""在段落识别后保护目录行的编号、引导线和页码，仅让标题进入翻译。"""

import re
from dataclasses import replace
from statistics import median

from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder, generate_base58_id

LEADER = re.compile(r"(?:[.·]\s*){5,}|…{3,}")
PAGE_NUMBER = re.compile(r"(?:\d+|[ivxlcdm]+)\s*$", re.I)
SECTION_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)*\s+")


def ranges(chars):
    text = "".join(c.char_unicode or "" for c in chars)
    leader = LEADER.search(text)
    number = PAGE_NUMBER.search(text)
    if not number or number.start() == 0:
        return None
    if leader and leader.end() > number.start():
        return None
    prefix = SECTION_NUMBER.match(text)
    start = prefix.end() if prefix else 0
    end = leader.start() if leader else number.start()
    if not text[start:end].strip():
        return None
    return start, end, number.start(), bool(leader)


class TocParagraphFinder(ParagraphFinder):
    def process_page(self, page):
        super().process_page(page)
        rows = []
        for paragraph in page.pdf_paragraph:
            for composition in paragraph.pdf_paragraph_composition:
                if composition.pdf_line:
                    chars = composition.pdf_line.pdf_character
                    info = ranges(chars)
                    if info and info[3]:
                        # 字符的 unicode 可多于一码，按实际文本偏移定位页码。
                        offset = 0
                        for char in chars:
                            if offset >= info[2]:
                                rows.append(char.box.x)
                                break
                            offset += len(char.char_unicode or "")
        if len(rows) < 3:
            return
        page_column = median(rows)
        paragraphs = []
        for paragraph in page.pdf_paragraph:
            pending = []

            def append_part(compositions):
                if not compositions:
                    return
                part = replace(paragraph, pdf_paragraph_composition=compositions,
                               debug_id=generate_base58_id())
                self.update_paragraph_data(part, update_unicode=True)
                paragraphs.append(part)

            for composition in paragraph.pdf_paragraph_composition:
                if not composition.pdf_line:
                    pending.append(composition)
                    continue
                chars = composition.pdf_line.pdf_character
                info = ranges(chars)
                if not info:
                    pending.append(composition)
                    continue
                start, end, number_start, dotted = info
                title, protected = [], []
                offset = 0
                number_x = None
                for char in chars:
                    if offset >= number_start and number_x is None:
                        number_x = char.box.x
                    (title if start <= offset < end else protected).append(char)
                    offset += len(char.char_unicode or "")
                if not title or number_x is None or (not dotted and abs(number_x - page_column) > 12):
                    pending.append(composition)
                    continue
                append_part(pending)
                pending = []
                # 留在未翻译字符层，保持原始字体、坐标与右对齐页码。
                page.pdf_character.extend(protected)
                append_part([self.create_line(title)])
            append_part(pending)
        page.pdf_paragraph = paragraphs


def install():
    from babeldoc.format.pdf import high_level
    high_level.ParagraphFinder = TocParagraphFinder
