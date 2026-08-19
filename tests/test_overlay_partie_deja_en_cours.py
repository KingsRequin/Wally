"""Wally rouvrait des parties par-dessus celles qui tournaient déjà.

Relevé en production le 2026-08-13, au lancement du live : trois bingos ouverts
en dix minutes (19:58:56, 20:01:27, 20:09:08), six cases chacun, chacun effaçant
le précédent. Le live était détecté à 19:58:43 — treize secondes avant le
premier. À 20:09:10, sa pensée affichée était « Le live est lancé, je remplis le
bingo » : il venait d'en ouvrir deux.

Le correctif du 2026-08-10 (l'état de l'overlay injecté dans le contexte
cognitif ET dans le prompt des conversations) tient toujours, et ces tests-là
sont dans `test_overlay_bingo_en_boucle.py`. Il était juste insuffisant : rendre
l'état VISIBLE est une consigne au modèle, pas un garde-fou. Au démarrage d'un
live, une ligne de contexte ne pèse rien.

Ce qui manquait : que l'OUTIL réponde, au moment du geste. Même patron que
`cancel_overlay` — « il te dira s'il y avait vraiment quelque chose » —, en sens
inverse. On ne retire pas l'initiative : on rend l'information quand elle compte.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.discord.handlers import run_overlay_tool
from bot.intelligence.action_dispatcher import ActionDispatcher
from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrateur():
    n = OverlayNarrator(OverlayFeed(), AsyncMock(), lambda: True)
    n._feed = MagicMock()
    return n


# ── les quatre parties qui DURENT ───────────────────────────────────────────

def test_un_second_bingo_ne_remplace_pas_le_premier():
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage", "il chute"], sollicite=True)
    n.check_bingo("le ping")

    assert n.show_widget("bingo", "", cells=["autre chose", "et encore"], sollicite=True) is None
    assert len(n._bingo["cells"]) == 3, "la grille en cours a été écrasée"
    assert n._bingo["done"][0] is True, "la case cochée a été perdue"


def test_un_second_sondage_ne_remplace_pas_le_premier():
    n = _narrateur()
    n.show_widget("poll", "", question="chocolat ou vanille ?",
                  options=["chocolat", "vanille"], seconds=30, sollicite=True)

    assert n.show_widget("poll", "", question="et le café ?",
                         options=["oui", "non"], sollicite=True) is None
    assert n._poll["question"] == "chocolat ou vanille ?"


def test_un_second_pendu_ne_remplace_pas_le_premier():
    n = _narrateur()
    n.show_widget("hangman", "", word="octane", hint="une légende", sollicite=True)
    n._count_hangman("kingsrequin", "o")
    trouvees = set(n._hangman["found"])

    assert n.show_widget("hangman", "", word="valkyrie", sollicite=True) is None
    assert n._hangman["word"] == "octane"
    assert n._hangman["found"] == trouvees


def test_un_second_objectif_ne_remplace_pas_le_premier():
    n = _narrateur()
    n.show_widget("goal", "", label="50 follows", target=50, kind="follow", sollicite=True)
    n.record_goal_event("follow")

    assert n.show_widget("goal", "", label="10 subs", target=10, kind="sub", sollicite=True) is None
    assert n._goal["label"] == "50 follows"
    assert n._goal["count"] == 1


# ── ce que le garde ne doit PAS empêcher ────────────────────────────────────

def test_cocher_une_case_reste_possible():
    """Le geste normal d'un bingo en cours. Le brider viderait le widget."""
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage"], sollicite=True)

    assert n.show_widget("bingo", "", check="le ping") is not None


def test_remontrer_la_grille_reste_possible():
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage"], sollicite=True)

    assert n.show_widget("bingo", "") is not None


def test_remontrer_le_pendu_reste_possible():
    n = _narrateur()
    n.show_widget("hangman", "", word="octane", hint="une légende", sollicite=True)

    assert n.show_widget("hangman", "on en est là") is not None


def test_une_partie_annulee_libere_la_place():
    """C'est la sortie qu'on lui indique : elle doit vraiment marcher."""
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage"], sollicite=True)
    n.cancel("bingo")

    assert n.show_widget("bingo", "", cells=["autre chose", "et encore"], sollicite=True) is not None
    assert n._bingo["cells"] == ["autre chose", "et encore"]


@pytest.mark.parametrize("widget, extra", [
    ("coinflip", {}),
    ("dice", {}),
    ("meme", {}),
    ("pinned", {"author": "azra", "text": "un message"}),
    ("counter", {"result": "42 morts"}),
])
def test_les_widgets_ephemeres_se_relancent_librement(widget, extra):
    """Un meme, un dé, un message épinglé ne durent pas : les brider ne ferait
    que retirer de l'initiative sans rien protéger."""
    n = _narrateur()
    n._memes = MagicMock()
    n._memes.pick.return_value = {"name": "chat.webp", "description": "un chat"}

    assert n.show_widget(widget, "", **extra) is not None
    assert n.show_widget(widget, "", **extra) is not None


# ── le refus doit être DIT : chemin conversationnel ─────────────────────────

def _bot(narrateur):
    return SimpleNamespace(overlay_narrator=narrateur)


def test_l_outil_dit_ce_qui_tourne_et_comment_recommencer():
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage", "il chute"], sollicite=True)
    n.check_bingo("le ping")

    out = json.loads(run_overlay_tool(
        _bot(n), {"widget": "bingo", "cells": ["autre", "chose"]}))

    assert out["status"] != "ok"
    assert "1/3" in out["message"], "l'état de la partie en cours doit être dit"
    assert "cancel_overlay" in out["message"], "la sortie doit être indiquée"


