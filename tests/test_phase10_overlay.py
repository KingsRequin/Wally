# tests/test_phase10_overlay.py
"""Phase 10 de l'audit du 2026-08-10 : overlay.

M19 — une grille de bingo complète n'était jamais close : réinjectée dans
      chaque prompt et réaffichée toutes les 10 min pour le reste du live.
M20 — `reset_live()` ne vidait pas le tampon du flux : un pendu `sticky` du
      live précédent revenait à l'écran, sans minuteur.
M21 — `redact()` posé sur `say()` mais pas sur `widget()` : le mot du pendu
      pouvait sortir par un `pinned`, un `counter`, un sondage ou un bingo.
M22 — un nouveau sondage était mis à jour « en place », avec la question et
      les intitulés de l'ancien.
"""
from pathlib import Path

from unittest.mock import MagicMock

from bot.core.overlay_feed import OverlayFeed


# ────────────────────────────── M21 ──────────────────────────────
def _feed():
    f = OverlayFeed.__new__(OverlayFeed)
    f._buffer = __import__("collections").deque(maxlen=50)
    f.publish = MagicMock()
    return f


def test_le_mot_du_pendu_ne_sort_pas_par_un_widget():
    from bot.core import secret_guard

    secret_guard.guard_secret("banane")
    try:
        f = _feed()
        f.widget("pinned", text="le mot est banane")
        params = f.publish.call_args.args[0]["params"]
        assert "banane" not in params["text"]
    finally:
        secret_guard.release_secret("banane")


def test_le_mot_ne_sort_pas_non_plus_par_une_liste():
    """Les cases de bingo et les intitulés d'un sondage sont des listes."""
    from bot.core import secret_guard

    secret_guard.guard_secret("banane")
    try:
        f = _feed()
        f.widget("bingo", cells=["une case", "banane", "autre"])
        cells = f.publish.call_args.args[0]["params"]["cells"]
        assert not any("banane" in c for c in cells)
    finally:
        secret_guard.release_secret("banane")


def test_les_nombres_traversent_intacts():
    """`redact` sur un entier le transformerait en chaîne."""
    from bot.core.overlay_feed import _redact_params

    assert _redact_params({"duration": 12, "full": True, "tally": [3, 1]}) == {
        "duration": 12, "full": True, "tally": [3, 1],
    }


def test_les_structures_imbriquees_sont_traitees():
    from bot.core import secret_guard

    secret_guard.guard_secret("banane")
    try:
        from bot.core.overlay_feed import _redact_params

        out = _redact_params({"a": {"b": ["banane"]}})
        assert "banane" not in str(out)
    finally:
        secret_guard.release_secret("banane")


# ────────────────────────────── M19 / M20 ──────────────────────────────
def _narrateur():
    from bot.intelligence.overlay_narrator import OverlayNarrator

    n = OverlayNarrator.__new__(OverlayNarrator)
    n._feed = MagicMock()
    n._bingo = None
    n._bingo_reminded_at = 0.0
    n._greeted = set()
    n._poll = None
    n._goal = None
    n._recent_bubbles = MagicMock()
    n._talkers = MagicMock()
    n._hangman = None
    n._release_hangman_secret = MagicMock()
    return n


def test_une_grille_complete_est_close():
    n = _narrateur()
    n._bingo = {"cells": ["a", "b"], "done": [True, False]}
    out = n.check_bingo(1)          # coche la dernière case
    assert out["full"] is True
    assert n._bingo is None, "la grille pleine reste injectée dans chaque prompt"


def test_une_grille_incomplete_reste_en_jeu():
    n = _narrateur()
    n._bingo = {"cells": ["a", "b", "c"], "done": [False, False, False]}
    out = n.check_bingo(1)
    assert out["full"] is False
    assert n._bingo is not None


def test_le_reset_vide_le_tampon_du_flux():
    n = _narrateur()
    n.reset_live()
    n._feed.clear.assert_called_once()


def test_un_flux_recalcitrant_ne_bloque_pas_le_demarrage_du_live():
    n = _narrateur()
    n._feed.clear.side_effect = RuntimeError("SSE mort")
    n.reset_live()                  # ne doit pas lever
    assert n._hangman is None


def test_le_mot_reste_masque_pendant_la_partie_mais_est_revele_a_la_fin():
    """Le filet couvre maintenant les widgets : la révélation finale doit donc
    lever le secret AVANT de publier, sinon elle affiche « […] »."""
    from bot.core import secret_guard
    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    # Registre global : un autre test peut y avoir laissé un mot, qui masquerait
    # une partie du nôtre (« fuse » → « […]e »).
    secret_guard.clear_secrets()
    feed = OverlayFeed()
    n = OverlayNarrator(feed, MagicMock(), lambda: True, min_interval_s=0)
    n.start_hangman("fusee")
    q = feed.subscribe()

    n._count_hangman("alice", "f")
    en_cours = [e for e in _vider(q) if e.get("type") == "widget"][-1]
    assert "fusee" not in str(en_cours["params"])

    for lettre in "use":
        n._count_hangman("alice", lettre)
    final = [e for e in _vider(q) if e.get("type") == "widget"][-1]
    assert final["params"]["won"] is True
    assert final["params"]["word"] == "fusee"


def _vider(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except Exception:
            return out


# ────────────────────────────── M22 ──────────────────────────────
def test_un_nouveau_sondage_nest_pas_mis_a_jour_en_place():
    src = Path("bot/dashboard/static/overlay.js").read_text(encoding="utf-8")
    # La signature est posée à la construction…
    assert "box.dataset.signature = JSON.stringify(" in src
    # …et comparée avant de choisir la mise à jour en place.
    assert "if (poll.dataset.signature !== signature) poll = null;" in src
