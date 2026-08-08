"""Annuler ce qui est sur l'overlay.

Rien n'était annulable avant : seul le chifoumi avait une sortie (`close`). Un
bingo, un pendu, un objectif ouverts vivaient jusqu'à la fin du live, et un meme
affiché restait jusqu'à l'expiration de son minuteur.

Deux exigences guident ces tests :
- un ABANDON ne dépouille pas — un sondage annulé n'a pas de gagnant ;
- le compte rendu reste HONNÊTE — quand il n'y avait rien, il faut le dire.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.discord.handlers import run_overlay_cancel_tool
from bot.intelligence.overlay_narrator import (
    CANCEL_TARGETS,
    CANCEL_TOOL_SPEC,
    OverlayNarrator,
)


def _narrator(live=True):
    return OverlayNarrator(OverlayFeed(), MagicMock(), lambda: live)


# ── OverlayFeed.clear ─────────────────────────────────────────────────────


def test_clear_publie_et_vide_le_tampon():
    """Le tampon compte autant que l'écran : `recent()` le rejoue à tout client
    qui se connecte, et la reconnexion SSE d'OBS suffisait à faire réapparaître
    ce qu'on venait d'annuler."""
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.widget("meme", src="/x.jpg", caption="un chat")
    assert feed.recent(), "le widget devrait être rejouable avant l'annulation"

    feed.clear()

    assert feed.recent() == []
    types = [q.get_nowait()["type"] for _ in range(q.qsize())]
    assert types[-1] == "clear"


# ── OverlayNarrator.cancel ────────────────────────────────────────────────


def test_le_bingo_est_abandonne():
    n = _narrator()
    n.start_bingo(["une carte", "un kill", "une chute"])
    assert n.cancel("bingo")["cancelled"] == ["bingo", ]
    assert n._bingo is None
    assert n.show_bingo() is None


def test_annuler_l_ecran_ne_touche_pas_aux_parties():
    """« enlève le meme » ne doit pas emporter le bingo qui tourne derrière."""
    n = _narrator()
    n.start_bingo(["une carte", "un kill"])
    out = n.cancel("ecran")
    assert out["cancelled"] == ["ecran"]
    assert n._bingo is not None, "le bingo devait survivre à un nettoyage d'écran"


def test_annuler_une_partie_nettoie_aussi_l_ecran():
    """Abandonner le bingo en laissant sa grille affichée n'aurait aucun sens.

    Le nettoyage est un EFFET, pas une chose annulée : « le bingo est abandonné »
    suffit au compte rendu, inutile d'y ajouter « et l'écran est nettoyé ».
    """
    n = _narrator()
    q = n._feed.subscribe()
    n.start_bingo(["une carte", "un kill"])
    assert n.cancel("bingo")["cancelled"] == ["bingo"]
    types = [q.get_nowait()["type"] for _ in range(q.qsize())]
    assert types[-1] == "clear", "la grille devait quitter l'écran"


def test_tout_emporte_les_parties_et_l_ecran():
    n = _narrator()
    n.start_bingo(["une carte", "un kill"])
    n.start_hangman("mirage")
    n.open_goal("50 follows", 50, "follow")
    done = n.cancel("tout")["cancelled"]
    assert set(done) == {"bingo", "pendu", "objectif", "ecran"}
    assert (n._bingo, n._hangman, n._goal) == (None, None, None)


def test_rien_en_cours_rend_une_liste_vide():
    """La liste vide est la réponse UTILE : elle permet de dire « il n'y avait
    pas de bingo » au lieu de laisser croire qu'on a retiré quelque chose."""
    n = _narrator()
    assert n.cancel("bingo")["cancelled"] == []


def test_une_cible_inconnue_est_signalee():
    n = _narrator()
    out = n.cancel("le truc bleu")
    assert out["unknown"] is True and out["cancelled"] == []


def test_on_annule_meme_hors_live():
    """C'est justement quand le stream vient de se couper qu'un bingo resté
    ouvert doit pouvoir être nettoyé."""
    n = _narrator(live=True)
    n.start_bingo(["une carte", "un kill"])
    n._is_live = lambda: False
    assert "bingo" in n.cancel("bingo")["cancelled"]


def test_un_sondage_annule_n_est_pas_depouille():
    """`close_poll()` annoncerait un gagnant à une manche interrompue."""
    n = _narrator()
    n.start_poll("chocolat ou vanille ?", ["chocolat", "vanille"], seconds=30)
    n._last_poll = None
    assert "sondage" in n.cancel("sondage")["cancelled"]
    assert n._poll is None
    assert n._last_poll is None, "un abandon ne produit aucun résultat"


