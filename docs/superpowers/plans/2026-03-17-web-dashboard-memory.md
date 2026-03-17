# Dashboard Memory Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter l'onglet Mémoire admin au dashboard — liste users mem0, affichage/suppression souvenirs, recherche globale.

**Architecture:** Nouvelle table SQLite `memory_users` alimentée par `MemoryService.add()`. Routes FastAPI accèdent à `state.memory._mem0` directement (pour conserver les IDs individuels). Frontend vanilla JS avec layout split gauche/droite.

**Tech Stack:** Python/FastAPI, aiosqlite, mem0, vanilla JS, pytest + httpx (tests)

---

## Chunk 1: Backend

### Task 1: database.py — table memory_users + méthodes

**Files:**
- Modify: `bot/db/database.py` (constante `SCHEMA` + 2 méthodes)
- Create: `tests/test_dashboard_memory_db.py`

#### Contexte

`database.py` contient une constante `SCHEMA` (module-level string) exécutée au démarrage via `conn.executescript(SCHEMA)`. L'attribut connexion est `self._conn` (pas `self._db`). Il existe déjà une méthode publique `execute(query, params)` qui fait commit.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_dashboard_memory_db.py` :

```python
import pytest
import time as time_module

from bot.db.database import Database


@pytest.mark.asyncio
async def test_upsert_memory_user_creates_entry():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:123", "discord")
    users = await db.list_memory_users()
    assert len(users) == 1
    assert users[0]["user_id"] == "discord:123"
    assert users[0]["platform"] == "discord"
    assert users[0]["last_updated"] > 0
    await db.close()


@pytest.mark.asyncio
async def test_upsert_memory_user_updates_last_updated():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:123", "discord")
    t1 = (await db.list_memory_users())[0]["last_updated"]
    # Forcer un timestamp légèrement différent
    import asyncio
    await asyncio.sleep(0.01)
    await db.upsert_memory_user("discord:123", "discord")
    t2 = (await db.list_memory_users())[0]["last_updated"]
    assert t2 >= t1
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_no_filter():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord")
    await db.upsert_memory_user("twitch:bob", "twitch")
    users = await db.list_memory_users()
    assert len(users) == 2
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_with_filter():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord")
    await db.upsert_memory_user("twitch:bob", "twitch")
    users = await db.list_memory_users(q="discord")
    assert len(users) == 1
    assert users[0]["user_id"] == "discord:alice"
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_empty():
    db = await Database.create(":memory:")
    users = await db.list_memory_users()
    assert users == []
    await db.close()
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_dashboard_memory_db.py -v
```
Attendu : `FAILED` — `Database has no attribute 'upsert_memory_user'`

- [ ] **Step 3: Ajouter le DDL dans `SCHEMA`**

Dans `bot/db/database.py`, ajouter AVANT la ligne `CREATE INDEX IF NOT EXISTS idx_emotion_history_ts...` :

```sql
CREATE TABLE IF NOT EXISTS memory_users (
    user_id      TEXT PRIMARY KEY,
    platform     TEXT NOT NULL,
    last_updated REAL NOT NULL
);

```

Le résultat final du bloc SCHEMA doit se terminer par :
```
...
CREATE INDEX IF NOT EXISTS idx_emotion_history_ts ON emotion_history(snapshot_at);
"""
```

- [ ] **Step 4: Ajouter les méthodes dans la classe `Database`**

Ajouter à la fin de la classe (après `cleanup_old_emotion_history`) :

```python
# ── Memory users tracking ─────────────────────────────────────────────────

async def upsert_memory_user(self, user_id: str, platform: str) -> None:
    await self._conn.execute(
        "INSERT INTO memory_users(user_id, platform, last_updated) VALUES(?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET last_updated=excluded.last_updated",
        (user_id, platform, time.time()),
    )
    await self._conn.commit()

async def list_memory_users(self, q: str | None = None) -> list[dict]:
    sql = "SELECT user_id, platform, last_updated FROM memory_users"
    params: tuple = ()
    if q:
        sql += " WHERE user_id LIKE ?"
        params = (f"%{q}%",)
    sql += " ORDER BY last_updated DESC"
    async with self._conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [{"user_id": r[0], "platform": r[1], "last_updated": r[2]} for r in rows]
```

