"""Une API muette ne veut pas dire « le live est terminé ».

Vécu le 2026-08-08 à 20:11:52 : `Failed to fetch Twitch stream status:` (message
d'exception vide, donc une simple coupure réseau) suivi dans la même seconde de
`Stream Azrael_TTV : live → offline` — alors que le live tournait encore. Wally a
quitté le vocal dans la foulée.

`get_stream()` renvoyait la forme « pas de live » sur TOUTE erreur : le watcher
ne pouvait pas distinguer « il a coupé son stream » de « je n'ai pas pu
demander ». Même famille que la sonde EventSub.
"""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from bot.twitch.api import TwitchAPI


def _api(monkeypatch, *, raise_exc=None, status=200, payload=None):
    api = TwitchAPI.__new__(TwitchAPI)
    api._tm = MagicMock()
    api._tm.bot_token = "tok"
    api._tm.refresh = AsyncMock(return_value=False)
    api._client_id = "cid"
    api._broadcaster_id = "42"

    class _Resp:
        status_code = status

        def raise_for_status(self):
            if status >= 400:
                raise httpx.HTTPStatusError("boom", request=None, response=None)

        def json(self):
            return payload or {"data": []}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            if raise_exc:
                raise raise_exc
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())
    return api


@pytest.mark.asyncio
async def test_une_coupure_reseau_donne_un_statut_inconnu(monkeypatch):
    api = _api(monkeypatch, raise_exc=httpx.ReadError(""))

    statut = await api.get_stream()

    assert statut["unknown"] is True
    assert statut["live"] is False   # le contrat reste un dict exploitable


@pytest.mark.asyncio
async def test_un_vrai_offline_nest_pas_marque_inconnu(monkeypatch):
    """Twitch a répondu, et sa réponse est « personne ne streame »."""
    api = _api(monkeypatch, payload={"data": []})

    statut = await api.get_stream()

    assert not statut.get("unknown")
    assert statut["live"] is False


@pytest.mark.asyncio
async def test_un_live_en_cours_reste_intact(monkeypatch):
    api = _api(monkeypatch, payload={"data": [{
        "title": "Ranked", "game_name": "Apex Legends",
        "viewer_count": 40, "started_at": "2026-08-08T18:00:00Z",
    }]})

    statut = await api.get_stream()

    assert statut["live"] is True
    assert not statut.get("unknown")


# ── le watcher doit ignorer ce qu'il ne sait pas ──

@pytest.mark.asyncio
async def test_le_watcher_garde_son_etat_quand_il_ne_sait_pas():
    """Le cœur du bug : sans ça, une coupure réseau déclenchait une transition
    live → offline, et tout ce qui en dépend (le vocal, notamment)."""
    from bot.core.stream_watcher import StreamWatcher

    transitions = []
    live = {"live": True, "title": "Ranked", "category": "Apex",
            "viewers": 40, "started_at": None}
    inconnu = {"live": False, "title": None, "category": None,
               "viewers": 0, "started_at": None, "unknown": True}

    api = MagicMock()
    api.get_stream = AsyncMock(side_effect=[live, inconnu])
    w = StreamWatcher(api, streamer_name="Azrael_TTV",
                      on_transition=lambda o, n: transitions.append((o, n)))

    await w._poll_once()      # baseline : live
    await w._poll_once()      # réseau coupé

    assert transitions == [], "une panne de sonde n'est pas une fin de live"
    assert w.status["live"] is True


@pytest.mark.asyncio
async def test_le_watcher_suit_un_vrai_passage_offline():
    """La régression à éviter : une vraie fin de live doit toujours passer."""
    from bot.core.stream_watcher import StreamWatcher

    transitions = []
    live = {"live": True, "title": "Ranked", "category": "Apex",
            "viewers": 40, "started_at": None}
    offline = {"live": False, "title": None, "category": None,
               "viewers": 0, "started_at": None}

    api = MagicMock()
    api.get_stream = AsyncMock(side_effect=[live, offline])
    w = StreamWatcher(api, streamer_name="Azrael_TTV",
                      on_transition=lambda o, n: transitions.append((o, n)))

    await w._poll_once()
    await w._poll_once()

    assert len(transitions) == 1
    assert w.status["live"] is False
