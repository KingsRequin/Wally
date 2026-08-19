"""Les jeux qui DURENT ne s'ouvrent que si on les demande.

Quatrième récidive du même défaut, arbitrée avec l'owner le 2026-08-19 : « il
lance encore des bingo sans qu'on lui demande ». Les trois correctifs précédents
traitaient la RELANCE (un bingo par-dessus un autre) — celui-ci traite la
PREMIÈRE ouverture, celle que personne n'a réclamée.

L'inventaire des logs est sans appel : toutes les ouvertures viennent de la voie
cognitive (`ACT show_overlay`), aucune d'une demande. 2026-08-13 09:33, 11:09,
19:58, 20:01, 20:09 · 08-14 09:20, 12:13, 20:06, 22:06 · 08-15 09:43, 20:01 ·
08-18 09:21 · 08-19 20:01 — presque toujours dans les minutes qui suivent le
lancement du live.

La règle est MÉCANIQUE, pas une consigne de prompt : la leçon du 2026-08-13 est
qu'« une ligne de contexte ne pèse rien face à l'envie d'ouvrir un bingo au
démarrage d'un stream ». Le défaut de `show_widget` est donc « personne ne l'a
demandé » — un futur chemin d'appel qu'on oublierait de marquer refusera, au
lieu d'ouvrir.

Ce qui reste libre : cocher une case, remontrer la grille, annuler, et TOUS les
widgets qui ne font que passer (meme, dé, roue, pile ou face, chifoumi, épinglé).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bot.intelligence.overlay_narrator import OverlayNarrator, ouverture_de_partie


def _narrateur():
    return OverlayNarrator(overlay_feed=MagicMock(), llm=MagicMock(),
                           is_live=lambda: True)


# ── ce qui compte comme « ouvrir une partie » ───────────────────────────────

@pytest.mark.parametrize("widget,extra,attendu", [
    ("bingo", {"cells": ["il blâme le ping", "il rage"]}, "bingo"),
    ("poll", {"question": "on continue ?", "options": ["oui", "non"]}, "sondage"),
    ("hangman", {"word": "wattson"}, "pendu"),
    ("goal", {"label": "objectif subs", "target": 10}, "objectif"),
])
def test_les_quatre_jeux_qui_DURENT_sont_reconnus(widget, extra, attendu):
    assert ouverture_de_partie(widget, **extra) == attendu


@pytest.mark.parametrize("widget,extra", [
    # Continuer une partie n'est pas l'ouvrir : c'est l'argument qui tranche.
    ("bingo", {}),
    ("bingo", {"check": "le ping"}),
    ("bingo", {"cells": ["  ", ""]}),          # des cases vides n'ouvrent rien
    ("hangman", {}),
    # Et tout ce qui ne fait que passer.
    ("coinflip", {}), ("dice", {"count": 2}), ("meme", {}), ("rps", {}),
    ("pinned", {"author": "bob", "text": "salut"}), ("wheel", {"options": ["a", "b"]}),
])
def test_le_reste_n_ouvre_AUCUNE_partie(widget, extra):
    assert ouverture_de_partie(widget, **extra) is None


# ── la garde, au point de passage unique ────────────────────────────────────

def test_un_bingo_que_PERSONNE_n_a_demande_ne_s_ouvre_pas():
    n = _narrateur()
    assert n.show_widget("bingo", "allez", cells=["il blâme le ping", "il rage"]) is None
    n._feed.widget.assert_not_called()
    assert n._bingo is None


def test_le_MEME_bingo_demandé_s_ouvre():
    """La porte reste grande ouverte : quelqu'un demande, Wally lance."""
    n = _narrateur()
    assert n.show_widget("bingo", "allez", cells=["il blâme le ping", "il rage"],
                         sollicite=True) is not None
    assert n._bingo is not None


def test_les_widgets_qui_PASSENT_restent_libres():
    """Brider l'initiative sur un pile ou face ne protégerait de rien et
    retirerait tout le sel — c'est le même critère que la garde anti-relance."""
    n = _narrateur()
    assert n.show_widget("coinflip", "pile ou face ?") is not None


def test_COCHER_une_case_reste_une_initiative_libre():
    """C'est même tout l'intérêt du bingo : Wally coche ce qu'il constate, sans
    qu'on ait à le lui dire."""
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage"], sollicite=True)
    n._feed.widget.reset_mock()
    assert n.show_widget("bingo", "gagné", check="le ping") is not None


def test_la_garde_ANTI_RELANCE_tient_toujours():
    """L'ancienne règle ne saute pas : deux demandes de suite n'écrasent pas la
    partie en cours."""
    n = _narrateur()
    n.show_widget("bingo", "", cells=["a", "b"], sollicite=True)
    assert n.show_widget("bingo", "", cells=["c", "d"], sollicite=True) is None
    assert n.game_already_running("bingo", cells=["c", "d"])


