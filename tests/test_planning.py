"""Le planning des streams.

Une image fixe, hébergée sur le serveur. Wally doit pouvoir en donner le lien
QUAND ON LUI DEMANDE — y compris hors live, où l'overlay ne s'affiche pas. Un
outil qui ne saurait répondre que pendant un stream laisserait Wally inventer
une réponse le reste du temps.
"""
import json
from unittest.mock import MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator, planning_url


def _narrator(live=True):
    return OverlayNarrator(OverlayFeed(), MagicMock(), lambda: live)


def _bot(narrator):
    return type("B", (), {"overlay_narrator": narrator})()


def test_le_lien_du_planning_est_absolu(monkeypatch):
    """Collé dans Discord, un chemin relatif ne montre rien."""
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    assert planning_url() == "https://heywally.fr/static/fichiers/planning.webp"


def test_le_lien_ne_double_pas_les_barres(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr")
    assert planning_url() == "https://heywally.fr/static/fichiers/planning.webp"


def test_le_widget_planning_publie_l_image(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    feed = OverlayFeed()
    n = OverlayNarrator(feed, MagicMock(), lambda: True)
    q = feed.subscribe()

    assert n.show_widget("planning", "voilà le programme") is not None

    ev = next(e for e in (q.get_nowait() for _ in range(q.qsize()))
              if e["type"] == "widget")
    assert ev["kind"] == "planning"
    assert ev["params"]["src"].endswith("/static/fichiers/planning.webp")


def test_hors_live_l_outil_donne_quand_meme_le_lien(monkeypatch):
    """Le cas qui justifie un outil dédié plutôt qu'un simple widget.

    `show_widget` rend None hors live. Si l'outil s'arrêtait là, Wally n'aurait
    aucune réponse à « c'est quand les streams ? » en dehors d'un direct.
    """
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    from bot.discord.handlers import run_planning_tool

    out = json.loads(run_planning_tool(_bot(_narrator(live=False)), {}))
    assert out["status"] == "ok"
    assert out["url"] == "https://heywally.fr/static/fichiers/planning.webp"
    assert out["affiche_sur_l_overlay"] is False


def test_en_live_le_lien_ET_l_affichage(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    from bot.discord.handlers import run_planning_tool

    out = json.loads(run_planning_tool(_bot(_narrator(live=True)), {}))
    assert out["status"] == "ok"
    assert out["url"].endswith("/static/fichiers/planning.webp")
    assert out["affiche_sur_l_overlay"] is True


def test_sans_overlay_branche_le_lien_reste_donne(monkeypatch):
    """L'overlay est un bonus ; le lien, lui, ne dépend de rien."""
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    from bot.discord.handlers import run_planning_tool

    out = json.loads(run_planning_tool(type("B", (), {})(), {}))
    assert out["status"] == "ok"
    assert out["url"].endswith("/static/fichiers/planning.webp")
    assert out["affiche_sur_l_overlay"] is False


@pytest.mark.asyncio
async def test_l_outil_est_offert_sur_les_deux_plateformes():
    """La parité Discord/Twitch est une règle du projet, pas une préférence.

    On interroge la liste réellement construite, et non la présence d'une
    variable : c'est ce que le modèle reçoit qui compte. Le bot factice n'a
    AUCUN service branché — le planning doit sortir quand même, puisqu'il rend
    un lien et non un affichage.
    """
    from types import SimpleNamespace

    from bot.discord.handlers import build_chat_tools as tools_discord
    from bot.twitch.handlers import build_chat_tools as tools_twitch

    # Le strict nécessaire : `build_chat_tools` lit l'id de l'owner pour décider
    # des outils réservés. Tout le reste reste absent, donc non branché.
    nu = SimpleNamespace(config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id="1")))

    noms_discord = {t["function"]["name"] for t in await tools_discord(nu, "42")}
    assert "show_planning" in noms_discord

    for depuis_chaine_home in (True, False):
        noms = {t["function"]["name"]
                for t in await tools_twitch(nu, overlay=depuis_chaine_home)}
        assert "show_planning" in noms, (
            "offert même depuis une chaîne invitée : le lien y est inoffensif"
        )


@pytest.mark.asyncio
async def test_une_chaine_invitee_n_affiche_pas_sur_l_overlay_maison(monkeypatch):
    """Le lien, oui ; l'écran d'Azraël, non — le même garde que les widgets."""
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    from bot.discord.handlers import run_planning_tool

    out = json.loads(run_planning_tool(_bot(_narrator(live=True)), {}, overlay=False))
    assert out["url"].endswith("/static/fichiers/planning.webp")
    assert out["affiche_sur_l_overlay"] is False


@pytest.mark.parametrize("widget", ["planning"])
def test_le_planning_fait_partie_des_widgets_connus(widget):
    """Le self-model dérive de cette liste : sans elle, Wally ignore qu'il sait
    montrer le planning."""
    assert widget in OverlayNarrator._WIDGETS
