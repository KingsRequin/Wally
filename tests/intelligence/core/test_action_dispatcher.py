import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio


@pytest_asyncio.fixture
async def tmp_fact_store(tmp_path):
    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.memory.facts import SQLiteFactStore
    db_path = str(tmp_path / "test.db")
    await create_v2_tables(db_path)
    return SQLiteFactStore(db_path)


@pytest.mark.asyncio
async def test_act_create_memory(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    from bot.intelligence.meta_agent import MetaDecision
    decision = MetaDecision(action="ACT", act_name="create_memory", act_args={"fact_content": "test memory content"})
    await dispatcher.dispatch(decision)
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.THOUGHT])
    assert len(facts) == 1
    assert facts[0].content == "test memory content"
    assert facts[0].category == FactCategory.THOUGHT
    assert facts[0].confidence == 1.0


@pytest.mark.asyncio
async def test_act_create_goal(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    from bot.intelligence.meta_agent import MetaDecision
    decision = MetaDecision(action="ACT", act_name="create_goal", act_args={"description": "learn new skills"})
    await dispatcher.dispatch(decision)
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.GOAL])
    assert len(facts) == 1
    assert facts[0].content == "learn new skills"
    assert facts[0].category == FactCategory.GOAL
    assert facts[0].decay_rate == 0.005


@pytest.mark.asyncio
async def test_act_create_desire(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    from bot.intelligence.meta_agent import MetaDecision
    decision = MetaDecision(action="ACT", act_name="create_desire", act_args={"content": "explore music"})
    await dispatcher.dispatch(decision)
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.DESIRE])
    assert len(facts) == 1
    assert facts[0].content == "explore music"
    assert facts[0].confidence == 0.8


