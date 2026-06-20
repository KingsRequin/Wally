# bot/core/llm/__init__.py
from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE, FALLBACK_IMAGE_RESPONSE

__all__ = [
    "BaseLLMClient",
    "FALLBACK_RESPONSE",
    "FALLBACK_IMAGE_RESPONSE",
    "OpenAILLMClient",
    "create_llm_client",
]


def __getattr__(name: str):
    # Lazy imports to avoid circular dependencies and heavy SDK loads at import time
    if name == "OpenAILLMClient":
        from bot.core.llm.openai_client import OpenAILLMClient
        return OpenAILLMClient
    if name == "create_llm_client":
        from bot.core.llm.factory import create_llm_client
        return create_llm_client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
