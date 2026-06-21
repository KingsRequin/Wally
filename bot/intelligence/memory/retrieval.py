# bot/intelligence/memory/retrieval.py
"""Récupération de faits — FTS5 + scoring Generative-Agents (porté de jarvis-OS).

Remplace l'ancien chemin Qdrant. Le score d'un fait pour une requête est le
produit de quatre signaux (Generative Agents, Park et al.) :

    score = importance × récence × pertinence × confiance

- importance : noté par le LLM à l'ingestion [0,1].
- récence    : décroissance exponentielle par demi-vie selon la catégorie.
- pertinence : décroît avec le rang BM25 (FTS5 renvoie déjà les meilleurs d'abord).
- confiance  : accumulée par les confirmations (réconciliation).
"""
from __future__ import annotations

import math
from datetime import datetime

from loguru import logger

from bot.intelligence.memory.facts import AtomicFact, FactCategory, SQLiteFactStore

# Demi-vie de la récence (en jours) par catégorie : un souvenir d'identité
# reste pertinent longtemps, une pensée ou une émotion s'estompe vite.
_HALF_LIFE_DAYS: dict[FactCategory, float] = {
    FactCategory.FAIT:    365.0,
    FactCategory.LANG:    365.0,
    FactCategory.REL:     180.0,
    FactCategory.GOAL:    120.0,
    FactCategory.PREF:     90.0,
    FactCategory.DESIRE:   30.0,
    FactCategory.EMOTION:  14.0,
    FactCategory.THOUGHT:   7.0,
}


def _age_days(last_seen: datetime) -> float:
    """Âge d'un fait en jours, robuste au mélange aware/naive."""
    ref = last_seen.replace(tzinfo=None) if last_seen.tzinfo else last_seen
    delta = datetime.utcnow() - ref
    return max(0.0, delta.total_seconds() / 86400.0)


def _recency(fact: AtomicFact) -> float:
    half_life = _HALF_LIFE_DAYS.get(fact.category, 90.0)
    return 0.5 ** (_age_days(fact.last_seen_at) / half_life)


def _ga_score(fact: AtomicFact, relevance: float) -> float:
    return max(0.0, fact.importance) * _recency(fact) * relevance * max(0.0, fact.confidence)


class MemoryRetrieval:
    """Façade FTS5 pour l'écriture et la recherche de faits atomiques."""

    def __init__(self, fact_store: SQLiteFactStore) -> None:
        self._facts = fact_store

    async def add_fact(self, fact: AtomicFact) -> int:
        """Persiste un fait en SQLite (FTS5 maintenu par les triggers)."""
        return await self._facts.add(fact)

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
        min_confidence: float = 0.3,
        categories: list[FactCategory] | None = None,
    ) -> list[AtomicFact]:
        """Recherche FTS5 BM25 → re-tri par score Generative-Agents.

        Sans hit FTS (requête vide ou aucun match), repli sur les faits récents
        de l'utilisateur, classés par importance × récence × confiance.
        """
        hits = await self._facts.search_fts(
            user_id, query, limit=max(limit * 2, 20), min_confidence=min_confidence
        )

        if not hits:
            facts = await self._facts.get_by_user(
                user_id, min_confidence=min_confidence, categories=categories
            )
            facts.sort(key=lambda f: _ga_score(f, relevance=0.5), reverse=True)
            return facts[:limit]

        # Pertinence : décroît avec le rang BM25 (hits déjà triés meilleur→pire).
        scored: list[tuple[AtomicFact, float]] = []
        for i, (fact, _bm25) in enumerate(hits):
            if categories and fact.category not in categories:
                continue
            relevance = math.exp(-0.4 * i)
            scored.append((fact, _ga_score(fact, relevance)))

        scored.sort(key=lambda t: t[1], reverse=True)
        top = [f for f, _ in scored[:limit]]

        for fact in top:
            if fact.id:
                await self._facts.mark_seen(fact.id)

        logger.debug("memory.search user={} query={!r} -> {} faits", user_id, query, len(top))
        return top
