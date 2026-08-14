"""Pendant un bingo, Wally doit avoir la GRILLE sous les yeux, pas juste le score.

Vécu le 2026-08-13 à 20:56 — il le dit lui-même en direct : « je n'ai pas les
cases du bingo en tête, je sais juste qu'il est ouvert avec 0/6 cases cochées ».
Son bloc d'état n'annonçait en effet que « Bingo : 0/6 cases cochées ».

Conséquence mesurée : trois lives d'affilée avec un bingo ouvert et AUCUNE case
cochée. Personne d'autre que lui ne peut cocher — l'outil est le sien.

Même patron que le pendu (`test_overlay_hangman_contexte.py`), avec la même
prudence : la consigne voyage collée à la donnée. Ici elle dit l'inverse de celle
du pendu — la grille est déjà à l'écran, rien à cacher ; ce qu'il faut rappeler,
c'est que cocher est un GESTE d'outil, pas une phrase à dire.
"""
from unittest.mock import MagicMock

from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrator():
    n = OverlayNarrator.__new__(OverlayNarrator)
    n._feed = MagicMock()
    n._live = lambda: True
    n._bingo = None
    n._goal = None
    n._poll = None
    n._hangman = None
    n.force_live_remaining = lambda: 0
    return n


def _with_bingo(done=None):
    n = _narrator()
    cells = ["Azraël blâme le ping", "un kill au couteau", "une chute bête"]
    n._bingo = {"cells": cells, "done": done or [False] * len(cells)}
    return n


def test_les_cases_sont_dans_le_contexte():
    """Sans leur texte, il n'a rien à reconnaître quand ça se produit."""
    bloc = _with_bingo().current_state_block()

    assert "Azraël blâme le ping" in bloc
    assert "un kill au couteau" in bloc
    assert "une chute bête" in bloc


def test_les_cases_cochees_se_distinguent_des_autres():
    """Sinon il recoche une case déjà faite, ou croit la grille vierge."""
    bloc = _with_bingo(done=[True, False, False]).current_state_block()

    lignes = [l for l in bloc.splitlines() if "blâme le ping" in l or "couteau" in l]
    cochee = next(l for l in lignes if "blâme le ping" in l)
    libre = next(l for l in lignes if "couteau" in l)
    assert cochee != libre
    assert cochee.strip().startswith(("0", "1", "2")) and "x" in cochee.lower()
    assert "x" not in libre.lower()


def test_le_score_reste_lisible():
    bloc = _with_bingo(done=[True, True, False]).current_state_block()
    assert "2/3" in bloc


def test_la_consigne_de_cocher_accompagne_la_grille():
    """Connaître les cases ne sert à rien s'il ignore que cocher lui revient."""
    bloc = _with_bingo().current_state_block().lower()

    assert "check" in bloc, "rien ne lui dit par quel geste cocher"
    assert "bingo" in bloc


def test_sans_partie_rien_nest_injecte():
    assert "bingo" not in _narrator().current_state_block().lower()


def test_les_cases_ne_trainent_pas_apres_la_grille():
    n = _with_bingo()
    n._bingo = None
    assert "couteau" not in n.current_state_block()
