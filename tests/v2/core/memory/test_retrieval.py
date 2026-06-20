"""Tests MemoryRetrieval — intégration SQLite + Qdrant mocké."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore
from bot.v2.core.memory.store import QdrantEmbeddingStore, SearchHit
from bot.v2.core.memory.retrieval import MemoryRetrieval


@pytest.mark.asyncio
async def test_add_fact_stores_in_sqlite_and_qdrant(tmp_db_path):
    """add_fact() écrit en SQLite ET dans Qdrant."""
    fact_store = SQLiteFactStore(tmp_db_path)
    qdrant_store = MagicMock()
    qdrant_store.ensure_collection = AsyncMock()
    qdrant_store.upsert = AsyncMock()

    retrieval = MemoryRetrieval(fact_store, qdrant_store)
    fact = AtomicFact(user_id="discord:123", content="test", category=FactCategory.PREF)
    fact_id = await retrieval.add_fact(fact)

    assert fact_id > 0
    qdrant_store.upsert.assert_called_once_with(
        fact_id=fact_id, user_id="discord:123", content="test"
    )


@pytest.mark.asyncio
async def test_search_returns_facts_by_semantic_similarity(tmp_db_path):
    """search() combine Qdrant hits avec SQLite pour retourner des AtomicFacts."""
    fact_store = SQLiteFactStore(tmp_db_path)
    fact = AtomicFact(user_id="discord:123", content="Aime le café", category=FactCategory.PREF)
    fact_id = await fact_store.add(fact)

    qdrant_store = MagicMock()
    qdrant_store.search = AsyncMock(return_value=[SearchHit(id=fact_id, score=0.9)])

    retrieval = MemoryRetrieval(fact_store, qdrant_store)
    results = await retrieval.search("café", "discord:123", limit=5)

    assert len(results) == 1
    assert results[0].content == "Aime le café"


@pytest.mark.asyncio
async def test_search_fallback_when_qdrant_empty(tmp_db_path):
    """Si Qdrant retourne rien, search() retombe sur get_by_user SQLite."""
    fact_store = SQLiteFactStore(tmp_db_path)
    await fact_store.add(AtomicFact(
        user_id="discord:123", content="Fait en SQLite", category=FactCategory.FAIT
    ))

    qdrant_store = MagicMock()
    qdrant_store.search = AsyncMock(return_value=[])  # Qdrant vide

    retrieval = MemoryRetrieval(fact_store, qdrant_store)
    results = await retrieval.search("quelque chose", "discord:123", limit=5)

    assert any(f.content == "Fait en SQLite" for f in results)


@pytest.mark.asyncio
async def test_search_excludes_low_confidence(tmp_db_path):
    """search() exclut les faits sous min_confidence."""
    fact_store = SQLiteFactStore(tmp_db_path)
    low = AtomicFact(user_id="discord:123", content="Low conf",
                     category=FactCategory.PREF, confidence=0.1)
    low_id = await fact_store.add(low)

    qdrant_store = MagicMock()
    qdrant_store.search = AsyncMock(return_value=[SearchHit(id=low_id, score=0.95)])

    retrieval = MemoryRetrieval(fact_store, qdrant_store)
    results = await retrieval.search("test", "discord:123", min_confidence=0.5)

    assert len(results) == 0
