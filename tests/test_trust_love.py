# tests/test_trust_love.py
import json
import math
import time
from unittest.mock import MagicMock, AsyncMock

import pytest

from bot.core.emotion import EmotionEngine
from bot.db.database import Database


def _make_emotion_config():
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=0.1, boredom_rise_per_hour=None) for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    config.bot.emotion_inertia_factor = 0.0
    config.bot.emotion_peak_threshold = 0.7
    return config


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


# ── T2: Emotion engine trust_delta + love_delta ───────────────────────────


@pytest.mark.asyncio
async def test_analyze_llm_returns_trust_and_love_delta():
    engine = EmotionEngine(_make_emotion_config())
    mock_openai = MagicMock()
    mock_openai.complete_structured = AsyncMock(return_value={
        "deltas": {"anger": 0.0, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": [],
        "trust_delta": 0.05,
        "love_delta": 0.03,
        "user_facts": [],
    })
    engine.set_openai_client(mock_openai)

    result = await engine.process_message(
        "t'es cool wally", trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "t'es cool wally"}],
    )
    assert result is not None
    assert abs(result["trust_delta"] - 0.05) < 0.01
    assert abs(result["love_delta"] - 0.03) < 0.01


@pytest.mark.asyncio
async def test_analyze_llm_clamps_trust_delta():
    engine = EmotionEngine(_make_emotion_config())
    mock_openai = MagicMock()
    mock_openai.complete_structured = AsyncMock(return_value={
        "deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": [],
        "trust_delta": 0.5,  # way over max
        "love_delta": -0.3,  # negative, should clamp to 0
        "user_facts": [],
    })
    engine.set_openai_client(mock_openai)

    result = await engine.process_message(
        "test", trust_score=0.5,
        context_messages=[{"author": "Bob", "content": "test"}],
    )
    assert result is not None
    assert result["trust_delta"] <= 0.1
    assert result["love_delta"] >= 0.0


@pytest.mark.asyncio
async def test_process_message_fallback_returns_none():
    """Sans OpenAI, process_message retourne None (fallback NRCLex)."""
    engine = EmotionEngine(_make_emotion_config())
    result = await engine.process_message("happy", trust_score=0.5)
    assert result is None
