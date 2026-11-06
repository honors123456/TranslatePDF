import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import codex_cli
from app.engines import EngineConfig, build_engine_settings


class CodexTests(unittest.TestCase):
    @patch.object(codex_cli.shutil, "which")
    def test_windows_service_finds_ide_cli_before_old_npm(self, which):
        if codex_cli.os.name != "nt":
            self.skipTest("Windows service PATH regression")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / ".vscode/extensions/openai.chatgpt-26.1007.21434-win32-x64/bin/windows-x86_64/codex.exe"
            binary.parent.mkdir(parents=True)
            binary.touch()
            which.side_effect = lambda name: {"codex.cmd": "C:/npm/codex.cmd", "node": "node.exe"}.get(name)
            with patch.dict(codex_cli.os.environ, {"USERPROFILE": directory}):
                self.assertEqual(codex_cli.cli_command(), [str(binary)])

    @patch.object(codex_cli, "require_chatgpt_login")
    @patch.object(codex_cli, "cli_command", return_value=["codex"])
    @patch.object(codex_cli, "stop_process")
    @patch.object(codex_cli.subprocess, "Popen")
    def test_nonzero_exit_preserves_structured_model_error(self, popen, *_):
        message = "The 'gpt-6-luna' model is not supported when using Codex with a ChatGPT account."
        event = {"type": "turn.failed", "error": {"message": json.dumps({"error": {"message": message}})}}
        popen.return_value.communicate.return_value = (json.dumps(event), "")
        popen.return_value.returncode = 1
        with self.assertRaisesRegex(RuntimeError, "model is not supported"):
            codex_cli.translate("hello")

    def test_error_detail_redacts_credentials(self):
        output = json.dumps({"type": "error", "message": 'denied Bearer abc123 api_key=sk-example "refresh_token":"secret"'})
        detail = codex_cli.request_error(output)
        for secret in ("abc123", "sk-example", "secret"):
            self.assertNotIn(secret, detail)
        self.assertIn("denied", detail)

    def test_only_final_message_is_translation(self):
        events = [
            {"type": "item.completed", "item": {"type": "reasoning", "text": "private"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "你好 {v1}"}},
            {"type": "turn.completed", "usage": {}},
        ]
        self.assertEqual(codex_cli.final_message("\n".join(map(json.dumps, events))), "你好 {v1}")

    def test_empty_failed_and_incomplete_responses(self):
        for output in ('{"type":"turn.completed"}', '{"type":"turn.failed"}',
                       '{"type":"item.completed","item":{"type":"agent_message","text":"partial"}}'):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                codex_cli.final_message(output)

    @patch.object(codex_cli, "cli_command", return_value=["codex"])
    @patch.object(codex_cli.subprocess, "run")
    def test_api_key_login_is_rejected(self, run, _):
        run.return_value = Mock(returncode=0, stdout="", stderr="Logged in using an API key")
        with self.assertRaises(ValueError):
            codex_cli.require_chatgpt_login()
        run.return_value.stderr = "Logged in using ChatGPT"
        codex_cli.require_chatgpt_login()

    def test_cancelled_request_never_starts_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "cancel"
            marker.touch()
            with patch.object(codex_cli, "require_chatgpt_login") as login:
                with self.assertRaises(RuntimeError):
                    codex_cli.translate("hello", cancel_file=marker)
                login.assert_not_called()

    @patch.object(codex_cli, "require_chatgpt_login")
    def test_settings_need_no_key_and_preserve_language_arguments(self, _):
        import shlex
        settings = build_engine_settings(EngineConfig(type="codex"), "en", "ja")
        command = shlex.split(settings.clitranslator_command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-6-luna")
        self.assertEqual(command[command.index("--lang-out") + 1], "ja")
        settings.validate_settings()

    @patch.dict(codex_cli.os.environ, {"OPENAI_API_KEY": "test", "CODEX_API_KEY": "test"})
    def test_no_api_key_in_child_environment(self):
        env = codex_cli.account_environment()
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_API_KEY", env)

    @patch.object(codex_cli, "require_chatgpt_login")
    @patch.object(codex_cli, "cli_command", return_value=["codex"])
    @patch.object(codex_cli, "stop_process")
    @patch.object(codex_cli.subprocess, "Popen")
    def test_timeout_stops_process(self, popen, stop, *_):
        process = popen.return_value
        with self.assertRaises(TimeoutError):
            codex_cli.translate("hello", timeout=0)
        stop.assert_called_once_with(process)

    @patch.object(codex_cli, "require_chatgpt_login")
    @patch.object(codex_cli, "cli_command", return_value=["codex"])
    @patch.object(codex_cli, "stop_process")
    @patch.object(codex_cli.subprocess, "Popen")
    def test_cancel_during_request_stops_process(self, popen, stop, *_):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "cancel"
            def cancel(**kwargs):
                marker.touch()
                raise subprocess.TimeoutExpired("codex", 0.25)
            popen.return_value.communicate.side_effect = cancel
            with self.assertRaises(RuntimeError):
                codex_cli.translate("hello", cancel_file=marker)
            stop.assert_called_once_with(popen.return_value)


if __name__ == "__main__":
    unittest.main()
