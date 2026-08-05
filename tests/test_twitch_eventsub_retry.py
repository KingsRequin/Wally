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