Note: `time` est déjà importé en haut du fichier (`import time`).

- [ ] **Step 5: Vérifier que les tests passent**

```bash
pytest tests/test_dashboard_memory_db.py -v
```
Attendu : 5 tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add bot/db/database.py tests/test_dashboard_memory_db.py
git commit -m "feat(memory): add memory_users table and db methods"
```

---

### Task 2: MemoryService.set_db() + wiring main.py

**Files:**
- Modify: `bot/core/memory.py`
- Modify: `bot/main.py` (1 ligne)
- Create: `tests/test_memory_set_db.py`

#### Contexte

`MemoryService` a déjà le pattern `set_openai_client()` (attribut `self._openai` initialisé à `None` dans `__init__`, méthode setter). Reproduire exactement ce pattern pour `_db`.

Dans `add()`, après `await asyncio.to_thread(self._mem0.add, full_content, user_id=uid)`, ajouter l'appel `upsert_memory_user`. Dans `main.py`, `memory = MemoryService(config)` est à la ligne 73 — ajouter `memory.set_db(db)` juste après.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_memory_set_db.py` :

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.memory import MemoryService


def _make_config():
    cfg = MagicMock()
    cfg.bot.context_window_size = 10
    cfg.bot.prelude_window_size = 5
    cfg.bot.context_token_threshold = 2000
    cfg.openai.secondary_model = "gpt-4o-mini"
    return cfg


def test_set_db_stores_reference():
    svc = MemoryService(_make_config())
    db = AsyncMock()
    svc.set_db(db)
    assert svc._db is db


def test_db_is_none_by_default():
    svc = MemoryService(_make_config())
    assert svc._db is None


@pytest.mark.asyncio
async def test_add_calls_upsert_when_db_set():
    svc = MemoryService(_make_config())
    db = AsyncMock()
    svc.set_db(db)

    mock_mem0 = MagicMock()
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    with patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
        await svc.add("discord", "123", "test content")

    db.upsert_memory_user.assert_called_once_with("discord:123", "discord")


@pytest.mark.asyncio
async def test_add_skips_upsert_when_no_db():
    svc = MemoryService(_make_config())
    # pas de set_db() appelé

    mock_mem0 = MagicMock()
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    with patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
        # ne doit pas lever d'exception
        await svc.add("discord", "123", "content")
    # test implicite : pas de crash


@pytest.mark.asyncio
async def test_add_skips_upsert_when_mem0_none():
    svc = MemoryService(_make_config())
    db = AsyncMock()
    svc.set_db(db)
    svc._mem0 = None
    svc._mem0_init_attempted = True

    await svc.add("discord", "123", "content")
    db.upsert_memory_user.assert_not_called()
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_memory_set_db.py -v
```
Attendu : `FAILED` — `MemoryService has no attribute 'set_db'`

- [ ] **Step 3: Modifier `bot/core/memory.py`**

Dans `__init__` de `MemoryService`, après `self._openai: Optional["OpenAIClient"] = None` (ligne ~54), ajouter :

```python
self._db: Optional[object] = None
```

Après la méthode `set_openai_client` (ligne ~58-59), ajouter :

```python
def set_db(self, db) -> None:
    self._db = db
```

Dans la méthode `add()`, après `await asyncio.to_thread(self._mem0.add, full_content, user_id=uid)` et avant `self._fire(self._maybe_consolidate(...))`, ajouter :

```python
if self._db is not None:
    await self._db.upsert_memory_user(uid, platform)
```

Le bloc `add()` doit ressembler à ceci après modification :

```python
async def add(self, platform: str, user_id: str, content: str,
              emotion_context: str = "") -> None:
    self._init_mem0()
    if self._mem0 is None:
        return
    try:
        uid = self._user_id(platform, user_id)
        full_content = f"[{emotion_context}] {content}" if emotion_context else content
        await asyncio.to_thread(self._mem0.add, full_content, user_id=uid)
        if self._db is not None:
            await self._db.upsert_memory_user(uid, platform)
        # Vérification consolidation en arrière-plan (ne bloque pas la réponse)
        self._fire(self._maybe_consolidate(platform, user_id))
    except Exception as exc:
        logger.warning("mem0 add failed: {e}", e=exc)
