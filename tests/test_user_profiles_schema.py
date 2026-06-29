import pytest
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables


@pytest.mark.asyncio
async def test_user_profiles_table_exists(tmp_path):
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    rows = await db.fetch_all("PRAGMA table_info(user_profiles)")
    cols = {r["name"] for r in rows}
    assert {"user_id", "portrait", "updated_at"} <= cols
    await db.close()
