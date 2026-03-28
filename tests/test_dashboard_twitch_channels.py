from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from bot.dashboard.routes.admin import router

@pytest.fixture
def app_with_twitch():
    app = FastAPI()
    app.include_router(router, prefix="/api/admin")

    mock_bot = MagicMock()
    mock_bot._channel_ids = {"keychka": "169154332", "streamer2": "999000111"}
    mock_bot._channel_was_live = {"keychka": True, "streamer2": False}
    mock_bot.get_channel.side_effect = lambda name: MagicMock() if name == "keychka" else None

    state = MagicMock()
    state.twitch_bot = mock_bot
    app.state.wally = state
    return TestClient(app)

def test_get_twitch_channels_returns_list(app_with_twitch):
    r = app_with_twitch.get("/api/admin/twitch/channels", headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2

def test_get_twitch_channels_irc_status(app_with_twitch):
    r = app_with_twitch.get("/api/admin/twitch/channels", headers={"Authorization": "Bearer test"})
    channels = {c["name"]: c for c in r.json()}
    assert channels["keychka"]["irc_connected"] is True
    assert channels["streamer2"]["irc_connected"] is False

def test_get_twitch_channels_live_status(app_with_twitch):
    r = app_with_twitch.get("/api/admin/twitch/channels", headers={"Authorization": "Bearer test"})
    channels = {c["name"]: c for c in r.json()}
    assert channels["keychka"]["live"] is True
    assert channels["streamer2"]["live"] is False

def test_get_twitch_channels_no_bot_returns_503(app_with_twitch):
    app_with_twitch.app.state.wally.twitch_bot = None
    r = app_with_twitch.get("/api/admin/twitch/channels", headers={"Authorization": "Bearer test"})
    assert r.status_code == 503
