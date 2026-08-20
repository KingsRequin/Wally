# tests/test_twitch_visite_persistance.py
"""Une visite de chaîne invitée survit au redémarrage (2026-08-20).

Même motif que le pari sur les kills, en plus discret. `_active_visits` liait le
nom de la chaîne à l'identifiant de sa ligne `twitch_visits`, et vivait en RAM.
Après un rebuild, ce lien était perdu : la ligne restait ouverte
(`left_at IS NULL`) POUR TOUJOURS, jamais finalisée, donc jamais résumée par le
LLM et jamais reprise dans le journal quotidien.

Rien à ranger de neuf ici — la table portait déjà tout. Il manquait la RELECTURE
au démarrage.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


class _Db:
    """La table `twitch_visits`, en mémoire."""

    def __init__(self, lignes=None):
        self.lignes = list(lignes or [])

    async def visites_ouvertes(self):
        return [dict(v) for v in self.lignes if v.get("left_at") is None]


@pytest.mark.asyncio
async def test_une_visite_ouverte_est_reprise_au_demarrage():
    from bot.twitch.bot import reprendre_visites

    db = _Db([{"id": 7, "channel": "azrael_ttv", "joined_at": 1000.0,
               "msg_count": 12, "left_at": None}])

    reprises = await reprendre_visites(db, ["azrael_ttv"])

    assert reprises["azrael_ttv"]["visit_id"] == 7
    assert reprises["azrael_ttv"]["joined_at"] == 1000.0
    # Le compte déjà en base repart de là : le perdre effacerait la moitié de
    # la visite du résumé.
    assert reprises["azrael_ttv"]["msg_count"] == 12


@pytest.mark.asyncio
async def test_une_visite_d_une_chaine_qu_on_a_quittee_est_ignoree():
    """Elle n'est plus dans la config : sa ligne ne nous regarde plus, et la
    reprendre ferait croire à une visite en cours qui n'existe pas."""
    from bot.twitch.bot import reprendre_visites

    db = _Db([{"id": 7, "channel": "ancienne", "joined_at": 1000.0,
               "msg_count": 3, "left_at": None}])

    assert await reprendre_visites(db, ["azrael_ttv"]) == {}


@pytest.mark.asyncio
async def test_une_visite_deja_close_n_est_pas_rouverte():
    from bot.twitch.bot import reprendre_visites

    db = _Db([{"id": 7, "channel": "azrael_ttv", "joined_at": 1000.0,
               "msg_count": 3, "left_at": 2000.0}])

    assert await reprendre_visites(db, ["azrael_ttv"]) == {}


@pytest.mark.asyncio
async def test_une_base_en_erreur_ne_bloque_pas_le_demarrage():
    from bot.twitch.bot import reprendre_visites

    db = MagicMock()
    db.visites_ouvertes = AsyncMock(side_effect=RuntimeError("base verrouillée"))

    assert await reprendre_visites(db, ["azrael_ttv"]) == {}


@pytest.mark.asyncio
async def test_sans_base_rien_ne_leve():
    from bot.twitch.bot import reprendre_visites

    assert await reprendre_visites(None, ["azrael_ttv"]) == {}


@pytest.mark.asyncio
async def test_le_compte_de_messages_est_ecrit_au_fil_de_l_eau():
    """Sinon la reprise repartirait toujours de zéro : la ligne ne porte le
    compte qu'à la clôture, qui est précisément ce qui n'arrive pas."""
    from bot.db.mixins.social import SocialMixin

    assert hasattr(SocialMixin, "bump_twitch_visit_messages")
