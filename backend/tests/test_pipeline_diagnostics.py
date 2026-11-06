import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline_diagnostics import DiagnosticCallback
from app.section_translator import failure_reason
from pdf2zh_next import high_level


class PipelineDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_timeout_survives_upstream_termination_cleanup(self):
        callback = DiagnosticCallback(timeout=0.01)
        callback.last_stage = "Translate Paragraphs"
        callback.last_current, callback.last_total = 8012, 10610
        process = Mock(exitcode=-15)
        process.is_alive.side_effect = [True, False]
        with (patch.object(high_level.asynchronize, "AsyncCallback", return_value=callback),
              patch.object(high_level.multiprocessing, "Process", return_value=process),
              patch.object(high_level.multiprocessing, "Pipe", side_effect=lambda **kw: (Mock(), Mock())),
              patch.object(high_level.multiprocessing, "Queue"),
              patch.object(high_level.threading, "Thread")):
            with self.assertRaisesRegex(TimeoutError, "8012/10610"):
                async for _ in high_level._translate_in_subprocess(None, Path("unused.pdf")):
                    self.fail("No progress should be produced")
        process.terminate.assert_called_once()
        self.assertTrue(callback.has_error())

    async def test_progress_and_terminal_events_remain_unchanged(self):
        callback = DiagnosticCallback(timeout=1)
        event = {"type": "progress_update", "stage": "Translate", "stage_current": 4, "stage_total": 10}
        callback.step_callback(event)
        result = await anext(callback)
        self.assertEqual(result.args[0], event)
        self.assertEqual(callback.last_current, 4)
        callback.finished_callback_without_args()
        with self.assertRaises(StopAsyncIteration):
            await anext(callback)
        self.assertFalse(callback.has_error())

    async def test_cancellation_is_not_relabelled_as_timeout(self):
        callback = DiagnosticCallback(timeout=10)
        waiting = asyncio.create_task(anext(callback))
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertFalse(callback.has_error())


class FailureReasonTests(unittest.TestCase):
    def test_classification_without_leaking_payload(self):
        cases = [(TimeoutError("secret"), "request_timeout"),
                 (subprocess.TimeoutExpired("secret", 1), "request_timeout"),
                 (subprocess.CalledProcessError(1, "secret", stderr="secret"), "cli_exit_1"),
                 (subprocess.CalledProcessError(1, "secret", stderr="secret usage_limit_reached"), "quota_exhausted"),
                 (subprocess.CalledProcessError(1, "secret", stderr="Codex 翻译请求超时。secret"), "request_timeout"),
                 (json.JSONDecodeError("secret", "secret", 0), "invalid_json"),
                 (ValueError("batch placeholder mismatch"), "batch placeholder mismatch"),
                 (ValueError("secret"), "validation_error"),
                 (RuntimeError("secret"), "request_error")]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                reason, error_type = failure_reason(error)
                self.assertEqual(reason, expected)
                self.assertNotIn("secret", reason + error_type)

    def test_retry_error_exposes_underlying_failure_category(self):
        from tenacity import Future, RetryError
        future = Future(3)
        future.set_exception(subprocess.TimeoutExpired("secret", 270))
        self.assertEqual(failure_reason(RetryError(future))[0], "request_timeout")
