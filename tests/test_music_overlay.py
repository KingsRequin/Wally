"""Le morceau en cours s'affiche à l'écran quand on le demande.

Quatrième et dernier lot du §10 : « n'importe quel viewer peut demander ce qui
passe : Wally le dit ET l'affiche sur le live ».

Deux choix qui distinguent ce widget de tous ceux ajoutés récemment :

  · Il COHABITE. L'avalanche et le spam de popups prennent l'écran seuls et
    effacent Wally ; une étiquette de titre, non — elle s'affiche pendant que la
    vie continue. C'est la question que le cliquet `wally_visible` force à se
    poser à chaque nouvel élément.

  · Il ne s'affiche QUE sur la chaîne maison. L'overlay appartient au live
    d'Azraël : une demande venue d'un salon Discord ou d'une chaîne invitée
    reçoit une réponse écrite, pas un affichage chez lui.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _narrateur(live: bool = True):
    from bot.intelligence.overlay_narrator import OverlayNarrator
    return OverlayNarrator(overlay_feed=MagicMock(), llm=MagicMock(),
                           is_live=lambda: live)


def _widget(n):
    appels = n._feed.widget.call_args_list
    return appels[-1] if appels else None


def _bot(*, etat=None, narrateur=None):
    bot = MagicMock()
    service = MagicMock()
    service.etat.return_value = etat
    service.commander = AsyncMock(return_value={"ok": True})
    bot.music = service
    bot.discord_bot.overlay_narrator = narrateur
    return bot


# ── le narrateur ────────────────────────────────────────────────────────────

def test_le_morceau_part_a_l_ecran():
    n = _narrateur()
    assert n.show_music("Numb", "Linkin Park", joue=True) is True
    appel = _widget(n)
    assert appel.args[0] == "music_now"
    assert appel.kwargs["title"] == "Numb"
    assert appel.kwargs["artist"] == "Linkin Park"


def test_hors_live_rien_ne_part():
    n = _narrateur(live=False)
    assert n.show_music("Numb", "Linkin Park", joue=True) is False
    assert _widget(n) is None


def test_sans_TITRE_on_n_affiche_pas_une_etiquette_vide():
    """Une carte vide à l'écran est pire que pas de carte."""
    n = _narrateur()
    assert n.show_music("", "Linkin Park", joue=True) is False
    assert _widget(n) is None


def test_le_MEME_morceau_ne_reclignote_pas_a_chaque_demande():
    """Cinq personnes demandent le titre en dix secondes : la carte ne doit pas
    repartir cinq fois. Wally répond quand même à chacune — c'est l'AFFICHAGE
    qu'on rationne, pas la parole."""
    n = _narrateur()
    assert n.show_music("Numb", "Linkin Park", joue=True) is True
    assert n.show_music("Numb", "Linkin Park", joue=True) is False


def test_un_AUTRE_morceau_s_affiche_tout_de_suite():
    """Le rationnement porte sur la répétition, pas sur le temps : quand la
    musique change, l'écran doit suivre."""
    n = _narrateur()
    n.show_music("Numb", "Linkin Park", joue=True)
    assert n.show_music("In The End", "Linkin Park", joue=True) is True


def test_les_textes_sont_bornes():
    """Ils viennent d'une page web et finissent en dur à l'écran."""
    n = _narrateur()
    n.show_music("x" * 500, "y" * 500, joue=True)
    k = _widget(n).kwargs
    assert len(k["title"]) <= 80 and len(k["artist"]) <= 80


# ── depuis le chat ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demander_le_titre_l_AFFICHE_aussi():
    """Le §10 : Wally le dit ET l'affiche."""
    from bot.core.music_tool import run_music_tool
    n = _narrateur()
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True},
               narrateur=n)
    out = await run_music_tool(bot, {"action": "now"}, roles=[], narrateur=n)
    assert "Numb" in out
    assert _widget(n) is not None


@pytest.mark.asyncio
async def test_sans_narrateur_la_reponse_ecrite_marche_QUAND_MEME():
    """Depuis Discord ou une chaîne invitée : on répond, on n'affiche pas chez
    Azraël. Et l'absence d'écran ne doit pas faire échouer la réponse."""
    from bot.core.music_tool import run_music_tool
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True})
    out = await run_music_tool(bot, {"action": "now"}, roles=[], narrateur=None)
    assert "Numb" in out


@pytest.mark.asyncio
async def test_quand_on_ne_sait_pas_on_n_affiche_RIEN():
    """Pas de carte « je ne sais pas » sur le live : c'est une réponse de chat."""
    from bot.core.music_tool import run_music_tool
    n = _narrateur()
    out = await run_music_tool(_bot(etat=None, narrateur=n), {"action": "now"},
                               roles=[], narrateur=n)
    assert "sais pas" in out.lower()
    assert _widget(n) is None


@pytest.mark.asyncio
async def test_un_ECRAN_en_panne_ne_casse_pas_la_reponse():
    """Le narrateur peut lever (bus overlay indisponible). La personne doit
    quand même obtenir son titre."""
    from bot.core.music_tool import run_music_tool
    n = MagicMock()
    n.show_music.side_effect = RuntimeError("bus mort")
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True})
    out = await run_music_tool(bot, {"action": "now"}, roles=[], narrateur=n)
    assert "Numb" in out


# ── les points de câblage ───────────────────────────────────────────────────

def test_l_element_est_declare_et_placable():
    from bot.core.overlay_elements import LIBELLES
    from bot.core.overlay_layout import _ORDRE_DEFAUT, ELEMENTS

    assert LIBELLES["music_now"]["nom"] and LIBELLES["music_now"]["description"]
    assert "music_now" in ELEMENTS
    assert "music_now" in _ORDRE_DEFAUT


def test_il_COHABITE_et_laisse_Wally_a_l_ecran():
    """Le choix que le cliquet `wally_visible` force à faire. Une étiquette de
    titre n'est pas un spectacle : elle n'a aucune raison d'effacer l'avatar,
    contrairement à l'avalanche ou au spam de popups."""
    from bot.core.overlay_layout import ELEMENTS

    assert ELEMENTS["music_now"]["solo"] is False
    assert ELEMENTS["music_now"]["wally_visible"] is True


def test_la_page_le_connait_et_sait_le_dessiner():
    from pathlib import Path

    statique = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
    assert '"music_now"' in (statique / "overlay_layout.js").read_text(encoding="utf-8")
    html = (statique / "overlay.html").read_text(encoding="utf-8")
    assert 'data-element="music_now"' in html
    assert "music-now" in html          # le style
    assert "music_now(" in (statique / "overlay.js").read_text(encoding="utf-8")


def test_le_bouton_d_essai_a_de_quoi_montrer():
    from bot.dashboard.routes.overlay import _ECHANTILLONS
    assert _ECHANTILLONS["music_now"]["title"]
