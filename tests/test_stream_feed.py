# tests/test_stream_feed.py
"""Flux passif des événements du stream : tampon, rendu, câblage watcher/events."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot.core.stream_feed as sf
import bot.core.stream_watcher as sw
from bot.core.stream_feed import StreamFeed, current_stream_feed_block
from bot.core.stream_watcher import StreamWatcher

LIVE = {
    "live": True, "title": "Ranked Apex", "category": "Apex Legends",
    "viewers": 40, "started_at": "2026-08-05T18:00:00Z",
}
OFFLINE = {
    "live": False, "title": None, "category": None, "viewers": 0, "started_at": None,
}


@pytest.fixture(autouse=True)
def _reset_active():
    sf._active = None
    sw._active = None
    yield
    sf._active = None
    sw._active = None


def _api(*results):
    api = AsyncMock()
    api.get_stream = AsyncMock(side_effect=list(results))
    return api


def _watcher_with_feed(*results, **kwargs):
    """Le consommateur réel est `StreamFeed.record(description, *, kind, notify)` :
    l'observateur de test en respecte la signature, sinon il teste un contrat qui
    n'existe pas."""
    events: list[str] = []

    def _record(description, *, kind="", notify=True):
        events.append(description)

    w = StreamWatcher(
        _api(*results), streamer_name="Azrael_TTV",
        on_event=_record, **kwargs,
    )
    return w, events


# ── StreamFeed : tampon et rendu ──────────────────────────────────────────────

def test_render_empty_feed_is_blank():
    assert StreamFeed("Azrael_TTV").render() == ""


def test_render_lists_events_with_age_and_passive_directive():
    feed = StreamFeed("Azrael_TTV")
    feed.record("Azrael_TTV a lancé son live (jeu : Apex Legends)")
    out = feed.render()
    assert "Flux du stream (perception passive)" in out
    assert "Azrael_TTV a lancé son live" in out
    assert "à l'instant" in out
    # La consigne de non-réaction voyage AVEC le bloc.
    assert "tu ne réagis pas" in out
    assert "si on t'interroge" in out


def test_record_ignores_consecutive_duplicate():
    feed = StreamFeed("Azrael_TTV")
    feed.record("raid de bob avec 30 spectateurs")
    feed.record("raid de bob avec 30 spectateurs")
    assert feed.render().count("raid de bob") == 1


def test_record_ignores_blank():
    feed = StreamFeed("Azrael_TTV")
    feed.record("   ")
    feed.record_chat("bob", "  ")
    assert feed.render() == ""


def test_events_are_bounded():
    feed = StreamFeed("Azrael_TTV", max_events=3)
    for i in range(6):
        feed.record(f"événement {i}")
    out = feed.render()
    assert "événement 0" not in out
    assert "événement 5" in out


def test_expired_events_are_dropped():
    feed = StreamFeed("Azrael_TTV", event_ttl=60.0)
    with patch("bot.core.stream_feed.time.monotonic", return_value=1000.0):
        feed.record("vieux truc")
    with patch("bot.core.stream_feed.time.monotonic", return_value=1100.0):
        assert feed.render() == ""


def test_chat_expires_faster_than_events():
    feed = StreamFeed("Azrael_TTV", event_ttl=600.0, chat_ttl=60.0)
    with patch("bot.core.stream_feed.time.monotonic", return_value=1000.0):
        feed.record("Azrael_TTV lance Apex Legends")
        feed.record_chat("bob", "gg")
    with patch("bot.core.stream_feed.time.monotonic", return_value=1100.0):
        out = feed.render()
    assert "Apex Legends" in out
    assert "[bob]" not in out


def test_chat_rendered_and_excludable():
    feed = StreamFeed("Azrael_TTV")
    feed.record("Azrael_TTV lance Apex Legends")
    feed.record_chat("bob", "gg les gars")
    assert "[bob] gg les gars" in feed.render()
    assert "[bob]" not in feed.render(include_chat=False)


def test_chat_only_still_renders():
    feed = StreamFeed("Azrael_TTV")
    feed.record_chat("bob", "gg")
    assert "[bob] gg" in feed.render()
    # ...mais pas si on exclut le chat : il ne reste rien.
    assert feed.render(include_chat=False) == ""


def test_age_labels():
    feed = StreamFeed("Azrael_TTV")
    with patch("bot.core.stream_feed.time.monotonic", return_value=0.0):
        feed.record("un événement")
    with patch("bot.core.stream_feed.time.monotonic", return_value=600.0):
        assert "il y a 10 min" in feed.render()
    with patch("bot.core.stream_feed.time.monotonic", return_value=7200.0 - 1):
        assert "il y a 1 h" in feed.render()


