# tests/test_emotion_competition.py
"""Tests pour la compétition continue pendant le decay.

_apply_competition() est appelée à la fin de _apply_decay().
Elle érode mutuellement les émotions incompatibles :
    extra = state[src] * state[tgt] * COMPETITION_K
    state[src] -= extra
    state[tgt] -= extra

COMPETITION_K = 0.05. Une seule itération de _apply_decay simule 1 tick (60s).
"""
import time
import pytest
from unittest.mock import MagicMock, patch
from bot.core.emotion import EmotionEngine, COMPETITION_K


def make_config(decay_lambda=0.0):
    """decay_lambda=0.0 neutralise le decay exponentiel pour isoler la compétition."""
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=decay_lambda, boredom_rise_per_hour=None)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    config.bot.emotion_inertia_factor = 0.5
    return config


def test_competition_reduces_anger_when_joy_high():
    """anger=0.65, joy=0.33 — après 1 tick de decay, les deux baissent."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.65
    engine._state["joy"] = 0.33

    # Figer _last_decay pour que _apply_decay fasse exactement 1 tick simulé
    engine._last_decay = time.time() - 60
    engine._apply_decay()

    assert engine._state["anger"] < 0.65, "anger doit baisser"
    assert engine._state["joy"] < 0.33,   "joy doit baisser"


def test_competition_symmetric():
    """Competition reduces both emotions; anger drops more due to extra anger→joy rule."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.5
    engine._state["joy"] = 0.5

    engine._last_decay = time.time() - 60
    engine._apply_decay()

    # Both joy↔anger and anger→joy pairs apply competition.
    # anger should drop more than joy (affected by 2 rules).
    assert engine._state["anger"] < 0.5
    assert engine._state["joy"] < 0.5
    # anger drops more because it appears in 2 competition pairs (joy→anger + anger→joy)
    assert engine._state["anger"] <= engine._state["joy"]


def test_competition_converges_in_10_minutes():
    """Scénario réel : anger=0.65, joy=0.33. Après 10 ticks (10min), incohérence résolue."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.65
    engine._state["joy"] = 0.33

    for _ in range(10):
        engine._last_decay = time.time() - 60
        engine._apply_decay()

    # L'une ou l'autre (ou les deux) doit avoir baissé significativement
    anger = engine._state["anger"]
    joy   = engine._state["joy"]
    assert anger < 0.60 or joy < 0.25, (
        f"Après 10 ticks : anger={anger:.3f}, joy={joy:.3f} — toujours incohérent"
    )


def test_competition_no_effect_when_one_is_zero():
    """Si l'une des émotions est à 0, pas de compétition (produit = 0)."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 0.8
    engine._state["joy"] = 0.0

    engine._last_decay = time.time() - 60
    engine._apply_decay()

    assert engine._state["anger"] == pytest.approx(0.8, abs=0.001)


def test_competition_does_not_go_below_zero():
    """Résultat clampé à 0.0 même avec des valeurs très hautes."""
    engine = EmotionEngine(make_config())
    engine._state["anger"] = 1.0
    engine._state["joy"] = 1.0

    for _ in range(1000):
        engine._last_decay = time.time() - 60
        engine._apply_decay()

    assert engine._state["anger"] >= 0.0
    assert engine._state["joy"]   >= 0.0


def test_sadness_joy_competition():
    """sadness et joy sont également en compétition."""
    engine = EmotionEngine(make_config())
    engine._state["sadness"] = 0.6
    engine._state["joy"] = 0.6

    engine._last_decay = time.time() - 60
    engine._apply_decay()

    assert engine._state["sadness"] < 0.6
    assert engine._state["joy"]     < 0.6


def test_curiosity_joy_no_competition():
    """curiosity et joy ne sont PAS en compétition."""
    engine = EmotionEngine(make_config())
    engine._state["curiosity"] = 0.8
    engine._state["joy"] = 0.8

    engine._last_decay = time.time() - 60
    engine._apply_decay()

    assert engine._state["curiosity"] == pytest.approx(0.8, abs=0.001)
    assert engine._state["joy"]       == pytest.approx(0.8, abs=0.001)
