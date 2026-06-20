# wally_v2/core/llm/factory.py
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from wally_v2.core.llm.base import BaseLLMClient

if TYPE_CHECKING:
    from bot.config import LLMRoleConfig  # réutilise la config existante
    from bot.db.database import Database


def create_llm_client(llm_config: "LLMRoleConfig", db: "Database") -> BaseLLMClient:
    """Instancie le bon client LLM selon le provider configuré."""
    provider = llm_config.provider.lower()

    if provider == "deepseek":
        from bot.core.llm.deepseek import DeepSeekLLMClient
        client = DeepSeekLLMClient(
            model=llm_config.model,
            db=db,
            temperature=getattr(llm_config, "temperature", 1.0),
            max_tokens=getattr(llm_config, "max_tokens", 2048),
            thinking_type=getattr(llm_config, "thinking_type", "disabled"),
            thinking_effort=getattr(llm_config, "thinking_effort", "low"),
        )
        logger.info(
            "Created DeepSeekLLMClient — model={model}, thinking={thinking}",
            model=llm_config.model,
            thinking=getattr(llm_config, "thinking_type", "disabled"),
        )
        return client

    if provider in ("claude", "anthropic"):
        from bot.core.llm.claude_client import ClaudeLLMClient
        return ClaudeLLMClient(
            model=llm_config.model, db=db,
            temperature=getattr(llm_config, "temperature", 0.8),
            max_tokens=getattr(llm_config, "max_tokens", 2048),
        )

    # Défaut OpenAI
    from bot.core.llm.openai_client import OpenAILLMClient
    return OpenAILLMClient(
        model=llm_config.model, db=db,
        temperature=getattr(llm_config, "temperature", 0.8),
        max_tokens=getattr(llm_config, "max_tokens", 2048),
    )