def test_le_refus_ne_passe_pas_pour_une_donnee_manquante():
    """« widget inconnu ou données manquantes » est un diagnostic FAUX ici :
    il envoie Wally corriger ses arguments, donc réessayer."""
    n = _narrateur()
    n.show_widget("poll", "", question="chocolat ?", options=["oui", "non"], sollicite=True)

    out = json.loads(run_overlay_tool(
        _bot(n), {"widget": "poll", "question": "café ?", "options": ["a", "b"]}))

    assert out["status"] == "busy"
    assert "inconnu" not in out["message"]


def test_le_pendu_refuse_sans_reveler_le_mot():
    """Le message peut voyager loin : il ne doit rien apprendre au chat."""
    n = _narrateur()
    n.show_widget("hangman", "", word="octane", hint="une légende", sollicite=True)

    message = json.loads(run_overlay_tool(
        _bot(n), {"widget": "hangman", "word": "valkyrie"}))["message"]

    assert "octane" not in message.lower()
    assert "légende" not in message.lower()


def test_hors_live_le_refus_reste_celui_du_live():
    """Une partie qui traîne après la fin du stream ne doit pas masquer la vraie
    raison : personne ne regarde."""
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage"], sollicite=True)
    n._live = lambda: False
    n.is_active = lambda: False

    out = json.loads(run_overlay_tool(
        _bot(n), {"widget": "bingo", "cells": ["autre", "chose"]}))

    assert out["status"] == "offline"


# ── le refus doit être DIT : chemin cognitif ────────────────────────────────

def _dispatcher(narrateur):
    disp = ActionDispatcher.__new__(ActionDispatcher)
    disp._overlay_narrator = narrateur
    disp._facts = None
    disp._feed = None
    disp._bot = MagicMock()
    disp._publish_act = MagicMock()
    return disp


@pytest.mark.asyncio
async def test_l_initiative_cognitive_n_ecrase_pas_la_partie():
    """La voie par laquelle les trois bingos du 2026-08-13 ont été ouverts."""
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage", "il chute"], sollicite=True)

    await _dispatcher(n)._act("show_overlay", {
        "widget": "bingo", "comment": "le live est lancé, je remplis le bingo",
        "cells": ["a", "b", "c", "d", "e", "f"],
    })

    assert len(n._bingo["cells"]) == 3, "l'initiative cognitive a écrasé la grille"


@pytest.mark.asyncio
async def test_le_refus_cognitif_remonte_au_flux_du_stream(monkeypatch):
    """Cette voie est un aller simple : sans trace lisible, le refus est muet et
    Wally réessaie au tick suivant."""
    from bot.core.stream_feed import StreamFeed

    feed = StreamFeed()
    monkeypatch.setattr("bot.core.stream_feed._active", feed)
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage"], sollicite=True)

    await _dispatcher(n)._act("show_overlay", {
        "widget": "bingo", "cells": ["a", "b", "c"],
    })

    rendu = feed.render()
    assert "bingo tourne DÉJÀ" in rendu
    assert "cancel_overlay" in rendu


@pytest.mark.asyncio
async def test_le_refus_cognitif_ne_reveille_pas_la_cadence(monkeypatch):
    """Perception passive : rendre l'insistance payante serait exactement le
    contraire de ce qu'on cherche."""
    from bot.core.stream_feed import StreamFeed

    feed = StreamFeed()
    observateur = MagicMock()
    feed.set_observer(observateur)
    monkeypatch.setattr("bot.core.stream_feed._active", feed)
    n = _narrateur()
    n.show_widget("bingo", "", cells=["il blâme le ping", "il rage"], sollicite=True)

    await _dispatcher(n)._act("show_overlay", {
        "widget": "bingo", "cells": ["a", "b", "c"],
    })

    observateur.assert_not_called()


@pytest.mark.asyncio
async def test_un_echec_ordinaire_ne_consigne_rien(monkeypatch):
    """Une roue à une case n'est pas une partie en cours : le flux du stream ne
    doit pas se remplir de nos ratés d'arguments."""
    from bot.core.stream_feed import StreamFeed

    feed = StreamFeed()
    monkeypatch.setattr("bot.core.stream_feed._active", feed)
    n = _narrateur()

    await _dispatcher(n)._act("show_overlay", {
        "widget": "wheel", "options": ["seule"],
    })

    assert feed.render() in ("", None)


# ── le modèle doit savoir que ce refus existe ───────────────────────────────

def test_le_catalogue_annonce_le_refus():
    """Un refus que le modèle ne connaît pas, c'est un refus qu'il prendra pour
    une panne — et il réessaiera."""
    from pathlib import Path

    catalogue = (
        Path(__file__).resolve().parent.parent
        / "bot/intelligence/persona/prompts/overlay_widgets.md"
    ).read_text(encoding="utf-8")

    assert "REFUSÉ" in catalogue
    assert "cancel_overlay" in catalogue


def test_la_description_de_l_outil_annonce_le_refus():
    from bot.intelligence.overlay_narrator import OVERLAY_TOOL_SPEC

    description = OVERLAY_TOOL_SPEC["function"]["description"]

    assert "REFUSE" in description
    assert "cancel_overlay" in description
