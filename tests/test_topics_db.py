import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_topics_table_exists(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    rows = await db.fetch_all("PRAGMA table_info(topics)")
    cols = {r["name"] for r in rows}
    assert {"name", "summary", "participants", "opinion", "mention_count", "last_seen_at", "created_at"} <= cols
    await db.close()


async def _mkdb(tmp_path):
    from bot.db.database import Database
    return await Database.create(str(tmp_path / "t.db"))


@pytest.mark.asyncio
async def test_upsert_topic_insert_then_merge(tmp_path):
    db = await _mkdb(tmp_path)
    await db.upsert_topic("Apex", "on en parle", [{"name": "Az", "uid": "discord:1"}], "surcoté")
    await db.upsert_topic("Apex", "encore", [{"name": "Bob", "uid": "discord:2"}, {"name": "Az", "uid": "discord:1"}], "toujours surcoté")
    topics = await db.get_topics()
    assert len(topics) == 1
    t = topics[0]
    assert t["name"] == "Apex"
    assert t["summary"] == "encore"
    assert t["opinion"] == "toujours surcoté"
    assert t["mention_count"] == 2
    uids = {p["uid"] for p in t["participants"]}
    assert uids == {"discord:1", "discord:2"}  # unionnés, pas de doublon Az
    await db.close()


@pytest.mark.asyncio
async def test_get_topics_order_and_limit(tmp_path):
    import time
    db = await _mkdb(tmp_path)
    await db.upsert_topic("Vieux", "x", [], "a")
    await db.execute("UPDATE topics SET last_seen_at = ? WHERE name='Vieux'", (time.time() - 1000,))
    await db.upsert_topic("Récent", "y", [], "b")
    topics = await db.get_topics(limit=1)
    assert [t["name"] for t in topics] == ["Récent"]
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_topics_removes_old(tmp_path):
    import time
    db = await _mkdb(tmp_path)
    await db.upsert_topic("Old", "x", [], "a")
    await db.execute("UPDATE topics SET last_seen_at = ? WHERE name='Old'", (time.time() - 40 * 86400,))
    await db.cleanup_topics(max_age_days=30)
    assert await db.get_topics() == []
    await db.close()
