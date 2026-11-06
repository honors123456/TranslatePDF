"""翻译引擎适配层：把前端传来的引擎配置映射为 pdf2zh-next 的引擎设置。

BYOK：api_key 只在内存中构造设置对象，不落盘、不写日志。
"""

import asyncio
import shlex
import sys
from pathlib import Path

from pydantic import BaseModel

from pdf2zh_next.config.translate_engine_model import (
    CLISettings,
    DeepSeekSettings,
    GeminiSettings,
    OllamaSettings,
    OpenAICompatibleSettings,
)

# Anthropic 官方 OpenAI 兼容端点（pdf2zh-next 无 Anthropic 直连类）
ANTHROPIC_OPENAI_COMPAT_BASE_URL = "https://api.anthropic.com/v1/"
# Gemini 官方 OpenAI 兼容端点（仅用于连通性测试；翻译走 pdf2zh 原生 GeminiSettings）
GEMINI_OPENAI_COMPAT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
OLLAMA_HOST = "http://127.0.0.1:11434"

DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "claude": "claude-opus-4-8",
    "gemini": "gemini-2.5-flash",
    "ollama": "translategemma:12b",
    "codex": "gpt-6-luna",
}


class EngineConfig(BaseModel):
    type: str  # deepseek | openai_compatible | claude | gemini | ollama | codex
    api_key: str = ""
    model: str | None = None
    base_url: str | None = None  # 仅 openai_compatible 需要
    host: str | None = None  # 仅 ollama 需要


def build_engine_settings(
    config: EngineConfig,
    lang_in: str = "en",
    lang_out: str = "zh",
    cancel_file: Path | None = None,
):
    model = config.model or DEFAULT_MODELS.get(config.type)
    if config.type == "codex":
        from .codex_cli import require_chatgpt_login

        require_chatgpt_login()
        command = [
            sys.executable, str(Path(__file__).with_name("codex_cli.py")),
            "--model", model, "--lang-in", lang_in, "--lang-out", lang_out,
        ]
        if cancel_file:
            command.extend(["--cancel-file", str(cancel_file)])
        return CLISettings(
            clitranslator_command=shlex.join(command), clitranslator_timeout=270,
        )
    if config.type != "ollama" and not config.api_key:
        raise ValueError("api_key is required")
    if config.type == "deepseek":
        return DeepSeekSettings(
            deepseek_model=model,
            deepseek_api_key=config.api_key,
        )
    if config.type == "openai_compatible":
        if not config.base_url:
            raise ValueError("base_url is required for openai_compatible engine")
        if not model:
            raise ValueError("model is required for openai_compatible engine")
        return OpenAICompatibleSettings(
            openai_compatible_model=model,
            openai_compatible_base_url=config.base_url,
            openai_compatible_api_key=config.api_key,
        )
    if config.type == "claude":
        return OpenAICompatibleSettings(
            openai_compatible_model=model,
            openai_compatible_base_url=ANTHROPIC_OPENAI_COMPAT_BASE_URL,
            openai_compatible_api_key=config.api_key,
        )
    if config.type == "gemini":
        return GeminiSettings(
            gemini_model=model,
            gemini_api_key=config.api_key,
        )
    if config.type == "ollama":
        return OllamaSettings(
            ollama_model=model,
            ollama_host=config.host or OLLAMA_HOST,
        )
    raise ValueError(f"unknown engine type: {config.type}")


def openai_compat_base_url(config: EngineConfig) -> str:
    """连通性测试用：四种引擎统一映射到各自的 OpenAI 兼容端点。"""
    urls = {
        "deepseek": DEEPSEEK_BASE_URL,
        "claude": ANTHROPIC_OPENAI_COMPAT_BASE_URL,
        "gemini": GEMINI_OPENAI_COMPAT_BASE_URL,
        "openai_compatible": config.base_url,
    }
    url = urls.get(config.type)
    if not url:
        raise ValueError(f"cannot test engine type: {config.type}")
    return url


async def test_connection(config: EngineConfig) -> dict:
    """发一条最小 chat completion 验证 key 与模型可用。"""
    import httpx

    model = config.model or DEFAULT_MODELS.get(config.type)
    if not model:
        raise ValueError("model is required")
    if config.type == "codex":
        from .codex_cli import translate

        content = await asyncio.to_thread(translate, "Hello, world.", model)
        return {"ok": bool(content.strip()), "model": model}
    if config.type == "ollama":
        return await _test_ollama(config.host or OLLAMA_HOST, model)
    if not config.api_key:
        raise ValueError("api_key is required")
    base = openai_compat_base_url(config).rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={
                "model": model,
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
    if resp.status_code == 200:
        return {"ok": True, "model": model}
    detail = resp.text[:300]
    return {"ok": False, "status": resp.status_code, "detail": detail}


async def _test_ollama(host: str, model: str) -> dict:
    """确认 Ollama 服务、目标模型和实际翻译推理均可用。"""
    import httpx

    base = host.rstrip("/")
    async with httpx.AsyncClient(timeout=120) as client:
        tags_resp = await client.get(f"{base}/api/tags")
        if tags_resp.status_code != 200:
            return {
                "ok": False,
                "status": tags_resp.status_code,
                "detail": tags_resp.text[:300],
            }

        models = tags_resp.json().get("models", [])
        installed = {
            name
            for item in models
            for name in (item.get("name"), item.get("model"))
            if name
        }
        candidates = {model, f"{model}:latest"} if ":" not in model else {model}
        if installed.isdisjoint(candidates):
            return {
                "ok": False,
                "detail": f"model not installed: {model}",
            }

        prompt = (
            "You are a professional English (en) to Chinese (zh) translator. "
            "Produce only the Chinese translation, without explanations. "
            "Please translate the following English text into Chinese:\n\nHello, world."
        )
        chat_resp = await client.post(
            f"{base}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0},
            },
        )
    if chat_resp.status_code != 200:
        return {
            "ok": False,
            "status": chat_resp.status_code,
            "detail": chat_resp.text[:300],
        }
    content = chat_resp.json().get("message", {}).get("content", "").strip()
    if not content:
        return {"ok": False, "detail": "model returned an empty translation"}
    return {"ok": True, "model": model}