```

- [ ] **Step 4: Modifier `bot/main.py`**

Après la ligne `memory.set_openai_client(openai_client)` (ligne ~75), ajouter :

```python
memory.set_db(db)
```

- [ ] **Step 5: Vérifier que les tests passent**

```bash
pytest tests/test_memory_set_db.py -v
```
Attendu : 5 tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add bot/core/memory.py bot/main.py tests/test_memory_set_db.py
git commit -m "feat(memory): add set_db() to MemoryService, wire upsert in add()"
```

---

### Task 3: Routes memory.py — réécriture complète

**Files:**
- Modify: `bot/dashboard/routes/memory.py` (réécriture complète)
- Create: `tests/test_dashboard_memory_routes.py`

#### Contexte

Le fichier actuel est un stub 501. Le router s'appelle `router` — **ne pas le renommer**, `app.py` l'importe déjà comme `memory.router` sous prefix `/api/admin`.

Les routes accèdent à `state.memory._mem0` directement (les méthodes publiques `get_all()` et `search()` retournent des strings, pas des listes avec IDs). Appeler `state.memory._init_mem0()` avant toute opération mem0 (méthode synchrone, idempotente). mem0 ≥ 0.1.40 retourne `{"results": [...]}` — toujours unwrapper avec `isinstance(results, dict)`.

