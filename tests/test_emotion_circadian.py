"""Tests for circadian rhythm modifiers."""
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from unittest.mock import MagicMock, patch
from bot.core.emotion import EmotionEngine
from bot.config import CircadianPeriod, CircadianConfig


def _make_engine(circadian_enabled=True, periods=None):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    if periods is None:
        periods = {
            "night": CircadianPeriod(hours=[0, 6], anger=1.3, curiosity=0.8, boredom=1.1),
            "morning": CircadianPeriod(hours=[6, 12], anger=0.9, joy=1.1, curiosity=1.2, boredom=0.9),
            "afternoon": CircadianPeriod(hours=[12, 18]),
            "evening": CircadianPeriod(hours=[18, 24], sadness=1.15),
        }
    config.circadian = CircadianConfig(enabled=circadian_enabled, periods=periods)
    return EmotionEngine(config)


@patch("bot.core.emotion.datetime")
def test_circadian_night_amplifies_anger(mock_dt):
    mock_dt.datetime.now.return_value = datetime(2026, 3, 27, 3, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("anger", 0.1)
    assert result == pytest.approx(0.1 * 1.3)


@patch("bot.core.emotion.datetime")
def test_circadian_night_reduces_curiosity(mock_dt):
    mock_dt.datetime.now.return_value = datetime(2026, 3, 27, 3, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("curiosity", 0.1)
    assert result == pytest.approx(0.1 * 0.8)


@patch("bot.core.emotion.datetime")
def test_circadian_afternoon_neutral(mock_dt):
    mock_dt.datetime.now.return_value = datetime(2026, 3, 27, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("anger", 0.1)
    assert result == pytest.approx(0.1)


@patch("bot.core.emotion.datetime")
def test_circadian_disabled_no_effect(mock_dt):
    mock_dt.datetime.now.return_value = datetime(2026, 3, 27, 3, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine(circadian_enabled=False)
    result = engine._apply_circadian("anger", 0.1)
    assert result == pytest.approx(0.1)


@patch("bot.core.emotion.datetime")
def test_circadian_negative_delta_passthrough(mock_dt):
    mock_dt.datetime.now.return_value = datetime(2026, 3, 27, 3, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("anger", -0.1)
    assert result == pytest.approx(-0.1)


@patch("bot.core.emotion.datetime")
def test_circadian_evening_sadness(mock_dt):
    mock_dt.datetime.now.return_value = datetime(2026, 3, 27, 21, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("sadness", 0.1)
    assert result == pytest.approx(0.1 * 1.15)
