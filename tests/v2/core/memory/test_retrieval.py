"""Tests MemoryRetrieval — FTS5 + scoring Generative-Agents (post-Qdrant)."""
import pytest

from bot.v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore
from bot.v2.core.memory.retrieval import MemoryRetrieval, _ga_score, _recency


def _fact(content, category=FactCategory.PREF, **kw):
    return AtomicFact(user_id="discord:123", content=content, category=category, **kw)


@pytest.mark.asyncio
async def test_add_fact_stores_in_sqlite(tmp_db_path):
    retrieval = MemoryRetrieval(SQLiteFactStore(tmp_db_path))
    fact_id = await retrieval.add_fact(_fact("aime le café"))
    assert fact_id > 0
    # retrouvable par FTS via search
    results = await retrieval.search("café", "discord:123", limit=5)
    assert any("café" in f.content for f in results)


@pytest.mark.asyncio
async def test_search_returns_facts_by_fts_match(tmp_db_path):
    store = SQLiteFactStore(tmp_db_path)
    retrieval = MemoryRetrieval(store)
    await retrieval.add_fact(_fact("aime le café"))
    await retrieval.add_fact(_fact("déteste les bugs"))

    results = await retrieval.search("café", "discord:123", limit=5)
    assert len(results) == 1
    assert results[0].content == "aime le café"


@pytest.mark.asyncio
async def test_search_fallback_when_no_fts_hit(tmp_db_path):
    """Requête sans match FTS → repli sur les faits récents (get_by_user)."""
    store = SQLiteFactStore(tmp_db_path)
    retrieval = MemoryRetrieval(store)
    await retrieval.add_fact(_fact("fait en mémoire", category=FactCategory.FAIT))

    results = await retrieval.search("zzzzznomatch", "discord:123", limit=5)
    assert any(f.content == "fait en mémoire" for f in results)


@pytest.mark.asyncio
async def test_search_excludes_low_confidence(tmp_db_path):
    store = SQLiteFactStore(tmp_db_path)
    retrieval = MemoryRetrieval(store)
    await retrieval.add_fact(_fact("note peu sûre", confidence=0.1))

    results = await retrieval.search("note", "discord:123", min_confidence=0.5)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_search_scoped_by_user(tmp_db_path):
    store = SQLiteFactStore(tmp_db_path)
    retrieval = MemoryRetrieval(store)
    await store.add(AtomicFact(user_id="discord:1", content="alice aime le jazz", category=FactCategory.PREF))
    await store.add(AtomicFact(user_id="discord:2", content="bob aime le jazz", category=FactCategory.PREF))

    results = await retrieval.search("jazz", "discord:1", limit=5)
    assert len(results) == 1 and results[0].user_id == "discord:1"


@pytest.mark.asyncio
async def test_ga_ranking_importance(tmp_db_path):
    """À pertinence FTS égale, le fait le plus important sort en tête."""
    store = SQLiteFactStore(tmp_db_path)
    retrieval = MemoryRetrieval(store)
    await retrieval.add_fact(_fact("apex anecdote", importance=0.2))
    await retrieval.add_fact(_fact("apex pivot", importance=0.9))

    results = await retrieval.search("apex", "discord:123", limit=5)
    assert results[0].content == "apex pivot"


def test_recency_decays_with_age():
    from datetime import datetime, timedelta
    fresh = _fact("x", category=FactCategory.EMOTION)
    fresh.last_seen_at = datetime.utcnow()
    old = _fact("y", category=FactCategory.EMOTION)
    old.last_seen_at = datetime.utcnow() - timedelta(days=14)  # 1 demi-vie EMOTION
    assert _recency(fresh) > _recency(old)
    assert _recency(old) == pytest.approx(0.5, abs=0.05)


def test_ga_score_is_product_of_signals():
    from datetime import datetime
    f = _fact("x", confidence=0.8, importance=0.5, category=FactCategory.FAIT)
    f.last_seen_at = datetime.utcnow()
    # récence ≈ 1 (fraîche), relevance = 1 → score ≈ importance × confidence
    assert _ga_score(f, relevance=1.0) == pytest.approx(0.5 * 0.8, abs=0.02)
