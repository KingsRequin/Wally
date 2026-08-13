"""La boucle de sonde du duel : muette hors duel, et sur une horloge murale.

Trois exigences que le brief pose comme non négociables :

  · hors duel, la boucle ne demande RIEN à l'API — la sonde du watcher suffit à
    entretenir l'historique, et un duel consomme déjà 1 req/s à lui seul ;
  · l'instant passé au `tick` vient de `time.time()`. L'état du duel est
    persisté et traverse les redémarrages : une horloge monotone y repart de
    zéro et rend toute comparaison absurde (piège déjà payé ici,
    `bug_monotonic_uptime`) ;
  · le runner est relu à chaque tour : il est câblé pendant le démarrage, et la
    boucle ne doit pas dépendre de qui, du câblage ou du `gather`, part le
    premier.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat
from bot.core.apex.duel_runner import boucle_sonde


def _runner(duel, cadence=2.0, cadence_courante=None):
    runner = MagicMock()
    runner.duel_en_cours = duel
    runner.cadence_s = cadence
    runner.cadence_courante = cadence if cadence_courante is None else cadence_courante
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
        await boucle_sonde(lambda: runner, sleep=_sommeil_borne(3, dodos))

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
        await boucle_sonde(lambda: runner, sleep=_sommeil_borne(1, []))

    assert vus, "le tick n'a jamais été appelé pendant un duel"
    # Une horloge monotone rendrait l'uptime de la machine : des jours d'écart.
    assert abs(vus[0] - time.time()) < 60


@pytest.mark.asyncio
async def test_un_runner_cable_apres_coup_est_pris_en_compte():
    """Le runner naît pendant le démarrage, la boucle peut partir avant lui."""
    runner = _runner(object())
    source = MagicMock(side_effect=[None, None, runner])

    with pytest.raises(asyncio.CancelledError):
        await boucle_sonde(source, sleep=_sommeil_borne(3, []))

    runner.tick.assert_awaited_once()


@pytest.mark.asyncio
async def test_attendre_un_uid_ne_se_sonde_pas_a_la_cadence_d_une_manche():
    """En résolution il n'y a rien à mesurer : inutile de se réveiller à 2 s."""
    duel = Duel(viewer_nom="bob", viewer_uid="", azrael_uid="7",
                etat=Etat.RESOLUTION)
    runner = DuelRunnerFactice(duel)
    dodos: list[float] = []

    with pytest.raises(asyncio.CancelledError):
        await boucle_sonde(lambda: runner, sleep=_sommeil_borne(1, dodos))

    assert dodos[0] > runner.cadence_s


class DuelRunnerFactice:
    """Juste ce que la boucle lit — la vraie cadence, elle, vient du runner."""

    def __init__(self, duel):
        from bot.core.apex.duel_runner import DuelRunner

        self._vrai = DuelRunner(client=MagicMock(), db=MagicMock(), api=MagicMock(),
                                annoncer=AsyncMock(), azrael_uid="7")
        self._vrai.duel_en_cours = duel
        self.tick = AsyncMock()

    @property
    def duel_en_cours(self):
        return self._vrai.duel_en_cours

    @property
    def cadence_s(self):
        return self._vrai.cadence_s

    @property
    def cadence_courante(self):
        return self._vrai.cadence_courante


@pytest.mark.asyncio
async def test_une_erreur_de_tick_ne_tue_pas_la_sonde():
    """Une boucle de fond ne meurt jamais en silence : elle repart."""
    runner = _runner(object())
    runner.tick = AsyncMock(side_effect=RuntimeError("API muette"))
    dodos: list[float] = []

    with pytest.raises(asyncio.CancelledError):
        await boucle_sonde(lambda: runner, sleep=_sommeil_borne(3, dodos))

    assert runner.tick.await_count >= 2


@pytest.mark.asyncio
async def test_sans_runner_la_sonde_attend_sans_rien_demander():
    """Apex indisponible : la boucle vit, silencieuse, sans toucher au réseau."""
    dodos: list[float] = []

    with pytest.raises(asyncio.CancelledError):
        await boucle_sonde(lambda: None, sleep=_sommeil_borne(2, dodos))

    assert len(dodos) == 2
