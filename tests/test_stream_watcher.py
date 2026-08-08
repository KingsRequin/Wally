import asyncio
from unittest.mock import AsyncMock

import pytest

import bot.core.stream_watcher as sw
from bot.core.stream_watcher import (
    StreamWatcher,
    current_stream_awareness,
    current_stream_status,
)

LIVE = {
    "live": True, "title": "Ranked Apex", "category": "Apex Legends",
    "viewers": 128, "started_at": "2026-07-10T18:00:00Z",
}
OFFLINE = {
    "live": False, "title": None, "category": None, "viewers": 0, "started_at": None,
}


@pytest.fixture(autouse=True)
def _reset_active():
    """Isole le singleton module-level entre les tests."""
    sw._active = None
    yield
    sw._active = None


def _api(*results):
    api = AsyncMock()
    api.get_stream = AsyncMock(side_effect=list(results))
    return api


async def test_status_defaults_offline():
    w = StreamWatcher(_api(), streamer_name="Azrael_TTV")
    assert w.status == OFFLINE
    # copie défensive : muter le retour ne touche pas l'état interne
    w.status["live"] = True
    assert w.status["live"] is False


async def test_first_poll_is_silent_baseline():
    """Un stream déjà live au boot ne doit PAS déclencher de fausse notif."""
    transitions = []
    w = StreamWatcher(_api(LIVE), on_transition=lambda o, n: transitions.append((o, n)))
    await w._poll_once()
    assert w.status["live"] is True
    assert transitions == []  # premier poll = baseline muette


async def test_transition_offline_to_live_fires():
    transitions = []
    w = StreamWatcher(
        _api(OFFLINE, LIVE),
        on_transition=lambda o, n: transitions.append((o, n)),
    )
    await w._poll_once()  # baseline offline
    await w._poll_once()  # offline -> live
    assert len(transitions) == 1
    old, new = transitions[0]
    assert old["live"] is False
    assert new["category"] == "Apex Legends"


async def test_transition_live_to_offline_fires():
    transitions = []
    w = StreamWatcher(
        _api(LIVE, OFFLINE),
        on_transition=lambda o, n: transitions.append(n),
    )
    await w._poll_once()  # baseline live
    await w._poll_once()  # live -> offline
    assert transitions == [OFFLINE]


async def test_no_transition_when_state_stable():
    transitions = []
    w = StreamWatcher(
        _api(LIVE, LIVE, LIVE),
        on_transition=lambda o, n: transitions.append(n),
    )
    for _ in range(3):
        await w._poll_once()
    assert transitions == []


async def test_on_poll_called_every_poll():
    seen = []
    w = StreamWatcher(_api(OFFLINE, LIVE), on_poll=seen.append)
    await w._poll_once()
    await w._poll_once()
    assert seen == [OFFLINE, LIVE]


async def test_poll_error_keeps_last_status_and_no_crash():
    api = AsyncMock()
    api.get_stream = AsyncMock(side_effect=[LIVE, RuntimeError("boom")])
    w = StreamWatcher(api)
    await w._poll_once()          # LIVE
    await w._poll_once()          # raise -> swallowed
    assert w.status["live"] is True  # dernier statut conservé


async def test_callback_exception_is_swallowed():
    def _boom(old, new):
        raise ValueError("kaboom")

    w = StreamWatcher(_api(OFFLINE, LIVE), on_transition=_boom)
    await w._poll_once()
    await w._poll_once()  # ne doit pas propager
    assert w.status["live"] is True


async def test_current_status_and_awareness_accessors():
    assert current_stream_status() is None
    assert current_stream_awareness() is None

    w = StreamWatcher(_api(LIVE), streamer_name="Azrael_TTV")
    w.activate()
    # avant tout poll : offline -> pas d'awareness
    assert current_stream_status()["live"] is False
    assert current_stream_awareness() is None

    await w._poll_once()  # devient live
    assert current_stream_status()["live"] is True
    line = current_stream_awareness()
    assert line is not None
    assert "Azrael_TTV" in line
    assert "Apex Legends" in line
    assert "Ranked Apex" in line


async def test_awareness_without_title():
    w = StreamWatcher(
        _api({**LIVE, "title": None}),
        streamer_name="Azrael_TTV",
    )
    w.activate()
    await w._poll_once()
    line = current_stream_awareness()
    assert line is not None
    assert "titre" not in line  # pas de titre => on n'en parle pas


async def test_run_loops_until_cancelled():
    w = StreamWatcher(_api(OFFLINE, LIVE, LIVE), interval=0)
    task = asyncio.create_task(w.run())
    await asyncio.sleep(0.05)
    task.cancel()
    await task
    assert w.status["live"] is True


def test_l_audience_est_percue_mais_ne_declenche_rien():
    """Le compteur de spectateurs fluctue tout seul : il ne dit rien de neuf au
    public et faisait commenter Wally dans le vide."""
    from bot.core.stream_watcher import StreamWatcher

    recu: list[tuple[str, bool]] = []

    def _record(description, *, kind="", notify=True):
        recu.append((description, notify))

    w = StreamWatcher(None, on_event=_record)
    w._viewers_mark = 10
    w._emit_feed_events(
        {"live": True, "viewers": 10, "category": "Apex", "title": "t"},
        {"live": True, "viewers": 40, "category": "Apex", "title": "t"},
    )
    audience = [r for r in recu if "audience" in r[0]]
    assert audience, "l'audience doit rester dans le flux passif"
    assert audience[0][1] is False, "mais sans réveiller le narrateur"


def test_un_changement_de_jeu_declenche_toujours():
    """Contre-exemple : ça, c'est un vrai événement du stream."""
    from bot.core.stream_watcher import StreamWatcher

    recu: list[tuple[str, bool]] = []

    def _record(description, *, kind="", notify=True):
        recu.append((description, notify))

    w = StreamWatcher(None, on_event=_record)
    w._emit_feed_events(
        {"live": True, "viewers": 10, "category": "Apex", "title": "t"},
        {"live": True, "viewers": 10, "category": "Rocket League", "title": "t"},
    )
    jeu = [r for r in recu if "change de jeu" in r[0]]
    assert jeu and jeu[0][1] is True
