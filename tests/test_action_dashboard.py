"""Tests for dashboard action endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from bot.dashboard.routes.actions import router


def _make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/actions")

    state = MagicMock()
    state.db = AsyncMock()
    state.db.list_action_tasks = AsyncMock(return_value=[
        {"id": 1, "action_type": "reminder", "description": "test",
         "status": "active", "creator_id": "123", "creator_platform": "discord",
         "target_channel": "456", "target_platform": "discord",
         "payload": '{}', "schedule_type": "once", "schedule_spec": '{}',
         "max_executions": 1, "execution_count": 0, "consecutive_failures": 0,
         "last_error": None, "created_at": "2026-03-22T10:00:00",
         "updated_at": "2026-03-22T10:00:00", "next_run_at": "2026-03-23T18:00:00",
         "last_run_at": None},
    ])
    state.db.get_action_task = AsyncMock(return_value={
        "id": 1, "status": "active", "description": "test",
    })
    state.db.list_action_permissions = AsyncMock(return_value=[
        {"action_type": "reminder", "min_role_discord": "everyone",
         "min_role_twitch": "admin", "enabled": 1},
    ])

    action_service = MagicMock()
    action_service.cancel = AsyncMock(return_value={"status": "cancelled", "task": {"id": 1, "description": "test"}})
    action_service.pause_task = AsyncMock()
    action_service.resume_task = AsyncMock()
    action_service.execute_task_now = AsyncMock(return_value="OK")
    action_service.update_permission = AsyncMock()
    action_service.set_action_enabled = AsyncMock()
    action_service._registry = MagicMock()
    action_service._registry.get_discord_roles_for_action = AsyncMock(return_value={})
    action_service._registry.update_discord_permission = AsyncMock()

    state.action_service = action_service
    state.discord_bot = None
    app.state.wally = state
    return app


def test_list_tasks():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/actions/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 1


def test_cancel_task():
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/api/actions/tasks/1/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_pause_task():
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/api/actions/tasks/1/pause")
    assert resp.status_code == 200


def test_resume_task():
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/api/actions/tasks/1/resume")
    assert resp.status_code == 200


def test_list_permissions():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/actions/permissions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["permissions"]) == 1


def test_update_permission():
    app = _make_app()
    client = TestClient(app)
    resp = client.put(
        "/api/actions/permissions/reminder",
        json={"min_role_twitch": "vip", "enabled": True},
    )
    assert resp.status_code == 200


def test_discord_roles_no_bot():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/actions/discord-roles")
    assert resp.status_code == 200
    assert resp.json() == {"guilds": []}


def test_update_discord_permission():
    app = _make_app()
    client = TestClient(app)
    resp = client.put(
        "/api/actions/permissions/reminder/discord",
        json={"guild_id": "111", "role_ids": ["everyone", "222"]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_update_discord_permission_no_guild():
    app = _make_app()
    client = TestClient(app)
    resp = client.put(
        "/api/actions/permissions/reminder/discord",
        json={"role_ids": ["everyone"]},
    )
    assert resp.status_code == 200
    assert "error" in resp.json()


def test_list_permissions_includes_discord_roles():
    app = _make_app()
    app.state.wally.action_service._registry.get_discord_roles_for_action = AsyncMock(
        return_value={"111": [{"role_id": "everyone", "role_name": "everyone"}]}
    )
    client = TestClient(app)
    resp = client.get("/api/actions/permissions")
    assert resp.status_code == 200
    perms = resp.json()["permissions"]
    assert len(perms) == 1
    assert "discord_roles" in perms[0]
    assert "111" in perms[0]["discord_roles"]
