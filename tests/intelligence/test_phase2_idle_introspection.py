"""Tests Phase 2 — amorce qui prime + introspection + exclusion du focus."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.intelligence.attention_agent import (
    AttentionContext, AttentionAgent, _seed_overlaps_focus,
    _INTROSPECTION_SEEDS,
)
from bot.intelligence.reasoning_agent import ReasoningAgent

_PROMPTS = Path(__file__).parent.parent.parent / "bot" / "intelligence" / "persona" / "prompts"


def _thought(text):
    return SimpleNamespace(content=text)


def _ctx(**over):
    base = dict(
        emotion_state={"joy": 0.1}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="night",
    )
    base.update(over)
    return AttentionContext(**base)


# --- Phase 2a : l'amorce prime, la dernière pensée ne ré-amorce pas -------- #

def test_recent_thought_omitted_when_idle_without_focus():
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    ctx = _ctx(idle_seed="Pars sur du neuf", preoccupation=None,
               recent_thoughts=[_thought("vieille rumination jubeii")])
    out = agent._format_context(ctx)
    assert "Dernière pensée" not in out
    assert "fait le tour" in out  # cadrage bifurcation


def test_recent_thought_kept_when_focus_present():
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    ctx = _ctx(idle_seed="vagabondage", preoccupation="un fil en cours",
               recent_thoughts=[_thought("ma dernière pensée")])
    out = agent._format_context(ctx)
    assert "Dernière pensée" in out


def test_recent_thought_kept_when_not_idle():
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    ctx = _ctx(idle_seed=None, preoccupation=None,
               recent_thoughts=[_thought("ma dernière pensée")])
    out = agent._format_context(ctx)
    assert "Dernière pensée" in out


# --- Phase 2b : exclusion du focus + introspection ------------------------ #

def test_seed_overlaps_focus():
    assert _seed_overlaps_focus(
        "Creuser jubeii1979 origine du souvenir Apex Legends",
        "jubeii1979 origine du souvenir Apex Legends floue",
    )
    assert not _seed_overlaps_focus(
        "Demander à Cluth ses jeux de course",
        "jubeii1979 origine du souvenir Apex",
    )


@pytest.mark.asyncio
async def test_idle_seed_introspection_fires(monkeypatch):
    agent = AttentionAgent(fact_store=None)
    # force la branche introspection
    monkeypatch.setattr("bot.intelligence.attention_agent.random.random", lambda: 0.0)
    seed, rss = await agent._build_idle_seed({}, [], [], "night", _FakeCat, None)
    assert seed in _INTROSPECTION_SEEDS
    assert rss is None


@pytest.mark.asyncio
async def test_idle_seed_excludes_focused_desire(monkeypatch):
    # pas d'introspection (random élevé), pas de souvenir/pensée échantillonnés
    monkeypatch.setattr("bot.intelligence.attention_agent.random.random", lambda: 0.99)

    class _Facts:
        async def sample_random(self, **k):
            return []

    agent = AttentionAgent(fact_store=_Facts())
    focus = "jubeii1979 origine du souvenir Apex Legends floue"
    focused = SimpleNamespace(content="Creuser jubeii1979 origine souvenir Apex Legends")
    other = SimpleNamespace(content="Demander à Cluth ses jeux de course préférés")
    seed, _ = await agent._build_idle_seed({}, [focused, other], [], "night", _FakeCat, focus)
    # le désir lié au focus est exclu → seul "Cluth" peut sortir (ou un fallback)
    assert "jubeii" not in (seed or "").lower()


class _FakeCat:
    THOUGHT = "THOUGHT"
