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
    state.db.upsert_link_proposal = AsyncMock()
    state.db.list_memory_users = AsyncMock(return_value=[])
    state.memory = MagicMock()
    state.memory._alias_cache = {}
    state.memory._init_mem0 = MagicMock()
    state.memory._mem0 = MagicMock()
    state.memory._mem0.get_all = MagicMock(return_value=[])
    state.memory._mem0.delete_all = MagicMock()
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
    # Le cache doit être mis à jour
    assert client.app.state.wally.memory._alias_cache.get("twitch:abc") == "discord:123"


def test_manual_link():
    """POST /api/admin/links/manual crée et auto-accepte une liaison."""
    client = make_app()
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
    state.memory._init_mem0 = MagicMock()
    state.memory._mem0 = MagicMock()
    state.memory._mem0.get_all = MagicMock(return_value=[
        {"memory": "aime Python"},
        {"memory": "joue à Minecraft"},
    ])
    state.memory._mem0.add = MagicMock()
    state.memory._mem0.delete_all = MagicMock()
    app.state.wally = state

    client = TestClient(app)
    resp = client.post("/api/admin/links/1/accept")
    assert resp.status_code == 200
    # Mémoires copiées vers canonical
    assert state.memory._mem0.add.call_count == 2
    # Ancien namespace nettoyé
    state.memory._mem0.delete_all.assert_called_once_with(user_id="twitch:abc")
    # memory_user supprimé
    state.db.delete_memory_user.assert_awaited_once_with("twitch:abc")


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
    state.memory._init_mem0 = MagicMock()
    state.memory._mem0 = MagicMock()
    state.memory._mem0.get_all = MagicMock(return_value=[
        {"memory": "aime Python"},
        {"memory": "joue à Minecraft"},
    ])
    # Deuxième appel à add échoue
    state.memory._mem0.add = MagicMock(side_effect=[None, Exception("mem0 error")])
    state.memory._mem0.delete_all = MagicMock()
    app.state.wally = state

    client = TestClient(app)
    resp = client.post("/api/admin/links/1/accept")
    assert resp.status_code == 200
    # Alias NON supprimé car copie partielle
    state.db.delete_memory_user.assert_not_awaited()
    state.memory._mem0.delete_all.assert_not_called()


def test_accept_link_mem0_none():
    """Si mem0 n'est pas disponible, la liaison est acceptée sans fusion."""
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
    state.memory._init_mem0 = MagicMock()
    state.memory._mem0 = None  # mem0 non disponible
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
