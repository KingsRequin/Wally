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
