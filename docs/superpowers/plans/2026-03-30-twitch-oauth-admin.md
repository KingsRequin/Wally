# Twitch OAuth Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un flux OAuth Twitch dans le dashboard admin (Système > Twitch) permettant de connecter/reconnecter les comptes bot et streamer sans éditer `.env` manuellement, suivi d'un redémarrage du container.

**Architecture:** Nouveau fichier `bot/dashboard/routes/twitch_auth.py` avec 4 routes admin (auth-status, auth-url, callback, restart). Le callback échange le code OAuth, écrit les tokens dans `.env` via `token_manager._write_env()`, push un event SSE `twitch_auth` au dashboard. Le JS réécrit `_renderSystemeTwitch` pour afficher deux cards de statut avec boutons "Connecter"/"Reconnecter" et un bouton "Redémarrer" post-auth.

**Tech Stack:** FastAPI, httpx, Python asyncio, vanilla JS (SSE via EventSource), Twitch OAuth2 (id.twitch.tv/oauth2)

---

## File Map

| Fichier | Action | Responsabilité |
|---|---|---|
| `bot/dashboard/routes/twitch_auth.py` | Créer | 4 routes OAuth admin |
| `bot/dashboard/app.py` | Modifier | Monter `twitch_auth.router` sur `/api/admin` |
| `bot/dashboard/static/app.js` | Modifier | Réécrire `_renderSystemeTwitch`, handler SSE `twitch_auth` |
| `tests/dashboard/test_twitch_auth.py` | Créer | Tests des 4 routes |

---

## Task 1 : Routes backend `twitch_auth.py`

**Files:**
- Create: `bot/dashboard/routes/twitch_auth.py`
- Test: `tests/dashboard/test_twitch_auth.py`

### Constantes et helpers

```python
# bot/dashboard/routes/twitch_auth.py
from __future__ import annotations
import asyncio, os, re, time, urllib.parse, uuid
from pathlib import Path
from typing import Any
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
_bg_tasks: set = set()
```

### Helper `_cleanup_states`

```python
def _cleanup_states() -> None:
    now = time.time()
    for k in [k for k, v in _pending_states.items() if v["expires_at"] < now]:
        del _pending_states[k]
```

### Helper `_validate_token`

```python
async def _validate_token(token: str, client_id: str) -> dict | None:
    """Appelle /helix/users avec le token, retourne {username, user_id} ou None."""
    if not token or not client_id:
        return None
    now = time.time()
    cache_key = token[:16]
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
```

### Helper `_write_env_direct` et `_write_env_ids`

```python
def _write_env_direct(env_path: Path, account: str, access: str, refresh: str) -> None:
    """Écrit tokens dans .env quand token_manager n'est pas disponible."""
    ak, rk = ("BOT_ACCESS_TOKEN","BOT_REFRESH_TOKEN") if account=="bot" else ("STREAMER_ACCESS_TOKEN","STREAMER_REFRESH_TOKEN")
    if not env_path.exists():
        return
    def _rop(text, key, val):
        pat = rf"^{key}=.*$"
        if re.search(pat, text, flags=re.MULTILINE):
            return re.sub(pat, f"{key}={val}", text, flags=re.MULTILINE)
        return text.rstrip("\n") + f"\n{key}={val}\n"
    content = env_path.read_text(encoding="utf-8")
    content = _rop(_rop(content, ak, access), rk, refresh)
    env_path.write_text(content, encoding="utf-8")

def _write_env_ids(env_path: Path, account: str, user_id: str, username: str) -> None:
    """Écrit TWITCH_BOT_ID/NICK ou TWITCH_BROADCASTER_ID dans .env."""
    if not user_id or not env_path.exists():
        return
    def _rop(text, key, val):
        pat = rf"^{key}=.*$"
        if re.search(pat, text, flags=re.MULTILINE):
            return re.sub(pat, f"{key}={val}", text, flags=re.MULTILINE)
        return text.rstrip("\n") + f"\n{key}={val}\n"
    content = env_path.read_text(encoding="utf-8")
    if account == "bot":
        content = _rop(content, "TWITCH_BOT_ID", user_id)
        if username:
            content = _rop(content, "TWITCH_BOT_NICK", username)
    else:
        content = _rop(content, "TWITCH_BROADCASTER_ID", user_id)
    env_path.write_text(content, encoding="utf-8")
```