@pytest.mark.asyncio
async def test_act_code_fix_is_noop(tmp_fact_store):
    """code_fix MUST log a warning and do nothing — security constraint."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    from bot.intelligence.meta_agent import MetaDecision
    decision = MetaDecision(action="ACT", act_name="code_fix", act_args={"path": "/etc/passwd", "code": "rm -rf /"})
    with patch("bot.intelligence.action_dispatcher.logger") as mock_logger:
        await dispatcher.dispatch(decision)
        mock_logger.warning.assert_called_once()
    # No facts must have been created
    facts = await tmp_fact_store.get_by_user("wally:self")
    assert len(facts) == 0


@pytest.mark.asyncio
async def test_dispatch_evolve_delegates_to_persona_manager():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision
    persona = MagicMock()
    persona.evolve = AsyncMock()
    dispatcher = ActionDispatcher(persona_manager=persona)
    decision = MetaDecision(action="EVOLVE", section="EMOTIONS", change="be more curious")
    await dispatcher.dispatch(decision)
    persona.evolve.assert_called_once_with("EMOTIONS", "be more curious")


import pytest as _pytest_fd
from unittest.mock import AsyncMock as _AMd, MagicMock as _MMd
from bot.intelligence.action_dispatcher import ActionDispatcher as _AD
from bot.intelligence.meta_agent import MetaDecision as _MDd


@_pytest_fd.mark.asyncio
async def test_speak_publishes_to_feed():
    feed = _MMd()
    channel = _MMd()
    channel.send = _AMd()
    bot = _MMd()
    bot.get_channel.return_value = channel
    disp = _AD(bot=bot, feed=feed)
    await disp.dispatch(_MDd(action="SPEAK", channel_id="123", message="salut"))
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "SPEAK" in types


@_pytest_fd.mark.asyncio
async def test_speak_records_wally_message_in_memory():
    """Le SPEAK cognitif doit s'enregistrer dans le contexte que lit le chemin réactif,
    sinon Wally oublie ses propres messages spontanés (bug d'amnésie)."""
    channel = _MMd()
    channel.send = _AMd()
    bot = _MMd()
    bot.get_channel.return_value = channel
    disp = _AD(bot=bot)
    await disp.dispatch(_MDd(action="SPEAK", channel_id="123", message="salut"))
    bot.memory.append_prelude.assert_called_once_with("123", "Wally", "salut")
    bot.memory.append_message.assert_called_once_with("123", "Wally", "salut", platform="discord")


@_pytest_fd.mark.asyncio
async def test_speak_logged_to_conv_log_as_message_out():
    """Le SPEAK cognitif est tracé dans le conv_log du canal (chronologie/débogage),
    sinon un message spontané réellement envoyé n'apparaît dans aucun log de canal."""
    channel = _MMd()
    channel.send = _AMd()
    channel.name = "chambre-de-wally"
    channel.guild.name = "Le Purgatoire"
    bot = _MMd()
    bot.get_channel.return_value = channel
    conv_log = _MMd()
    bot.conv_log = conv_log
    disp = _AD(bot=bot)
    await disp.dispatch(_MDd(action="SPEAK", channel_id="123", message="salut"))
    conv_log.log.assert_called_once()
    args, kwargs = conv_log.log.call_args
    assert args[0] == "discord"
    assert args[1] == "Le Purgatoire/chambre-de-wally"
    assert args[2] == "message_out"
    assert kwargs["kind"] == "cognitive"
    assert kwargs["content"] == "salut"


@pytest.mark.asyncio
async def test_act_create_memory_event_carries_full(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision
    feed = MagicMock()
    long = "x" * 400
    disp = ActionDispatcher(fact_store=tmp_fact_store, feed=feed)
    await disp.dispatch(MetaDecision(action="ACT", act_name="create_memory",
                                     act_args={"fact_content": long}))
    ev = next(c.args[0] for c in feed.publish.call_args_list
              if c.args and c.args[0].get("type") == "ACT")
    assert len(ev["detail"]) <= 300
    assert ev["full"] == f"create_memory: {long}"
    assert ev["detail"] == f"create_memory: {long}"[:300]


@_pytest_fd.mark.asyncio
async def test_dm_records_wally_message_in_memory():
    """Le DM cognitif au créateur doit s'enregistrer dans le contexte du canal DM,
    pour que Wally se souvienne de la question qu'il a posée."""
    sent = _MMd()
    sent.channel.id = 999
    user = _MMd()
    user.send = _AMd(return_value=sent)
    bot, _u = _bot_with_config(owner_id=OWNER_ID, name="Wally")
    bot.fetch_user = _AMd(return_value=user)
    disp = _AD(bot=bot)
    await disp.dispatch(_MDd(action="ACT", act_name="dm",
                             act_args={"user_id": "610550333042589752", "message": "coucou"}))
    bot.memory.append_prelude.assert_called_once_with("999", "Wally", "coucou")
    bot.memory.append_message.assert_called_once_with("999", "Wally", "coucou", platform="discord")


@pytest.mark.asyncio
async def test_act_advance_goal_appends_progress(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import AtomicFact, FactCategory
    from bot.intelligence.meta_agent import MetaDecision

    gid = await tmp_fact_store.add(AtomicFact(
        user_id="wally:self", content="Mon objectif", category=FactCategory.GOAL,
    ))
    feed = MagicMock()
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store, feed=feed)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="advance_goal",
        act_args={"goal_id": gid, "step": "premier pas concret"},
    ))
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.GOAL])
    assert "· premier pas concret" in facts[0].content
    assert "— progression —" in facts[0].content
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "ACT" in types


@pytest.mark.asyncio
async def test_act_advance_goal_goal_id_as_str(tmp_fact_store):
    """goal_id en str est accepté (le LLM peut l'envoyer ainsi)."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import AtomicFact, FactCategory
    from bot.intelligence.meta_agent import MetaDecision

    gid = await tmp_fact_store.add(AtomicFact(
        user_id="wally:self", content="But", category=FactCategory.GOAL,
    ))
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="advance_goal",
        act_args={"goal_id": str(gid), "step": "un pas"},
    ))
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.GOAL])
    assert "· un pas" in facts[0].content


@pytest.mark.asyncio
async def test_act_advance_goal_missing_args_no_crash(tmp_fact_store):
    """goal_id absent / invalide ne crash pas, ne modifie rien."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    # goal_id manquant
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="advance_goal", act_args={"step": "un pas"},
    ))
    # goal_id invalide
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="advance_goal",
        act_args={"goal_id": "abc", "step": "un pas"},
    ))
    # step manquant
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="advance_goal", act_args={"goal_id": 1},
    ))


@pytest.mark.asyncio
async def test_act_fulfill_goal_archives(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import AtomicFact, FactCategory, FactStatus
    from bot.intelligence.meta_agent import MetaDecision

    gid = await tmp_fact_store.add(AtomicFact(
        user_id="wally:self", content="But à finir", category=FactCategory.GOAL,
    ))
    feed = MagicMock()
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store, feed=feed)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="fulfill_goal", act_args={"goal_id": gid},
    ))
    active = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.GOAL])
    assert active == []
    archived = await tmp_fact_store.get_by_user(
        "wally:self", categories=[FactCategory.GOAL], status=FactStatus.ARCHIVED
    )
    assert len(archived) == 1
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "ACT" in types


