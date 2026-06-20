from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from bot.dashboard.routes import status


def _client(avg):
    app = FastAPI()
    app.include_router(status.router, prefix="/api/public")
    app.state.wally = SimpleNamespace(
        start_time=0.0, message_count=0, message_count_discord=0,
        message_count_twitch=0, message_count_web=0,
        discord_bot=None, twitch_bot=None, config=SimpleNamespace(),
        avg_response_ms=avg,
    )
    return TestClient(app)


def test_status_includes_avg_response_ms():
    r = _client(123.4).get("/api/public/status")
    assert r.status_code == 200
    assert r.json()["avg_response_ms"] == 123.4