AppState est accessible via `request.app.state.wally`.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_dashboard_memory_routes.py` :

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import (
    BotConfig, OpenAIConfig, EmotionDecayConfig, TwitchEventConfig,
    TwitchConfig, DiscordConfig,
)


def _make_config(dashboard_token: str = "test-token"):
    """Suit le même pattern que test_dashboard_routes.py — MagicMock + vraies dataclasses."""
    cfg = MagicMock()
    cfg.bot = BotConfig(
        trigger_names=["wally"],
        language_default="fr",
        context_window_size=10,
        context_token_threshold=2000,
        prelude_window_size=3,
        journal_time="08:00",
        journal_channel_id=None,
        dashboard_token=dashboard_token,
    )
    cfg.openai = OpenAIConfig(
        primary_model="gpt-4o-mini",
        secondary_model="gpt-4o-mini",
        temperature=0.7,
        max_tokens=1000,
    )
    cfg.discord = DiscordConfig(anger_trigger_threshold=3, timeout_minutes=10)
    cfg.twitch = TwitchConfig(channels=[], cooldown_seconds=10)
    cfg.emotions = {
        "anger": EmotionDecayConfig(decay_lambda=0.1),
        "joy": EmotionDecayConfig(decay_lambda=0.1),
        "sadness": EmotionDecayConfig(decay_lambda=0.1),
        "curiosity": EmotionDecayConfig(decay_lambda=0.1),
        "boredom": EmotionDecayConfig(decay_lambda=0.1),
    }
    cfg.twitch_events = {"follow": TwitchEventConfig(active=True, message="Hey!")}
    cfg.save = MagicMock()
    return cfg


def _make_state(dashboard_token: str = "test-token"):
    """Crée un AppState minimal pour les tests des routes mémoire."""
    # Memory service mock
    memory = MagicMock()
    memory._init_mem0 = MagicMock()  # synchrone, no-op
    mock_mem0 = MagicMock()
    memory._mem0 = mock_mem0

    # Database mock
    db = AsyncMock()

    state = AppState(
        config=_make_config(dashboard_token),
        db=db,
        emotion=MagicMock(),
        memory=memory,
        persona=MagicMock(),
        openai_client=MagicMock(),
        token_manager=MagicMock(),
        twitch_api=None,
        discord_bot=None,
        twitch_bot=None,
    )
    return state, mock_mem0, db


def _make_client(state: AppState):
    app = create_dashboard_app(state)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


HEADERS = {"Authorization": "Bearer test-token"}


# ── GET /api/admin/memory/users ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_users_returns_users():
    state, _, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0}
    ]
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data["users"]) == 1
    assert data["users"][0]["user_id"] == "discord:123"


@pytest.mark.asyncio
async def test_list_users_with_filter():
    state, _, db = _make_state()
    db.list_memory_users.return_value = []
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users?q=discord", headers=HEADERS)
    assert r.status_code == 200
    db.list_memory_users.assert_called_once_with("discord")


# ── GET /api/admin/memory/users/{user_id} ────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_memories_returns_list():
    state, mock_mem0, _ = _make_state()
    mock_mem0.get_all.return_value = [
        {"id": "mem-1", "memory": "Préfère le français"},
        {"id": "mem-2", "memory": "Aime Minecraft"},
    ]
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.get(
                "/api/admin/memory/users/discord%3A123", headers=HEADERS
            )
    assert r.status_code == 200
    data = r.json()
    assert len(data["memories"]) == 2
    assert data["memories"][0]["id"] == "mem-1"


@pytest.mark.asyncio
async def test_get_user_memories_unwraps_dict():
    """mem0 >= 0.1.40 retourne {"results": [...]}"""
    state, mock_mem0, _ = _make_state()
    mock_mem0.get_all.return_value = {
        "results": [{"id": "mem-1", "memory": "Test"}]
    }
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.get(
                "/api/admin/memory/users/discord%3A123", headers=HEADERS
            )
    assert r.status_code == 200
    assert len(r.json()["memories"]) == 1


@pytest.mark.asyncio
async def test_get_user_memories_503_when_mem0_none():
    state, _, _ = _make_state()
    state.memory._mem0 = None
    async with _make_client(state) as client:
        r = await client.get(
            "/api/admin/memory/users/discord%3A123", headers=HEADERS
        )
    assert r.status_code == 503


# ── DELETE /api/admin/memory/users/{user_id} ─────────────────────────────────

@pytest.mark.asyncio
async def test_delete_user_calls_delete_all_and_db():
    state, mock_mem0, db = _make_state()
    mock_mem0.delete_all = MagicMock()
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.delete(
                "/api/admin/memory/users/discord%3A123", headers=HEADERS
            )
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    mock_mem0.delete_all.assert_called_once_with(user_id="discord:123")
    db.execute.assert_called_once()


# ── DELETE /api/admin/memory/users/{user_id}/memories/{memory_id} ────────────

@pytest.mark.asyncio
async def test_delete_memory_calls_mem0_delete():
    state, mock_mem0, _ = _make_state()
    mock_mem0.delete = MagicMock()
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.delete(
                "/api/admin/memory/users/discord%3A123/memories/mem-abc",
                headers=HEADERS,
            )
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    mock_mem0.delete.assert_called_once_with("mem-abc")


# ── GET /api/admin/memory/search ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_requires_q():
    state, _, _ = _make_state()
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/search", headers=HEADERS)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_search_returns_results():
    state, mock_mem0, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0}
    ]
    mock_mem0.search.return_value = [
        {"memory": "Aime Minecraft", "score": 0.9}
    ]
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.get(
                "/api/admin/memory/search?q=Minecraft", headers=HEADERS
            )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["user_id"] == "discord:123"
    assert results[0]["memory"] == "Aime Minecraft"


@pytest.mark.asyncio
async def test_search_unwraps_dict():
    state, mock_mem0, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0}
    ]
    mock_mem0.search.return_value = {"results": [{"memory": "Test", "score": 0.8}]}
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.get(
                "/api/admin/memory/search?q=test", headers=HEADERS
            )
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_dashboard_memory_routes.py -v
```
Attendu : `FAILED` — les routes retournent 501

- [ ] **Step 3: Réécrire `bot/dashboard/routes/memory.py`**

