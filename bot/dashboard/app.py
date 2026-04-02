# bot/dashboard/app.py
from __future__ import annotations

import asyncio
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.responses import StreamingResponse
from loguru import logger
from starlette.types import Scope

from bot.dashboard.auth import BearerAuthMiddleware

if TYPE_CHECKING:
    from bot.dashboard.state import AppState

STATIC_DIR = Path(__file__).parent / "static"
PUBLIC_UI_DIR = Path("public-ui")
STARTER_DIR = STATIC_DIR / "public-starter"


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles avec Cache-Control: no-store pour bypasser le cache CDN (Cloudflare)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["CDN-Cache-Control"] = "no-store"
        response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
        return response


class SPAStaticFiles(StaticFiles):
    """StaticFiles avec fallback vers index.html pour les routes SPA inconnues."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                response = await super().get_response("index.html", scope)
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                return response
            raise


def _maybe_seed_public_ui(
    starter_dir: Path = STARTER_DIR,
    public_ui_dir: Path = PUBLIC_UI_DIR,
) -> None:
    """Copie le starter kit dans public-ui/ si le dossier est vide ou absent."""
    if not starter_dir.exists():
        return
    if public_ui_dir.exists() and any(public_ui_dir.iterdir()):
        return  # déjà peuplé — ne pas écraser
    public_ui_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(starter_dir), str(public_ui_dir), dirs_exist_ok=True)
    logger.info("Public UI seeded from starter kit into {}", public_ui_dir)


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

        # Seed public-ui/ depuis le starter kit si vide
        try:
            _maybe_seed_public_ui()
        except Exception as exc:
            logger.warning("Failed to seed public-ui: {e}", e=exc)

        # Créer le token preview s'il n'existe pas déjà
        try:
            await state.db.create_setup_invite("__preview__", expires_at=None, is_preview=1)
        except Exception:
            pass  # INSERT OR REPLACE gère les doublons

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
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(BearerAuthMiddleware, state=state)

    # Import routes (après création pour éviter les imports circulaires)
    from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, costs, roadmap, chat_auth, chat, gallery, actions, setup, twitch_auth, theme, graph

    # Public routes
    app.include_router(status.router, prefix="/api/public")
    app.include_router(emotions.public_router, prefix="/api/public")
    app.include_router(twitch.router, prefix="/api/public")
    app.include_router(sse.public_router, prefix="/api/public")
    app.include_router(roadmap.router, prefix="/api/public")
    app.include_router(gallery.public_router, prefix="/api/public")
    app.include_router(graph.public_router, prefix="/api/public")

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
    app.include_router(gallery.admin_router, prefix="/api/admin")
    app.include_router(graph.router, prefix="/api/admin")
    app.include_router(actions.router, prefix="/api/actions")
    app.include_router(setup.admin_router, prefix="/api/admin/setup")
    app.include_router(setup.wizard_router, prefix="/api/setup")
    app.include_router(twitch_auth.router, prefix="/api/admin")

    # Theme CSS dynamique — enregistré AVANT le mount static pour priorité de routing
    app.add_api_route("/static/theme.css", theme.serve_theme_css, methods=["GET"], include_in_schema=False)
    app.include_router(theme.router, prefix="/api/admin")

    # Static files — NoCacheStaticFiles force la revalidation via Cloudflare tunnel
    if STATIC_DIR.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")

    # Cache-bust version: updated at startup, forces CDN to fetch fresh assets
    _asset_version = str(int(time.time()))

    @app.get("/admin")
    async def admin_panel():
        html = (STATIC_DIR / "index.html").read_text()
        html = html.replace("style.css?v=6", f"style.css?v={_asset_version}")
        html = html.replace("app.js?v=6", f"app.js?v={_asset_version}")
        html = html.replace("theme.css?v=6", f"theme.css?v={_asset_version}")
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

    @app.get("/overlay-image")
    async def overlay_image_page():
        return FileResponse(
            "bot/dashboard/static/overlay_image.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/setup/preview")
    async def setup_preview_page():
        html = (STATIC_DIR / "setup.html").read_text()
        html = html.replace("__WIZARD_TOKEN__", "__preview__").replace("__WIZARD_MODE__", "preview")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/setup/{token}")
    async def setup_wizard_page(request: Request, token: str):
        import time as _time
        from fastapi import HTTPException as _HTTPException
        row = await state.db.get_setup_invite(token)
        if row is None:
            raise _HTTPException(status_code=404, detail="Lien invalide ou expiré.")
        if not row["is_preview"]:
            if row["expires_at"] and row["expires_at"] < _time.time():
                raise _HTTPException(status_code=410, detail="Ce lien a expiré.")
            if row["used_at"]:
                raise _HTTPException(status_code=409, detail="Ce lien a déjà été utilisé.")
        html = (STATIC_DIR / "setup.html").read_text()
        html = html.replace("__WIZARD_TOKEN__", token).replace("__WIZARD_MODE__", "normal")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    # Public UI — SPAStaticFiles en dernier (catch-all SPA)
    # Enregistré après tous les routers API pour ne pas intercepter /api/*, /admin, etc.
    if PUBLIC_UI_DIR.exists():
        app.mount(
            "/",
            SPAStaticFiles(directory=str(PUBLIC_UI_DIR), html=True),
            name="public-ui",
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
