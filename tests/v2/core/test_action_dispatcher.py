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
