# tests/test_phase5_dashboard.py
"""Phase 5 de l'audit du 2026-08-10 : le dashboard exposé.

C23 — `twitch_callback` : seule route du wizard sans validation d'invitation,
      et le `state` OAuth n'était confronté à rien.
C24 — token admin comparé avec `!=` au lieu de `hmac.compare_digest`.
C25 — `/api/public/emotions/history` sans LIMIT : 9 344 lignes en base.
C26 — `NaN`/`Infinity` acceptés par `json.loads` → 500 répétable sans auth.
"""
import math

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException


# ────────────────────────────── C23 ──────────────────────────────
def _requete(db):
    r = MagicMock()
    r.app.state.wally.db = db
    r.query_params = {}
    return r


@pytest.mark.asyncio
async def test_un_state_qui_ne_correspond_pas_au_jeton_est_refuse():
    from bot.dashboard.routes.setup import twitch_callback

    db = MagicMock()
    db.get_setup_session = AsyncMock(return_value={})
    r = _requete(db)
    r.query_params = {"code": "abc", "state": "AUTRE_JETON:bot"}

    with pytest.raises(HTTPException) as e:
        await twitch_callback(r, "MON_JETON")
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_un_state_absent_est_refuse():
    from bot.dashboard.routes.setup import twitch_callback

    db = MagicMock()
    r = _requete(db)
    r.query_params = {"code": "abc"}

    with pytest.raises(HTTPException) as e:
        await twitch_callback(r, "MON_JETON")
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_une_invitation_revoquee_ne_donne_plus_de_callback():
    from bot.dashboard.routes.setup import twitch_callback

    db = MagicMock()
    db.get_setup_invite = AsyncMock(return_value=None)   # révoquée / inconnue
    r = _requete(db)
    r.query_params = {"code": "abc", "state": "MON_JETON:bot"}

    with pytest.raises(HTTPException) as e:
        await twitch_callback(r, "MON_JETON")
    assert e.value.status_code == 404


# ────────────────────────────── C24 ──────────────────────────────
def test_le_token_admin_est_compare_en_temps_constant():
    import inspect

    from bot.dashboard.routes import setup

    src = inspect.getsource(setup._check_preview_auth)
    assert "compare_digest" in src
    assert "!= cfg_token" not in src


def test_un_mauvais_token_de_preview_est_refuse():
    from bot.dashboard.routes.setup import _check_preview_auth

    r = MagicMock()
    r.app.state.wally.config.bot.dashboard_token = "le-vrai-token"
    r.headers = {"Authorization": "Bearer le-vrai-tokeX"}

    with pytest.raises(HTTPException) as e:
        _check_preview_auth(r, "__preview__")
    assert e.value.status_code == 401


def test_le_bon_token_de_preview_passe():
    from bot.dashboard.routes.setup import _check_preview_auth

    r = MagicMock()
    r.app.state.wally.config.bot.dashboard_token = "le-vrai-token"
    r.headers = {"Authorization": "Bearer le-vrai-token"}
    _check_preview_auth(r, "__preview__")  # ne lève pas


# ────────────────────────────── C25 ──────────────────────────────
@pytest.mark.asyncio
async def test_l_historique_des_emotions_est_plafonne():
    from bot.db.mixins.emotion import EmotionMixin

    vues = {}

    class _DB(EmotionMixin):
        async def fetch_all(self, query, params=()):
            vues["query"] = query
            vues["params"] = params
            return []

    await _DB().get_emotion_snapshots_since(0.0)
    assert "LIMIT" in vues["query"]
    assert vues["params"][1] > 0


@pytest.mark.asyncio
async def test_l_historique_reste_chronologique():
    """Le graphe attend un ordre croissant ; on prend les récents puis on inverse."""
    from bot.db.mixins.emotion import EmotionMixin

    class _DB(EmotionMixin):
        async def fetch_all(self, query, params=()):
            # La requête trie DESC : la base rendrait les plus récents d'abord.
            return [{"snapshot_at": 30.0}, {"snapshot_at": 20.0}, {"snapshot_at": 10.0}]

    out = await _DB().get_emotion_snapshots_since(0.0)
    assert [r["snapshot_at"] for r in out] == [10.0, 20.0, 30.0]


# ────────────────────────────── C26 ──────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("valeur", [float("nan"), float("inf"), float("-inf")])
async def test_une_telemetrie_non_finie_est_un_400_pas_un_500(valeur):
    from bot.dashboard.routes.overlay import overlay_health

    r = MagicMock()
    r.json = AsyncMock(return_value={"fps": valeur, "worst_frame_ms": 12})
    r.app.state.wally = MagicMock()

    with pytest.raises(HTTPException) as e:
        await overlay_health(r)
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_une_telemetrie_normale_passe_toujours():
    from bot.dashboard.routes.overlay import overlay_health

    etat = MagicMock()
    r = MagicMock()
    r.json = AsyncMock(return_value={"fps": 60, "worst_frame_ms": 18, "gpu": "RTX"})
    r.app.state.wally = etat

    assert (await overlay_health(r))["ok"] is True
    assert etat.overlay_health["fps"] == 60


@pytest.mark.asyncio
async def test_un_booleen_nest_pas_un_fps():
    from bot.dashboard.routes.overlay import overlay_health

    r = MagicMock()
    r.json = AsyncMock(return_value={"fps": True, "worst_frame_ms": 10})
    r.app.state.wally = MagicMock()

    with pytest.raises(HTTPException) as e:
        await overlay_health(r)
    assert e.value.status_code == 400


def test_json_loads_accepte_bien_nan():
    """Le point de départ du défaut : ce n'est pas une hypothèse."""
    import json

    assert math.isnan(json.loads('{"fps": NaN}')["fps"])