@pytest.mark.asyncio
async def test_act_fulfill_goal_missing_id_no_crash(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="fulfill_goal", act_args={},
    ))


# ── Phase 2b : react (réaction emoji) ──

@pytest.mark.asyncio
async def test_act_react_adds_reaction():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    message = MagicMock()
    message.add_reaction = AsyncMock()
    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    bot = MagicMock()
    bot.get_channel.return_value = channel
    feed = MagicMock()
    dispatcher = ActionDispatcher(bot=bot, feed=feed)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="react",
        act_args={"channel_id": "123", "message_id": "42", "emoji": "🔥"},
    ))
    channel.fetch_message.assert_called_once_with(42)
    message.add_reaction.assert_called_once_with("🔥")
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "REACT" in types


@pytest.mark.asyncio
async def test_act_react_channel_not_found_no_crash():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot = MagicMock()
    bot.get_channel.return_value = None
    dispatcher = ActionDispatcher(bot=bot)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="react",
        act_args={"channel_id": "123", "message_id": "42", "emoji": "🔥"},
    ))


@pytest.mark.asyncio
async def test_act_react_message_not_found_no_crash():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    channel = MagicMock()
    channel.fetch_message = AsyncMock(side_effect=Exception("not found"))
    bot = MagicMock()
    bot.get_channel.return_value = channel
    dispatcher = ActionDispatcher(bot=bot)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="react",
        act_args={"channel_id": "123", "message_id": "42", "emoji": "🔥"},
    ))


@pytest.mark.asyncio
async def test_act_react_missing_args_noop():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot = MagicMock()
    dispatcher = ActionDispatcher(bot=bot)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="react",
        act_args={"channel_id": "", "message_id": "", "emoji": ""},
    ))
    bot.get_channel.assert_not_called()


# ── Phase 2b : note_to_self (note privée) ──

@pytest.mark.asyncio
@pytest.mark.parametrize("kind,expected", [
    ("mood", "EMOTION"),
    ("question", "DESIRE"),
    ("reminder", "DESIRE"),
    ("autre", "THOUGHT"),
])
async def test_act_note_to_self_category(tmp_fact_store, kind, expected):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self",
        act_args={"note": "ne pas oublier ça", "kind": kind},
    ))
    facts = await tmp_fact_store.get_by_user(
        "wally:self", categories=[FactCategory(expected)]
    )
    assert len(facts) == 1
    assert facts[0].content == "ne pas oublier ça"
    assert facts[0].source == "note_to_self"


@pytest.mark.asyncio
async def test_act_note_to_self_reminder_schedules(tmp_fact_store):
    """Un reminder avec in_minutes pose une échéance future (#A3)."""
    from datetime import datetime
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self",
        act_args={"note": "demander à KingsRequin s'il stream", "kind": "reminder",
                  "in_minutes": 90},
    ))
    facts = await tmp_fact_store.get_by_user("wally:self")
    assert len(facts) == 1
    assert facts[0].scheduled_at is not None
    # échéance dans ~90 min (tolérance large)
    delta_min = (facts[0].scheduled_at - datetime.utcnow()).total_seconds() / 60
    assert 80 < delta_min < 100
    # pas encore dû
    assert await tmp_fact_store.get_due_facts(datetime.utcnow()) == []


