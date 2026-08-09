"""Phase 11 : pendu ressuscité, bingo mal rapporté, clip annoncé à tort."""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

from bot.core.overlay_feed import OverlayFeed


# ── Un widget clos ne ressuscite plus à la reconnexion ───────────────────────
#
# Un événement `sticky` est réémis par `recent()` SANS jamais périmer — c'est ce
# qui permet à une partie en cours de revenir chez un OBS qui se reconnecte.
# Mais rien ne les retirait à la fin : le dernier coup est publié en
# `sticky=False` avec 12 s de durée, donc filtré par l'âge au bout de 12 s,
# tandis que TOUS les coups précédents restaient éligibles. Une reconnexion
# tardive rejouait alors un état INTERMÉDIAIRE d'une partie terminée, sans
# minuteur, à l'écran jusqu'au widget suivant.

def test_la_fin_de_partie_purge_les_etats_collants():
    feed = OverlayFeed()
    feed.widget("hangman", sticky=True, mask=["", "", ""], duration=10)
    feed.widget("hangman", sticky=True, mask=["f", "", ""], duration=10)
    feed.widget("hangman", sticky=False, won=True, word="fusee", duration=12)

    sticky_restants = [
        e for e in feed.recent()
        if e.get("kind") == "hangman" and (e.get("params") or {}).get("sticky") is True
    ]
    assert sticky_restants == []


def test_une_partie_en_cours_survit_toujours_a_une_reconnexion():
    """La propriété que le `sticky` sert à garantir ne doit pas être perdue."""
    feed = OverlayFeed()
    feed.widget("hangman", sticky=True, mask=["f", "", ""], duration=10)

    rejoues = [e for e in feed.recent() if e.get("kind") == "hangman"]
    assert len(rejoues) == 1


def test_la_purge_ne_touche_pas_les_autres_widgets():
    feed = OverlayFeed()
    feed.widget("bingo", sticky=True, cells=["a"], duration=10)
    feed.widget("hangman", sticky=False, lost=True, duration=12)

    kinds = {e.get("kind") for e in feed.recent()}
    assert "bingo" in kinds


# ── Le compte rendu du bingo dit ce qui s'est passé ──────────────────────────

def test_une_case_cochee_est_rapportee_comme_telle():
    """`_overlay_outcome` lisait `done`, que AUCUN des trois retours ne fournit,
    et la coche d'une case ne renvoie même pas `cells` : l'outil annonçait
    « 0/0 cases cochées » après un `check`, et ne disait jamais que la grille
    était complète."""
    from bot.discord.handlers import _overlay_outcome

    texte = _overlay_outcome({"widget": "bingo", "checked": "ff sur un 1v1", "full": False})
    assert "ff sur un 1v1" in texte
    assert "0/0" not in texte


def test_une_grille_complete_est_signalee():
    from bot.discord.handlers import _overlay_outcome

    texte = _overlay_outcome({"widget": "bingo", "checked": "rage quit", "full": True})
    assert "complète" in texte


def test_louverture_annonce_la_taille_de_la_grille():
    from bot.discord.handlers import _overlay_outcome

    texte = _overlay_outcome({"widget": "bingo", "cells": ["a", "b", "c"]})
    assert "3" in texte


# ── Le journal du clip dit ce qui est parti à l'écran ────────────────────────

async def test_un_clip_non_affiche_nest_pas_annonce_comme_joue():
    """`show_clip` rend False si le live s'est coupé pendant la préparation —
    jusqu'à 3 min de reprises. Le booléen était ignoré et le log annonçait quand
    même le clip."""
    from bot.twitch import clip_announce

    narrator = MagicMock()
    narrator.is_active.return_value = True
    narrator.show_clip.return_value = False          # le live s'est coupé entre-temps
    api = MagicMock()
    api.get_clip_video_url = AsyncMock(return_value=None)

    async def _sans_attendre(_):
        return None

    messages = []
    with _capture(clip_announce.logger, messages):
        await clip_announce.announce_clip(
            narrator, api, {"id": "c1", "title": "un clip", "creator_name": "alice"},
            sleep=_sans_attendre,
        )

    assert any("non affiché" in m for m in messages)
    assert not any("joué" in m for m in messages)


def test_le_journal_applique_le_vrai_test_de_lecture():
    """Une URL de vidéo ne suffit pas : elle doit passer la liste blanche
    d'hôtes de `_is_clip_video`. Le chemin explicite faisait déjà ce test ;
    l'automatique se contentait de `if video` et annonçait « joué » un clip
    tombé en carte nue."""
    code = inspect.getsource(__import__("bot.twitch.clip_announce", fromlist=["x"]))
    assert "OverlayNarrator._is_clip_video(video)" in code


class _capture:
    """Collecte les messages loguru émis pendant le bloc."""

    def __init__(self, logger, sink: list):
        self._logger = logger
        self._sink = sink
        self._id = None

    def __enter__(self):
        self._id = self._logger.add(lambda m: self._sink.append(str(m)), level="DEBUG")
        return self

    def __exit__(self, *a):
        self._logger.remove(self._id)
        return False


# ── Trois pièges de lecture retirés ──────────────────────────────────────────

def test_lannotation_de_on_event_correspond_a_lappel():
    """Elle annonçait UN argument alors que l'appel en passe trois depuis le
    typage des événements, et le repli qui rattrapait le TypeError a été retiré :
    une réimplémentation écrite d'après elle aurait levé, absorbée en
    `logger.warning` — flux passif muet, sans cause visible."""
    from bot.core.stream_watcher import StreamWatcher

    code = inspect.getsource(StreamWatcher.__init__)
    assert "Callable[[str], None]] = None" not in code


def test_set_chat_observer_a_disparu():
    """Il annonçait servir « aux sondages et aux saluts de l'overlay » et
    n'était appelé de nulle part — ces deux fonctions sont câblées en direct
    depuis `twitch/handlers.py`."""
    from bot.core import stream_feed

    assert not hasattr(stream_feed.StreamFeed, "set_chat_observer")


def test_plus_de_branche_morte_dans_on_chat_message():
    from bot.intelligence.overlay_narrator import OverlayNarrator

    code = inspect.getsource(OverlayNarrator.on_chat_message)
    assert "if author:\n            key = author.strip()" not in code
