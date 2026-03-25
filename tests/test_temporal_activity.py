# tests/test_temporal_activity.py
import time

import pytest

from bot.db.database import Database


@pytest.mark.asyncio
async def test_get_last_interaction_returns_timestamp(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_memory_user("discord:610550333042589752", "discord", username="Alice")
    result = await db.get_last_interaction("discord:610550333042589752")
    assert result is not None
    assert abs(result - time.time()) < 5  # within 5 seconds
    await db.close()


@pytest.mark.asyncio
async def test_get_last_interaction_unknown_user(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    result = await db.get_last_interaction("discord:999")
    assert result is None
    await db.close()
