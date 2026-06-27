import aiosqlite
import pytest
from bot.db.schema_v2 import create_v2_tables


@pytest.mark.asyncio
async def test_social_rhythm_bins_table_created(tmp_path):
    db_path = str(tmp_path / "t.db")
    await create_v2_tables(db_path)
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='social_rhythm_bins'"
        )
        assert await cur.fetchone() is not None
        cur = await db.execute("PRAGMA table_info(social_rhythm_bins)")
        cols = {row[1] for row in await cur.fetchall()}
        assert cols == {"bin_key", "avg", "eng", "days", "eng_obs", "updated_at"}


@pytest.mark.asyncio
async def test_create_v2_tables_idempotent(tmp_path):
    db_path = str(tmp_path / "t.db")
    await create_v2_tables(db_path)
    await create_v2_tables(db_path)  # ne doit pas lever
