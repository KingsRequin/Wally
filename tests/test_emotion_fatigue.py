"""Tests for emotional fatigue (refractory period)."""
import pytest
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine, EMOTIONS


def _make_engine(**overrides):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    for k, v in overrides.items():
        setattr(config, k, v)
    return EmotionEngine(config)


def test_fatigue_initial_state_all_zero():
    engine = _make_engine()
    assert all(v == 0.0 for v in engine.get_fatigue().values())


def test_fatigue_triggers_on_peak():
    engine = _make_engine()
    engine._state["anger"] = 0.6
    engine.apply_delta("anger", 0.15)  # 0.75 > 0.7
    assert engine._fatigue["anger"] > 0.0


def test_fatigue_does_not_trigger_below_threshold():
    engine = _make_engine()
    engine._state["anger"] = 0.3
    engine.apply_delta("anger", 0.1)  # 0.4 < 0.7
    assert engine._fatigue["anger"] == 0.0


def test_fatigue_dampens_subsequent_deltas():
    engine = _make_engine()
    engine._fatigue["anger"] = 0.8
    dampened = engine._apply_fatigue("anger", 0.2)
    expected = 0.2 * (1 - 0.8 * 0.7)
    assert dampened == pytest.approx(expected)


def test_fatigue_no_effect_when_zero():
    engine = _make_engine()
    engine._fatigue["joy"] = 0.0
    assert engine._apply_fatigue("joy", 0.3) == pytest.approx(0.3)


def test_fatigue_recovery_over_time():
    engine = _make_engine()
    engine._fatigue["anger"] = 0.6
    engine._recover_fatigue(1.0)  # 1 hour
    expected = max(0.0, 0.6 - 0.1 * 1.0)
    assert engine._fatigue["anger"] == pytest.approx(expected)


def test_fatigue_recovery_floors_at_zero():
    engine = _make_engine()
    engine._fatigue["anger"] = 0.05
    engine._recover_fatigue(1.0)
    assert engine._fatigue["anger"] == 0.0


def test_boredom_no_fatigue():
    engine = _make_engine()
    engine._state["boredom"] = 0.6
    engine.apply_delta("boredom", 0.15)  # 0.75
    assert engine._fatigue["boredom"] == 0.0
