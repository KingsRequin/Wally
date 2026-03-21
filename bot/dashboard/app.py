# bot/dashboard/app.py
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.responses import StreamingResponse
from loguru import logger
from starlette.types import Scope

from bot.dashboard.auth import BearerAuthMiddleware

if TYPE_CHECKING:
    from bot.dashboard.state import AppState

STATIC_DIR = Path(__file__).parent / "static"


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles avec Cache-Control: no-store pour bypasser le cache CDN (Cloudflare)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["CDN-Cache-Control"] = "no-store"
        response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
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
        cleanup_task = asyncio.create_task(_chat_cleanup_task(state))
        notif_task = asyncio.create_task(_cost_notification_task(state))
        logger.info("Dashboard started on port 8080")
        yield
        task.cancel()
        cleanup_task.cancel()
        notif_task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        try:
            await notif_task
        except asyncio.CancelledError:
            pass
        logger.info("Dashboard shutdown")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.wally = state
    app.add_middleware(BearerAuthMiddleware, state=state)

    # Import routes (après création pour éviter les imports circulaires)
    from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, costs, roadmap, chat_auth, chat

    # Public routes
    app.include_router(status.router, prefix="/api/public")
    app.include_router(emotions.public_router, prefix="/api/public")
    app.include_router(twitch.router, prefix="/api/public")
    app.include_router(sse.public_router, prefix="/api/public")
    app.include_router(roadmap.router, prefix="/api/public")

    # Chat routes (public — JWT auth handled internally)
    app.include_router(chat_auth.router, prefix="/api/chat")
    app.include_router(chat.router)

    # Admin routes
    app.include_router(emotions.admin_router, prefix="/api/admin")
    app.include_router(admin.router, prefix="/api/admin")
    app.include_router(sse.admin_router, prefix="/api/admin")
    app.include_router(memory.router, prefix="/api/admin")
    app.include_router(links.router, prefix="/api/admin")
    app.include_router(costs.router, prefix="/api/admin")

    # Static files — NoCacheStaticFiles force la revalidation via Cloudflare tunnel
    if STATIC_DIR.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")

    # Cache-bust version: updated at startup, forces CDN to fetch fresh assets
    _asset_version = str(int(time.time()))

    @app.get("/")
    async def root():
        html = (STATIC_DIR / "index.html").read_text()
        # Replace static ?v=N with current startup timestamp
        html = html.replace("style.css?v=4", f"style.css?v={_asset_version}")
        html = html.replace("app.js?v=4", f"app.js?v={_asset_version}")
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "CDN-Cache-Control": "no-store",
                "Cloudflare-CDN-Cache-Control": "no-store",
            },
        )

    @app.get("/overlay")
    async def overlay():
        html = (STATIC_DIR / "overlay.html").read_text()
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            },
        )

    return app


async def _snapshot_task(state: "AppState") -> None:
    """Insère un snapshot d'émotion toutes les 5 minutes."""
    while True:
        await asyncio.sleep(300)
        try:
            await state.db.insert_emotion_snapshot(state.emotion.get_state())
        except Exception as exc:
            logger.warning("Failed periodic emotion snapshot: {e}", e=exc)


async def _cost_notification_task(state: "AppState") -> None:
    """Vérifie les coûts toutes les 30 minutes et envoie des alertes Discord si nécessaire."""
    from datetime import datetime
    while True:
        await asyncio.sleep(1800)  # 30 min
        try:
            if state.notifications is None:
                continue
            threshold = state.config.bot.cost_alert_threshold
            if threshold <= 0:
                continue
            month_start = datetime.now().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ).timestamp()
            stats = await state.db.get_cost_stats(month_start)
            current = stats["total"]
            pct = round(current / threshold * 100, 1)
            status = "critical" if pct >= 80 else "warning" if pct >= 60 else "ok"
            await state.notifications.notify_cost_alert(status, pct, current, threshold)
        except Exception as exc:
            logger.warning("Cost notification check failed: {e}", e=exc)


async def _chat_cleanup_task(state: "AppState") -> None:
    """Nettoie les vieux messages chat et refresh tokens toutes les 24h."""
    while True:
        await asyncio.sleep(86400)
        try:
            await state.db.cleanup_old_chat_messages(days=30)
            await state.db.cleanup_expired_refresh_tokens()
            logger.info("Chat cleanup: old messages and expired tokens removed")
        except Exception as exc:
            logger.warning("Chat cleanup failed: {e}", e=exc)
