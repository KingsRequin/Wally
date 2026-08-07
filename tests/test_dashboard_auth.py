import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bot.dashboard.auth import BearerAuthMiddleware, SseTickets


def _make_app(token: str | None) -> FastAPI:
    """Helper : app minimale avec middleware auth et une route admin."""
    cfg = MagicMock()
    cfg.bot.dashboard_token = token
    state = MagicMock()
    state.config = cfg
    state.sse_tickets = SseTickets()

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, state=state)
    app.state.tickets = state.sse_tickets

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


def test_sse_logs_refuse_sans_ticket():
    """Ces routes étaient servies SANS AUCUNE authentification — `/sse/logs`
    diffuse le contenu des DM Discord, et le port est publié sur 0.0.0.0."""
    client = TestClient(_make_app("secret123"))
    assert client.get("/api/admin/sse/logs").status_code == 401


def test_sse_logs_accepte_un_ticket_valide():
    """`EventSource` ne peut pas envoyer d'en-tête : un ticket à usage unique
    remplace le Bearer, sans laisser le token dans les logs d'accès."""
    app = _make_app("secret123")
    client = TestClient(app)
    ticket = app.state.tickets.issue()
    assert client.get(f"/api/admin/sse/logs?ticket={ticket}").status_code == 200


def test_un_ticket_ne_sert_qu_une_fois():
    app = _make_app("secret123")
    client = TestClient(app)
    ticket = app.state.tickets.issue()
    client.get(f"/api/admin/sse/logs?ticket={ticket}")
    assert client.get(f"/api/admin/sse/logs?ticket={ticket}").status_code == 401


def test_un_ticket_expire():
    tickets = SseTickets()
    ticket = tickets.issue()
    tickets._issued[ticket] = 0.0        # périmé
    assert tickets.consume(ticket) is False


def test_le_callback_twitch_reste_sans_auth():
    """Redirect de navigateur venu de Twitch : aucun en-tête possible, et la
    route valide elle-même le `state` OAuth."""
    from bot.dashboard.auth import _NO_AUTH
    assert "/api/admin/twitch/auth/callback" in _NO_AUTH


def test_middleware_is_pure_asgi_not_basehttp():
    """Régression bug 500 SSE : le middleware NE DOIT PAS hériter de
    BaseHTTPMiddleware (dont le pipe memory-stream lève « No response returned. »
    quand un client SSE se déconnecte). Un pur ASGI middleware est immunisé."""
    from starlette.middleware.base import BaseHTTPMiddleware
    assert not issubclass(BearerAuthMiddleware, BaseHTTPMiddleware)


def test_streaming_response_flows_through_middleware():
    """Une réponse SSE (StreamingResponse) traverse le middleware sans être
    bufferisée : le corps streamé arrive intégralement au client."""
    from fastapi.responses import StreamingResponse

    cfg = MagicMock()
    cfg.bot.dashboard_token = "secret123"
    state = MagicMock()
    state.config = cfg
    tickets = SseTickets()
    state.sse_tickets = tickets

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, state=state)

    async def _gen():
        for i in range(3):
            yield f"data: {i}\n\n"

    @app.get("/api/admin/sse/logs")
    async def sse_logs():
        return StreamingResponse(_gen(), media_type="text/event-stream")

    client = TestClient(app)
    with client.stream("GET", f"/api/admin/sse/logs?ticket={tickets.issue()}") as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())
    assert "data: 0" in body and "data: 2" in body
