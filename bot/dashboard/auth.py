# bot/dashboard/auth.py
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from bot.dashboard.state import AppState

_ADMIN_PREFIX = "/api/admin/"
# EventSource (SSE) cannot send custom headers — these paths bypass Bearer auth
# and are only accessible on a trusted local network.
# Twitch OAuth callback is a browser redirect from Twitch — no Bearer token possible.
_SSE_EXEMPT = {"/api/admin/sse/logs", "/api/admin/sse/actions", "/api/admin/twitch/auth/callback"}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, state: "AppState"):
        super().__init__(app)
        self._state = state

    async def dispatch(self, request, call_next):
        if not request.url.path.startswith(_ADMIN_PREFIX):
            return await call_next(request)

        # SSE endpoints cannot send Authorization headers
        if request.url.path in _SSE_EXEMPT:
            return await call_next(request)

        token = self._state.config.bot.dashboard_token
        if not token:
            return JSONResponse(
                {"detail": "dashboard_token not configured"},
                status_code=503,
            )

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != token:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return await call_next(request)
