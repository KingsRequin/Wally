import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio


@pytest_asyncio.fixture
async def tmp_fact_store(tmp_path):
    from bot.v2.db.schema_v2 import create_v2_tables
    from bot.v2.core.memory.facts import SQLiteFactStore
    db_path = str(tmp_path / "test.db")
    await create_v2_tables(db_path)
    return SQLiteFactStore(db_path)


@pytest.mark.asyncio
async def test_act_create_memory(tmp_fact_store):
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.memory.facts import FactCategory
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    from bot.v2.core.meta_agent import MetaDecision
    decision = MetaDecision(action="ACT", act_name="create_memory", act_args={"fact_content": "test memory content"})
    await dispatcher.dispatch(decision)
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.THOUGHT])
    assert len(facts) == 1
    assert facts[0].content == "test memory content"
    assert facts[0].category == FactCategory.THOUGHT
    assert facts[0].confidence == 1.0


@pytest.mark.asyncio
async def test_act_create_goal(tmp_fact_store):
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.memory.facts import FactCategory
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    from bot.v2.core.meta_agent import MetaDecision
    decision = MetaDecision(action="ACT", act_name="create_goal", act_args={"description": "learn new skills"})
    await dispatcher.dispatch(decision)
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.GOAL])
    assert len(facts) == 1
    assert facts[0].content == "learn new skills"
    assert facts[0].category == FactCategory.GOAL
    assert facts[0].decay_rate == 0.005


@pytest.mark.asyncio
async def test_act_create_desire(tmp_fact_store):
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.memory.facts import FactCategory
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    from bot.v2.core.meta_agent import MetaDecision
    decision = MetaDecision(action="ACT", act_name="create_desire", act_args={"content": "explore music"})
    await dispatcher.dispatch(decision)
    facts = await tmp_fact_store.get_by_user("wally:self", categories=[FactCategory.DESIRE])
    assert len(facts) == 1
    assert facts[0].content == "explore music"
    assert facts[0].confidence == 0.8


@pytest.mark.asyncio
async def test_act_code_fix_is_noop(tmp_fact_store):
    """code_fix MUST log a warning and do nothing — security constraint."""
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.memory.facts import FactCategory
    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    from bot.v2.core.meta_agent import MetaDecision
    decision = MetaDecision(action="ACT", act_name="code_fix", act_args={"path": "/etc/passwd", "code": "rm -rf /"})
    with patch("bot.v2.core.action_dispatcher.logger") as mock_logger:
        await dispatcher.dispatch(decision)
        mock_logger.warning.assert_called_once()
    # No facts must have been created
    facts = await tmp_fact_store.get_by_user("wally:self")
    assert len(facts) == 0


@pytest.mark.asyncio
async def test_dispatch_evolve_delegates_to_persona_manager():
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision
    persona = MagicMock()
    persona.evolve = AsyncMock()
    dispatcher = ActionDispatcher(persona_manager=persona)
    decision = MetaDecision(action="EVOLVE", section="EMOTIONS", change="be more curious")
    await dispatcher.dispatch(decision)
    persona.evolve.assert_called_once_with("EMOTIONS", "be more curious")


import pytest as _pytest_fd
from unittest.mock import AsyncMock as _AMd, MagicMock as _MMd
from bot.v2.core.action_dispatcher import ActionDispatcher as _AD
from bot.v2.core.meta_agent import MetaDecision as _MDd


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


@pytest.mark.asyncio
async def test_act_advance_goal_appends_progress(tmp_fact_store):
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.memory.facts import AtomicFact, FactCategory
    from bot.v2.core.meta_agent import MetaDecision

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
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.memory.facts import AtomicFact, FactCategory
    from bot.v2.core.meta_agent import MetaDecision

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
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

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
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.memory.facts import AtomicFact, FactCategory, FactStatus
    from bot.v2.core.meta_agent import MetaDecision

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
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="fulfill_goal", act_args={},
    ))


# ── Phase 2b : react (réaction emoji) ──

@pytest.mark.asyncio
async def test_act_react_adds_reaction():
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

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
    assert "ACT" in types


@pytest.mark.asyncio
async def test_act_react_channel_not_found_no_crash():
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

    bot = MagicMock()
    bot.get_channel.return_value = None
    dispatcher = ActionDispatcher(bot=bot)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="react",
        act_args={"channel_id": "123", "message_id": "42", "emoji": "🔥"},
    ))


@pytest.mark.asyncio
async def test_act_react_message_not_found_no_crash():
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

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
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

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
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.memory.facts import FactCategory
    from bot.v2.core.meta_agent import MetaDecision

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
async def test_act_note_to_self_empty_noop(tmp_fact_store):
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

    dispatcher = ActionDispatcher(fact_store=tmp_fact_store)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self", act_args={"note": "  ", "kind": "mood"},
    ))
    facts = await tmp_fact_store.get_by_user("wally:self")
    assert facts == []
