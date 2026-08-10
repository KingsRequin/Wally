"""Wally relançait un bingo toutes les deux minutes, sans qu'on lui demande rien.

Relevé en production le 2026-08-10, au lancement du live d'Azraël — cinq bingos
en huit minutes (19:37:14, 19:37:56, 19:38:43, 19:42:47, 19:45:07), dont un en
réponse à « wally ta une petite blague a raconter ? ».

Ses propres pensées disent tout :

  19:38:43  « J'avais un bingo prêt, mais je réalise que je ne l'ai pas encore
             ouvert concrètement. »   ← il en avait ouvert DEUX dans la minute
  19:39:28  « Il n'y a pas de commande "annuler" dans mes widgets — je peux
             juste cocher des cases ou en remontrer une nouvelle. »

Il ne se trompait sur rien : il était aveugle et démuni.

  · Deux prompts, deux contenus. `build_system_prompt` (conversations) recevait
    le bloc « Sur ton overlay » ; `ReasoningAgent._format_context` (la boucle
    cognitive) ne recevait que le CATALOGUE des widgets. Le seul chemin qui
    prend des initiatives était le seul aveugle à leurs effets.
  · `cancel_overlay` existait comme outil de conversation, pas comme action
    cognitive — alors que le bloc d'état l'annonçait déjà noir sur blanc. La
    promesse existait, pas le moyen de la tenir.
"""
from unittest.mock import MagicMock

import pytest

from bot.intelligence.action_dispatcher import ActionDispatcher
from bot.intelligence.attention_agent import AttentionContext


def _ctx():
    """Le vrai type de contexte cognitif, vide. Un faux objet masquerait un
    champ renommé : `_format_context` lit `ctx.time_of_day` sans `getattr`."""
    return AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
    )


def _agent():
    """Un ReasoningAgent nu — `_format_context` n'a pas besoin du reste."""
    from bot.intelligence.reasoning_agent import ReasoningAgent

    agent = ReasoningAgent.__new__(ReasoningAgent)
    agent._widgets_overlay = "## L'overlay du stream est ALLUMÉ"
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {}
    return agent


def _contexte(agent, monkeypatch, *, etat: str | None, actif: bool = True):
    import bot.intelligence.overlay_narrator as narrateur

    monkeypatch.setattr(narrateur, "overlay_actif", lambda: actif)
    monkeypatch.setattr(narrateur, "current_overlay_state_block", lambda: etat)
    return agent._format_context(_ctx())


def test_la_cognition_voit_ce_qui_est_deja_affiche(monkeypatch):
    """Le défaut de fond : sans cet état, chaque tick « redécouvre » l'overlay vide."""
    contexte = _contexte(
        _agent(), monkeypatch,
        etat="\n--- Sur ton overlay ---\nBingo : 0/6 cases cochées.",
    )

    assert "Bingo : 0/6 cases cochées." in contexte, (
        "la boucle cognitive ne voit pas le bingo qu'elle vient d'ouvrir — "
        "elle le rouvrira au tick suivant, et au suivant"
    )


def test_le_catalogue_et_letat_arrivent_ensemble(monkeypatch):
    """Le catalogue dit ce qu'il PEUT afficher, l'état ce qui l'EST déjà.
    L'un sans l'autre, c'est l'invitation à rouvrir en boucle."""
    contexte = _contexte(
        _agent(), monkeypatch, etat="\n--- Sur ton overlay ---\nBingo : 2/9 cases cochées.",
    )

    assert "L'overlay du stream est ALLUMÉ" in contexte
    assert "Bingo : 2/9" in contexte


def test_rien_a_lecran_najoute_aucun_token(monkeypatch):
    """Cas courant : pas de live, ou rien d'ouvert. Le bloc doit disparaître."""
    contexte = _contexte(_agent(), monkeypatch, etat=None)

    assert "Sur ton overlay" not in contexte