```python
# bot/dashboard/routes/memory.py
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

if TYPE_CHECKING:
    pass

router = APIRouter()


def _get_mem0(request: Request):
    """Initialise mem0 si besoin et retourne l'objet, ou lève 503."""
    state = request.app.state.wally
    state.memory._init_mem0()
    if state.memory._mem0 is None:
        raise HTTPException(503, detail="mem0 not available")
    return state.memory._mem0


def _unwrap(results) -> list:
    """Unwrap mem0 >= 0.1.40 qui retourne {"results": [...]} au lieu d'une liste."""
    if isinstance(results, dict):
        return results.get("results", [])
    return results if results else []


# ── GET /memory/users ─────────────────────────────────────────────────────────

@router.get("/memory/users")
async def list_users(request: Request, q: str | None = None):
    state = request.app.state.wally
    users = await state.db.list_memory_users(q)
    return {"users": users}


# ── GET /memory/users/{user_id} ───────────────────────────────────────────────

@router.get("/memory/users/{user_id}")
async def get_user_memories(user_id: str, request: Request):
    mem0 = _get_mem0(request)
    results = await asyncio.to_thread(mem0.get_all, user_id=user_id)
    memories = [
        {"id": r.get("id"), "memory": r.get("memory", "")}
        for r in _unwrap(results)
        if r.get("memory")
    ]
    return {"user_id": user_id, "memories": memories}


# ── DELETE /memory/users/{user_id} ────────────────────────────────────────────

@router.delete("/memory/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    state = request.app.state.wally
    mem0 = _get_mem0(request)
    await asyncio.to_thread(mem0.delete_all, user_id=user_id)
    await state.db.execute(
        "DELETE FROM memory_users WHERE user_id = ?", (user_id,)
    )
    return {"deleted": True}


# ── DELETE /memory/users/{user_id}/memories/{memory_id} ──────────────────────

@router.delete("/memory/users/{user_id}/memories/{memory_id}")
async def delete_memory(user_id: str, memory_id: str, request: Request):
    mem0 = _get_mem0(request)
    await asyncio.to_thread(mem0.delete, memory_id)
    return {"deleted": True}


# ── GET /memory/search ────────────────────────────────────────────────────────

@router.get("/memory/search")
async def search_memories(request: Request, q: str | None = None):
    if not q or not q.strip():
        raise HTTPException(400, detail="q parameter required")
    state = request.app.state.wally
    mem0 = _get_mem0(request)

    users = await state.db.list_memory_users()
    all_results = []
    for user in users:
        uid = user["user_id"]
        platform = user["platform"]
        try:
            raw = await asyncio.to_thread(mem0.search, q, user_id=uid, limit=3)
            for r in _unwrap(raw):
                if r.get("memory"):
                    all_results.append({
                        "user_id": uid,
                        "platform": platform,
                        "memory": r["memory"],
                        "score": r.get("score", 0.0),
                    })
        except Exception:
            pass  # Qdrant timeout pour cet user — on continue

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": all_results}
```

- [ ] **Step 4: Vérifier que les tests passent**

```bash
pytest tests/test_dashboard_memory_routes.py -v
```
Attendu : tous les tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/routes/memory.py tests/test_dashboard_memory_routes.py
git commit -m "feat(dashboard): implement memory routes (list, get, delete, search)"
```

---

## Chunk 2: Frontend

### Task 4: Frontend — index.html + app.js

**Files:**
- Modify: `bot/dashboard/static/index.html`
- Modify: `bot/dashboard/static/app.js`

#### Contexte

Dans `index.html`, le bouton MÉMOIRE est actuellement :
```html
<button class="tab-btn disabled" title="Phase 2">🧠 MÉMOIRE</button>
```

Il faut : retirer `disabled`, ajouter `data-tab="memory"` et `onclick="showTab('memory')"`.

Ajouter `<div class="tab-content" id="tab-memory"></div>` dans `<main>`, après le dernier `tab-content` existant (`#tab-admin-logs`).

Dans `app.js`, la fonction `showTab(tabId)` existe déjà — ajouter l'init de la tab mémoire avec un guard `!document.getElementById('mem-user-list')` pour ne rendre qu'une seule fois.

Toutes les fonctions mémoire utilisent `apiFetch()` (déjà défini dans `app.js`) qui gère l'auth Bearer.

**Helpers existants :** `escHtml()` est déjà défini dans `app.js`. Ajouter `escAttr()` pour les attributs inline.

**Déviations intentionnelles par rapport au spec (améliorations) :**
- Fonction `selectMemUser` / variable `_selectedMemUser` (spec : `selectUser` / `_selectedUser`) — préfixe `mem` évite conflits de noms globaux
- IDs HTML `mem-entry-${m.id}` (spec : `mem-${m.id}`) — plus lisible pour le debug
- `u.user_id.split(':').slice(1).join(':')` (spec : `split(':')[1]`) — gère les noms Twitch avec `:`
- `_selectedMemUser = null` dans `deleteAllMemories` — évite une état stale après suppression
- `onMemSearch` : cas supplémentaire `else` quand champ vide + pas de user sélectionné → affiche message guide

