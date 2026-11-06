import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock
from contextlib import nullcontext

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main, page_preview
from app.tasks import Task, TaskManager
from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder
from babeldoc.babeldoc_exception.BabelDOCException import ExtractTextError


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / ".tmp")
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_publish_single_page_and_reject_multi_page(self):
        source = self.root / "source.pdf"
        with pymupdf.open() as document:
            document.new_page().insert_text((50, 50), "Translated page")
            document.save(source)
        result = SimpleNamespace(mono_pdf_path=source)
        self.assertTrue(page_preview.publish_page(result, self.root / "preview", 1))
        with pymupdf.open(self.root / "preview/1.png") as image:
            self.assertGreater(image[0].rect.width, 0)
        with pymupdf.open(source) as document:
            document.new_page()
            document.save(self.root / "two.pdf")
        with self.assertRaises(ValueError):
            page_preview.publish_page(SimpleNamespace(mono_pdf_path=self.root / "two.pdf"), self.root, 2)

    def test_worker_installs_native_single_page_strategy(self):
        settings = SimpleNamespace(translation=SimpleNamespace(output=str(self.root)))
        config = SimpleNamespace(split_strategy=None)
        with patch.object(page_preview, "_original_config", return_value=config), \
             patch.object(page_preview.high_level, "_do_translate_single"), \
             patch.object(page_preview.pdf2zh_high_level, "create_babeldoc_config"):
            page_preview.install(settings)
            actual = page_preview.pdf2zh_high_level.create_babeldoc_config(settings, "source.pdf")
            self.assertIs(actual, config)
            self.assertEqual(config.split_strategy.max_pages_per_part, 1)

    def test_real_paragraph_finder_reproduces_empty_page_failure(self):
        config = Mock()
        config.progress_monitor.stage_start.return_value = nullcontext(Mock())
        with patch("babeldoc.format.pdf.document_il.midend.paragraph_finder.FontMapper"):
            finder = ParagraphFinder(config)
        with patch.object(finder, "process_page"):
            with self.assertRaisesRegex(ExtractTextError, "contains no paragraphs"):
                finder.process(SimpleNamespace(page=[SimpleNamespace(pdf_paragraph=[])]))

    def test_empty_page_preserved_for_preview_and_final_merge(self):
        source = self.root / "blank.pdf"
        with pymupdf.open() as document:
            document.new_page(width=400, height=500)
            document.save(source)
        monitor = SimpleNamespace(part_index=0)
        config = SimpleNamespace(input_file=source, use_alternating_pages_dual=False,
                                 raise_if_cancelled=Mock())
        with patch.object(page_preview, "_original_single", side_effect=ExtractTextError(
            "The document contains no paragraphs.")):
            result, untranslated = page_preview.translate_or_preserve(monitor, config, self.root / "preview")
        self.assertTrue(untranslated)
        with pymupdf.open(result.mono_pdf_path) as document:
            self.assertEqual(len(document), 1)
            self.assertEqual(document[0].rect.width, 400)
        with pymupdf.open(result.dual_pdf_path) as document:
            self.assertEqual(document[0].rect.width, 800)
        self.assertTrue(page_preview.publish_page(result, self.root / "preview", 1))
        config.use_alternating_pages_dual = True
        result = page_preview.preserve_page(config, self.root / "other/preview", 1)
        with pymupdf.open(result.dual_pdf_path) as document:
            self.assertEqual(len(document), 2)

    def test_other_errors_are_not_hidden(self):
        for error in (ExtractTextError("The document contains too many CID paragraphs."),
                      RuntimeError("network failure"), asyncio.CancelledError()):
            with patch.object(page_preview, "_original_single", side_effect=error):
                with self.assertRaises(type(error)):
                    page_preview.translate_or_preserve(None, None, self.root)

    async def test_ready_page_is_visible_before_finish_and_survives_failure(self):
        directory = self.root / "task/preview"
        directory.mkdir(parents=True)
        (directory / "1.png").write_bytes(b"preview")
        task = Task("task", "source.pdf")
        ready, release = asyncio.Event(), asyncio.Event()

        async def stream(*args):
            yield {"type": "preview_ready", "page_number": 1, "total_pages": 2}
            ready.set()
            await release.wait()
            yield {"type": "error", "error": "second page failed"}

        manager = TaskManager(self.root, self.root / "uploads")
        with patch("app.tasks.do_translate_async_stream", stream):
            job = asyncio.create_task(manager._translate(task, None, self.root / "source.pdf"))
            await asyncio.wait_for(ready.wait(), 2)
            self.assertEqual(task.snapshot()["preview_pages"], 1)
            self.assertEqual(task.status, "running")
            self.assertFalse(task.snapshot()["has_mono"])
            with patch.object(main.manager, "get", return_value=task), patch.object(main, "OUTPUT_DIR", self.root):
                response = await main.preview_page("task", 1)
                self.assertEqual(response.media_type, "image/png")
                for page in (0, 2):
                    with self.assertRaises(main.HTTPException):
                        await main.preview_page("task", page)
            release.set()
            await job
        self.assertEqual(task.status, "error")
        self.assertEqual(task.preview_pages, 1)

    async def test_unpublished_or_out_of_order_pages_are_not_advertised(self):
        task = Task("task", "source.pdf")

        async def stream(*args):
            for page in (2, 1):
                yield {"type": "preview_ready", "page_number": page, "total_pages": 2}

        with patch("app.tasks.do_translate_async_stream", stream):
            await TaskManager(self.root, self.root)._translate(task, None, Path("unused"))
        self.assertEqual(task.preview_pages, 0)

    async def test_cancel_keeps_published_preview(self):
        task = Task("task", "source.pdf", preview_pages=1)
        started = asyncio.Event()

        async def stream(*args):
            started.set()
            await asyncio.Event().wait()
            yield {}

        with patch("app.tasks.do_translate_async_stream", stream):
            job = asyncio.create_task(TaskManager(self.root, self.root)._run(
                task, None, Path("unused"), False))
            await asyncio.wait_for(started.wait(), 2)
            job.cancel()
            await job
        self.assertEqual(task.status, "cancelled")
        self.assertEqual(task.preview_pages, 1)