def test_current_block_none_without_active_feed():
    assert current_stream_feed_block() is None


def test_current_block_none_when_feed_is_empty():
    StreamFeed("Azrael_TTV").activate()
    assert current_stream_feed_block() is None


def test_activate_exposes_block():
    feed = StreamFeed("Azrael_TTV")
    feed.activate()
    feed.record("raid de bob avec 30 spectateurs")
    assert "raid de bob" in current_stream_feed_block()
    assert "raid de bob" in current_stream_feed_block(include_chat=False)


# ── StreamWatcher : traduction des polls en événements de flux ────────────────

async def test_baseline_poll_emits_nothing():
    w, events = _watcher_with_feed(LIVE)
    await w._poll_once()
    assert events == []


async def test_live_start_emits_game_and_title():
    w, events = _watcher_with_feed(OFFLINE, LIVE)
    await w._poll_once()
    await w._poll_once()
    assert len(events) == 1
    assert "a lancé son live" in events[0]
    assert "Apex Legends" in events[0]
    assert "Ranked Apex" in events[0]


async def test_live_end_emits_event():
    w, events = _watcher_with_feed(LIVE, OFFLINE)
    await w._poll_once()
    await w._poll_once()
    assert events == ["Azrael_TTV a terminé son live."]


async def test_category_change_during_live():
    w, events = _watcher_with_feed(LIVE, {**LIVE, "category": "Warhammer: Darktide"})
    await w._poll_once()
    await w._poll_once()
    assert events == ["Azrael_TTV change de jeu : Apex Legends → Warhammer: Darktide"]


async def test_title_change_during_live():
    w, events = _watcher_with_feed(LIVE, {**LIVE, "title": "on passe master"})
    await w._poll_once()
    await w._poll_once()
    assert len(events) == 1
    assert "changé le titre" in events[0]
    assert "on passe master" in events[0]


async def test_no_event_when_nothing_moves():
    w, events = _watcher_with_feed(LIVE, dict(LIVE))
    await w._poll_once()
    await w._poll_once()
    assert events == []


async def test_viewer_swing_emitted_once_per_plateau():
    # 40 → 90 (+125 %, ≥ 10) : vague. Puis 95 : trop faible, silence.
    w, events = _watcher_with_feed(
        LIVE, {**LIVE, "viewers": 90}, {**LIVE, "viewers": 95},
    )
    await w._poll_once()
    await w._poll_once()
    await w._poll_once()
    assert events == ["l'audience monte : 40 → 90 spectateurs"]


async def test_small_viewer_variation_is_ignored():
    w, events = _watcher_with_feed(LIVE, {**LIVE, "viewers": 45})
    await w._poll_once()
    await w._poll_once()
    assert events == []


async def test_viewer_drop_emitted():
    w, events = _watcher_with_feed(LIVE, {**LIVE, "viewers": 12})
    await w._poll_once()
    await w._poll_once()
    assert events == ["l'audience retombe : 40 → 12 spectateurs"]


async def test_on_event_failure_never_breaks_poll():
    def boom(_desc):
        raise RuntimeError("flux cassé")

    w = StreamWatcher(_api(OFFLINE, LIVE), streamer_name="Azrael_TTV", on_event=boom)
    await w._poll_once()
    await w._poll_once()  # ne lève pas
    assert w.status["live"] is True


# ── Câblage : événements Twitch et chat du stream ─────────────────────────────

def _event_bot(feed):
    bot = MagicMock()
    bot.stream_feed = feed
    bot.emotion.get_state = MagicMock(return_value={})
    bot.config.twitch_events.get = lambda k, d=None: MagicMock(active=True, message="msg")
    return bot


def _register(bot):
    from bot.twitch.events import register_events
    handlers: dict = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    return handlers


async def test_raid_is_recorded_in_feed():
    feed = StreamFeed("Azrael_TTV")
    bot = _event_bot(feed)
    handlers = _register(bot)
    payload = MagicMock()
    payload.data.viewer_count = 42
    payload.data.raider.name = "bob"
    payload.data.reciever.name = "azrael_ttv"
    with patch("bot.twitch.events.social._generate_and_send", new_callable=AsyncMock):
        await handlers["event_eventsub_notification_raid"](payload)
    assert "raid de bob avec 42 spectateurs" in feed.render()


