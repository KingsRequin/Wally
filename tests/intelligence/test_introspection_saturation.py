"""Anti-spirale introspective : la proba d'introspection émerge de la saturation
récente au lieu d'être fixe à 1/3.

Contexte (bug du 25/07/2026) : sans interaction humaine, Wally passait des
journées entières en méta-rumination. `_INTROSPECTION_PROB = 1/3` était un biais
STRUCTUREL fixe, sans contre-poids quand la vie mentale récente était déjà
saturée d'auto-analyse. On mesure désormais la part d'amorces introspectives sur
une fenêtre glissante ; plus elle est haute, plus la proba effective chute
(auto-correction émergente, aucun seuil horaire codé).
"""
from types import SimpleNamespace

import pytest

from bot.intelligence.attention_agent import (
    AttentionAgent,
    _INTROSPECTION_SEEDS,
    _INTROSPECTION_PROB,
)


class _FakeCat:
    THOUGHT = "THOUGHT"


class _EmptyFacts:
    async def sample_random(self, **k):
        return []


def _fire_at(monkeypatch, value):
    """Force random.random() à renvoyer `value` (tirage d'introspection)."""
    monkeypatch.setattr(
        "bot.intelligence.attention_agent.random.random", lambda: value
    )


@pytest.mark.asyncio
async def test_introspection_fires_when_window_empty(monkeypatch):
    """Fenêtre vide → saturation nulle → comportement d'origine (proba = base)."""
    agent = AttentionAgent(fact_store=_EmptyFacts())
    # value < base et fenêtre vide → introspection doit se déclencher
    _fire_at(monkeypatch, _INTROSPECTION_PROB * 0.5)
    seed, rss = await agent._build_idle_seed({}, [], [], "night", _FakeCat, None)
    assert seed in _INTROSPECTION_SEEDS
    assert rss is None


@pytest.mark.asyncio
async def test_introspection_suppressed_when_saturated(monkeypatch):
    """Fenêtre saturée d'introspection → proba effective ≈ 0 → même un tirage
    qui aurait déclenché l'introspection à froid ne la déclenche plus."""
    agent = AttentionAgent(fact_store=_EmptyFacts())
    # Sature la fenêtre : toutes les amorces récentes étaient introspectives.
    agent._seed_introspective_window.extend([True] * agent._seed_introspective_window.maxlen)
    # Un tirage juste sous la base : à froid il aurait déclenché l'introspection.
    _fire_at(monkeypatch, _INTROSPECTION_PROB * 0.5)
    seed, _ = await agent._build_idle_seed({}, [], [], "night", _FakeCat, None)
    assert seed not in _INTROSPECTION_SEEDS  # supprimée par la saturation


@pytest.mark.asyncio
async def test_probability_decays_monotonically(monkeypatch):
    """La proba effective décroît quand la fraction introspective récente monte."""
    agent = AttentionAgent(fact_store=_EmptyFacts())
    win = agent._seed_introspective_window
    p_empty = agent._effective_introspection_prob()
    # Mi-saturation : moitié introspective, moitié tournée vers le monde.
    win.clear()
    win.extend([True, False] * (win.maxlen // 2))
    p_half = agent._effective_introspection_prob()
    # Pleine saturation : que de l'auto-analyse récente.
    win.clear()
    win.extend([True] * win.maxlen)
    p_full = agent._effective_introspection_prob()
    assert p_empty == pytest.approx(_INTROSPECTION_PROB)
    assert p_full < p_half < p_empty
    assert p_full == pytest.approx(0.0, abs=1e-9)


@pytest.mark.asyncio
async def test_window_records_each_call(monkeypatch):
    """Chaque amorce idle enregistre exactement un booléen (introspective ou non)."""
    agent = AttentionAgent(fact_store=_EmptyFacts())
    _fire_at(monkeypatch, 0.99)  # jamais d'introspection
    await agent._build_idle_seed({}, [], [], "night", _FakeCat, None)
    await agent._build_idle_seed({}, [], [], "night", _FakeCat, None)
    assert len(agent._seed_introspective_window) == 2
    assert not any(agent._seed_introspective_window)  # toutes non-introspectives
