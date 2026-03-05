import pytest
import asyncio
import time
from bot.db.database import Database


@pytest.mark.asyncio
async def test_schema_created(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    names = {row["name"] for row in tables}
    assert {"cost_log", "timeout_log", "welcomed", "trust_scores"}.issubset(names)
    await db.close()


@pytest.mark.asyncio
async def test_log_and_get_cost(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.log_cost("gpt-4o", 100, 50, 0.001, "test")
    cost = await db.get_cost_since(time.time() - 60)
    assert cost > 0
    await db.close()


@pytest.mark.asyncio
async def test_trust_score_default(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    score = await db.get_trust_score("discord", "unknown_user")
    assert score == 0.5  # default
    await db.close()


@pytest.mark.asyncio
async def test_trust_score_update(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.update_trust_score("discord", "user1", 0.1)
    score = await db.get_trust_score("discord", "user1")
    assert abs(score - 0.6) < 0.001  # 0.5 default + 0.1 delta
    await db.close()


@pytest.mark.asyncio
async def test_trust_score_clamped(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.update_trust_score("discord", "user1", 999.0)
    score = await db.get_trust_score("discord", "user1")
    assert score == 1.0
    await db.close()


@pytest.mark.asyncio
async def test_welcomed(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    assert not await db.is_welcomed("user1", "guild1")
    await db.mark_welcomed("user1", "guild1")
    assert await db.is_welcomed("user1", "guild1")
    # Idempotent
    await db.mark_welcomed("user1", "guild1")
    assert await db.is_welcomed("user1", "guild1")
    await db.close()


@pytest.mark.asyncio
async def test_mute(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    assert not await db.is_muted("user1", "guild1")
    await db.add_timeout("user1", "guild1", duration_minutes=10, anger_level=0.9)
    assert await db.is_muted("user1", "guild1")
    await db.close()


@pytest.mark.asyncio
async def test_count_recent_triggers(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    assert await db.count_recent_triggers("user1", "guild1") == 0
    await db.add_timeout("user1", "guild1", duration_minutes=1, anger_level=0.8)
    await db.add_timeout("user1", "guild1", duration_minutes=1, anger_level=0.8)
    count = await db.count_recent_triggers("user1", "guild1", window_seconds=60)
    assert count == 2
    await db.close()