### Route `GET /api/admin/twitch/auth-status`

```python
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
```

### Route `POST /api/admin/twitch/auth-url`

```python
@router.post("/twitch/auth-url")
async def twitch_auth_url(request: Request) -> dict:
    body    = await request.json()
    account = body.get("account", "bot")
    if account not in ("bot","streamer"):
        raise HTTPException(400, "account doit être 'bot' ou 'streamer'")
    client_id = os.getenv("TWITCH_CLIENT_ID","")
    if not client_id:
        raise HTTPException(400, "TWITCH_CLIENT_ID non configuré dans .env")
    base_url     = os.getenv("WEB_BASE_URL", str(request.base_url).rstrip("/"))
    redirect_uri = f"{base_url}/api/admin/twitch/auth/callback"
    _cleanup_states()
    state_key = uuid.uuid4().hex
    _pending_states[state_key] = {"account": account, "expires_at": time.time() + 600}
    scope  = _BOT_SCOPES if account == "bot" else _STREAMER_SCOPES
    params = {"response_type":"code","client_id":client_id,"redirect_uri":redirect_uri,"scope":scope,"state":state_key}
    return {"url": "https://id.twitch.tv/oauth2/authorize?" + urllib.parse.urlencode(params)}
```

### Route `GET /api/admin/twitch/auth/callback`

```python
@router.get("/twitch/auth/callback")
async def twitch_auth_callback(request: Request):
    code      = request.query_params.get("code","")
    state_key = request.query_params.get("state","")
    error     = request.query_params.get("error","")

    def _err(msg):
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
            f"<h2>Erreur</h2><p>{msg}</p><p>Ferme cet onglet et réessaie.</p></body></html>"
        )

    if error:
        return _err(f"Twitch a refusé l'autorisation : {error}")

    _cleanup_states()
    pending = _pending_states.pop(state_key, None)
    if not pending or pending["expires_at"] < time.time():
        return _err("Lien expiré ou invalide — réessaie depuis le dashboard.")

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
        return _err("Erreur réseau lors de l'échange du code.")

    if resp.status_code != 200:
        logger.error("Twitch token exchange HTTP {}: {}", resp.status_code, resp.text)
        return _err(f"Twitch a rejeté l'échange ({resp.status_code}).")

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
    logger.info("Twitch {} OAuth success — user={} id={}", account, username, user_id)

    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
        "<h2>Compte connecte !</h2>"
        "<p>Tu peux fermer cet onglet et revenir au dashboard.</p>"
        "<script>window.close();</script></body></html>"
    )
```

### Route `POST /api/admin/twitch/restart`

Même pattern que `POST /api/admin/bot/restart` dans `admin.py:649` — utiliser `asyncio.create_subprocess_exec("docker","compose","-f",compose_file,"restart","wally")`.

```python
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
```

- [ ] **Étape 1 : Écrire les tests failing**

Créer `tests/dashboard/test_twitch_auth.py` :

