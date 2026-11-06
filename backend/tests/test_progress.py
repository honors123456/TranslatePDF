import asyncio
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.tasks import Task, TaskManager
from app import main


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_sse_heartbeat_and_reconnection_snapshot(self):
        task = Task("sse", "test.pdf", overall_progress=42)
        with patch.object(main.manager, "get", return_value=task), patch("app.main.asyncio.sleep"):
            response = await main.task_events(task.id)
            iterator = response.body_iterator
            first = await anext(iterator)
            self.assertIn('"overall_progress": 42', first)
            self.assertEqual(await anext(iterator), ": heartbeat\n\n")
            task.status = "done"
            task.overall_progress = 100
            self.assertIn('"status": "done"', await anext(iterator))
            with self.assertRaises(StopAsyncIteration):
                await anext(iterator)
            reconnected = await main.task_events(task.id)
            self.assertIn('"status": "done"', await anext(reconnected.body_iterator))
            await reconnected.body_iterator.aclose()

    async def test_repeated_cancel_does_not_interrupt_cleanup_wait(self):
        manager = TaskManager(Path("unused"), Path("unused"))
        task = Task("cancel", "test.pdf")
        waiting = asyncio.Event()

        async def work():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await waiting.wait()
                raise

        task.job = asyncio.create_task(work())
        manager.tasks[task.id] = task
        await asyncio.sleep(0)
        try:
            self.assertTrue(manager.cancel(task.id))
            await asyncio.sleep(0)
            self.assertTrue(manager.cancel(task.id))
            await asyncio.sleep(0)
            self.assertFalse(task.job.done())
        finally:
            waiting.set()
            with self.assertRaises(asyncio.CancelledError):
                await task.job

    async def test_regression_missing_and_invalid_values_preserve_progress(self):
        snapshots = []
        task = Task("progress", "test.pdf")

        async def stream(*args):
            for progress in (62.5, 0, None, float("nan"), float("inf"), "bad", 110):
                yield {"type": "progress_update", "stage": "Translate",
                       "overall_progress": progress, "stage_current": 1, "stage_total": 3}
                snapshots.append(task.snapshot())
            yield {"type": "progress_start", "stage": "Save"}
            snapshots.append(task.snapshot())

        manager = TaskManager(Path("unused"), Path("unused"))
        with patch("app.tasks.do_translate_async_stream", stream):
            await manager._translate(task, None, Path("test.pdf"))
        self.assertEqual([s["overall_progress"] for s in snapshots], [62.5] * 6 + [99, 99])
        self.assertEqual(snapshots[0]["stage_total"], 3)
        self.assertIsNone(snapshots[-1]["stage_current"])
        self.assertGreaterEqual(task.updated_at, task.created_at)

    async def test_cleaning_keeps_loop_responsive_and_hides_unfinished_files(self):
        await self.check_cleaning(cancel=False)

    async def test_cancel_waits_for_cleaning_without_publishing_files(self):
        await self.check_cleaning(cancel=True)

    async def check_cleaning(self, cancel):
        started, release = threading.Event(), threading.Event()
        task = Task("clean", "test.pdf", overall_progress=99)

        def clean(*args):
            started.set()
            release.wait(5)

        async def stream(*args):
            yield {"type": "finish", "translate_result": SimpleNamespace(
                mono_pdf_path="mono.pdf", dual_pdf_path="dual.pdf")}

        manager = TaskManager(Path("unused"), Path("unused"))
        with patch("app.tasks.do_translate_async_stream", stream), patch("app.tasks.clean_outputs", clean):
            job = asyncio.create_task(manager._translate(task, None, Path("test.pdf")))
            try:
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await asyncio.sleep(0.01)
                self.assertFalse(job.done())
                self.assertEqual(task.stage, "PDF 后处理")
                self.assertEqual(task.overall_progress, 99)
                self.assertFalse(task.snapshot()["has_mono"])
                if cancel:
                    job.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(job.done())
            finally:
                release.set()
                if cancel:
                    with self.assertRaises(asyncio.CancelledError):
                        await job
                else:
                    await job
        if cancel:
            self.assertIsNone(task.mono_path)
        else:
            self.assertEqual(task.status, "done")
            self.assertEqual(task.overall_progress, 100)
            self.assertTrue(task.snapshot()["has_mono"])
