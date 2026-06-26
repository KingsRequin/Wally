"""Tests ResponseGate."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.gate import ResponseGate, GateDecision
from bot.intelligence.memory.facts import AtomicFact, FactCategory, SQLiteFactStore


def make_gate(llm_result: dict | None = None, llm_raises: bool = False):
    llm = MagicMock()
    if llm_raises:
        llm.complete_structured = AsyncMock(side_effect=RuntimeError("LLM failed"))
    else:
        llm.complete_structured = AsyncMock(return_value=llm_result or {"decision": "RESPOND"})

    fact_store = MagicMock()
    fact_store.add = AsyncMock(return_value=1)

    return ResponseGate(llm=llm, fact_store=fact_store, prompts_dir="bot/intelligence/persona/prompts")


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


@pytest.mark.asyncio
async def test_decide_dm_always_responds_without_llm():
    """En DM (is_dm=True), gate retourne RESPOND sans appeler le LLM."""
    gate = make_gate({"decision": "IGNORE"})  # le LLM dirait IGNORE...
    result = await gate.decide("ca", "discord:123", EMOTION_STATE, [], [], is_dm=True)
    assert result.decision == "RESPOND"           # ...mais le DM force RESPOND
    gate._llm.complete_structured.assert_not_called()


@pytest.mark.asyncio
async def test_decide_dm_respects_ignored_user():
    """is_ignored a priorité sur is_dm : un utilisateur banni reste ignoré."""
    gate = make_gate()
    result = await gate.decide("ca", "discord:123", EMOTION_STATE, [], [],
                               is_dm=True, is_ignored=True)
    assert result.decision == "IGNORE"
    gate._llm.complete_structured.assert_not_called()


@pytest.mark.asyncio
async def test_decide_includes_recent_thread_in_prompt():
    """Le fil récent passé à decide() apparaît dans le message envoyé au LLM."""
    gate = make_gate({"decision": "RESPOND"})
    thread = [
        {"author": "KingsRequin", "content": "c'est nul ta blague"},
        {"author": "Wally", "content": "assume, c'est le degré zéro"},
    ]
    await gate.decide("c'est pas déjà le cas ?", "discord:123", EMOTION_STATE, [], [],
                      recent_messages=thread)
    sent = gate._llm.complete_structured.call_args.kwargs["messages"][0]["content"]
    assert "KingsRequin: c'est nul ta blague" in sent
    assert "Wally: assume" in sent
