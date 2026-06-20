import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from wally_v2.core.cognitive_loop import CognitiveLoop, TICK_ACTIVE, TICK_MODERATE, TICK_IDLE


def _make_loop():
    attention = MagicMock()
    monologue = MagicMock()
    meta = MagicMock()
    dispatcher = MagicMock()

    from wally_v2.core.attention_agent import AttentionContext
    attention.build_context = AsyncMock(return_value=AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
    ))
    from wally_v2.core.inner_monologue import MonologueResult
    monologue.generate = AsyncMock(return_value=MonologueResult(text="pensée", thought_fact_id=1))

    from wally_v2.core.meta_agent import MetaDecision
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
    await loop._tick()
    attention.build_context.assert_called_once()
    monologue.generate.assert_called_once()
    meta.decide.assert_called_once()
    dispatcher.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_stop_cancels_task():
    loop, *_ = _make_loop()
    loop._running = True
    loop._task = asyncio.create_task(asyncio.sleep(9999))
    await loop.stop()
    assert loop._task.cancelled() or loop._task.done()
