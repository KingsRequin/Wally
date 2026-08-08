# tests/test_twitch_relance.py
"""Relancer Wally juste après sa réponse, sur Twitch.

Vu en live le 2026-08-08, sur azrael_ttv :

    15:42:11  Wally      « Ciseaux contre ma feuille, bien joué. »
    15:42:17  KingsRequin « @WallyTeBully encore une partie »   ← ignoré

Six secondes, `cooldown_seconds: 10` : `is_on_cooldown` a renvoyé True et le
handler est sorti sans un mot de log. La mention était pourtant là, et c'était
une réponse directe au message de Wally.

Le cooldown protège des inconnus qui mitraillent une chaîne publique — pas d'une
conversation en cours. Wally accorde donc UNE relance après chaque réponse.
"""
import time

from bot.twitch.handlers import (
    _RELANCE_WINDOW_S,
    _consume_relance,
    _note_reply_sent,
    _relances,
)


def _vide():
    _relances.clear()


def test_sans_reponse_prealable_aucune_relance():
    """Un inconnu qui mentionne Wally reste soumis au cooldown."""
    _vide()
    assert _consume_relance("chan", "42") is False


def test_apres_une_reponse_la_relance_passe():
    _vide()
    _note_reply_sent("chan", "42")
    assert _consume_relance("chan", "42") is True


def test_la_relance_ne_sert_qu_une_fois():
    """Sinon la fenêtre deviendrait un blanc-seing : le cooldown ne reprendrait
    jamais tant que la personne écrit."""
    _vide()
    _note_reply_sent("chan", "42")
    assert _consume_relance("chan", "42") is True
    assert _consume_relance("chan", "42") is False


def test_repondre_a_nouveau_rouvre_une_relance():
    """Un échange qui dure reste fluide : chaque réponse de Wally en rend une."""
    _vide()
    _note_reply_sent("chan", "42")
    _consume_relance("chan", "42")
    _note_reply_sent("chan", "42")
    assert _consume_relance("chan", "42") is True


def test_la_fenetre_expire():
    """Revenir une heure plus tard n'est plus la suite d'un échange."""
    _vide()
    _note_reply_sent("chan", "42")
    _relances[("chan", "42")] = time.monotonic() - _RELANCE_WINDOW_S - 1
    assert _consume_relance("chan", "42") is False


def test_la_relance_est_propre_a_la_personne():
    """Wally répond à l'un ; un autre ne gagne pas une exemption au passage."""
    _vide()
    _note_reply_sent("chan", "42")
    assert _consume_relance("chan", "99") is False


def test_la_relance_est_propre_au_canal():
    _vide()
    _note_reply_sent("chan_a", "42")
    assert _consume_relance("chan_b", "42") is False


def test_les_entrees_perimees_sont_purgees():
    """Le process tourne des semaines : le dict ne doit pas gonfler."""
    _vide()
    for i in range(5):
        _note_reply_sent("chan", str(i))
        _relances[("chan", str(i))] = time.monotonic() - _RELANCE_WINDOW_S - 1
    _note_reply_sent("chan", "frais")
    assert list(_relances) == [("chan", "frais")]
