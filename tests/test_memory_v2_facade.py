import pytest

from bot.intelligence.memory.service import MemoryService


@pytest.fixture
def mem(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.memory.facts import SQLiteFactStore
    from bot.intelligence.memory.retrieval import MemoryRetrieval
    db_path = str(tmp_path / "wally.db")
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(create_v2_tables(db_path))
    finally:
        loop.close()
    svc = MemoryService(SimpleNamespace())
    svc._facts = SQLiteFactStore(db_path)
    svc._retrieval = MemoryRetrieval(svc._facts)  # FTS5, plus de Qdrant
    return svc


@pytest.mark.asyncio
async def test_add_and_search_roundtrip(mem):
    await mem.add("discord", "123", "aime les bouchons en plastique", category="PREF")
    out = await mem.search("discord", "123", "bouchons")
    assert "bouchon" in out.lower()


@pytest.mark.asyncio
async def test_add_namespaces_user_id(mem):
    # Use a realistic Discord snowflake (17 digits) to avoid the cross-platform fix
    await mem.add("discord", "12345678901234567", "fait test")
    facts = await mem._facts.get_by_user("discord:12345678901234567")
    assert len(facts) == 1
    assert facts[0].user_id == "discord:12345678901234567"


@pytest.mark.asyncio
async def test_add_dedups_same_content(mem):
    """Le même fait ajouté 2× → 1 seul fait confirmé (pas de doublon)."""
    uid = "12345678901234567"  # snowflake 17 chiffres (évite le cross-platform fix)
    await mem.add("discord", uid, "aime le café", category="PREF")
    await mem.add("discord", uid, "Aime le café !", category="PREF")  # variante normalisée
    facts = await mem._facts.get_by_user(f"discord:{uid}")
    assert len(facts) == 1
    assert facts[0].support_count == 2


@pytest.mark.asyncio
async def test_add_keeps_distinct_content(mem):
    """Deux faits différents coexistent."""
    uid = "12345678901234567"
    await mem.add("discord", uid, "aime le café", category="PREF")
    await mem.add("discord", uid, "déteste les bugs", category="PREF")
    facts = await mem._facts.get_by_user(f"discord:{uid}")
    assert len(facts) == 2
