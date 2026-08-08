"""Pendant un pendu, Wally doit avoir la partie sous les yeux.

Vécu le 2026-08-08 : pendu lancé, quelqu'un demande un autre indice — Wally ne
sait pas répondre. Son contexte ne disait que « N lettres restent, M essais » :
ni le mot, ni l'indice, ni les lettres déjà proposées.

Choix de l'owner : le mot ENTRE dans le contexte, avec la consigne de ne jamais
l'écrire. Le masque et les lettres ratées sont de toute façon affichés à l'écran,
donc publics ; c'est le mot et l'indice qui sont l'ajout sensible.
"""
from unittest.mock import MagicMock

import pytest

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


def _with_game(**over):
    n = _narrator()
    n._hangman = {
        "word": "ordinateur",
        "display": "ordinateur",
        "hint": "ça chauffe",
        "found": {"o", "r"},
        "missed": ["s", "z"],
        **over,
    }
    return n


def test_le_mot_et_lindice_sont_dans_le_contexte():
    """Sans eux, « donne un autre indice » restait sans réponse possible."""
    bloc = _with_game().current_state_block()

    assert "ordinateur" in bloc
    assert "ça chauffe" in bloc


def test_la_consigne_de_ne_pas_le_dire_accompagne_le_mot():
    """Le mot part dans tous ses prompts : la consigne voyage avec lui."""
    bloc = _with_game().current_state_block()

    assert "jamais" in bloc.lower()


def test_letat_de_la_partie_est_lisible():
    """Lettres trouvées, ratées, essais restants : de quoi commenter juste."""
    bloc = _with_game().current_state_block()

    assert "o r" in bloc.lower() or "o, r" in bloc.lower()   # trouvées
    assert "s" in bloc.lower() and "z" in bloc.lower()       # ratées
    assert "4" in bloc      # 6 - 2 ratés = 4 essais restants


def test_le_masque_montre_ce_que_le_chat_voit():
    """Le masque est déjà à l'écran : le donner ne révèle rien de plus, et c'est
    ce qui permet à Wally de parler de la partie en cours."""
    bloc = _with_game().current_state_block()

    # « ordinateur » avec o et r trouvés, les autres masquées
    assert "O R _ _ _ _ _ _ _ R" in bloc


def test_sans_partie_rien_nest_injecte():
    assert "pendu" not in _narrator().current_state_block().lower()


def test_le_mot_ne_sort_pas_quand_la_partie_est_finie():
    """Une partie terminée met `_hangman` à None — le mot ne doit pas traîner."""
    n = _with_game()
    n._hangman = None

    assert "ordinateur" not in n.current_state_block()


@pytest.mark.parametrize("missed,restants", [([], 6), (["a"], 5), (["a", "b", "c"], 3)])
def test_les_essais_restants_suivent_les_erreurs(missed, restants):
    bloc = _with_game(missed=missed).current_state_block()
    assert f"{restants} essai" in bloc
