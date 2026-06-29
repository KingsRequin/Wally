import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_session_analyses_has_new_columns(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    rows = await db.fetch_all("PRAGMA table_info(session_analyses)")
    cols = {r["name"] for r in rows}
    assert {"platform", "channel_id", "summary"} <= cols
    await db.close()


@pytest.mark.asyncio
async def test_thoughts_table_dropped(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='thoughts'"
    )
    assert rows == []
    await db.close()


@pytest.mark.asyncio
async def test_migration_idempotent_on_legacy_table(tmp_path):
    # Simule une vieille DB avec l'ancien schéma session_analyses (sans les colonnes)
    import aiosqlite
    path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(path) as raw:
        await raw.execute(
            "CREATE TABLE session_analyses ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, quality REAL, "
            "issues TEXT, successes TEXT, improvement_note TEXT, created_at TEXT NOT NULL)"
        )
        await raw.execute("CREATE TABLE thoughts (id INTEGER PRIMARY KEY, content TEXT, created_at TEXT)")
        await raw.commit()
    # create_v2_tables doit migrer sans lever, deux fois de suite
    from bot.db.schema_v2 import create_v2_tables
    await create_v2_tables(path)
    await create_v2_tables(path)  # idempotent
    db = await Database.create(path)
    rows = await db.fetch_all("PRAGMA table_info(session_analyses)")
    cols = {r["name"] for r in rows}
    assert {"platform", "channel_id", "summary"} <= cols
    await db.close()
