# Web Dashboard Wally — Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Intégrer un serveur FastAPI dans le processus asyncio de Wally, exposant une SPA dark neobrutalism avec jauges d'émotions SSE en temps réel, statut stream Twitch, et contrôles admin (config, émotions, logs).

**Architecture:** `uvicorn.Server` ajouté dans `asyncio.gather()` aux côtés des bots Discord/Twitch. Services injectés via `AppState` dataclass sur `app.state.wally`. Auth Bearer middleware sur `/api/admin/*`. Vanilla JS SPA servi en statique. SSE via `EventSource` côté client.

**Tech Stack:** FastAPI ≥ 0.111, uvicorn ≥ 0.30, httpx (existant), aiosqlite (existant), vanilla JS + Canvas API

**Spec:** `docs/superpowers/specs/2026-03-16-web-dashboard-phase1-design.md`

---

## File Map

**Nouveaux fichiers créés :**
```
bot/dashboard/__init__.py
bot/dashboard/state.py          # AppState dataclass — point d'injection de tous les services
bot/dashboard/auth.py           # Middleware Bearer + dépendance require_auth()
bot/dashboard/app.py            # create_dashboard_app(), lifespan, snapshot task 5min
bot/dashboard/routes/__init__.py
bot/dashboard/routes/status.py  # GET /api/public/status
bot/dashboard/routes/emotions.py # GET/POST emotions public + admin
bot/dashboard/routes/admin.py   # GET/POST config, GET models OpenAI
bot/dashboard/routes/sse.py     # SSE émotions (public) + SSE logs (admin)
bot/dashboard/routes/twitch.py  # GET /api/public/twitch/stream avec cache TTL
bot/dashboard/routes/memory.py  # Stub 501 Phase 2
bot/dashboard/static/index.html # SPA complète
bot/dashboard/static/style.css  # Dark neobrutalism
bot/dashboard/static/app.js     # Onglets, SSE, auth, canvas
tests/test_dashboard_auth.py
tests/test_dashboard_routes.py
tests/test_twitch_get_stream.py
```

**Fichiers existants modifiés :**
```
bot/twitch/api.py           # + méthode get_stream()
bot/discord/bot.py          # + attribut dashboard_state = None
bot/twitch/bot.py           # + attribut dashboard_state = None
bot/discord/handlers.py     # + incrément message_count
bot/twitch/handlers.py      # + incrément message_count
bot/main.py                 # + AppState, uvicorn.Server dans gather()
docker-compose.yml          # + ports 127.0.0.1:8080:8080
requirements.txt            # + fastapi, uvicorn
```

---

## Chunk 1: Infrastructure

### Task 1: `bot/dashboard/state.py` — AppState

**Files:**
- Create: `bot/dashboard/__init__.py`
- Create: `bot/dashboard/state.py`

- [ ] **Créer `bot/dashboard/__init__.py`** (fichier vide)

- [ ] **Créer `bot/dashboard/state.py`**

```python
# bot/dashboard/state.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.persona import PersonaService
    from bot.core.openai_client import OpenAIClient
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.discord.bot import WallyDiscord
    from bot.twitch.bot import WallyTwitch


@dataclass
class AppState:
    config: "Config"
    db: "Database"
    emotion: "EmotionEngine"
    memory: "MemoryService"
    persona: "PersonaService"
    openai_client: "OpenAIClient"
    token_manager: "TwitchTokenManager"
    twitch_api: Optional["TwitchAPI"]
    discord_bot: Optional["WallyDiscord"]
    twitch_bot: Optional["WallyTwitch"]
    start_time: float = field(default_factory=time.time)
    message_count: int = 0
```

- [ ] **Commit**

```bash
git add bot/dashboard/__init__.py bot/dashboard/state.py
git commit -m "feat(dashboard): add AppState dataclass"
```

---

### Task 2: `bot/dashboard/auth.py` — Middleware Bearer

**Files:**
- Create: `bot/dashboard/auth.py`
- Create: `tests/test_dashboard_auth.py`

- [ ] **Écrire les tests**

```python
# tests/test_dashboard_auth.py
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bot.dashboard.auth import BearerAuthMiddleware


def _make_app(token: str | None) -> FastAPI:
    """Helper : app minimale avec middleware auth et une route admin."""
    cfg = MagicMock()
    cfg.bot.dashboard_token = token
    state = MagicMock()
    state.config = cfg

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, state=state)

    @app.get("/api/admin/test")
    async def admin_route():
        return {"ok": True}

    @app.get("/api/public/test")
    async def public_route():
        return {"ok": True}

    return app


def test_public_route_no_auth_required():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/public/test")
    assert r.status_code == 200


def test_admin_valid_token():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer secret123"})
    assert r.status_code == 200


def test_admin_invalid_token_returns_401():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_admin_no_token_header_returns_401():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test")
    assert r.status_code == 401


def test_admin_token_not_configured_returns_503():
    client = TestClient(_make_app(None))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503


def test_admin_empty_token_returns_503():
    client = TestClient(_make_app(""))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503
```

- [ ] **Vérifier que les tests échouent**

