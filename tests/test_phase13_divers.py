# tests/test_phase13_divers.py
"""Phase 13 de l'audit du 2026-08-10 : les derniers défauts moyens.

M37 — le cache Apex n'était jamais purgé, clé indexée sur un pseudo du chat.
M38 — `"legends": null` (rendu par l'API) faisait lever la lecture du profil.
M40 — pas de cache négatif météo : 5 s d'attente à chaque tick pendant une panne.
M41 — `feedparser.parse(resp.text)` ignore la déclaration d'encodage du XML.
M42 — la route « renommer son image » comparait un ID préfixé à un ID brut :
      403 systématique, route morte depuis sa création.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ────────────────────────────── M38 ──────────────────────────────
def test_un_payload_avec_legends_null_ne_leve_pas():
    from bot.core.apex.reader import read_profile

    payload = {
        "global": {"name": "xeforce_", "uid": "1", "platform": "PC", "level": 100},
        "legends": None,               # rendu tel quel par l'API
        "realtime": {},
        "total": {},
    }
    profil = read_profile(payload)      # ne doit pas lever
    assert profil is not None
    assert profil.skin is None


def test_un_payload_normal_reste_lu():
    from bot.core.apex.reader import read_profile

    payload = {
        "global": {"name": "xeforce_", "uid": "1", "platform": "PC", "level": 100},
        "legends": {"selected": {"gameInfo": {"skin": "Revenant Rouge"}}},
        "realtime": {},
        "total": {},
    }
    assert read_profile(payload).skin == "Revenant Rouge"


# ────────────────────────────── M37 ──────────────────────────────
@pytest.mark.asyncio
async def test_le_cache_apex_se_purge():
    from bot.core.apex.client import ApexClient

    horloge = {"t": 1000.0}
    c = ApexClient.__new__(ApexClient)
    c._api_key = "k"
    c._ttl = {"bridge": 60}
    c._now = lambda: horloge["t"]
    c._lock = __import__("asyncio").Lock()
    c._last_request = 0.0
    c._cache = {}
    c._fetch = AsyncMock(return_value={"ok": True})

    await c.get("bridge", {"player": "joueur_a"})
    horloge["t"] += 3600                      # l'entrée périme
    await c.get("bridge", {"player": "joueur_b"})

    assert len(c._cache) == 1, "les entrées périmées s'accumulent sans fin"


@pytest.mark.asyncio
async def test_une_entree_encore_fraiche_nest_pas_purgee():
    from bot.core.apex.client import ApexClient

    horloge = {"t": 1000.0}
    c = ApexClient.__new__(ApexClient)
    c._api_key = "k"
    c._ttl = {"bridge": 600}
    c._now = lambda: horloge["t"]
    c._lock = __import__("asyncio").Lock()
    c._last_request = 0.0
    c._cache = {}
    c._fetch = AsyncMock(return_value={"ok": True})

    await c.get("bridge", {"player": "a"})
    await c.get("bridge", {"player": "b"})
    assert len(c._cache) == 2


# ────────────────────────────── M40 ──────────────────────────────
@pytest.mark.asyncio
async def test_une_panne_meteo_nest_pas_retentee_a_chaque_tick():
    from bot.core import system_info

    system_info._weather_cache = (0.0, None)
    system_info._weather_echec_ts = 0.0

    appels = {"n": 0}

    class _Client:
        async def __aenter__(self):
            appels["n"] += 1
            raise OSError("wttr.in injoignable")

        async def __aexit__(self, *a):
            return False

    with patch("httpx.AsyncClient", return_value=_Client()):
        await system_info.fetch_weather_france()
        await system_info.fetch_weather_france()
        await system_info.fetch_weather_france()

    assert appels["n"] == 1, "chaque tick repayait les 5 s de timeout"


# ────────────────────────────── M41 ──────────────────────────────
def test_le_flux_rss_est_parse_en_octets():
    from bot.core import rss_feed

    src = inspect.getsource(rss_feed)
    assert "feedparser.parse, resp.content" in src
    assert "feedparser.parse, resp.text" not in src


# ────────────────────────────── M42 ──────────────────────────────
@pytest.mark.asyncio
async def test_le_createur_peut_renommer_son_image():
    from bot.dashboard.routes import gallery

    requete = MagicMock()
    requete.json = AsyncMock(return_value={"title": "Mon titre"})
    etat = requete.app.state.wally
    # En base, `gallery_images.user_id` est l'ID BRUT.
    etat.db.get_gallery_image = AsyncMock(return_value={"user_id": "610550333042589752"})
    etat.db.update_gallery_title = AsyncMock()

    with patch.object(gallery, "_extract_user_id_from_jwt",
                      return_value=("discord:610550333042589752", {})):
        out = await gallery.update_title(requete, "img-1")

    assert out["title"] == "Mon titre"
    etat.db.update_gallery_title.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_tiers_ne_peut_pas_renommer_l_image_d_un_autre():
    from fastapi import HTTPException

    from bot.dashboard.routes import gallery

    requete = MagicMock()
    requete.json = AsyncMock(return_value={"title": "Piraté"})
    etat = requete.app.state.wally
    etat.db.get_gallery_image = AsyncMock(return_value={"user_id": "111111111111111111"})
    etat.db.update_gallery_title = AsyncMock()

    with patch.object(gallery, "_extract_user_id_from_jwt",
                      return_value=("discord:610550333042589752", {})):
        with pytest.raises(HTTPException) as e:
            await gallery.update_title(requete, "img-1")

    assert e.value.status_code == 403
    etat.db.update_gallery_title.assert_not_awaited()
