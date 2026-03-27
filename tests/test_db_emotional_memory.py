"""Tests for emotional_memory table and mood/fatigue persistence."""
import pytest
import pytest_asyncio
from bot.db.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_upsert_emotional_memory(db):
    await db.upsert_emotional_memory("123", "discord", "joy", 0.5, 10)
    rows = await db.get_emotional_memory("123", "discord")
    assert len(rows) == 1
    assert rows[0]["emotion"] == "joy"
    assert rows[0]["affinity"] == pytest.approx(0.5)
    assert rows[0]["interaction_count"] == 10


@pytest.mark.asyncio
async def test_upsert_emotional_memory_updates_existing(db):
    await db.upsert_emotional_memory("123", "discord", "joy", 0.3, 5)
    await db.upsert_emotional_memory("123", "discord", "joy", 0.7, 15)
    rows = await db.get_emotional_memory("123", "discord")
    assert len(rows) == 1
    assert rows[0]["affinity"] == pytest.approx(0.7)
    assert rows[0]["interaction_count"] == 15


@pytest.mark.asyncio
async def test_get_emotional_memory_empty(db):
    rows = await db.get_emotional_memory("999", "discord")
    assert rows == []


@pytest.mark.asyncio
async def test_multiple_emotions_per_user(db):
    await db.upsert_emotional_memory("123", "discord", "joy", 0.5, 10)
    await db.upsert_emotional_memory("123", "discord", "anger", -0.3, 5)
    rows = await db.get_emotional_memory("123", "discord")
    assert len(rows) == 2
    emotions = {r["emotion"]: r["affinity"] for r in rows}
    assert emotions["joy"] == pytest.approx(0.5)
    assert emotions["anger"] == pytest.approx(-0.3)


@pytest.mark.asyncio
async def test_save_load_mood_state(db):
    mood = {"anger": 0.1, "joy": 0.3, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.05}
    await db.save_mood_state(mood)
    loaded = await db.load_mood_state()
    for e in mood:
        assert loaded.get(e, 0.0) == pytest.approx(mood[e])


@pytest.mark.asyncio
async def test_save_load_fatigue_state(db):
    fatigue = {"anger": 0.5, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    await db.save_fatigue_state(fatigue)
    loaded = await db.load_fatigue_state()
    assert loaded.get("anger", 0.0) == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_load_mood_state_empty_returns_zeros(db):
    loaded = await db.load_mood_state()
    assert all(v == 0.0 for v in loaded.values())
