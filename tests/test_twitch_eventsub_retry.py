"""Reprise différée des souscriptions EventSub refusées au démarrage.

Contexte : au boot, les dernières souscriptions (`subscription_end`, `cheer`)
tombent en 429 quand les reboots sont rapprochés — le budget de CRÉATION se
recharge en minutes. Sans reprise, elles manquaient jusqu'au redémarrage suivant
et les bits passaient inaperçus.

Un fix antérieur retentait en 3/6/12 s en bloquant le boot : réfuté en live et
reverté. Ici la reprise est espacée en minutes ET en tâche de fond.
"""
import asyncio

import pytest

from bot.twitch.events import _RETRY_DELAYS, _retry_failed_subscriptions


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """Neutralise les attentes réelles (plusieurs minutes)."""
    async def _instant(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant)


def test_les_reprises_sont_espacees_en_minutes():
    """Le fix reverté échouait justement pour avoir retenté en secondes."""
    assert min(_RETRY_DELAYS) >= 60
    assert list(_RETRY_DELAYS) == sorted(_RETRY_DELAYS)  # espacement croissant


@pytest.mark.asyncio
async def test_une_souscription_qui_repasse_est_recreee():
    calls = []

    async def _ok():
        calls.append("cheer")

    await _retry_failed_subscriptions([("cheer", _ok)])
    assert calls == ["cheer"]  # réussie du premier coup, pas de reprise inutile


@pytest.mark.asyncio
async def test_on_retente_jusqu_a_ce_que_ca_passe():
    attempts = []

    async def _flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("429")

    await _retry_failed_subscriptions([("cheer", _flaky)])
    assert len(attempts) == 2  # échec puis succès → on s'arrête là


@pytest.mark.asyncio
async def test_abandon_signale_en_warning_apres_toutes_les_reprises():
    """Tant qu'on retente, c'est attendu ; une fois abandonné, c'est une anomalie."""
    from loguru import logger

    captured: list[str] = []
    sink = logger.add(lambda m: captured.append(m), level="WARNING")
    try:
        async def _always_429():
            raise RuntimeError("429")

        await _retry_failed_subscriptions([("cheer", _always_429)])
    finally:
        logger.remove(sink)

    assert any("abandon" in m and "cheer" in m for m in captured)


@pytest.mark.asyncio
async def test_aucun_warning_tant_que_la_reprise_aboutit():
    from loguru import logger

    captured: list[str] = []
    sink = logger.add(lambda m: captured.append(m), level="WARNING")
    try:
        attempts = []

        async def _flaky():
            attempts.append(1)
            if len(attempts) < 2:
                raise RuntimeError("429")

        await _retry_failed_subscriptions([("cheer", _flaky)])
    finally:
        logger.remove(sink)

    assert captured == []


@pytest.mark.asyncio
async def test_une_fabrique_est_reutilisable():
    """Une coroutine ne s'await qu'une fois : d'où les fabriques."""
    seen = []

    async def _fail_once():
        seen.append(1)
        if len(seen) == 1:
            raise RuntimeError("429")

    await _retry_failed_subscriptions([("sub", _fail_once)])
    assert len(seen) == 2  # la seconde tentative n'a pas levé "cannot reuse coroutine"


# ── Nettoyage des souscriptions mortes ──

class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeHTTP:
    """Client httpx minimal : mémorise les DELETE émis."""

    def __init__(self, payload, get_status=200):
        self._payload = payload
        self._get_status = get_status
        self.deleted: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse(self._get_status, self._payload)

    async def delete(self, url, headers=None, params=None):
        self.deleted.append(params["id"])
        return _FakeResponse(204)


@pytest.mark.asyncio
async def test_seules_les_souscriptions_mortes_sont_supprimees(monkeypatch):
    """Une souscription vivante ne doit surtout pas sauter."""
    import bot.twitch.events as ev

    http = _FakeHTTP({"data": [
        {"id": "a", "status": "websocket_disconnected", "type": "channel.cheer"},
        {"id": "b", "status": "enabled", "type": "channel.subscribe"},
        {"id": "c", "status": "websocket_failed_ping_pong", "type": "channel.raid"},
    ]})
    monkeypatch.setattr(ev.httpx, "AsyncClient", lambda **kw: http)

    removed = await ev.purge_stale_subscriptions("cid", "tok")
    assert removed == 2
    assert http.deleted == ["a", "c"]


