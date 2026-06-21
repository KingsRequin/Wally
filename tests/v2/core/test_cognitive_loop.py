import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.v2.core.cognitive_loop import CognitiveLoop, TICK_ACTIVE, TICK_MODERATE, TICK_IDLE


def _make_loop():
    attention = MagicMock()
    reasoning = MagicMock()
    dispatcher = MagicMock()

    from bot.v2.core.attention_agent import AttentionContext
    attention.build_context = AsyncMock(return_value=AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
    ))
    from bot.v2.core.reasoning_agent import ReasoningResult
    from bot.v2.core.meta_agent import MetaDecision
    reasoning.reason = AsyncMock(return_value=ReasoningResult(
        thought_text="pensée", thought_fact_id=1, decisions=[MetaDecision(action="THINK")]
    ))
    dispatcher.dispatch = AsyncMock()

    return CognitiveLoop(attention, reasoning, dispatcher), attention, reasoning, dispatcher


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
    loop, attention, reasoning, dispatcher = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    attention.build_context.assert_called_once()
    reasoning.reason.assert_called_once()
    dispatcher.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_tick_skips_when_no_new_activity():
    """Sans nouvelle activité depuis le dernier tick, on ne re-génère rien
    (anti-rumination : pas de pensée répétée sur un contexte identique)."""
    loop, attention, reasoning, dispatcher = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()              # 1er tick : traite l'activité
    await loop._tick()              # 2e tick : aucune activité nouvelle → skip
    attention.build_context.assert_called_once()
    reasoning.reason.assert_called_once()


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
from bot.v2.core.reasoning_agent import ReasoningResult as _RR
from bot.v2.core.meta_agent import MetaDecision as _MD


def _ctx_feed():
    return _ACtx(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="matin",
    )


@_pytest_feed.mark.asyncio
async def test_tick_publishes_think_and_decide_to_feed():
    feed = _MM()
    attention, reasoning, dispatcher = _MM(), _MM(), _MM()
    attention.build_context = _AM(return_value=_ctx_feed())
    reasoning.reason = _AM(return_value=_RR(
        thought_text="je réfléchis", thought_fact_id=1, decisions=[_MD(action="THINK")]
    ))
    dispatcher.dispatch = _AM()
    loop = CognitiveLoop(attention, reasoning, dispatcher, None, feed)
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    published = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "THINK" in published and "DECIDE" in published
    think = next(c.args[0] for c in feed.publish.call_args_list if c.args[0]["type"] == "THINK")
    assert think["text"] == "je réfléchis"


@_pytest_feed.mark.asyncio
async def test_tick_without_feed_does_not_crash():
    attention, reasoning, dispatcher = _MM(), _MM(), _MM()
    attention.build_context = _AM(return_value=_ctx_feed())
    reasoning.reason = _AM(return_value=_RR(
        thought_text="x", thought_fact_id=1, decisions=[_MD(action="THINK")]
    ))
    dispatcher.dispatch = _AM()
    loop = CognitiveLoop(attention, reasoning, dispatcher)
    await loop._tick()


# ── Conscience sociale : auto-régulation des messages spontanés ──

@pytest.mark.asyncio
async def test_speak_records_unanswered():
    """Un SPEAK dispatché incrémente le compteur 'sans réponse' du canal."""
    loop, attention, reasoning, dispatcher = _make_loop()
    reasoning.reason = AsyncMock(return_value=_RR(
        thought_text="yo", thought_fact_id=1,
        decisions=[_MD(action="SPEAK", channel_id="55", message="yo")],
    ))
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    assert loop._spontaneous["55"]["unanswered"] == 1


def test_user_reply_resets_unanswered():
    """Quand l'user parle dans le canal, le compteur 'sans réponse' retombe à 0."""
    loop, *_ = _make_loop()
    loop._spontaneous["55"] = {"last_ts": 1.0, "unanswered": 3}
    loop.notify_activity(channel_id=55, author="Bob", content="ah oui ?")
    assert loop._spontaneous["55"]["unanswered"] == 0


@pytest.mark.asyncio
async def test_unanswered_passed_to_context():
    """Les messages sans réponse sont transmis à build_context pour le reasoning."""
    import time
    loop, attention, reasoning, dispatcher = _make_loop()
    loop._spontaneous["55"] = {"last_ts": time.monotonic() - 120, "unanswered": 2}
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    spont = attention.build_context.call_args.kwargs["spontaneous"]
    assert spont and spont[0]["channel"] == "55" and spont[0]["unanswered"] == 2
