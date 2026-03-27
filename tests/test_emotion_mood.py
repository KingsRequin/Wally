"""Tests for the mood (EMA) layer in EmotionEngine."""
import math
import pytest
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine, EMOTIONS


def _make_engine(**overrides):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.5
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.3)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    for k, v in overrides.items():
        setattr(config, k, v)
    return EmotionEngine(config)


def test_mood_initial_state_all_zero():
    engine = _make_engine()
    mood = engine.get_mood()
    assert all(v == 0.0 for v in mood.values())
    assert set(mood.keys()) == set(EMOTIONS)


def test_mood_ema_update():
    engine = _make_engine()
    engine._state["joy"] = 0.8
    engine._update_mood(delta_t_hours=0.0)
    expected = 0.02 * 0.8 + (1 - 0.02) * 0.0
    assert engine._mood["joy"] == pytest.approx(expected)


def test_mood_ema_converges_over_many_ticks():
    engine = _make_engine()
    engine._state["joy"] = 0.6
    for _ in range(200):
        engine._update_mood(delta_t_hours=0.0)
    assert engine._mood["joy"] == pytest.approx(0.6, abs=0.05)


def test_mood_decay_toward_zero():
    engine = _make_engine()
    engine._mood["joy"] = 0.5
    engine._state["joy"] = 0.0
    for _ in range(200):
        engine._update_mood(delta_t_hours=0.0)
    assert engine._mood["joy"] < 0.05


def test_mood_bias_amplifies_matching_delta():
    engine = _make_engine()
    engine._mood["joy"] = 0.6
    biased = engine._apply_mood_bias("joy", 0.1)
    expected = 0.1 * (1 + 0.6 * 0.3)
    assert biased == pytest.approx(expected)


def test_mood_bias_no_effect_when_mood_zero():
    engine = _make_engine()
    engine._mood["anger"] = 0.0
    assert engine._apply_mood_bias("anger", 0.2) == pytest.approx(0.2)


def test_mood_persists_in_get_state_separately():
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._mood["anger"] = 0.2
    assert engine.get_state()["anger"] == 0.5
    assert engine.get_mood()["anger"] == 0.2