- [ ] **Step 1: Modifier `bot/dashboard/static/index.html`**

Remplacer :
```html
<button class="tab-btn disabled" title="Phase 2">🧠 MÉMOIRE</button>
```

Par :
```html
<button class="tab-btn" data-tab="memory" onclick="showTab('memory')">🧠 MÉMOIRE</button>
```

Ajouter dans `<main>`, après la div `id="tab-admin-logs"` (et avant `</main>`) :
```html
  <!-- ── MEMORY ─────────────────────────────────────────────────────────── -->
  <div class="tab-content" id="tab-memory"></div>
```

- [ ] **Step 2: Vérifier `index.html`**

```bash
python3 -c "
from html.parser import HTMLParser
class P(HTMLParser):
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get('data-tab') == 'memory':
            print('OK: memory tab button found')
        if d.get('id') == 'tab-memory':
            print('OK: tab-memory div found')
        if d.get('onclick') == \"showTab('memory')\":
            print('OK: onclick found')
P().feed(open('bot/dashboard/static/index.html').read())
"
```
Attendu : trois lignes `OK`

- [ ] **Step 3: Ajouter les fonctions mémoire dans `bot/dashboard/static/app.js`**

Ajouter à la fin du fichier :

```javascript
// ── Memory tab ────────────────────────────────────────────────────────────────

function escAttr(str) {
  return String(str).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderMemoryTab() {
  document.getElementById('tab-memory').innerHTML = `
    <div style="padding:12px 16px;border-bottom:2px solid #333;display:flex;gap:10px;align-items:center">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px;white-space:nowrap">CHERCHER</span>
      <input type="text" id="mem-search" placeholder="Recherche dans tous les souvenirs…"
             oninput="onMemSearch(this.value)"
             style="flex:1;max-width:320px;padding:7px 10px;background:var(--bg);border:3px solid var(--border);color:var(--text);font-family:var(--font);font-size:0.9rem;box-shadow:2px 2px 0px #fff;outline:none;border-radius:0">
    </div>
    <div style="display:flex;min-height:400px">
      <div style="width:220px;border-right:2px solid #333;display:flex;flex-direction:column">
        <div style="padding:10px 12px;border-bottom:1px solid #333">
          <input type="text" id="mem-user-filter" placeholder="Filtrer users…"
                 oninput="onUserFilter(this.value)"
                 style="width:100%;padding:7px 10px;background:var(--bg);border:3px solid var(--border);color:var(--text);font-family:var(--font);font-size:0.8rem;outline:none;border-radius:0">
        </div>
        <div id="mem-user-list" style="flex:1;overflow-y:auto;padding:8px"></div>
      </div>
      <div id="mem-detail" style="flex:1;overflow-y:auto;min-height:0">
        <div style="padding:16px;color:var(--text-muted);font-size:0.85rem">
          Sélectionne un utilisateur pour voir ses souvenirs.
        </div>
      </div>
    </div>
  `;
  loadMemoryUsers();
}

let _selectedMemUser = null;

async function loadMemoryUsers(filter = '') {
  const url = '/api/admin/memory/users' + (filter ? `?q=${encodeURIComponent(filter)}` : '');
  const r = await apiFetch(url);
  if (!r || !r.ok) return;
  const { users } = await r.json();
  const el = document.getElementById('mem-user-list');
  if (!el) return;
  if (users.length === 0) {
    el.innerHTML = '<div style="color:#555;font-size:0.75rem;padding:8px">Aucun utilisateur</div>';
    return;
  }
  el.innerHTML = users.map(u => `
    <div class="mem-user-item"
         data-uid="${escAttr(u.user_id)}"
         onclick="selectMemUser('${escAttr(u.user_id)}')"
         style="padding:7px 10px;background:#1a1a1a;border:2px solid ${u.user_id === _selectedMemUser ? '#00ccff' : '#555'};
                margin-bottom:4px;cursor:pointer;color:${u.user_id === _selectedMemUser ? '#00ccff' : 'var(--text)'}">
      <span style="font-size:0.65rem;color:#888;display:block">${escHtml(u.platform)}</span>
      <span style="font-size:0.8rem">${escHtml(u.user_id.split(':').slice(1).join(':') || u.user_id)}</span>
    </div>`).join('');
}

async function selectMemUser(userId) {
  _selectedMemUser = userId;
  // Mettre à jour la sélection visuelle sans recharger toute la liste
  document.querySelectorAll('.mem-user-item').forEach(el => {
    const selected = el.dataset.uid === userId;
    el.style.borderColor = selected ? '#00ccff' : '#555';
    el.style.color = selected ? '#00ccff' : 'var(--text)';
  });
  await loadUserMemories(userId);
}

async function loadUserMemories(userId) {
  const r = await apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId));
  if (!r || !r.ok) return;
  const { memories } = await r.json();
  renderMemories(userId, memories);
}

function renderMemories(userId, memories) {
  const el = document.getElementById('mem-detail');
  if (!el) return;
  el.innerHTML = `
    <div style="padding:10px 16px;border-bottom:1px solid #333;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">${escHtml(userId)} — ${memories.length} souvenir(s)</span>
      <button class="btn btn-danger" onclick="deleteAllMemories('${escAttr(userId)}')"
              style="font-size:0.72rem;padding:4px 10px">🗑 TOUT SUPPRIMER</button>
    </div>
    <div style="padding:12px">
      ${memories.length === 0
        ? '<div style="color:#555;font-size:0.85rem">Aucun souvenir.</div>'
        : memories.map(m => `
          <div style="background:#1a1a1a;border:2px solid #333;padding:10px 12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-start"
               id="mem-entry-${escAttr(m.id)}">
            <span style="font-size:0.82rem;flex:1;line-height:1.5">${escHtml(m.memory)}</span>
            <button onclick="deleteMemory('${escAttr(userId)}','${escAttr(m.id)}')"
                    style="background:none;border:none;color:#ff3333;cursor:pointer;font-size:1.1rem;margin-left:12px;flex-shrink:0;line-height:1">✕</button>
          </div>`).join('')
      }
    </div>
  `;
}

async function deleteMemory(userId, memoryId) {
  const r = await apiFetch(
    `/api/admin/memory/users/${encodeURIComponent(userId)}/memories/${encodeURIComponent(memoryId)}`,
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    document.getElementById('mem-entry-' + memoryId)?.remove();
    toast('Souvenir supprimé', 'success');
  } else {
    toast('Erreur suppression', 'error');
  }
}

async function deleteAllMemories(userId) {
  const r = await apiFetch(
    '/api/admin/memory/users/' + encodeURIComponent(userId),
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    document.getElementById('mem-detail').innerHTML =
      '<div style="padding:16px;color:#555;font-size:0.85rem">Aucun souvenir.</div>';
    _selectedMemUser = null;
    const filter = document.getElementById('mem-user-filter')?.value || '';
    loadMemoryUsers(filter);
    toast('Mémoire supprimée', 'success');
  } else {
    toast('Erreur suppression', 'error');
  }
}

let _memSearchTimer = null;
function onMemSearch(value) {
  clearTimeout(_memSearchTimer);
  _memSearchTimer = setTimeout(async () => {
    if (value.length >= 2) {
      await searchMemories(value);
    } else if (_selectedMemUser) {
      await loadUserMemories(_selectedMemUser);
    } else {
      document.getElementById('mem-detail').innerHTML =
        '<div style="padding:16px;color:var(--text-muted);font-size:0.85rem">Sélectionne un utilisateur.</div>';
    }
  }, 400);
}

async function searchMemories(q) {
  const r = await apiFetch('/api/admin/memory/search?q=' + encodeURIComponent(q));
  if (!r || !r.ok) return;
  const { results } = await r.json();
  const el = document.getElementById('mem-detail');
  if (!el) return;
  el.innerHTML = `
    <div style="padding:10px 16px;border-bottom:1px solid #333">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">${results.length} résultat(s) pour "${escHtml(q)}"</span>
    </div>
    <div style="padding:12px">
      ${results.length === 0
        ? '<div style="color:#555;font-size:0.85rem">Aucun résultat.</div>'
        : results.map(res => `
          <div style="background:#1a1a1a;border:2px solid #333;padding:10px 12px;margin-bottom:8px">
            <span style="font-size:0.65rem;color:#888;display:block;margin-bottom:4px">${escHtml(res.user_id)}</span>
            <span style="font-size:0.82rem;line-height:1.5">${escHtml(res.memory)}</span>
          </div>`).join('')
      }
    </div>
  `;
}

let _userFilterTimer = null;
function onUserFilter(value) {
  clearTimeout(_userFilterTimer);
  _userFilterTimer = setTimeout(() => loadMemoryUsers(value), 300);
}
```

