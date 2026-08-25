# bot/core/llm/factory.py
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from bot.core.llm.base import BaseLLMClient

if TYPE_CHECKING:
    from bot.config import LLMRoleConfig
    from bot.db.database import Database


# Les providers de TEXTE que cette factory sait construire — source de vérité
# unique. Elle vivait auparavant dans `config.py` sous le nom
# `VALID_LLM_PROVIDERS`, avec la valeur `("openai", "claude")` : ni l'une ni
# l'autre n'existe ici, la constante n'était lue nulle part, et le dashboard
# proposait ces deux-là. Sauvegarder le panneau LLM levait donc une `ValueError`
# APRÈS avoir déjà muté la config en mémoire — le `config.save()` suivant, venu
# de n'importe quel autre bouton, gravait un provider inconnu dans `config.yaml`
# et le bot ne redémarrait plus.
#
# Une liste tenue à côté du `if` qu'elle décrit ne peut plus diverger de lui.
SUPPORTED_TEXT_PROVIDERS = ("deepseek", "openai")


def create_llm_client(llm_config: "LLMRoleConfig", db: "Database") -> BaseLLMClient:
    """Instancie le client LLM de TEXTE pour un rôle donné.

    Deux fournisseurs : `deepseek` et `openai`. Le second n'était pas branché ici
    alors que `OpenAILLMClient` implémente `BaseLLMClient` en entier et tourne
    déjà en production pour la vision et les images — il ne manquait que cette
    branche pour qu'un rôle texte puisse le désigner.

    La génération d'IMAGES reste construite directement dans `bot/bootstrap.py`
    (`image_client`) : elle a sa propre config et n'est pas un rôle de texte.
    """
    provider = llm_config.provider.lower()

    if provider == "openai":
        from bot.core.llm.openai_client import OpenAILLMClient
        client_openai = OpenAILLMClient(
            model=llm_config.model,
            db=db,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
            reasoning_effort=llm_config.reasoning_effort,
            text_verbosity=llm_config.text_verbosity,
        )
        logger.info(
            "Created OpenAILLMClient — model={model}, temp={temp}, "
            "reasoning={effort}, verbosity={verb}",
            model=llm_config.model, temp=llm_config.temperature,
            effort=llm_config.reasoning_effort, verb=llm_config.text_verbosity,
        )
        return client_openai

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
        f"Fournisseur LLM de texte inconnu : {provider!r}. "
        f"Supportés : {', '.join(SUPPORTED_TEXT_PROVIDERS)}."
    )
