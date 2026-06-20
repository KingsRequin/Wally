"""Tests ResponseGate."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from wally_v2.core.gate import ResponseGate, GateDecision
from wally_v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore


def make_gate(llm_result: dict | None = None, llm_raises: bool = False):
    llm = MagicMock()
    if llm_raises:
        llm.complete_structured = AsyncMock(side_effect=RuntimeError("LLM failed"))
    else:
        llm.complete_structured = AsyncMock(return_value=llm_result or {"decision": "RESPOND"})

    fact_store = MagicMock()
    fact_store.add = AsyncMock(return_value=1)

    return ResponseGate(llm=llm, fact_store=fact_store, prompts_dir="wally_v2/persona/prompts")


EMOTION_STATE = {"anger": 0.1, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.1}


@pytest.mark.asyncio
async def test_decide_respond_default():
    """decide() retourne RESPOND par défaut."""
    gate = make_gate({"decision": "RESPOND"})
    result = await gate.decide("Salut !", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "RESPOND"


@pytest.mark.asyncio
async def test_decide_ignore_stores_emotional_fact():
    """Si IGNORE, un AtomicFact EMOTION est créé en SQLite."""
    gate = make_gate({"decision": "IGNORE", "reason": "trop de spam"})
    result = await gate.decide("encore moi", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "IGNORE"
    gate._fact_store.add.assert_called_once()
    call_args = gate._fact_store.add.call_args[0][0]
    assert isinstance(call_args, AtomicFact)
    assert call_args.category == FactCategory.EMOTION
    assert "discord:123" == call_args.user_id


@pytest.mark.asyncio
async def test_decide_react_returns_emoji():
    """decide() avec REACT retourne l'emoji fourni."""
    gate = make_gate({"decision": "REACT", "emoji": "👀"})
    result = await gate.decide("haha", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "REACT"
    assert result.emoji == "👀"


@pytest.mark.asyncio
async def test_decide_defer_returns_seconds():
    """decide() avec DEFER retourne defer_seconds."""
    gate = make_gate({"decision": "DEFER", "defer_seconds": 300})
    result = await gate.decide("msg", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "DEFER"
    assert result.defer_seconds == 300


@pytest.mark.asyncio
async def test_decide_fallback_to_respond_on_llm_error():
    """Si le LLM lève une exception, gate retourne RESPOND (fail-safe)."""
    gate = make_gate(llm_raises=True)
    result = await gate.decide("msg", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "RESPOND"


@pytest.mark.asyncio
async def test_decide_is_ignored_bypasses_llm():
    """Si is_ignored=True, gate retourne immédiatement IGNORE sans appel LLM."""
    gate = make_gate()
    result = await gate.decide("msg", "discord:123", EMOTION_STATE, [], [], is_ignored=True)
    assert result.decision == "IGNORE"
    gate._llm.complete_structured.assert_not_called()
