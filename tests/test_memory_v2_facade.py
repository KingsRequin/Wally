import pytest

from bot.core.memory import MemoryService


@pytest.fixture
def mem(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from wally_v2.db.schema_v2 import create_v2_tables
    from wally_v2.core.memory.facts import SQLiteFactStore
    from wally_v2.core.memory.retrieval import MemoryRetrieval
    db_path = str(tmp_path / "wally.db")
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(create_v2_tables(db_path))
    finally:
        loop.close()
    svc = MemoryService(SimpleNamespace())

    class _StubQdrant:
        async def ensure_collection(self): pass
        async def upsert(self, **kw): pass
        async def search(self, **kw): return []  # force fallback get_by_user
    svc._facts = SQLiteFactStore(db_path)
    svc._retrieval = MemoryRetrieval(svc._facts, _StubQdrant())
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
