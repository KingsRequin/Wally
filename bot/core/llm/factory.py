# bot/core/llm/factory.py
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from bot.core.llm.base import BaseLLMClient

if TYPE_CHECKING:
    from bot.config import LLMRoleConfig
    from bot.db.database import Database


def create_llm_client(llm_config: "LLMRoleConfig", db: "Database") -> BaseLLMClient:
    """Instantiate the right LLM client based on provider config."""
    provider = llm_config.provider.lower()

    if provider == "claude" or provider == "anthropic":
        from bot.core.llm.claude_client import ClaudeLLMClient
        client = ClaudeLLMClient(
            model=llm_config.model,
            db=db,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )
        logger.info(
            "Created ClaudeLLMClient — model={model}, temp={temp}",
            model=llm_config.model, temp=llm_config.temperature,
        )
        return client

    elif provider == "openai":
        from bot.core.llm.openai_client import OpenAILLMClient
        client = OpenAILLMClient(
            model=llm_config.model,
            db=db,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
            reasoning_effort=llm_config.reasoning_effort,
            text_verbosity=llm_config.text_verbosity,
        )
        logger.info(
            "Created OpenAILLMClient — model={model}, temp={temp}",
            model=llm_config.model, temp=llm_config.temperature,
        )
        return client

    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Use 'openai' or 'claude'.")
