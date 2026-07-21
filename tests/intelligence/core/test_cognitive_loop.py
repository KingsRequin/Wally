import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.cognitive_loop import CognitiveLoop, TICK_ACTIVE, TICK_MODERATE, TICK_IDLE


def _make_loop(verdict="PROGRESSE"):
    attention = MagicMock()
    reasoning = MagicMock()
    dispatcher = MagicMock()

    from bot.intelligence.attention_agent import AttentionContext
    attention.build_context = AsyncMock(return_value=AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
        preoccupation="ma préoccupation",
    ))
    from bot.intelligence.reasoning_agent import ReasoningResult
    from bot.intelligence.meta_agent import MetaDecision
    reasoning.reason = AsyncMock(return_value=ReasoningResult(
        thought_text="pensée", thought_fact_id=7, decisions=[MetaDecision(action="THINK")]
    ))
    dispatcher.dispatch = AsyncMock()

    facts = MagicMock()
    facts.set_status = AsyncMock()
    focus_fact = MagicMock()
    focus_fact.id = 99
    facts.get_latest_by_source = AsyncMock(return_value=focus_fact)
    facts.get_due_facts = AsyncMock(return_value=[])
    facts.clear_schedule = AsyncMock()

    judge = MagicMock()
    judge.judge = AsyncMock(return_value=verdict)

    feed = MagicMock()
    feed.publish = MagicMock()

    loop = CognitiveLoop(
        attention, reasoning, dispatcher, feed=feed,
        fact_store=facts, progress_judge=judge,
        # Le routage/gardes SPEAK ne se testent que si la parole spontanée est
        # autorisée ; sa coupure par défaut est couverte par
        # test_cognitive_loop_speak_gate.py.
        spontaneous_channel_speak_enabled=True,
    )
    return loop, attention, reasoning, dispatcher, facts, judge, feed


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


def test_notify_activity_stores_user_key():
    """user_key ("platform:raw_id") est conservé pour l'enrichissement mémoire (#A1)."""
    loop, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hi", user_key="discord:111")
    assert loop._recent_interactions[-1]["user_key"] == "discord:111"


def test_notify_activity_user_key_optional():
    """user_key absent → stocké à None (rétro-compat)."""
    loop, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hi")
    assert loop._recent_interactions[-1]["user_key"] is None


# ── #A6 : boucle feedback émotion→action→résultat ──

def test_response_to_spontaneous_rewards_joy():
    """Quelqu'un répond à un message spontané de Wally → bouffée de joie (#A6)."""
    from bot.intelligence.cognitive_loop import SOCIAL_FEEDBACK_JOY
    loop, *_ = _make_loop()
    loop._emotion = MagicMock()
    loop._spontaneous["1"] = {"last_ts": 0.0, "unanswered": 2}
    loop.notify_activity(channel_id=1, author="Alice", content="oui pourquoi ?")
    loop._emotion.apply_delta.assert_called_once_with("joy", SOCIAL_FEEDBACK_JOY)
    # le compteur sans réponse est remis à zéro
    assert loop._spontaneous["1"]["unanswered"] == 0


def test_no_joy_when_not_a_response():
    """Un message hors sollicitation spontanée ne déclenche aucune émotion."""
    loop, *_ = _make_loop()
    loop._emotion = MagicMock()
    loop.notify_activity(channel_id=1, author="Alice", content="coucou")
    loop._emotion.apply_delta.assert_not_called()


def test_response_resets_ignored_penalty_flag():
    """Une réponse rouvre un nouvel épisode : la pénalité d'abandon peut se reposer."""
    loop, *_ = _make_loop()
    loop._emotion = MagicMock()
    loop._spontaneous["1"] = {"last_ts": 0.0, "unanswered": 3, "penalized": True}
    loop.notify_activity(channel_id=1, author="Alice", content="présent")
    assert loop._spontaneous["1"]["penalized"] is False


def test_ignored_penalizes_anger_once():
    """Être ignoré (≥3 sans réponse) pique la colère — une seule fois par épisode (#A6)."""
    from bot.intelligence.cognitive_loop import SOCIAL_IGNORED_ANGER
    loop, *_ = _make_loop()
    loop._emotion = MagicMock()
    st = {"last_ts": 0.0, "unanswered": 3}
    loop._penalize_if_ignored(st)
    loop._penalize_if_ignored(st)  # second appel : pas de double pénalité
    loop._emotion.apply_delta.assert_called_once_with("anger", SOCIAL_IGNORED_ANGER)
    assert st["penalized"] is True


