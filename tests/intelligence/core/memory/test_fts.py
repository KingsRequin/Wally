"""Phase 1 du port mémoire jarvis-OS : kernel FTS5 + modèle S-P-O.

Vérifie la recherche plein-texte BM25 (remplace Qdrant), la persistance du
triplet sujet-prédicat-objet, et le renforcement sans duplication (confirm).
"""
import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.memory.facts import (
    AtomicFact, FactCategory, FactStatus, SQLiteFactStore, _fts_match_query,
)


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "wally_test.db")
    await create_v2_tables(db_path)
    return SQLiteFactStore(db_path)


def _fact(user_id, content, category=FactCategory.FAIT, **kw):
    return AtomicFact(user_id=user_id, content=content, category=category, **kw)


@pytest.mark.asyncio
async def test_spo_fields_persist(store):
    fid = await store.add(_fact(
        "discord:1", "KingsRequin joue à Apex",
        category=FactCategory.FAIT,
        subject="KingsRequin", predicate="plays", object_="Apex",
        importance=0.8,
    ))
    facts = await store.get_by_user("discord:1")
    assert len(facts) == 1
    f = facts[0]
    assert f.id == fid
    assert f.subject == "KingsRequin" and f.predicate == "plays" and f.object_ == "Apex"
    assert f.importance == 0.8 and f.support_count == 1


@pytest.mark.asyncio
async def test_fts_finds_by_keyword(store):
    await store.add(_fact("discord:1", "KingsRequin adore le café"))
    await store.add(_fact("discord:1", "KingsRequin déteste les bugs"))
    hits = await store.search_fts("discord:1", "café", limit=5)
    assert len(hits) == 1
    fact, rank = hits[0]
    assert "café" in fact.content
    assert isinstance(rank, float)


@pytest.mark.asyncio
async def test_fts_diacritics_insensitive(store):
    await store.add(_fact("discord:1", "KingsRequin adore le café"))
    # requête sans accent doit matcher le contenu accentué (remove_diacritics)
    hits = await store.search_fts("discord:1", "cafe", limit=5)
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_fts_scoped_by_user(store):
    await store.add(_fact("discord:1", "Alice aime le jazz"))
    await store.add(_fact("discord:2", "Bob aime le jazz"))
    hits = await store.search_fts("discord:1", "jazz", limit=5)
    assert len(hits) == 1
    assert hits[0][0].user_id == "discord:1"


@pytest.mark.asyncio
async def test_fts_indexes_spo_triplet(store):
    # le sujet/objet du triplet sont indexés même si absents de `content`
    await store.add(_fact(
        "discord:1", "note",
        subject="Kaelis", predicate="plays", object_="Minecraft",
    ))
    hits = await store.search_fts("discord:1", "Minecraft", limit=5)
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_confirm_reinforces_without_duplicate(store):
    fid = await store.add(_fact("discord:1", "KingsRequin aime le café", confidence=0.6))
    await store.confirm(fid)
    facts = await store.get_by_user("discord:1")
    assert len(facts) == 1  # pas de doublon
    assert facts[0].support_count == 2
    assert facts[0].confidence == pytest.approx(0.65)


@pytest.mark.asyncio
async def test_fts_empty_query_returns_nothing(store):
    await store.add(_fact("discord:1", "KingsRequin aime le café"))
    assert await store.search_fts("discord:1", "   ", limit=5) == []
    assert await store.search_fts("discord:1", "!!! ??", limit=5) == []


def test_fts_match_query_sanitization():
    assert _fts_match_query("café crème!") == '"café" OR "crème"'
    assert _fts_match_query("le la de") == ""      # que des stopwords
    assert _fts_match_query("") == ""
    assert _fts_match_query("Apex?!") == '"apex"'