@pytest.mark.asyncio
async def test_le_nettoyage_ne_bloque_jamais_le_boot(monkeypatch):
    """Twitch injoignable : on continue sans souscriptions nettoyées."""
    import bot.twitch.events as ev

    class _Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def get(self, *a, **kw): raise RuntimeError("réseau HS")

    monkeypatch.setattr(ev.httpx, "AsyncClient", lambda **kw: _Boom())
    assert await ev.purge_stale_subscriptions("cid", "tok") == 0


@pytest.mark.asyncio
async def test_pas_de_token_pas_d_appel(monkeypatch):
    import bot.twitch.events as ev
    assert await ev.purge_stale_subscriptions("cid", "") == 0


# ── Fermeture des transports WebSocket ──

class _FakeSock:
    def __init__(self, closed=False):
        self.closed = closed
        self.close_called = False

    async def close(self):
        self.close_called = True
        self.closed = True


class _FakeWS:
    def __init__(self, sock):
        self._sock = sock


class _FakeBot:
    def __init__(self, sockets):
        self._eventsub_client = type("C", (), {"_sockets": sockets})()


@pytest.mark.asyncio
async def test_les_transports_ouverts_sont_rendus_a_twitch():
    """La limite est de 3 par utilisateur : un socket non fermé reste occupé."""
    import bot.twitch.events as ev

    a, b = _FakeSock(), _FakeSock()
    closed = await ev.close_eventsub_client(_FakeBot([_FakeWS(a), _FakeWS(b)]))
    assert closed == 2
    assert a.close_called and b.close_called


@pytest.mark.asyncio
async def test_un_socket_deja_ferme_est_ignore():
    import bot.twitch.events as ev

    deja = _FakeSock(closed=True)
    assert await ev.close_eventsub_client(_FakeBot([_FakeWS(deja)])) == 0
    assert not deja.close_called


@pytest.mark.asyncio
async def test_sans_client_eventsub_rien_ne_casse():
    import bot.twitch.events as ev

    assert await ev.close_eventsub_client(object()) == 0


@pytest.mark.asyncio
async def test_une_fermeture_qui_echoue_ne_bloque_pas_les_autres():
    """À l'arrêt, une erreur sur un socket ne doit pas laisser les autres ouverts."""
    import bot.twitch.events as ev

    class _Boom(_FakeSock):
        async def close(self):
            raise RuntimeError("socket cassé")

    ok = _FakeSock()
    closed = await ev.close_eventsub_client(_FakeBot([_FakeWS(_Boom()), _FakeWS(ok)]))
    assert closed == 1
    assert ok.close_called


# ── Correctif du suivi des sockets (twitchio 2.10.0) ──

@pytest.mark.asyncio
async def test_le_socket_cree_faute_de_place_est_memorise(monkeypatch):
    """Sans ça, twitchio rouvrait une WebSocket par souscription → limite de 3
    connexions par utilisateur atteinte, puis 429."""
    import bot.twitch.events as ev
    from twitchio.ext.eventsub import EventSubWSClient
    import twitchio.ext.eventsub.websocket as tio_ws

    created: list[object] = []

    class _FakeWebsocket:
        def __init__(self, client, http):
            self.remaining_slots = 0  # force la branche « aucune place »
            created.append(self)

        async def connect(self):
            return None

        def add_subscription(self, sub):
            self.sub = sub

    monkeypatch.setattr(tio_ws, "Websocket", _FakeWebsocket)
    monkeypatch.setattr(EventSubWSClient, "_wally_socket_tracking_patched", False, raising=False)
    ev._patch_socket_tracking()

    client = EventSubWSClient.__new__(EventSubWSClient)
    client.client = object()
    client._http = object()
    client._sockets = []

    await client._assign_subscription(object())
    # 1er socket (liste vide) + celui créé faute de place, TOUS deux suivis
    assert len(client._sockets) == len(created)
    assert len(client._sockets) == 2


def test_le_patch_est_idempotent():
    import bot.twitch.events as ev
    from twitchio.ext.eventsub import EventSubWSClient

    ev._patch_socket_tracking()
    first = EventSubWSClient._assign_subscription
    ev._patch_socket_tracking()
    assert EventSubWSClient._assign_subscription is first
