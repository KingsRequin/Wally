"""Chifoumi — le chat vote, Wally joue contre la majorité."""
import time

import pytest
from unittest.mock import MagicMock

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _n(live=True):
    feed = OverlayFeed()
    return OverlayNarrator(feed, MagicMock(), lambda: live), feed


def test_une_manche_s_ouvre():
    n, _ = _n()
    assert n.show_widget("rps", "", seconds=15) is not None


def test_pas_de_manche_hors_live():
    n, _ = _n(live=False)
    assert n.show_widget("rps", "") is None


def test_une_seule_manche_a_la_fois():
    """Deux manches en parallèle rendraient les votes ininterprétables."""
    n, _ = _n()
    n.start_rps(15)
    assert n.start_rps(15) is False


def test_le_chat_vote_par_nom_ou_par_numero():
    n, _ = _n()
    n.start_rps(30)
    n._count_rps("alice", "pierre")
    n._count_rps("bob", "1")
    assert n._rps["votes"] == {"alice": "pierre", "bob": "pierre"}


def test_un_mot_noye_dans_une_phrase_ne_vote_pas():
    """« la pierre du temple » n'est pas un vote."""
    n, _ = _n()
    n.start_rps(30)
    n._count_rps("alice", "regarde la pierre du temple")
    assert n._rps["votes"] == {}


def test_un_seul_vote_par_personne_mais_changement_permis():
    n, _ = _n()
    n.start_rps(30)
    n._count_rps("alice", "pierre")
    n._count_rps("alice", "ciseaux")
    assert n._rps["votes"] == {"alice": "ciseaux"}


def test_les_votes_apres_l_echeance_sont_ignores():
    n, _ = _n()
    n.start_rps(30)
    n._rps["ends_at"] = time.monotonic() - 1
    n._count_rps("alice", "pierre")
    assert n._rps["votes"] == {}


@pytest.mark.parametrize("chat_move,mine,attendu", [
    ("pierre", "feuille", "wally"),
    ("feuille", "pierre", "chat"),
    ("ciseaux", "ciseaux", "draw"),
    ("pierre", "ciseaux", "chat"),
])
def test_le_verdict_suit_les_regles(chat_move, mine, attendu):
    n, _ = _n()
    n.start_rps(30)
    n._count_rps("alice", chat_move)
    assert n.close_rps(mine)["outcome"] == attendu


def test_wally_peut_imposer_son_coup():
    """C'est ce qui lui permet de tricher — assumé."""
    n, _ = _n()
    n.start_rps(30)
    n._count_rps("alice", "pierre")
    assert n.close_rps("feuille")["mine"] == "feuille"


def test_une_manche_sans_vote_se_clot_proprement():
    n, feed = _n()
    n.start_rps(30)
    q = feed.subscribe()
    assert n.close_rps()["outcome"] == "void"
    ev = [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"][-1]
    assert ev["params"]["phase"] == "void"


def test_clore_sans_manche_ne_fait_rien():
    n, _ = _n()
    assert n.close_rps() is None


def test_un_nouveau_live_efface_la_manche():
    n, _ = _n()
    n.start_rps(30)
    n.reset_live()
    assert n._rps is None
