# bot/dashboard/app.py
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from loguru import logger
from starlette.types import Scope

from bot.dashboard.auth import BearerAuthMiddleware

if TYPE_CHECKING:
    from bot.dashboard.state import AppState

STATIC_DIR = Path(__file__).parent / "static"


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles avec Cache-Control: no-cache pour éviter le cache CDN (Cloudflare)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def create_dashboard_app(state: "AppState") -> FastAPI:
    """Crée et configure l'application FastAPI du dashboard.

    Injecte AppState dans app.state.wally pour accès depuis les routes via
    request.app.state.wally.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Snapshot immédiat au démarrage — graphe 24h disponible dès l'ouverture
        try:
            await state.db.insert_emotion_snapshot(state.emotion.get_state())
        except Exception as exc:
            logger.warning("Failed initial emotion snapshot: {e}", e=exc)

        # SSE logs sink setup
        from bot.dashboard.routes.sse import setup_log_sink
        setup_log_sink()

        task = asyncio.create_task(_snapshot_task(state))
        logger.info("Dashboard started on port 8080")
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Dashboard shutdown")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.wally = state
    app.add_middleware(BearerAuthMiddleware, state=state)

    # Import routes (après création pour éviter les imports circulaires)
    from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links

    # Public routes
    app.include_router(status.router, prefix="/api/public")
    app.include_router(emotions.public_router, prefix="/api/public")
    app.include_router(twitch.router, prefix="/api/public")
    app.include_router(sse.public_router, prefix="/api/public")

    # Admin routes
    app.include_router(emotions.admin_router, prefix="/api/admin")
    app.include_router(admin.router, prefix="/api/admin")
    app.include_router(sse.admin_router, prefix="/api/admin")
    app.include_router(memory.router, prefix="/api/admin")
    app.include_router(links.router, prefix="/api/admin")

    # Static files — NoCacheStaticFiles force la revalidation via Cloudflare tunnel
    if STATIC_DIR.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def root():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app


async def _snapshot_task(state: "AppState") -> None:
    """Insère un snapshot d'émotion toutes les 5 minutes."""
    while True:
        await asyncio.sleep(300)
        try:
            await state.db.insert_emotion_snapshot(state.emotion.get_state())
        except Exception as exc:
            logger.warning("Failed periodic emotion snapshot: {e}", e=exc)
