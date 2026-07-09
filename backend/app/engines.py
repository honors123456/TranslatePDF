"""翻译引擎适配层：把前端传来的引擎配置映射为 pdf2zh-next 的引擎设置。

BYOK：api_key 只在内存中构造设置对象，不落盘、不写日志。
"""

from pydantic import BaseModel

from pdf2zh_next.config.translate_engine_model import (
    DeepSeekSettings,
    GeminiSettings,
    OpenAICompatibleSettings,
)

# Anthropic 官方 OpenAI 兼容端点（pdf2zh-next 无 Anthropic 直连类）
ANTHROPIC_OPENAI_COMPAT_BASE_URL = "https://api.anthropic.com/v1/"
# Gemini 官方 OpenAI 兼容端点（仅用于连通性测试；翻译走 pdf2zh 原生 GeminiSettings）
GEMINI_OPENAI_COMPAT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "claude": "claude-opus-4-8",
    "gemini": "gemini-2.5-flash",
}


class EngineConfig(BaseModel):
    type: str  # deepseek | openai_compatible | claude | gemini
    api_key: str
    model: str | None = None
    base_url: str | None = None  # 仅 openai_compatible 需要


def build_engine_settings(config: EngineConfig):
    model = config.model or DEFAULT_MODELS.get(config.type)
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
