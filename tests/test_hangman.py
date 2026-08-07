"""Pendu — le chat propose des lettres.

Le mot ne doit JAMAIS partir vers l'overlay tant qu'il n'est pas terminé : les
viewers le liraient à l'écran et le jeu n'aurait aucun intérêt.
"""
from unittest.mock import MagicMock

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _n(live=True):
    feed = OverlayFeed()
    return OverlayNarrator(feed, MagicMock(), lambda: live), feed


def _events(feed_queue):
    return [e for e in (feed_queue.get_nowait() for _ in range(feed_queue.qsize()))
            if e["type"] == "widget"]


def test_le_mot_n_est_jamais_publie_avant_la_fin():
    n, feed = _n()
    q = feed.subscribe()
    n.start_hangman("fusée")
    ev = _events(q)[0]
    assert ev["params"]["word"] == ""
    assert "".join(ev["params"]["mask"]) == ""     # tout est masqué


def test_une_lettre_trouvee_se_revele():
    n, feed = _n()
    n.start_hangman("fusée")
    q = feed.subscribe()
    n._count_hangman("alice", "u")
    ev = _events(q)[-1]
    assert ev["params"]["mask"][1] == "u"
    assert ev["params"]["misses"] == 0


def test_les_accents_sont_ignores():
    """« fusée » se devine avec un « e » : le chat ne tape pas les accents."""
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "e")
    assert "e" in n._hangman["found"]


def test_une_lettre_absente_compte_une_faute():
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "z")
    assert n._hangman["missed"] == ["z"]


def test_une_lettre_deja_proposee_ne_recompte_pas():
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "z")
    n._count_hangman("bob", "z")
    assert n._hangman["missed"] == ["z"]


def test_un_mot_entier_n_est_pas_une_proposition():
    """Sinon chaque message du chat proposerait des lettres."""
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "salut les gars")
    assert not n._hangman["found"] and not n._hangman["missed"]


def test_la_partie_est_gagnee_quand_tout_est_trouve():
    n, feed = _n()
    n.start_hangman("fusee")
    q = feed.subscribe()
    for lettre in "fuse":
        n._count_hangman("alice", lettre)
    ev = _events(q)[-1]
    assert ev["params"]["won"] is True
    assert ev["params"]["word"] == "fusee"        # révélé à la fin seulement
    assert n._hangman is None


def test_la_partie_est_perdue_a_six_fautes():
    n, feed = _n()
    n.start_hangman("fusee")
    q = feed.subscribe()
    for lettre in "bcdgkl":
        n._count_hangman("alice", lettre)
    ev = _events(q)[-1]
    assert ev["params"]["lost"] is True and ev["params"]["misses"] == 6
    assert n._hangman is None


def test_un_mot_trop_court_est_refuse():
    n, _ = _n()
    assert n.start_hangman("ok") is False


def test_un_mot_trop_long_est_refuse():
    """Au-delà, les cases débordent du widget."""
    n, _ = _n()
    assert n.start_hangman("anticonstitutionnellement") is False


def test_pas_de_partie_hors_live():
    n, _ = _n(live=False)
    assert n.start_hangman("fusee") is False


def test_un_nouveau_live_efface_la_partie():
    n, _ = _n()
    n.start_hangman("fusee")
    n.reset_live()
    assert n._hangman is None


def test_l_espace_d_un_mot_compose_reste_visible():
    n, feed = _n()
    q = feed.subscribe()
    n.start_hangman("rocket league")
    ev = _events(q)[0]
    assert " " in ev["params"]["mask"]
