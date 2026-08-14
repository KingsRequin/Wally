"""Tests pour les boutons de redémarrage du dashboard (`/bot/restart` et
`/twitch/restart`), qui doivent passer par le pont hôte (`HostBridgeClient`)
plutôt que par un `docker compose` local — impossible depuis l'intérieur du
container (ni le binaire, ni le compose file, ni le socket Docker n'y sont
montés).

Aucun test ici ne redémarre quoi que ce soit réellement : `HostBridgeClient`
est exercé via ses méthodes `health`/`docker_restart`, patchées au niveau
classe. Le comportement observable seul est vérifié (code HTTP, corps JSON) —
jamais une ligne d'implémentation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.dashboard.auth import BearerAuthMiddleware
from bot.dashboard.routes import admin, twitch_auth
from bot.intelligence.host_bridge import HostBridgeClient

H = {"Authorization": "Bearer test-token"}


def _make_app(router) -> FastAPI:
    app = FastAPI()
    state = MagicMock()
    state.config.bot.dashboard_token = "test-token"
    app.state.wally = state
    app.add_middleware(BearerAuthMiddleware, state=state)
    app.include_router(router, prefix="/api/admin")
    return app


@pytest.fixture(autouse=True)
def _bridge_env(monkeypatch):
    """Isole BRIDGE_SOCKET_PATH/BRIDGE_SECRET du vrai environnement de prod."""
    monkeypatch.delenv("BRIDGE_SECRET", raising=False)
    monkeypatch.delenv("BRIDGE_SOCKET_PATH", raising=False)
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)


@pytest.mark.parametrize(
    "path,router",
    [("/bot/restart", admin.router), ("/twitch/restart", twitch_auth.router)],
)
class TestRestartRoutes:
    def test_no_secret_configured_is_explicit_failure(self, path, router):
        client = TestClient(_make_app(router))
        r = client.post(f"/api/admin{path}", headers=H)
        assert r.status_code == 503
        assert "non configur" in r.json()["detail"].lower()

    def test_bridge_unreachable_is_explicit_failure(self, path, router, monkeypatch):
        monkeypatch.setenv("BRIDGE_SECRET", "supersecret")
        with patch.object(HostBridgeClient, "health", new=AsyncMock(return_value=False)):
            client = TestClient(_make_app(router))
            r = client.post(f"/api/admin{path}", headers=H)
        assert r.status_code == 503
        assert "injoignable" in r.json()["detail"].lower()

    def test_dispatch_failure_surfaces_real_error(self, path, router, monkeypatch):
        monkeypatch.setenv("BRIDGE_SECRET", "supersecret")
        with patch.object(HostBridgeClient, "health", new=AsyncMock(return_value=True)), \
             patch.object(
                 HostBridgeClient, "docker_restart",
                 new=AsyncMock(side_effect=RuntimeError("service not allowed")),
             ):
            client = TestClient(_make_app(router))
            r = client.post(f"/api/admin{path}", headers=H)
        assert r.status_code == 503
        assert "service not allowed" in r.json()["detail"]

    def test_success_reports_ok_true(self, path, router, monkeypatch):
        monkeypatch.setenv("BRIDGE_SECRET", "supersecret")
        docker_restart = AsyncMock(return_value=None)
        with patch.object(HostBridgeClient, "health", new=AsyncMock(return_value=True)), \
             patch.object(HostBridgeClient, "docker_restart", new=docker_restart):
            client = TestClient(_make_app(router))
            r = client.post(f"/api/admin{path}", headers=H)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        docker_restart.assert_awaited_once_with("wally")
