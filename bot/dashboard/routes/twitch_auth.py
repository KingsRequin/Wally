# bot/dashboard/routes/twitch_auth.py
from __future__ import annotations
import asyncio, hashlib, os, re, time, urllib.parse, uuid
from pathlib import Path
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from bot.dashboard.routes.sse import broadcast_event

router = APIRouter()

_TWITCH_TOKEN_URL  = "https://id.twitch.tv/oauth2/token"
_TWITCH_USERS_URL  = "https://api.twitch.tv/helix/users"
_BOT_SCOPES        = "user:read:chat user:write:chat user:bot moderator:read:followers chat:read chat:edit"
_STREAMER_SCOPES   = "channel:read:subscriptions bits:read"

_pending_states: dict[str, dict] = {}   # state_key -> {account, expires_at}
_status_cache:   dict[str, dict] = {}   # token_prefix -> {info, cached_at}
_STATUS_CACHE_TTL = 60
_bg_tasks: set[asyncio.Task] = set()


def _replace_or_append(text: str, key: str, value: str) -> str:
    """Remplace KEY=... dans text ou ajoute KEY=value en fin de fichier."""
    pattern = rf"^{key}=.*$"
    if re.search(pattern, text, flags=re.MULTILINE):
        return re.sub(pattern, f"{key}={value}", text, flags=re.MULTILINE)
    return text.rstrip("\n") + f"\n{key}={value}\n"


def _cleanup_states() -> None:
    now = time.time()
    for k in [k for k, v in _pending_states.items() if v["expires_at"] < now]:
        del _pending_states[k]


async def _validate_token(token: str, client_id: str) -> dict | None:
    """Appelle /helix/users avec le token, retourne {username, user_id} ou None."""
    if not token or not client_id:
        return None
    now = time.time()
    cache_key = hashlib.sha256(token.encode()).hexdigest()[:16]
    cached = _status_cache.get(cache_key)
    if cached and (now - cached["cached_at"]) < _STATUS_CACHE_TTL:
        return cached["info"]
    try:
        async with httpx.AsyncClient() as c:
            resp = await c.get(_TWITCH_USERS_URL,
                headers={"Authorization": f"Bearer {token}", "Client-Id": client_id},
                timeout=5)
        info = None
        if resp.status_code == 200:
            users = resp.json().get("data", [])
            if users:
                info = {"username": users[0].get("display_name",""), "user_id": users[0].get("id","")}
        _status_cache[cache_key] = {"info": info, "cached_at": now}
        return info
    except Exception as exc:
        logger.warning("Twitch token validation error: {e}", e=exc)
        return None


def _write_env_direct(env_path: Path, account: str, access: str, refresh: str) -> None:
    """Ecrit tokens dans .env quand token_manager n'est pas disponible."""
    ak, rk = ("BOT_ACCESS_TOKEN","BOT_REFRESH_TOKEN") if account=="bot" else ("STREAMER_ACCESS_TOKEN","STREAMER_REFRESH_TOKEN")
    if not env_path.exists():
        return
    content = env_path.read_text(encoding="utf-8")
    content = _replace_or_append(_replace_or_append(content, ak, access), rk, refresh)
    env_path.write_text(content, encoding="utf-8")


def _write_env_ids(env_path: Path, account: str, user_id: str, username: str) -> None:
    """Ecrit TWITCH_BOT_ID/NICK ou TWITCH_BROADCASTER_ID dans .env."""
    if not user_id or not env_path.exists():
        return
    content = env_path.read_text(encoding="utf-8")
    if account == "bot":
        content = _replace_or_append(content, "TWITCH_BOT_ID", user_id)
        if username:
            content = _replace_or_append(content, "TWITCH_BOT_NICK", username)
    else:
        content = _replace_or_append(content, "TWITCH_BROADCASTER_ID", user_id)
    env_path.write_text(content, encoding="utf-8")


@router.get("/twitch/auth-status")
async def twitch_auth_status(request: Request) -> dict:
    state     = request.app.state.wally
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    tm        = getattr(getattr(state, "twitch_bot", None), "token_manager", None)
    bot_info      = await _validate_token(tm.bot_token if tm else "",      client_id)
    streamer_info = await _validate_token(tm.streamer_token if tm else "", client_id)
    return {
        "bot":      {"connected": bot_info is not None,      "username": (bot_info or {}).get("username",""),      "user_id": (bot_info or {}).get("user_id","")},
        "streamer": {"connected": streamer_info is not None, "username": (streamer_info or {}).get("username",""), "user_id": (streamer_info or {}).get("user_id","")},
        "client_id_set": bool(client_id),
    }