def test_penalize_if_ignored_safe_without_emotion():
    """Sans moteur émotionnel injecté, la pénalité ne lève pas."""
    loop, *_ = _make_loop()
    loop._emotion = None
    loop._penalize_if_ignored({"unanswered": 3})  # ne doit pas lever


def test_notify_event_records_in_interactions():
    """Un événement hors-message (réaction, arrivée) entre dans le flux perçu (#A2)."""
    loop, *_ = _make_loop()
    loop.notify_event(channel_id=5, description="Azrael vient de rejoindre le serveur")
    last = loop._recent_interactions[-1]
    assert last["channel"] == "5"
    assert last["content"] == "Azrael vient de rejoindre le serveur"
    assert last["is_event"] is True


def test_notify_event_updates_activity_ts():
    """Un événement réveille le cerveau (activité fraîche → tick non no-op)."""
    loop, *_ = _make_loop()
    assert loop._last_activity_ts == 0.0
    loop.notify_event(channel_id=5, description="quelqu'un a réagi 👍")
    assert loop._last_activity_ts > 0


def test_notify_event_relevant_sets_relevant_ts():
    """Un événement qui vise Wally (réaction sur SON message) → cadence vive."""
    loop, *_ = _make_loop()
    assert loop._last_relevant_activity_ts == float("-inf")
    loop.notify_event(channel_id=5, description="Kaelis a réagi ❤️ à ton message", relevant=True)
    assert loop._last_relevant_activity_ts > 0


def test_notify_event_passive_keeps_relevant_ts_idle():
    """Un événement passif (arrivée serveur) ne force pas la cadence vive."""
    loop, *_ = _make_loop()
    loop.notify_event(channel_id=5, description="Azrael vient de rejoindre le serveur")
    assert loop._last_relevant_activity_ts == float("-inf")


def test_notify_event_has_no_user_key():
    """Un événement n'a pas de user_key → ignoré par l'enrichissement participant (#A1)."""
    loop, *_ = _make_loop()
    loop.notify_event(channel_id=5, description="x a réagi 👍")
    assert loop._recent_interactions[-1].get("user_key") is None


# ── notify_typing : indicateurs de frappe (conversation vivante) ────────────

def test_notify_typing_records_passive_perception():
    """Une frappe entre dans le flux perçu comme événement passif."""
    loop, *_ = _make_loop()
    loop.notify_typing(channel_id=5, author="Alice (@alice)")
    last = loop._recent_interactions[-1]
    assert last["channel"] == "5"
    assert "Alice (@alice)" in last["content"]
    assert "écrire" in last["content"]
    assert last["is_event"] is True


def test_notify_typing_updates_activity_ts():
    """Une frappe réveille l'activité → le canal est perçu vivant (tick non idle)."""
    loop, *_ = _make_loop()
    assert loop._last_activity_ts == 0.0
    loop.notify_typing(channel_id=5, author="Alice")
    assert loop._last_activity_ts > 0


def test_notify_typing_is_passive_never_wakes_active_cadence():
    """La frappe ne VISE pas Wally → ne réveille jamais la cadence vive (Phase 2c)."""
    loop, *_ = _make_loop()
    loop.notify_typing(channel_id=5, author="Alice")
    assert loop._last_relevant_activity_ts == float("-inf")


def test_notify_typing_throttled_per_channel_author():
    """Discord réémet la frappe ~toutes les 10 s : on n'en perçoit qu'un épisode."""
    loop, *_ = _make_loop()
    loop.notify_typing(channel_id=5, author="Alice")
    loop.notify_typing(channel_id=5, author="Alice")
    loop.notify_typing(channel_id=5, author="Alice")
    typing_lines = [i for i in loop._recent_interactions if i.get("is_event")]
    assert len(typing_lines) == 1


def test_notify_typing_distinct_authors_not_throttled_together():
    """L'étranglement est par (canal, auteur) : deux personnes = deux perceptions."""
    loop, *_ = _make_loop()
    loop.notify_typing(channel_id=5, author="Alice")
    loop.notify_typing(channel_id=5, author="Bob")
    typing_lines = [i for i in loop._recent_interactions if i.get("is_event")]
    assert len(typing_lines) == 2


