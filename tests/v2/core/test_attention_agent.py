import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from bot.v2.core.attention_agent import AttentionAgent, AttentionContext
from bot.v2.core.memory.facts import AtomicFact, FactCategory, FactStatus


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
    store.search_by_category = AsyncMock(side_effect=fake_search)
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [])
    assert ctx.active_desires == [desire]
    assert ctx.active_goals == [goal]
    assert ctx.recent_thoughts == [thought]

    # Verify correct limits were passed
    calls = store.search_by_category.call_args_list
    desire_call = next(c for c in calls if c.args[0] == FactCategory.DESIRE)
    goal_call = next(c for c in calls if c.args[0] == FactCategory.GOAL)
    thought_call = next(c for c in calls if c.args[0] == FactCategory.THOUGHT)
    assert desire_call.kwargs.get("limit", desire_call.args[2] if len(desire_call.args) > 2 else 10) == 5
    assert goal_call.kwargs.get("limit", goal_call.args[2] if len(goal_call.args) > 2 else 10) == 5
    assert thought_call.kwargs.get("limit", thought_call.args[2] if len(thought_call.args) > 2 else 10) == 3


@pytest.mark.asyncio
async def test_build_context_time_of_day_values():
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [])
    assert ctx.time_of_day in ("morning", "afternoon", "evening", "night")


@pytest.mark.asyncio
async def test_build_context_truncates_interactions_to_10():
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    # 15 interactions — should be truncated to last 10
    interactions = [
        {"channel": "1", "author": f"user{i}", "content": f"msg{i}", "ts": float(i)}
        for i in range(15)
    ]
    ctx = await agent.build_context({}, interactions)
    assert len(ctx.recent_interactions) == 10
    # Should be the LAST 10 (indices 5-14)
    assert ctx.recent_interactions[0]["author"] == "user5"
    assert ctx.recent_interactions[-1]["author"] == "user14"
