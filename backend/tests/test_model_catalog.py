import asyncio
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main, model_catalog
from app.engines import EngineConfig


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_headers_pagination_and_filtering(self):
        cases = [
            ("deepseek", "Authorization", {"data": [{"id": "new-model"}]}),
            ("claude", "x-api-key", {"data": [{"id": "new-model"}]}),
            ("gemini", "x-goog-api-key", {"models": [
                {"name": "models/new-model", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]},
            ]}),
            ("ollama", None, {"models": [{"name": "new-model"}]}),
        ]
        original = httpx.AsyncClient
        for engine, header, payload in cases:
            def respond(request):
                if header:
                    self.assertIn("secret", request.headers[header])
                return httpx.Response(200, json=payload)
            with patch.object(model_catalog.httpx, "AsyncClient", side_effect=lambda **kw: original(
                transport=httpx.MockTransport(respond), **kw,
            )):
                self.assertEqual(await model_catalog.list_models(
                    EngineConfig(type=engine, api_key="secret")), ["new-model"])

    async def test_gemini_pagination(self):
        original = httpx.AsyncClient
        calls = []

        def respond(request):
            calls.append(request)
            model = "second" if "pageToken" in request.url.params else "first"
            result = {"models": [{"name": f"models/{model}",
                                  "supportedGenerationMethods": ["generateContent"]}]}
            if model == "first":
                result["nextPageToken"] = "next"
            return httpx.Response(200, json=result)

        with patch.object(model_catalog.httpx, "AsyncClient", side_effect=lambda **kw: original(
            transport=httpx.MockTransport(respond), **kw,
        )):
            self.assertEqual(await model_catalog.list_models(
                EngineConfig(type="gemini", api_key="secret")), ["first", "second"])
        self.assertEqual(len(calls), 2)

    async def test_errors_do_not_expose_keys(self):
        with patch.object(main, "list_models", side_effect=httpx.ConnectError("secret")):
            with self.assertRaises(main.HTTPException) as result:
                await main.engine_models(EngineConfig(type="gemini", api_key="secret"))
        self.assertNotIn("secret", result.exception.detail)
        with patch.object(model_catalog, "codex_models", AsyncMock(return_value=[])):
            with self.assertRaises(ValueError):
                await model_catalog.list_models(EngineConfig(type="codex"))

    async def test_codex_handshake_pagination_and_cleanup(self):
        reader = asyncio.StreamReader()
        for reply in [
            {"id": 0, "result": {}},
            {"method": "notification"},
            {"id": 1, "result": {"data": [{"model": "first"}], "nextCursor": "next"}},
            {"id": 2, "result": {"data": [{"model": "second"}], "nextCursor": None}},
        ]:
            reader.feed_data((json.dumps(reply) + "\n").encode())
        reader.feed_eof()
        messages = []
        process = SimpleNamespace(
            stdin=SimpleNamespace(write=messages.append, drain=AsyncMock()), stdout=reader,
            returncode=None, kill=lambda: messages.append(b"killed"), wait=AsyncMock(),
        )
        with patch.object(model_catalog, "require_chatgpt_login"), \
             patch.object(model_catalog, "cli_command", return_value=["codex"]), \
             patch.object(model_catalog.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
            self.assertEqual(await model_catalog.codex_models(), ["first", "second"])
        self.assertEqual(json.loads(messages[1])["method"], "initialized")
        self.assertEqual(json.loads(messages[3])["params"]["cursor"], "next")
        process.wait.assert_awaited_once()

    async def test_upload_above_100mb_keeps_chunked_io(self):
        # 101 MB 流式上传；实际写入重定向到计数器，不创建大文件或启动翻译。
        chunk = b"x" * (1024 * 1024)
        upload = UploadFile(filename="large.pdf", file=io.BytesIO())
        upload.read = AsyncMock(side_effect=[chunk] * 101 + [b""])
        written = []

        class Sink:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, data):
                written.append(len(data))

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / ".tmp") as directory, \
             patch.object(main, "UPLOAD_DIR", Path(directory)), \
             patch.object(Path, "open", return_value=Sink()), \
             patch.object(main.manager, "create", return_value=SimpleNamespace(snapshot=lambda: {"id": "ok"})):
            result = await main.create_task(upload, '{"type":"codex"}', "en", "zh", None)
        self.assertEqual(result, {"id": "ok"})
        self.assertEqual(sum(written), 101 * 1024 * 1024)
        self.assertTrue(all(call.args == (1024 * 1024,) for call in upload.read.call_args_list))
