import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from wally_v2.core.attention_agent import AttentionAgent, AttentionContext
from wally_v2.core.memory.facts import AtomicFact, FactCategory, FactStatus


def _make_fact(category: FactCategory, content: str = "test") -> AtomicFact:
    now = datetime.now(timezone.utc).isoformat()
    return AtomicFact(
        user_id="wally:self",
        content=content,
        category=category,
        confidence=0.9,
        created_at=now,
        last_seen_at=now,
    )


@pytest.mark.asyncio
async def test_build_context_returns_emotion_state():
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    emotion = {"joy": 0.8, "anger": 0.0, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.1}
    ctx = await agent.build_context(emotion, [])
    assert ctx.emotion_state == emotion


@pytest.mark.asyncio
async def test_build_context_loads_desires_goals_thoughts():
    desire = _make_fact(FactCategory.DESIRE, "désir de parler")
    goal = _make_fact(FactCategory.GOAL, "objectif long terme")
    thought = _make_fact(FactCategory.THOUGHT, "pensée récente")

    async def fake_search(category, status=FactStatus.ACTIVE, limit=10):
        if category == FactCategory.DESIRE:
            return [desire]
        if category == FactCategory.GOAL:
            return [goal]
        if category == FactCategory.THOUGHT:
            return [thought]
        return []

    store = MagicMock()
    store.search_by_category = fake_search
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [])
    assert ctx.active_desires == [desire]
    assert ctx.active_goals == [goal]
    assert ctx.recent_thoughts == [thought]


@pytest.mark.asyncio
async def test_build_context_time_of_day_values():
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [])
    assert ctx.time_of_day in ("morning", "afternoon", "evening", "night")
