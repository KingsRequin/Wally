"""Quand rien ne s'affiche, Wally doit dire ce qui manque À CE widget-LÀ.

Le refus de `show_overlay` rendait une phrase unique, quel que soit le widget :

    Rien affiché : 'hangman' est inconnu ou il manque des données
    (la roue veut au moins 2 options, un sondage une question).

Ce texte n'est pas un log : il repart au modèle comme résultat d'outil, et Wally
le reformule en direct dans le chat. Il annonçait donc aux spectateurs la
contrainte de la ROUE devant un pendu sans mot — et, ne sachant pas ce qui
manquait vraiment, ne pouvait pas corriger son appel. Onze refus ainsi libellés
entre le 2026-08-06 et le 2026-08-11 (pendu sans `word`, bingo sans `cells`,
comparaison sans chiffres), tous légitimes sur le fond.

Le motif se construit désormais LÀ OÙ L'ON REFUSE — seul endroit qui sait ce qui
manque — et remonte par `dernier_refus_widget()`.
"""
import json
from unittest.mock import MagicMock

import pytest

from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrateur():
    return OverlayNarrator(overlay_feed=MagicMock(), llm=MagicMock(),
                           is_live=lambda: True)


# (widget, arguments incomplets, ce que le motif DOIT nommer)
_MANQUES = [
    ("wheel",    {"options": ["une seule"]},   "options"),
    ("countdown", {},                          "seconds"),
    ("gauge",    {},                           "percent"),
    ("pinned",   {"text": "   "},              "text"),
    ("hangman",  {},                           "word"),
    ("bingo",    {"cells": ["une seule"]},    "cells"),
    ("stats",    {"player": "Azrael"},         "lines"),
    ("versus",   {"left_name": "a", "right_name": "b"}, "left_value"),
]


@pytest.mark.parametrize("widget,extra,attendu", _MANQUES)
def test_le_motif_nomme_le_champ_qui_manque(widget, extra, attendu):
    n = _narrateur()
    assert n.show_widget(widget, "allez", sollicite=True, **extra) is None
    assert attendu in n.dernier_refus_widget(), (
        f"'{widget}' refusé sans nommer `{attendu}` : {n.dernier_refus_widget()!r}")


@pytest.mark.parametrize("widget,extra,_attendu", _MANQUES)
def test_le_motif_ne_parle_JAMAIS_dun_autre_widget(widget, extra, _attendu):
    """L'ancien texte citait la roue et le sondage pour tout le monde."""
    n = _narrateur()
    n.show_widget(widget, "allez", sollicite=True, **extra)
    motif = n.dernier_refus_widget().lower()
    if widget != "wheel":
        assert "roue" not in motif, motif
    if widget != "poll":
        assert "sondage" not in motif, motif


def test_un_widget_inconnu_est_dit_inconnu_pas_incomplet():
    """`clip` existe, mais pas par ce chemin — il a ses propres données."""
    n = _narrateur()
    assert n.show_widget("clip", "regardez ça") is None
    motif = n.dernier_refus_widget()
    assert "clip" in motif and "widget" in motif
    assert "manque" not in motif.lower()


def test_hors_live_le_motif_le_dit():
    n = OverlayNarrator(overlay_feed=MagicMock(), llm=MagicMock(),
                        is_live=lambda: False)
    assert n.show_widget("coinflip") is None
    assert "live" in n.dernier_refus_widget()


def test_un_appel_qui_ABOUTIT_efface_le_motif_precedent():
    """Sinon l'appelant rendrait le refus de l'appel d'avant."""
    n = _narrateur()
    n.show_widget("wheel", "go", sollicite=True, options=["seule"])
    assert n.dernier_refus_widget()
    assert n.show_widget("coinflip", "pile ou face") is not None
    assert n.dernier_refus_widget() == ""


def test_loutil_rend_le_motif_au_modele():
    """Bout en bout : c'est CE texte que Wally reformule dans le chat."""
    from bot.discord import handlers

    narrateur = _narrateur()
    narrateur.is_active = lambda: True
    bot = MagicMock()
    bot.overlay_narrator = narrateur

    brut = handlers.run_overlay_tool(
        bot, {"widget": "hangman", "comment": "à vous de deviner"})
    charge = json.loads(brut)

    assert charge["status"] == "rejected"
    assert "word" in charge["message"]
    assert "roue" not in charge["message"].lower()
