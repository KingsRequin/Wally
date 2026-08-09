"""Le catalogue des widgets d'overlay ne doit être là que quand l'overlay écoute.

`reasoning_system.md` faisait 4084 mots, dont 952 — 23 % — pour décrire dix-sept
widgets utilisables UNIQUEMENT pendant un live (le prompt le disait lui-même :
« sinon rien ne s'affiche, personne ne regarde »). Et `self._system` est construit
une seule fois : ce catalogue partait donc à chaque tick, 24 h/24. Mesuré le
2026-08-09 : 30 ticks dans la journée, ~40 000 tokens de widgets inutilisables.

Le projet avait déjà tranché ce débat pour `[SPEAK]`, mesure à l'appui — « inutile
de laisser le LLM choisir une action qui sera jetée au dispatch : il décidait en
boucle une action structurellement impossible (18 messages écrits pour rien en 5
jours) ». Même patron ici.
"""
from pathlib import Path

import pytest

from bot.intelligence.reasoning_agent import ReasoningAgent
from tests.test_selfupgrade_historique_groupe import _ctx

_PROMPTS = Path(__file__).parent.parent / "bot" / "intelligence" / "persona" / "prompts"


@pytest.fixture(autouse=True)
def _overlay_au_repos(monkeypatch):
    """Par défaut : aucun overlay actif (le cas de la grande majorité du temps)."""
    monkeypatch.setattr(
        "bot.intelligence.overlay_narrator.overlay_actif", lambda: False, raising=False
    )


def _agent() -> ReasoningAgent:
    return ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)


def test_le_prompt_de_base_ne_porte_plus_le_catalogue():
    """Le catalogue a quitté `reasoning_system.md` pour son propre fichier."""
    systeme = (_PROMPTS / "reasoning_system.md").read_text(encoding="utf-8")
    assert "coinflip" not in systeme
    assert "hangman" not in systeme
    # L'action reste documentée ailleurs, dans le fichier dédié.
    assert (_PROMPTS / "overlay_widgets.md").exists()
    catalogue = (_PROMPTS / "overlay_widgets.md").read_text(encoding="utf-8")
    for widget in ("coinflip", "hangman", "bingo", "poll", "rps", "meme"):
        assert widget in catalogue, f"{widget} perdu dans l'extraction"


def test_aucun_widget_propose_quand_loverlay_dort():
    assert "coinflip" not in _agent()._format_context(_ctx())


def test_les_widgets_apparaissent_quand_loverlay_ecoute(monkeypatch):
    monkeypatch.setattr(
        "bot.intelligence.overlay_narrator.overlay_actif", lambda: True, raising=False
    )
    rendu = _agent()._format_context(_ctx())
    assert "coinflip" in rendu
    assert "show_overlay" in rendu


def test_un_narrateur_en_erreur_ne_casse_pas_le_tick(monkeypatch):
    """Best-effort : perdre le catalogue est un moindre mal, perdre le tick non."""
    def _explose():
        raise RuntimeError("narrateur cassé")

    monkeypatch.setattr(
        "bot.intelligence.overlay_narrator.overlay_actif", _explose, raising=False
    )
    assert "coinflip" not in _agent()._format_context(_ctx())
