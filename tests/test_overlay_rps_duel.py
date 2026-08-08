# tests/test_overlay_rps_duel.py
"""Le chifoumi : un duel tranché sur-le-champ, plus un vote.

Le chat votait pendant quinze secondes et Wally jouait contre la majorité. Trop
long pour ce que c'est : on demande un chifoumi comme on demande un pile ou
face. Les deux coups sont désormais tirés, l'animation joue, le vainqueur
s'affiche — et Wally garde le droit de forcer le sien.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrateur(live=True):
    n = OverlayNarrator(OverlayFeed(), AsyncMock(), lambda: live)
    n._feed = MagicMock()
    return n


def _publie(n):
    return n._feed.widget.call_args.kwargs


MOVES = ("pierre", "feuille", "ciseaux")


def test_un_duel_se_joue_d_un_coup():
    n = _narrateur()
    out = n.show_widget("rps", "allez", opponent="KingsRequin")

    assert out is not None
    params = _publie(n)
    assert params["mine"] in MOVES
    assert params["theirs"] in MOVES
    assert params["opponent"] == "KingsRequin"
    assert params["outcome"] in ("wally", "opponent", "draw")


def test_le_verdict_suit_les_regles_du_jeu():
    n = _narrateur()
    for _ in range(40):                       # les tirages varient, la règle non
        n.show_widget("rps", "", opponent="X")
        p = _publie(n)
        mine, theirs, outcome = p["mine"], p["theirs"], p["outcome"]
        if mine == theirs:
            assert outcome == "draw"
        elif (mine, theirs) in (("pierre", "ciseaux"), ("feuille", "pierre"),
                                ("ciseaux", "feuille")):
            assert outcome == "wally"
        else:
            assert outcome == "opponent"


def test_wally_peut_forcer_son_coup():
    """Le tirage se fait côté serveur : c'est ce qui lui permet de tricher."""
    n = _narrateur()
    n.show_widget("rps", "je prends pierre", move="pierre", opponent="X")
    assert _publie(n)["mine"] == "pierre"


def test_un_coup_impose_invalide_retombe_sur_le_hasard():
    n = _narrateur()
    n.show_widget("rps", "", move="lance-flammes", opponent="X")
    assert _publie(n)["mine"] in MOVES


def test_sans_adversaire_nomme_on_joue_quand_meme():
    """Le nom vient du chat ou du vocal ; son absence ne bloque pas le duel."""
    n = _narrateur()
    assert n.show_widget("rps", "") is not None
    assert _publie(n)["opponent"]


def test_rien_hors_live():
    n = _narrateur(live=False)
    assert n.show_widget("rps", "", opponent="X") is None
    n._feed.widget.assert_not_called()


def test_le_resultat_est_rendu_a_l_appelant():
    """Wally doit pouvoir commenter le duel qu'il vient de provoquer."""
    n = _narrateur()
    out = n.show_widget("rps", "", move="ciseaux", opponent="Azra")
    assert out["mine"] == "ciseaux"
    assert out["opponent"] == "Azra"
    assert out["outcome"] in ("wally", "opponent", "draw")


def test_deux_duels_de_suite_sont_permis():
    """Plus de manche à clore : rien ne reste ouvert entre deux demandes."""
    n = _narrateur()
    assert n.show_widget("rps", "", opponent="X") is not None
    assert n.show_widget("rps", "", opponent="Y") is not None
