# tests/test_trust_love.py
import math
import time

import pytest

from bot.db.database import Database


@pytest.mark.asyncio
async def test_love_column_exists(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    # Should not raise — column exists after migration
    await db.update_love_score("discord", "123", 0.5)
    love = await db.get_love_score("discord", "123")
    assert abs(love - 0.5) < 0.01
    await db.close()


@pytest.mark.asyncio
async def test_get_love_score_default_zero(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    love = await db.get_love_score("discord", "unknown")
    assert love == 0.0
    await db.close()


@pytest.mark.asyncio
async def test_love_decay_over_time(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.update_love_score("discord", "123", 0.8, decay_lambda=0.1)
    # Manually backdate love_updated_at by 7 days
    seven_days_ago = time.time() - 7 * 86400
    await db.execute(
        "UPDATE trust_scores SET love_updated_at=? WHERE user_id=? AND platform=?",
        (seven_days_ago, "123", "discord"),
    )
    love = await db.get_love_score("discord", "123", decay_lambda=0.1)
    # Expected: 0.8 * exp(-0.1 * 7) ≈ 0.8 * 0.4966 ≈ 0.397
    assert abs(love - 0.8 * math.exp(-0.1 * 7)) < 0.05
    await db.close()


@pytest.mark.asyncio
async def test_love_no_decay_recent(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.update_love_score("discord", "123", 0.8)
    love = await db.get_love_score("discord", "123")
    assert abs(love - 0.8) < 0.01
    await db.close()


@pytest.mark.asyncio
async def test_love_clamps_at_one(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.update_love_score("discord", "123", 0.9)
    await db.update_love_score("discord", "123", 0.5)
    love = await db.get_love_score("discord", "123")
    assert love <= 1.0
    await db.close()
