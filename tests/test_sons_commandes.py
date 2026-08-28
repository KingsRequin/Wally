"""Les sons que le chat déclenche — `!apero`, `!perks`, `!bonjour`…

Fonctionnalité la plus utilisée de PhantomBot : 232 usages sur 7 mois, plus que
tout le reste réuni. Rien n'est écrit en dur : le dossier décide de ce qui
existe, le nom du fichier EST le nom de la commande.
"""
import json
from unittest.mock import MagicMock

import pytest

from bot.core.sons import (
    DEFAUTS, GENRES, ReglagesSons, SoundLibrary, resoudre_commande,
)
from bot.twitch.commands.sons import _derniers, handle_son_command


@pytest.fixture
def atelier(tmp_path):
    """Un dossier de sons de commande, avec deux fichiers."""
    d = tmp_path / "commande"
    d.mkdir()
    (d / "APERO.mp3").write_bytes(b"\xff\xfb" + b"0" * 200)
    (d / "perks.mp3").write_bytes(b"\xff\xfb" + b"0" * 200)
    return tmp_path


def _regler(atelier, commande, **valeurs):
    """Écrit `reglages.json` à la main — comme l'owner le fait aujourd'hui.

    Volontairement pas de `ReglagesSons.ecrire()` : la classe est en lecture
    seule tant que l'écran qui l'appellerait n'existe pas.
    """
    fichier = atelier / "commande" / "reglages.json"
    courant = json.loads(fichier.read_text()) if fichier.is_file() else {}
    courant.setdefault(commande, {}).update(valeurs)
    fichier.write_text(json.dumps(courant), encoding="utf-8")


def test_le_genre_commande_existe():
    assert "commande" in GENRES


def test_le_nom_du_fichier_est_la_commande(atelier):
    """`APERO.mp3` répond à `!apero` — pas de table à tenir à côté du dossier."""
    assert SoundLibrary(atelier).commandes() == {
        "apero": "APERO.mp3", "perks": "perks.mp3",
    }


def test_un_dossier_sans_sons_de_commande_ne_leve_pas(tmp_path):
    assert SoundLibrary(tmp_path).commandes() == {}


# ── Réglages par son ──────────────────────────────────────────────────────────

def test_aucun_cooldown_par_defaut(tmp_path):
    """Arbitrage owner : PhantomBot imposait 120 s à tous, personne ne l'avait demandé."""
    assert DEFAUTS["cooldown"] == 0.0
    assert ReglagesSons(tmp_path).pour("apero")["cooldown"] == 0.0


def test_un_reglage_ecrit_se_relit(atelier):
    _regler(atelier, "apero", cooldown=120, volume=0.5)
    assert ReglagesSons(atelier).pour("APERO") == {"cooldown": 120.0, "volume": 0.5}


def test_le_volume_est_borne(atelier):
    """Au-delà de 2, Web Audio sature : ça s'entend comme une panne, pas un réglage."""
    _regler(atelier, "apero", volume=99, cooldown=-5)
    assert ReglagesSons(atelier).pour("apero") == {"cooldown": 0.0, "volume": 2.0}


def test_un_fichier_de_reglages_illisible_rend_les_defauts(atelier):
    (atelier / "commande" / "reglages.json").write_text("{ pas du json")
    assert ReglagesSons(atelier).pour("apero") == DEFAUTS


def test_les_reglages_vivent_dans_le_dossier_des_sons(atelier):
    """Une sauvegarde du dossier emporte les réglages avec les fichiers."""
    _regler(atelier, "apero", volume=0.3)
    assert (atelier / "commande" / "reglages.json").is_file()
    assert ReglagesSons(atelier).pour("apero")["volume"] == 0.3


# ── Le déclencheur ────────────────────────────────────────────────────────────

def _bot(atelier):
    bot = MagicMock()
    bot.dashboard_state.sons = SoundLibrary(atelier)
    bot.dashboard_state.overlay_feed = MagicMock()
    return bot


@pytest.fixture(autouse=True)
def _vide_les_cooldowns():
    _derniers.clear()
    yield
    _derniers.clear()


async def test_un_son_connu_part_sur_loverlay(atelier):
    bot = _bot(atelier)
    assert await handle_son_command(bot, "apero") is True
    event = bot.dashboard_state.overlay_feed.publish.call_args[0][0]
    assert event["type"] == "son"
    assert event["nom"] == "APERO.mp3"
    assert event["volume"] == 1.0
    # Sans `scene` : un son demandé par le chat s'entend sur TOUTES les pages.
    assert "scene" not in event


async def test_un_mot_qui_nest_pas_un_son_est_rendu_au_routeur(atelier):
    """False, pour que le message reparte vers la perception normale de Wally."""
    bot = _bot(atelier)
    assert await handle_son_command(bot, "bonjour") is False
    bot.dashboard_state.overlay_feed.publish.assert_not_called()


