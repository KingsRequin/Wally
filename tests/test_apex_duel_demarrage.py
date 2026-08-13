"""Le démarrage du duel : l'ordre des deux appels, et la source globale.

Deux invariants que rien ne rattrape à l'exécution :

  · `charger()` écrase l'identifiant de récompense avec ce qu'il trouve en base,
    y compris une valeur vide. Appelé APRÈS `assurer_recompense()`, il part donc
    sans identifiant — et chaque remboursement échoue, le viewer perd ses points.
  · sans `activate()`, `current_duel()` rend toujours None : Wally arbitre un
    duel dont il est incapable de parler, alors que toute la perception est en
    place.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex import duel_runner as mod
from bot.core.apex.duel import Duel, Etat
from bot.core.apex.duel_runner import (CLE_ETAT, CLE_RECOMPENSE, DuelRunner,
                                       armer_le_duel, current_duel)
from bot.twitch.events.redemptions import _est_notre_recompense


@pytest.fixture(autouse=True)
def _pas_de_fuite_globale():
    """`activate()` pose une source de module : la rendre au test suivant."""
    yield
    mod._active = None


def _runner_avec_duel_persiste(reward_id_dans_le_duel: str = ""):
    """Un duel en base, comme après un rebuild en pleine partie.

    `reward_id` absent de l'état persisté est le cas qui mord : c'est celui
    d'un duel ouvert par une version antérieure, ou d'un état écrit avant que
    l'identifiant ne soit connu.
    """
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7",
                redemption_id="rd", etat=Etat.ATTENTE_SQUAD)
    etat = duel.to_dict()
    if reward_id_dans_le_duel:
        etat["reward_id"] = reward_id_dans_le_duel

    stock = {CLE_ETAT: json.dumps(etat), CLE_RECOMPENSE: "rw-1"}
    db = MagicMock()
    db.get_state = AsyncMock(side_effect=lambda cle: stock.get(cle))
    db.set_state = AsyncMock(side_effect=lambda cle, val: stock.update({cle: val}))

    api = MagicMock()
    api.recompenses_gerables = AsyncMock(return_value=[{"id": "rw-1"}])
    api.creer_recompense = AsyncMock(return_value="rw-NEUVE")
    return DuelRunner(client=MagicMock(), db=db, api=api, annoncer=AsyncMock(),
                      azrael_uid="7"), api


@pytest.mark.asyncio
async def test_le_duel_repris_reste_remboursable():
    """L'identifiant de récompense survit à la reprise d'un duel."""
    runner, api = _runner_avec_duel_persiste()

    await armer_le_duel(runner, titre="Duel", cout=5000, prompt="ton uid")

    api.creer_recompense.assert_not_awaited()   # celle qui existe suffit
    bot = MagicMock()
    bot.duel_runner = runner
    assert await _est_notre_recompense(bot, "rw-1") is True


@pytest.mark.asyncio
async def test_le_duel_repris_est_lisible_par_le_prompt():
    runner, _ = _runner_avec_duel_persiste()

    await armer_le_duel(runner, titre="Duel", cout=5000, prompt="ton uid")

    assert current_duel() is not None
    assert current_duel().viewer_nom == "bob"


@pytest.mark.asyncio
async def test_sans_duel_en_base_la_recompense_est_quand_meme_connue():
    runner, api = _runner_avec_duel_persiste()
    await runner._db.set_state(CLE_ETAT, "")

    await armer_le_duel(runner, titre="Duel", cout=5000, prompt="ton uid")

    bot = MagicMock()
    bot.duel_runner = runner
    assert await _est_notre_recompense(bot, "rw-1") is True
    assert current_duel() is None
