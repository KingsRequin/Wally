# tests/test_dashboard_public_ui.py
"""Tests pour la séparation Public UI / Admin."""
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
import pytest
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app, _maybe_seed_public_ui
from bot.dashboard.state import AppState


def _make_state() -> AppState:
    emotion = MagicMock()
    emotion.get_state.return_value = {
        "anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.1
    }
    db = MagicMock()
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.insert_emotion_snapshot = AsyncMock()
    db.create_setup_invite = AsyncMock()
    cfg = MagicMock()
    cfg.bot.dashboard_token = "testtoken"
    cfg.bot.cost_alert_threshold = 0
    return AppState(
        config=cfg, db=db, emotion=emotion,
        memory=MagicMock(), persona=MagicMock(),
        primary_llm=MagicMock(), secondary_llm=MagicMock(),
        image_client=MagicMock(), token_manager=MagicMock(),
        twitch_api=None, discord_bot=None, twitch_bot=None,
        start_time=time.time() - 100, message_count=0,
    )


# ── _maybe_seed_public_ui ──────────────────────────────────────────────────────

def test_seed_copies_files_when_target_empty(tmp_path):
    """Copie les fichiers starter si public-ui/ est vide."""
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "index.html").write_text("<html>starter</html>")
    (starter / "style.css").write_text("body{}")
    target = tmp_path / "public-ui"
    target.mkdir()

    _maybe_seed_public_ui(starter_dir=starter, public_ui_dir=target)

    assert (target / "index.html").read_text() == "<html>starter</html>"
    assert (target / "style.css").read_text() == "body{}"


def test_seed_does_not_overwrite_existing(tmp_path):
    """Ne touche pas public-ui/ si des fichiers existent déjà."""
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "index.html").write_text("<html>starter</html>")
    target = tmp_path / "public-ui"
    target.mkdir()
    (target / "index.html").write_text("<html>custom</html>")

    _maybe_seed_public_ui(starter_dir=starter, public_ui_dir=target)

    assert (target / "index.html").read_text() == "<html>custom</html>"


def test_seed_creates_target_if_missing(tmp_path):
    """Crée public-ui/ s'il n'existe pas du tout."""
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "index.html").write_text("<html>starter</html>")
    target = tmp_path / "public-ui"  # n'existe pas

    _maybe_seed_public_ui(starter_dir=starter, public_ui_dir=target)

    assert (target / "index.html").exists()


def test_seed_noop_when_starter_missing(tmp_path):
    """Ne plante pas si le répertoire starter n'existe pas."""
    starter = tmp_path / "starter-missing"
    target = tmp_path / "public-ui"
    target.mkdir()

    _maybe_seed_public_ui(starter_dir=starter, public_ui_dir=target)

    assert not list(target.iterdir())


# ── Routing ────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_with_public_ui(tmp_path, monkeypatch):
    """App avec un public-ui/ temporaire contenant un index.html minimal."""
    public_ui = tmp_path / "public-ui"
    public_ui.mkdir()
    (public_ui / "index.html").write_text("<html><body>public</body></html>")
    (public_ui / "style.css").write_text("body{color:red}")
    monkeypatch.setattr("bot.dashboard.app.PUBLIC_UI_DIR", public_ui)
    return create_dashboard_app(_make_state())


def test_app_starts_without_public_ui(tmp_path, monkeypatch):
    """L'app démarre sans planter quand public-ui/ n'existe pas."""
    missing = tmp_path / "nonexistent-public-ui"
    monkeypatch.setattr("bot.dashboard.app.PUBLIC_UI_DIR", missing)
    # Should not raise
    app = create_dashboard_app(_make_state())
    assert app is not None


@pytest.fixture
async def client(app_with_public_ui):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_public_ui), base_url="http://test"
    ) as c:
        yield c


async def test_admin_route_returns_html(client):
    """/admin sert le panel admin (index.html embarqué)."""
    r = await client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


async def test_root_returns_public_ui(client):
    """/ sert public-ui/index.html."""
    r = await client.get("/")
    assert r.status_code == 200
    assert b"public" in r.content


async def test_spa_deep_link_returns_public_ui(client):
    """/une-page retourne public-ui/index.html (SPA fallback)."""
    r = await client.get("/une-page")
    assert r.status_code == 200
    assert b"public" in r.content


async def test_static_asset_served(client):
    """/style.css retourne le fichier CSS de public-ui."""
    r = await client.get("/style.css")
    assert r.status_code == 200
    assert b"color:red" in r.content


async def test_api_not_intercepted_by_spa(client):
    """/api/public/status n'est pas intercepté par le SPA fallback."""
    r = await client.get("/api/public/status")
    assert r.status_code == 200
    assert "uptime_seconds" in r.json()
