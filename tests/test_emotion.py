# tests/test_emotion.py
import json
import math
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    # lambda est exprimé par minute : E = 1.0 * e^(-0.1 * (10/60)) ≈ 0.983
    anger = engine.get_state()["anger"]
    expected = math.exp(-0.1 * (10 / 60.0))
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


@pytest.mark.asyncio
async def test_analyze_message_returns_dict():
    engine = EmotionEngine(make_config())
    deltas = await engine.analyze_message("I am so happy and joyful today!", trust_score=0.5)
    assert isinstance(deltas, dict)
    # All values should be floats >= 0
    assert all(isinstance(v, float) and v >= 0 for v in deltas.values())


# ── LLM analysis ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_message_uses_llm_when_openai_injected():
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value=json.dumps({
        "deltas": {"anger": 0.2, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": []
    }))
    engine.set_openai_client(mock_openai)

    await engine.process_message("t'es nul", trust_score=0.5, context_messages=[
        {"author": "Alice", "content": "t'es nul"}
    ])

    assert engine.get_state()["anger"] == pytest.approx(0.2, abs=0.01)
    mock_openai.complete_secondary.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_falls_back_on_llm_failure():
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(side_effect=Exception("API error"))
    engine.set_openai_client(mock_openai)

    # Should not raise — falls back to NRCLex (English text to get non-zero)
    await engine.process_message("happy joyful", trust_score=0.5, context_messages=[
        {"author": "Alice", "content": "happy joyful"}
    ])
    # Fallback ran without error — state is valid
    assert all(0.0 <= v <= 1.0 for v in engine.get_state().values())


@pytest.mark.asyncio
async def test_process_message_falls_back_on_invalid_json():
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value="pas du json")
    engine.set_openai_client(mock_openai)

    await engine.process_message("test", trust_score=0.5, context_messages=[
        {"author": "Alice", "content": "test"}
    ])
    assert all(0.0 <= v <= 1.0 for v in engine.get_state().values())


@pytest.mark.asyncio
async def test_process_message_without_context_uses_fallback():
    """Sans context_messages, l'analyse LLM est skippée même si OpenAI est injecté."""
    engine = EmotionEngine(make_config())
    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock()
    engine.set_openai_client(mock_openai)

    await engine.process_message("happy joyful", trust_score=0.5)

    mock_openai.complete_secondary.assert_not_called()


# ── Learned words ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_learn_new_word_persisted(tmp_path):
    engine = EmotionEngine(make_config())

    with patch("bot.core.emotion._LEARNED_WORDS_PATH", str(tmp_path / "fr_emotion_words.json")):
        await engine._learn_words([{"word": "relou", "emotion": "boredom", "delta": 0.08}])

        saved = json.loads((tmp_path / "fr_emotion_words.json").read_text())
        assert ["relou", 0.08] in saved["boredom"]


@pytest.mark.asyncio
async def test_learn_word_deduplication_hardcoded():
    """Un mot déjà dans FR_EMOTION_WORDS ne doit pas être réappris."""
    engine = EmotionEngine(make_config())
    initial_count = sum(len(v) for v in engine._learned_words.values())

    # "merde" est dans FR_EMOTION_WORDS (anger)
    await engine._learn_words([{"word": "merde", "emotion": "anger", "delta": 0.10}])

    final_count = sum(len(v) for v in engine._learned_words.values())
    assert final_count == initial_count


@pytest.mark.asyncio
async def test_learn_word_invalid_emotion_ignored():
    engine = EmotionEngine(make_config())
    await engine._learn_words([{"word": "relou", "emotion": "fear", "delta": 0.08}])
    assert all("relou" not in [w for w, _ in v] for v in engine._learned_words.values())


@pytest.mark.asyncio
async def test_learn_word_invalid_delta_ignored():
    engine = EmotionEngine(make_config())
    await engine._learn_words([{"word": "relou", "emotion": "boredom", "delta": 5.0}])
    assert all("relou" not in [w for w, _ in v] for v in engine._learned_words.values())


# ── build_emotion_tag ─────────────────────────────────────────────────────────

def test_build_emotion_tag_with_dominant_emotions():
    from bot.core.emotion import build_emotion_tag
    state = {"anger": 0.0, "joy": 0.7, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0}
    tag = build_emotion_tag(state)
    assert "joy" in tag
    assert "curiosity" in tag
    assert tag.startswith("Wally:")


def test_build_emotion_tag_returns_empty_when_none_dominant():
    from bot.core.emotion import build_emotion_tag
    state = {"anger": 0.2, "joy": 0.3, "sadness": 0.0, "curiosity": 0.1, "boredom": 0.0}
    tag = build_emotion_tag(state)
    assert tag == ""


def test_build_emotion_tag_threshold_boundary():
    from bot.core.emotion import build_emotion_tag
    # Exactement au seuil : 0.4 → inclus
    state = {"anger": 0.4, "joy": 0.39, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    tag = build_emotion_tag(state)
    assert "anger" in tag
    assert "joy" not in tag
