"""La grammaire des couleurs d'annonce, tenue chemin par chemin.

Douze endroits publient dans le chat sans qu'on ait rien demandé à Wally.
Twitch n'accepte que quatre teintes plus `primary` : une couleur par CHEMIN
reviendrait à réutiliser les mêmes au hasard, et le violet du duel, celui du
pendu et celui du remboursement ne diraient plus rien. Elles disent une
INTENTION — ça commence, ça a réussi, ça a raté — exactement comme les accents
de l'overlay.

Ce fichier tient cette règle. Sans lui, un chemin ajouté demain repartirait en
violet par défaut, ce qui ne se voit pas : l'annonce part, elle est juste muette
sur ce qu'elle raconte.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.api import TwitchAPI


def _bot():
    bot = MagicMock()
    bot.twitch_api.send_automatic = AsyncMock(return_value=True)
    bot.twitch_api.COULEUR_ECHEC = TwitchAPI.COULEUR_ECHEC
    bot.twitch_api.COULEUR_REUSSITE = TwitchAPI.COULEUR_REUSSITE
    bot.twitch_api.COULEUR_DEBUT = TwitchAPI.COULEUR_DEBUT
    return bot


def _couleur_envoyee(bot) -> str:
    return bot.twitch_api.send_automatic.await_args.kwargs.get("color", "")


# ── Les cinq remboursements ──────────────────────────────────────────────

@pytest.mark.parametrize("module", [
    "bot.twitch.events.tts_viewer",
    "bot.twitch.events.im_out",
    "bot.twitch.events.virus_popups",
    "bot.twitch.events.humeur",
])
async def test_un_remboursement_sort_en_orange(module):
    """Le viewer a payé et n'a pas eu ce qu'il attendait. C'est la seule
    annonce où il PERD quelque chose : il doit la repérer dans un chat qui
    défile, sans avoir à lire chaque ligne."""
    import importlib

    m = importlib.import_module(module)
    bot = _bot()
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    await m._rendre(bot, "bob", "rw1", "rd1", "un motif")
    assert _couleur_envoyee(bot) == TwitchAPI.COULEUR_ECHEC


async def test_le_remboursement_des_recompenses_sort_en_orange():
    from bot.twitch.events import redemptions

    bot = _bot()
    await redemptions._dire(bot, "bob", "les points reviennent")
    assert _couleur_envoyee(bot) == TwitchAPI.COULEUR_ECHEC


# ── Les issues ───────────────────────────────────────────────────────────

def test_une_issue_inconnue_ne_choisit_pas_de_couleur():
    """Le violet neutre est le repli, jamais une couleur prise au hasard : une
    issue mal orthographiée doit perdre le REPÈRE, pas mentir sur le résultat."""
    from bot.twitch.jeu_announce import couleur_de

    assert couleur_de("reussite") == TwitchAPI.COULEUR_REUSSITE
    assert couleur_de("echec") == TwitchAPI.COULEUR_ECHEC
    assert couleur_de("") == ""
    assert couleur_de("gagné") == ""


# ── Les étapes du duel ───────────────────────────────────────────────────

def _evt(type_: str, **donnees):
    e = MagicMock()
    e.type = type_
    e.donnees = donnees
    return e


@pytest.mark.parametrize("type_,attendu", [
    ("duel_ouvert", TwitchAPI.COULEUR_DEBUT),
    ("manche_debut", TwitchAPI.COULEUR_DEBUT),
    ("recommence", TwitchAPI.COULEUR_DEBUT),
    ("manche_fin", ""),
    ("refus", TwitchAPI.COULEUR_ECHEC),
    ("abandon", TwitchAPI.COULEUR_ECHEC),
    ("compte_introuvable", TwitchAPI.COULEUR_ECHEC),
    ("rattrapage", TwitchAPI.COULEUR_ECHEC),
])
def test_chaque_etape_du_duel_a_son_intention(type_, attendu):
    from bot.twitch.duel_announce import couleur_etape

    assert couleur_etape(_evt(type_)) == attendu


def test_le_verdict_se_lit_du_point_de_vue_du_duelliste():
    """C'est le VIEWER qui a payé ses points, c'est lui que l'annonce concerne.
    Azraël vainqueur sort donc en orange, et une égalité n'est ni l'un ni
    l'autre."""
    from bot.twitch.duel_announce import couleur_etape

    assert couleur_etape(_evt("verdict", gagnant="bob")) == TwitchAPI.COULEUR_REUSSITE
    assert couleur_etape(_evt("verdict", gagnant="azrael")) == TwitchAPI.COULEUR_ECHEC
    assert couleur_etape(_evt("verdict", gagnant=None)) == ""


# ── La grammaire elle-même ───────────────────────────────────────────────

def test_les_couleurs_dintention_sont_toutes_acceptees_par_twitch():
    """Une valeur hors liste vaut un 400, donc PAS d'annonce du tout — ou, avec
    le repli de `send_announcement`, une annonce qui perd sa couleur en
    silence. Les deux se remarquent en live, jamais avant."""
    for couleur in (TwitchAPI.COULEUR_DEBUT, TwitchAPI.COULEUR_REUSSITE,
                    TwitchAPI.COULEUR_ECHEC, TwitchAPI.AUTO_COLOR):
        assert couleur in TwitchAPI.ANNOUNCE_COLORS


def test_les_trois_intentions_sont_distinctes():
    """Deux intentions de la même teinte, c'est une grammaire qui ne dit plus
    rien — le défaut exact qu'on corrige."""
    assert len({TwitchAPI.COULEUR_DEBUT, TwitchAPI.COULEUR_REUSSITE,
                TwitchAPI.COULEUR_ECHEC, TwitchAPI.AUTO_COLOR}) == 4
