import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.v2.core.cognitive_loop import CognitiveLoop, TICK_ACTIVE, TICK_MODERATE, TICK_IDLE


def _make_loop():
    attention = MagicMock()
    monologue = MagicMock()
    meta = MagicMock()
    dispatcher = MagicMock()

    from bot.v2.core.attention_agent import AttentionContext
    attention.build_context = AsyncMock(return_value=AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
    ))
    from bot.v2.core.inner_monologue import MonologueResult
    monologue.generate = AsyncMock(return_value=MonologueResult(text="pensée", thought_fact_id=1))

    from bot.v2.core.meta_agent import MetaDecision
    meta.decide = AsyncMock(return_value=[MetaDecision(action="THINK")])
    dispatcher.dispatch = AsyncMock()

    return CognitiveLoop(attention, monologue, meta, dispatcher), attention, monologue, meta, dispatcher


def test_notify_activity_updates_ts():
    loop, *_ = _make_loop()
    assert loop._last_activity_ts == 0.0
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    assert loop._last_activity_ts > 0


def test_tick_interval_active():
    import time
    loop, *_ = _make_loop()
    loop._last_activity_ts = time.time()
    assert loop._tick_interval() == TICK_ACTIVE


def test_tick_interval_idle():
    loop, *_ = _make_loop()
    loop._last_activity_ts = 0.0  # epoch = très ancien
    assert loop._tick_interval() == TICK_IDLE


@pytest.mark.asyncio
async def test_tick_calls_full_pipeline():
    loop, attention, monologue, meta, dispatcher = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    attention.build_context.assert_called_once()
    monologue.generate.assert_called_once()
    meta.decide.assert_called_once()
    dispatcher.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_tick_skips_when_no_new_activity():
    """Sans nouvelle activité depuis le dernier tick, on ne re-génère rien
    (anti-rumination : pas de pensée répétée sur un contexte identique)."""
    loop, attention, monologue, meta, dispatcher = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()              # 1er tick : traite l'activité
    await loop._tick()              # 2e tick : aucune activité nouvelle → skip
    attention.build_context.assert_called_once()
    monologue.generate.assert_called_once()


@pytest.mark.asyncio
async def test_stop_cancels_task():
    loop, *_ = _make_loop()
    loop._running = True
    loop._task = asyncio.create_task(asyncio.sleep(9999))
    await loop.stop()
    assert loop._task.cancelled() or loop._task.done()


import pytest as _pytest_feed
from unittest.mock import AsyncMock as _AM, MagicMock as _MM
from bot.v2.core.attention_agent import AttentionContext as _ACtx
from bot.v2.core.inner_monologue import MonologueResult as _MR
from bot.v2.core.meta_agent import MetaDecision as _MD


def _ctx_feed():
    return _ACtx(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="matin",
    )


@_pytest_feed.mark.asyncio
async def test_tick_publishes_think_and_decide_to_feed():
    feed = _MM()
    attention, monologue, meta, dispatcher = _MM(), _MM(), _MM(), _MM()
    attention.build_context = _AM(return_value=_ctx_feed())
    monologue.generate = _AM(return_value=_MR(text="je réfléchis", thought_fact_id=1))
    meta.decide = _AM(return_value=[_MD(action="THINK")])
    dispatcher.dispatch = _AM()
    loop = CognitiveLoop(attention, monologue, meta, dispatcher, None, feed)
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    published = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "THINK" in published and "DECIDE" in published
    think = next(c.args[0] for c in feed.publish.call_args_list if c.args[0]["type"] == "THINK")
    assert think["text"] == "je réfléchis"


@_pytest_feed.mark.asyncio
async def test_tick_without_feed_does_not_crash():
    attention, monologue, meta, dispatcher = _MM(), _MM(), _MM(), _MM()
    attention.build_context = _AM(return_value=_ctx_feed())
    monologue.generate = _AM(return_value=_MR(text="x", thought_fact_id=1))
    meta.decide = _AM(return_value=[_MD(action="THINK")])
    dispatcher.dispatch = _AM()
    loop = CognitiveLoop(attention, monologue, meta, dispatcher)
    await loop._tick()
