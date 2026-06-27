"""Tests Phase 4 — garde langue française du monologue cognitif."""
from pathlib import Path

import pytest
from unittest.mock import AsyncMock

from bot.intelligence.reasoning_agent import ReasoningAgent

_PROMPTS = Path(__file__).parent.parent.parent / "bot" / "intelligence" / "persona" / "prompts"


class _Facts:
    async def add(self, fact):
        return 1


def _ctx():
    from bot.intelligence.attention_agent import AttentionContext
    return AttentionContext(
        emotion_state={"joy": 0.1}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="night",
    )


@pytest.mark.asyncio
async def test_english_thought_triggers_one_regeneration():
    agent = ReasoningAgent(llm=None, fact_store=_Facts(), prompts_dir=_PROMPTS)
    # 1er appel anglais, 2e appel français → une seule régénération
    agent._llm = type("LLM", (), {})()
    agent._llm.complete_with_reasoning = AsyncMock(side_effect=[
        ("[THINK]", "I am thinking about the weather and the stream tonight, it is boring"),
        ("[THINK]", "Je réfléchis à la météo et au stream de ce soir, c'est plutôt ennuyeux"),
    ])
    result = await agent.reason(_ctx())
    assert agent._llm.complete_with_reasoning.call_count == 2
    assert "Je réfléchis" in result.thought_text


@pytest.mark.asyncio
async def test_french_thought_no_regeneration():
    agent = ReasoningAgent(llm=None, fact_store=_Facts(), prompts_dir=_PROMPTS)
    agent._llm = type("LLM", (), {})()
    agent._llm.complete_with_reasoning = AsyncMock(return_value=(
        "[THINK]", "Je me demande ce que les gens font ce soir sur le serveur, tranquille",
    ))
    await agent.reason(_ctx())
    assert agent._llm.complete_with_reasoning.call_count == 1


@pytest.mark.asyncio
async def test_persistent_english_is_published_anyway():
    agent = ReasoningAgent(llm=None, fact_store=_Facts(), prompts_dir=_PROMPTS)
    agent._llm = type("LLM", (), {})()
    agent._llm.complete_with_reasoning = AsyncMock(side_effect=[
        ("[THINK]", "I keep thinking in english about the game and the players tonight"),
        ("[THINK]", "Still thinking in english despite the instruction, nothing to do here"),
    ])
    result = await agent.reason(_ctx())
    assert agent._llm.complete_with_reasoning.call_count == 2  # une seule régén
    assert result.thought_text  # publié quand même (ne bloque pas le tick)
