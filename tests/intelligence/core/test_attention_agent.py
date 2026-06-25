import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.attention_agent import AttentionAgent, AttentionContext
from bot.intelligence.memory.facts import AtomicFact, FactCategory, FactStatus


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
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
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
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
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
async def test_build_context_emotes_expose_postable_code():
    # Note d'usage apprise pour l'emote "pepe" (clé = nom nu, valeur = usage).
    note = _make_fact(FactCategory.PREF, "pepe → quand quelqu'un est triste")

    async def fake_get_by_user(user_id, categories=None):
        return [note] if user_id == "wally:emotes" else []

    store = MagicMock()
    store.get_by_user = AsyncMock(side_effect=fake_get_by_user)
    store.get_latest_by_source = AsyncMock(return_value=None)
    store.search_by_category = AsyncMock(return_value=[])

    # Le provider renvoie des paires (nom, code postable "<:nom:id>").
    agent = AttentionAgent(
        store,
        emote_provider=lambda: [("pepe", "<:pepe:111>"), ("kek", "<:kek:222>")],
    )
    ctx = await agent.build_context({}, [])

    # Emote connue → "<code> → usage" (le CODE postable, pas le nom nu).
    assert ctx.emotes_known == ["<:pepe:111> → quand quelqu'un est triste"]
    # Emote inconnue → le code postable seul (Wally peut quand même l'utiliser).
    assert ctx.emotes_unknown == ["<:kek:222>"]


@pytest.mark.asyncio
async def test_build_context_emotes_dedup_by_name():
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    store.search_by_category = AsyncMock(return_value=[])

    # Même nom présent sur deux serveurs → une seule entrée (le premier code).
    agent = AttentionAgent(
        store,
        emote_provider=lambda: [("pepe", "<:pepe:111>"), ("pepe", "<:pepe:999>")],
    )
    ctx = await agent.build_context({}, [])
    assert ctx.emotes_unknown == ["<:pepe:111>"]


@pytest.mark.asyncio
async def test_build_context_time_of_day_values():
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    store.search_by_category = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [])
    assert ctx.time_of_day in ("morning", "afternoon", "evening", "night")


@pytest.mark.asyncio
async def test_build_context_truncates_interactions_to_10():
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
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
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
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
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
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
    """sample_random est appelé deux fois en idle :
    1. exclude_category=THOUGHT (souvenirs factuels)
    2. include_category=THOUGHT (pensées passées pour alimenter le vagabondage)
    """
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    await agent.build_context({"joy": 0.5}, [], idle=True)
    assert store.sample_random.call_count == 2
    calls_kwargs = [c.kwargs for c in store.sample_random.call_args_list]
    assert any(kw.get("exclude_category") == FactCategory.THOUGHT for kw in calls_kwargs)
    assert any(kw.get("include_category") == FactCategory.THOUGHT for kw in calls_kwargs)


@pytest.mark.asyncio
async def test_build_context_idle_falls_back_to_emotion_or_time():
    """Même sans souvenir/but/désir, l'heure ou l'émotion fournit une amorce."""
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [], idle=True)  # rien sauf l'heure
    assert ctx.idle_seed  # l'heure est toujours disponible


# ── Phase 1b : pulsion émotionnelle ──

@pytest.mark.asyncio
async def test_build_context_populates_emotional_drive_when_dominant():
    """Une émotion dominante au-dessus du seuil peuple emotional_drive."""
    from bot.intelligence.emotional_drive import _DRIVES
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
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
    store.get_by_user = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context(
        {"boredom": 0.2, "anger": 0.1, "joy": 0.1, "sadness": 0.0, "curiosity": 0.3}, []
    )
    assert ctx.emotional_drive is None


# ── Phase 3a : préoccupation courante (fil de pensée continu) ──

def _latest_by_source(focus=None, self_narrative=None):
    """Helper : side_effect pour get_latest_by_source qui distingue par source.

    build_context interroge get_latest_by_source DEUX fois (source="focus" pour
    la préoccupation, source="self_narrative" pour le récit de soi) ; un
    return_value unique les confondrait. On route donc par argument `source`.
    """
    async def _fn(user_id, source, category=None):
        if source == "focus":
            return focus
        if source == "self_narrative":
            return self_narrative
        return None
    return _fn


@pytest.mark.asyncio
async def test_build_context_populates_preoccupation():
    """build_context peuple preoccupation depuis le dernier fait focus."""
    focus = _make_fact(FactCategory.THOUGHT, "comprendre Kaelis")
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(side_effect=_latest_by_source(focus=focus))
    agent = AttentionAgent(store)
    ctx = await agent.build_context({"joy": 0.5}, [])
    assert ctx.preoccupation == "comprendre Kaelis"
    store.get_latest_by_source.assert_any_call("wally:self", "focus")


@pytest.mark.asyncio
async def test_build_context_preoccupation_none_when_no_focus():
    """Aucun fait focus → preoccupation None."""
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    agent = AttentionAgent(store)
    ctx = await agent.build_context({"joy": 0.5}, [])
    assert ctx.preoccupation is None


# ── Phase 3b : récit de soi (qui je deviens) ──

@pytest.mark.asyncio
async def test_build_context_populates_self_narrative():
    """build_context peuple self_narrative depuis le dernier fait self_narrative."""
    sn = _make_fact(FactCategory.THOUGHT, "je deviens plus posé")
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(side_effect=_latest_by_source(self_narrative=sn))
    agent = AttentionAgent(store)
    ctx = await agent.build_context({"joy": 0.5}, [])
    assert ctx.self_narrative == "je deviens plus posé"
    store.get_latest_by_source.assert_any_call("wally:self", "self_narrative")


@pytest.mark.asyncio
async def test_build_context_self_narrative_none_when_absent():
    """Aucun fait self_narrative → self_narrative None."""
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    agent = AttentionAgent(store)
    ctx = await agent.build_context({"joy": 0.5}, [])
    assert ctx.self_narrative is None


# ── Phase 3c : affinités (opinions auto-dirigées sur les gens) ──

@pytest.mark.asyncio
async def test_build_context_populates_relationships():
    """build_context peuple relationships depuis get_by_user("wally:self", [REL])."""
    rel1 = _make_fact(FactCategory.REL, "Kaelis — drôle mais lourd")
    rel2 = _make_fact(FactCategory.REL, "Azrael — je lui fais confiance")
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[rel1, rel2])
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    agent = AttentionAgent(store)
    ctx = await agent.build_context({"joy": 0.5}, [])
    assert ctx.relationships == [rel1, rel2]
    store.get_by_user.assert_any_call("wally:self", categories=[FactCategory.REL])


@pytest.mark.asyncio
async def test_build_context_relationships_empty_when_none():
    """Aucun fait REL → relationships liste vide."""
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=[])
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    agent = AttentionAgent(store)
    ctx = await agent.build_context({"joy": 0.5}, [])
    assert ctx.relationships == []


@pytest.mark.asyncio
async def test_build_context_relationships_capped_at_5():
    """Seules les ~5 opinions les plus récentes sont gardées."""
    rels = [_make_fact(FactCategory.REL, f"Pers{i} — avis {i}") for i in range(8)]
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=rels)
    store.search_by_category = AsyncMock(return_value=[])
    store.sample_random = AsyncMock(return_value=[])
    store.get_latest_by_source = AsyncMock(return_value=None)
    agent = AttentionAgent(store)
    ctx = await agent.build_context({"joy": 0.5}, [])
    assert len(ctx.relationships) == 5
    assert ctx.relationships == rels[:5]
