# tests/test_apex_overlay_narrator.py
"""`show_apex` : le panneau part à l'écran, ou rien ne part du tout.

Règle héritée de l'overlay : rien hors live, et jamais de carte creuse — Wally
doit pouvoir dire « je n'ai pas pu » plutôt que raconter un panneau imaginaire.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


class _FakeApex:
    def __init__(self, panel):
        self._panel = panel
        self.calls = []

    async def build_panel(self, panel, player="", requester=None, period="live",
                          notion="kills"):
        self.calls.append((panel, player, requester))
        return self._panel


def _narrateur(live=True, panel=None):
    feed = OverlayFeed()
    apex = _FakeApex(panel)
    n = OverlayNarrator(feed, AsyncMock(), lambda: live, apex=apex)
    return n, feed, apex


@pytest.mark.asyncio
async def test_le_panneau_part_a_l_ecran():
    n, feed, apex = _narrateur(panel={"kind": "apex_rank", "player": "Azrael_TTV", "rank_name": "Gold"})
    feed.widget = MagicMock()

    out = await n.show_apex("rank", "Azrael_ttv", "il grimpe")

    assert out == {"widget": "apex_rank", "player": "Azrael_TTV"}
    assert apex.calls == [("rank", "Azrael_ttv", None)]
    # Le `kind` sert de nom de widget ; il ne doit pas repartir dans les données.
    feed.widget.assert_called_once_with("apex_rank", player="Azrael_TTV", rank_name="Gold")


@pytest.mark.asyncio
async def test_rien_hors_live():
    """Personne ne regarde : on n'appelle même pas l'API."""
    n, _, apex = _narrateur(live=False, panel={"kind": "apex_rank"})
    assert await n.show_apex("rank") is None
    assert apex.calls == []


@pytest.mark.asyncio
async def test_sans_donnee_aucune_carte_n_est_publiee():
    n, _, _ = _narrateur(panel=None)
    assert await n.show_apex("rank", "Inconnu") is None


@pytest.mark.asyncio
async def test_sans_service_apex_rien_ne_casse():
    n = OverlayNarrator(OverlayFeed(), AsyncMock(), lambda: True)
    assert await n.show_apex("rank") is None


@pytest.mark.asyncio
async def test_une_erreur_du_service_ne_remonte_pas():
    """Un panneau raté ne doit pas faire échouer la réponse en cours."""
    feed = OverlayFeed()

    class _Boom:
        async def build_panel(self, *a, **k):
            raise RuntimeError("API HS")

    n = OverlayNarrator(feed, AsyncMock(), lambda: True, apex=_Boom())
    assert await n.show_apex("rank") is None


@pytest.mark.asyncio
async def test_l_identite_du_demandeur_est_transmise_au_service():
    """« affiche mon rang » n'a de sens que si le service sait qui demande."""
    n, _, apex = _narrateur(panel={"kind": "apex_rank", "player": "X"})
    await n.show_apex("rank", "", "", requester="twitch:42")
    assert apex.calls == [("rank", "", "twitch:42")]
