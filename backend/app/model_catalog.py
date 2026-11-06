"""按需查询引擎模型目录，不保存凭据、不发起模型推理。"""

import asyncio
import json
import subprocess

import httpx

from .codex_cli import CREATE_FLAGS, account_environment, cli_command, require_chatgpt_login
from .engines import EngineConfig, OLLAMA_HOST, openai_compat_base_url


async def codex_models() -> list[str]:
    await asyncio.to_thread(require_chatgpt_login)
    process = await asyncio.create_subprocess_exec(
        *cli_command(), "app-server", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=account_environment(), creationflags=CREATE_FLAGS,
    )

    async def send(message):
        process.stdin.write((json.dumps(message) + "\n").encode())
        await process.stdin.drain()

    async def request(request_id, method, params):
        await send({"id": request_id, "method": method, "params": params})
        while line := await process.stdout.readline():
            reply = json.loads(line)
            if reply.get("id") == request_id:
                if "error" in reply:
                    raise ValueError("Codex 模型目录查询失败，请检查 CLI 版本与登录状态。")
                return reply["result"]
        raise ValueError("Codex 模型目录进程已退出。")

    try:
        async with asyncio.timeout(30):
            await request(0, "initialize", {
                "clientInfo": {"name": "translation_pdf", "version": "1.0"},
            })
            await send({"method": "initialized", "params": {}})
            models = []
            cursor = None
            for request_id in range(1, 101):
                result = await request(request_id, "model/list", {
                    "limit": 100, "cursor": cursor, "includeHidden": False,
                })
                models.extend(item["model"] for item in result["data"] if not item.get("hidden"))
                cursor = result.get("nextCursor")
                if not cursor:
                    return models
            raise ValueError("Codex 模型目录分页超出范围。")
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


async def list_models(config: EngineConfig) -> list[str]:
    if config.type == "codex":
        models = await codex_models()
    else:
        if config.type != "ollama" and not config.api_key:
            raise ValueError("请先填写 API Key。")
        params = {}
        headers = {}
        if config.type == "ollama":
            url = f"{(config.host or OLLAMA_HOST).rstrip('/')}/api/tags"
        elif config.type == "gemini":
            url = "https://generativelanguage.googleapis.com/v1beta/models"
            headers = {"x-goog-api-key": config.api_key}
            params = {"pageSize": 1000}
        elif config.type == "claude":
            url = "https://api.anthropic.com/v1/models"
            headers = {"x-api-key": config.api_key, "anthropic-version": "2023-06-01"}
            params = {"limit": 1000}
        else:
            url = f"{openai_compat_base_url(config).rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {config.api_key}"}
        models = []
        async with httpx.AsyncClient(timeout=20) as client:
            for _ in range(100):
                response = await client.get(url, headers=headers, params=params)
                if response.status_code != 200:
                    # 不返回上游正文或异常 URL，避免泄露凭据。
                    raise ValueError(f"模型目录查询失败（HTTP {response.status_code}）。")
                payload = response.json()
                if config.type == "ollama":
                    models.extend(item["name"] for item in payload.get("models", []))
                elif config.type == "gemini":
                    models.extend(
                        item["name"].removeprefix("models/")
                        for item in payload.get("models", [])
                        if "generateContent" in item.get("supportedGenerationMethods", [])
                    )
                else:
                    models.extend(item["id"] for item in payload.get("data", []))
                if config.type == "gemini" and payload.get("nextPageToken"):
                    params["pageToken"] = payload["nextPageToken"]
                elif config.type == "claude" and payload.get("has_more"):
                    params["after_id"] = payload["last_id"]
                else:
                    break
            else:
                raise ValueError("模型目录分页超出范围。")
    models = list(dict.fromkeys(model for model in models if isinstance(model, str) and model))
    if not models:
        raise ValueError("未获取到可用模型，保留手动输入。")
    return models
