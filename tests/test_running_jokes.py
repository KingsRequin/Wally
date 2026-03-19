# tests/test_running_jokes.py
import pytest

from bot.db.database import Database


@pytest.mark.asyncio
async def test_insert_joke(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_joke("c'était drôle", "chan1", "discord", 5)
    jokes = await db.get_recent_jokes("chan1")
    assert len(jokes) == 1
    assert "c'était drôle" in jokes[0]
    await db.close()


@pytest.mark.asyncio
async def test_get_recent_jokes_returns_latest(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    for i in range(5):
        await db.insert_joke(f"joke {i}", "chan1", "discord", 3)
    jokes = await db.get_recent_jokes("chan1", limit=3)
    assert len(jokes) == 3
    assert jokes[0] == "joke 4"  # most recent first
    await db.close()


@pytest.mark.asyncio
async def test_get_recent_jokes_filters_by_channel(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_joke("joke A", "chan1", "discord", 3)
    await db.insert_joke("joke B", "chan2", "discord", 3)
    jokes = await db.get_recent_jokes("chan1")
    assert len(jokes) == 1
    assert "joke A" in jokes[0]
    await db.close()


@pytest.mark.asyncio
async def test_get_recent_jokes_empty(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    jokes = await db.get_recent_jokes("chan1")
    assert jokes == []
    await db.close()
