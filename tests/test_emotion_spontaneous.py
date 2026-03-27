"""Tests for spontaneous internal emotion events."""
import random
import pytest
from unittest.mock import MagicMock, patch
from bot.core.emotion import EmotionEngine, EMOTIONS
from bot.config import SpontaneousEvent, SpontaneousConfig


def _make_engine(prob=0.02, events=None):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.emotional_memory = MagicMock(learning_rate=0.05, priming_factor=0.0, amplification_factor=0.0, decay_lambda_per_day=0.01)
    config.circadian = MagicMock(enabled=False)
    if events is None:
        events = {
            "wandering_thought": SpontaneousEvent(weight=30, effects={"curiosity": 0.05}),
            "pleasant_memory": SpontaneousEvent(weight=20, effects={"joy": 0.05}),
            "creative_spark": SpontaneousEvent(weight=15, effects={"curiosity": 0.08, "boredom": -0.1}),
        }
    config.spontaneous = SpontaneousConfig(probability_per_tick=prob, max_delta=0.1, events=events)
    return EmotionEngine(config)


def test_spontaneous_no_trigger_when_probability_zero():
    engine = _make_engine(prob=0.0)
    state_before = engine.get_state()
    engine._maybe_spontaneous_event()
    assert engine.get_state() == state_before


@patch("bot.core.emotion.random")
def test_spontaneous_event_triggers(mock_random):
    mock_random.random.return_value = 0.01  # < 0.02
    engine = _make_engine()
    # Force random.choices to return wandering_thought
    mock_random.choices.return_value = [("wandering_thought", SpontaneousEvent(weight=30, effects={"curiosity": 0.05}))]
    old_curiosity = engine._state["curiosity"]
    engine._maybe_spontaneous_event()
    assert engine._state["curiosity"] > old_curiosity


@patch("bot.core.emotion.random")
def test_spontaneous_event_does_not_trigger(mock_random):
    mock_random.random.return_value = 0.5  # > 0.02
    engine = _make_engine()
    state_before = engine.get_state()
    engine._maybe_spontaneous_event()
    assert engine.get_state() == state_before


def test_spontaneous_respects_max_delta():
    engine = _make_engine(events={
        "big_event": SpontaneousEvent(weight=100, effects={"joy": 0.5}),
    })
    engine._state["joy"] = 0.0
    with patch("bot.core.emotion.random") as mock_random:
        mock_random.random.return_value = 0.0
        mock_random.choices.return_value = [("big_event", SpontaneousEvent(weight=100, effects={"joy": 0.5}))]
        engine._maybe_spontaneous_event()
    assert engine._state["joy"] <= 0.1  # max_delta
