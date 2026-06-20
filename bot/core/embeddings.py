# bot/core/embeddings.py
from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Awaitable, Callable

from loguru import logger

_EMBEDDING_MODEL = "text-embedding-3-small"
_CACHE_MAX = 1000


async def make_embedding_fn(openai_client, db) -> Callable[[str], Awaitable[list[float]]]:
    """Construit une fonction d'embedding OpenAI partagée (cache LRU + log coût).

    openai_client : objet exposant .embeddings.create(model=, input=) (SDK OpenAI brut).
    db            : Database avec log_cost(...).
    """
    cache: "OrderedDict[str, list[float]]" = OrderedDict()

    async def embed(text: str) -> list[float]:
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        try:
            resp = await openai_client.embeddings.create(model=_EMBEDDING_MODEL, input=text)
            vector = resp.data[0].embedding
        except Exception as e:
            logger.warning("Embedding failed: {e}", e=e)
            raise
        try:
            usage = getattr(resp, "usage", None)
            tokens = getattr(usage, "total_tokens", 0) if usage else 0
            await db.log_cost(
                model=_EMBEDDING_MODEL, input_tokens=tokens, output_tokens=0,
                cost_usd=(tokens / 1_000_000) * 0.02, purpose="embedding", user_id=None,
            )
        except Exception as e:
            logger.debug("Embedding cost log failed (non-fatal): {e}", e=e)
        cache[key] = vector
        if len(cache) > _CACHE_MAX:
            cache.popitem(last=False)
        return vector

    return embed