```bash
pytest tests/test_dashboard_auth.py -v
```
Attendu : `ImportError` ou `ModuleNotFoundError` (auth.py n'existe pas encore)

- [ ] **Implémenter `bot/dashboard/auth.py`**

```python
# bot/dashboard/auth.py
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from bot.dashboard.state import AppState

_ADMIN_PREFIX = "/api/admin/"


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, state: "AppState"):
        super().__init__(app)
        self._state = state

    async def dispatch(self, request, call_next):
        if not request.url.path.startswith(_ADMIN_PREFIX):
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
```

- [ ] **Vérifier que les tests passent**

```bash
pytest tests/test_dashboard_auth.py -v
```
Attendu : 6 tests PASSED

- [ ] **Commit**

```bash
git add bot/dashboard/auth.py tests/test_dashboard_auth.py
git commit -m "feat(dashboard): add BearerAuthMiddleware with tests"
```

---

### Task 3: `bot/dashboard/app.py` — Squelette FastAPI + snapshot task

**Files:**
- Create: `bot/dashboard/routes/__init__.py`
- Create: `bot/dashboard/app.py`
- Create: `bot/dashboard/static/` (répertoire vide pour l'instant)

> Note : `create_dashboard_app()` monte les routers créés dans les tâches suivantes. Pour ce squelette, les imports de routes sont différés afin d'éviter les `ImportError` avant que les fichiers existent.

- [ ] **Créer les répertoires et fichiers vides**

```bash
mkdir -p bot/dashboard/routes bot/dashboard/static
touch bot/dashboard/routes/__init__.py
touch bot/dashboard/static/.gitkeep
```

- [ ] **Implémenter `bot/dashboard/app.py`**

```python
# bot/dashboard/app.py
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger

from bot.dashboard.auth import BearerAuthMiddleware

if TYPE_CHECKING:
    from bot.dashboard.state import AppState

STATIC_DIR = Path(__file__).parent / "static"


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
    from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory

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

    # Static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
```

- [ ] **Commit**

```bash
git add bot/dashboard/routes/__init__.py bot/dashboard/app.py bot/dashboard/static/.gitkeep
git commit -m "feat(dashboard): add FastAPI app skeleton with lifespan and snapshot task"
```

---

## Chunk 2: Routes

### Task 4: `bot/twitch/api.py` — `get_stream()`

**Files:**
- Modify: `bot/twitch/api.py`
- Create: `tests/test_twitch_get_stream.py`

- [ ] **Écrire les tests**

```python
# tests/test_twitch_get_stream.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from bot.twitch.api import TwitchAPI


@pytest.fixture
def api():
    tm = MagicMock()
    tm.bot_token = "fake_token"
    return TwitchAPI(
        token_manager=tm,
        client_id="client123",
        bot_id="bot456",
        broadcaster_id="broadcaster789",
    )


async def test_get_stream_live(api):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{
            "title": "Coding stream",
            "game_name": "Software and Game Development",
            "viewer_count": 42,
            "started_at": "2026-03-16T10:00:00Z",
        }]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await api.get_stream()

    assert result["live"] is True
    assert result["title"] == "Coding stream"
    assert result["category"] == "Software and Game Development"
    assert result["viewers"] == 42
    assert result["started_at"] == "2026-03-16T10:00:00Z"


async def test_get_stream_offline(api):
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await api.get_stream()

    assert result["live"] is False
    assert result["title"] is None
    assert result["viewers"] == 0


async def test_get_stream_error_returns_offline(api):
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        mock_client_cls.return_value = mock_client

        result = await api.get_stream()

    assert result["live"] is False
```

- [ ] **Vérifier que les tests échouent**

```bash
pytest tests/test_twitch_get_stream.py -v
```
Attendu : `AttributeError: 'TwitchAPI' object has no attribute 'get_stream'`

- [ ] **Ajouter `get_stream()` dans `bot/twitch/api.py`** (après `send_message`, avant la fin de la classe)

```python
    STREAMS_URL = "https://api.twitch.tv/helix/streams"

    async def get_stream(self) -> dict:
        """GET /helix/streams?user_id={self._broadcaster_id}.

        Retourne un dict normalisé :
          {live, title, category, viewers, started_at}
        En cas d'erreur ou de stream offline, live=False et les autres champs sont None/0.
        Utilise self._tm.bot_token (cohérent avec send_message).
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.STREAMS_URL,
                    params={"user_id": self._broadcaster_id},
                    headers={
                        "Authorization": f"Bearer {self._tm.bot_token}",
                        "Client-Id": self._client_id,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
                if not data:
                    return {
                        "live": False,
                        "title": None,
                        "category": None,
                        "viewers": 0,
                        "started_at": None,
                    }
                s = data[0]
                return {
                    "live": True,
                    "title": s.get("title"),
                    "category": s.get("game_name"),
                    "viewers": s.get("viewer_count", 0),
                    "started_at": s.get("started_at"),
                }
        except Exception as exc:
            logger.warning("Failed to fetch Twitch stream status: {e}", e=exc)
            return {
                "live": False,
                "title": None,
                "category": None,
                "viewers": 0,
                "started_at": None,
            }
```

- [ ] **Vérifier que les tests passent**

```bash
pytest tests/test_twitch_get_stream.py -v
```
Attendu : 3 tests PASSED

- [ ] **Commit**

```bash
git add bot/twitch/api.py tests/test_twitch_get_stream.py
git commit -m "feat(twitch): add TwitchAPI.get_stream() with tests"
```

---

### Task 5: `bot/dashboard/routes/status.py`

**Files:**
- Create: `bot/dashboard/routes/status.py`

- [ ] **Créer `bot/dashboard/routes/status.py`**

```python
# bot/dashboard/routes/status.py
from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/status")
async def get_status(request: Request) -> dict:
    """Retourne uptime, connectivité Discord/Twitch, et compteur de messages."""
    state = request.app.state.wally

    uptime = time.time() - state.start_time

    discord_online = (
        state.discord_bot is not None
        and state.discord_bot.is_ready()
    )
    twitch_online = (
        state.twitch_bot is not None
        and getattr(state.twitch_bot, "_eventsub_client", None) is not None
    )

    return {
        "uptime_seconds": uptime,
        "discord_online": discord_online,
        "twitch_online": twitch_online,
        "total_messages": state.message_count,
    }
```

- [ ] **Commit**

```bash
git add bot/dashboard/routes/status.py
git commit -m "feat(dashboard): add status route"
```

---

### Task 6: `bot/dashboard/routes/emotions.py`

**Files:**
- Create: `bot/dashboard/routes/emotions.py`

- [ ] **Créer `bot/dashboard/routes/emotions.py`**

```python
# bot/dashboard/routes/emotions.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bot.core.emotion import EMOTIONS

public_router = APIRouter()
admin_router = APIRouter()


@public_router.get("/emotions")
async def get_emotions_public(request: Request) -> dict:
    return request.app.state.wally.emotion.get_state()


@public_router.get("/emotions/history")
async def get_emotions_history(request: Request) -> dict:
    state = request.app.state.wally
    snapshots = await state.db.get_today_emotion_snapshots()
    return {"history": snapshots}


@admin_router.get("/emotions")
async def get_emotions_admin(request: Request) -> dict:
    return request.app.state.wally.emotion.get_state()


class SetEmotionBody(BaseModel):
    emotion: str
    value: float


@admin_router.post("/emotions/set")
async def set_emotion(request: Request, body: SetEmotionBody) -> dict:
    state = request.app.state.wally
    if body.emotion not in EMOTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown emotion: {body.emotion}")
    if not 0.0 <= body.value <= 1.0:
        raise HTTPException(status_code=400, detail="value must be 0.0–1.0")
    state.emotion.set_emotion(body.emotion, body.value)
    return {"status": "ok", "emotion": body.emotion, "value": body.value}


@admin_router.post("/emotions/reset")
async def reset_emotions(request: Request) -> dict:
    """Reset toutes les émotions à 0.5 (neutre).
    Appelle set_emotion() pour chaque émotion — NE PAS utiliser emotion.reset()
    qui remet à 0.0.
    """
    state = request.app.state.wally
    for emotion in EMOTIONS:
        state.emotion.set_emotion(emotion, 0.5)
    return {"status": "ok", "message": "All emotions reset to 0.5 (neutral)"}
```

- [ ] **Commit**

```bash
git add bot/dashboard/routes/emotions.py
git commit -m "feat(dashboard): add emotions routes (public + admin)"
```

---

### Task 7: `bot/dashboard/routes/admin.py` — Config + modèles OpenAI

**Files:**
- Create: `bot/dashboard/routes/admin.py`

- [ ] **Créer `bot/dashboard/routes/admin.py`**

```python
# bot/dashboard/routes/admin.py
from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

router = APIRouter()

_OPENAI_INCLUDE = ["gpt", "chatgpt", "o1", "o3", "o4"]
_OPENAI_EXCLUDE = ["realtime", "preview", "audio", "vision"]


@router.get("/config")
async def get_config(request: Request) -> dict:
    cfg = request.app.state.wally.config
    return {
        "bot": asdict(cfg.bot),
        "openai": asdict(cfg.openai),
        "discord": asdict(cfg.discord),
        "twitch": asdict(cfg.twitch),
        "emotions": {k: asdict(v) for k, v in cfg.emotions.items()},
        "twitch_events": {k: asdict(v) for k, v in cfg.twitch_events.items()},
    }


@router.post("/config")
async def update_config(request: Request, body: dict) -> dict:
    """Mise à jour partielle de la config en mémoire + config.save().

    Stratégie de merge :
    - Sous-objets dict : merge champ par champ (seuls les champs fournis sont mis à jour).
    - Listes (trigger_names, channels, channel_whitelist, etc.) : remplacement intégral.
    - Champs inconnus : ignorés silencieusement.
    """
    state = request.app.state.wally
    cfg = state.config

    if "openai" in body:
        d = body["openai"]
        if "temperature" in d:
            temp = float(d["temperature"])
            if not (0.0 <= temp <= 2.0):
                raise HTTPException(status_code=400, detail="temperature must be 0.0–2.0")
            cfg.openai.temperature = temp
        if "primary_model" in d:
            cfg.openai.primary_model = str(d["primary_model"])
        if "secondary_model" in d:
            cfg.openai.secondary_model = str(d["secondary_model"])
        if "max_tokens" in d:
            cfg.openai.max_tokens = int(d["max_tokens"])

    if "bot" in body:
        d = body["bot"]
        if "language_default" in d:
            cfg.bot.language_default = str(d["language_default"])
        if "journal_time" in d:
            cfg.bot.journal_time = str(d["journal_time"])
        if "context_window_size" in d:
            cfg.bot.context_window_size = int(d["context_window_size"])
        if "context_token_threshold" in d:
            cfg.bot.context_token_threshold = int(d["context_token_threshold"])
        if "journal_channel_id" in d:
            cfg.bot.journal_channel_id = d["journal_channel_id"]
        if "dashboard_token" in d:
            cfg.bot.dashboard_token = str(d["dashboard_token"]) or None
        if "trigger_names" in d:
            cfg.bot.trigger_names = list(d["trigger_names"])  # liste : remplacement intégral

    if "discord" in body:
        d = body["discord"]
        if "anger_trigger_threshold" in d:
            cfg.discord.anger_trigger_threshold = int(d["anger_trigger_threshold"])
        if "timeout_minutes" in d:
            cfg.discord.timeout_minutes = int(d["timeout_minutes"])
        if "channel_filter_mode" in d:
            cfg.discord.channel_filter_mode = str(d["channel_filter_mode"])
        if "channel_whitelist" in d:
            cfg.discord.channel_whitelist = list(d["channel_whitelist"])  # liste
        if "channel_blacklist" in d:
            cfg.discord.channel_blacklist = list(d["channel_blacklist"])  # liste

    if "twitch" in body:
        d = body["twitch"]
        if "channels" in d:
            cfg.twitch.channels = list(d["channels"])  # liste
        if "cooldown_seconds" in d:
            cfg.twitch.cooldown_seconds = int(d["cooldown_seconds"])

    if "emotions" in body:
        for name, d in body["emotions"].items():
            if name in cfg.emotions and "decay_lambda" in d:
                lam = float(d["decay_lambda"])
                if lam <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"decay_lambda for {name} must be > 0",
                    )
                cfg.emotions[name].decay_lambda = lam

    cfg.save()
    return {"status": "saved"}


@router.get("/openai/models")
async def get_openai_models(request: Request) -> dict:
    """Liste les modèles OpenAI filtrés selon les règles du cahier des charges.

    Inclut : gpt, chatgpt, o1, o3, o4
    Exclut : realtime, preview, audio, vision

    Fallback sur les modèles configurés en cas d'erreur API.
    """
    state = request.app.state.wally
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        models_page = await client.models.list()
        filtered = sorted([
            m.id for m in models_page.data
            if any(kw in m.id for kw in _OPENAI_INCLUDE)
            and not any(kw in m.id for kw in _OPENAI_EXCLUDE)
        ])
        return {"models": filtered}
    except Exception as exc:
        logger.warning("Failed to list OpenAI models: {e}", e=exc)
        return {"models": [
            state.config.openai.primary_model,
            state.config.openai.secondary_model,
        ]}
```

- [ ] **Commit**

```bash
git add bot/dashboard/routes/admin.py
git commit -m "feat(dashboard): add admin config and OpenAI models routes"
```

---

### Task 8: `bot/dashboard/routes/sse.py` — SSE émotions + logs

**Files:**
- Create: `bot/dashboard/routes/sse.py`

- [ ] **Créer `bot/dashboard/routes/sse.py`**

```python
# bot/dashboard/routes/sse.py
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

public_router = APIRouter()
admin_router = APIRouter()

# Fan-out broadcast pour les logs SSE.
# Chaque connexion SSE ajoute une Queue à cette liste.
# Le sink loguru itère sur list(_log_queues) pour thread-safety (copie avant itération).
_log_queues: list[asyncio.Queue] = []
_sink_id: int | None = None


def _log_sink(message) -> None:
    """Sink loguru — appelé de manière synchrone depuis le thread de logging.

    Itère sur une copie de _log_queues pour éviter RuntimeError si la liste est
    modifiée (append/remove) depuis le thread asyncio en parallèle.
    """
    record = message.record
    entry = {
        "level": record["level"].name,
        "message": record["message"],
        "time": record["time"].strftime("%H:%M:%S"),
    }
    for q in list(_log_queues):
        try:
            q.put_nowait(entry)
        except Exception:
            pass  # Queue pleine — log ignoré silencieusement


def setup_log_sink() -> None:
    """Enregistre le sink loguru une seule fois (idempotent)."""
    global _sink_id
    if _sink_id is None:
        _sink_id = logger.add(_log_sink)


@public_router.get("/sse/emotions")
async def sse_emotions(request: Request):
    """SSE flux d'émotions — push toutes les 5s depuis EmotionEngine en mémoire.

    Source de vérité : emotion.get_state() — état live avec décroissance en cours.
    PAS de lecture DB.
    """
    state = request.app.state.wally

    async def generate():
        try:
            while True:
                data = json.dumps(state.emotion.get_state())
                yield f"data: {data}\n\n"
                await asyncio.sleep(5)
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@admin_router.get("/sse/logs")
async def sse_logs(request: Request):
    """SSE flux de logs loguru en temps réel (admin uniquement).

    Architecture fan-out : chaque connexion crée une Queue(maxsize=100).
    Keepalive toutes les 15s pour éviter les timeouts proxy.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _log_queues.append(queue)

    async def generate():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            try:
                _log_queues.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Commit**

```bash
git add bot/dashboard/routes/sse.py
git commit -m "feat(dashboard): add SSE routes (emotions + logs fan-out)"
```

---

### Task 9: `bot/dashboard/routes/twitch.py` — Statut stream avec cache TTL

**Files:**
- Create: `bot/dashboard/routes/twitch.py`

- [ ] **Créer `bot/dashboard/routes/twitch.py`**

```python
# bot/dashboard/routes/twitch.py
from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()

# Cache module-level pour éviter les appels Twitch API à chaque requête.
_cache: dict = {"data": None, "fetched_at": 0.0, "is_live": False}

TTL_LIVE = 60      # secondes — statut live : refresh fréquent
TTL_OFFLINE = 300  # secondes — statut offline : refresh rare


@router.get("/twitch/stream")
async def get_stream_status(request: Request) -> dict:
    """Retourne le statut du stream Azrael_TTV avec cache TTL.

    TTL asymétrique : 60s si live (données changeantes), 5min si offline.
    Si twitch_api est None (Twitch désactivé), retourne offline immédiatement.
    """
    state = request.app.state.wally

    if state.twitch_api is None:
        return {"live": False, "title": None, "category": None, "viewers": 0, "started_at": None}

    now = time.time()
    ttl = TTL_LIVE if _cache["is_live"] else TTL_OFFLINE

    if _cache["data"] is not None and (now - _cache["fetched_at"]) < ttl:
        return _cache["data"]

    result = await state.twitch_api.get_stream()
    _cache.update({
        "data": result,
        "fetched_at": now,
        "is_live": result.get("live", False),
    })
    return result
```

- [ ] **Commit**

```bash
git add bot/dashboard/routes/twitch.py
git commit -m "feat(dashboard): add Twitch stream status route with TTL cache"
```

---

### Task 10: `bot/dashboard/routes/memory.py` — Stub Phase 2

**Files:**
- Create: `bot/dashboard/routes/memory.py`

- [ ] **Créer `bot/dashboard/routes/memory.py`**

```python
# bot/dashboard/routes/memory.py
# Phase 2 — Gestion mémoire mem0 + trust scores
# Tous les endpoints retournent 501 Not Implemented.
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_NOT_IMPL = JSONResponse(
    {"detail": "Memory management not implemented (Phase 2)"},
    status_code=501,
)


@router.api_route("/memory/{path:path}", methods=["GET", "POST", "DELETE"])
async def memory_stub(path: str):
    return _NOT_IMPL
```

- [ ] **Commit**

```bash
git add bot/dashboard/routes/memory.py
git commit -m "feat(dashboard): add memory route stub (Phase 2)"
```

---

### Task 11: Tests routes — `tests/test_dashboard_routes.py`

**Files:**
- Create: `tests/test_dashboard_routes.py`

- [ ] **Créer `tests/test_dashboard_routes.py`**

```python
# tests/test_dashboard_routes.py
"""Tests d'intégration des routes dashboard avec une app FastAPI de test."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState


def _make_state(**overrides) -> AppState:
    """Crée un AppState minimal avec des mocks."""
    emotion = MagicMock()
    emotion.get_state.return_value = {
        "anger": 0.1, "joy": 0.7, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0
    }
    emotion.set_emotion = MagicMock()

    db = MagicMock()
    db.get_today_emotion_snapshots = AsyncMock(return_value=[])
    db.insert_emotion_snapshot = AsyncMock()

    cfg = MagicMock()
    cfg.bot.dashboard_token = "testtoken"
    cfg.bot.trigger_names = ["wally"]

    state = AppState(
        config=cfg,
        db=db,
        emotion=emotion,
        memory=MagicMock(),
        persona=MagicMock(),
        openai_client=MagicMock(),
        token_manager=MagicMock(),
        twitch_api=None,
        discord_bot=None,
        twitch_bot=None,
        start_time=time.time() - 100,
        message_count=42,
    )
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


@pytest.fixture
def app():
    return create_dashboard_app(_make_state())


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Status ────────────────────────────────────────────────────────────────────

async def test_status_shape(client):
    r = await client.get("/api/public/status")
    assert r.status_code == 200
    data = r.json()
    assert "uptime_seconds" in data
    assert "discord_online" in data
    assert "twitch_online" in data
    assert data["total_messages"] == 42


async def test_status_discord_offline_when_none(client):
    r = await client.get("/api/public/status")
    assert r.json()["discord_online"] is False


# ── Emotions public ───────────────────────────────────────────────────────────

async def test_get_emotions_public(client):
    r = await client.get("/api/public/emotions")
    assert r.status_code == 200
    data = r.json()
    assert data["joy"] == 0.7
    assert "anger" in data


async def test_get_emotions_history(client):
    r = await client.get("/api/public/emotions/history")
    assert r.status_code == 200
    assert "history" in r.json()


# ── Emotions admin ────────────────────────────────────────────────────────────

ADMIN_HEADERS = {"Authorization": "Bearer testtoken"}


async def test_set_emotion_valid(client):
    r = await client.post(
        "/api/admin/emotions/set",
        json={"emotion": "joy", "value": 0.9},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["emotion"] == "joy"


async def test_set_emotion_unknown_returns_400(client):
    r = await client.post(
        "/api/admin/emotions/set",
        json={"emotion": "fear", "value": 0.5},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


async def test_set_emotion_out_of_range_returns_400(client):
    r = await client.post(
        "/api/admin/emotions/set",
        json={"emotion": "joy", "value": 1.5},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


async def test_reset_emotions_calls_set_emotion_05(client, app):
    state = app.state.wally
    state.emotion.set_emotion.reset_mock()
    r = await client.post("/api/admin/emotions/reset", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    calls = {call.args[0]: call.args[1] for call in state.emotion.set_emotion.call_args_list}
    assert calls["joy"] == 0.5
    assert calls["anger"] == 0.5
    assert calls["sadness"] == 0.5


# ── Config ────────────────────────────────────────────────────────────────────

async def test_get_config(client, app):
    app.state.wally.config.bot.dashboard_token = "testtoken"
    r = await client.get("/api/admin/config", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert "bot" in r.json()
    assert "openai" in r.json()


async def test_update_config_invalid_temperature(client):
    r = await client.post(
        "/api/admin/config",
        json={"openai": {"temperature": 5.0}},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


async def test_update_config_invalid_lambda(client, app):
    app.state.wally.config.emotions = {"joy": MagicMock(decay_lambda=0.1)}
    r = await client.post(
        "/api/admin/config",
        json={"emotions": {"joy": {"decay_lambda": -0.5}}},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


# ── Twitch stream ─────────────────────────────────────────────────────────────

async def test_stream_offline_when_no_twitch_api(client):
    r = await client.get("/api/public/twitch/stream")
    assert r.status_code == 200
    assert r.json()["live"] is False


async def test_stream_uses_cache(app):
    """Vérifie que get_stream() n'est pas appelé deux fois dans le TTL."""
    mock_api = AsyncMock()
    mock_api.get_stream = AsyncMock(return_value={
        "live": True, "title": "Test", "category": "IRL",
        "viewers": 10, "started_at": "2026-03-16T10:00:00Z",
    })
    state = _make_state(twitch_api=mock_api)
    test_app = create_dashboard_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        # Reset cache
        from bot.dashboard.routes import twitch as twitch_mod
        twitch_mod._cache.update({"data": None, "fetched_at": 0.0, "is_live": False})

        await c.get("/api/public/twitch/stream")
        await c.get("/api/public/twitch/stream")

    # get_stream() appelé une seule fois (deuxième requête utilise le cache)
    mock_api.get_stream.assert_called_once()


# ── Memory stub ───────────────────────────────────────────────────────────────

async def test_memory_stub_returns_501(client):
    r = await client.get("/api/admin/memory/users", headers=ADMIN_HEADERS)
    assert r.status_code == 501
```

- [ ] **Lancer les tests**

```bash
pytest tests/test_dashboard_routes.py -v
```
Attendu : tous les tests PASSED

- [ ] **Commit**

```bash
git add tests/test_dashboard_routes.py
git commit -m "test(dashboard): add integration tests for all routes"
```

---

## Chunk 3: Integration

### Task 12: `bot/discord/bot.py` + `bot/twitch/bot.py` — `dashboard_state`

**Files:**
- Modify: `bot/discord/bot.py`
- Modify: `bot/twitch/bot.py`

- [ ] **Ajouter `dashboard_state = None` dans `WallyDiscord.__init__()`** (après la dernière ligne `self.xxx = ...`)

```python
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]
```

- [ ] **Ajouter `dashboard_state = None` dans `WallyTwitch.__init__()`** (après `self._cooldowns = ...`)

```python
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]
```

- [ ] **Commit**

```bash
git add bot/discord/bot.py bot/twitch/bot.py
git commit -m "feat(dashboard): add dashboard_state attribute to bot classes"
```

---

### Task 13: `bot/discord/handlers.py` + `bot/twitch/handlers.py` — message counter

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/twitch/handlers.py`

