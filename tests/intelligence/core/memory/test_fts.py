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


# ── #A5 : recherche sémantique globale (amorce de vagabondage ciblée) ──

@pytest.mark.asyncio
async def test_search_related_is_global_across_users(store):
    """search_related ignore le cloisonnement par user_id : un thème ramène les
    faits liés de tout le monde (≠ search_fts qui est scoped)."""
    await store.add(_fact("discord:1", "Alice adore le jazz"))
    await store.add(_fact("discord:2", "Bob joue du jazz au piano"))
    await store.add(_fact("discord:3", "Carol déteste le rap"))
    hits = await store.search_related("jazz", limit=5)
    contents = {f.content for f in hits}
    assert "Alice adore le jazz" in contents
    assert "Bob joue du jazz au piano" in contents
    assert "Carol déteste le rap" not in contents


@pytest.mark.asyncio
async def test_search_related_excludes_category(store):
    """exclude_category retire une catégorie (ex. THOUGHT) du résultat."""
    await store.add(_fact("discord:1", "le jazz c'est cool", category=FactCategory.FAIT))
    await store.add(_fact("wally:self", "je réfléchis au jazz", category=FactCategory.THOUGHT))
    hits = await store.search_related("jazz", limit=5, exclude_category=FactCategory.THOUGHT)
    assert [f.content for f in hits] == ["le jazz c'est cool"]


@pytest.mark.asyncio
async def test_search_related_empty_query(store):
    await store.add(_fact("discord:1", "le jazz c'est cool"))
    assert await store.search_related("   ", limit=5) == []


# ── #A3 : planification temporelle (scheduled_at + get_due_facts) ──

@pytest.mark.asyncio
async def test_scheduled_at_persists(store):
    from datetime import datetime, timedelta
    due = datetime.utcnow() + timedelta(hours=2)
    fid = await store.add(_fact(
        "wally:self", "rappeler à KingsRequin de stream",
        category=FactCategory.DESIRE, scheduled_at=due,
    ))
    facts = await store.get_by_user("wally:self")
    assert facts[0].id == fid
    assert facts[0].scheduled_at == due


@pytest.mark.asyncio
async def test_scheduled_at_defaults_none(store):
    await store.add(_fact("discord:1", "fait sans échéance"))
    assert (await store.get_by_user("discord:1"))[0].scheduled_at is None


@pytest.mark.asyncio
async def test_get_due_facts_returns_only_past_due(store):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    await store.add(_fact("wally:self", "rappel dû", category=FactCategory.DESIRE,
                          scheduled_at=now - timedelta(minutes=5)))
    await store.add(_fact("wally:self", "rappel futur", category=FactCategory.DESIRE,
                          scheduled_at=now + timedelta(hours=1)))
    await store.add(_fact("wally:self", "note sans échéance", category=FactCategory.DESIRE))
    due = await store.get_due_facts(now)
    assert [f.content for f in due] == ["rappel dû"]


@pytest.mark.asyncio
async def test_clear_schedule_disarms_reminder(store):
    """clear_schedule retire l'échéance sans toucher au reste du fait (#A3)."""
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    fid = await store.add(_fact("wally:self", "rappel dû", category=FactCategory.DESIRE,
                                scheduled_at=now - timedelta(minutes=5)))
    await store.clear_schedule(fid)
    assert await store.get_due_facts(now) == []
    facts = await store.get_by_user("wally:self")
    assert facts[0].scheduled_at is None
    assert facts[0].status == FactStatus.ACTIVE   # le désir survit, juste désarmé


@pytest.mark.asyncio
async def test_get_due_facts_ignores_archived(store):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    fid = await store.add(_fact("wally:self", "rappel archivé", category=FactCategory.DESIRE,
                                scheduled_at=now - timedelta(minutes=5)))
    await store.set_status(fid, FactStatus.ARCHIVED)
    assert await store.get_due_facts(now) == []


def test_fts_match_query_sanitization():
    assert _fts_match_query("café crème!") == '"café" OR "crème"'
    assert _fts_match_query("le la de") == ""      # que des stopwords
    assert _fts_match_query("") == ""
    assert _fts_match_query("Apex?!") == '"apex"'
