"""Objectif automatique, vagues d'emotes, paliers de compteur, rappel du bingo."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _n(live=True, reply="ça commence à faire"):
    feed = OverlayFeed()
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=reply)
    return OverlayNarrator(feed, llm, lambda: live), feed


def _widgets(q):
    return [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"]


# ── objectif alimenté par les vrais événements ──

def test_un_objectif_se_remplit_avec_les_evenements():
    """Sans ça, il faudrait redonner le chiffre à la main à chaque abonnement."""
    n, feed = _n()
    n.open_goal("objectif subs", 4, "sub")
    q = feed.subscribe()
    assert n.record_goal_event("sub") is True
    ev = _widgets(q)[-1]
    assert ev["kind"] == "gauge" and ev["params"]["percent"] == 25.0


def test_un_evenement_d_un_autre_type_ne_compte_pas():
    n, _ = _n()
    n.open_goal("objectif subs", 4, "sub")
    assert n.record_goal_event("follow") is False


def test_un_don_de_plusieurs_abonnements_compte_pour_autant():
    n, _ = _n()
    n.open_goal("objectif subs", 10, "sub")
    n.record_goal_event("sub", 5)
    assert n._goal["count"] == 5


def test_l_objectif_atteint_se_ferme():
    n, _ = _n()
    n.open_goal("objectif subs", 2, "sub")
    n.record_goal_event("sub")
    n.record_goal_event("sub")
    assert n._goal is None


def test_un_objectif_invalide_est_refuse():
    n, _ = _n()
    assert n.open_goal("x", 0, "sub") is False
    assert n.open_goal("x", 5, "licornes") is False
    assert n.open_goal("x", "beaucoup", "sub") is False


def test_pas_d_objectif_hors_live():
    n, _ = _n(live=False)
    assert n.open_goal("x", 5, "sub") is False


def test_un_evenement_sans_objectif_ne_fait_rien():
    n, _ = _n()
    assert n.record_goal_event("sub") is False


# ── vagues d'emotes ──

def test_une_vague_s_affiche():
    n, feed = _n()
    q = feed.subscribe()
    assert n.show_emote_wave("KEKW") is True
    assert _widgets(q)[-1]["params"]["emote"] == "KEKW"


def test_pas_de_vague_hors_live():
    n, _ = _n(live=False)
    assert n.show_emote_wave("KEKW") is False


# ── paliers de compteur ──

def test_les_paliers_sont_ceux_qui_comptent():
    assert OverlayNarrator.is_counter_milestone(10)
    assert OverlayNarrator.is_counter_milestone(200)
    assert not OverlayNarrator.is_counter_milestone(11)
    assert not OverlayNarrator.is_counter_milestone(150)


@pytest.mark.asyncio
async def test_un_palier_declenche_une_remarque():
    """Un chiffre qui monte tout seul finit par ne plus rien dire."""
    n, feed = _n()
    q = feed.subscribe()
    assert await n.on_counter_milestone("pas rechargé", 10) == "ça commence à faire"
    assert [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "bubble"]


@pytest.mark.asyncio
async def test_un_non_palier_ne_coute_aucun_appel():
    n, _ = _n()
    assert await n.on_counter_milestone("pas rechargé", 11) is None
    n._llm.complete.assert_not_awaited()


# ── rappel du bingo ──

def test_le_bingo_est_remontre_de_temps_en_temps():
    """Sinon les viewers arrivés entre deux cases ignorent qu'une partie court."""
    n, feed = _n()
    n.start_bingo(["a", "b"])
    q = feed.subscribe()
    assert n.maybe_remind_bingo(every_s=0.0) is True
    assert _widgets(q)[-1]["kind"] == "bingo"


def test_le_rappel_ne_se_repete_pas_trop_vite():
    n, _ = _n()
    n.start_bingo(["a", "b"])
    n.maybe_remind_bingo(every_s=0.0)
    assert n.maybe_remind_bingo(every_s=600.0) is False


def test_pas_de_rappel_sans_partie():
    n, _ = _n()
    assert n.maybe_remind_bingo(every_s=0.0) is False
