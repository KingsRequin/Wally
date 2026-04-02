# tests/test_setup_routes.py
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from tests.test_dashboard_routes import _make_config, _make_state


def _make_full_state(**overrides) -> AppState:
    state = _make_state(**overrides)
    db = MagicMock()
    db.insert_emotion_snapshot = AsyncMock()
    db.create_setup_invite = AsyncMock()
    db.list_setup_invites = AsyncMock(return_value=[])
    db.get_setup_invite = AsyncMock(return_value=None)
    db.revoke_setup_invite = AsyncMock()
    db.next_setup_port = AsyncMock(return_value=8081)
    db.save_setup_session = AsyncMock()
    db.get_setup_session = AsyncMock(return_value={})
    db.use_setup_invite = AsyncMock()
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    state.db = db
    return state


@pytest.fixture
async def client():
    state = _make_full_state()
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, state


@pytest.mark.asyncio
async def test_generate_invite_requires_auth(client):
    c, _ = client
    resp = await c.post("/api/admin/setup/invite")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_generate_invite_ok(client):
    c, state = client
    resp = await c.post(
        "/api/admin/setup/invite",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert "url" in body
    assert len(body["token"]) > 10
    state.db.create_setup_invite.assert_called_once()


@pytest.mark.asyncio
async def test_list_invites_ok(client):
    c, state = client
    state.db.list_setup_invites = AsyncMock(return_value=[])
    resp = await c.get(
        "/api/admin/setup/invites",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert resp.status_code == 200
    assert "invites" in resp.json()


@pytest.mark.asyncio
async def test_revoke_invite_ok(client):
    c, state = client
    resp = await c.delete(
        "/api/admin/setup/invite/tok123",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert resp.status_code == 200
    state.db.revoke_setup_invite.assert_called_once_with("tok123")


@pytest.mark.asyncio
async def test_wizard_save_invalid_token(client):
    c, state = client
    state.db.get_setup_invite = AsyncMock(return_value=None)
    resp = await c.post("/api/setup/badtoken/save", json={"foo": "bar"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_wizard_save_expired_token(client):
    c, state = client
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "expires_at": time.time() - 1, "used_at": None, "is_preview": 0
    }[k]
    state.db.get_setup_invite = AsyncMock(return_value=row)
    resp = await c.post("/api/setup/expiredtok/save", json={"foo": "bar"})
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_wizard_validate_discord_bad_token(client):
    c, state = client
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "expires_at": time.time() + 3600, "used_at": None, "is_preview": 0
    }[k]
    state.db.get_setup_invite = AsyncMock(return_value=row)
    with patch("bot.dashboard.routes.setup.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=401))
        mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
        resp = await c.post(
            "/api/setup/tok/validate-discord",
            json={"discord_token": "badtoken"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


@pytest.mark.asyncio
async def test_submit_wizard(client):
    c, state = client
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "expires_at": time.time() + 3600, "used_at": None, "is_preview": 0,
        "token": "tok999",
    }[k]
    state.db.get_setup_invite = AsyncMock(return_value=row)
    state.db.get_setup_session = AsyncMock(return_value={"bot_name": "cindy"})
    state.db.use_setup_invite = AsyncMock()
    resp = await c.post("/api/setup/tok999/submit", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["slug"] == "cindy"
    assert not data["dry_run"]
    state.db.use_setup_invite.assert_awaited_once()