```python
from __future__ import annotations
import os, pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from bot.dashboard.routes import twitch_auth
from bot.dashboard.auth import BearerAuthMiddleware

def _make_app(bot_token="", streamer_token=""):
    app = FastAPI()
    state = MagicMock()
    state.config.bot.dashboard_token = "test-token"
    tm = MagicMock()
    tm.bot_token = bot_token
    tm.streamer_token = streamer_token
    twitch_bot = MagicMock()
    twitch_bot.token_manager = tm
    state.twitch_bot = twitch_bot
    app.state.wally = state
    app.add_middleware(BearerAuthMiddleware, state=state)
    app.include_router(twitch_auth.router, prefix="/api/admin")
    return app

H = {"Authorization": "Bearer test-token"}

def test_auth_status_no_tokens():
    with patch.object(twitch_auth, "_validate_token", new=AsyncMock(return_value=None)):
        client = TestClient(_make_app())
        r = client.get("/api/admin/twitch/auth-status", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["bot"]["connected"] is False
    assert d["streamer"]["connected"] is False

def test_auth_status_bot_connected():
    info = {"username": "WallyTeBully", "user_id": "961407719"}
    with patch.object(twitch_auth, "_validate_token", new=AsyncMock(side_effect=[info, None])):
        client = TestClient(_make_app(bot_token="valid"))
        r = client.get("/api/admin/twitch/auth-status", headers=H)
    assert r.json()["bot"]["connected"] is True
    assert r.json()["bot"]["username"] == "WallyTeBully"

def test_auth_url_bot():
    with patch.dict(os.environ, {"TWITCH_CLIENT_ID": "cid", "WEB_BASE_URL": "https://ex.com"}):
        client = TestClient(_make_app())
        r = client.post("/api/admin/twitch/auth-url", json={"account":"bot"}, headers=H)
    assert r.status_code == 200
    assert "id.twitch.tv/oauth2/authorize" in r.json()["url"]
    assert "user%3Aread%3Achat" in r.json()["url"] or "user:read:chat" in r.json()["url"]

def test_auth_url_streamer():
    with patch.dict(os.environ, {"TWITCH_CLIENT_ID": "cid", "WEB_BASE_URL": "https://ex.com"}):
        client = TestClient(_make_app())
        r = client.post("/api/admin/twitch/auth-url", json={"account":"streamer"}, headers=H)
    assert "channel" in r.json()["url"]

def test_auth_url_missing_client_id():
    env = {k:v for k,v in os.environ.items() if k != "TWITCH_CLIENT_ID"}
    with patch.dict(os.environ, env, clear=True):
        client = TestClient(_make_app())
        r = client.post("/api/admin/twitch/auth-url", json={"account":"bot"}, headers=H)
    assert r.status_code == 400

def test_callback_invalid_state():
    client = TestClient(_make_app())
    r = client.get("/api/admin/twitch/auth/callback?code=x&state=nonexistent", headers=H)
    assert r.status_code == 200
    assert "xpir" in r.text.lower() or "nvalid" in r.text.lower() or "erreur" in r.text.lower()
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/dashboard/test_twitch_auth.py -v 2>&1 | head -20
```

Attendu : `ImportError: cannot import name 'twitch_auth'` (module pas encore créé).

- [ ] **Étape 3 : Créer `bot/dashboard/routes/twitch_auth.py`**

Copier le code de chaque section ci-dessus dans un seul fichier, dans l'ordre :
1. Imports + constantes
2. `_cleanup_states`
3. `_validate_token`
4. `_write_env_direct`
5. `_write_env_ids`
6. Toutes les routes

- [ ] **Étape 4 : Lancer les tests**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/dashboard/test_twitch_auth.py -v
```

Attendu : 6 tests PASSED.

- [ ] **Étape 5 : Commit**

```bash
git add bot/dashboard/routes/twitch_auth.py tests/dashboard/test_twitch_auth.py
git commit -m "feat(twitch-auth): routes OAuth admin — auth-status, auth-url, callback, restart"
```

---

## Task 2 : Monter le router dans `app.py`

**Files:**
- Modify: `bot/dashboard/app.py`

- [ ] **Étape 1 : Ajouter l'import**

Ligne 90 de `bot/dashboard/app.py`, ajouter `twitch_auth` :

```python
# Avant
from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, costs, roadmap, chat_auth, chat, gallery, actions, setup

