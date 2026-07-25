# bot/dashboard/auth.py
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from bot.dashboard.state import AppState

_ADMIN_PREFIX = "/api/admin/"
# EventSource (SSE) cannot send custom headers — these paths bypass Bearer auth
# and are only accessible on a trusted local network.
# Twitch OAuth callback is a browser redirect from Twitch — no Bearer token possible.
_SSE_EXEMPT = {"/api/admin/sse/logs", "/api/admin/sse/actions", "/api/admin/sse/voice", "/api/admin/twitch/auth/callback"}


class BearerAuthMiddleware:
    """Pur ASGI middleware (surtout PAS ``BaseHTTPMiddleware``).

    ``BaseHTTPMiddleware`` pipe la réponse dans un memory-stream anyio ; sur un
    flux SSE de longue durée, une déconnexion client interrompt ce stream et
    ``call_next`` lève ``RuntimeError("No response returned.")`` → une 500
    parasite loggée à chaque fermeture d'un ``/sse/*``. Un middleware ASGI natif
    ne bufferise jamais le corps : il délègue directement à ``self.app`` et est
    donc immunisé contre ce mode d'échec.
    """

    def __init__(self, app: ASGIApp, state: AppState) -> None:
        self.app = app
        self._state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith(_ADMIN_PREFIX) or path in _SSE_EXEMPT:
            await self.app(scope, receive, send)
            return

        token = self._state.config.bot.dashboard_token
        if not token:
            await JSONResponse(
                {"detail": "dashboard_token not configured"},
                status_code=503,
            )(scope, receive, send)
            return

        auth = Headers(scope=scope).get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != token:
            await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
            return

        await self.app(scope, receive, send)
