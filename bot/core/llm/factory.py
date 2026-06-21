# bot/core/llm/factory.py
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from bot.core.llm.base import BaseLLMClient

if TYPE_CHECKING:
    from bot.config import LLMRoleConfig
    from bot.db.database import Database


def create_llm_client(llm_config: "LLMRoleConfig", db: "Database") -> BaseLLMClient:
    """Instantiate the text LLM client. DeepSeek is the only supported text provider.

    OpenAI is reserved for image generation and is constructed directly in
    bot/bootstrap.py — never through this factory.
    """
    provider = llm_config.provider.lower()

    if provider == "deepseek":
        from bot.core.llm.deepseek import DeepSeekLLMClient
        client = DeepSeekLLMClient(
            model=llm_config.model,
            db=db,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
            thinking_type=llm_config.thinking_type,
            thinking_effort=llm_config.thinking_effort,
        )
        logger.info(
            "Created DeepSeekLLMClient — model={model}, temp={temp}, thinking={tt}/{te}",
            model=llm_config.model, temp=llm_config.temperature,
            tt=llm_config.thinking_type, te=llm_config.thinking_effort,
        )
        return client

    raise ValueError(
        f"Unknown text LLM provider: {provider!r}. Only 'deepseek' is supported "
        "(OpenAI is image-only, constructed directly in bootstrap)."
    )