def test_notify_typing_throttle_expires():
    """Passé TYPING_THROTTLE, une nouvelle frappe est de nouveau perçue."""
    from bot.intelligence.cognitive_loop import TYPING_THROTTLE
    loop, *_ = _make_loop()
    loop.notify_typing(channel_id=5, author="Alice")
    # On recule le dernier marquage au-delà de la fenêtre d'étranglement.
    loop._typing_seen[("5", "Alice")] -= TYPING_THROTTLE + 1
    loop.notify_typing(channel_id=5, author="Alice")
    typing_lines = [i for i in loop._recent_interactions if i.get("is_event")]
    assert len(typing_lines) == 2


def test_notify_reply_records_wally_response_in_interactions():
    """La réponse réactive de Wally entre dans _recent_interactions → le flux
    cognitif voit la conversation complète et ne re-répond pas (anti-doublon)."""
    loop, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="tu streams quand ?")
    loop.notify_reply(1, content="Jamais, j'ai pas de corps.", author="Wally")
    last = loop._recent_interactions[-1]
    assert last["author"] == "Wally"
    assert "pas de corps" in last["content"]
    assert last["is_self"] is True
    assert loop._last_reply["1"] > 0  # anti-récap court terme toujours posé


def test_notify_reply_without_content_keeps_old_behavior():
    """Sans contenu, notify_reply ne pose que l'anti-récap (pas d'interaction)."""
    loop, *_ = _make_loop()
    before = len(loop._recent_interactions)
    loop.notify_reply(1)
    assert len(loop._recent_interactions) == before
    assert loop._last_reply["1"] > 0


def test_tick_interval_active():
    import time
    loop, *_ = _make_loop()
    # La cadence vive suit l'activité PERTINENTE (mention/DM/réponse), pas la
    # perception passive (Phase 2c).
    loop._last_relevant_activity_ts = time.monotonic()
    assert loop._tick_interval() == TICK_ACTIVE


def test_tick_interval_idle_at_boot_regardless_of_uptime():
    """Non-régression bug#1 (reboot hôte) : à l'instantiation, sans monkeypatch de
    time.monotonic, la cadence doit être idle quel que soit l'uptime réel de la
    machine. `time.monotonic()` compte depuis le boot machine, pas depuis le
    démarrage du process : un sentinel `0.0` sur `_last_relevant_activity_ts`
    ferait lire `elapsed = uptime` et déclencherait à tort TICK_ACTIVE/MODERATE
    pendant la première heure suivant chaque reboot de l'hôte."""
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    loop, *_ = _make_loop()
    v = loop._tick_interval()
    assert TICK_IDLE <= v <= TICK_IDLE_MAX
    assert v != TICK_ACTIVE
    assert v != TICK_MODERATE


def test_passive_activity_does_not_trigger_active_cadence(monkeypatch):
    """Un message de canal qui ne vise pas Wally (relevant=False) est perçu mais
    ne déclenche pas la cadence vive : le tick reste en cadence idle."""
    # `_tick_interval` mesure `time.monotonic() - _last_relevant_activity_ts` ;
    # avec le champ resté à 0.0, l'écart vaut l'uptime réel de la machine. On le
    # fige loin dans le temps pour que « idle » soit déterministe (sinon le test
    # dépend de l'uptime : cf. reboot hôte → uptime < 1h → cadence MODERATE).
    monkeypatch.setattr("time.monotonic", lambda: 1_000_000.0)
    loop, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="x", content="bla bla", relevant=False)
    # perçu (recent_interactions) mais pas de cadence active
    assert loop._recent_interactions
    assert loop._last_relevant_activity_ts == float("-inf")
    assert loop._tick_interval() >= TICK_IDLE


def test_relevant_activity_triggers_active_cadence():
    loop, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="x", content="@wally salut", relevant=True)
    assert loop._last_relevant_activity_ts > 0.0
    assert loop._tick_interval() == TICK_ACTIVE


def test_dm_is_always_relevant():
    loop, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="x", content="coucou", is_dm=True)
    assert loop._last_relevant_activity_ts > 0.0
    assert loop._tick_interval() == TICK_ACTIVE


def test_tick_interval_idle(monkeypatch):
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    # Fige monotonic loin dans le futur → écart vs _last_relevant_activity_ts (0.0)
    # > 1h → chemin idle, indépendamment de l'uptime réel de la machine.
    monkeypatch.setattr("time.monotonic", lambda: 1_000_000.0)
    loop, *_ = _make_loop()
    # Idle = intervalle aléatoire 5 min – 1 h (effet naturel). On vérifie la plage
    # sur plusieurs tirages.
    for _ in range(20):
        v = loop._tick_interval()
        assert TICK_IDLE <= v <= TICK_IDLE_MAX


