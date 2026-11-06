import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import codex_batch, codex_cli
from app.engines import EngineConfig
from app.section_translator import SectionTranslator
from app.tasks import TaskManager
from babeldoc.utils.priority_thread_pool_executor import PriorityThreadPoolExecutor


class CodexConcurrencyTests(unittest.TestCase):
    @patch.object(codex_cli, "require_chatgpt_login")
    def test_settings_limit_codex_requests_to_eight_and_keep_one_task(self, _):
        manager = TaskManager(Path("unused"), Path("unused"))
        settings = manager._build_settings("test", EngineConfig(type="codex"), "en", "zh", None)
        self.assertEqual(settings.translation.pool_max_workers, 8)
        self.assertEqual(settings.translation.qps, 8)
        self.assertEqual(manager._codex_sem._value, 1)

    def test_eight_batches_keep_paragraph_mapping_when_responses_are_reordered(self):
        translator = object.__new__(SectionTranslator)
        translator.translation_config = Mock()
        barrier, lock = threading.Barrier(8), threading.Lock()
        active = maximum = 0
        outputs = {}

        def request(text):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                barrier.wait(timeout=5)
                rows = json.loads(text[len(codex_batch.PREFIX):])
                return json.dumps([{"id": row["id"], "text": "translated " + row["text"]}
                                   for row in reversed(rows)])
            finally:
                with lock:
                    active -= 1

        translator.translate_engine = SimpleNamespace(translate=request)
        translator.pre_translate_paragraph = lambda p, *a: (p.unicode, SimpleNamespace(placeholders=[]))

        def writeback(paragraph, tracker, translation_input, text):
            with lock:
                outputs[paragraph.unicode] = text

        translator.post_translate_paragraph = writeback
        with PriorityThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for batch in range(16):
                entries = [((SimpleNamespace(unicode=f"batch{batch}-paragraph{i}"), None, Mock(), Mock(), {}, {}), {})
                           for i in range(2)]
                futures.append(executor.submit(translator._translate_section, entries, priority=0))
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(maximum, 8)
        self.assertEqual(len(outputs), 32)
        for source, result in outputs.items():
            self.assertEqual(result, "translated " + source)

    def test_shared_cancel_marker_stops_all_eight_cli_requests(self):
        root = Path(__file__).resolve().parents[2] / ".tmp/codex-concurrency-tests"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            marker = Path(directory) / "cancel"
            barrier = threading.Barrier(8)
            processes = []

            def factory(*args, **kwargs):
                process = Mock()
                processes.append(process)

                def communicate(**kwargs):
                    barrier.wait(timeout=5)
                    marker.touch()
                    raise subprocess.TimeoutExpired("codex", 0.25)

                process.communicate.side_effect = communicate
                return process

            with (patch.object(codex_cli, "require_chatgpt_login"),
                  patch.object(codex_cli, "cli_command", return_value=["codex"]),
                  patch.object(codex_cli.subprocess, "Popen", side_effect=factory),
                  patch.object(codex_cli, "stop_process") as stop,
                  ThreadPoolExecutor(max_workers=8) as executor):
                futures = [executor.submit(codex_cli.translate, "hello", cancel_file=marker) for _ in range(8)]
                for future in futures:
                    with self.assertRaisesRegex(RuntimeError, "取消"):
                        future.result(timeout=10)
                self.assertEqual(len(processes), 8)
                self.assertEqual(stop.call_count, 8)
