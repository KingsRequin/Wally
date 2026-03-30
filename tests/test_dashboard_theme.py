"""Tests des routes de theming dashboard."""
import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import ThemeConfig


def _make_state_with_theme(accent="#06b6d4", layout="sidebar-left"):
    """AppState minimal avec ThemeConfig réel."""
    from tests.test_dashboard_routes import _make_state
    state = _make_state()
    state.config.theme = ThemeConfig(accent_color=accent, layout_variant=layout)
    return state


@pytest.fixture
def app():
    return create_dashboard_app(_make_state_with_theme())


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_theme_css_returns_200(client):
    r = await client.get("/static/theme.css")
    assert r.status_code == 200


async def test_theme_css_content_type(client):
    r = await client.get("/static/theme.css")
    assert "text/css" in r.headers["content-type"]


async def test_theme_css_contains_accent(client):
    r = await client.get("/static/theme.css")
    assert "--accent: #06b6d4" in r.text


async def test_theme_css_contains_layout_variant(client):
    r = await client.get("/static/theme.css")
    assert '--layout-variant: "sidebar-left"' in r.text


async def test_theme_css_contains_accent_soft(client):
    r = await client.get("/static/theme.css")
    assert "--accent-soft: rgba(6, 182, 212, 0.12)" in r.text


async def test_theme_css_no_cache(client):
    r = await client.get("/static/theme.css")
    assert "no-store" in r.headers.get("cache-control", "")


async def test_theme_css_custom_accent():
    """Accent personnalisé génère la bonne couleur."""
    app = create_dashboard_app(_make_state_with_theme(accent="#ff6b6b"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/static/theme.css")
    assert "--accent: #ff6b6b" in r.text
    assert "--accent-soft: rgba(255, 107, 107, 0.12)" in r.text


async def test_get_theme_returns_all_fields(client):
    r = await client.get("/api/admin/theme", headers={"Authorization": "Bearer testtoken"})
    assert r.status_code == 200
    data = r.json()
    assert "accent_color" in data
    assert "bg_color" in data
    assert "layout_variant" in data
    assert "tab_style" in data
    assert "surface_color" in data
    assert "sidebar_bg" in data


async def test_post_theme_updates_accent(client):
    r = await client.post(
        "/api/admin/theme",
        json={"accent_color": "#ff6b6b"},
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["accent_color"] == "#ff6b6b"


async def test_post_theme_rejects_invalid_color(client):
    r = await client.post(
        "/api/admin/theme",
        json={"accent_color": "notacolor"},
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 400


async def test_post_theme_rejects_invalid_layout(client):
    r = await client.post(
        "/api/admin/theme",
        json={"layout_variant": "top-bar"},
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 400


async def test_post_theme_calls_config_save(client):
    state = _make_state_with_theme()
    state.config.save = MagicMock()
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(
            "/api/admin/theme",
            json={"accent_color": "#aabbcc"},
            headers={"Authorization": "Bearer testtoken"},
        )
    state.config.save.assert_called_once()
