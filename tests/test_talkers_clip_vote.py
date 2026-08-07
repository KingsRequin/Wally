"""Top des bavards, alerte clip, votes prononcés en vocal."""
from unittest.mock import MagicMock

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _n(live=True):
    feed = OverlayFeed()
    n = OverlayNarrator(feed, MagicMock(), lambda: live)
    n._live()          # entrée en live : c'est là que le compteur repart à zéro
    return n, feed


def _widgets(q):
    return [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"]


# ── les plus bavards ──

def test_le_classement_sort_les_trois_premiers():
    n, feed = _n()
    n._talkers.update({"alice": 5, "bob": 3, "carol": 7, "dan": 1})
    q = feed.subscribe()
    out = n.show_talkers()
    assert [r[0] for r in out["rows"]] == ["carol", "alice", "bob"]
    assert len(_widgets(q)[-1]["params"]["rows"]) == 3


def test_pas_de_classement_sans_personne():
    n, _ = _n()
    assert n.show_talkers() is None


def test_pas_de_classement_hors_live():
    n, _ = _n(live=False)
    n._talkers.update({"alice": 3})
    assert n.show_talkers() is None


def test_un_nouveau_live_repart_de_zero():
    n, _ = _n()
    n._talkers.update({"alice": 5})
    n.reset_live()
    assert n.show_talkers() is None


# ── clip ──

def test_un_clip_est_signale_avec_son_auteur():
    """C'est celui qui clippe qu'on récompense, pas le clip."""
    n, feed = _n()
    q = feed.subscribe()
    assert n.show_clip("le fail du siècle", "Kassandre") is True
    p = _widgets(q)[-1]["params"]
    assert p["author"] == "Kassandre" and p["title"] == "le fail du siècle"


def test_pas_de_clip_hors_live():
    n, _ = _n(live=False)
    assert n.show_clip("x", "y") is False


# ── votes prononcés ──

def test_un_chiffre_dit_a_l_oral_compte():
    n, _ = _n()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    assert n.count_spoken_vote("Azraël", "bah moi je dis deux") is True
    assert n._poll["votes"]["azraël"] == 1


def test_oui_et_non_valent_un_et_deux():
    n, _ = _n()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    n.count_spoken_vote("Rina", "oui carrément")
    n.count_spoken_vote("Malef", "non")
    assert n._poll["votes"] == {"rina": 0, "malef": 1}


def test_le_libelle_de_l_option_compte_aussi():
    n, _ = _n()
    n.start_poll("quelle map ?", ["Olympus", "Storm Point"], seconds=30)
    assert n.count_spoken_vote("Taki", "olympus") is True
    assert n._poll["votes"]["taki"] == 0


def test_une_phrase_longue_n_est_pas_un_vote():
    """« on part sur la map deux mille douze » parle d'autre chose."""
    n, _ = _n()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    assert n.count_spoken_vote("Bob", "on part sur la map deux mille douze là bas") is False


def test_un_vote_hors_options_ne_compte_pas():
    n, _ = _n()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    assert n.count_spoken_vote("Bob", "quatre") is False


def test_sans_sondage_rien_n_est_compte():
    n, _ = _n()
    assert n.count_spoken_vote("Bob", "deux") is False


def test_un_vote_apres_l_echeance_est_ignore():
    import time as _t
    n, _ = _n()
    n.start_poll("chocolat ?", ["Oui", "Non"], seconds=30)
    n._poll["ends_at"] = _t.monotonic() - 1
    assert n.count_spoken_vote("Bob", "deux") is False
