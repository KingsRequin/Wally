# tests/test_emotion_suppression.py
import pytest
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine


def make_config():
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=0.1, boredom_rise_per_hour=None)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    config.bot.emotion_inertia_factor = 0.0
    return config


# ── apply_delta : suppressions ────────────────────────────────────────────────

def test_joy_suppresses_anger():
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.8
    engine.apply_delta("joy", 0.2)
    assert engine.get_state()["joy"] == pytest.approx(0.2, abs=0.001)
    # joy→anger (0.8): -0.16, anger→joy (0.4) with emotion=tgt: -0.08 → 0.56
    assert engine.get_state()["anger"] == pytest.approx(0.56, abs=0.001)


def test_joy_suppresses_sadness():
    # ("joy","sadness",0.8) bidirectionnel via _apply_suppression → suppression unique
    # sadness = 0.6 - 0.4*0.8 = 0.6 - 0.32 = 0.28
    engine = EmotionEngine(make_config())
    engine._state["sadness"] = 0.6
    engine.apply_delta("joy", 0.4)
    assert engine.get_state()["joy"] == pytest.approx(0.4, abs=0.001)
    assert engine.get_state()["sadness"] == pytest.approx(0.28, abs=0.001)


def test_anger_suppresses_joy():
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.8
    engine.apply_delta("anger", 0.3)
    assert engine.get_state()["anger"] == pytest.approx(0.3, abs=0.001)
    # joy→anger (0.8) with emotion=tgt: -0.24, anger→joy (0.4) with emotion=src: -0.12 → 0.44
    assert engine.get_state()["joy"] == pytest.approx(0.44, abs=0.001)


def test_sadness_suppresses_joy():
    # ("joy","sadness",0.8) bidirectionnel via elif dans _apply_suppression → suppression unique
    # joy = 0.8 - 0.3*0.8 = 0.8 - 0.24 = 0.56
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.8
    engine.apply_delta("sadness", 0.3)
    assert engine.get_state()["sadness"] == pytest.approx(0.3, abs=0.001)
    assert engine.get_state()["joy"] == pytest.approx(0.56, abs=0.001)


def test_anger_does_not_suppress_sadness():
    engine = EmotionEngine(make_config())
    engine._state["sadness"] = 0.5
    engine.apply_delta("anger", 0.3)
    assert engine.get_state()["sadness"] == pytest.approx(0.5, abs=0.001)


def test_curiosity_does_not_suppress_joy():
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.8
    engine.apply_delta("curiosity", 0.3)
    assert engine.get_state()["joy"] == pytest.approx(0.8, abs=0.001)


def test_boredom_does_not_suppress_joy():
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.8
    engine.apply_delta("boredom", 0.3)
    assert engine.get_state()["joy"] == pytest.approx(0.8, abs=0.001)


# ── apply_delta : edge cases ──────────────────────────────────────────────────

def test_negative_delta_no_suppression():
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.5
    engine.apply_delta("joy", -0.1)
    assert engine.get_state()["anger"] == pytest.approx(0.5, abs=0.001)


def test_zero_delta_no_suppression():
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.5
    engine.apply_delta("joy", 0.0)
    assert engine.get_state()["anger"] == pytest.approx(0.5, abs=0.001)


def test_suppression_floored_at_zero():
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.05
    engine.apply_delta("joy", 0.8)  # suppression = 0.8*0.8 = 0.64 > 0.05
    assert engine.get_state()["anger"] == pytest.approx(0.0, abs=0.001)


def test_double_suppression_llm_order():
    """Simule l'ordre d'appel LLM : anger d'abord, puis joy.
    anger=0.5, joy=0.8 initiaux.
    1. apply_delta("anger", 0.1) → anger=0.6, joy=0.8-0.1*0.8-0.1*0.4=0.68
    2. apply_delta("joy", 0.2)  → joy=0.88, anger=0.6-0.2*0.8-0.2*0.4=0.36
    """
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.5
    engine._state["joy"] = 0.8
    engine.apply_delta("anger", 0.1)
    engine.apply_delta("joy", 0.2)
    assert engine.get_state()["anger"] == pytest.approx(0.36, abs=0.001)
    assert engine.get_state()["joy"] == pytest.approx(0.88, abs=0.001)


# ── set_emotion : suppressions ────────────────────────────────────────────────

def test_set_emotion_joy_suppresses_anger():
    """set_emotion("joy", 0.9) depuis 0 : delta_effectif=0.9.
    anger -= 0.9*0.8 (joy→anger) + 0.9*0.4 (anger→joy as tgt) = 1.08 → clamp 0.0."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.8
    engine.set_emotion("joy", 0.9)
    assert engine.get_state()["joy"] == pytest.approx(0.9, abs=0.001)
    assert engine.get_state()["anger"] == pytest.approx(0.0, abs=0.001)


def test_set_emotion_negative_effective_delta_no_suppression():
    """Si set_emotion baisse la valeur (delta_effectif < 0), pas de suppression."""
    engine = EmotionEngine(make_config())
    engine._state["joy"] = 0.5
    engine._state["anger"] = 0.8
    engine.set_emotion("joy", 0.1)  # delta_effectif = 0.1 - 0.5 = -0.4
    assert engine.get_state()["anger"] == pytest.approx(0.8, abs=0.001)


def test_suppression_uses_effective_delta_when_clamped():
    """Quand apply_delta est clampé (emotion déjà à 0.9, delta=0.5 → effective=0.1),
    la suppression utilise le delta effectif (0.1), pas le delta brut (0.5)."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.9  # anger près du plafond
    engine._state["joy"] = 0.8
    engine.apply_delta("anger", 0.5)  # anger → clampé à 1.0 (effective=0.1)
    assert engine.get_state()["anger"] == pytest.approx(1.0, abs=0.001)
    assert engine.get_state()["joy"] == pytest.approx(0.68, abs=0.001)  # 0.8 - 0.1*0.8 - 0.1*0.4
