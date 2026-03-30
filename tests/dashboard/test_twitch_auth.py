from __future__ import annotations
import os, pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from bot.dashboard.routes import twitch_auth
from bot.dashboard.auth import BearerAuthMiddleware

def _make_app(bot_token="", streamer_token=""):
    app = FastAPI()
    state = MagicMock()
    state.config.bot.dashboard_token = "test-token"
    tm = MagicMock()
    tm.bot_token = bot_token
    tm.streamer_token = streamer_token
    twitch_bot = MagicMock()
    twitch_bot.token_manager = tm
    state.twitch_bot = twitch_bot
    app.state.wally = state
    app.add_middleware(BearerAuthMiddleware, state=state)
    app.include_router(twitch_auth.router, prefix="/api/admin")
    return app

H = {"Authorization": "Bearer test-token"}

def test_auth_status_no_tokens():
    with patch.object(twitch_auth, "_validate_token", new=AsyncMock(return_value=None)):
        client = TestClient(_make_app())
        r = client.get("/api/admin/twitch/auth-status", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["bot"]["connected"] is False
    assert d["streamer"]["connected"] is False

def test_auth_status_bot_connected():
    info = {"username": "WallyTeBully", "user_id": "961407719"}
    with patch.object(twitch_auth, "_validate_token", new=AsyncMock(side_effect=[info, None])):
        client = TestClient(_make_app(bot_token="valid"))
        r = client.get("/api/admin/twitch/auth-status", headers=H)
    assert r.json()["bot"]["connected"] is True
    assert r.json()["bot"]["username"] == "WallyTeBully"

def test_auth_url_bot():
    with patch.dict(os.environ, {"TWITCH_CLIENT_ID": "cid", "WEB_BASE_URL": "https://ex.com"}):
        client = TestClient(_make_app())
        r = client.post("/api/admin/twitch/auth-url", json={"account":"bot"}, headers=H)
    assert r.status_code == 200
    assert "id.twitch.tv/oauth2/authorize" in r.json()["url"]
    assert "user%3Aread%3Achat" in r.json()["url"] or "user:read:chat" in r.json()["url"]

def test_auth_url_streamer():
    with patch.dict(os.environ, {"TWITCH_CLIENT_ID": "cid", "WEB_BASE_URL": "https://ex.com"}):
        client = TestClient(_make_app())
        r = client.post("/api/admin/twitch/auth-url", json={"account":"streamer"}, headers=H)
    assert "channel" in r.json()["url"]

def test_auth_url_missing_client_id():
    env = {k:v for k,v in os.environ.items() if k != "TWITCH_CLIENT_ID"}
    with patch.dict(os.environ, env, clear=True):
        client = TestClient(_make_app())
        r = client.post("/api/admin/twitch/auth-url", json={"account":"bot"}, headers=H)
    assert r.status_code == 400

def test_callback_invalid_state():
    client = TestClient(_make_app())
    r = client.get("/api/admin/twitch/auth/callback?code=x&state=nonexistent", headers=H)
    assert r.status_code == 200
    assert "xpir" in r.text.lower() or "nvalid" in r.text.lower() or "erreur" in r.text.lower()

def test_callback_success():
    """Test le flux complet du callback OAuth : échange de code, écriture .env, SSE."""
    app = _make_app()

    # Insérer un state valide directement dans le module
    import time
    state_key = "validstate123"
    twitch_auth._pending_states[state_key] = {
        "account": "bot",
        "expires_at": time.time() + 600,
    }

    token_response = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
    }
    user_response = {
        "data": [{"display_name": "WallyTeBully", "id": "961407719"}]
    }

    import httpx

    class _MockClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def post(self, *a, **kw):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = token_response
            return resp
        async def get(self, *a, **kw):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = user_response
            return resp

    import os
    with patch.dict(os.environ, {"TWITCH_CLIENT_ID": "cid", "TWITCH_CLIENT_SECRET": "secret", "WEB_BASE_URL": "https://ex.com"}):
        with patch("httpx.AsyncClient", return_value=_MockClient()):
            with patch.object(twitch_auth, "broadcast_event") as mock_broadcast:
                client = TestClient(app)
                r = client.get(
                    f"/api/admin/twitch/auth/callback?code=authcode&state={state_key}",
                    headers=H,
                )

    assert r.status_code == 200
    assert "connecte" in r.text.lower()
    mock_broadcast.assert_called_once()
    call_args = mock_broadcast.call_args[0][0]
    assert call_args["type"] == "twitch_auth"
    assert call_args["account"] == "bot"
    assert call_args["username"] == "WallyTeBully"
