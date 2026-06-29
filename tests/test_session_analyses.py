import pytest
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables


async def _make_db(tmp_path):
    """DB de test avec tables V1 + V2 (comme en prod via bootstrap)."""
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    return db


@pytest.mark.asyncio
async def test_insert_and_get_summary(tmp_path):
    db = await _make_db(tmp_path)
    await db.insert_session_analysis("discord:111:2026-06-29", "discord", "111", "On a parlé d'Apex.")
    out = await db.get_recent_session_summaries("discord", "111")
    assert len(out) == 1
    assert out[0]["summary"] == "On a parlé d'Apex."
    await db.close()


@pytest.mark.asyncio
async def test_upsert_replaces_same_session_id(tmp_path):
    db = await _make_db(tmp_path)
    await db.insert_session_analysis("discord:111:2026-06-29", "discord", "111", "v1")
    await db.insert_session_analysis("discord:111:2026-06-29", "discord", "111", "v2")
    out = await db.get_recent_session_summaries("discord", "111")
    assert len(out) == 1
    assert out[0]["summary"] == "v2"
    await db.close()


@pytest.mark.asyncio
async def test_channel_isolation(tmp_path):
    db = await _make_db(tmp_path)
    await db.insert_session_analysis("discord:111:2026-06-29", "discord", "111", "salon A")
    await db.insert_session_analysis("discord:222:2026-06-29", "discord", "222", "salon B")
    out = await db.get_recent_session_summaries("discord", "111")
    assert [o["summary"] for o in out] == ["salon A"]
    await db.close()


@pytest.mark.asyncio
async def test_limit_and_order(tmp_path):
    db = await _make_db(tmp_path)
    for i in range(5):
        await db.insert_session_analysis(f"discord:111:day{i}", "discord", "111", f"jour {i}")
    out = await db.get_recent_session_summaries("discord", "111", limit=2)
    assert len(out) == 2
    await db.close()