def test_un_etat_illisible_ne_casse_pas_le_tick(monkeypatch):
    """Perdre un bloc de contexte est un moindre mal ; perdre le tick, non."""
    import bot.intelligence.overlay_narrator as narrateur

    def _explose():
        raise RuntimeError("narrateur en vrac")

    monkeypatch.setattr(narrateur, "overlay_actif", lambda: True)
    monkeypatch.setattr(narrateur, "current_overlay_state_block", _explose)

    contexte = _agent()._format_context(_ctx())   # ne doit pas lever
    assert "L'overlay du stream est ALLUMÉ" in contexte


# ─────────────────────────── cancel_overlay ───────────────────────────
def _dispatcher():
    disp = ActionDispatcher.__new__(ActionDispatcher)
    disp._overlay_narrator = MagicMock()
    disp._facts = None
    disp._feed = None
    disp._bot = MagicMock()
    disp._publish_act = MagicMock()
    return disp


@pytest.mark.asyncio
async def test_la_cognition_peut_enfin_annuler_un_bingo():
    """« wally annule le bingo », dit trois fois, restait sans effet possible."""
    disp = _dispatcher()
    disp._overlay_narrator.cancel.return_value = {"cancelled": ["bingo"]}

    await disp._act("cancel_overlay", {"target": "bingo"})

    disp._overlay_narrator.cancel.assert_called_once_with("bingo")
    disp._publish_act.assert_called_once()


@pytest.mark.asyncio
async def test_annuler_sans_cible_efface_tout():
    disp = _dispatcher()
    disp._overlay_narrator.cancel.return_value = {"cancelled": ["bingo", "objectif"]}

    await disp._act("cancel_overlay", {})

    disp._overlay_narrator.cancel.assert_called_once_with("tout")


@pytest.mark.asyncio
async def test_annuler_ce_qui_nexiste_pas_nest_pas_une_action():
    """La liste vide est une réponse : rien n'a été retiré, donc rien à publier."""
    disp = _dispatcher()
    disp._overlay_narrator.cancel.return_value = {"cancelled": []}

    await disp._act("cancel_overlay", {"target": "pendu"})

    disp._overlay_narrator.cancel.assert_called_once_with("pendu")
    disp._publish_act.assert_not_called()


@pytest.mark.asyncio
async def test_une_cible_inconnue_ne_leve_pas():
    disp = _dispatcher()
    disp._overlay_narrator.cancel.return_value = {"cancelled": [], "unknown": True}

    await disp._act("cancel_overlay", {"target": "licorne"})

    disp._overlay_narrator.cancel.assert_called_once_with("licorne")
    disp._publish_act.assert_not_called()


def test_le_catalogue_documente_lannulation():
    """Une action que le modèle ne connaît pas est une action qui n'existe pas.

    Le bloc d'état annonçait `cancel_overlay` depuis toujours, mais le catalogue
    des ACT ne le décrivait nulle part — Wally en a conclu, correctement, qu'il
    ne pouvait pas annuler.
    """
    from pathlib import Path

    catalogue = (
        Path(__file__).resolve().parent.parent
        / "bot/intelligence/persona/prompts/overlay_widgets.md"
    ).read_text(encoding="utf-8")

    assert "cancel_overlay" in catalogue
    # Le JSON est obligatoire : `_ACT_RE` exige `[ACT nom {…}]`.
    assert '[ACT cancel_overlay {"target"' in catalogue


def test_la_forme_documentee_est_reellement_parsable():
    """Le catalogue et le parseur doivent être d'accord — sinon l'action est
    décrite, émise, et silencieusement perdue."""
    from bot.intelligence.meta_agent import parse_decisions

    decisions = parse_decisions('[ACT cancel_overlay {"target": "bingo"}]')

    actes = [d for d in decisions if d.action == "ACT"]
    assert len(actes) == 1
    assert actes[0].act_name == "cancel_overlay"
    assert actes[0].act_args == {"target": "bingo"}