@pytest.mark.asyncio
async def test_act_note_to_self_without_in_minutes_no_schedule(tmp_fact_store):
    """Une note ordinaire (sans in_minutes) n'a pas d'échéance."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self",
        act_args={"note": "juste une pensée", "kind": "reminder"},
    ))
    facts = await tmp_fact_store.get_by_user("wally:self")
    assert facts[0].scheduled_at is None


@pytest.mark.asyncio
async def test_act_note_to_self_empty_noop(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self", act_args={"note": "  ", "kind": "mood"},
    ))
    facts = await tmp_fact_store.get_by_user("wally:self")
    assert facts == []


# ── Phase 3a : set_focus (préoccupation courante) ──

@pytest.mark.asyncio
async def test_act_set_focus_adds_focus_fact(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    from bot.intelligence.meta_agent import MetaDecision

    feed = MagicMock()
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store, feed=feed)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="set_focus",
        act_args={"focus": "comprendre pourquoi Kaelis m'évite"},
    ))
    latest = await tmp_fact_store.get_latest_by_source("wally:self", "focus")
    assert latest is not None
    assert latest.content == "comprendre pourquoi Kaelis m'évite"
    assert latest.category == FactCategory.THOUGHT
    assert latest.source == "focus"
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "ACT" in types


@pytest.mark.asyncio
async def test_act_set_focus_archives_previous(tmp_fact_store):
    """Un 2e set_focus archive le précédent : une seule préoccupation active."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory, FactStatus
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="set_focus", act_args={"focus": "première préoccupation"},
    ))
    # Simuler 10+ min écoulées pour bypasser le cooldown.
    dispatcher._last_focus_ts = 0.0
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="set_focus", act_args={"focus": "deuxième préoccupation"},
    ))
    # Le dernier focus actif est le second.
    latest = await tmp_fact_store.get_latest_by_source("wally:self", "focus")
    assert latest.content == "deuxième préoccupation"
    # Un seul fait focus actif au total.
    active = await tmp_fact_store.get_by_user(
        "wally:self", categories=[FactCategory.THOUGHT]
    )
    focus_active = [f for f in active if f.source == "focus"]
    assert len(focus_active) == 1
    # Le premier est archivé.
    archived = await tmp_fact_store.get_by_user(
        "wally:self", categories=[FactCategory.THOUGHT], status=FactStatus.ARCHIVED
    )
    assert any(f.content == "première préoccupation" for f in archived)


@pytest.mark.asyncio
async def test_act_set_focus_empty_noop(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="set_focus", act_args={"focus": "  "},
    ))
    assert await tmp_fact_store.get_latest_by_source("wally:self", "focus") is None


# ── Phase 3b : reflect_self (récit de soi cumulatif) ──

@pytest.mark.asyncio
async def test_act_reflect_self_adds_narrative_fact(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    from bot.intelligence.meta_agent import MetaDecision

    feed = MagicMock()
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store, feed=feed)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="reflect_self",
        act_args={"narrative": "Je deviens un peu moins sec avec les gens."},
    ))
    latest = await tmp_fact_store.get_latest_by_source("wally:self", "self_narrative")
    assert latest is not None
    assert latest.content == "Je deviens un peu moins sec avec les gens."
    assert latest.category == FactCategory.THOUGHT
    assert latest.source == "self_narrative"
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "ACT" in types


@pytest.mark.asyncio
async def test_act_reflect_self_empty_noop(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="reflect_self", act_args={"narrative": "  "},
    ))
    assert await tmp_fact_store.get_latest_by_source("wally:self", "self_narrative") is None


@pytest.mark.asyncio
async def test_act_reflect_self_is_cumulative(tmp_fact_store):
    """Le récit de soi s'accumule : 2 reflect_self → 2 faits actifs (pas d'archivage)."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="reflect_self", act_args={"narrative": "premier récit"},
    ))
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="reflect_self", act_args={"narrative": "deuxième récit"},
    ))
    # Les deux récits restent ACTIFS (cumulatif).
    active = await tmp_fact_store.get_by_user(
        "wally:self", categories=[FactCategory.THOUGHT]
    )
    narratives = [f for f in active if f.source == "self_narrative"]
    assert len(narratives) == 2
    # Le dernier surfacé est le second.
    latest = await tmp_fact_store.get_latest_by_source("wally:self", "self_narrative")
    assert latest.content == "deuxième récit"


# ── Phase 3c : note_relation (opinion auto-dirigée sur les gens) ──

@pytest.mark.asyncio
async def test_act_note_relation_adds_rel_fact(tmp_fact_store):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    from bot.intelligence.meta_agent import MetaDecision

    feed = MagicMock()
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store, feed=feed)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_relation",
        act_args={"about": "Kaelis", "opinion": "drôle mais lourd quand il insiste"},
    ))
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.REL])
    assert len(facts) == 1
    assert facts[0].content == "Kaelis — drôle mais lourd quand il insiste"
    assert facts[0].category == FactCategory.REL
    assert facts[0].source == "opinion"
    assert facts[0].confidence == 1.0
    assert facts[0].user_id == "wally:self"
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "ACT" in types


@pytest.mark.asyncio
async def test_act_note_relation_is_cumulative(tmp_fact_store):
    """Pas d'archivage : les opinions s'accumulent (les plus récentes priment)."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.memory.facts import FactCategory
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_relation",
        act_args={"about": "Kaelis", "opinion": "sympa"},
    ))
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_relation",
        act_args={"about": "Kaelis", "opinion": "il m'agace finalement"},
    ))
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.REL])
    assert len(facts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    {"about": "  ", "opinion": "sympa"},
    {"about": "Kaelis", "opinion": "  "},
    {"about": "Kaelis"},
    {"opinion": "sympa"},
    {},
])
async def test_act_note_relation_missing_args_noop(tmp_fact_store, args):
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_relation", act_args=args,
    ))
    facts = await tmp_fact_store.get_by_user("wally:self")
    assert facts == []