@pytest.mark.asyncio
async def test_la_cloture_planifiee_est_coupee():
    """Sans ça, le `sleep` en cours rouvrait le dépouillement d'un sondage
    qu'on venait d'abandonner."""
    n = _narrator()
    n.start_poll("chocolat ou vanille ?", ["chocolat", "vanille"], seconds=30)
    task = n._poll_task
    assert task is not None, "la clôture doit être planifiée dans une boucle asyncio"
    n.cancel("sondage")
    assert task.cancelled() or task.cancelling() or n._poll_task is None


# ── le bloc d'état injecté au prompt ──────────────────────────────────────


def test_pas_de_bloc_hors_live():
    n = _narrator(live=False)
    assert n.current_state_block() == ""


def test_pas_de_bloc_quand_rien_ne_tourne():
    """Le cas courant doit coûter zéro token."""
    assert _narrator().current_state_block() == ""


def test_le_bloc_dit_ce_qui_tourne():
    n = _narrator()
    n.start_bingo(["une carte", "un kill", "une chute"])
    n.open_goal("50 follows", 50, "follow")
    block = n.current_state_block()
    assert "0/3 cases" in block
    assert "0/50" in block


def test_le_bloc_disparait_apres_annulation():
    n = _narrator()
    n.start_bingo(["une carte", "un kill"])
    n.cancel("tout")
    assert n.current_state_block() == ""


# ── l'outil exposé au LLM ─────────────────────────────────────────────────


def _bot(result):
    narrator = MagicMock()
    narrator.cancel.return_value = result
    return SimpleNamespace(overlay_narrator=narrator)


def test_l_outil_rend_compte_de_ce_qui_a_ete_annule():
    out = json.loads(run_overlay_cancel_tool(
        _bot({"target": "bingo", "cancelled": ["bingo", "ecran"]}), {"target": "bingo"}))
    assert out["status"] == "ok"
    assert "abandonné" in out["message"]


def test_l_outil_avoue_qu_il_n_y_avait_rien():
    """Sans ça, Wally répond « c'est annulé » à qui lui demande de couper un
    bingo qui n'a jamais existé."""
    out = json.loads(run_overlay_cancel_tool(
        _bot({"target": "bingo", "cancelled": []}), {"target": "bingo"}))
    assert out["status"] == "nothing"
    assert "ne prétends pas" in out["message"]


def test_l_outil_annonce_l_absence_de_depouillement():
    """Le mot compte : Wally ne doit pas annoncer de gagnant."""
    out = json.loads(run_overlay_cancel_tool(
        _bot({"target": "sondage", "cancelled": ["sondage", "ecran"]}), {"target": "sondage"}))
    assert "sans dépouillement" in out["message"]


def test_l_outil_signale_une_cible_inconnue():
    out = json.loads(run_overlay_cancel_tool(
        _bot({"target": "zzz", "cancelled": [], "unknown": True}), {"target": "zzz"}))
    assert out["status"] == "rejected"


def test_sans_overlay_branche_l_outil_le_dit():
    out = json.loads(run_overlay_cancel_tool(SimpleNamespace(), {"target": "tout"}))
    assert out["status"] == "unavailable"


def test_l_enum_de_l_outil_couvre_exactement_les_cibles_gerees():
    """Une cible acceptée par l'enum mais inconnue de `cancel()` répondrait
    « rien en cours » sur une demande pourtant valide."""
    enum = CANCEL_TOOL_SPEC["function"]["parameters"]["properties"]["target"]["enum"]
    assert set(enum) == set(CANCEL_TARGETS)
    assert CANCEL_TOOL_SPEC["function"]["parameters"]["required"] == ["target"]


def test_chaque_cible_est_traitee_sans_erreur():
    """Dérivé de l'enum plutôt que recopié : une cible ajoutée à la liste sans
    branche dans `cancel()` doit faire tomber ce test."""
    for target in CANCEL_TARGETS:
        assert _narrator().cancel(target).get("unknown") is not True


# ── le mode test, dit au prompt ───────────────────────────────────────────
#
# Le 2026-08-08, mode test actif, Wally a refusé d'afficher un clip en
# expliquant « on n'est pas en live » — sans appeler l'outil. Il avait raison
# sur le live et tort sur la conclusion : rien ne lui disait que son overlay
# répondait quand même.


def test_le_bloc_signale_le_mode_test():
    n = _narrator(live=False)
    n.force_live(5)
    block = n.current_state_block()
    assert "mode test" in block.lower()


def test_le_mode_test_ne_se_fait_pas_passer_pour_un_live():
    """Sinon Wally annonce un stream au chat alors qu'il n'y en a pas."""
    n = _narrator(live=False)
    n.force_live(5)
    assert "aucun live" in n.current_state_block().lower()


def test_un_vrai_live_n_ajoute_aucune_ligne():
    """Le cas courant doit rester à zéro token : `stream_live` le dit déjà."""
    assert _narrator(live=True).current_state_block() == ""