@router.post("/twitch/auth-url")
async def twitch_auth_url(request: Request) -> dict:
    body    = await request.json()
    account = body.get("account", "bot")
    if account not in ("bot","streamer"):
        raise HTTPException(400, "account doit etre 'bot' ou 'streamer'")
    client_id = os.getenv("TWITCH_CLIENT_ID","")
    if not client_id:
        raise HTTPException(400, "TWITCH_CLIENT_ID non configure dans .env")
    base_url     = os.getenv("WEB_BASE_URL", str(request.base_url).rstrip("/"))
    redirect_uri = f"{base_url}/api/admin/twitch/auth/callback"
    _cleanup_states()
    state_key = uuid.uuid4().hex
    _pending_states[state_key] = {"account": account, "expires_at": time.time() + 600}
    scope  = _BOT_SCOPES if account == "bot" else _STREAMER_SCOPES
    params = {"response_type":"code","client_id":client_id,"redirect_uri":redirect_uri,"scope":scope,"state":state_key}
    return {"url": "https://id.twitch.tv/oauth2/authorize?" + urllib.parse.urlencode(params)}


@router.get("/twitch/auth/callback")
async def twitch_auth_callback(request: Request):
    code      = request.query_params.get("code","")
    state_key = request.query_params.get("state","")
    error     = request.query_params.get("error","")

    def _err(msg):
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
            f"<h2>Erreur</h2><p>{msg}</p><p>Ferme cet onglet et ressaie.</p></body></html>"
        )

    if error:
        return _err(f"Twitch a refuse l'autorisation : {error}")

    _cleanup_states()
    pending = _pending_states.pop(state_key, None)
    if not pending or pending["expires_at"] < time.time():
        return _err("Lien expire ou invalide - reessaie depuis le dashboard.")

    account       = pending["account"]
    client_id     = os.getenv("TWITCH_CLIENT_ID","")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET","")
    base_url      = os.getenv("WEB_BASE_URL", str(request.base_url).rstrip("/"))
    redirect_uri  = f"{base_url}/api/admin/twitch/auth/callback"

    try:
        async with httpx.AsyncClient() as c:
            resp = await c.post(_TWITCH_TOKEN_URL, data={
                "client_id": client_id, "client_secret": client_secret,
                "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
            }, timeout=15)
    except Exception as exc:
        logger.error("Twitch token exchange network error: {}", exc)
        return _err("Erreur reseau lors de l'echange du code.")

    if resp.status_code != 200:
        logger.error("Twitch token exchange HTTP {}: {}", resp.status_code, resp.text)
        return _err(f"Twitch a rejete l'echange ({resp.status_code}).")

    tokens        = resp.json()
    access_token  = tokens.get("access_token","")
    refresh_token = tokens.get("refresh_token","")

    username = ""
    user_id  = ""
    try:
        async with httpx.AsyncClient() as c:
            ur = await c.get(_TWITCH_USERS_URL,
                headers={"Authorization": f"Bearer {access_token}", "Client-Id": client_id},
                timeout=10)
        if ur.status_code == 200:
            users = ur.json().get("data",[])
            if users:
                username = users[0].get("display_name","")
                user_id  = users[0].get("id","")
    except Exception as exc:
        logger.warning("Could not fetch Twitch username after OAuth: {}", exc)

    # .env path
    _ep = os.getenv("ENV_PATH","")
    env_path = Path(_ep) if _ep else (Path(__file__).parent.parent.parent.parent / ".env")

    state   = request.app.state.wally
    tm      = getattr(getattr(state,"twitch_bot",None),"token_manager",None)
    if tm is not None:
        tm._write_env(account, access_token, refresh_token)
        if account == "bot":
            tm._bot_token    = access_token
            tm._bot_refresh  = refresh_token
        else:
            tm._streamer_token   = access_token
            tm._streamer_refresh = refresh_token
    else:
        _write_env_direct(env_path, account, access_token, refresh_token)

    _write_env_ids(env_path, account, user_id, username)
    _status_cache.clear()

    broadcast_event({"type":"twitch_auth","account":account,"username":username,"user_id":user_id})
    logger.info("Twitch {} OAuth success - user={} id={}", account, username, user_id)

    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
        "<h2>Compte connecte !</h2>"
        "<p>Tu peux fermer cet onglet et revenir au dashboard.</p>"
        "<script>window.close();</script></body></html>"
    )


@router.post("/twitch/restart")
async def restart_twitch_container(request: Request) -> dict:
    logger.warning("Twitch restart requested via dashboard")
    compose_file = os.getenv("COMPOSE_FILE","/app/docker-compose.yml")

    async def _do():
        await asyncio.sleep(1)
        proc = await asyncio.create_subprocess_exec(
            "docker","compose","-f",compose_file,"restart","wally",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("Twitch restart failed: {}", stderr.decode())

    task = asyncio.create_task(_do())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"ok": True}