def test_tick_interval_idle_high_boredom_near_floor(monkeypatch):
    """Ennui élevé (0.9) → plafond ramené quasi au plancher : tous les tirages
    restent proches de TICK_IDLE (5 min)."""
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    monkeypatch.setattr("time.monotonic", lambda: 1_000_000.0)  # force idle (cf. supra)
    loop, *_ = _make_loop()
    emotion = MagicMock()
    emotion.get_state = MagicMock(return_value={"boredom": 0.9})
    loop._emotion = emotion
    # hi = 300 + 3300 * (1 - 0.9) = 630 → tirages dans [300, 630].
    for _ in range(40):
        v = loop._tick_interval()
        assert TICK_IDLE <= v <= 630
        assert v < TICK_IDLE_MAX


def test_tick_interval_idle_low_boredom_can_reach_ceiling(monkeypatch):
    """Ennui faible → la plage va jusqu'au plafond (1 h) : sur de nombreux
    tirages, au moins un dépasse largement le plancher."""
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    monkeypatch.setattr("time.monotonic", lambda: 1_000_000.0)  # force idle (cf. supra)
    loop, *_ = _make_loop()
    emotion = MagicMock()
    emotion.get_state = MagicMock(return_value={"boredom": 0.0})
    loop._emotion = emotion
    seen_high = False
    for _ in range(200):
        v = loop._tick_interval()
        assert TICK_IDLE <= v <= TICK_IDLE_MAX
        if v > 2000:
            seen_high = True
    assert seen_high  # le plafond est réellement atteignable


def test_tick_interval_idle_no_emotion_full_range(monkeypatch):
    """Sans EmotionEngine (boredom=0) → plage complète préservée."""
    from bot.intelligence.cognitive_loop import TICK_IDLE_MAX
    monkeypatch.setattr("time.monotonic", lambda: 1_000_000.0)  # force idle (cf. supra)
    loop, *_ = _make_loop()  # emotion_engine None
    assert loop._emotion is None
    for _ in range(20):
        v = loop._tick_interval()
        assert TICK_IDLE <= v <= TICK_IDLE_MAX


@pytest.mark.asyncio
async def test_tick_calls_full_pipeline():
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    attention.build_context.assert_called_once()
    reasoning.reason.assert_called_once()
    dispatcher.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_tick_triggers_due_reminder():
    """Un rappel programmé arrivé à échéance revient à la conscience puis est
    désarmé pour ne pas se redéclencher (#A3)."""
    from types import SimpleNamespace
    loop, attention, reasoning, dispatcher, facts, *_ = _make_loop()
    facts.get_due_facts = AsyncMock(return_value=[
        SimpleNamespace(content="demander à KingsRequin s'il stream", id=5)
    ])
    await loop._tick()
    forced = attention.build_context.call_args.kwargs.get("forced_seed")
    assert forced and "KingsRequin" in forced
    facts.clear_schedule.assert_awaited_once_with(5)


@pytest.mark.asyncio
async def test_tick_no_due_reminder_no_forced_seed():
    """Sans rappel dû, aucune amorce forcée n'est injectée."""
    loop, attention, reasoning, dispatcher, facts, judge, feed = _make_loop()
    await loop._tick()
    assert attention.build_context.call_args.kwargs.get("forced_seed") is None
    facts.clear_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_tick_with_new_activity_is_not_idle():
    """Un tick déclenché par une nouvelle activité pense la conversation
    (idle=False)."""
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    assert attention.build_context.call_args.kwargs["idle"] is False


@pytest.mark.asyncio
async def test_tick_idle_still_thinks():
    """Sans nouvelle activité, le loop NE no-op PLUS : il pense en idle
    (build_context reçoit idle=True, reason est appelé)."""
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
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
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
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
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
    loop._spontaneous["55"] = {"last_ts": time.monotonic() - 120, "unanswered": 2}
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    spont = attention.build_context.call_args.kwargs["spontaneous"]
    assert spont and spont[0]["channel"] == "55" and spont[0]["unanswered"] == 2


