"""Tests that /api/public/status exposes owner_discord_id and bot_name."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from bot.dashboard.routes import status


def _client(owner_discord_id: str, name: str) -> TestClient:
    app = FastAPI()
    app.include_router(status.router, prefix="/api/public")
    app.state.wally = SimpleNamespace(
        start_time=0.0,
        message_count=0,
        message_count_discord=0,
        message_count_twitch=0,
        message_count_web=0,
        discord_bot=None,
        twitch_bot=None,
        avg_response_ms=None,
        config=SimpleNamespace(
            bot=SimpleNamespace(
                owner_discord_id=owner_discord_id,
                name=name,
            )
        ),
    )
    return TestClient(app)


def test_status_exposes_owner_discord_id():
    r = _client("42", "Cindy").get("/api/public/status")
    assert r.status_code == 200
    assert r.json()["owner_discord_id"] == "42"


def test_status_exposes_bot_name():
    r = _client("42", "Cindy").get("/api/public/status")
    assert r.status_code == 200
    assert r.json()["bot_name"] == "Cindy"


def test_status_owner_reflects_config():
    """Wally config: owner_discord_id matches the real owner."""
    r = _client("610550333042589752", "Wally").get("/api/public/status")
    assert r.status_code == 200
    data = r.json()
    assert data["owner_discord_id"] == "610550333042589752"
    assert data["bot_name"] == "Wally"