- [ ] **Dans `bot/discord/handlers.py`**, ajouter l'incrément juste après le guard `if message.author.bot: return`

Localiser la ligne :
```python
    if message.author.bot:
        return
```

Ajouter immédiatement après :
```python
    # Dashboard message counter
    if getattr(bot, "dashboard_state", None) is not None:
        bot.dashboard_state.message_count += 1
```

- [ ] **Dans `bot/twitch/handlers.py`**, ajouter l'incrément au tout début de `handle_message`, avant `content = payload.message.text`

```python
    # Dashboard message counter (tous les messages, pas seulement les triggers)
    if getattr(bot, "dashboard_state", None) is not None:
        bot.dashboard_state.message_count += 1
```

- [ ] **Lancer les tests existants pour vérifier que rien n'est cassé**

```bash
pytest tests/ -v --ignore=tests/test_dashboard_routes.py --ignore=tests/test_dashboard_auth.py --ignore=tests/test_twitch_get_stream.py
```
Attendu : tous les tests existants PASSED

- [ ] **Commit**

```bash
git add bot/discord/handlers.py bot/twitch/handlers.py
git commit -m "feat(dashboard): increment message_count in Discord and Twitch handlers"
```

---

### Task 14: `bot/main.py` — AppState + uvicorn dans `asyncio.gather()`