@pytest.mark.asyncio
async def test_speak_suppressed_when_redite():
    """Anti-redite : un SPEAK quasi identique à un message spontané récent est
    supprimé (fin des 2 messages jumeaux type Bloodshade à 10h d'écart)."""
    import time
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
    obs = ("Bloodshade poste 'rien à déclarer' dans #shame pendant qu'il lance "
           "un avis de recherche sur Azraël. La coordination est impeccable.")
    loop._recent_speaks = [{"channel": "55", "content": obs, "ts": time.time()}]
    reasoning.reason = AsyncMock(return_value=_RR(
        thought_text="obs", thought_fact_id=1,
        decisions=[_MD(action="SPEAK", channel_id="55", message=obs)],
    ))
    loop.notify_activity(channel_id=55, author="Alice", content="hello")
    await loop._tick()
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_speak_dispatched_when_not_redite():
    """Un SPEAK sur un sujet neuf passe normalement (pas de faux positif)."""
    import time
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
    loop._recent_speaks = [{
        "channel": "55", "content": "un vieux sujet totalement différent",
        "ts": time.time(),
    }]
    reasoning.reason = AsyncMock(return_value=_RR(
        thought_text="obs", thought_fact_id=1,
        decisions=[_MD(action="SPEAK", channel_id="55",
                       message="quelqu'un a vu le nouveau patch Apex ?")],
    ))
    loop.notify_activity(channel_id=55, author="Alice", content="hello")
    await loop._tick()
    dispatcher.dispatch.assert_called_once()


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


@pytest.mark.asyncio
async def test_tick_rests_on_thought_matching_window_not_just_previous():
    """Anti-rumination sur fenêtre glissante : une pensée identique à l'avant-
    dernière (mais distincte de la dernière) doit quand même reposer. L'ancienne
    logique (comparaison au seul tick précédent) l'aurait laissée passer."""
    attention, reasoning, dispatcher = _MM(), _MM(), _MM()
    attention.build_context = _AM(return_value=_ctx_feed())
    reasoning.reason = _AM(side_effect=[
        _RR(thought_text="je rumine le bug emoji de KingsRequin", thought_fact_id=1, decisions=[_MD(action="THINK")]),
        _RR(thought_text="tiens il fait beau en France aujourd'hui", thought_fact_id=2, decisions=[_MD(action="THINK")]),
        _RR(thought_text="je rumine le bug emoji de KingsRequin", thought_fact_id=3, decisions=[_MD(action="THINK")]),
    ])
    dispatcher.dispatch = _AM()
    loop = CognitiveLoop(attention, reasoning, dispatcher)
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    await loop._tick()
    await loop._tick()
    await loop._tick()
    # tick3 rattrapé par la fenêtre (== tick1) → seuls les 2 premiers dispatchent.
    assert dispatcher.dispatch.call_count == 2


@pytest.mark.asyncio
async def test_focus_rumination_count_is_cumulative():
    """Anti-rumination structurelle : un focus qui ressasse en ALTERNANCE avec
    des 'progressions' (le juge se fait berner par les reformulations, cf. 11h
    sur « anti-inférence ») doit quand même mourir. Le compteur de ressassement
    est cumulatif sur la vie du fil, pas remis à zéro à chaque fausse avancée.

    Séquence R, P, R : avec l'ancien reset-sur-PROGRESSE le focus survivait
    (1→0→1) ; désormais il cumule (1→1→2) et expire au 2e ressassement."""
    from bot.intelligence.memory.facts import FactStatus
    loop, attention, reasoning, dispatcher, facts, judge, feed = _make_loop()
    judge.judge = AsyncMock(side_effect=["RESSASSE", "PROGRESSE", "RESSASSE"])
    await loop._tick()   # RESSASSE → count 1
    await loop._tick()   # PROGRESSE → count reste 1 (cumul), PAS de reset
    await loop._tick()   # RESSASSE → count 2 ≥ LIMIT → focus expiré
    # _expire_focus archive le fact focus (id 99 dans _make_loop).
    facts.set_status.assert_any_await(99, FactStatus.ARCHIVED)


@pytest.mark.asyncio
async def test_focus_divague_resets_rumination_count():
    """DIVAGUE = vrai changement de sujet → le fil repart de zéro (le capital de
    ressassement accumulé est effacé, contrairement à PROGRESSE)."""
    from bot.intelligence.memory.facts import FactStatus
    loop, attention, reasoning, dispatcher, facts, judge, feed = _make_loop()
    judge.judge = AsyncMock(side_effect=["RESSASSE", "DIVAGUE", "RESSASSE"])
    await loop._tick()   # RESSASSE → count 1
    await loop._tick()   # DIVAGUE → reset 0 (nouveau sujet)
    await loop._tick()   # RESSASSE → count 1 < LIMIT → focus PAS expiré
    for call in facts.set_status.await_args_list:
        assert call.args[0] != 99, "le focus ne devait pas être expiré après un seul ressassement post-divagation"


# ── Fix A : rendu propre des messages dans le prompt cognitif (_one_line) ──

