import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.toc_layout import TocParagraphFinder, ranges
from babeldoc.format.pdf.document_il import Box, PdfCharacter, PdfParagraph, VisualBbox
from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder


def characters(text, y=100):
    return [PdfCharacter(char_unicode=c, box=Box(i * 5, y, i * 5 + 5, y + 10),
                         visual_bbox=VisualBbox(Box(i * 5, y, i * 5 + 5, y + 10)),
                         vertical=False, xobj_id=0) for i, c in enumerate(text)]


class TocLayoutTests(unittest.TestCase):
    def setUp(self):
        self.finder = object.__new__(TocParagraphFinder)

    def page(self, texts):
        lines = [self.finder.create_line(characters(text, 100 + i * 20))
                 for i, text in enumerate(texts)]
        return SimpleNamespace(pdf_paragraph=[PdfParagraph(pdf_paragraph_composition=lines)],
                               pdf_character=[])

    def process(self, page):
        with patch.object(ParagraphFinder, "process_page"):
            self.finder.process_page(page)

    def test_spaced_contiguous_and_roman_leaders(self):
        for text in ("1.2 Title . . . . . 12", "1.2 Title .....12", "Title ..... xiv"):
            with self.subTest(text=text):
                start, end, number, dotted = ranges(characters(text))
                self.assertEqual(text[start:end].strip(), "Title")
                self.assertTrue(dotted)
                self.assertIn(text[number:].strip(), ("12", "xiv"))

    def test_rows_split_and_original_number_characters_preserved(self):
        page = self.page(["1.1 Alpha . . . . . 12", "1.2 Bravo . . . . . 13",
                          "1.3 Delta . . . . . 14"])
        original = [c for line in page.pdf_paragraph[0].pdf_paragraph_composition
                    for c in line.pdf_line.pdf_character]
        self.process(page)
        self.assertEqual([p.unicode.strip() for p in page.pdf_paragraph],
                         ["Alpha", "Bravo", "Delta"])
        translated = [c for p in page.pdf_paragraph for line in p.pdf_paragraph_composition
                      for c in line.pdf_line.pdf_character]
        self.assertEqual({id(c) for c in original},
                         {id(c) for c in translated + page.pdf_character})
        self.assertEqual(len(original), len(translated) + len(page.pdf_character))
        self.assertTrue(any(c.char_unicode == "." for c in page.pdf_character))

    def test_body_and_insufficient_directory_evidence_unchanged(self):
        for texts in (["This is ordinary text 12"], ["Title . . . . . 12"]):
            page = self.page(texts)
            original = page.pdf_paragraph[0]
            self.process(page)
            self.assertIs(page.pdf_paragraph[0], original)
            self.assertEqual(page.pdf_character, [])

    def test_invalid_rows(self):
        for text in ("", "12", ".....12", "1.2 .....12", "Title ....."):
            self.assertIsNone(ranges(characters(text)))


if __name__ == "__main__":
    unittest.main()
