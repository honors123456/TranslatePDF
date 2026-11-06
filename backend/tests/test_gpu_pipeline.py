import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import gpu_patch, translation_worker
from app.tasks import Task, TaskManager


class GPUConfigurationTests(unittest.TestCase):
    def setUp(self):
        previous = gpu_patch.doclayout.onnxruntime
        self.addCleanup(setattr, gpu_patch.doclayout, "onnxruntime", previous)

    @patch.object(gpu_patch.onnxruntime, "get_available_providers", return_value=["DmlExecutionProvider", "CPUExecutionProvider"])
    @patch.object(gpu_patch.onnxruntime, "InferenceSession")
    def test_directml_options_and_actual_session(self, factory, _):
        factory.return_value.get_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        gpu_patch.apply()
        session = gpu_patch.doclayout.onnxruntime.InferenceSession(b"model", providers=["CPUExecutionProvider"])
        options = factory.call_args.kwargs["sess_options"]
        self.assertFalse(options.enable_mem_pattern)
        self.assertEqual(options.execution_mode, gpu_patch.onnxruntime.ExecutionMode.ORT_SEQUENTIAL)
        self.assertEqual(factory.call_args.kwargs["providers"][0], "DmlExecutionProvider")
        session.run([], {})
        factory.return_value.run.assert_called_once()

    @patch.object(gpu_patch.onnxruntime, "get_available_providers", return_value=["DmlExecutionProvider", "CPUExecutionProvider"])
    @patch.object(gpu_patch.onnxruntime, "InferenceSession")
    def test_gpu_failure_retries_cpu(self, factory, _):
        cpu = Mock()
        cpu.get_providers.return_value = ["CPUExecutionProvider"]
        factory.side_effect = [RuntimeError("GPU unavailable"), cpu]
        gpu_patch.apply()
        self.assertIs(gpu_patch.doclayout.onnxruntime.InferenceSession(b"model"), cpu)
        self.assertEqual(factory.call_args.kwargs["providers"], ["CPUExecutionProvider"])

    @patch.object(translation_worker.gpu_patch, "apply")
    @patch.object(translation_worker, "_original_worker")
    def test_worker_initializes_gpu_before_original_pipeline(self, original, apply):
        order = []
        apply.side_effect = lambda: order.append("gpu")
        original.side_effect = lambda *args: order.append("pipeline")
        translation_worker.gpu_translation_worker(None, None, None, None, Mock())
        self.assertEqual(order, ["gpu", "pipeline"])
        original.assert_called_once()

    @patch.object(gpu_patch.onnxruntime, "get_available_providers", return_value=["CPUExecutionProvider"])
    def test_cpu_only_installation_preserves_original_factory(self, _):
        original = gpu_patch.doclayout.onnxruntime
        gpu_patch.apply()
        self.assertIs(gpu_patch.doclayout.onnxruntime, original)

    def test_directml_session_serializes_concurrent_run_calls(self):
        active = maximum = 0
        def run():
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(0.01)
            active -= 1
        session = gpu_patch._SequentialSession(SimpleNamespace(run=run))
        threads = [threading.Thread(target=session.run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(maximum, 1)


class StageTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_stage_timings_are_added_and_exposed(self):
        async def stream(*args):
            for event in [{"type": "progress_start", "stage": "Parse PDF"},
                          {"type": "progress_end", "stage": "Parse PDF"},
                          {"type": "progress_start", "stage": "Parse PDF"},
                          {"type": "progress_end", "stage": "Parse PDF"},
                          {"type": "finish", "translate_result": SimpleNamespace(mono_pdf_path=None, dual_pdf_path=None)}]:
                await asyncio.sleep(0)
                yield event
        manager = TaskManager(Path("unused-output"), Path("unused-upload"))
        task = Task("test", "test.pdf")
        with patch("app.tasks.do_translate_async_stream", stream), patch("app.tasks.time.perf_counter", side_effect=[10, 12, 20, 23]), patch("app.tasks.clean_outputs"):
            await manager._translate(task, None, Path("test.pdf"))
        self.assertEqual(task.snapshot()["stage_seconds"], {"Parse PDF": 5})
        self.assertEqual(task.status, "done")


if __name__ == "__main__":
    unittest.main()
