# bot/v2/core/memory/retrieval.py
from __future__ import annotations

from loguru import logger

from bot.v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore
from bot.v2.core.memory.store import QdrantEmbeddingStore


class MemoryRetrieval:
    """Façade hybride SQLite + Qdrant pour la recherche de faits atomiques."""

    def __init__(self, fact_store: SQLiteFactStore, qdrant_store: QdrantEmbeddingStore) -> None:
        self._facts = fact_store
        self._qdrant = qdrant_store

    async def add_fact(self, fact: AtomicFact) -> int:
        """Persiste un fait en SQLite + indexe l'embedding dans Qdrant."""
        fact_id = await self._facts.add(fact)
        await self._qdrant.ensure_collection()
        await self._qdrant.upsert(fact_id=fact_id, user_id=fact.user_id, content=fact.content)
        return fact_id

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
        min_confidence: float = 0.3,
        categories: list[FactCategory] | None = None,
    ) -> list[AtomicFact]:
        """Recherche sémantique Qdrant → charge + filtre depuis SQLite."""
        hits = await self._qdrant.search(query=query, user_id=user_id, limit=limit * 2)

        if not hits:
            # Fallback : faits les plus récents depuis SQLite
            return await self._facts.get_by_user(
                user_id, min_confidence=min_confidence, categories=categories
            )

        # Charger depuis SQLite, filtrer par confiance
        fact_ids = [h.id for h in hits]
        loaded = await self._facts.get_by_ids(fact_ids, min_confidence=min_confidence)

        if categories:
            loaded = [f for f in loaded if f.category in categories]

        # Re-trier : score Qdrant × confidence SQLite
        id_to_score = {h.id: h.score for h in hits}
        loaded.sort(key=lambda f: id_to_score.get(f.id, 0.0) * f.confidence, reverse=True)

        # Renforcer les faits utilisés
        for fact in loaded[:limit]:
            if fact.id:
                await self._facts.mark_seen(fact.id)

        return loaded[:limit]
