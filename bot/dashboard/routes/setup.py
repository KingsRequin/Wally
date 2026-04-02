# bot/dashboard/routes/setup.py
"""Routes Setup Wizard — admin (génération invitations) + wizard public."""
from __future__ import annotations

import os
import time
import urllib.parse
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

admin_router = APIRouter()
wizard_router = APIRouter()

_TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_DISCORD_API_URL = "https://discord.com/api/v10/users/@me"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _invite_status(row) -> str:
    if row["is_preview"]:
        return "preview"
    if row["used_at"]:
        return "used"
    if row["expires_at"] is not None and row["expires_at"] == -1:
        return "revoked"
    if row["expires_at"] and row["expires_at"] < time.time():
        return "expired"
    return "pending"


async def _get_valid_invite(token: str, db) -> Any:
    """Retourne la row de l'invite, lève 404/410/409 si invalide."""
    row = await db.get_setup_invite(token)
    if row is None:
        raise HTTPException(status_code=404, detail="Lien invalide.")
    if not row["is_preview"]:
        if row["expires_at"] and row["expires_at"] < time.time():
            raise HTTPException(status_code=410, detail="Lien expiré.")
        if row["used_at"]:
            raise HTTPException(status_code=409, detail="Lien déjà utilisé.")
    return row


def _check_preview_auth(request: Request, token: str) -> None:
    """Si token == __preview__, vérifie le Bearer admin."""
    if token != "__preview__":
        return
    cfg_token = request.app.state.wally.config.bot.dashboard_token
    auth = request.headers.get("Authorization", "")
    if not cfg_token or not auth.startswith("Bearer ") or auth[7:] != cfg_token:
        raise HTTPException(status_code=401, detail="Admin auth required for preview.")


# ── Admin routes ──────────────────────────────────────────────────────────────

@admin_router.post("/invite")
async def generate_invite(request: Request) -> dict:
    state = request.app.state.wally
    token = uuid.uuid4().hex
    expires_at = time.time() + 7 * 86400
    await state.db.create_setup_invite(token, expires_at=expires_at)
    base_url = os.getenv("WEB_BASE_URL", "")
    url = f"{base_url}/setup/{token}" if base_url else f"/setup/{token}"
    logger.info("Setup invite generated: token={}", token[:8] + "...")
    return {"token": token, "url": url, "expires_at": expires_at}


@admin_router.get("/invites")
async def list_invites(request: Request) -> dict:
    state = request.app.state.wally
    rows = await state.db.list_setup_invites()
    invites = [
        {
            "token": r["token"][:8] + "...",
            "token_full": r["token"],
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
            "used_at": r["used_at"],
            "slug": r["slug"],
            "port": r["port"],
            "status": _invite_status(r),
        }
        for r in rows
    ]
    return {"invites": invites}


@admin_router.delete("/invite/{token}")
async def revoke_invite(request: Request, token: str) -> dict:
    state = request.app.state.wally
    await state.db.revoke_setup_invite(token)
    return {"status": "revoked"}


# ── Wizard routes ─────────────────────────────────────────────────────────────

@wizard_router.post("/{token}/save")
async def save_step(request: Request, token: str, body: dict) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    await _get_valid_invite(token, db)
    await db.save_setup_session(token, body)
    return {"status": "saved"}


@wizard_router.post("/{token}/validate-discord")
async def validate_discord(request: Request, token: str, body: dict) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    await _get_valid_invite(token, db)
    discord_token = body.get("discord_token", "")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _DISCORD_API_URL,
            headers={"Authorization": f"Bot {discord_token}"},
            timeout=10,
        )
    if resp.status_code == 200:
        data = resp.json()
        return {"ok": True, "username": data.get("username", ""), "id": data.get("id", "")}
    return {"ok": False, "error": f"Discord a refusé le token (HTTP {resp.status_code})"}