def test_le_refus_DIT_pourquoi_et_ouvre_une_porte():
    """Un refus muet ferait réessayer. Celui-ci nomme la règle et donne la
    sortie : proposer, puis lancer si on lui dit oui."""
    n = _narrateur()
    motif = n.refus_faute_de_demande("bingo", cells=["a", "b"])
    assert motif and "demande" in motif.lower()
    assert n.refus_faute_de_demande("coinflip") is None


def test_le_refus_se_TAIT_quand_le_motif_est_ailleurs():
    """Hors live, rien ne s'affiche pour une tout autre raison. Donner ce
    motif-là serait plausible et faux — et un motif faux se retient."""
    hors_live = OverlayNarrator(overlay_feed=MagicMock(), llm=MagicMock(),
                                is_live=lambda: False)
    assert hors_live.refus_faute_de_demande("bingo", cells=["a", "b"]) is None


# ── la voie cognitive ne peut pas se déclarer sollicitée ────────────────────

@pytest.mark.asyncio
async def test_l_initiative_cognitive_n_OUVRE_plus_de_bingo():
    from bot.intelligence.action_dispatcher import ActionDispatcher

    narrateur = MagicMock()
    narrateur.show_widget.return_value = None
    narrateur.game_already_running.return_value = None
    narrateur.refus_faute_de_demande.return_value = "Rien affiché : ..."
    d = ActionDispatcher(bot=MagicMock(), overlay_narrator=narrateur)

    await d._act("show_overlay", {"widget": "bingo", "comment": "le live démarre",
                                  "cells": ["il blâme le ping"]})

    assert narrateur.show_widget.call_args.kwargs.get("sollicite") is not True


@pytest.mark.asyncio
async def test_le_MODELE_ne_peut_pas_se_declarer_sollicite():
    """Le drapeau vient de l'appelant, JAMAIS du modèle — même règle que
    l'adversaire du chifoumi, qui ne peut pas être désigné par lui."""
    from bot.intelligence.action_dispatcher import ActionDispatcher

    narrateur = MagicMock()
    narrateur.show_widget.return_value = None
    narrateur.game_already_running.return_value = None
    narrateur.refus_faute_de_demande.return_value = None
    d = ActionDispatcher(bot=MagicMock(), overlay_narrator=narrateur)

    await d._act("show_overlay", {"widget": "bingo", "cells": ["a"],
                                  "sollicite": True})

    assert narrateur.show_widget.call_args.kwargs.get("sollicite") is not True


@pytest.mark.asyncio
async def test_le_refus_est_CONSIGNE_dans_le_flux_du_stream(monkeypatch):
    """Perception passive, sans `notify` : il doit le LIRE au tick suivant, pas
    être réveillé par son propre refus — rendre l'insistance payante serait le
    contraire du but."""
    from bot.intelligence import action_dispatcher as mod

    feed = MagicMock()
    monkeypatch.setattr("bot.core.stream_feed.active_stream_feed", lambda: feed)

    narrateur = MagicMock()
    narrateur.show_widget.return_value = None
    narrateur.game_already_running.return_value = None
    narrateur.refus_faute_de_demande.return_value = "Rien affiché : personne ne l'a demandé."
    d = mod.ActionDispatcher(bot=MagicMock(), overlay_narrator=narrateur)

    await d._act("show_overlay", {"widget": "bingo", "cells": ["a"]})

    feed.record.assert_called_once()
    assert feed.record.call_args.kwargs["notify"] is False


# ── la voie conversationnelle, elle, est une demande ────────────────────────

def test_l_outil_de_conversation_marque_la_DEMANDE():
    """Quelqu'un a parlé à Wally pour en arriver là : c'est exactement ce que le
    drapeau veut dire."""
    from bot.discord.handlers import run_overlay_tool

    narrator = MagicMock()
    narrator.show_widget.return_value = {"widget": "bingo"}
    narrator.is_active.return_value = True
    narrator.game_already_running.return_value = None
    bot = SimpleNamespace(overlay_narrator=narrator)

    run_overlay_tool(bot, {"widget": "bingo", "cells": ["a", "b"]}, requester="zeddo")

    assert narrator.show_widget.call_args.kwargs["sollicite"] is True


def test_le_catalogue_DIT_la_regle_au_modele():
    """La garde tient toute seule, mais un refus qu'on n'a pas vu venir se
    rejoue : le catalogue doit dire de PROPOSER plutôt que d'ouvrir."""
    from pathlib import Path

    prompt = (Path(__file__).resolve().parents[1] / "bot" / "intelligence"
              / "persona" / "prompts" / "overlay_widgets.md").read_text(encoding="utf-8")
    assert "s'ouvrent sur DEMANDE" in prompt
    assert "propose" in prompt.lower()
    # Et il doit dire ce qui RESTE libre : une consigne qui ne parle que
    # d'interdits fait un compagnon qui n'ose plus rien.
    for libre in ("cocher", "meme", "annuler"):
        assert libre in prompt.lower()
