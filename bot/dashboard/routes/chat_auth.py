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


def create_jwt(
    discord_id: str, username: str, avatar_url: str | None, secret: str,
    ttl: int = JWT_TTL, is_owner: bool = False,
) -> str:
    payload = {
        "discord_id": discord_id,
        "username": username,
        "avatar_url": avatar_url,
        # Le VERDICT, signé, plutôt que la donnée qui permet de le calculer.
        # Le site public lisait `owner_discord_id` sur `/api/public/status`,
        # une route anonyme : le snowflake réel du propriétaire partait à tout
        # visiteur, pour une comparaison purement cosmétique (afficher ou non
        # le bouton ADMIN). L'autorisation réelle est côté serveur de toute
        # façon — l'identifiant n'avait aucune raison d'être publié.
        "is_owner": bool(is_owner),
        "exp": time.time() + ttl,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def _est_owner(request, discord_id: str) -> bool:
    """Le serveur tranche, une fois, à l'émission du jeton."""
    owner = getattr(
        getattr(getattr(request.app.state.wally, "config", None), "bot", None),
        "owner_discord_id", "",
    )
    return bool(owner) and str(discord_id) == str(owner)


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
    # `state` anti-CSRF de connexion. Sans lui, un attaquant pouvait faire
    # consommer SON code par le navigateur d'une victime (lien piégé) : la
    # victime se retrouvait authentifiée sur le chat web sous l'identité de
    # l'attaquant, et ses messages, sa mémoire et ses votes de galerie étaient
    # attribués à ce compte. `twitch_auth.py` gérait déjà correctement un
    # `state` avec TTL ; ce flux-ci ne le faisait pas.
    _purge_states()
    state_key = uuid.uuid4().hex
    _pending_states[state_key] = time.time() + _STATE_TTL_S
    url = (
        f"{DISCORD_AUTH_URL}?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code&scope=identify"
        f"&state={state_key}"
    )
    return RedirectResponse(url)


# ── GET /chat/auth/callback ───────────────────────────────────────────────────

@router.get("/auth/callback")
async def callback(code: str, request: Request, state: str = ""):
    import httpx

    # Le `state` doit avoir été émis par NOTRE `/auth/login`, et pas expiré.
    _purge_states()
    if not state or _pending_states.pop(state, None) is None:
        logger.warning("Discord OAuth2: state absent ou inconnu — connexion refusée")
        raise HTTPException(400, detail="Lien de connexion invalide ou expiré")

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

    state = request.app.state.wally
    if await state.db.is_chat_user_banned(discord_id):
        logger.info("Discord OAuth2 login refused (banned): {u} ({id})", u=username, id=discord_id)
        raise HTTPException(403, detail="Banned")

    secret = _jwt_secret(request)
    jwt_token = create_jwt(discord_id, username, avatar_url, secret,
                           is_owner=_est_owner(request, discord_id))

    refresh_token = uuid.uuid4().hex
    await state.db.store_refresh_token(
        hash_token(refresh_token), discord_id, username, avatar_url,
        time.time() + REFRESH_TTL,
    )
    await state.db.cleanup_expired_refresh_tokens()

    logger.info("Discord OAuth2 login: {u} ({id})", u=username, id=discord_id)

    # Ephemeral one-time code — avoids tokens in URL/history/logs
    auth_code = uuid.uuid4().hex
    _purge_codes()
    _pending_codes[auth_code] = {
        "jwt": jwt_token, "refresh_token": refresh_token,
        "expires": time.time() + 60,
    }
    return RedirectResponse(f"/?chat_code={auth_code}")


# Ephemeral auth codes (one-time, 60s TTL)
_pending_codes: dict[str, dict] = {}

# `state` OAuth2 en attente : {clé: instant d'expiration}.
_pending_states: dict[str, float] = {}
_STATE_TTL_S = 600.0


def _purge_states() -> None:
    maintenant = time.time()
    for cle in [k for k, exp in _pending_states.items() if exp < maintenant]:
        _pending_states.pop(cle, None)


def _purge_codes() -> None:
    """Retire les codes périmés.

    Le TTL de 60 s n'était vérifié qu'à la LECTURE : un code jamais échangé —
    l'utilisateur ferme l'onglet après le redirect — restait indéfiniment en
    mémoire, avec son JWT et son refresh token valide 30 jours. `SseTickets`
    montrait déjà le motif attendu.
    """
    maintenant = time.time()
    for cle in [k for k, v in _pending_codes.items() if v.get("expires", 0) < maintenant]:
        _pending_codes.pop(cle, None)


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

    if await state.db.is_chat_user_banned(stored["discord_id"]):
        await state.db.delete_refresh_token(hash_token(old_token))
        raise HTTPException(403, detail="Banned")

    await state.db.delete_refresh_token(hash_token(old_token))

    new_refresh = uuid.uuid4().hex
    await state.db.store_refresh_token(
        hash_token(new_refresh), stored["discord_id"], stored["username"],
        stored["avatar_url"], time.time() + REFRESH_TTL,
    )

    secret = _jwt_secret(request)
    jwt_token = create_jwt(
        stored["discord_id"], stored["username"], stored["avatar_url"], secret,
        is_owner=_est_owner(request, stored["discord_id"]),
    )

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
