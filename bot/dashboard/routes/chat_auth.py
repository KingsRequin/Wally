# bot/dashboard/routes/chat_auth.py
from __future__ import annotations

import hashlib
import os
import time
import uuid

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from loguru import logger

router = APIRouter()

JWT_ALGORITHM = "HS256"
JWT_TTL = 3600  # 1 hour
REFRESH_TTL = 30 * 86400  # 30 days

DISCORD_API = "https://discord.com/api/v10"
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"


_generated_secret: str | None = None


def _jwt_secret_raw() -> str:
    """Retourne le secret JWT — réutilisable depuis chat.py sans Request."""
    global _generated_secret
    secret = os.getenv("JWT_SECRET")
    if secret:
        return secret
    if _generated_secret:
        return _generated_secret
    import secrets
    _generated_secret = secrets.token_hex(32)
    logger.warning("JWT_SECRET not set — auto-generated a temporary secret (will change on restart)")
    return _generated_secret


def _jwt_secret(request: Request) -> str:
    return _jwt_secret_raw()


def create_jwt(discord_id: str, username: str, avatar_url: str | None, secret: str, ttl: int = JWT_TTL) -> str:
    payload = {
        "discord_id": discord_id,
        "username": username,
        "avatar_url": avatar_url,
        "exp": time.time() + ttl,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str, secret: str) -> dict | None:
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── GET /chat/auth/login ──────────────────────────────────────────────────────

@router.get("/auth/login")
async def login(request: Request):
    client_id = os.getenv("DISCORD_CLIENT_ID")
    base_url = os.getenv("WEB_BASE_URL", "").rstrip("/")
    if not client_id or not base_url:
        raise HTTPException(500, detail="Discord OAuth2 not configured")

    redirect_uri = f"{base_url}/api/chat/auth/callback"
    url = (
        f"{DISCORD_AUTH_URL}?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code&scope=identify"
    )
    return RedirectResponse(url)


# ── GET /chat/auth/callback ───────────────────────────────────────────────────

@router.get("/auth/callback")
async def callback(code: str, request: Request):
    import httpx

    client_id = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    base_url = os.getenv("WEB_BASE_URL", "").rstrip("/")
    if not client_id or not client_secret or not base_url:
        raise HTTPException(500, detail="Discord OAuth2 not configured")

    redirect_uri = f"{base_url}/api/chat/auth/callback"

    async with httpx.AsyncClient() as http:
        token_resp = await http.post(DISCORD_TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        })
        if token_resp.status_code != 200:
            logger.warning("Discord OAuth2 token exchange failed: {s}", s=token_resp.status_code)
            raise HTTPException(400, detail="Discord authentication failed")

        access_token = token_resp.json().get("access_token")

        user_resp = await http.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(400, detail="Failed to fetch Discord profile")

        user = user_resp.json()

    discord_id = user["id"]
    username = user.get("global_name") or user.get("username", "")
    avatar_hash = user.get("avatar")
    avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png" if avatar_hash else None

    secret = _jwt_secret(request)
    jwt_token = create_jwt(discord_id, username, avatar_url, secret)

    refresh_token = uuid.uuid4().hex
    state = request.app.state.wally
    await state.db.store_refresh_token(
        hash_token(refresh_token), discord_id, username, avatar_url,
        time.time() + REFRESH_TTL,
    )
    await state.db.cleanup_expired_refresh_tokens()

    logger.info("Discord OAuth2 login: {u} ({id})", u=username, id=discord_id)

    # Ephemeral one-time code — avoids tokens in URL/history/logs
    auth_code = uuid.uuid4().hex
    _pending_codes[auth_code] = {
        "jwt": jwt_token, "refresh_token": refresh_token,
        "expires": time.time() + 60,
    }
    return RedirectResponse(f"/?chat_code={auth_code}")


# Ephemeral auth codes (one-time, 60s TTL)
_pending_codes: dict[str, dict] = {}


# ── GET /chat/auth/exchange ───────────────────────────────────────────────────

@router.get("/auth/exchange")
async def exchange_code(code: str):
    """Exchange a one-time auth code for JWT + refresh token."""
    entry = _pending_codes.pop(code, None)
    if not entry or entry["expires"] < time.time():
        raise HTTPException(401, detail="Invalid or expired auth code")
    return {"jwt": entry["jwt"], "refresh_token": entry["refresh_token"]}


# ── GET /chat/auth/refresh ────────────────────────────────────────────────────

@router.get("/auth/refresh")
async def refresh(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, detail="Refresh token required")

    old_token = auth[7:]
    state = request.app.state.wally
    stored = await state.db.get_refresh_token(hash_token(old_token))
    if not stored:
        raise HTTPException(401, detail="Invalid or expired refresh token")

    await state.db.delete_refresh_token(hash_token(old_token))

    new_refresh = uuid.uuid4().hex
    await state.db.store_refresh_token(
        hash_token(new_refresh), stored["discord_id"], stored["username"],
        stored["avatar_url"], time.time() + REFRESH_TTL,
    )

    secret = _jwt_secret(request)
    jwt_token = create_jwt(stored["discord_id"], stored["username"], stored["avatar_url"], secret)

    return {"jwt": jwt_token, "refresh_token": new_refresh}


# ── GET /chat/auth/me ─────────────────────────────────────────────────────────

@router.get("/auth/me")
async def me(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, detail="JWT required")

    payload = decode_jwt(auth[7:], _jwt_secret(request))
    if not payload:
        raise HTTPException(401, detail="Invalid or expired token")

    return {
        "discord_id": payload["discord_id"],
        "username": payload["username"],
        "avatar_url": payload.get("avatar_url"),
    }


# ── GET /chat/auth/admin-token ────────────────────────────────────────────────

@router.get("/auth/admin-token")
async def admin_token(request: Request):
    """Échange un JWT Discord du propriétaire contre le token admin du dashboard.

    Permet à l'owner (déjà authentifié via Discord) d'ouvrir /admin sans saisir
    de mot de passe. Tout autre Discord ID est refusé.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, detail="JWT required")

    payload = decode_jwt(auth[7:], _jwt_secret(request))
    if not payload:
        raise HTTPException(401, detail="Invalid or expired token")

    owner = request.app.state.wally.config.bot.owner_discord_id
    if not owner or str(payload.get("discord_id")) != owner:
        raise HTTPException(403, detail="Not authorized")

    token = request.app.state.wally.config.bot.dashboard_token
    if not token:
        raise HTTPException(503, detail="dashboard_token not configured")

    return {"token": token}