async def test_cheer_is_recorded_in_feed():
    feed = StreamFeed("Azrael_TTV")
    bot = _event_bot(feed)
    handlers = _register(bot)
    payload = MagicMock()
    payload.data.bits = 500
    payload.data.is_anonymous = False
    payload.data.user.name = "alice"
    payload.data.broadcaster.name = "azrael_ttv"
    with patch("bot.twitch.events.social._generate_and_send", new_callable=AsyncMock):
        await handlers["event_eventsub_notification_cheer"](payload)
    assert "alice balance 500 bits" in feed.render()


async def test_feed_absent_does_not_break_events():
    bot = _event_bot(None)
    handlers = _register(bot)
    payload = MagicMock()
    payload.data.viewer_count = 10
    payload.data.raider.name = "bob"
    payload.data.reciever.name = "azrael_ttv"
    with patch("bot.twitch.events.social._generate_and_send", new_callable=AsyncMock):
        await handlers["event_eventsub_notification_raid"](payload)  # ne lève pas


async def test_home_chat_recorded_while_live():
    from tests.test_twitch_handlers import make_bot, make_payload
    from bot.twitch.handlers import handle_message

    feed = StreamFeed("Azrael_TTV")
    bot = make_bot()
    bot.stream_feed = feed
    bot._channel_ids = {}
    bot._stream_info = {"live": True}
    bot._active_visits = {}
    bot.cognitive_loop = None
    bot.fact_extractor = None
    bot.reaction_tracker = None
    with patch("bot.twitch.handlers.dispatch_command", new_callable=AsyncMock,
               return_value=False):
        await handle_message(bot, make_payload(content="gg", author_name="bob",
                                               channel="azrael_ttv"))
    assert "[bob] gg" in feed.render()


async def test_chat_not_recorded_when_offline():
    from tests.test_twitch_handlers import make_bot, make_payload
    from bot.twitch.handlers import handle_message

    feed = StreamFeed("Azrael_TTV")
    bot = make_bot()
    bot.stream_feed = feed
    bot._channel_ids = {}
    bot._stream_info = {"live": False}
    bot._active_visits = {}
    bot.cognitive_loop = None
    bot.fact_extractor = None
    bot.reaction_tracker = None
    with patch("bot.twitch.handlers.dispatch_command", new_callable=AsyncMock,
               return_value=False):
        await handle_message(bot, make_payload(content="gg", author_name="bob",
                                               channel="azrael_ttv"))
    assert feed.render() == ""


async def test_guest_channel_chat_not_recorded():
    from tests.test_twitch_handlers import make_bot, make_payload
    from bot.twitch.handlers import handle_message

    feed = StreamFeed("Azrael_TTV")
    bot = make_bot()
    bot.stream_feed = feed
    bot._channel_ids = {"invite": "999"}
    bot._stream_info = {"live": True}
    bot._active_visits = {}
    bot.cognitive_loop = None
    bot.fact_extractor = None
    bot.reaction_tracker = None
    with patch("bot.twitch.handlers.dispatch_command", new_callable=AsyncMock,
               return_value=False):
        await handle_message(bot, make_payload(content="gg", author_name="bob",
                                               channel="invite"))
    assert feed.render() == ""


# ── observateur (overlay de stream) ──

def test_l_observateur_est_notifie_des_evenements_retenus():
    from bot.core.stream_feed import StreamFeed
    vus = []
    feed = StreamFeed(streamer_name="azrael")
    feed.set_observer(lambda description, kind: vus.append(description))
    feed.record("Un raid de 42 personnes arrive", kind="raid")
    assert vus == ["Un raid de 42 personnes arrive"]


def test_l_observateur_ne_voit_pas_les_doublons_consecutifs():
    """Un poll qui « flappe » ne doit pas déclencher deux réactions."""
    from bot.core.stream_feed import StreamFeed
    vus = []
    feed = StreamFeed()
    feed.set_observer(lambda description, kind: vus.append(description))
    feed.record("Le jeu passe à Apex", kind="game_change")
    feed.record("Le jeu passe à Apex", kind="game_change")
    assert len(vus) == 1


def test_un_observateur_en_erreur_ne_casse_pas_le_flux():
    """Le flux de contexte est prioritaire sur l'overlay."""
    from bot.core.stream_feed import StreamFeed
    def _boom(_):
        raise RuntimeError("overlay HS")
    feed = StreamFeed()
    feed.set_observer(_boom)
    feed.record("Un raid arrive")          # ne doit pas lever
    assert "Un raid arrive" in feed.render()


def test_observateur_detachable():
    from bot.core.stream_feed import StreamFeed
    vus = []
    feed = StreamFeed()
    feed.set_observer(vus.append)
    feed.set_observer(None)
    feed.record("Un raid arrive")
    assert vus == []
