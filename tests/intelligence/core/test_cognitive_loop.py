import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.cognitive_loop import CognitiveLoop, TICK_ACTIVE, TICK_MODERATE, TICK_IDLE


def _make_loop():
    attention = MagicMock()
    reasoning = MagicMock()
    dispatcher = MagicMock()

    from bot.intelligence.attention_agent import AttentionContext
    attention.build_context = AsyncMock(return_value=AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
    ))
    from bot.intelligence.reasoning_agent import ReasoningResult
    from bot.intelligence.meta_agent import MetaDecision
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


def test_notify_activity_stores_message_id():
    loop, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello", message_id="42")
    assert loop._recent_interactions[-1]["message_id"] == "42"


def test_notify_activity_message_id_optional():
    """message_id absent → stocké à None (rétro-compat)."""
    loop, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    assert loop._recent_interactions[-1]["message_id"] is None


def test_tick_interval_active():
    import time
    loop, *_ = _make_loop()
    loop._last_activity_ts = time.time()
    assert loop._tick_interval() == TICK_ACTIVE


def test_tick_interval_idle():
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    loop, *_ = _make_loop()
    loop._last_activity_ts = 0.0  # epoch = très ancien
    # Idle = intervalle aléatoire 5 min – 1 h (effet naturel). On vérifie la plage
    # sur plusieurs tirages.
    for _ in range(20):
        v = loop._tick_interval()
        assert TICK_IDLE <= v <= TICK_IDLE_MAX


def test_tick_interval_idle_high_boredom_near_floor():
    """Ennui élevé (0.9) → plafond ramené quasi au plancher : tous les tirages
    restent proches de TICK_IDLE (5 min)."""
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    loop, *_ = _make_loop()
    emotion = MagicMock()
    emotion.get_state = MagicMock(return_value={"boredom": 0.9})
    loop._emotion = emotion
    loop._last_activity_ts = 0.0  # idle
    # hi = 300 + 3300 * (1 - 0.9) = 630 → tirages dans [300, 630].
    for _ in range(40):
        v = loop._tick_interval()
        assert TICK_IDLE <= v <= 630
        assert v < TICK_IDLE_MAX


def test_tick_interval_idle_low_boredom_can_reach_ceiling():
    """Ennui faible → la plage va jusqu'au plafond (1 h) : sur de nombreux
    tirages, au moins un dépasse largement le plancher."""
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    loop, *_ = _make_loop()
    emotion = MagicMock()
    emotion.get_state = MagicMock(return_value={"boredom": 0.0})
    loop._emotion = emotion
    loop._last_activity_ts = 0.0  # idle
    seen_high = False
    for _ in range(200):
        v = loop._tick_interval()
        assert TICK_IDLE <= v <= TICK_IDLE_MAX
        if v > 2000:
            seen_high = True
    assert seen_high  # le plafond est réellement atteignable


def test_tick_interval_idle_no_emotion_full_range():
    """Sans EmotionEngine (boredom=0) → plage complète préservée."""
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    loop, *_ = _make_loop()  # emotion_engine None
    assert loop._emotion is None
    loop._last_activity_ts = 0.0
    for _ in range(20):
        v = loop._tick_interval()
        assert TICK_IDLE <= v <= TICK_IDLE_MAX


@pytest.mark.asyncio
async def test_tick_calls_full_pipeline():
    loop, attention, reasoning, dispatcher = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    attention.build_context.assert_called_once()
    reasoning.reason.assert_called_once()
    dispatcher.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_tick_with_new_activity_is_not_idle():
    """Un tick déclenché par une nouvelle activité pense la conversation
    (idle=False)."""
    loop, attention, reasoning, dispatcher = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    assert attention.build_context.call_args.kwargs["idle"] is False


@pytest.mark.asyncio
async def test_tick_idle_still_thinks():
    """Sans nouvelle activité, le loop NE no-op PLUS : il pense en idle
    (build_context reçoit idle=True, reason est appelé)."""
    loop, attention, reasoning, dispatcher = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()              # 1er tick : conversation (idle=False)
    await loop._tick()              # 2e tick : aucune activité nouvelle → idle
    assert attention.build_context.call_count == 2
    assert reasoning.reason.call_count == 2
    # Le 2e appel doit être idle.
    assert attention.build_context.call_args.kwargs["idle"] is True


@pytest.mark.asyncio
async def test_stop_cancels_task():
    loop, *_ = _make_loop()
    loop._running = True
    loop._task = asyncio.create_task(asyncio.sleep(9999))
    await loop.stop()
    assert loop._task.cancelled() or loop._task.done()


import pytest as _pytest_feed
from unittest.mock import AsyncMock as _AM, MagicMock as _MM
from bot.intelligence.attention_agent import AttentionContext as _ACtx
from bot.intelligence.reasoning_agent import ReasoningResult as _RR
from bot.intelligence.meta_agent import MetaDecision as _MD


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
    """Un SPEAK dispatché incrémente le compteur 'sans réponse' du canal.

    Le canal SPEAK ("55") correspond à une interaction récente connue, donc il
    n'est pas redirigé."""
    loop, attention, reasoning, dispatcher = _make_loop()
    reasoning.reason = AsyncMock(return_value=_RR(
        thought_text="yo", thought_fact_id=1,
        decisions=[_MD(action="SPEAK", channel_id="55", message="yo")],
    ))
    loop.notify_activity(channel_id=55, author="Alice", content="hello")
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