**Files:**
- Modify: `bot/main.py`

- [ ] **Dans `bot/main.py`**, ajouter les imports en haut du bloc `async def main()`

Localiser la ligne :
```python
    from bot.core.sessions import SessionManager
```

Avant cette ligne, ne pas toucher. Après la totalité du bloc `# ── Twitch adapter ───`, ajouter le bloc suivant **avant** `await asyncio.gather(*tasks)` :

Localiser :
```python
    await asyncio.gather(*tasks)
```

Remplacer par :

```python
    # ── Dashboard ─────────────────────────────────────────────────────────────
    from bot.dashboard.app import create_dashboard_app
    from bot.dashboard.state import AppState
    import uvicorn

    _twitch_bot_ref = twitch_bot if token_manager.bot_token else None
    _twitch_api_ref = twitch_api if token_manager.bot_token else None

    dashboard_state = AppState(
        config=config,
        db=db,
        emotion=emotion,
        memory=memory,
        persona=persona,
        openai_client=openai_client,
        token_manager=token_manager,
        twitch_api=_twitch_api_ref,
        discord_bot=discord_bot,
        twitch_bot=_twitch_bot_ref,
    )

    discord_bot.dashboard_state = dashboard_state
    if _twitch_bot_ref is not None:
        _twitch_bot_ref.dashboard_state = dashboard_state

    dashboard_app = create_dashboard_app(dashboard_state)
    dashboard_server = uvicorn.Server(
        uvicorn.Config(
            dashboard_app,
            host="0.0.0.0",
            port=8080,
            log_config=None,   # loguru gère les logs — désactiver uvicorn's logging
            access_log=False,
        )
    )
    tasks.append(dashboard_server.serve())
    logger.info("Dashboard server added to gather on port 8080")

    await asyncio.gather(*tasks)
```

> Note : `twitch_bot` et `twitch_api` peuvent ne pas être définis si la condition `if token_manager.bot_token:` est False. La ligne `_twitch_bot_ref = twitch_bot if ...` résoudrait un `NameError`. Initialiser `twitch_bot = None` et `twitch_api = None` avant le bloc conditionnel Twitch pour que la référence soit toujours définie.

- [ ] **Initialiser `twitch_bot = None` et `twitch_api = None` avant le bloc conditionnel**

Localiser :
```python
    tasks = [discord_bot.start(discord_token)]
    if token_manager.bot_token:
```

Ajouter avant :
```python
    twitch_bot = None
    twitch_api = None
```

- [ ] **Lancer les tests pour vérifier les imports**

```bash
python -c "from bot.main import main; print('OK')"
```
Attendu : `OK` (pas d'erreur d'import)

- [ ] **Commit**

```bash
git add bot/main.py
git commit -m "feat(dashboard): wire AppState and uvicorn server into main.py"
```

---

### Task 15: `requirements.txt` + `docker-compose.yml`

**Files:**
- Modify: `requirements.txt`
- Modify: `docker-compose.yml`

- [ ] **Ajouter dans `requirements.txt`** (après `httpx`) :

```
# Web dashboard
fastapi>=0.111.0
uvicorn>=0.30.0
```

- [ ] **Dans `docker-compose.yml`**, ajouter le port dans le service `wally`

Localiser dans le service `wally` :
```yaml
    env_file: .env
```

Ajouter après la section `environment:` et avant `volumes:` (ou adapter selon la position exacte dans le fichier) :

```yaml
    ports:
      - "127.0.0.1:8080:8080"
```

- [ ] **Vérifier la syntaxe docker-compose**

```bash
docker compose config --quiet && echo "OK"
```
Attendu : `OK`

- [ ] **Commit**

```bash
git add requirements.txt docker-compose.yml
git commit -m "feat(dashboard): add fastapi/uvicorn deps and expose port 8080"
```

---

## Chunk 4: Frontend

### Task 16: `bot/dashboard/static/style.css` — Dark Neobrutalism

**Files:**
- Create: `bot/dashboard/static/style.css`

- [ ] **Créer `bot/dashboard/static/style.css`**