def test_one_line_short_unchanged():
    from bot.intelligence.reasoning_agent import _one_line
    assert _one_line("court message", 220) == "court message"


def test_one_line_neutralizes_newlines():
    from bot.intelligence.reasoning_agent import _one_line
    assert _one_line("a\nb", 220) == "a b"
    assert "\n" not in _one_line("ligne1\nligne2\nligne3", 220)


def test_one_line_truncates_with_ellipsis():
    from bot.intelligence.reasoning_agent import _one_line
    out = _one_line("x" * 300, 220)
    assert out.endswith("…")
    assert len(out) <= 221


def test_one_line_real_message_not_cut_at_mais():
    """Régression : le message réel de 139 chars (qui était coupé pile à « mais »
    par l'ancien [:100]) doit désormais être rendu entier, sans ellipse."""
    from bot.intelligence.reasoning_agent import _one_line
    msg = ("attention, tu ne réponds pas a chaque message au moins ?\n"
           "il faut juste que tu puisses les lire, mais si tu réponds a chaque fois c'est trop")
    out = _one_line(msg, 220)
    assert out.endswith("c'est trop")
    assert not out.endswith("mais")
    assert "…" not in out  # 139 < 220 → aucune troncature


# ── Bug 2 : routage SPEAK vers un vrai canal ──

@pytest.mark.asyncio
async def test_speak_unknown_channel_redirected_to_last_active():
    """SPEAK avec channel halluciné inconnu + une interaction récente sur '55'
    → la décision dispatchée vise '55'."""
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
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
        spontaneous_channel_speak_enabled=True,
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
    loop, attention, reasoning, dispatcher, *_ = _make_loop()
    reasoning.reason = AsyncMock(return_value=_RR(
        thought_text="je veux dire un truc dans le vide", thought_fact_id=1,
        decisions=[_MD(action="SPEAK", channel_id="999999", message="yo")],
    ))
    # aucune notify_activity → _recent_interactions vide
    await loop._tick()
    dispatcher.dispatch.assert_not_called()


# ── Anti-rumination sémantique : juge de progression ──

@pytest.mark.asyncio
async def test_ressasse_not_published_and_thought_archived():
    from bot.intelligence.memory.facts import FactStatus
    loop, _a, _r, _d, facts, _j, feed = _make_loop(verdict="RESSASSE")
    await loop._tick()
    # Pensée ressassée : aucun THINK publié sur le feed.
    think_published = any(c.args[0].get("type") == "THINK" for c in feed.publish.call_args_list)
    assert not think_published
    # La pensée déjà stockée (#7) est archivée.
    facts.set_status.assert_any_await(7, FactStatus.ARCHIVED)
    # Compteur incrémenté.
    assert loop._focus_rumination_count == 1


@pytest.mark.asyncio
async def test_two_ressasse_expire_focus():
    from bot.intelligence.memory.facts import FactStatus
    loop, _a, _r, _d, facts, _j, _f = _make_loop(verdict="RESSASSE")
    await loop._tick()
    await loop._tick()
    # Au 2e ressassement, le focus actif (#99) est archivé et le compteur remis à 0.
    facts.set_status.assert_any_await(99, FactStatus.ARCHIVED)
    assert loop._focus_rumination_count == 0


@pytest.mark.asyncio
async def test_progresse_published_and_counter_preserved():
    """PROGRESSE publie la pensée MAIS ne remet PAS le compteur de ressassement à
    zéro : le capital accumulé est conservé (compteur cumulatif anti-immortalité
    du focus). Seuls DIVAGUE / juge absent / expiration remettent à zéro."""
    loop, _a, _r, _d, facts, _j, feed = _make_loop(verdict="PROGRESSE")
    loop._focus_rumination_count = 1
    await loop._tick()
    think_published = any(c.args[0].get("type") == "THINK" for c in feed.publish.call_args_list)
    assert think_published
    assert "pensée" in loop._recent_thoughts
    assert loop._focus_rumination_count == 1


@pytest.mark.asyncio
async def test_judge_failure_falls_back_to_lexical():
    # Juge qui lève → on ne crashe pas ; la pensée est publiée (fallback : pas de
    # doublon lexical dans la fenêtre vide).
    loop, _a, _r, _d, _facts, judge, feed = _make_loop()
    judge.judge = AsyncMock(side_effect=RuntimeError("LLM down"))
    await loop._tick()
    think_published = any(c.args[0].get("type") == "THINK" for c in feed.publish.call_args_list)
    assert think_published
