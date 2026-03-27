"""Integration tests for the full delta processing pipeline."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from bot.core.emotion import EmotionEngine, EMOTIONS


def _make_engine(mood_bias=0.0, fatigue_dampening=0.0):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=mood_bias)
    config.fatigue = MagicMock(dampening=fatigue_dampening, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.emotional_memory = MagicMock(learning_rate=0.05, priming_factor=0.05, amplification_factor=0.3, decay_lambda_per_day=0.01)
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    config.secondaries = {}
    return EmotionEngine(config)


def test_prepare_deltas_applies_mood_and_fatigue():
    engine = _make_engine(mood_bias=0.3, fatigue_dampening=0.7)
    engine._mood["joy"] = 0.5
    engine._fatigue["joy"] = 0.3
    raw = {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    result = engine.prepare_deltas(raw, user_id="123", platform="discord")
    # joy: 0.2 * (1+0.5*0.3) mood * (1-0.3*0.7) fatigue
    expected = 0.2 * (1 + 0.5 * 0.3) * (1 - 0.3 * 0.7)
    assert result["joy"] == pytest.approx(expected, abs=0.01)


def test_prepare_deltas_includes_priming():
    engine = _make_engine()
    engine._user_affinity[("123", "discord")] = {
        "joy": 0.6, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0,
        "_count": {e: 10 for e in EMOTIONS},
    }
    raw = {e: 0.0 for e in EMOTIONS}
    result = engine.prepare_deltas(raw, user_id="123", platform="discord")
    # priming: 0.6 * 0.05 = 0.03
    assert result["joy"] == pytest.approx(0.03, abs=0.01)


def test_prepare_deltas_no_user_id_skips_user_features():
    engine = _make_engine()
    raw = {"joy": 0.1, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    result = engine.prepare_deltas(raw)
    assert result["joy"] == pytest.approx(0.1, abs=0.01)


@pytest.mark.asyncio
async def test_process_message_uses_pipeline():
    engine = _make_engine()
    engine._openai = AsyncMock()
    deltas = {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    engine._analyze_llm = AsyncMock(return_value=(deltas, [], 0.0, 0.0, []))
    await engine.process_message(
        "hello", trust_score=0.5,
        context_messages=[{"author": "test", "content": "hi"}],
        trigger_user="test_user", platform="discord",
        user_id="123",
    )
    assert engine._state["joy"] > 0.0


@pytest.mark.asyncio
async def test_process_message_updates_affinity():
    engine = _make_engine()
    engine._openai = AsyncMock()
    deltas = {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    engine._analyze_llm = AsyncMock(return_value=(deltas, [], 0.0, 0.0, []))
    await engine.process_message(
        "hello", trust_score=0.5,
        context_messages=[{"author": "test", "content": "hi"}],
        trigger_user="test_user", platform="discord",
        user_id="123",
    )
    aff = engine.get_user_affinity("123", "discord")
    assert aff["joy"] > 0.0
