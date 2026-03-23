# bot/core/openai_client.py
# Backward-compatibility shim — imports redirect to bot.core.llm.openai_client
from bot.core.llm.openai_client import (
    OpenAILLMClient as OpenAIClient,
    estimate_cost,
    _uses_responses_api,
    MODEL_COSTS,
    FALLBACK_COST,
    IMAGE_COSTS,
    _tools_for_responses_api,
)
from bot.core.llm.base import FALLBACK_RESPONSE, FALLBACK_IMAGE_RESPONSE

__all__ = [
    "OpenAIClient",
    "estimate_cost",
    "_uses_responses_api",
    "MODEL_COSTS",
    "FALLBACK_COST",
    "IMAGE_COSTS",
    "FALLBACK_RESPONSE",
    "FALLBACK_IMAGE_RESPONSE",
]