# Après
from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, costs, roadmap, chat_auth, chat, gallery, actions, setup, twitch_auth
```

- [ ] **Étape 2 : Monter le router**

Après la ligne `app.include_router(setup.wizard_router, prefix="/api/setup")` (~ligne 114), ajouter :

```python
    app.include_router(twitch_auth.router, prefix="/api/admin")
```

- [ ] **Étape 3 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai
python -c "from bot.dashboard.routes import twitch_auth; print('OK', [r.path for r in twitch_auth.router.routes])"
```

Attendu : `OK ['/twitch/auth-status', '/twitch/auth-url', '/twitch/auth/callback', '/twitch/restart']`

- [ ] **Étape 4 : Lancer toute la suite de tests**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/ -x -q 2>&1 | tail -5
```

Attendu : aucune régression.

- [ ] **Étape 5 : Commit**

```bash
git add bot/dashboard/app.py
git commit -m "feat(twitch-auth): monter twitch_auth router sur /api/admin"
```

---

## Task 3 : UI dans `app.js`

**Files:**
- Modify: `bot/dashboard/static/app.js`

### 3a — Variable globale et handler SSE

- [ ] **Étape 1 : Ajouter `_twitchPendingRestart`**

Chercher `var logSSE` dans `app.js` (vers le début du fichier). Juste en dessous, ajouter :

```javascript
var _twitchPendingRestart = false;
```

- [ ] **Étape 2 : Ajouter le handler SSE dans `startLogSSE`**

Dans `startLogSSE`, repérer ce bloc (ligne ~1539) :

```javascript
      if (data.type === 'links_analyzed' || data.type === 'link_accepted' || data.type === 'link_rejected' || data.type === 'link_unlinked') {
        loadMemoryUsers();
        pollLinksBadge();
        if (data.type === 'links_analyzed' && data.count > 0) {
          toast(`🔗 ${data.count} liaison(s) à vérifier`, 'info');
        }
        return;
      }
      appendLog(data);
```

Ajouter avant `appendLog(data)` :

```javascript
      if (data.type === 'twitch_auth') {
        _onTwitchAuthSuccess(data.account, data.username);
        return;
      }
```

- [ ] **Étape 3 : Ajouter les fonctions utilitaires après `_waitForReconnect`**

Après la fonction `_waitForReconnect` (ligne ~230), ajouter :

```javascript
function _onTwitchAuthSuccess(account, username) {
  _twitchPendingRestart = true;
  var label = account === 'bot' ? 'bot' : 'streamer';
  toast('Compte ' + label + ' connecte' + (username ? ' — ' + username : '') + ' ! Redemarre le container.', 'success');
  var panel = document.getElementById('systeme-sub-twitch');
  if (panel && panel.classList.contains('active')) {
    _renderSystemeTwitch(panel);
  }
}

async function startTwitchOAuth(account) {
  var r = await apiFetch('/api/admin/twitch/auth-url', {
    method: 'POST',
    body: JSON.stringify({ account: account }),
  });
  if (!r || !r.ok) { toast('Erreur generation URL OAuth', 'error'); return; }
  var data = await r.json();
  var popup = window.open(data.url, 'twitch-oauth', 'width=600,height=700,noopener');
  if (!popup) toast('Popup bloque — autorise les popups pour ce site.', 'error');
}

