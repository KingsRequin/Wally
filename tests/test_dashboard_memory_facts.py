import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bot.dashboard.routes.memory import router


def _client(fact_store=None):
    app = FastAPI()
    app.include_router(router)
    wally = MagicMock()
    wally.fact_store = fact_store
    app.state.wally = wally
    return TestClient(app)


# ── C1 : détail utilisateur (faits S-P-O) ──

def test_user_detail_returns_facts():
    from bot.intelligence.memory.facts import AtomicFact, FactCategory
    store = MagicMock()
    f = AtomicFact(user_id="discord:1", content="aime le jazz",
                   category=FactCategory.FAIT, confidence=0.9,
                   subject="Pierre", predicate="aime", object_="le jazz")
    f.id = 3
    store.get_by_user = AsyncMock(return_value=[f])
    r = _client(fact_store=store).get("/memory/users/discord:1")
    body = r.json()
    assert body["user_id"] == "discord:1"
    assert len(body["facts"]) == 1
    assert body["facts"][0]["content"] == "aime le jazz"
    assert body["facts"][0]["category"] == "FAIT"
    assert body["facts"][0]["subject"] == "Pierre"
    store.get_by_user.assert_awaited_once_with("discord:1")


def test_user_detail_no_store():
    r = _client(fact_store=None).get("/memory/users/discord:1")
    assert r.json()["facts"] == []


# ── C2 : mémoire interne de Wally ──

def test_self_route_shape():
    from bot.intelligence.memory.facts import FactCategory
    store = MagicMock()

    async def by_cat(c, status=None, limit=10):
        return {
            FactCategory.GOAL: [MagicMock(content="dominer Apex")],
            FactCategory.DESIRE: [MagicMock(content="comprendre Kaelis")],
            FactCategory.THOUGHT: [MagicMock(content="je doute")],
        }.get(c, [])

    store.search_by_category = AsyncMock(side_effect=by_cat)
    store.get_by_user = AsyncMock(return_value=[MagicMock(content="Kaelis — drôle")])
    store.get_latest_by_source = AsyncMock(return_value=MagicMock(content="le silence"))
    r = _client(fact_store=store).get("/memory/self")
    body = r.json()
    assert body["goals"] == ["dominer Apex"]
    assert body["desires"] == ["comprendre Kaelis"]
    assert body["thoughts"] == ["je doute"]
    assert body["relationships"] == ["Kaelis — drôle"]
    assert body["focus"] == "le silence"


def test_self_route_no_store():
    r = _client(fact_store=None).get("/memory/self")
    assert r.json() == {"goals": [], "desires": [], "thoughts": [],
                        "relationships": [], "focus": None}