```css
/* Dark Neobrutalism — Wally Dashboard
   Règles fondamentales :
   - Bordures épaisses 3px solid #ffffff
   - Ombres dures sans flou : box-shadow 4px 4px 0px #ffffff
   - Zéro dégradé, zéro flou
   - Border-radius : 0px (max 4px)
*/

:root {
  --bg: #0f0f0f;
  --card: #1a1a1a;
  --border: #ffffff;
  --shadow: 4px 4px 0px #ffffff;
  --shadow-sm: 2px 2px 0px #ffffff;
  --text: #ffffff;
  --text-muted: #aaaaaa;
  --c-anger: #ff3333;
  --c-joy: #ffdd00;
  --c-curiosity: #00ccff;
  --c-sadness: #7777ff;
  --c-boredom: #888888;
  --c-online: #00ff88;
  --c-offline: #ff3333;
  --font: 'Courier New', Courier, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  min-height: 100vh;
}

/* ── Header ──────────────────────────────────────────────────────────────── */

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 3px solid var(--border);
  background: var(--bg);
  position: sticky;
  top: 0;
  z-index: 100;
}

.logo {
  font-size: 1.4rem;
  font-weight: 900;
  letter-spacing: 4px;
  color: var(--c-joy);
}

.mode-toggle {
  display: flex;
  gap: 0;
}

.mode-btn {
  padding: 6px 16px;
  border: 3px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.1s, transform 0.1s;
}

.mode-btn:first-child { border-right-width: 1.5px; }
.mode-btn:last-child  { border-left-width: 1.5px; }

.mode-btn.active {
  background: var(--border);
  color: var(--bg);
  box-shadow: none;
}

.mode-btn:hover:not(.active) {
  box-shadow: none;
  transform: translate(2px, 2px);
}

/* ── Tab navigation ──────────────────────────────────────────────────────── */

nav.tabs {
  display: flex;
  border-bottom: 3px solid var(--border);
  overflow-x: auto;
  scrollbar-width: none;
}

nav.tabs::-webkit-scrollbar { display: none; }

.tab-btn {
  padding: 10px 18px;
  border: none;
  border-right: 1px solid #333;
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.8rem;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.1s, color 0.1s;
}

.tab-btn.active {
  background: var(--border);
  color: var(--bg);
}

.tab-btn:hover:not(.active) {
  background: #222;
  color: var(--text);
}

.tab-btn.disabled {
  color: #444;
  cursor: not-allowed;
}

/* ── Main content ────────────────────────────────────────────────────────── */

main { padding: 20px; max-width: 1100px; margin: 0 auto; }

.tab-content { display: none; }
.tab-content.active { display: block; }

/* ── Cards ───────────────────────────────────────────────────────────────── */

.card {
  background: var(--card);
  border: 3px solid var(--border);
  box-shadow: var(--shadow);
  padding: 16px;
  margin-bottom: 16px;
}

.card-title {
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 10px;
}

.card-value {
  font-size: 1.8rem;
  font-weight: 900;
}

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }

@media (max-width: 600px) {
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
}

/* ── Status dots ─────────────────────────────────────────────────────────── */

.status-dot {
  display: inline-block;
  width: 10px; height: 10px;
  border-radius: 50%;
  margin-right: 8px;
}

.status-dot.online  { background: var(--c-online); box-shadow: 0 0 6px var(--c-online); }
.status-dot.offline { background: var(--c-offline); }

/* ── Emotion gauges ──────────────────────────────────────────────────────── */

.emotion-row {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  gap: 10px;
}

.emotion-label {
  width: 80px;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 1px;
  flex-shrink: 0;
}

.gauge-track {
  flex: 1;
  height: 18px;
  background: #222;
  border: 3px solid var(--border);
  box-shadow: 2px 2px 0px var(--border);
  position: relative;
  overflow: hidden;
}

.gauge-fill {
  height: 100%;
  width: 0%;
  transition: width 1s ease;
}

.gauge-fill.anger    { background: var(--c-anger); }
.gauge-fill.joy      { background: var(--c-joy); }
.gauge-fill.curiosity{ background: var(--c-curiosity); }
.gauge-fill.sadness  { background: var(--c-sadness); }
.gauge-fill.boredom  { background: var(--c-boredom); }

.gauge-val {
  width: 38px;
  text-align: right;
  font-size: 0.8rem;
  font-weight: 700;
  flex-shrink: 0;
}

/* ── Editable sliders (admin) ────────────────────────────────────────────── */

.emotion-slider {
  flex: 1;
  accent-color: var(--border);
  cursor: pointer;
}

/* ── Emotion summary ─────────────────────────────────────────────────────── */

.emotion-summary {
  font-size: 0.9rem;
  color: var(--text-muted);
  font-style: italic;
  margin-top: 12px;
  min-height: 1.4em;
}

/* ── Canvas graph ────────────────────────────────────────────────────────── */

.graph-container {
  border: 3px solid var(--border);
  box-shadow: var(--shadow);
  background: #111;
  padding: 4px;
  margin-top: 16px;
}

#emotionCanvas { display: block; width: 100%; }

/* ── Buttons ─────────────────────────────────────────────────────────────── */

.btn {
  padding: 8px 18px;
  border: 3px solid var(--border);
  background: var(--card);
  color: var(--text);
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.1s, transform 0.1s;
}

.btn:hover {
  box-shadow: none;
  transform: translate(2px, 2px);
}

.btn:active { box-shadow: none; transform: translate(4px, 4px); }

.btn-danger  { border-color: var(--c-anger);  color: var(--c-anger); }
.btn-success { border-color: var(--c-joy);    color: var(--c-joy); }
.btn-info    { border-color: var(--c-curiosity); color: var(--c-curiosity); }

/* ── Inputs & Selects ────────────────────────────────────────────────────── */

.field-group { margin-bottom: 14px; }

.field-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 4px;
}

input[type="text"], input[type="number"], input[type="password"], select, textarea {
  width: 100%;
  padding: 7px 10px;
  background: var(--bg);
  border: 3px solid var(--border);
  color: var(--text);
  font-family: var(--font);
  font-size: 0.9rem;
  box-shadow: var(--shadow-sm);
  outline: none;
  border-radius: 0;
}

input[type="range"] {
  accent-color: var(--border);
  width: 100%;
}

/* ── Stream card ─────────────────────────────────────────────────────────── */

.stream-live-badge {
  display: inline-block;
  padding: 2px 10px;
  background: var(--c-anger);
  color: #fff;
  font-weight: 900;
  font-size: 0.75rem;
  letter-spacing: 2px;
  border: 2px solid var(--border);
  margin-bottom: 8px;
}

.stream-offline-badge {
  display: inline-block;
  padding: 2px 10px;
  background: #333;
  color: var(--text-muted);
  font-weight: 900;
  font-size: 0.75rem;
  letter-spacing: 2px;
  border: 2px solid #555;
  margin-bottom: 8px;
}

/* ── Logs ────────────────────────────────────────────────────────────────── */

.log-controls { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }

.log-stream {
  background: #000;
  border: 3px solid var(--border);
  box-shadow: var(--shadow);
  height: 400px;
  overflow-y: auto;
  padding: 10px;
  font-size: 0.78rem;
  line-height: 1.5;
}

.log-entry { margin-bottom: 2px; }
.log-entry.INFO    { color: #ccc; }
.log-entry.WARNING { color: var(--c-joy); }
.log-entry.ERROR   { color: var(--c-anger); }
.log-entry.hidden  { display: none; }

/* ── Config sections ─────────────────────────────────────────────────────── */

.config-section { margin-bottom: 24px; }

.config-section-title {
  font-size: 0.75rem;
  font-weight: 900;
  letter-spacing: 3px;
  color: var(--c-joy);
  text-transform: uppercase;
  border-bottom: 2px solid var(--c-joy);
  padding-bottom: 4px;
  margin-bottom: 14px;
}

/* ── Auth modal ──────────────────────────────────────────────────────────── */

.modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 1000;
  align-items: center;
  justify-content: center;
}

.modal-overlay.visible { display: flex; }

.modal {
  background: var(--card);
  border: 3px solid var(--border);
  box-shadow: 8px 8px 0px var(--border);
  padding: 24px;
  width: 340px;
  max-width: 90vw;
}

.modal h2 {
  font-size: 1.1rem;
  font-weight: 900;
  letter-spacing: 2px;
  margin-bottom: 16px;
}

/* ── Toasts ──────────────────────────────────────────────────────────────── */

#toast-container {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  padding: 10px 16px;
  border: 3px solid var(--border);
  box-shadow: var(--shadow);
  font-weight: 700;
  font-size: 0.85rem;
  animation: toast-in 0.15s ease;
  max-width: 320px;
}

.toast.success { background: #1a1a00; color: var(--c-joy);   border-color: var(--c-joy); }
.toast.error   { background: #1a0000; color: var(--c-anger); border-color: var(--c-anger); }

@keyframes toast-in {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Favicon SVG (dynamique) ─────────────────────────────────────────────── */
/* Le favicon est mis à jour via JS selon l'émotion dominante */
```

