# tests/test_emotion.py
import math
import time
from unittest.mock import MagicMock

from bot.core.emotion import EmotionEngine, EMOTIONS


def make_config():
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=0.1) for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    config.emotions["joy"].decay_lambda = 0.05
    config.discord.anger_trigger_threshold = 3
    config.discord.timeout_minutes = 10
    return config


def test_initial_state_all_zero():
    engine = EmotionEngine(make_config())
    state = engine.get_state()
    assert set(state.keys()) == set(EMOTIONS)
    assert all(v == 0.0 for v in state.values())


def test_apply_delta_increases():
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 0.5)
    assert abs(engine.get_state()["joy"] - 0.5) < 0.001


def test_apply_delta_clamps_at_one():
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 2.0)
    assert engine.get_state()["joy"] == 1.0


def test_apply_delta_clamps_at_zero():
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", -5.0)
    assert engine.get_state()["anger"] == 0.0


def test_set_emotion():
    engine = EmotionEngine(make_config())
    engine.set_emotion("sadness", 0.7)
    assert abs(engine.get_state()["sadness"] - 0.7) < 0.001


def test_reset():
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 0.8)
    engine.apply_delta("anger", 0.6)
    engine.reset()
    assert all(v == 0.0 for v in engine.get_state().values())


def test_decay_reduces_emotion():
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", 1.0)
    # Simulate 10 seconds elapsed
    engine._last_decay = time.time() - 10
    engine._apply_decay()
    # E = 1.0 * e^(-0.1 * 10) ≈ 0.368
    anger = engine.get_state()["anger"]
    expected = math.exp(-0.1 * 10)
    assert abs(anger - expected) < 0.01


def test_decay_zeroes_tiny_values():
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.005
    engine._last_decay = time.time() - 1
    engine._apply_decay()
    assert engine.get_state()["joy"] == 0.0


def test_get_dominant_above_threshold():
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 0.9)
    engine.apply_delta("curiosity", 0.5)
    dominant = engine.get_dominant(threshold=0.4)
    assert "joy" in dominant
    assert "curiosity" in dominant
    assert "anger" not in dominant


def test_get_dominant_empty_when_all_below():
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 0.1)
    assert engine.get_dominant(threshold=0.4) == []


def test_unknown_emotion_ignored():
    engine = EmotionEngine(make_config())
    engine.apply_delta("nonexistent", 0.5)  # should not raise
    assert "nonexistent" not in engine.get_state()


def test_analyze_message_returns_dict():
    import asyncio
    engine = EmotionEngine(make_config())
    deltas = asyncio.get_event_loop().run_until_complete(
        engine.analyze_message("I am so happy and joyful today!", trust_score=0.5)
    )
    assert isinstance(deltas, dict)
    # All values should be floats >= 0
    assert all(isinstance(v, float) and v >= 0 for v in deltas.values())