# ── Phase 2c : dm (DM Discord, owner-only) ──

OWNER_ID = "610550333042589752"


def _dm_bot():
    """Bot mock avec fetch_user (AsyncMock) → user mock avec send (AsyncMock)."""
    user = MagicMock()
    user.send = AsyncMock()
    bot = MagicMock()
    bot.fetch_user = AsyncMock(return_value=user)
    return bot, user


def _bot_with_config(owner_id: str = OWNER_ID, name: str = "Wally"):
    """Bot mock avec config.bot.owner_discord_id et config.bot.name configurés."""
    bot, user = _dm_bot()
    bot_cfg = MagicMock()
    bot_cfg.owner_discord_id = owner_id
    bot_cfg.name = name
    config = MagicMock()
    config.bot = bot_cfg
    bot.config = config
    return bot, user


@pytest.mark.asyncio
async def test_act_dm_to_owner_sends():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot, user = _bot_with_config(owner_id=OWNER_ID, name="Wally")
    feed = MagicMock()
    dispatcher = ActionDispatcher(bot=bot, feed=feed)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="dm",
        act_args={"user_id": OWNER_ID, "message": "une vraie question ?"},
    ))
    bot.fetch_user.assert_called_once_with(int(OWNER_ID))
    user.send.assert_called_once_with("une vraie question ?")
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "DM" in types


@pytest.mark.asyncio
async def test_act_dm_to_non_owner_blocked():
    """Sécurité : DM vers un autre id que l'owner → send PAS appelé, pas de crash."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot, user = _bot_with_config(owner_id=OWNER_ID, name="Wally")
    dispatcher = ActionDispatcher(bot=bot)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="dm",
        act_args={"user_id": "999999999999999999", "message": "salut"},
    ))
    bot.fetch_user.assert_not_called()
    user.send.assert_not_called()


@pytest.mark.asyncio
async def test_act_dm_missing_args_noop():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot, user = _bot_with_config(owner_id=OWNER_ID, name="Wally")
    dispatcher = ActionDispatcher(bot=bot)
    # message vide
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="dm", act_args={"user_id": OWNER_ID, "message": "  "},
    ))
    # user_id vide
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="dm", act_args={"user_id": "", "message": "salut"},
    ))
    bot.fetch_user.assert_not_called()
    user.send.assert_not_called()


@pytest.mark.asyncio
async def test_act_dm_send_raises_no_crash():
    """user.send lève (DM fermés / Forbidden) → pas de crash, dispatch ne propage pas."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot, user = _bot_with_config(owner_id=OWNER_ID, name="Wally")
    user.send = AsyncMock(side_effect=Exception("DM fermés"))
    dispatcher = ActionDispatcher(bot=bot)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="dm",
        act_args={"user_id": OWNER_ID, "message": "coucou"},
    ))
    user.send.assert_called_once()


# ── Task 6 : owner + étiquettes nom via config.bot ──

@pytest.mark.asyncio
async def test_dm_owner_via_config_accepted():
    """_dm accepte l'owner configuré dans bot.config.bot.owner_discord_id."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot, user = _bot_with_config(owner_id=OWNER_ID, name="Wally")
    feed = MagicMock()
    dispatcher = ActionDispatcher(bot=bot, feed=feed)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="dm",
        act_args={"user_id": OWNER_ID, "message": "via config"},
    ))
    bot.fetch_user.assert_called_once_with(int(OWNER_ID))
    user.send.assert_called_once_with("via config")
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "DM" in types


@pytest.mark.asyncio
async def test_dm_non_owner_via_config_blocked():
    """_dm bloque un non-owner même quand l'owner vient de config.bot."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot, user = _bot_with_config(owner_id=OWNER_ID, name="Wally")
    dispatcher = ActionDispatcher(bot=bot)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="dm",
        act_args={"user_id": "999999999999999999", "message": "non autorisé"},
    ))
    bot.fetch_user.assert_not_called()
    user.send.assert_not_called()


