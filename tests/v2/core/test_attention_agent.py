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


@pytest.mark.asyncio
async def test_build_context_non_idle_has_no_seed():
    """En mode normal (idle=False), idle_seed est None."""
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context({"joy": 0.5}, [])
    assert ctx.idle_seed is None


@pytest.mark.asyncio
async def test_build_context_idle_produces_seed():
    """En mode idle, idle_seed est une amorce non vide construite à partir
    d'une source disponible (souvenir, but, désir, émotion ou heure)."""
    memory = _make_fact(FactCategory.FAIT, "Kaelis aime le jazz")
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[memory])
    agent = AttentionAgent(store)
    ctx = await agent.build_context(
        {"joy": 0.8, "anger": 0.0, "boredom": 0.3}, [], idle=True
    )
    assert ctx.idle_seed
    assert isinstance(ctx.idle_seed, str)


@pytest.mark.asyncio
async def test_build_context_idle_excludes_thought_from_memory_seed():
    """sample_random est appelé en excluant THOUGHT (pas de pensée comme souvenir)."""
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    await agent.build_context({"joy": 0.5}, [], idle=True)
    store.sample_random.assert_called_once()
    assert store.sample_random.call_args.kwargs["exclude_category"] == FactCategory.THOUGHT


@pytest.mark.asyncio
async def test_build_context_idle_falls_back_to_emotion_or_time():
    """Même sans souvenir/but/désir, l'heure ou l'émotion fournit une amorce."""
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [], idle=True)  # rien sauf l'heure
    assert ctx.idle_seed  # l'heure est toujours disponible


# ── Phase 1b : pulsion émotionnelle ──

@pytest.mark.asyncio
async def test_build_context_populates_emotional_drive_when_dominant():
    """Une émotion dominante au-dessus du seuil peuple emotional_drive."""
    from bot.v2.core.emotional_drive import _DRIVES
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context(
        {"boredom": 0.8, "anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0}, []
    )
    assert ctx.emotional_drive == _DRIVES["boredom"]


@pytest.mark.asyncio
async def test_build_context_no_drive_when_neutral():
    """État neutre (aucune émotion au-dessus du seuil) → emotional_drive None."""
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context(
        {"boredom": 0.2, "anger": 0.1, "joy": 0.1, "sadness": 0.0, "curiosity": 0.3}, []
    )
    assert ctx.emotional_drive is None
