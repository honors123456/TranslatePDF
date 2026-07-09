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
