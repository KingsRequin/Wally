# tests/test_twitch_clips_selection.py
"""Choisir un clip autrement que « le dernier ».

Helix trie déjà par nombre de vues et sait borner la fenêtre : le podium des
plus vus ne coûte donc rien de plus qu'un appel. La recherche par titre, elle,
se fait ici — Helix ne sait pas filtrer là-dessus, pas plus que sur le clippeur.
"""
from unittest.mock import AsyncMock

import pytest

from tests.test_twitch_api import make_api

CLIPS = [
    {"id": "a", "title": "le 1v3 de fou sur World's Edge", "creator_name": "KingsRequin",
     "view_count": 420, "created_at": "2026-08-08T10:00:00Z"},
    {"id": "b", "title": "Azra rate le saut", "creator_name": "Azrael",
     "view_count": 130, "created_at": "2026-08-08T09:00:00Z"},
    {"id": "c", "title": "la reverse sur Fuse", "creator_name": "azrael_ttv",
     "view_count": 12, "created_at": "2026-08-07T20:00:00Z"},
]


@pytest.mark.asyncio
async def test_le_podium_garde_l_ordre_des_vues():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    top = await api.get_top_clips(days=7, first=3)
    assert [c["id"] for c in top] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_le_podium_est_borne():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert len(await api.get_top_clips(days=7, first=2)) == 2


@pytest.mark.asyncio
async def test_le_podium_trie_meme_si_helix_rend_le_desordre():
    """On ne se repose pas sur un ordre non garanti par contrat."""
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=list(reversed(CLIPS)))
    top = await api.get_top_clips(days=7, first=3)
    assert [c["view_count"] for c in top] == [420, 130, 12]


@pytest.mark.asyncio
async def test_sans_clip_le_podium_est_vide():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=[])
    assert await api.get_top_clips(days=7) == []


@pytest.mark.asyncio
async def test_chercher_un_clip_par_son_titre():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    trouve = await api.find_clip("la reverse")
    assert trouve["id"] == "c"


@pytest.mark.asyncio
async def test_la_recherche_ignore_la_casse_et_les_accents():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert (await api.find_clip("WORLD'S EDGE"))["id"] == "a"


@pytest.mark.asyncio
async def test_a_egalite_de_pertinence_le_plus_vu_gagne():
    """« le clip d'Azra » : deux titres le mentionnent, on montre le meilleur."""
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    trouve = await api.find_clip("azra")
    assert trouve["id"] == "b"          # 130 vues contre 12


@pytest.mark.asyncio
async def test_un_titre_introuvable_ne_rend_pas_un_clip_au_hasard():
    """Mieux vaut dire qu'on n'a pas trouvé que montrer autre chose."""
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert await api.find_clip("recette de la tartiflette") is None
