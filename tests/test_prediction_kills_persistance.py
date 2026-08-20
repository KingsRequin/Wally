# tests/test_prediction_kills_persistance.py
"""Un pari ouvert survit au redémarrage (2026-08-20).

Plus grave que le widget de fin de partie : un pari Twitch engage les POINTS DES
VIEWERS. Deux défauts se cumulaient.

1. `PredictionKills.en_cours` vivait en RAM. Un rebuild — il y en a eu cinq le
   19/08 entre 20 h et 23 h — et plus personne ne savait qu'un pari était ouvert.
2. Pire : l'objet lui-même n'était créé QUE par `run_prediction_tool`, donc
   paresseusement, au premier pari. Après un redémarrage, `bot.prediction_kills`
   n'existait plus du tout : `_solder_pari_sur_partie` sortait à la première
   ligne, et le pari restait ouvert chez Twitch indéfiniment. Les mises sont
   bloquées tant que la prédiction n'est ni résolue ni annulée.

Le pari n'est PAS borné à la session du live, contrairement au suivi des kills :
une prédiction ouverte chez Twitch le reste, live ou pas. C'est l'âge seul qui
la périme.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.prediction_kills import PredictionKills

TRANCHES = [{"label": "0-2", "min": 0, "max": 2, "outcome_id": "o1"},
            {"label": "3+", "min": 3, "max": None, "outcome_id": "o2"}]


def _db():
    db = MagicMock()
    db._v = {}

    async def _set(c, v): db._v[c] = v
    async def _get(c): return db._v.get(c)
    async def _del(c): db._v.pop(c, None)

    db.set_state = AsyncMock(side_effect=_set)
    db.get_state = AsyncMock(side_effect=_get)
    db.delete_state = AsyncMock(side_effect=_del)
    return db


def _bot(db, api=None):
    bot = MagicMock()
    bot.db = db
    bot.twitch_api = api or MagicMock()
    return bot


@pytest.mark.asyncio
async def test_un_pari_ouvert_est_retrouve_apres_un_rebuild():
    db = _db()
    api = MagicMock()
    api.creer_prediction = AsyncMock(return_value={
        "id": "P1", "title": "Combien de kills ?",
        "outcomes": [{"id": "o1", "title": "0-2"}, {"id": "o2", "title": "3+"}]})

    avant = PredictionKills(db)
    assert (await avant.ouvrir(_bot(db, api), "Combien de kills ?",
                               [{"label": "0-2", "min": 0, "max": 2},
                                {"label": "3+", "min": 3, "max": None}], 60))["ok"]

    apres = PredictionKills(db)
    await apres.charger()

    assert apres.en_cours is not None
    assert apres.en_cours["id"] == "P1"


@pytest.mark.asyncio
async def test_le_pari_repris_se_resout_sur_le_bilan_suivant():
    """C'est tout l'intérêt : rendre leurs points aux viewers."""
    db = _db()
    api = MagicMock()
    api.resoudre_prediction = AsyncMock(return_value=True)

    avant = PredictionKills(db)
    avant.en_cours = {"id": "P1", "titre": "t", "tranches": TRANCHES}
    await avant.ranger()

    apres = PredictionKills(db)
    await apres.charger()
    assert await apres.sur_bilan(_bot(db, api), {"partie": 5}) is True

    api.resoudre_prediction.assert_awaited_once_with("P1", "o2")


@pytest.mark.asyncio
async def test_un_pari_resolu_ne_ressuscite_pas():
    db = _db()
    api = MagicMock()
    api.resoudre_prediction = AsyncMock(return_value=True)

    suivi = PredictionKills(db)
    suivi.en_cours = {"id": "P1", "titre": "t", "tranches": TRANCHES}
    await suivi.ranger()
    await suivi.sur_bilan(_bot(db, api), {"partie": 5})

    apres = PredictionKills(db)
    await apres.charger()
    assert apres.en_cours is None


@pytest.mark.asyncio
async def test_un_pari_annule_ne_ressuscite_pas():
    db = _db()
    api = MagicMock()
    api.annuler_prediction = AsyncMock(return_value=True)

    suivi = PredictionKills(db)
    suivi.en_cours = {"id": "P1", "titre": "t", "tranches": TRANCHES}
    await suivi.ranger()
    await suivi.sur_bilan(_bot(db, api), {"partie": None})   # non mesurable

    apres = PredictionKills(db)
    await apres.charger()
    assert apres.en_cours is None


@pytest.mark.asyncio
async def test_un_pari_qu_on_n_a_pas_pu_solder_est_garde():
    """Twitch refuse : on réessaiera à la partie suivante plutôt que
    d'abandonner les mises."""
    db = _db()
    api = MagicMock()
    api.resoudre_prediction = AsyncMock(return_value=False)

    suivi = PredictionKills(db)
    suivi.en_cours = {"id": "P1", "titre": "t", "tranches": TRANCHES}
    await suivi.ranger()
    assert await suivi.sur_bilan(_bot(db, api), {"partie": 5}) is False

    apres = PredictionKills(db)
    await apres.charger()
    assert apres.en_cours is not None


@pytest.mark.asyncio
async def test_sans_base_tout_fonctionne_comme_avant():
    suivi = PredictionKills(None)
    await suivi.charger()
    await suivi.ranger()
    assert suivi.en_cours is None