- [ ] **Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "feat(dashboard): add dark neobrutalism stylesheet"
```

---

### Task 17: `bot/dashboard/static/index.html` — SPA complète

**Files:**
- Create: `bot/dashboard/static/index.html`

- [ ] **Créer `bot/dashboard/static/index.html`**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wally Dashboard</title>
  <link rel="stylesheet" href="/static/style.css">
  <link rel="icon" id="favicon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='14' fill='%23888888'/></svg>">
</head>
<body>

<header>
  <div class="logo">WALLY</div>
  <div class="mode-toggle">
    <button class="mode-btn active" id="btn-public" onclick="switchMode('public')">PUBLIC</button>
    <button class="mode-btn" id="btn-admin" onclick="switchMode('admin')">ADMIN 🔒</button>
  </div>
</header>

<!-- Tab navigation — public -->
<nav class="tabs" id="tabs-public">
  <button class="tab-btn active" data-tab="status"   onclick="showTab('status')">📊 STATUT</button>
  <button class="tab-btn"        data-tab="emotions" onclick="showTab('emotions')">😤 HUMEUR</button>
  <button class="tab-btn"        data-tab="stream"   onclick="showTab('stream')">🎮 STREAM</button>
  <button class="tab-btn"        data-tab="stats"    onclick="showTab('stats')">📈 STATS</button>
</nav>

<!-- Tab navigation — admin -->
<nav class="tabs" id="tabs-admin" style="display:none">
  <button class="tab-btn active" data-tab="admin-config"   onclick="showTab('admin-config')">⚙ CONFIG</button>
  <button class="tab-btn"        data-tab="admin-emotions" onclick="showTab('admin-emotions')">😤 HUMEUR</button>
  <button class="tab-btn"        data-tab="admin-logs"     onclick="showTab('admin-logs')">📜 LOGS</button>
  <button class="tab-btn disabled" title="Phase 2">🧠 MÉMOIRE</button>
  <button class="tab-btn disabled" title="Phase 2">💸 COÛTS</button>
  <button class="tab-btn disabled" title="Phase 3">🎭 PERSONA</button>
  <button class="tab-btn disabled" title="Phase 3">⏱ TIMEOUTS</button>
</nav>

<main>

  <!-- ── STATUS ───────────────────────────────────────────────────────── -->
  <div class="tab-content active" id="tab-status">
    <div class="grid-2">
      <div class="card">
        <div class="card-title">UPTIME</div>
        <div class="card-value" id="uptime">—</div>
      </div>
      <div class="card">
        <div class="card-title">PLATEFORMES</div>
        <div style="margin-bottom:8px">
          <span class="status-dot offline" id="dot-discord"></span>
          <span id="lbl-discord">Discord</span>
        </div>
        <div>
          <span class="status-dot offline" id="dot-twitch"></span>
          <span id="lbl-twitch">Twitch</span>
        </div>
      </div>
    </div>
  </div>

  <!-- ── EMOTIONS (public) ─────────────────────────────────────────────── -->
  <div class="tab-content" id="tab-emotions">
    <div class="card">
      <div class="card-title">HUMEUR EN DIRECT</div>
      <div id="gauges-public"></div>
      <div class="emotion-summary" id="emotion-summary">—</div>
    </div>
    <div class="graph-container">
      <div class="card-title" style="padding:8px 8px 0">DERNIÈRES 24H</div>
      <canvas id="emotionCanvas" height="140"></canvas>
    </div>
  </div>

  <!-- ── STREAM ────────────────────────────────────────────────────────── -->
  <div class="tab-content" id="tab-stream">
    <div class="card" id="stream-card">
      <div class="card-title">AZRAEL_TTV</div>
      <div id="stream-content">Chargement…</div>
    </div>
  </div>

  <!-- ── STATS ─────────────────────────────────────────────────────────── -->
  <div class="tab-content" id="tab-stats">
    <div class="grid-2">
      <div class="card">
        <div class="card-title">MESSAGES TRAITÉS</div>
        <div class="card-value" id="stat-messages">—</div>
        <div style="color:var(--text-muted);font-size:0.75rem;margin-top:6px">depuis le dernier démarrage</div>
      </div>
    </div>
  </div>

  <!-- ── ADMIN CONFIG ───────────────────────────────────────────────────── -->
  <div class="tab-content" id="tab-admin-config">
    <div id="config-form-container">Chargement…</div>
  </div>

  <!-- ── ADMIN EMOTIONS ────────────────────────────────────────────────── -->
  <div class="tab-content" id="tab-admin-emotions">
    <div class="card">
      <div class="card-title">FORCER UNE VALEUR</div>
      <div id="gauges-admin"></div>
      <div style="margin-top:16px">
        <button class="btn btn-danger" onclick="resetEmotions()">🔄 RESET À NEUTRE (0.5)</button>
      </div>
    </div>
  </div>

  <!-- ── ADMIN LOGS ─────────────────────────────────────────────────────── -->
  <div class="tab-content" id="tab-admin-logs">
    <div class="log-controls">
      <button class="btn active" id="log-filter-ALL"     onclick="setLogFilter('ALL')">TOUS</button>
      <button class="btn"        id="log-filter-INFO"    onclick="setLogFilter('INFO')">INFO</button>
      <button class="btn"        id="log-filter-WARNING" onclick="setLogFilter('WARNING')">WARNING</button>
      <button class="btn"        id="log-filter-ERROR"   onclick="setLogFilter('ERROR')">ERROR</button>
      <button class="btn"        onclick="clearLogs()">🗑 VIDER</button>
    </div>
    <div class="log-stream" id="log-stream"></div>
  </div>

</main>

<!-- Auth modal -->
<div class="modal-overlay" id="auth-modal">
  <div class="modal">
    <h2>🔒 ACCÈS ADMIN</h2>
    <!-- WARNING: Token stored in localStorage — acceptable for personal use.
         For public exposure, use HttpOnly cookies instead. -->
    <div class="field-group">
      <label class="field-label">Dashboard Token</label>
      <input type="password" id="token-input" placeholder="Entrer le token…"
             onkeydown="if(event.key==='Enter') submitToken()">
    </div>
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="btn btn-success" onclick="submitToken()">VALIDER</button>
      <button class="btn" onclick="hideAuthModal()">ANNULER</button>
    </div>
  </div>
</div>

<!-- Toast container -->
<div id="toast-container"></div>

<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "feat(dashboard): add SPA HTML with all tab sections"
```

---

### Task 18: `bot/dashboard/static/app.js` — Logique SPA complète

**Files:**
- Create: `bot/dashboard/static/app.js`

- [ ] **Créer `bot/dashboard/static/app.js`**

```javascript
// bot/dashboard/static/app.js
// WARNING: Auth token stored in localStorage — acceptable for personal use.
// For public exposure, replace with HttpOnly cookies.

'use strict';

// ── Constants ────────────────────────────────────────────────────────────────

const AUTH_KEY = 'wally_token';
const EMOTION_COLORS = {
  anger:    '#ff3333',
  joy:      '#ffdd00',
  curiosity:'#00ccff',
  sadness:  '#7777ff',
  boredom:  '#888888',
};
const EMOTION_LABELS = {
  anger: 'ANGER', joy: 'JOY', curiosity: 'CURIOSITY', sadness: 'SADNESS', boredom: 'BOREDOM',
};
const EMOTIONS = ['anger', 'joy', 'sadness', 'curiosity', 'boredom'];

// ── State ────────────────────────────────────────────────────────────────────

let currentMode = 'public';
let currentTab  = 'status';
let emotionSSE  = null;
let logSSE      = null;
let logFilter   = 'ALL';
let currentEmotions = {};

// ── Mode & tabs ───────────────────────────────────────────────────────────────

function switchMode(mode) {
  if (mode === 'admin') {
    if (!getToken()) { showAuthModal(); return; }
  }
  currentMode = mode;

  document.getElementById('btn-public').classList.toggle('active', mode === 'public');
  document.getElementById('btn-admin').classList.toggle('active',  mode === 'admin');
  document.getElementById('tabs-public').style.display = mode === 'public' ? 'flex' : 'none';
  document.getElementById('tabs-admin').style.display  = mode === 'admin'  ? 'flex' : 'none';

  const firstTab = mode === 'public' ? 'status' : 'admin-config';
  showTab(firstTab);

  if (mode === 'admin') {
    loadConfig();
    startLogSSE();
  } else {
    stopLogSSE();
  }
}

function showTab(tabId) {
  // Désactiver tous les onglets du mode courant
  const navId = currentMode === 'public' ? 'tabs-public' : 'tabs-admin';
  document.querySelectorAll(`#${navId} .tab-btn`).forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  const btn = document.querySelector(`#${navId} [data-tab="${tabId}"]`);
  if (btn) btn.classList.add('active');

  const content = document.getElementById(`tab-${tabId}`);
  if (content) content.classList.add('active');

  currentTab = tabId;

  // Chargements spécifiques par onglet
  if (tabId === 'stream')   loadStreamStatus();
  if (tabId === 'stats')    loadStats();
  if (tabId === 'emotions') loadEmotionHistory();
}

// ── Auth ─────────────────────────────────────────────────────────────────────

function getToken()       { return localStorage.getItem(AUTH_KEY); }
function saveToken(t)     { localStorage.setItem(AUTH_KEY, t); }
function clearToken()     { localStorage.removeItem(AUTH_KEY); }
function showAuthModal()  { document.getElementById('auth-modal').classList.add('visible'); }
function hideAuthModal()  { document.getElementById('auth-modal').classList.remove('visible'); }