- [ ] **Step 4: Modifier la fonction `showTab` dans `app.js`**

Dans la fonction `showTab(tabId)` existante, trouver le bloc des "chargements spécifiques par onglet" (commentaire déjà présent) et ajouter :

```javascript
if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
```

Le bloc doit ressembler à :
```javascript
  // Chargements spécifiques par onglet
  if (tabId === 'stream')   loadStreamStatus();
  if (tabId === 'stats')    loadStats();
  if (tabId === 'emotions') loadEmotionHistory();
  if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
```

Vérifier que la ligne a bien été ajoutée :
```bash
grep -n "renderMemoryTab" bot/dashboard/static/app.js
```
Attendu : au moins 2 lignes — la définition de la fonction ET l'appel dans `showTab`.

- [ ] **Step 5: Vérifier la syntaxe JS**

```bash
node --check bot/dashboard/static/app.js && echo "JS syntax OK"
```
Attendu : `JS syntax OK`

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/app.js
git commit -m "feat(dashboard): add Memory admin tab with split layout and search"
```

---

## Chunk 3: Vérification finale

### Task 5: Vérification complète + commit final

**Files:** aucun (vérification uniquement)

- [ ] **Step 1: Vérifier la syntaxe Python de tous les fichiers modifiés**

```bash
python3 -m py_compile \
  bot/db/database.py \
  bot/core/memory.py \
  bot/main.py \
  bot/dashboard/routes/memory.py && echo "Syntax OK"
