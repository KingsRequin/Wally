# tests/test_site_clips_publics.py
"""La page publique `/clips` et la route qui la nourrit.

Deux pièges portés par cette route, tous deux déjà payés ailleurs :

- **Helix trie par nombre de VUES, jamais par date** (cf. `get_last_clip`).
  Servir sa réponse telle quelle mettrait le clip le plus vu en tête d'une page
  qui promet « les derniers ».
- **Un vide mis en cache est une panne figée.** `get_recent_clips` rend `[]`
  aussi bien quand la chaîne n'a rien clippé que quand l'appel a échoué : le
  statut du live juste au-dessus a coûté cinq minutes de « hors ligne » en plein
  stream pour cette raison exacte.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.routes import twitch as twitch_mod
from tests.test_dashboard_routes import _make_state

_NOW = datetime.now(timezone.utc)


def _clip(jours: int, ident: str, vues: int) -> dict:
    return {
        "id": ident,
        "title": f"clip {ident}",
        "creator_name": "KingsRequin",
        "view_count": vues,
        "duration": 30.0,
        "created_at": (_NOW - timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thumbnail_url": f"https://clips-media-assets2.twitch.tv/{ident}-preview.jpg",
        "url": f"https://clips.twitch.tv/{ident}",
        # Champs que Helix renvoie et que la page n'affiche pas.
        "broadcaster_id": "659251746",
        "video_id": "vodvod",
        "vod_offset": 1234,
    }


@pytest.fixture(autouse=True)
def _cache_vierge():
    """Le cache est un module-level : sans ce reset, un test tient l'autre."""
    twitch_mod._clips_cache.update({"data": None, "fetched_at": 0.0})
    yield
    twitch_mod._clips_cache.update({"data": None, "fetched_at": 0.0})


def _app(clips: list[dict] | None = None, api=None):
    if api is None and clips is not None:
        api = AsyncMock()
        api.get_recent_clips = AsyncMock(return_value=clips)
    return create_dashboard_app(_make_state(twitch_api=api)), api


async def _get(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get("/api/public/twitch/clips")


async def test_sans_twitch_la_page_recoit_une_liste_vide():
    app, _ = _app(api=None)
    r = await _get(app)
    assert r.status_code == 200
    assert r.json() == {"clips": []}


async def test_les_clips_sortent_du_plus_recent_au_plus_vieux():
    """L'ordre de Helix (par vues) ne doit RIEN décider ici."""
    app, _ = _app([_clip(30, "vieux", 9999), _clip(1, "hier", 3), _clip(9, "semaine", 500)])
    ids = [c["id"] for c in (await _get(app)).json()["clips"]]
    assert ids == ["hier", "semaine", "vieux"]


async def test_la_carte_ne_porte_que_ce_qu_elle_affiche():
    app, _ = _app([_clip(1, "hier", 42)])
    clip = (await _get(app)).json()["clips"][0]
    assert clip["id"] == "hier"
    assert clip["creator"] == "KingsRequin"
    assert clip["views"] == 42
    assert clip["duration"] == 30.0
    assert clip["thumbnail_url"].endswith("-preview.jpg")
    # Rien de ce que la page n'affiche pas ne part au visiteur.
    assert "broadcaster_id" not in clip
    assert "video_id" not in clip
    assert "vod_offset" not in clip


async def test_un_clip_sans_slug_est_jete():
    """Sans `id`, le front ne peut construire aucune URL d'embed : la carte
    serait un bouton qui ouvre un lecteur vide."""
    app, _ = _app([{"id": "", "title": "fantôme"}, _clip(1, "hier", 1)])
    assert [c["id"] for c in (await _get(app)).json()["clips"]] == ["hier"]


async def test_deux_visiteurs_ne_font_qu_un_appel_helix():
    app, api = _app([_clip(1, "hier", 1)])
    await _get(app)
    await _get(app)
    api.get_recent_clips.assert_awaited_once()


async def test_une_reponse_vide_n_est_pas_mise_en_cache():
    """Un 401 d'une seconde ne doit pas vider la page pendant deux minutes."""
    api = AsyncMock()
    api.get_recent_clips = AsyncMock(side_effect=[[], [_clip(1, "hier", 1)]])
    app, _ = _app(api=api)

    assert (await _get(app)).json()["clips"] == []
    assert [c["id"] for c in (await _get(app)).json()["clips"]] == ["hier"]


# ── Le branchement côté site ──────────────────────────────────────────────

_UI = Path("public-ui")


def test_la_page_est_branchee_partout():
    """Un module de page qui n'est ni importé, ni routé, ni atteignable depuis
    la nav est du code mort qu'aucun test d'API ne voit."""
    app_js = (_UI / "app.js").read_text()
    assert "import * as pageClips from './pages/clips.js';" in app_js
    assert "'/clips'" in app_js
    assert 'data-route="/clips"' in (_UI / "index.html").read_text()
    assert (_UI / "pages" / "clips.js").exists()


def test_le_lecteur_twitch_recoit_le_domaine_hote():
    """Sans `parent`, Twitch refuse l'embed par un écran noir SANS erreur JS :
    ni le smoke test ni la console ne le verraient."""
    assert "parent: location.hostname" in (_UI / "pages" / "clips.js").read_text()
