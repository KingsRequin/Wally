"""OverlayNarrator — budget de parole et condensation des pensées.

Le risque du projet est produit : un compagnon qui commente sans arrêt devient
insupportable, et un overlay ne se scrolle pas. Le budget doit donc REFUSER,
pas seulement être suggéré dans un prompt.
"""
from unittest.mock import AsyncMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrator(live=True, reply="je m'ennuie ferme", interval=90.0):
    feed = OverlayFeed()
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=reply)
    return OverlayNarrator(feed, llm, lambda: live, min_interval_s=interval), feed, llm


# ── hors live ──

@pytest.mark.asyncio
async def test_rien_ne_sort_hors_live():
    """Personne ne regarde : ni bulle, ni appel LLM payé pour rien."""
    n, feed, llm = _narrator(live=False)
    q = feed.subscribe()
    assert await n.on_thought("une longue pensée introspective") is None
    llm.complete.assert_not_awaited()
    assert q.empty()


@pytest.mark.asyncio
async def test_une_sonde_de_live_cassee_fait_taire():
    """En cas de doute sur l'état du stream, on se tait."""
    feed = OverlayFeed()
    llm = AsyncMock()
    def _boom():
        raise RuntimeError("API twitch HS")
    n = OverlayNarrator(feed, llm, _boom)
    assert await n.on_thought("pensée") is None
    llm.complete.assert_not_awaited()


# ── budget ──

@pytest.mark.asyncio
async def test_le_budget_refuse_la_deuxieme_bulle():
    n, feed, llm = _narrator()
    assert await n.on_thought("première pensée") is not None
    assert await n.on_thought("deuxième pensée") is None   # trop tôt
    assert llm.complete.await_count == 1                    # pas payé pour rien


@pytest.mark.asyncio
async def test_le_creneau_est_reserve_avant_la_condensation():
    """Deux pensées quasi simultanées ne doivent pas passer toutes les deux
    pendant que la première attend encore le LLM."""
    n, feed, llm = _narrator()
    slow = []

    async def _slow_complete(*a, **kw):
        slow.append(1)
        if len(slow) == 1:
            assert n._may_speak() is False   # créneau déjà pris
        return "ok court"

    llm.complete = _slow_complete
    await n.on_thought("pensée")
    assert len(slow) == 1


@pytest.mark.asyncio
async def test_le_budget_se_libere_apres_l_intervalle():
    n, _, _ = _narrator(interval=0.0)
    assert await n.on_thought("une") is not None
    assert await n.on_thought("deux") is not None


# ── condensation ──

@pytest.mark.asyncio
async def test_la_pensee_publiee_est_une_bulle_de_pensee():
    n, feed, _ = _narrator(reply="personne parle, je m'ennuie")
    q = feed.subscribe()
    await n.on_thought("longue rumination sur le silence du serveur")

    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait())
    thinking = [e for e in kinds if e["type"] == "thinking"]
    bubbles = [e for e in kinds if e["type"] == "bubble"]
    assert thinking and thinking[0]["active"] is True     # les trois points d'abord
    assert bubbles[0]["mode"] == "thought"
    assert bubbles[0]["text"] == "personne parle, je m'ennuie"


@pytest.mark.asyncio
async def test_rien_a_dire_eteint_les_points():
    """Le prompt répond RIEN quand la pensée n'intéresse pas un spectateur."""
    n, feed, _ = _narrator(reply="RIEN")
    q = feed.subscribe()
    assert await n.on_thought("méta-rumination sur ma propre nature") is None
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [e["active"] for e in events if e["type"] == "thinking"] == [True, False]
    assert not [e for e in events if e["type"] == "bubble"]


@pytest.mark.asyncio
async def test_une_condensation_trop_longue_est_rejetee():
    n, _, _ = _narrator(reply="mot " * 60)
    assert await n.on_thought("pensée") is None


@pytest.mark.asyncio
async def test_un_llm_en_erreur_ne_casse_rien():
    n, feed, llm = _narrator()
    llm.complete = AsyncMock(side_effect=RuntimeError("API down"))
    assert await n.on_thought("pensée") is None


@pytest.mark.asyncio
async def test_pensee_vide_ignoree():
    n, feed, llm = _narrator()
    assert await n.on_thought("   ") is None
    llm.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_les_guillemets_du_modele_sont_retires():
    n, _, _ = _narrator(reply='"je m\'ennuie ferme"')
    assert await n.on_thought("pensée") == "je m'ennuie ferme"
