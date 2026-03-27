"""Tests for per-user emotional memory (affinity) and habituation."""
import time
import pytest
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine, EMOTIONS


def _make_engine():
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(
        threshold_count=3, window_seconds=600, decay_factor=0.5,
        reset_seconds=1800, exempt=["anger"],
    )
    config.emotional_memory = MagicMock(
        learning_rate=0.05, priming_factor=0.05,
        amplification_factor=0.3, decay_lambda_per_day=0.01,
    )
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    return EmotionEngine(config)


# ── Affinity ──────────────────────────────────────────

def test_get_user_affinity_default_zeros():
    engine = _make_engine()
    aff = engine.get_user_affinity("123", "discord")
    assert all(v == 0.0 for v in aff.values())


def test_update_user_affinity():
    engine = _make_engine()
    deltas = {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    engine.update_user_affinity("123", "discord", deltas)
    aff = engine.get_user_affinity("123", "discord")
    assert aff["joy"] == pytest.approx(0.05 * 0.2)


def test_affinity_accumulates():
    engine = _make_engine()
    for _ in range(10):
        engine.update_user_affinity("123", "discord", {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    aff = engine.get_user_affinity("123", "discord")
    assert aff["joy"] == pytest.approx(10 * 0.05 * 0.2)


def test_affinity_clamped():
    engine = _make_engine()
    for _ in range(500):
        engine.update_user_affinity("123", "discord", {"anger": 0.3, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    aff = engine.get_user_affinity("123", "discord")
    assert aff["anger"] <= 1.0


def test_apply_priming():
    engine = _make_engine()
    engine._user_affinity[("123", "discord")] = {"joy": 0.6, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0, "_count": {e: 10 for e in EMOTIONS}}
    priming = engine._get_priming_deltas("123", "discord")
    assert priming["joy"] == pytest.approx(0.6 * 0.05)


def test_apply_amplification():
    engine = _make_engine()
    engine._user_affinity[("123", "discord")] = {"joy": 0.6, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0, "_count": {e: 10 for e in EMOTIONS}}
    result = engine._apply_affinity_amplification("123", "discord", "joy", 0.1)
    expected = 0.1 * (1 + 0.6 * 0.3)
    assert result == pytest.approx(expected)


def test_amplification_no_effect_opposite_direction():
    engine = _make_engine()
    engine._user_affinity[("123", "discord")] = {"joy": -0.5, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0, "_count": {e: 10 for e in EMOTIONS}}
    result = engine._apply_affinity_amplification("123", "discord", "joy", 0.1)
    assert result <= 0.1


# ── Habituation ───────────────────────────────────────

def test_habituation_no_effect_first_few():
    engine = _make_engine()
    for _ in range(3):
        result = engine._apply_habituation("123", "joy", 0.2)
        assert result == pytest.approx(0.2)


def test_habituation_reduces_after_threshold():
    engine = _make_engine()
    for _ in range(3):
        engine._apply_habituation("123", "joy", 0.2)
    result = engine._apply_habituation("123", "joy", 0.2)
    assert result == pytest.approx(0.2 * 0.5)


def test_habituation_compounds():
    engine = _make_engine()
    for _ in range(3):
        engine._apply_habituation("123", "joy", 0.2)
    engine._apply_habituation("123", "joy", 0.2)  # 0.5x
    result = engine._apply_habituation("123", "joy", 0.2)  # 0.25x
    assert result == pytest.approx(0.2 * 0.25)


def test_habituation_anger_exempt():
    engine = _make_engine()
    for _ in range(5):
        result = engine._apply_habituation("123", "anger", 0.2)
    assert result == pytest.approx(0.2)


def test_habituation_resets_after_timeout():
    engine = _make_engine()
    for _ in range(4):
        engine._apply_habituation("123", "joy", 0.2)
    # Simulate time passing
    for key in engine._habituation_tracker:
        engine._habituation_tracker[key] = [(e, t - 2000) for e, t in engine._habituation_tracker[key]]
    result = engine._apply_habituation("123", "joy", 0.2)
    assert result == pytest.approx(0.2)
