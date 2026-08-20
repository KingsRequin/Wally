# tests/test_etat_persistant.py
"""Le patron commun des états qui doivent survivre à un redémarrage (2026-08-20).

Trois modules l'avaient déjà réécrit chacun de son côté — l'overlay (bingo,
pendu, objectif), le duel Apex, le point de départ de progression — avec à
chaque fois les mêmes pièges à repayer : borner à la session du live, tolérer
une identité de live pas encore connue, ne jamais laisser une écriture se faire
ramasser par le garbage collector en vol.

Les redémarrages sont FRÉQUENTS ici (cinq le 19/08 entre 20 h et 23 h) : tout
ce qui vit en RAM meurt plusieurs fois par soirée.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.etat_persistant import EtatPersistant


def _db():
    db = MagicMock()
    db._valeurs = {}

    async def _set(cle, val):
        db._valeurs[cle] = val

    async def _get(cle):
        return db._valeurs.get(cle)

    async def _del(cle):
        db._valeurs.pop(cle, None)

    db.set_state = AsyncMock(side_effect=_set)
    db.get_state = AsyncMock(side_effect=_get)
    db.delete_state = AsyncMock(side_effect=_del)
    return db


@pytest.mark.asyncio
async def test_ce_qui_est_range_est_relu():
    db = _db()
    etat = EtatPersistant(db, "test:truc", session=lambda: "live-1")

    await etat.ranger({"total": 27, "parties": 6})

    assert await etat.charger() == {"total": 27, "parties": 6}


@pytest.mark.asyncio
async def test_l_etat_d_un_autre_live_est_ignore():
    """Deux lives se suivent : le cumul du précédent n'a rien à faire dans
    le suivant."""
    db = _db()
    session = ["live-1"]
    etat = EtatPersistant(db, "test:truc", session=lambda: session[0])
    await etat.ranger({"total": 27})

    session[0] = "live-2"
    assert await etat.charger() == {}


@pytest.mark.asyncio
async def test_une_session_inconnue_retombe_sur_l_age():
    """Au démarrage, le statut Twitch n'est pas encore revenu du poll (60 s) :
    l'identité du live est vide des DEUX côtés. Sans repli, la reprise échouait
    précisément dans le cas qu'elle vise — le rebuild."""
    db = _db()
    horloge = [1000.0]
    etat = EtatPersistant(db, "test:truc", session=lambda: "",
                          horloge=lambda: horloge[0], age_max_s=600)
    await etat.ranger({"total": 27})

    horloge[0] += 30          # un rebuild dure une quinzaine de secondes
    assert await etat.charger() == {"total": 27}


@pytest.mark.asyncio
async def test_un_etat_trop_vieux_est_ignore():
    db = _db()
    horloge = [1000.0]
    etat = EtatPersistant(db, "test:truc", session=lambda: "",
                          horloge=lambda: horloge[0], age_max_s=600)
    await etat.ranger({"total": 27})

    horloge[0] += 3600        # le live d'hier
    assert await etat.charger() == {}


@pytest.mark.asyncio
async def test_une_base_absente_ne_leve_jamais():
    etat = EtatPersistant(None, "test:truc", session=lambda: "live-1")
    await etat.ranger({"a": 1})
    assert await etat.charger() == {}


@pytest.mark.asyncio
async def test_un_json_tronque_ne_ressuscite_rien():
    """Une écriture interrompue laisse du JSON coupé en deux."""
    db = _db()
    db._valeurs["test:truc"] = '{"session": "live-1", "donnees": {"tot'
    etat = EtatPersistant(db, "test:truc", session=lambda: "live-1")
    assert await etat.charger() == {}


@pytest.mark.asyncio
async def test_une_base_en_erreur_ne_casse_pas_l_appelant():
    db = _db()
    db.get_state = AsyncMock(side_effect=RuntimeError("disque plein"))
    db.set_state = AsyncMock(side_effect=RuntimeError("disque plein"))
    etat = EtatPersistant(db, "test:truc", session=lambda: "live-1")

    await etat.ranger({"a": 1})     # ne lève pas
    assert await etat.charger() == {}


@pytest.mark.asyncio
async def test_ranger_sans_attendre_garde_une_reference_forte():
    """La boucle asyncio ne garde qu'une référence FAIBLE sur les tâches : une
    tâche collectée en vol perdrait précisément l'écriture qui doit survivre au
    process."""
    import asyncio

    db = _db()
    etat = EtatPersistant(db, "test:truc", session=lambda: "live-1")

    etat.ranger_bientot({"total": 3})
    assert etat._taches                      # tenue tant qu'elle n'a pas fini
    await asyncio.gather(*list(etat._taches))
    assert await etat.charger() == {"total": 3}
    assert not etat._taches                  # et relâchée après


def test_hors_boucle_asyncio_ranger_bientot_ne_leve_pas():
    """Appelée depuis un chemin synchrone en test, il n'y a pas de boucle."""
    etat = EtatPersistant(_db(), "test:truc", session=lambda: "live-1")
    etat.ranger_bientot({"total": 3})        # ne lève pas


@pytest.mark.asyncio
async def test_oublier_efface_la_cle():
    db = _db()
    etat = EtatPersistant(db, "test:truc", session=lambda: "live-1")
    await etat.ranger({"total": 27})

    await etat.oublier()

    assert await etat.charger() == {}