async function restartTwitchContainer() {
  if (!confirm('Redemarrer le container Wally ? Le dashboard sera indisponible ~10s.')) return;
  var r = await apiFetch('/api/admin/twitch/restart', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur restart', 'error'); return; }
  _twitchPendingRestart = false;
  toast('Redemerrage en cours...', 'success');
  _waitForReconnect();
}
```

### 3b — Réécriture de `_renderSystemeTwitch`

- [ ] **Étape 4 : Remplacer la fonction `_renderSystemeTwitch`**

Remplacer l'intégralité de la fonction `_renderSystemeTwitch` (ligne ~4759, de `async function _renderSystemeTwitch(panel)` jusqu'à la `}` fermante) par :

```javascript
async function _renderSystemeTwitch(panel) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:var(--text-muted);padding:16px">Chargement...</p>';

  var statusR = await apiFetch('/api/admin/twitch/auth-status');
  var status  = statusR && statusR.ok ? await statusR.json() : null;

  var botConnected     = status && status.bot.connected;
  var streamerConnected = status && status.streamer.connected;
  var clientIdSet      = status ? status.client_id_set : false;

  var BOT_SCOPES      = 'user:read:chat · user:write:chat · user:bot · moderator:read:followers · chat:read · chat:edit';
  var STREAMER_SCOPES = 'channel:read:subscriptions · bits:read';

  function _authCard(id, icon, title, connected, username, scopes) {
    var dotColor   = connected ? '#22c55e' : '#ef4444';
    var statusText = connected ? (username || 'Connecte') : 'Non connecte';
    var btnLabel   = connected ? 'Reconnecter' : 'Connecter';
    var btn = clientIdSet
      ? '<button class="btn btn-success" style="width:100%;margin-top:4px" onclick="startTwitchOAuth(\'' + id + '\')">' + btnLabel + '</button>'
      : '<p style="color:#f59e0b;font-size:0.8em;margin-top:8px">Configurer TWITCH_CLIENT_ID dans .env</p>';
    return '<div class="card" style="flex:1;min-width:220px;padding:20px">'
      + '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">'
      + '<span style="font-size:1.5em">' + icon + '</span>'
      + '<div><div class="card-title" style="margin:0">' + title + '</div>'
      + '<div style="display:flex;align-items:center;gap:6px;margin-top:4px">'
      + '<span style="width:8px;height:8px;border-radius:50%;background:' + dotColor + ';display:inline-block"></span>'
      + '<span style="font-size:0.85em;color:' + (connected ? 'var(--text-primary)' : 'var(--text-muted)') + '">' + statusText + '</span>'
      + '</div></div></div>'
      + '<div style="font-size:0.75em;color:var(--text-muted);margin-bottom:14px;line-height:1.6"><strong>Scopes :</strong> ' + scopes + '</div>'
      + btn
      + '</div>';
  }

  // Charger les chaines invitees
  var chR = await apiFetch('/api/admin/twitch/channels');
  var channelsHtml = '';
  if (chR && chR.ok) {
    var channels = await chR.json();
    channelsHtml = channels.length === 0
      ? '<p style="color:var(--text-muted);margin-bottom:12px">Aucune chaine invitee.</p>'
      : channels.map(function(ch) {
          var dotClass   = ch.irc_connected ? 'connected' : 'pending';
          var badgeClass = ch.live ? 'live' : 'offline';
          var badgeText  = ch.live ? 'LIVE' : 'hors ligne';
          return '<div class="twitch-channel-card" id="guest-ch-' + ch.name + '">'
            + '<div class="tc-dot ' + dotClass + '"></div>'
            + '<span class="tc-name">' + ch.name + '</span>'
            + '<span class="tc-badge ' + badgeClass + '">' + badgeText + '</span>'
            + '<button class="tc-kick" onclick="removeGuestChannel(\'' + ch.name + '\')">Deconnecter</button>'
            + '</div>';
        }).join('');
  } else {
    channelsHtml = '<p style="color:var(--text-muted);font-size:0.85em">Twitch non demarre — connecte les comptes ci-dessus et redemarre.</p>';
  }

  var restartHtml = _twitchPendingRestart
    ? '<div style="margin-top:20px">'
      + '<button class="btn" style="background:#f59e0b;color:#000;font-weight:600;width:100%" onclick="restartTwitchContainer()">Redemarrer le container</button>'
      + '<p style="font-size:0.75em;color:var(--text-muted);margin-top:6px;text-align:center">Le dashboard sera indisponible ~10s.</p>'
      + '</div>'
    : '';

  panel.innerHTML = '<div style="padding:0 2px">'
    + '<div style="font-size:0.7em;letter-spacing:.08em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px">Authentification Twitch</div>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px">'
    + _authCard('bot',      '🤖', 'Compte Bot',      botConnected,      status && status.bot.username,      BOT_SCOPES)
    + _authCard('streamer', '📺', 'Compte Streamer',  streamerConnected, status && status.streamer.username, STREAMER_SCOPES)
    + '</div>'
    + restartHtml
    + '<hr style="border-color:rgba(255,255,255,0.08);margin:16px 0">'
    + '<div style="font-size:0.7em;letter-spacing:.08em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px">Chaines invitees</div>'
    + '<div id="guest-channels-list">' + channelsHtml + '</div>'
    + '<div id="twitch-channels-add">'
    + '<input type="text" id="guest-channel-input" placeholder="nom de chaine twitch..." style="flex:1" onkeydown="if(event.key===\'Enter\') addGuestChannel()">'
    + '<button class="btn btn-success" onclick="addGuestChannel()">+ Ajouter</button>'
    + '</div>'
    + '<div id="guest-channel-error" style="color:var(--c-offline);font-size:0.85em;margin-top:6px;display:none"></div>'
    + '<p style="color:var(--text-muted);font-size:0.8em;margin-top:10px">Le broadcaster doit avoir autorise le bot (scope channel:bot) pour que Wally puisse parler.</p>'
    + '</div>';

  // Vider le div legacy tab-admin-twitch pour eviter les doublons
  var twitchEl = document.getElementById('tab-admin-twitch');
  if (twitchEl) twitchEl.innerHTML = '';
}
```

- [ ] **Étape 5 : Vérifier la syntaxe JS**

```bash
node --check /opt/stacks/wally-ai/bot/dashboard/static/app.js && echo "OK"
```

Attendu : `OK`

- [ ] **Étape 6 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(twitch-auth): UI Systeme>Twitch — cards auth, SSE handler, bouton restart"
```