```
Attendu : `Syntax OK`

- [ ] **Step 2: Lancer la suite complète de tests**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```
Attendu : tous les nouveaux tests `PASSED`, 3 échecs pre-existants inchangés (`test_make_bar_*`).

Nouveaux tests attendus :
- `tests/test_dashboard_memory_db.py` — 5 tests
- `tests/test_memory_set_db.py` — 5 tests
- `tests/test_dashboard_memory_routes.py` — 10 tests

Total attendu : ~282 tests passants (262 existants + 20 nouveaux).

- [ ] **Step 3: Vérifier la syntaxe JS**

```bash
node --check bot/dashboard/static/app.js && echo "JS syntax OK"
```
Attendu : `JS syntax OK`

- [ ] **Step 4: Vérifier que l'arbre est propre**

```bash
git status
```
Attendu : "nothing to commit, working tree clean" — chaque tâche des Chunks 1-2 a déjà commité ses fichiers. Si des fichiers sont encore unstaged (ex: `index.html`, `app.js`), les ajouter explicitement :

```bash
# Seulement si nécessaire (ne PAS faire git add -A — risque de stager .env et __pycache__)
git add bot/dashboard/static/index.html bot/dashboard/static/app.js
git commit -m "feat(dashboard): add Memory admin tab with split layout and search"
```

---

## Notes d'implémentation

### Pattern `asyncio.to_thread` dans les tests

Dans `test_dashboard_memory_routes.py`, les appels `asyncio.to_thread(fn, **kwargs)` sont mockés avec :
```python
patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw)))
```
Cela exécute `fn(**kw)` directement (synchrone) au lieu de le déléguer à un thread.

### Guard `_init_mem0()` avant accès à `_mem0`

`_init_mem0()` est synchrone et idempotente (guard `_mem0_init_attempted`). L'appeler à chaque requête est sûr — elle ne tente l'initialisation qu'une seule fois.

### URL encoding des user_id

`user_id` contient `:` (ex: `discord:123`). FastAPI décode automatiquement les path params URL-encodés (`discord%3A123` → `discord:123`). Le client JS utilise `encodeURIComponent(userId)` avant chaque appel.

### mem0 dict unwrapping

mem0 ≥ 0.1.40 retourne `{"results": [...]}` au lieu d'une liste. La fonction helper `_unwrap()` gère les deux cas pour `get_all` et `search`.
