# tests/test_admin_update.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from tests.test_dashboard_routes import _make_state


def _make_state_with_checker(update_available: bool):
    state = _make_state()
    checker = MagicMock()
    checker.update_available = update_available
    state.update_checker = checker
    return state


@pytest.fixture
async def client_with_update():
    state = _make_state_with_checker(update_available=True)
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def client_no_update():
    state = _make_state_with_checker(update_available=False)
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def client_no_checker():
    state = _make_state()
    state.update_checker = None
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_bot_status_update_available_true(client_with_update):
    r = await client_with_update.get(
        "/api/admin/bot/status",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["update_available"] is True


@pytest.mark.asyncio
async def test_bot_status_update_available_false(client_no_update):
    r = await client_no_update.get(
        "/api/admin/bot/status",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["update_available"] is False


@pytest.mark.asyncio
async def test_bot_status_no_checker_returns_false(client_no_checker):
    r = await client_no_checker.get(
        "/api/admin/bot/status",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["update_available"] is False


@pytest.mark.asyncio
async def test_config_has_no_is_main_field(client_no_checker):
    """Le champ is_main ne doit plus exister dans GET /config."""
    r = await client_no_checker.get(
        "/api/admin/config",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert "is_main" not in r.json()
