# bot/dashboard/app.py
from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import time
from contextlib import asynccontextmanager
from html import escape as html_escape
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from loguru import logger
from starlette.types import Scope

from bot.dashboard.auth import BearerAuthMiddleware

if TYPE_CHECKING:
    from bot.dashboard.state import AppState

# L'image Docker (Python 3.12, sans /etc/mime.types) ignore `.webp` : tout ce
# que Starlette sert en devinant le type — `/static`, les `FileResponse` sans
# `media_type` — partait en `application/octet-stream`. Les navigateurs
# reniflent le contenu d'un `<img>` et affichaient quand même, mais Discord, lui,
# se fie au Content-Type et refuse l'aperçu. Une ligne au démarrage vaut mieux
# qu'un correctif par route, celles à venir comprises.
mimetypes.add_type("image/webp", ".webp")

# Les `?v=…` des feuilles et des scripts du panneau admin, quelle que soit
# l'empreinte déjà écrite dans `index.html`.
_ASSET_VERSION_RE = re.compile(r'(src|href)="(/static/[^"?]+\.(?:js|css))\?v=[^"]*"')

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
    if public_ui_dir.is_dir() and any(public_ui_dir.iterdir()):
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

        # Créer le token preview s'il n'existe pas déjà
        try:
            await state.db.create_setup_invite("__preview__", expires_at=None, is_preview=1)
        except Exception:
            pass  # INSERT OR REPLACE gère les doublons

        task = asyncio.create_task(_snapshot_task(state))
        cleanup_task = asyncio.create_task(_chat_cleanup_task(state))
        logger.info("Dashboard started on port 8080")
        yield
        task.cancel()
        cleanup_task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Dashboard shutdown")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.wally = state
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(BearerAuthMiddleware, state=state)

    # Import routes (après création pour éviter les imports circulaires)
    from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, roadmap, chat_auth, chat, gallery, actions, setup, twitch_auth, theme, journal, cognitive, voice, overlay, apex_chart, apex_accounts

    # Public routes
    app.include_router(status.router, prefix="/api/public")
    app.include_router(emotions.public_router, prefix="/api/public")
    app.include_router(twitch.router, prefix="/api/public")
    app.include_router(sse.public_router, prefix="/api/public")
    app.include_router(roadmap.router, prefix="/api/public")
    app.include_router(gallery.public_router, prefix="/api/public")
    app.include_router(apex_chart.public_router, prefix="/api/public")
    app.include_router(journal.public_router, prefix="/api/public")
    app.include_router(cognitive.public_router, prefix="/api/public")
    app.include_router(overlay.public_router, prefix="/api/public")

    # Chat routes (public — JWT auth handled internally)
    app.include_router(chat_auth.router, prefix="/api/chat")
    app.include_router(chat.public_router, prefix="/api/public")
    app.include_router(chat.router)

    # Admin routes
    app.include_router(emotions.admin_router, prefix="/api/admin")
    app.include_router(admin.router, prefix="/api/admin")
    app.include_router(sse.admin_router, prefix="/api/admin")
    app.include_router(memory.router, prefix="/api/admin")
    app.include_router(links.router, prefix="/api/admin")
    app.include_router(apex_accounts.router, prefix="/api/admin")
    app.include_router(gallery.admin_router, prefix="/api/admin")
    app.include_router(actions.router, prefix="/api/actions")
    app.include_router(setup.admin_router, prefix="/api/admin/setup")
    app.include_router(setup.wizard_router, prefix="/api/setup")
    app.include_router(twitch_auth.router, prefix="/api/admin")
    app.include_router(voice.admin_router, prefix="/api/admin")
    app.include_router(overlay.admin_router, prefix="/api/admin")

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
        # Une expression, plutôt que trois `replace` sur un numéro écrit en
        # dur : `index.html` était passé à `app.js?v=8` sans que ces lignes
        # suivent, et le cache-bust du panneau ne visait plus rien depuis. Le
        # motif attrape désormais n'importe quelle empreinte, sur n'importe
        # quel fichier statique — les scripts ajoutés plus tard compris.
        html = _ASSET_VERSION_RE.sub(rf'\1="\2?v={_asset_version}"', html)
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
        # TOUS les scripts, pas seulement overlay.js : `overlay_apex.js` et les
        # bibliothèques de `vendor/` restaient sinon dans le cache d'OBS pour
        # toujours. La vidéo de l'avatar, elle, n'est pas touchée.
        from bot.dashboard.routes.overlay import (
            overlay_version, version_static_scripts,
        )
        html = version_static_scripts(html, overlay_version())
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            },
        )

    @app.get("/overlay-image")
    async def overlay_image_page():
        """OBSOLÈTE : l'image de la galerie est une ZONE de l'overlay principal.

        Son contenu a été porté dans `overlay.js` (`[data-element="image"]`),
        où elle se place et s'éteint comme les autres éléments. Cette page reste
        servie parce qu'elle est peut-être encore dans des scènes OBS — les deux
        écoutent le même flux, donc tant qu'elles coexistent l'image s'affiche
        en double.
        """
        return FileResponse(
            "bot/dashboard/static/overlay_image.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/overlay-rotation")
    async def overlay_rotation_page():
        """RETIRÉE : le rotateur de memes est une ZONE de l'overlay principal.

        Sa boucle vit dans `overlay.js` (`[data-element="rotator"]`), où elle se
        place, se dimensionne, s'éteint ET se cadence depuis le panneau de mise
        en scène. Elle a été supprimée d'ici : les deux sources coexistant, les
        memes s'affichaient en double.

        La route est GARDÉE et sert un avis de remplacement. Cette source est
        peut-être encore dans une scène OBS : un 404 y mettrait un rectangle
        vide sans explication, et on l'apprendrait en plein live. Elle se
        supprimera pour de bon une fois la source retirée d'OBS.
        """
        return FileResponse(
            "bot/dashboard/static/overlay_rotation.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    # Le seul slug qu'on accepte d'écrire dans la page. C'est exactement ce que
    # `slug_depuis_nom()` produit — lettres minuscules, chiffres, traits d'union.
    _SLUG_SCENE_RE = re.compile(r"^[a-z0-9-]{1,64}$")

    @app.get("/overlay-{slug}")
    async def overlay_scene(slug: str):
        """La page d'une scène.

        Déclarée APRÈS `/overlay-image` et `/overlay-rotation` : FastAPI retient
        la première route qui filtre, et celle-ci les capterait toutes les deux.

        Un slug inconnu est servi quand même — OBS peut pointer sur une scène
        supprimée, et un 404 mettrait un écran noir en plein live. La page
        demandera son layout et recevra celui de la scène par défaut.

        SÉCURITÉ — ce slug vient de l'URL et finit dans un attribut HTML. Écrit
        tel quel, `/overlay-x" onload="…` refermait l'attribut et injectait du
        JavaScript sur le domaine public, celui-là même qui sert le panneau
        d'administration : de quoi lire son jeton. Vérifié exploitable en
        production le 2026-08-15, corrigé dans la foulée.

        Deux barrières plutôt qu'une, parce que celle qui saute est toujours
        celle qu'on croyait seule :
          1. le format est validé — un slug ne peut pas contenir de guillemet ;
          2. l'échappement HTML reste appliqué, même sur un slug déjà validé.

        Un slug mal formé n'est PAS refusé : la page est servie avec un slug
        vide, donc sur la scène par défaut. La règle « jamais d'écran noir en
        plein live » vaut aussi pour une URL malveillante — répondre 404 ne
        protégerait personne de plus et casserait une source OBS mal saisie.
        """
        from bot.dashboard.routes.overlay import (
            overlay_version, version_static_scripts,
        )
        propre = slug if _SLUG_SCENE_RE.fullmatch(slug) else ""
        html = (STATIC_DIR / "overlay.html").read_text()
        html = version_static_scripts(html, overlay_version())
        html = html.replace(
            'data-scene-slug=""',
            f'data-scene-slug="{html_escape(propre, quote=True)}"',
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/setup/preview")
    async def setup_preview_page():
        html = (STATIC_DIR / "setup.html").read_text()
        html = html.replace("__WIZARD_TOKEN__", json.dumps("__preview__")).replace("__WIZARD_MODE__", "preview")
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
        # `json.dumps()` : le jeton finit dans un contexte JS (`const WIZARD_TOKEN
        # = …;`), pas HTML — un échappement HTML ne protège pas une chaîne JS.
        # Même patron que la faille corrigée sur `/overlay-{slug}` le 2026-08-15 ;
        # pas exploitable ici (jeton = `uuid.uuid4().hex`, créé sous
        # authentification), mais c'est justement le genre de trou qui ne se
        # voit qu'après coup.
        html = html.replace("__WIZARD_TOKEN__", json.dumps(token)).replace("__WIZARD_MODE__", "normal")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    # Seed public-ui/ depuis le starter kit si vide — avant le mount conditionnel
    try:
        _maybe_seed_public_ui()
    except Exception as exc:
        logger.warning("Failed to seed public-ui: {e}", e=exc)

    # Public UI — SPAStaticFiles en dernier (catch-all SPA)
    # Enregistré après tous les routers API pour ne pas intercepter /api/*, /admin, etc.
    if PUBLIC_UI_DIR.is_dir():
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