async def test_le_volume_regle_voyage_avec_levenement(atelier):
    _regler(atelier, "apero", volume=0.25)
    bot = _bot(atelier)
    await handle_son_command(bot, "apero")
    assert bot.dashboard_state.overlay_feed.publish.call_args[0][0]["volume"] == 0.25


async def test_le_cooldown_est_tenu_par_le_serveur(atelier):
    """Côté page, ouvrir un second overlay suffirait à le contourner."""
    _regler(atelier, "apero", cooldown=300)
    bot = _bot(atelier)
    assert await handle_son_command(bot, "apero") is True
    assert await handle_son_command(bot, "apero") is True   # traité, mais muet
    assert bot.dashboard_state.overlay_feed.publish.call_count == 1


async def test_sans_cooldown_le_son_repart_aussitot(atelier):
    bot = _bot(atelier)
    await handle_son_command(bot, "apero")
    await handle_son_command(bot, "apero")
    assert bot.dashboard_state.overlay_feed.publish.call_count == 2


async def test_le_cooldown_dun_son_ne_bloque_pas_les_autres(atelier):
    _regler(atelier, "apero", cooldown=300)
    bot = _bot(atelier)
    await handle_son_command(bot, "apero")
    assert await handle_son_command(bot, "perks") is True
    assert bot.dashboard_state.overlay_feed.publish.call_count == 2


async def test_sans_overlay_cable_rien_ne_leve(atelier):
    bot = MagicMock()
    bot.dashboard_state = None
    assert await handle_son_command(bot, "apero") is False


# ── Alias ─────────────────────────────────────────────────────────────────────

def test_un_alias_designe_le_meme_son(atelier):
    """Relevé dans les logs : `!perk` tapé 8 fois pour un son nommé `perks`."""
    _regler(atelier, "perks", alias=["perk", "perques"])
    lib, reg = SoundLibrary(atelier), ReglagesSons(atelier)
    assert resoudre_commande(lib, reg, "perk") == ("perks", "perks.mp3")
    assert resoudre_commande(lib, reg, "PERQUES") == ("perks", "perks.mp3")


def test_le_nom_du_fichier_prime_sur_un_alias(atelier):
    """Sinon un alias posé par inadvertance détourne un son existant, en silence."""
    _regler(atelier, "perks", alias=["apero"])
    assert resoudre_commande(SoundLibrary(atelier), ReglagesSons(atelier),
                             "apero") == ("apero", "APERO.mp3")


def test_un_alias_vers_un_son_supprime_ne_resout_rien(atelier):
    """Le fichier part, l'alias reste dans le JSON : il ne doit rien déclencher."""
    _regler(atelier, "disparu", alias=["fantome"])
    assert resoudre_commande(SoundLibrary(atelier), ReglagesSons(atelier),
                             "fantome") is None


def test_un_alias_revendique_deux_fois_est_stable(atelier):
    """Arbitraire mais DÉTERMINISTE : un choix au hasard serait indébogable."""
    _regler(atelier, "perks", alias=["truc"])
    _regler(atelier, "apero", alias=["truc"])
    reg = ReglagesSons(atelier)
    assert reg.alias()["truc"] == "apero"          # premier dans l'ordre alpha
    assert reg.alias() == ReglagesSons(atelier).alias()


def test_un_alias_mal_formé_est_ignore_sans_lever(atelier):
    _regler(atelier, "perks", alias="pas une liste")
    _regler(atelier, "apero", alias=["", "  ", 42, "ok"])
    assert ReglagesSons(atelier).alias() == {"ok": "apero"}


async def test_un_alias_declenche_le_son(atelier):
    _regler(atelier, "perks", alias=["perk"])
    bot = _bot(atelier)
    assert await handle_son_command(bot, "perk") is True
    assert bot.dashboard_state.overlay_feed.publish.call_args[0][0]["nom"] == "perks.mp3"


async def test_un_alias_ne_contourne_pas_le_cooldown_du_son(atelier):
    """Le piège de tout système d'alias : deux portes, un seul verrou."""
    _regler(atelier, "perks", alias=["perk"], cooldown=300)
    bot = _bot(atelier)
    assert await handle_son_command(bot, "perks") is True
    assert await handle_son_command(bot, "perk") is True     # traité, mais muet
    assert bot.dashboard_state.overlay_feed.publish.call_count == 1


async def test_un_alias_herite_du_volume_du_son(atelier):
    _regler(atelier, "perks", alias=["perk"], volume=0.4)
    bot = _bot(atelier)
    await handle_son_command(bot, "perk")
    assert bot.dashboard_state.overlay_feed.publish.call_args[0][0]["volume"] == 0.4
