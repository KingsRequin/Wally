"""Tests for emergent secondary emotions."""
import pytest
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine
from bot.config import SecondaryEmotionDef


def _make_engine(secondaries=None):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.emotional_memory = MagicMock(learning_rate=0.05, priming_factor=0.0, amplification_factor=0.0, decay_lambda_per_day=0.01)
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    if secondaries is None:
        secondaries = {
            "frustration": SecondaryEmotionDef(a="anger", b="boredom", threshold=0.3),
            "nostalgia": SecondaryEmotionDef(a="joy", b="sadness", threshold=0.3),
            "pride": SecondaryEmotionDef(a="joy", b="curiosity", threshold=0.4),
            "contempt": SecondaryEmotionDef(a="anger", b="boredom", threshold=[0.4, 0.5]),
            "wonder": SecondaryEmotionDef(a="curiosity", b="joy", threshold=0.5),
        }
    config.secondaries = secondaries
    return EmotionEngine(config)


def test_no_secondaries_when_below_threshold():
    engine = _make_engine()
    engine._state["anger"] = 0.2
    engine._state["boredom"] = 0.2
    assert engine.get_secondary_emotions() == []


def test_frustration_emerges():
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._state["boredom"] = 0.4
    names = [n for n, _ in engine.get_secondary_emotions()]
    assert "frustration" in names


def test_intensity_is_min_of_primaries():
    engine = _make_engine()
    engine._state["anger"] = 0.6
    engine._state["boredom"] = 0.4
    result = engine.get_secondary_emotions()
    frustration = next((i for n, i in result if n == "frustration"), None)
    assert frustration == pytest.approx(0.4)


def test_asymmetric_threshold_contempt():
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._state["boredom"] = 0.45
    names = [n for n, _ in engine.get_secondary_emotions()]
    assert "contempt" not in names  # boredom < 0.5
    assert "frustration" in names  # both > 0.3


def test_asymmetric_threshold_contempt_passes():
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._state["boredom"] = 0.6
    names = [n for n, _ in engine.get_secondary_emotions()]
    assert "contempt" in names


def test_sorted_by_intensity_descending():
    engine = _make_engine()
    engine._state["anger"] = 0.6
    engine._state["boredom"] = 0.5
    engine._state["joy"] = 0.4
    engine._state["sadness"] = 0.35
    result = engine.get_secondary_emotions()
    intensities = [i for _, i in result]
    assert intensities == sorted(intensities, reverse=True)


def test_multiple_secondaries_at_once():
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._state["boredom"] = 0.5
    engine._state["joy"] = 0.5
    engine._state["sadness"] = 0.4
    names = [n for n, _ in engine.get_secondary_emotions()]
    assert "frustration" in names
    assert "nostalgia" in names