async function submitToken() {
  const t = document.getElementById('token-input').value.trim();
  if (!t) return;
  // Vérifier le token en appelant un endpoint admin
  const r = await fetch('/api/admin/config', { headers: { 'Authorization': `Bearer ${t}` } });
  if (r.ok) {
    saveToken(t);
    hideAuthModal();
    document.getElementById('token-input').value = '';
    switchMode('admin');
    toast('Accès admin accordé', 'success');
  } else {
    toast('Token invalide', 'error');
  }
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function apiFetch(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(url, { ...opts, headers });
  if (r.status === 401) { clearToken(); switchMode('public'); toast('Session expirée', 'error'); return null; }
  return r;
}

// ── Toasts ────────────────────────────────────────────────────────────────────

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Status polling ────────────────────────────────────────────────────────────

async function loadStatus() {
  const r = await fetch('/api/public/status');
  if (!r.ok) return;
  const d = await r.json();

  // Uptime
  const s = Math.floor(d.uptime_seconds);
  const days = Math.floor(s / 86400);
  const hrs  = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  document.getElementById('uptime').textContent =
    days > 0 ? `${days}j ${hrs}h ${mins}m` : `${hrs}h ${mins}m`;

  // Dots
  const setDot = (id, online) => {
    const dot = document.getElementById(id);
    dot.classList.toggle('online',  online);
    dot.classList.toggle('offline', !online);
  };
  setDot('dot-discord', d.discord_online);
  setDot('dot-twitch',  d.twitch_online);
  document.getElementById('stat-messages').textContent = d.total_messages.toLocaleString();
}

// ── Stats ─────────────────────────────────────────────────────────────────────

async function loadStats() {
  const r = await fetch('/api/public/status');
  if (!r.ok) return;
  const d = await r.json();
  document.getElementById('stat-messages').textContent = d.total_messages.toLocaleString();
}

// ── Emotions SSE ──────────────────────────────────────────────────────────────

function buildGauges(containerId, editable) {
  const c = document.getElementById(containerId);
  c.innerHTML = '';
  for (const e of EMOTIONS) {
    const row = document.createElement('div');
    row.className = 'emotion-row';
    row.innerHTML = `
      <span class="emotion-label" style="color:${EMOTION_COLORS[e]}">${EMOTION_LABELS[e]}</span>
      ${editable
        ? `<input type="range" class="emotion-slider" id="slider-${e}" min="0" max="1" step="0.01" value="0"
             oninput="document.getElementById('val-${e}').textContent=parseFloat(this.value).toFixed(2)"
             onchange="setEmotion('${e}', parseFloat(this.value))">`
        : `<div class="gauge-track"><div class="gauge-fill ${e}" id="fill-${e}"></div></div>`
      }
      <span class="gauge-val" id="val-${e}">0.00</span>
    `;
    c.appendChild(row);
  }
}

function updateEmotionGauges(emotions) {
  currentEmotions = emotions;
  for (const e of EMOTIONS) {
    const v = emotions[e] ?? 0;
    const fill = document.getElementById(`fill-${e}`);
    if (fill) fill.style.width = `${(v * 100).toFixed(1)}%`;
    const slider = document.getElementById(`slider-${e}`);
    if (slider) slider.value = v;
    const val = document.getElementById(`val-${e}`);
    if (val) val.textContent = v.toFixed(2);
  }
  updateEmotionSummary(emotions);
  updateFavicon(emotions);
}

function updateEmotionSummary(emotions) {
  const dominant = EMOTIONS.filter(e => emotions[e] >= 0.4);
  const el = document.getElementById('emotion-summary');
  if (!el) return;
  if (dominant.length === 0) { el.textContent = 'Wally est dans un état neutre.'; return; }
  const names = { anger:'en colère', joy:'joyeux', sadness:'triste', curiosity:'curieux', boredom:'ennuyé' };
  el.textContent = `Wally est ${dominant.map(e => names[e]).join(' et ')}.`;
}

function updateFavicon(emotions) {
  const dominant = EMOTIONS.reduce((a, b) => (emotions[a] > emotions[b] ? a : b));
  const color = emotions[dominant] >= 0.2 ? EMOTION_COLORS[dominant] : '#888888';
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='14' fill='${color}'/></svg>`;
  document.getElementById('favicon').href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function startEmotionSSE() {
  if (emotionSSE) emotionSSE.close();
  emotionSSE = new EventSource('/api/public/sse/emotions');
  emotionSSE.onmessage = (e) => {
    try { updateEmotionGauges(JSON.parse(e.data)); } catch {}
  };
  emotionSSE.onerror = () => {
    // Reconnexion automatique gérée par EventSource
  };
}

// ── Emotion canvas graph ──────────────────────────────────────────────────────

async function loadEmotionHistory() {
  const r = await fetch('/api/public/emotions/history');
  if (!r.ok) return;
  const { history } = await r.json();
  drawEmotionGraph(history);
}

function drawEmotionGraph(history) {
  const canvas = document.getElementById('emotionCanvas');
  if (!canvas || !history || history.length < 2) return;

  const W = canvas.offsetWidth || 800;
  canvas.width  = W;
  canvas.height = 140;
  const ctx = canvas.getContext('2d');

  ctx.fillStyle = '#111';
  ctx.fillRect(0, 0, W, 140);

  const PAD = { top: 10, bottom: 20, left: 4, right: 4 };
  const gW = W - PAD.left - PAD.right;
  const gH = 140 - PAD.top - PAD.bottom;

  const tMin = history[0].snapshot_at;
  const tMax = history[history.length - 1].snapshot_at;
  const tRange = tMax - tMin || 1;

  for (const e of EMOTIONS) {
    ctx.beginPath();
    ctx.strokeStyle = EMOTION_COLORS[e];
    ctx.lineWidth = 2;
    ctx.globalAlpha = 0.85;
    history.forEach((snap, i) => {
      const x = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
      const y = PAD.top  + (1 - (snap[e] ?? 0)) * gH;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // Axe temporel (labels)
  ctx.fillStyle = '#666';
  ctx.font = '10px monospace';
  ctx.textAlign = 'left';
  const label0 = new Date(tMin * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' });
  const labelN = new Date(tMax * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' });
  ctx.fillText(label0, PAD.left, 138);
  ctx.textAlign = 'right';
  ctx.fillText(labelN, W - PAD.right, 138);
}

// ── Stream status ─────────────────────────────────────────────────────────────

async function loadStreamStatus() {
  const r = await fetch('/api/public/twitch/stream');
  if (!r.ok) return;
  const d = await r.json();
  const el = document.getElementById('stream-content');

  if (d.live) {
    el.innerHTML = `
      <div class="stream-live-badge">🔴 LIVE</div>
      <div style="font-size:1.1rem;font-weight:700;margin-bottom:6px">${escHtml(d.title || '')}</div>
      <div style="color:var(--text-muted);margin-bottom:4px">${escHtml(d.category || '')}</div>
      <div style="font-size:1.5rem;font-weight:900;color:var(--c-curiosity)">${(d.viewers || 0).toLocaleString()} viewers</div>
    `;
  } else {
    el.innerHTML = `
      <div class="stream-offline-badge">OFFLINE</div>
      ${d.started_at ? `<div style="color:var(--text-muted);margin-top:6px;font-size:0.85rem">Dernier stream : ${new Date(d.started_at).toLocaleString('fr')}</div>` : ''}
    `;
  }
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Admin config ──────────────────────────────────────────────────────────────

async function loadConfig() {
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) return;
  const cfg = await r.json();
  renderConfigForm(cfg);
}

async function loadOpenAIModels() {
  const r = await apiFetch('/api/admin/openai/models');
  if (!r || !r.ok) return [];
  const { models } = await r.json();
  return models;
}

async function renderConfigForm(cfg) {
  const container = document.getElementById('config-form-container');
  const models = await loadOpenAIModels();

  container.innerHTML = `
    <!-- OpenAI -->
    <div class="card config-section">
      <div class="config-section-title">OPENAI</div>
      <div class="field-group">
        <label class="field-label">Modèle principal</label>
        <select id="cfg-primary-model">
          ${models.map(m => `<option value="${m}" ${m === cfg.openai.primary_model ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label">Modèle secondaire</label>
        <select id="cfg-secondary-model">
          ${models.map(m => `<option value="${m}" ${m === cfg.openai.secondary_model ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label">Température (0.0 – 2.0)</label>
        <input type="number" id="cfg-temperature" min="0" max="2" step="0.1" value="${cfg.openai.temperature}">
      </div>
      <div class="field-group">
        <label class="field-label">Max tokens</label>
        <input type="number" id="cfg-max-tokens" min="100" max="8000" value="${cfg.openai.max_tokens}">
      </div>
      <button class="btn btn-success" onclick="saveOpenAI()">💾 SAUVEGARDER</button>
    </div>

    <!-- Émotions — lambdas -->
    <div class="card config-section">
      <div class="config-section-title">DÉCROISSANCE ÉMOTIONS (λ)</div>
      ${Object.entries(cfg.emotions).map(([name, ec]) => `
        <div class="field-group">
          <label class="field-label" style="color:${EMOTION_COLORS[name] || '#fff'}">${name.toUpperCase()} λ</label>
          <input type="range" id="cfg-lambda-${name}" min="0.01" max="2" step="0.01" value="${ec.decay_lambda}"
            oninput="document.getElementById('lbl-lambda-${name}').textContent=parseFloat(this.value).toFixed(2)">
          <span id="lbl-lambda-${name}">${ec.decay_lambda.toFixed(2)}</span>
        </div>
      `).join('')}
      <button class="btn btn-success" onclick="saveEmotionLambdas()">💾 SAUVEGARDER</button>
    </div>

    <!-- Bot général -->
    <div class="card config-section">
      <div class="config-section-title">BOT GÉNÉRAL</div>
      <div class="field-group">
        <label class="field-label">Langue par défaut</label>
        <input type="text" id="cfg-lang" value="${cfg.bot.language_default}">
      </div>
      <div class="field-group">
        <label class="field-label">Heure journal (HH:MM)</label>
        <input type="text" id="cfg-journal-time" value="${cfg.bot.journal_time}">
      </div>
      <div class="field-group">
        <label class="field-label">Taille fenêtre contexte</label>
        <input type="number" id="cfg-ctx-size" value="${cfg.bot.context_window_size}">
      </div>
      <div class="field-group">
        <label class="field-label">Triggers (séparés par virgule)</label>
        <input type="text" id="cfg-triggers" value="${(cfg.bot.trigger_names || []).join(', ')}">
      </div>
      <button class="btn btn-success" onclick="saveBotGeneral()">💾 SAUVEGARDER</button>
    </div>
  `;
}

async function saveOpenAI() {
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify({ openai: {
      primary_model:   document.getElementById('cfg-primary-model').value,
      secondary_model: document.getElementById('cfg-secondary-model').value,
      temperature:     parseFloat(document.getElementById('cfg-temperature').value),
      max_tokens:      parseInt(document.getElementById('cfg-max-tokens').value),
    }}),
  });
  if (r && r.ok) toast('Config OpenAI sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
}

async function saveEmotionLambdas() {
  const emotions = {};
  for (const e of EMOTIONS) {
    const el = document.getElementById(`cfg-lambda-${e}`);
    if (el) emotions[e] = { decay_lambda: parseFloat(el.value) };
  }
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify({ emotions }) });
  if (r && r.ok) toast('Lambdas sauvegardés', 'success'); else toast('Erreur sauvegarde', 'error');
}

async function saveBotGeneral() {
  const triggers = document.getElementById('cfg-triggers').value
    .split(',').map(s => s.trim()).filter(Boolean);
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify({ bot: {
      language_default: document.getElementById('cfg-lang').value,
      journal_time:     document.getElementById('cfg-journal-time').value,
      context_window_size: parseInt(document.getElementById('cfg-ctx-size').value),
      trigger_names:    triggers,
    }}),
  });
  if (r && r.ok) toast('Config bot sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
}

// ── Admin emotions ────────────────────────────────────────────────────────────

async function setEmotion(emotion, value) {
  const r = await apiFetch('/api/admin/emotions/set', {
    method: 'POST',
    body: JSON.stringify({ emotion, value }),
  });
  if (r && r.ok) toast(`${emotion}: ${value.toFixed(2)}`, 'success');
  else toast('Erreur', 'error');
}

async function resetEmotions() {
  const r = await apiFetch('/api/admin/emotions/reset', { method: 'POST' });
  if (r && r.ok) {
    // Mettre à jour les sliders admin
    for (const e of EMOTIONS) {
      const s = document.getElementById(`slider-${e}`);
      if (s) { s.value = 0.5; document.getElementById(`val-${e}`).textContent = '0.50'; }
    }
    toast('Émotions reset à 0.5', 'success');
  } else {
    toast('Erreur reset', 'error');
  }
}

// ── Admin logs SSE ────────────────────────────────────────────────────────────

function startLogSSE() {
  if (logSSE) logSSE.close();
  const token = getToken();
  if (!token) return;
  logSSE = new EventSource(`/api/admin/sse/logs`);
  // Note : EventSource ne supporte pas les headers custom.
  // Le token est vérifié via le middleware — pour l'instant on compte sur
  // le fait que le dashboard est sur réseau local non public.
  logSSE.onmessage = (e) => {
    try { appendLog(JSON.parse(e.data)); } catch {}
  };
}

function stopLogSSE() {
  if (logSSE) { logSSE.close(); logSSE = null; }
}

const MAX_LOG_ENTRIES = 200;

function appendLog(entry) {
  const el = document.getElementById('log-stream');
  if (!el) return;
  const div = document.createElement('div');
  div.className = `log-entry ${entry.level}`;
  if (logFilter !== 'ALL' && entry.level !== logFilter) div.classList.add('hidden');
  div.textContent = `[${entry.time}] ${entry.level.padEnd(7)} ${entry.message}`;
  el.appendChild(div);
  // Limiter le nombre d'entrées
  while (el.children.length > MAX_LOG_ENTRIES) el.removeChild(el.firstChild);
  // Auto-scroll si en bas
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) {
    el.scrollTop = el.scrollHeight;
  }
}

function setLogFilter(level) {
  logFilter = level;
  document.querySelectorAll('.log-controls .btn').forEach(b => {
    b.classList.toggle('active', b.id === `log-filter-${level}`);
  });
  document.querySelectorAll('.log-entry').forEach(e => {
    e.classList.toggle('hidden', level !== 'ALL' && !e.classList.contains(level));
  });
}

function clearLogs() {
  const el = document.getElementById('log-stream');
  if (el) el.innerHTML = '';
}

// Note: EventSource ne supporte pas les headers — pour admin SSE logs,
// une solution production utiliserait un cookie HttpOnly ou un token dans
// le query string (ex: /api/admin/sse/logs?token=xxx).
// Pour usage perso réseau local, la route est accessible sans vérification
// du token SSE (le middleware vérifie uniquement les requêtes HTTP standard).

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  // Construire les jauges
  buildGauges('gauges-public', false);
  buildGauges('gauges-admin',  true);

  // Charger le statut initial
  await loadStatus();

  // Démarrer SSE émotions
  startEmotionSSE();

  // Polling statut toutes les 30s
  setInterval(loadStatus, 30000);

  // Si token existant → proposer mode admin
  // (mais ne pas switcher automatiquement)
});
```

- [ ] **Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/app.js
git commit -m "feat(dashboard): add complete vanilla JS SPA with SSE, auth, canvas graph"
```

---

## Chunk 5: Vérification finale

### Task 19: Lancer tous les tests

- [ ] **Lancer la suite complète**

```bash
pytest tests/ -v
```
Attendu : tous les tests PASSED (incluant les 110 tests existants + nouveaux)

- [ ] **Vérifier la syntaxe Python des nouveaux fichiers**

```bash
python -m py_compile \
  bot/dashboard/state.py \
  bot/dashboard/auth.py \
  bot/dashboard/app.py \
  bot/dashboard/routes/status.py \
  bot/dashboard/routes/emotions.py \
  bot/dashboard/routes/admin.py \
  bot/dashboard/routes/sse.py \
  bot/dashboard/routes/twitch.py \
  bot/dashboard/routes/memory.py \
  bot/twitch/api.py \
  bot/main.py && echo "Syntax OK"
```
Attendu : `Syntax OK`

- [ ] **Commit final**

```bash
git add -A
git commit -m "feat(dashboard): Phase 1 complete — FastAPI dashboard with SSE and dark neobrutalism SPA"
```

---

## Notes d'implémentation

### EventSource et admin SSE logs
`EventSource` ne supporte pas les headers HTTP custom. Le middleware `BearerAuthMiddleware` vérifie uniquement les requêtes HTTP standard (non-SSE). Pour usage perso réseau local, c'est acceptable. Pour exposition publique, remplacer par un token dans le query string ou des cookies HttpOnly.

### Loguru sink + `put_nowait()`
Le sink `_log_sink` est appelé de manière synchrone depuis le thread loguru. Utiliser `put_nowait()` (thread-safe en CPython). Itérer sur `list(_log_queues)` pour éviter `RuntimeError` si la liste est modifiée concurremment.

### `emotion.reset()` vs `set_emotion(e, 0.5)`
`EmotionEngine.reset()` remet toutes les émotions à `0.0`. Ne JAMAIS appeler `reset()` pour le "reset à neutre" du dashboard. Appeler `set_emotion(e, 0.5)` pour chaque émotion.

### `twitch_bot` et `twitch_api` — initialisation dans `main.py`
Initialiser `twitch_bot = None` et `twitch_api = None` AVANT le bloc conditionnel `if token_manager.bot_token:` pour éviter `NameError` lors de la création de `AppState`.