@wizard_router.post("/{token}/twitch-auth-url")
async def twitch_auth_url(request: Request, token: str, body: dict) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    await _get_valid_invite(token, db)

    base_url = os.getenv("WEB_BASE_URL", "")
    account_type = body.get("account_type", "bot")
    client_id = body.get("client_id", "")
    redirect_uri = f"{base_url}/api/setup/{token}/twitch/callback"

    if account_type == "bot":
        scope = "user:read:chat user:write:chat user:bot moderator:read:followers chat:read chat:edit"
    else:
        scope = "bits:read channel:read:subscriptions moderator:read:followers"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": f"{token}:{account_type}",
    }
    url = "https://id.twitch.tv/oauth2/authorize?" + urllib.parse.urlencode(params)
    await db.save_setup_session(token, {
        "twitch_client_id": client_id,
        "twitch_client_secret": body.get("client_secret", ""),
        "twitch_redirect_uri": redirect_uri,
    })
    return {"url": url}


@wizard_router.get("/{token}/twitch/callback")
async def twitch_callback(request: Request, token: str):
    from fastapi.responses import HTMLResponse
    code = request.query_params.get("code")
    state_param = request.query_params.get("state", "")
    error = request.query_params.get("error")

    if error:
        return JSONResponse({"error": error}, status_code=400)

    parts = state_param.rsplit(":", 1)
    account_type = parts[1] if len(parts) == 2 else "bot"

    db = request.app.state.wally.db
    session = await db.get_setup_session(token)
    client_id = session.get("twitch_client_id", "")
    client_secret = session.get("twitch_client_secret", "")
    redirect_uri = session.get("twitch_redirect_uri", "")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _TWITCH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        )

    if resp.status_code != 200:
        logger.error("Twitch token exchange failed: {}", resp.text)
        return HTMLResponse("<html><body><h2>Erreur Twitch</h2><p>Ferme cet onglet et réessaie.</p></body></html>", status_code=500)

    tokens = resp.json()
    prefix = "bot" if account_type == "bot" else "streamer"
    update = {
        f"{prefix}_access_token": tokens.get("access_token", ""),
        f"{prefix}_refresh_token": tokens.get("refresh_token", ""),
        f"twitch_{prefix}_connected": True,
    }
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "Client-Id": client_id,
            },
            timeout=10,
        )
    if user_resp.status_code == 200:
        udata = user_resp.json().get("data", [{}])[0]
        update[f"twitch_{prefix}_username"] = udata.get("display_name", "")
        update[f"twitch_{prefix}_id"] = udata.get("id", "")

    await db.save_setup_session(token, update)
    logger.info("Twitch {} connected for token {}", account_type, token[:8])

    html = """<html><body style="font-family:sans-serif;text-align:center;padding:40px">
    <h2>✅ Compte connecté !</h2>
    <p>Tu peux fermer cet onglet et revenir au wizard.</p>
    <script>window.close();</script></body></html>"""
    return HTMLResponse(html)


@wizard_router.get("/{token}/twitch-status")
async def twitch_status(request: Request, token: str) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    await _get_valid_invite(token, db)
    session = await db.get_setup_session(token)
    return {
        "bot_connected": bool(session.get("twitch_bot_connected")),
        "streamer_connected": bool(session.get("twitch_streamer_connected")),
        "bot_username": session.get("twitch_bot_username", ""),
        "streamer_username": session.get("twitch_streamer_username", ""),
    }


@wizard_router.post("/{token}/submit")
async def submit_wizard(request: Request, token: str, body: dict) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    row = await _get_valid_invite(token, db)
    session = await db.get_setup_session(token)
    is_dry_run = row["is_preview"] and body.get("dry_run", True)
    slug = session.get("bot_name", "bot").lower().replace(" ", "_")
    if not is_dry_run:
        await db.use_setup_invite(token, slug=slug, port=0)
    logger.info("Setup wizard completed for slug={} dry_run={}", slug, is_dry_run)
    return {"status": "ok", "slug": slug, "dry_run": is_dry_run}
