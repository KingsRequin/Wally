import pytest
from datetime import datetime, timedelta
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables


async def _make_db(tmp_path):
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    return db


async def _add_fact(db, user_id, content, status="active", category="FAIT", when=None):
    ts = (when or datetime.utcnow()).isoformat()
    await db.execute(
        "INSERT INTO atomic_facts (user_id, content, category, importance, support_count, "
        "confidence, status, source, created_at, last_seen_at, decay_rate) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, content, category, 0.5, 1, 0.9, status, "test", ts, ts, 0.005),
    )


@pytest.mark.asyncio
async def test_profile_upsert_and_get(tmp_path):
    db = await _make_db(tmp_path)
    await db.upsert_user_profile("discord:1", "Portrait v1")
    assert await db.get_user_profile("discord:1") == "Portrait v1"
    await db.upsert_user_profile("discord:1", "Portrait v2")
    assert await db.get_user_profile("discord:1") == "Portrait v2"
    assert await db.get_user_profile("discord:999") is None
    await db.close()


@pytest.mark.asyncio
async def test_users_with_recent_facts(tmp_path):
    db = await _make_db(tmp_path)
    await _add_fact(db, "discord:1", "récent")
    await _add_fact(db, "discord:2", "vieux", when=datetime.utcnow() - timedelta(days=10))
    since = (datetime.utcnow() - timedelta(days=1)).isoformat()
    users = await db.get_users_with_recent_facts(since)
    assert "discord:1" in users
    assert "discord:2" not in users
    await db.close()


@pytest.mark.asyncio
async def test_active_and_superseded_split(tmp_path):
    db = await _make_db(tmp_path)
    await _add_fact(db, "discord:1", "aime la stratégie", status="active")
    await _add_fact(db, "discord:1", "détestait le solo", status="superseded")
    active = await db.get_active_facts_for_user("discord:1")
    superseded = await db.get_superseded_facts_for_user("discord:1")
    assert [f["content"] for f in active] == ["aime la stratégie"]
    assert [f["content"] for f in superseded] == ["détestait le solo"]
    await db.close()
