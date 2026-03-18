# tests/test_dashboard_links.py
"""Tests pour les routes de liaison de comptes."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_app():
    """Crée une app FastAPI de test avec un state mocké."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bot.dashboard.routes.links import router

    app = FastAPI()
    app.include_router(router, prefix="/api/admin")

    state = MagicMock()
    state.db.list_link_proposals = AsyncMock(return_value=[
        {"id": 1, "canonical_id": "discord:123", "alias_id": "twitch:abc",
         "confidence": 0.85, "status": "pending", "created_at": 1000.0, "resolved_at": None}
    ])
    state.db.accept_link = AsyncMock(return_value={"canonical_id": "discord:123", "alias_id": "twitch:abc"})
    state.db.reject_link = AsyncMock()
    state.memory = MagicMock()
    state.memory._alias_cache = {}
    state.memory._mem0 = MagicMock()
    state.memory._mem0.get_all = MagicMock(return_value=[])
    state.config.bot.link_min_confidence = 0.75
    app.state.wally = state

    return TestClient(app)


def test_list_links():
    """GET /api/admin/links retourne la liste des propositions."""
    client = make_app()
    resp = client.get("/api/admin/links")
    assert resp.status_code == 200
    data = resp.json()
    assert "proposals" in data
    assert len(data["proposals"]) == 1


def test_reject_link():
    """POST /api/admin/links/1/reject rejette la liaison."""
    client = make_app()
    resp = client.post("/api/admin/links/1/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_accept_link_updates_alias_cache():
    """POST /api/admin/links/1/accept met à jour le cache d'alias."""
    client = make_app()
    resp = client.post("/api/admin/links/1/accept")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    # Le cache doit être mis à jour
    assert client.app.state.wally.memory._alias_cache.get("twitch:abc") == "discord:123"
