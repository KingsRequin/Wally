# tests/test_dashboard_links.py
"""Tests pour les routes de liaison de comptes."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from bot.core.memory_store import MemoryRecord


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
    state.db.upsert_link_proposal = AsyncMock()
    state.db.list_memory_users = AsyncMock(return_value=[])
    state.memory = MagicMock()
    state.memory._alias_cache = {}
    # Mock the store property to return an AsyncMock with store methods
    mock_store = AsyncMock()
    mock_store.get_all = AsyncMock(return_value=[])
    mock_store.delete_by_user = AsyncMock()
    mock_store.upsert = AsyncMock(return_value="new-id")
    type(state.memory).store = PropertyMock(return_value=mock_store)
    state.db.delete_memory_user = AsyncMock()
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
    # add_alias doit avoir été appelé
    client.app.state.wally.memory.add_alias.assert_called_once_with("twitch:abc", "discord:123")


def test_manual_link():
    """POST /api/admin/links/manual crée et auto-accepte une liaison."""
    client = make_app()
    # list_memory_users doit retourner les users pour que _resolve_user_id les trouve
    client.app.state.wally.db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:999", "platform": "discord", "last_updated": 1000.0,
         "username": "testdiscord", "trust_score": 0.5, "in_memory_users": True},
        {"user_id": "twitch:testuser", "platform": "twitch", "last_updated": 1000.0,
         "username": "testtwitch", "trust_score": 0.5, "in_memory_users": True},
    ])
    # Configurer list_link_proposals pour retourner le lien créé (pour l'auto-accept)
    client.app.state.wally.db.list_link_proposals = AsyncMock(return_value=[
        {"id": 99, "canonical_id": "discord:999", "alias_id": "twitch:testuser",
         "confidence": 1.0, "status": "pending", "created_at": 1000.0, "resolved_at": None}
    ])
    resp = client.post("/api/admin/links/manual", json={
        "canonical_id": "discord:999",
        "alias_id": "twitch:testuser",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["canonical_id"] == "discord:999"
    assert data["alias_id"] == "twitch:testuser"
    client.app.state.wally.db.upsert_link_proposal.assert_called_once_with("discord:999", "twitch:testuser", 1.0)


def test_accept_link_merges_memories():
    """accept_link copie les mémoires, supprime l'ancien namespace et memory_user."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bot.dashboard.routes.links import router

    app = FastAPI()
    app.include_router(router, prefix="/api/admin")

    state = MagicMock()
    state.db.accept_link = AsyncMock(return_value={"canonical_id": "discord:123", "alias_id": "twitch:abc"})
    state.db.delete_memory_user = AsyncMock()
    state.memory = MagicMock()
    state.memory._alias_cache = {}
    # Mock the store property
    mock_store = AsyncMock()
    mock_store.get_all = AsyncMock(return_value=[
        MemoryRecord(id="r1", text="aime Python", user_id="twitch:abc", category="FAIT", date="2026-01-01", source="fact_extractor", platform="twitch"),
        MemoryRecord(id="r2", text="joue à Minecraft", user_id="twitch:abc", category="FAIT", date="2026-01-01", source="fact_extractor", platform="twitch"),
    ])
    mock_store.upsert = AsyncMock(return_value="new-id")
    mock_store.delete_by_user = AsyncMock()
    type(state.memory).store = PropertyMock(return_value=mock_store)
    app.state.wally = state

    client = TestClient(app)
    resp = client.post("/api/admin/links/1/accept")
    assert resp.status_code == 200
    # Mémoires copiées vers canonical
    assert mock_store.upsert.call_count == 2
    # Ancien namespace store nettoyé
    mock_store.delete_by_user.assert_called_once_with("twitch:abc")
    # memory_users conservé (pour garder le username pour l'affichage)
    state.db.delete_memory_user.assert_not_awaited()


def test_accept_link_partial_failure_keeps_alias():
    """Si la copie échoue partiellement, l'alias n'est pas supprimé."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bot.dashboard.routes.links import router

    app = FastAPI()
    app.include_router(router, prefix="/api/admin")

    state = MagicMock()
    state.db.accept_link = AsyncMock(return_value={"canonical_id": "discord:123", "alias_id": "twitch:abc"})
    state.db.delete_memory_user = AsyncMock()
    state.memory = MagicMock()
    state.memory._alias_cache = {}
    mock_store = AsyncMock()
    mock_store.get_all = AsyncMock(return_value=[
        MemoryRecord(id="r1", text="aime Python", user_id="twitch:abc", category="FAIT", date="2026-01-01", source="fact_extractor", platform="twitch"),
        MemoryRecord(id="r2", text="joue à Minecraft", user_id="twitch:abc", category="FAIT", date="2026-01-01", source="fact_extractor", platform="twitch"),
    ])
    # Second upsert fails
    mock_store.upsert = AsyncMock(side_effect=[AsyncMock(return_value="new-id"), Exception("store error")])
    mock_store.delete_by_user = AsyncMock()
    type(state.memory).store = PropertyMock(return_value=mock_store)
    app.state.wally = state

    client = TestClient(app)
    resp = client.post("/api/admin/links/1/accept")
    assert resp.status_code == 200
    # Alias NON supprimé car copie partielle
    state.db.delete_memory_user.assert_not_awaited()
    mock_store.delete_by_user.assert_not_called()


def test_accept_link_store_none():
    """Si le store n'est pas disponible, la liaison est acceptée sans fusion."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bot.dashboard.routes.links import router

    app = FastAPI()
    app.include_router(router, prefix="/api/admin")

    state = MagicMock()
    state.db.accept_link = AsyncMock(return_value={"canonical_id": "discord:123", "alias_id": "twitch:abc"})
    state.db.delete_memory_user = AsyncMock()
    state.memory = MagicMock()
    state.memory._alias_cache = {}
    type(state.memory).store = PropertyMock(return_value=None)
    app.state.wally = state

    client = TestClient(app)
    resp = client.post("/api/admin/links/1/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    # Pas de tentative de fusion
    state.db.delete_memory_user.assert_not_awaited()


def test_manual_link_rejects_same_id():
    """POST /api/admin/links/manual rejette si les deux IDs sont identiques."""
    client = make_app()
    resp = client.post("/api/admin/links/manual", json={
        "canonical_id": "discord:123",
        "alias_id": "discord:123",
    })
    assert resp.status_code == 400
