import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import codex_batch
from app.section_translator import SectionTranslator, install
from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator


class BatchProtocolTests(unittest.TestCase):
    def test_reordered_rows_match_ids_and_preserve_formulas(self):
        output = json.dumps([{"id": "1", "text": "乙"}, {"id": "0", "text": "甲 {v1}"}])
        self.assertEqual(codex_batch.decode(output, ["a {v1}", "b"], [["{v1}"], []]), ["甲 {v1}", "乙"])

    def test_rejects_missing_duplicate_wrong_ids_empty_and_lost_placeholders(self):
        for rows in ([], [{"id": "1", "text": "x"}], [{"id": "0", "text": ""}],
                     [{"id": "0", "text": "x"}], [{"id": "0", "text": 3}], {}):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                codex_batch.decode(json.dumps(rows), ["a {v1}"], [["{v1}"]])
        with self.assertRaises(ValueError):
            codex_batch.decode('[{"id":"0","text":"a"},{"id":"0","text":"b"}]', ["a", "b"], [[], []])

    def test_plain_text_is_not_changed_and_batch_has_structure_instruction(self):
        self.assertEqual(codex_batch.instruction("hello"), "hello")
        self.assertIn('"id": "0"', codex_batch.instruction(codex_batch.encode(["hello"])))

    def test_rejects_invented_formula_placeholder(self):
        with self.assertRaises(ValueError):
            codex_batch.decode('[{"id":"0","text":"x {v999}"}]', ["x"], [[]])


class SectionTests(unittest.TestCase):
    def make_translator(self):
        translator = object.__new__(SectionTranslator)
        translator.translation_config = Mock()
        translator.translate_engine = Mock()
        return translator

    def test_cross_page_section_heading_and_length_boundaries(self):
        translator = self.make_translator()
        translator._pending = []
        translator._pending_chars = 0
        first = SimpleNamespace(pdf_paragraph=[SimpleNamespace(unicode="heading", layout_label="title"),
                                              SimpleNamespace(unicode="body", layout_label="text")])
        last = SimpleNamespace(pdf_paragraph=[SimpleNamespace(unicode="continued", layout_label="text"),
                                             SimpleNamespace(unicode="next heading", layout_label="title")])
        translator._last_page = last
        batches = []
        executor = Mock()
        executor.submit.side_effect = lambda fn, entries, **kw: batches.append(entries)

        def process_page(self, page, executor, pbar, tracker):
            for paragraph in page.pdf_paragraph:
                executor.submit(self.translate_paragraph, paragraph, page, pbar, tracker, {}, {}, priority=1)

        with patch.object(ILTranslator, "process_page", process_page):
            translator.process_page(first, executor)
            self.assertFalse(batches)
            translator.process_page(last, executor)
        self.assertEqual([len(batch) for batch in batches], [3, 1])
        self.assertNotIn("priority", batches[0][0][1])
        translator._pending, translator._pending_chars = [], 0
        batches.clear()
        with patch.object(ILTranslator, "process_page", process_page), patch("app.section_translator.MAX_CHARS", 8):
            translator.process_page(last, executor)
        self.assertEqual([len(batch) for batch in batches], [1, 1])

    def test_invalid_batch_splits_and_falls_back_to_single_requests(self):
        translator = self.make_translator()
        translator.translate_engine.translate.side_effect = ["invalid json", "甲 {v1}", "乙"]
        self.assertEqual(translator._request(["a {v1}", "b"], [["{v1}"], []]), ["甲 {v1}", "乙"])
        self.assertEqual(translator.translate_engine.translate.call_count, 3)

    def test_cancel_stops_before_request(self):
        translator = self.make_translator()
        translator.translation_config.raise_if_cancelled.side_effect = RuntimeError("cancelled")
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            translator._request(["a", "b"], [[], []])
        translator.translate_engine.translate.assert_not_called()

    def test_batch_uses_one_request_and_writes_each_paragraph_with_progress(self):
        translator = self.make_translator()
        translator.pre_translate_paragraph = Mock(side_effect=[
            ("a {v1}", SimpleNamespace(placeholders=[SimpleNamespace(placeholder="{v1}")])),
            ("b", SimpleNamespace(placeholders=[])),
            (None, None),
        ])
        translator.post_translate_paragraph = Mock()
        translator.translate_engine.translate.return_value = '[{"id":"0","text":"甲 {v1}"},{"id":"1","text":"乙"}]'
        pbar = Mock()
        paragraphs = [SimpleNamespace(debug_id=str(i)) for i in range(3)]
        entries = [((p, None, pbar, Mock(), {}, {}), {}) for p in paragraphs]
        translator._translate_section(entries)
        translator.translate_engine.translate.assert_called_once()
        self.assertEqual(translator.post_translate_paragraph.call_count, 2)
        self.assertIs(translator.post_translate_paragraph.call_args_list[0].args[0], paragraphs[0])
        self.assertEqual(pbar.advance.call_count, 3)

    def test_other_engines_are_not_replaced(self):
        from babeldoc.format.pdf import high_level
        previous = high_level.ILTranslator
        install(SimpleNamespace(translate_engine_settings=SimpleNamespace()))
        self.assertIs(high_level.ILTranslator, previous)

    def test_heading_free_document_is_bounded_by_paragraph_count(self):
        translator = self.make_translator()
        translator._pending, translator._pending_chars = [], 0
        page = SimpleNamespace(pdf_paragraph=[SimpleNamespace(unicode="x", layout_label="text") for _ in range(50)])
        translator._last_page = page
        batches = []
        executor = Mock()
        executor.submit.side_effect = lambda fn, entries, **kw: batches.append(entries)

        def process_page(self, page, executor, pbar, tracker):
            for paragraph in page.pdf_paragraph:
                executor.submit(self.translate_paragraph, paragraph, page, pbar, tracker, {}, {})

        with patch.object(ILTranslator, "process_page", process_page):
            translator.process_page(page, executor)
        self.assertEqual([len(batch) for batch in batches], [24, 24, 2])

    def test_failed_single_paragraph_keeps_source_without_claiming_translation(self):
        translator = self.make_translator()
        translator.translate_engine.translate.return_value = "lost formula"
        self.assertEqual(translator._request(["a {v1}"], [["{v1}"]]), [None])