---

## Task 4 : Test d'intégration manuel

- [ ] **Étape 1 : Rebuild + démarrer**

```bash
cd /opt/stacks/wally-ai
docker compose build wally && docker compose up -d wally
sleep 5 && docker compose logs wally --tail=20
```

Attendu : pas d'erreur d'import, dashboard démarre sur port 8080.

- [ ] **Étape 2 : Vérifier `auth-status`**

```bash
TOKEN=$(grep DASHBOARD_TOKEN /opt/stacks/wally-ai/.env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/admin/twitch/auth-status | python3 -m json.tool
```

Attendu : JSON avec `bot.connected`, `streamer.connected`, `client_id_set: true`.

- [ ] **Étape 3 : Ouvrir le dashboard > Système > Twitch**

Vérifier visuellement :
- Deux cards "Compte Bot" et "Compte Streamer" avec statut vert/rouge
- Bouton "Connecter"/"Reconnecter" présent sur chaque card
- Section "Chaînes invitées" en dessous

- [ ] **Étape 4 : Tester le flux OAuth complet**

- Cliquer "Connecter" sur "Compte Bot"
- S'authentifier sur Twitch avec le compte bot
- Vérifier : popup se ferme, toast "Compte bot connecté", bouton "Redémarrer" apparaît
- Vérifier dans `.env` que `BOT_ACCESS_TOKEN`, `BOT_REFRESH_TOKEN`, `TWITCH_BOT_ID`, `TWITCH_BOT_NICK` sont mis à jour

- [ ] **Étape 5 : Tester le redémarrage**

- Cliquer "Redémarrer le container"
- Confirmer
- Vérifier que `_waitForReconnect` reprend et affiche "Bot reconnecté !" après ~10s
- Vérifier que le bot Twitch démarre bien (logs + statut control bar)
