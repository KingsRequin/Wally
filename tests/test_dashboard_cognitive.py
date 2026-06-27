import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bot.dashboard.routes.cognitive import public_router


def _client(*, event_store=None, fact_store=None):
    app = FastAPI()
    app.include_router(public_router, prefix="/api/public")
    wally = MagicMock()
    wally.cognitive_event_store = event_store
    wally.fact_store = fact_store
    app.state.wally = wally
    return TestClient(app)


# ── A6 : historique ──

def test_history_returns_events_and_next_before():
    store = MagicMock()
    store.recent = AsyncMock(return_value=[
        {"id": 9, "type": "THINK", "text": "a"},
        {"id": 7, "type": "ACT", "detail": "b"},
    ])
    r = _client(event_store=store).get("/api/public/cognitive/history?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["events"]) == 2
    assert body["next_before"] == 7


def test_history_no_store_returns_empty():
    r = _client(event_store=None).get("/api/public/cognitive/history")
    assert r.json() == {"events": [], "next_before": None}


# ── A7 : but courant ──

def test_goal_route_shape():
    from bot.intelligence.memory.facts import FactCategory
    store = MagicMock()

    async def by_cat(cat, status=None, limit=10):
        if cat == FactCategory.GOAL:
            return [MagicMock(content="dominer Apex")]
        if cat == FactCategory.DESIRE:
            return [MagicMock(content="comprendre Kaelis")]
        return []

    store.search_by_category = AsyncMock(side_effect=by_cat)
    store.get_latest_by_source = AsyncMock(return_value=MagicMock(content="le silence de KingsRequin"))
    r = _client(fact_store=store).get("/api/public/cognitive/goal")
    body = r.json()
    assert body["goals"] == ["dominer Apex"]
    assert body["preoccupation"] == "le silence de KingsRequin"
    assert body["desires"] == ["comprendre Kaelis"]


def test_goal_route_no_store():
    r = _client(fact_store=None).get("/api/public/cognitive/goal")
    assert r.json() == {"goals": [], "preoccupation": None, "desires": []}
