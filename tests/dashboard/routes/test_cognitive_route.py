from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from bot.v2.core.cognitive_feed import CognitiveFeed
from bot.dashboard.routes import cognitive


def _app_with_feed(feed):
    app = FastAPI()
    app.include_router(cognitive.public_router, prefix="/api/public")
    app.state.wally = SimpleNamespace(cognitive_feed=feed)
    return app


def test_state_returns_buffer_snapshot():
    feed = CognitiveFeed()
    feed.publish({"type": "THINK", "text": "salut"})
    r = TestClient(_app_with_feed(feed)).get("/api/public/cognitive/state")
    assert r.status_code == 200
    assert r.json()["events"][0]["type"] == "THINK"


def test_state_degrades_when_feed_absent():
    r = TestClient(_app_with_feed(None)).get("/api/public/cognitive/state")
    assert r.status_code == 200
    assert r.json() == {"events": []}
