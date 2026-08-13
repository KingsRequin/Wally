"""La boucle de sonde du duel : muette hors duel, et sur une horloge murale.

Deux exigences que le brief pose comme non négociables :

  · hors duel, la boucle ne demande RIEN à l'API — la sonde du watcher suffit à
    entretenir l'historique, et un duel consomme déjà 1 req/s à lui seul ;
  · l'instant passé au `tick` vient de `time.time()`. L'état du duel est
    persisté et traverse les redémarrages : une horloge monotone y repart de
    zéro et rend toute comparaison absurde (piège déjà payé ici,
    `bug_monotonic_uptime`).
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel_runner import boucle_sonde


def _runner(duel):
    runner = MagicMock()
    runner.duel_en_cours = duel
    runner.cadence_s = 2.0
    runner.tick = AsyncMock()
    return runner


def _sommeil_borne(limite: int, journal: list):
    """Un `sleep` qui compte les tours et arrête la boucle au bout de `limite`."""
    async def _sleep(duree: float) -> None:
        journal.append(duree)
        if len(journal) >= limite:
            raise asyncio.CancelledError
    return _sleep


@pytest.mark.asyncio
async def test_hors_duel_la_sonde_ne_demande_rien():
    runner = _runner(None)
    dodos: list[float] = []

    with pytest.raises(asyncio.CancelledError):
        await boucle_sonde(runner, sleep=_sommeil_borne(3, dodos))

    runner.tick.assert_not_awaited()
    # Et elle dort vraiment entre deux vérifications : une boucle qui tourne à
    # vide sans attendre mangerait un cœur pour ne rien faire.
    assert dodos and all(d > 0 for d in dodos)


@pytest.mark.asyncio
async def test_le_tick_recoit_une_horloge_murale():
    vus: list[float] = []
    runner = _runner(object())
    runner.tick = AsyncMock(side_effect=lambda t: vus.append(t))

    with pytest.raises(asyncio.CancelledError):
        await boucle_sonde(runner, sleep=_sommeil_borne(1, []))

    assert vus, "le tick n'a jamais été appelé pendant un duel"
    # Une horloge monotone rendrait l'uptime de la machine : des jours d'écart.
    assert abs(vus[0] - time.time()) < 60


@pytest.mark.asyncio
async def test_une_erreur_de_tick_ne_tue_pas_la_sonde():
    """Une boucle de fond ne meurt jamais en silence : elle repart."""
    runner = _runner(object())
    runner.tick = AsyncMock(side_effect=RuntimeError("API muette"))
    dodos: list[float] = []

    with pytest.raises(asyncio.CancelledError):
        await boucle_sonde(runner, sleep=_sommeil_borne(3, dodos))

    assert runner.tick.await_count >= 2


@pytest.mark.asyncio
async def test_sans_runner_la_boucle_s_arrete_sans_bruit():
    """Apex indisponible au boot : pas de duel, pas de sonde."""
    await boucle_sonde(None, sleep=_sommeil_borne(1, []))
