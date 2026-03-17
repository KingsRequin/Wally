import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bot.dashboard.auth import BearerAuthMiddleware


def _make_app(token: str | None) -> FastAPI:
    """Helper : app minimale avec middleware auth et une route admin."""
    cfg = MagicMock()
    cfg.bot.dashboard_token = token
    state = MagicMock()
    state.config = cfg

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, state=state)

    @app.get("/api/admin/test")
    async def admin_route():
        return {"ok": True}

    @app.get("/api/public/test")
    async def public_route():
        return {"ok": True}

    @app.get("/api/admin/sse/logs")
    async def sse_logs_route():
        return {"ok": True}

    return app


def test_public_route_no_auth_required():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/public/test")
    assert r.status_code == 200


def test_admin_valid_token():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer secret123"})
    assert r.status_code == 200


def test_admin_invalid_token_returns_401():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_admin_no_token_header_returns_401():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test")
    assert r.status_code == 401


def test_admin_token_not_configured_returns_503():
    client = TestClient(_make_app(None))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503


def test_admin_empty_token_returns_503():
    client = TestClient(_make_app(""))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503


def test_sse_logs_exempt_from_auth():
    """EventSource ne peut pas envoyer de headers — la route SSE doit être accessible sans token."""
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/sse/logs")
    assert r.status_code == 200
