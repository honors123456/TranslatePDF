import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ocr_background import needs_ocr_background, prepare_page


class OcrBackgroundTests(unittest.TestCase):
    def make_page(self, document, hidden=True, image=True, visible=False, text="Original OCR text"):
        page = document.new_page(width=300, height=400)
        if image:
            with pymupdf.open() as raster:
                original = raster.new_page(width=300, height=400)
                original.insert_text((30, 60), "Original scanned text")
                page.insert_image(page.rect, pixmap=original.get_pixmap())
        page.insert_text((30, 60), text, render_mode=3 if hidden else 0)
        if visible:
            page.insert_text((30, 100), "Visible normal PDF text")
        return page

    def test_hidden_ocr_text_over_raster_is_detected(self):
        with pymupdf.open() as document:
            self.assertTrue(needs_ocr_background(self.make_page(document)))

    def test_normal_mixed_or_text_only_pages_are_unchanged(self):
        for options in ({"hidden": False}, {"visible": True}, {"image": False}, {"text": " "}):
            with self.subTest(options=options), pymupdf.open() as document:
                self.assertFalse(needs_ocr_background(self.make_page(document, **options)))

    def test_image_without_ocr_text_is_not_misclassified(self):
        with pymupdf.open() as document:
            page = self.make_page(document, text="")
            self.assertTrue(page.get_image_info())
            self.assertFalse(needs_ocr_background(page))

    def test_native_flags_are_applied_only_to_current_page(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / ".tmp") as directory:
            source = Path(directory) / "ocr.pdf"
            with pymupdf.open() as document:
                self.make_page(document)
                document.save(source)
            shared = SimpleNamespace(auto_enabled_ocr_workaround=False)
            config = SimpleNamespace(input_file=source, ocr_workaround=False,
                skip_scanned_detection=False, disable_rich_text_translate=False,
                remove_non_formula_lines=True, shared_context_cross_split_part=shared)
            self.assertTrue(prepare_page(config))
            self.assertTrue(config.ocr_workaround)
            self.assertTrue(config.skip_scanned_detection)
            self.assertTrue(config.disable_rich_text_translate)
            self.assertFalse(config.remove_non_formula_lines)
            self.assertFalse(shared.auto_enabled_ocr_workaround)
            self.assertFalse(prepare_page(config))