# ── Bug 1 : anti-rumination (pensées répétées en mode actif) ──

def test_too_similar_identical():
    from bot.intelligence.cognitive_loop import _too_similar
    assert _too_similar("Je m'ennuie ici", "Je m'ennuie ici") is True
    # normalisation : casse / espaces
    assert _too_similar("Je  m'ennuie ICI ", "je m'ennuie ici") is True


def test_too_similar_near_duplicate():
    from bot.intelligence.cognitive_loop import _too_similar
    a = "Je me demande ce que fait Azrael en ce moment, ça fait un moment."
    b = "Je me demande ce que fait Azrael en ce moment, ça fait un moment !"
    assert _too_similar(a, b) is True


def test_too_similar_different():
    from bot.intelligence.cognitive_loop import _too_similar
    a = "Je me demande ce que fait Azrael en ce moment."
    b = "Tiens, Bob parle de jazz, ça me rappelle un vieux souvenir."
    assert _too_similar(a, b) is False


def test_too_similar_empty():
    from bot.intelligence.cognitive_loop import _too_similar
    assert _too_similar("", "quelque chose") is False
    assert _too_similar("quelque chose", "") is False


@pytest.mark.asyncio
async def test_tick_rests_on_duplicate_thought():
    """Deux ticks renvoyant la MÊME thought_text → le 2e se repose : pas de
    dispatch, pas de feed THINK republié."""
    feed = _MM()
    attention, reasoning, dispatcher = _MM(), _MM(), _MM()
    attention.build_context = _AM(return_value=_ctx_feed())
    reasoning.reason = _AM(return_value=_RR(
        thought_text="exactement la même pensée", thought_fact_id=1,
        decisions=[_MD(action="THINK")],
    ))
    dispatcher.dispatch = _AM()
    loop = CognitiveLoop(attention, reasoning, dispatcher, None, feed)
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()   # 1er tick : pensée neuve → dispatch
    await loop._tick()   # 2e tick : pensée identique → repos
    assert dispatcher.dispatch.call_count == 1
    think_count = sum(
        1 for c in feed.publish.call_args_list if c.args[0]["type"] == "THINK"
    )
    assert think_count == 1


@pytest.mark.asyncio
async def test_tick_continues_on_distinct_thought():
    """Deux ticks avec des pensées distinctes → les deux dispatchent."""
    attention, reasoning, dispatcher = _MM(), _MM(), _MM()
    attention.build_context = _AM(return_value=_ctx_feed())
    reasoning.reason = _AM(side_effect=[
        _RR(thought_text="première pensée", thought_fact_id=1, decisions=[_MD(action="THINK")]),
        _RR(thought_text="seconde pensée totalement différente", thought_fact_id=2, decisions=[_MD(action="THINK")]),
    ])
    dispatcher.dispatch = _AM()
    loop = CognitiveLoop(attention, reasoning, dispatcher)
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    await loop._tick()
    assert dispatcher.dispatch.call_count == 2


# ── Bug 2 : routage SPEAK vers un vrai canal ──

@pytest.mark.asyncio
async def test_speak_unknown_channel_redirected_to_last_active():
    """SPEAK avec channel halluciné inconnu + une interaction récente sur '55'
    → la décision dispatchée vise '55'."""
    loop, attention, reasoning, dispatcher = _make_loop()
    reasoning.reason = AsyncMock(return_value=_RR(
        thought_text="je veux dire un truc", thought_fact_id=1,
        decisions=[_MD(action="SPEAK", channel_id="999999", message="yo")],
    ))
    loop.notify_activity(channel_id=55, author="Alice", content="hello")
    await loop._tick()
    dispatcher.dispatch.assert_called_once()
    dispatched = dispatcher.dispatch.call_args.args[0]
    assert dispatched.channel_id == "55"


@pytest.mark.asyncio
async def test_speak_directory_channel_not_redirected():
    """SPEAK vers un canal de l'annuaire (speakable_channels) SANS interaction
    récente → choix proactif valide : dispatché tel quel, pas de redirection."""
    attention, reasoning, dispatcher = _MM(), _MM(), _MM()
    attention.build_context = _AM(return_value=_ctx_feed())
    reasoning.reason = _AM(return_value=_RR(
        thought_text="j'ai un meme à poster", thought_fact_id=1,
        decisions=[_MD(action="SPEAK", channel_id="875450811151450143", message="lol")],
    ))
    dispatcher.dispatch = _AM()
    loop = CognitiveLoop(
        attention, reasoning, dispatcher,
        speakable_channels={"875450811151450143", "875421532351000627"},
    )
    # aucune notify_activity → _recent_interactions vide, mais le canal est
    # dans l'annuaire.
    await loop._tick()
    dispatcher.dispatch.assert_called_once()
    dispatched = dispatcher.dispatch.call_args.args[0]
    assert dispatched.channel_id == "875450811151450143"


@pytest.mark.asyncio
async def test_speak_no_active_channel_dropped():
    """SPEAK avec channel inconnu + AUCUNE interaction → décision abandonnée,
    dispatch jamais appelé."""
    loop, attention, reasoning, dispatcher = _make_loop()
    reasoning.reason = AsyncMock(return_value=_RR(
        thought_text="je veux dire un truc dans le vide", thought_fact_id=1,
        decisions=[_MD(action="SPEAK", channel_id="999999", message="yo")],
    ))
    # aucune notify_activity → _recent_interactions vide
    await loop._tick()
    dispatcher.dispatch.assert_not_called()