@pytest.mark.asyncio
async def test_dm_owner_unconfigured_no_dm():
    """Quand owner_discord_id est vide dans la config, aucun DM ne part (warning loggé)."""
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    bot, user = _bot_with_config(owner_id="", name="Wally")
    dispatcher = ActionDispatcher(bot=bot)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="dm",
        act_args={"user_id": OWNER_ID, "message": "sans owner configuré"},
    ))
    bot.fetch_user.assert_not_called()
    user.send.assert_not_called()


@pytest.mark.asyncio
async def test_speak_records_configured_bot_name():
    """_record_self_message utilise le nom configuré dans config.bot.name, pas 'Wally' codé en dur."""
    channel = MagicMock()
    channel.send = AsyncMock()
    bot, _user = _bot_with_config(owner_id=OWNER_ID, name="Cindy")
    bot.get_channel.return_value = channel
    disp = _AD(bot=bot)
    await disp.dispatch(_MDd(action="SPEAK", channel_id="123", message="salut"))
    bot.memory.append_prelude.assert_called_once_with("123", "Cindy", "salut")
    bot.memory.append_message.assert_called_once_with("123", "Cindy", "salut", platform="discord")


@pytest.mark.asyncio
async def test_react_publishes_distinct_type():
    """react doit publier un event REACT (pas ACT) avec les champs emoji+channel."""
    feed = MagicMock()
    bot = MagicMock()
    channel = MagicMock()
    bot.get_channel.return_value = channel
    message = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    message.reactions = []
    message.add_reaction = AsyncMock()
    dispatcher = _AD(bot=bot, feed=feed)
    await dispatcher.dispatch(_MDd(
        action="ACT", act_name="react",
        act_args={"channel_id": "1", "message_id": "2", "emoji": "🔥"},
    ))
    types = [c.args[0].get("type") for c in feed.publish.call_args_list if c.args]
    assert "REACT" in types
    react_events = [c.args[0] for c in feed.publish.call_args_list if c.args and c.args[0].get("type") == "REACT"]
    assert len(react_events) == 1
    assert react_events[0]["emoji"] == "🔥"
    assert react_events[0]["channel"] == "1"


@pytest.mark.asyncio
async def test_react_skips_if_already_reacted():
    """Idempotence REACT : si Wally a DÉJÀ une réaction sur ce message, il ne
    réagit pas une 2e fois (fin des 7 réactions en boucle sur un msg figé)."""
    feed = MagicMock()
    bot = MagicMock()
    channel = MagicMock()
    bot.get_channel.return_value = channel
    message = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    # Une réaction déjà posée par le bot lui-même (Discord: reaction.me == True).
    own_reaction = MagicMock()
    own_reaction.me = True
    message.reactions = [own_reaction]
    message.add_reaction = AsyncMock()
    dispatcher = _AD(bot=bot, feed=feed)
    await dispatcher.dispatch(_MDd(
        action="ACT", act_name="react",
        act_args={"channel_id": "1", "message_id": "2", "emoji": "🤣"},
    ))
    message.add_reaction.assert_not_called()
    react_events = [c.args[0] for c in feed.publish.call_args_list if c.args and c.args[0].get("type") == "REACT"]
    assert react_events == []


@pytest.mark.asyncio
async def test_react_adds_when_others_reacted_but_not_bot():
    """Réactions d'AUTRES membres seulement (reaction.me == False) → Wally réagit."""
    bot = MagicMock()
    channel = MagicMock()
    bot.get_channel.return_value = channel
    message = MagicMock()
    channel.fetch_message = AsyncMock(return_value=message)
    other_reaction = MagicMock()
    other_reaction.me = False
    message.reactions = [other_reaction]
    message.add_reaction = AsyncMock()
    dispatcher = _AD(bot=bot)
    await dispatcher.dispatch(_MDd(
        action="ACT", act_name="react",
        act_args={"channel_id": "1", "message_id": "2", "emoji": "🔥"},
    ))
    message.add_reaction.assert_awaited_once_with("🔥")
