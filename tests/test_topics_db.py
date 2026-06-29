import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_topics_table_exists(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    rows = await db.fetch_all("PRAGMA table_info(topics)")
    cols = {r["name"] for r in rows}
    assert {"name", "summary", "participants", "opinion", "mention_count", "last_seen_at", "created_at"} <= cols
    await db.close()
