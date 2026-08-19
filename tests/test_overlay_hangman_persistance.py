# tests/test_overlay_hangman_persistance.py
"""Le pendu reste à l'écran tant qu'on y joue, et le redemander ne le rejoue pas.

Constaté en direct le 2026-08-08 : la grille disparaissait au bout de dix
secondes — la durée d'un résultat qu'on lit, pas d'une partie qu'on joue — et
demander à la revoir repartait sur un nouveau mot, effaçant les lettres déjà
trouvées.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrateur():
    n = OverlayNarrator(OverlayFeed(), AsyncMock(), lambda: True)
    n._feed = MagicMock()
    return n


def _dernier(n, kind="hangman"):
    """Le dernier widget publié de ce type."""
    for appel in reversed(n._feed.widget.call_args_list):
        if appel.args and appel.args[0] == kind:
            return appel.kwargs
    return None


def test_une_partie_en_cours_reste_affichee():
    n = _narrateur()
    n.start_hangman("fuse", "une légende")
    assert _dernier(n)["sticky"] is True


def test_le_redemander_ne_relance_pas_la_partie():
    """« remontre le pendu » doit remontrer LA partie, pas en commencer une."""
    n = _narrateur()
    n.start_hangman("fuse", "une légende")
    n._count_hangman("kingsrequin", "f")
    trouvees = set(n._hangman["found"])

    out = n.show_widget("hangman", "on en est là")

    assert out is not None
    assert n._hangman["found"] == trouvees, "les lettres trouvées ont été perdues"
    assert n._hangman["word"] == "fuse", "le mot a changé"


def test_le_redemander_sans_partie_ne_montre_rien():
    n = _narrateur()
    assert n.show_widget("hangman", "vas-y") is None


def test_un_mot_fourni_lance_bien_une_nouvelle_partie():
    n = _narrateur()
    assert n.show_widget("hangman", "allez", word="octane", sollicite=True) is not None
    assert n._hangman["word"] == "octane"


def test_la_fin_de_partie_ne_reste_pas_a_l_ecran():
    """Gagné ou perdu, la grille se lit puis s'efface comme un résultat."""
    n = _narrateur()
    n.start_hangman("sol", "petit mot")       # trois lettres, le minimum accepté
    for lettre in "sol":
        n._count_hangman("kingsrequin", lettre)
    assert n._hangman is None, "la partie devait être gagnée"
    assert not _dernier(n).get("sticky")


def test_une_partie_perdue_ne_reste_pas_non_plus():
    n = _narrateur()
    n.start_hangman("fuse", "une légende")
    for lettre in "bcdgkm":                    # six fautes
        n._count_hangman("kingsrequin", lettre)
    assert n._hangman is None
    assert not _dernier(n).get("sticky")


def test_on_peut_toujours_l_annuler():
    n = _narrateur()
    n.start_hangman("fuse", "une légende")
    result = n.cancel("pendu")
    assert result.get("cancelled")
    assert n._hangman is None


def test_une_partie_en_cours_survit_a_une_reconnexion_obs():
    """OBS coupe et rouvre sa source SSE : la grille doit revenir telle quelle."""
    from bot.core.overlay_feed import OverlayFeed

    feed = OverlayFeed()
    n = OverlayNarrator(feed, AsyncMock(), lambda: True)
    n.start_hangman("fuse", "une légende")

    rejoues = [e for e in feed.recent() if e.get("kind") == "hangman"
               or (e.get("params") or {}).get("mask")]
    assert rejoues, "la partie en cours n'est pas rejouée à la reconnexion"
