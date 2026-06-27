"""Tests Phase 6 — conscience des demandes d'amélioration.

Couvre le rendu du bloc « déjà demandées » dans le prompt de raisonnement et la
garde anti-redemande de SelfFix.
"""
from pathlib import Path

import pytest

from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.reasoning_agent import ReasoningAgent
from bot.intelligence.self_fix import SelfFix, UpgradeRequest
from bot.intelligence.upgrade_registry import UpgradeRow, DELIVERED

_PROMPTS = Path(__file__).parent.parent.parent / "bot" / "intelligence" / "persona" / "prompts"


def _ctx(**over):
    base = dict(
        emotion_state={"joy": 0.1},
        active_desires=[], active_goals=[], recent_thoughts=[],
        recent_interactions=[], time_of_day="morning",
    )
    base.update(over)
    return AttentionContext(**base)


def test_format_context_renders_upgrade_block():
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    ctx = _ctx(upgrade_requests=[
        UpgradeRow(id=1, proposal="voir les réactions emoji sur les messages",
                   status=DELIVERED, created_at="2026-06-25T10:00", decided_at=None),
    ])
    out = agent._format_context(ctx)
    assert "déjà demandées" in out
    assert "réactions emoji" in out
    assert "DÉJÀ LIVRÉE" in out


def test_format_context_omits_block_when_empty():
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    out = agent._format_context(_ctx(upgrade_requests=[]))
    assert "déjà demandées" not in out


class _FakeRegistry:
    def __init__(self, hit):
        self._hit = hit
        self.recorded = []

    async def find_similar(self, proposal, threshold=0.3):
        return self._hit

    async def record_request(self, proposal):
        self.recorded.append(proposal)
        return 99

    async def set_status(self, *a):
        pass


class _FakeBot:
    memory = None  # _record_outcome best-effort -> no-op
    def __init__(self):
        self.config = None


@pytest.mark.asyncio
async def test_request_upgrade_blocked_when_similar_exists():
    hit = UpgradeRow(id=7, proposal="accès aux réactions emoji", status=DELIVERED,
                     created_at="2026-06-25T10:00", decided_at="2026-06-25T11:00")
    reg = _FakeRegistry(hit)
    sf = SelfFix(bridge=None, bot=_FakeBot(), registry=reg)
    await sf.request_upgrade(UpgradeRequest(goal="voir les réactions emoji des gens"))
    # garde anti-redemande : rien n'est ré-enregistré, pas d'exécution
    assert reg.recorded == []
    assert sf._pending is False


@pytest.mark.asyncio
async def test_request_upgrade_force_bypasses_guard():
    """force=True (demande explicite du créateur) outrepasse la garde — la demande
    est enregistrée même si une similaire existe (l'exécution échoue ensuite faute
    d'owner configuré, ce qui est attendu hors intégration)."""
    hit = UpgradeRow(id=7, proposal="accès aux réactions emoji", status=DELIVERED,
                     created_at="2026-06-25T10:00", decided_at=None)
    reg = _FakeRegistry(hit)
    sf = SelfFix(bridge=None, bot=_FakeBot(), registry=reg)
    await sf.request_upgrade(UpgradeRequest(goal="voir les réactions emoji"), force=True)
    assert reg.recorded == ["voir les réactions emoji"]
