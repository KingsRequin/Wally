# tests/test_overlay_clip_modes.py
"""Choisir le clip à montrer : le dernier, le plus vu, ou celui d'un titre.

« Mets le dernier clip » ne couvrait qu'un cas sur trois. Le podium, lui,
n'affiche aucune vidéo : cinq clips à la suite monopoliseraient l'écran.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator

CLIP = {
    "title": "le 1v3 de la mort",
    "creator_name": "Azrael",
    "embed_url": "https://clips.twitch.tv/embed?clip=x",
    "duration": 28.5,
}

TOP = [
    {"title": "le 1v3 de la mort", "creator_name": "Azrael", "view_count": 420},
    {"title": "la reverse sur Fuse", "creator_name": "KingsRequin", "view_count": 130},
]


def _narrateur(live=True, clip=CLIP, top=TOP):
    feed = OverlayFeed()
    n = OverlayNarrator(
        feed, MagicMock(), lambda: live,
        last_clip=AsyncMock(return_value=clip),
        top_clips=AsyncMock(return_value=top),
    )
    return n


@pytest.mark.asyncio
async def test_le_mode_par_defaut_reste_le_dernier_clip():
    n = _narrateur()
    await n.play_last_clip()
    n._last_clip.assert_awaited_once_with(None, query=None, most_viewed=False)


@pytest.mark.asyncio
async def test_on_peut_demander_le_plus_vu():
    n = _narrateur()
    await n.play_last_clip(most_viewed=True)
    assert n._last_clip.await_args.kwargs["most_viewed"] is True


@pytest.mark.asyncio
async def test_on_peut_demander_un_clip_par_son_titre():
    n = _narrateur()
    await n.play_last_clip(query="le 1v3")
    assert n._last_clip.await_args.kwargs["query"] == "le 1v3"


@pytest.mark.asyncio
async def test_le_podium_liste_les_clips_avec_leurs_vues():
    n = _narrateur()
    n._feed = MagicMock()

    out = await n.show_top_clips(5)

    assert out["count"] == 2
    assert out["best"] == "le 1v3 de la mort"
    params = n._feed.widget.call_args.kwargs
    assert params["rows"][0]["views"] == 420
    assert params["rows"][0]["author"] == "Azrael"


@pytest.mark.asyncio
async def test_le_podium_est_plafonne_a_cinq():
    beaucoup = [{"title": f"clip {i}", "creator_name": "x", "view_count": i} for i in range(20)]
    n = _narrateur(top=beaucoup)
    n._feed = MagicMock()

    await n.show_top_clips(50)

    n._top_clips.assert_awaited_once_with(5)


@pytest.mark.asyncio
async def test_sans_clip_aucun_podium_n_est_publie():
    n = _narrateur(top=[])
    n._feed = MagicMock()
    assert await n.show_top_clips() is None
    n._feed.widget.assert_not_called()


@pytest.mark.asyncio
async def test_hors_live_pas_de_podium():
    n = _narrateur(live=False)
    assert await n.show_top_clips() is None


@pytest.mark.asyncio
async def test_une_api_muette_ne_casse_rien():
    n = OverlayNarrator(
        OverlayFeed(), MagicMock(), lambda: True,
        top_clips=AsyncMock(side_effect=RuntimeError("Helix HS")),
    )
    assert await n.show_top_clips() is None


@pytest.mark.asyncio
async def test_sans_fournisseur_de_podium_rien_ne_casse():
    n = OverlayNarrator(OverlayFeed(), MagicMock(), lambda: True)
    assert await n.show_top_clips() is None
