"""Le jour où plus rien ne s'écrit, quelqu'un doit l'apprendre.

Vécu le 2026-08-30 : de 11 h 43 à 21 h 54, toute écriture en base a échoué en
`OperationalError('database is locked')` — coûts, état émotionnel, profils
Apex, compteur de messages, snapshots. Dix heures. Seul le redémarrage y a mis
fin. Rien n'a prévenu : chaque site attrapait SON échec en WARNING et
continuait, et personne ne lit 1 756 lignes de warning.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlite3 import OperationalError

from bot.core.veille_verrou import VeilleVerrou


def _verrou() -> OperationalError:
    return OperationalError("database is locked")


@pytest.fixture
def notifications():
    n = AsyncMock()
    n.send = AsyncMock(return_value=True)
    return n


async def test_un_echec_isole_ne_reveille_personne(notifications):
    """Un verrou passager est NORMAL : `busy_timeout` en absorbe tous les jours."""
    veille = VeilleVerrou(notifications, seuil=3)
    await veille.constater(_verrou())
    await veille.constater(None)
    notifications.send.assert_not_awaited()


async def test_le_seuil_franchi_alerte_une_seule_fois(notifications):
    """On alerte au FRANCHISSEMENT, pas à chaque tour : sinon on l'ignore."""
    veille = VeilleVerrou(notifications, seuil=3)
    for _ in range(6):
        await veille.constater(_verrou())
    assert notifications.send.await_count == 1
    assert "verrou" in notifications.send.await_args[0][0].lower()


async def test_le_retour_a_la_normale_se_dit_et_rearme(notifications):
    """Sans réarmement, un second épisode passerait inaperçu."""
    veille = VeilleVerrou(notifications, seuil=2)
    await veille.constater(_verrou())
    await veille.constater(_verrou())
    await veille.constater(None)
    assert notifications.send.await_count == 2
    assert "revenue" in notifications.send.await_args[0][0].lower()

    for _ in range(2):
        await veille.constater(_verrou())
    assert notifications.send.await_count == 3


async def test_une_panne_qui_n_est_pas_un_verrou_ne_compte_pas(notifications):
    """Une table absente ou un disque plein est un AUTRE problème.

    Le compteur ne doit pas mélanger les deux : trois pannes différentes
    d'affilée ne font pas un verrou, et l'annoncer comme tel enverrait le
    diagnostic sur une fausse piste.
    """
    veille = VeilleVerrou(notifications, seuil=2)
    await veille.constater(OperationalError("no such table: atomic_facts"))
    await veille.constater(ValueError("autre chose"))
    await veille.constater(OperationalError("no such table: atomic_facts"))
    notifications.send.assert_not_awaited()


async def test_sans_service_de_notification_la_veille_tient_quand_meme():
    """`notifications` est optionnel au démarrage — la veille ne doit pas planter."""
    veille = VeilleVerrou(None, seuil=1)
    await veille.constater(_verrou())   # ne lève pas
    assert veille.alerte_posee is True
