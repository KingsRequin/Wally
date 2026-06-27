# Wally Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre lisible et complet « ce qui se passe dans la tête de Wally » : flux cognitif riche + historique persistant + texte dépliable (site public), popup but courant, et exposition de la mémoire (admin).

**Architecture:** Backend — un `CognitiveEventStore` SQLite (rotation 1000) que `CognitiveFeed.publish` alimente (sauf ATTN), de nouvelles routes publiques (history, goal) et admin (facts user, mémoire interne). Front — rendu enrichi par type + clic-déplier + scroll historique + popup but (public), détail mémoire (admin).

**Tech Stack:** Python 3.11 asyncio, aiosqlite, FastAPI, JS vanilla (public-starter), pytest.

## Global Constraints

- Logging via `loguru` uniquement (jamais `print`/`logging`).
- Tout I/O async ; best-effort sur le feed/persistance — **jamais bloquant pour le tick** (try/except + log warning).
- Mémoire V2 = `SQLiteFactStore` (FTS5/SQLite). `user_id` brut côté API mémoire (`memory.add` rebuild `platform:user_id`), mais `fact_store.get_by_user` attend le `user_id` **préfixé** (`"discord:123"`, `"wally:self"`).
- DDL idempotent (`CREATE TABLE IF NOT EXISTS`), comme `schema_v2.py`.
- Historique : **ATTN exclu** de la persistance (live seulement). Cap rotation = **1000**.
- Front public : source de vérité = `bot/dashboard/static/public-starter/` ; **miroir requis** vers `public-ui/`.
- Design arcade : VT323/Press Start 2P, fond CRT `#120a26`, couleurs events existantes (THINK `#ffd400`, SPEAK `#43e0ff`, ACT `#7CFC52`, DECIDE `#bf94ff`, ATTN `#ff3b6b`, EVOLVE `#ff8a3b`).
- Déploiement backend = rebuild image (non bind-mount).

---

# Phase A — Backend feed

### Task A1: CognitiveEventStore (table + append + rotation + recent)

**Files:**
- Create: `bot/intelligence/cognitive_event_store.py`
- Modify: `bot/db/schema_v2.py` (ajout DDL `cognitive_events`)
- Test: `tests/intelligence/core/test_cognitive_event_store.py`

**Interfaces:**
- Produces:
  - `CognitiveEventStore(db_path: str, cap: int = 1000)`
  - `async append(event: dict) -> None` — INSERT (ts mur + JSON) puis trim au cap.
  - `async recent(limit: int = 50, before_id: int | None = None) -> list[dict]` — events décroissants ; chaque dict = l'event d'origine + `{"id": int, "ts": float}`.

- [ ] **Step 1: Ajouter le DDL idempotent dans `schema_v2.py`**

Dans `_SCHEMA_SQL` (après la table `fact_relations`), ajouter :

```sql
CREATE TABLE IF NOT EXISTS cognitive_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    type    TEXT    NOT NULL,
    payload TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_events_id ON cognitive_events(id);
```

- [ ] **Step 2: Écrire le test (rotation + recent)**

```python
# tests/intelligence/core/test_cognitive_event_store.py
import pytest
from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.cognitive_event_store import CognitiveEventStore


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "wally.db")
    await create_v2_tables(db_path)
    return CognitiveEventStore(db_path, cap=5)


@pytest.mark.asyncio
async def test_append_and_recent_roundtrip(store):
    await store.append({"type": "THINK", "text": "bonjour"})
    rows = await store.recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["type"] == "THINK"
    assert rows[0]["text"] == "bonjour"
    assert isinstance(rows[0]["id"], int)
    assert isinstance(rows[0]["ts"], float)


@pytest.mark.asyncio
async def test_recent_is_descending(store):
    for i in range(3):
        await store.append({"type": "ACT", "detail": f"a{i}"})
    rows = await store.recent(limit=10)
    assert [r["detail"] for r in rows] == ["a2", "a1", "a0"]


@pytest.mark.asyncio
async def test_rotation_caps_rows(store):
    for i in range(12):
        await store.append({"type": "ACT", "detail": f"a{i}"})
    rows = await store.recent(limit=100)
    assert len(rows) == 5                      # cap respecté
    assert rows[0]["detail"] == "a11"          # le plus récent gardé


@pytest.mark.asyncio
async def test_recent_pagination_before_id(store):
    ids = []
    for i in range(4):
        await store.append({"type": "ACT", "detail": f"a{i}"})
    rows = await store.recent(limit=10)
    mid = rows[1]["id"]                          # 3e plus récent commence après
    older = await store.recent(limit=10, before_id=mid)
    assert all(r["id"] < mid for r in older)
```

- [ ] **Step 3: Lancer les tests — échec attendu**

Run: `python3 -m pytest tests/intelligence/core/test_cognitive_event_store.py -q`
Expected: FAIL (`ModuleNotFoundError: cognitive_event_store`)

- [ ] **Step 4: Implémenter `CognitiveEventStore`**

```python
# bot/intelligence/cognitive_event_store.py
from __future__ import annotations

import json
import time

import aiosqlite
from loguru import logger


class CognitiveEventStore:
    """Historique persistant léger du flux cognitif (rotation par count)."""

    def __init__(self, db_path: str, cap: int = 1000) -> None:
        self._db_path = db_path
        self._cap = cap

    async def append(self, event: dict) -> None:
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT INTO cognitive_events (ts, type, payload) VALUES (?, ?, ?)",
                    (time.time(), str(event.get("type", "event")),
                     json.dumps(event, ensure_ascii=False)),
                )
                # Rotation : ne garder que les `cap` derniers ids.
                await db.execute(
                    "DELETE FROM cognitive_events WHERE id <= "
                    "(SELECT MAX(id) FROM cognitive_events) - ?",
                    (self._cap,),
                )
                await db.commit()
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            logger.warning("CognitiveEventStore.append: {}", e)

    async def recent(self, limit: int = 50, before_id: int | None = None) -> list[dict]:
        sql = "SELECT id, ts, payload FROM cognitive_events"
        params: list = []
        if before_id is not None:
            sql += " WHERE id < ?"
            params.append(before_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(sql, params)
                rows = await cur.fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("CognitiveEventStore.recent: {}", e)
            return []
        out = []
        for r in rows:
            try:
                evt = json.loads(r["payload"])
            except Exception:  # noqa: BLE001
                evt = {"type": "event"}
            evt["id"] = r["id"]
            evt["ts"] = r["ts"]
            out.append(evt)
        return out
```

- [ ] **Step 5: Lancer les tests — succès attendu**

Run: `python3 -m pytest tests/intelligence/core/test_cognitive_event_store.py -q`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add bot/intelligence/cognitive_event_store.py bot/db/schema_v2.py tests/intelligence/core/test_cognitive_event_store.py
git commit -m "feat(cognition): CognitiveEventStore — historique persistant du flux cognitif"
```

---

### Task A2: CognitiveFeed persiste les events (sauf ATTN)

**Files:**
- Modify: `bot/intelligence/cognitive_feed.py`
- Test: `tests/intelligence/core/test_cognitive_feed_persist.py` (create)

**Interfaces:**
- Consumes: `CognitiveEventStore.append` (Task A1).
- Produces: `CognitiveFeed(buffer_size, queue_maxsize, conv_log, event_store=None)` — `publish` planifie `event_store.append(event)` pour tout type **sauf `ATTN`**.

- [ ] **Step 1: Écrire le test**

```python
# tests/intelligence/core/test_cognitive_feed_persist.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.cognitive_feed import CognitiveFeed


@pytest.mark.asyncio
async def test_publish_persists_non_attn():
    store = MagicMock()
    store.append = AsyncMock()
    feed = CognitiveFeed(event_store=store)
    feed.publish({"type": "ACT", "detail": "react 🔥"})
    await asyncio.sleep(0)            # laisse la task append s'exécuter
    store.append.assert_awaited_once()
    assert store.append.await_args.args[0]["type"] == "ACT"


@pytest.mark.asyncio
async def test_publish_skips_attn_persistence():
    store = MagicMock()
    store.append = AsyncMock()
    feed = CognitiveFeed(event_store=store)
    feed.publish({"type": "ATTN", "target": "x", "content_snippet": "y"})
    await asyncio.sleep(0)
    store.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_without_store_does_not_crash():
    feed = CognitiveFeed()              # event_store=None
    feed.publish({"type": "THINK", "text": "ok"})   # ne doit pas lever
```

- [ ] **Step 2: Lancer — échec attendu**

Run: `python3 -m pytest tests/intelligence/core/test_cognitive_feed_persist.py -q`
Expected: FAIL (`event_store` inconnu)

- [ ] **Step 3: Modifier `CognitiveFeed`**

Dans `__init__`, ajouter le paramètre et le stocker :

```python
    def __init__(
        self, buffer_size: int = 30, queue_maxsize: int = 50, conv_log=None,
        event_store=None,
    ) -> None:
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._queues: list[asyncio.Queue] = []
        self._queue_maxsize = queue_maxsize
        self._conv_log = conv_log
        # Historique persistant (#observability). None → live seulement.
        self._event_store = event_store
```

Dans `publish`, après le fan-out (fin de méthode), ajouter la persistance best-effort (ATTN exclu) :

```python
        # Persistance de l'historique (sauf ATTN, trop fréquent/transitoire).
        if self._event_store is not None and event.get("type") != "ATTN":
            try:
                asyncio.get_running_loop().create_task(
                    self._event_store.append(dict(event))
                )
            except RuntimeError:
                pass   # pas de loop (test sync) → on saute la persistance
```

- [ ] **Step 4: Lancer — succès attendu**

Run: `python3 -m pytest tests/intelligence/core/test_cognitive_feed_persist.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/cognitive_feed.py tests/intelligence/core/test_cognitive_feed_persist.py
git commit -m "feat(cognition): CognitiveFeed persiste le flux (hors ATTN) via event_store"
```

---

### Task A3: REACT — type d'event distinct

**Files:**
- Modify: `bot/intelligence/action_dispatcher.py` (méthode `_react`, ≈l.421)
- Test: `tests/intelligence/core/test_action_dispatcher.py`

**Interfaces:**
- Produces: l'action `react` publie `{"type": "REACT", "emoji", "channel", "detail"}` au lieu de `{"type": "ACT", "detail": "react …"}`.

- [ ] **Step 1: Lire `_react` et son émission feed actuelle**

Run: `grep -n "_react\|react" bot/intelligence/action_dispatcher.py | head`
Repérer l'appel `self._feed.publish({"type": "ACT", "detail": f"react …"})`.

- [ ] **Step 2: Écrire le test**

```python
@pytest.mark.asyncio
async def test_react_publishes_distinct_type():
    from unittest.mock import MagicMock
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision
    feed = MagicMock()
    bot = MagicMock()                       # _react a besoin du bot Discord
    dispatcher = ActionDispatcher(bot=bot, feed=feed)
    # neutraliser l'I/O Discord réelle de _react :
    dispatcher._react = dispatcher._react   # (voir Step 4 : émission AVANT l'I/O)
    await dispatcher.dispatch(MetaDecision(
        action="ACT", act_name="react",
        act_args={"channel_id": "1", "message_id": "2", "emoji": "🔥"},
    ))
    types = [c.args[0].get("type") for c in feed.publish.call_args_list if c.args]
    assert "REACT" in types
```

> Note : si `_react` fait de l'I/O Discord avant l'émission, déplacer l'émission feed **avant** l'I/O (ou la rendre best-effort) pour que le test n'exige pas de vrai client.

- [ ] **Step 3: Lancer — échec attendu**

Run: `python3 -m pytest tests/intelligence/core/test_action_dispatcher.py -k react_publishes_distinct -q`
Expected: FAIL (type "ACT" au lieu de "REACT")

- [ ] **Step 4: Modifier l'émission dans `_react`**

Remplacer `self._feed.publish({"type": "ACT", "detail": f"react {emoji}"})` par :

```python
        if self._feed:
            self._feed.publish({
                "type": "REACT", "emoji": emoji, "channel": str(channel_id),
                "detail": f"a réagi {emoji}",
            })
```

- [ ] **Step 5: Lancer — succès attendu**

Run: `python3 -m pytest tests/intelligence/core/test_action_dispatcher.py -k react -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add bot/intelligence/action_dispatcher.py tests/intelligence/core/test_action_dispatcher.py
git commit -m "feat(cognition): REACT devient un type d'event distinct du flux"
```

---

### Task A4: Self-fix — issue publiée sur le feed

**Files:**
- Modify: `bot/intelligence/self_fix.py` (≈l.276-303, là où l'issue est persistée en mémoire)
- Test: `tests/test_self_fix.py` (ou créer si absent)

**Interfaces:**
- Consumes: le `feed` déjà injecté dans `self_fix` (sinon best-effort via `getattr`).
- Produces: à chaque transition (acceptée / refusée / déployée / abandonnée), `feed.publish({"type": "ACT", "detail": "auto-modif <issue> : <goal>", "full": <goal complet>})`.

- [ ] **Step 1: Repérer le feed dans self_fix**

Run: `grep -n "feed\|publish\|goal\|self._\(deploy\|outcome\|accept\)" bot/intelligence/self_fix.py | head -30`
Identifier si `self_fix` a accès à `cognitive_feed` (attribut ou via le bot). Sinon, l'injecter dans le constructeur (ajouter `feed=None`) et le câbler au wiring (Task A8).

- [ ] **Step 2: Écrire le test** (adapter aux noms réels repérés au Step 1)

```python
@pytest.mark.asyncio
async def test_self_fix_publishes_outcome_to_feed():
    from unittest.mock import MagicMock
    feed = MagicMock()
    # construire le SelfFix avec feed=feed et simuler une issue "déployée"
    # puis :
    types_details = [c.args[0] for c in feed.publish.call_args_list if c.args]
    assert any(e["type"] == "ACT" and "auto-modif" in e["detail"] for e in types_details)
```

- [ ] **Step 3: Lancer — échec attendu** ; **Step 4: publier l'issue** au point de transition :

```python
        if getattr(self, "_feed", None):
            self._feed.publish({
                "type": "ACT",
                "detail": f"auto-modif {issue} : {goal[:200]}",
                "full": goal,
            })
```

- [ ] **Step 5: Lancer — succès** ; **Step 6: Commit**

```bash
git add bot/intelligence/self_fix.py tests/test_self_fix.py
git commit -m "feat(cognition): self-fix publie son issue (acceptée/refusée/déployée) sur le feed"
```

---

### Task A5: Anti-troncature — champ `full` sur les ACT longs

**Files:**
- Modify: `bot/intelligence/action_dispatcher.py` (émissions ACT tronquées : `detail[:300]`, code_fix `goal[:60]`)
- Test: `tests/intelligence/core/test_action_dispatcher.py`

**Interfaces:**
- Produces: les events ACT au texte tronqué portent désormais `detail` (snippet, ≤300) **et** `full` (texte complet, ≤2000).

- [ ] **Step 1: Écrire le test (code_fix)**

```python
@pytest.mark.asyncio
async def test_code_fix_event_carries_full_goal():
    from unittest.mock import MagicMock
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision
    feed = MagicMock()
    long_goal = "x" * 400
    dispatcher = ActionDispatcher(bot=MagicMock(), feed=feed, fact_store=MagicMock())
    # déclencher code_fix (adapter : code_fix exige peut-être un gate/owner — mocker)
    # ...
    evs = [c.args[0] for c in feed.publish.call_args_list if c.args]
    cf = next(e for e in evs if "auto-modif" in e.get("detail", ""))
    assert cf["full"] == long_goal
    assert len(cf["detail"]) <= 250
```

- [ ] **Step 2: Lancer — échec** ; **Step 3: ajouter `full`** aux émissions concernées :

Pour code_fix (≈l.591) : `goal[:60]` → `goal[:200]`, et ajouter `"full": goal`. Pour les ACT `detail[:300]` issus d'un texte plus long (create_memory, note), ajouter `"full": <texte complet>[:2000]`.

- [ ] **Step 4: Lancer — succès** ; **Step 5: Commit**

```bash
git add bot/intelligence/action_dispatcher.py tests/intelligence/core/test_action_dispatcher.py
git commit -m "feat(cognition): events ACT portent le texte complet (full) pour le dépliage"
```

---

### Task A6: Route `/api/public/cognitive/history`

**Files:**
- Modify: `bot/dashboard/routes/cognitive.py`
- Test: `tests/test_dashboard_cognitive.py` (create)

**Interfaces:**
- Consumes: `request.app.state.wally.cognitive_event_store` (exposé en Task A8).
- Produces: `GET /api/public/cognitive/history?limit=50&before=<id>` → `{"events": [...], "next_before": <id|null>}`.

- [ ] **Step 1: Écrire le test (route via app FastAPI minimale)**

```python
# tests/test_dashboard_cognitive.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bot.dashboard.routes.cognitive import public_router


def _client(store=None):
    app = FastAPI()
    app.include_router(public_router, prefix="/api/public")
    wally = MagicMock()
    wally.cognitive_event_store = store
    app.state.wally = wally
    return TestClient(app)


def test_history_returns_events_and_next_before():
    store = MagicMock()
    store.recent = AsyncMock(return_value=[
        {"id": 9, "type": "THINK", "text": "a"},
        {"id": 7, "type": "ACT", "detail": "b"},
    ])
    r = _client(store).get("/api/public/cognitive/history?limit=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["events"]) == 2
    assert body["next_before"] == 7        # plus petit id de la page


def test_history_no_store_returns_empty():
    r = _client(None).get("/api/public/cognitive/history")
    assert r.json() == {"events": [], "next_before": None}
```

- [ ] **Step 2: Lancer — échec** ; **Step 3: ajouter la route**

```python
@public_router.get("/cognitive/history")
async def cognitive_history(request: Request, limit: int = 50, before: int | None = None):
    store = getattr(request.app.state.wally, "cognitive_event_store", None)
    if store is None:
        return {"events": [], "next_before": None}
    limit = max(1, min(limit, 200))
    events = await store.recent(limit=limit, before_id=before)
    next_before = events[-1]["id"] if events else None
    return {"events": events, "next_before": next_before}
```

- [ ] **Step 4: Lancer — succès** ; **Step 5: Commit**

```bash
git add bot/dashboard/routes/cognitive.py tests/test_dashboard_cognitive.py
git commit -m "feat(dashboard): route /api/public/cognitive/history (historique paginé)"
```

---

### Task A7: Route `/api/public/cognitive/goal`

**Files:**
- Modify: `bot/dashboard/routes/cognitive.py`
- Test: `tests/test_dashboard_cognitive.py`

**Interfaces:**
- Consumes: `request.app.state.wally.fact_store` (exposé en Task A8) — `search_by_category`, `get_latest_by_source`.
- Produces: `GET /api/public/cognitive/goal` → `{"goals": [str], "preoccupation": str|None, "desires": [str]}`.

- [ ] **Step 1: Écrire le test**

```python
def test_goal_route_shape():
    from bot.intelligence.memory.facts import FactCategory
    store = MagicMock()
    async def by_cat(cat, status=None, limit=10):
        return [MagicMock(content="dominer Apex")] if cat == FactCategory.GOAL else \
               [MagicMock(content="comprendre Kaelis")] if cat == FactCategory.DESIRE else []
    store.search_by_category = AsyncMock(side_effect=by_cat)
    store.get_latest_by_source = AsyncMock(return_value=MagicMock(content="le silence de KingsRequin"))
    app = FastAPI(); app.include_router(public_router, prefix="/api/public")
    wally = MagicMock(); wally.fact_store = store; app.state.wally = wally
    r = TestClient(app).get("/api/public/cognitive/goal")
    body = r.json()
    assert body["goals"] == ["dominer Apex"]
    assert body["preoccupation"] == "le silence de KingsRequin"
    assert body["desires"] == ["comprendre Kaelis"]
```

- [ ] **Step 2: Lancer — échec** ; **Step 3: ajouter la route**

```python
@public_router.get("/cognitive/goal")
async def cognitive_goal(request: Request):
    store = getattr(request.app.state.wally, "fact_store", None)
    if store is None:
        return {"goals": [], "preoccupation": None, "desires": []}
    from bot.intelligence.memory.facts import FactCategory, FactStatus
    goals = await store.search_by_category(FactCategory.GOAL, status=FactStatus.ACTIVE, limit=5)
    desires = await store.search_by_category(FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=5)
    focus = await store.get_latest_by_source("wally:self", "focus")
    return {
        "goals": [g.content for g in goals],
        "preoccupation": focus.content if focus else None,
        "desires": [d.content for d in desires],
    }
```

- [ ] **Step 4: Lancer — succès** ; **Step 5: Commit**

```bash
git add bot/dashboard/routes/cognitive.py tests/test_dashboard_cognitive.py
git commit -m "feat(dashboard): route /api/public/cognitive/goal (but courant + préoccupation)"
```

---

### Task A8: Wiring DI — event_store + exposer fact_store sur le bot

**Files:**
- Modify: `bot/discord/bot.py` (≈l.162-232, création fact_store / cognitive_feed)
- Test: vérification de démarrage (pas de test unitaire — fold dans la vérif globale)

**Interfaces:**
- Produces: `self.cognitive_event_store`, `self.fact_store` exposés sur le bot (lus par les routes A6/A7) ; `CognitiveFeed(..., event_store=self.cognitive_event_store)` ; `self_fix` reçoit `feed=self.cognitive_feed` (Task A4).

- [ ] **Step 1: Exposer le fact_store** — après `_fact_store = SQLiteFactStore(_db_path)` :

```python
            self.fact_store = _fact_store
```

- [ ] **Step 2: Créer l'event store** — avant la création de `CognitiveFeed` :

```python
            from bot.intelligence.cognitive_event_store import CognitiveEventStore
            self.cognitive_event_store = CognitiveEventStore(_db_path)
```

- [ ] **Step 3: Injecter dans le feed** — modifier la ligne `self.cognitive_feed = CognitiveFeed(conv_log=_conv_log)` :

```python
            self.cognitive_feed = CognitiveFeed(
                conv_log=_conv_log, event_store=self.cognitive_event_store,
            )
```

- [ ] **Step 4: Câbler le feed dans self_fix** (selon Task A4) là où `self_fix`/`SelfFix` est construit (grep `SelfFix(` / `self_fix`), passer `feed=self.cognitive_feed`.

- [ ] **Step 5: Vérifier import + compile**

Run: `python3 -m py_compile bot/discord/bot.py bot/intelligence/cognitive_feed.py bot/intelligence/cognitive_event_store.py`
Expected: aucune sortie (OK)

- [ ] **Step 6: Suite complète + commit**

Run: `python3 -m pytest -q` (attendu : verts sauf les 3 échecs + 16 erreurs costs PRÉEXISTANTS)

```bash
git add bot/discord/bot.py
git commit -m "chore(cognition): wiring DI event_store + fact_store/feed pour routes et self-fix"
```

---

# Phase B — Front public (vérifié au navigateur)

> Le front JS vanilla n'a pas de tests auto : chaque task se vérifie au **navigateur** (chromium headless 390px + desktop). Fichier : `bot/dashboard/static/public-starter/tabs/status.js`. **Miroir obligatoire** vers `public-ui/tabs/status.js` à la fin de chaque task.

### Task B1: Rendu enrichi par type (libellés + icônes + REACT/DM/self-fix)

**Files:**
- Modify: `bot/dashboard/static/public-starter/tabs/status.js` (`feedText`, ≈l.34-42 ; couleurs ≈l.20-23)

- [ ] **Step 1: Étendre `feedText` et la table de couleurs/icônes**

```javascript
const FEED_META = {
  THINK:  { color: '#ffd400', icon: '💭', label: 'pense' },
  SPEAK:  { color: '#43e0ff', icon: '🗣️', label: 'parle' },
  ACT:    { color: '#7CFC52', icon: '⚙️', label: 'agit' },
  REACT:  { color: '#7CFC52', icon: '😶', label: 'réagit' },
  DM:     { color: '#43e0ff', icon: '✉️', label: 'DM' },
  DECIDE: { color: '#bf94ff', icon: '🎯', label: 'décide' },
  ATTN:   { color: '#ff3b6b', icon: '👁️', label: 'remarque' },
  EVOLVE: { color: '#ff8a3b', icon: '🧬', label: 'évolue' },
  SLEEP:  { color: '#6f6597', icon: '😴', label: 'somnole' },
};

function feedText(e) {
  if (e.type === 'THINK') return e.text || '';
  if (e.type === 'SPEAK') return (e.channel ? '#'+e.channel+' ' : '') + (e.detail || '');
  if (e.type === 'REACT') return (e.detail || ('a réagi ' + (e.emoji || '')));
  if (e.type === 'DM')    return '→ ' + (e.target || '') + ' : ' + (e.message || '');
  if (e.type === 'ATTN')  return (e.target || '—') + ' : ' + (e.content_snippet || '');
  if (e.type === 'DECIDE') return (e.actions || []).join(' · ');
  if (e.type === 'ACT')   return e.detail || '';
  if (e.type === 'EVOLVE') return 'persona → ' + (e.detail || '');
  return e.detail || e.text || '';
}
```

Utiliser `FEED_META[e.type]` dans `renderFeed` pour l'icône + le libellé + la couleur de bordure de chaque ligne.

- [ ] **Step 2: Vérifier au navigateur** — lancer l'app (skill `run`), ouvrir le site, déclencher quelques events, confirmer que SPEAK/ACT/REACT/DM apparaissent distinctement (icône + couleur). Capturer un screenshot.

- [ ] **Step 3: Miroir + commit**

```bash
cp bot/dashboard/static/public-starter/tabs/status.js public-ui/tabs/status.js
git add bot/dashboard/static/public-starter/tabs/status.js public-ui/tabs/status.js
git commit -m "feat(public): flux cognitif — rendu enrichi par type (icônes, libellés, REACT/DM)"
```

### Task B2: Clic pour déplier le texte complet (`full`)

- [ ] **Step 1:** Dans `renderFeed`, si `e.full && e.full !== feedText(e)`, rendre la ligne cliquable (`cursor:pointer`, classe `expandable`). Au clic, basculer l'affichage entre `feedText(e)` (snippet) et `e.full`. Stocker l'état déplié dans un `Set` d'ids (ou index).
- [ ] **Step 2:** Vérifier au navigateur (un event long, ex. self-fix goal) se déplie/replie au clic. Screenshot.
- [ ] **Step 3:** Miroir + commit `feat(public): clic pour déplier le texte complet d'un event`.

### Task B3: Scroll historique (charge `/cognitive/history`)

- [ ] **Step 1:** Ajouter `loadHistory(beforeId)` qui `fetch('/api/public/cognitive/history?before='+beforeId)`, append les events (les plus anciens en bas), mémorise `next_before`. Au scroll en bas de `.feed-list` (`scrollTop+clientHeight >= scrollHeight-20`), appeler `loadHistory(next_before)` si pas déjà en cours et `next_before !== null`.
- [ ] **Step 2:** Vérifier au navigateur : scroller charge des events plus anciens. Screenshot.
- [ ] **Step 3:** Miroir + commit `feat(public): historique défilable du flux cognitif`.

### Task B4: Popup « but actuel »

- [ ] **Step 1:** Ajouter un bouton `🎯 Son but` dans l'en-tête de l'onglet activité. Au clic, `fetch('/api/public/cognitive/goal')` puis afficher une modale arcade : section « But » (liste `goals`, sinon « il vagabonde, aucun but fixé »), « Préoccupation du moment » (`preoccupation`), « Ce qui le travaille » (`desires`). Fermeture au clic hors modale / Échap.
- [ ] **Step 2:** Vérifier au navigateur (avec et sans but). Screenshot.
- [ ] **Step 3:** Miroir + commit `feat(public): popup but courant de Wally`.

---

# Phase C — Admin mémoire

### Task C1: Route `/api/admin/memory/users/{user_id}/facts`

**Files:**
- Modify: `bot/dashboard/routes/memory.py` (remplace le stub ≈l.249-254)
- Test: `tests/test_dashboard_memory_facts.py` (create)

**Interfaces:**
- Consumes: `fact_store.get_by_user(user_id)` (user_id **préfixé**).
- Produces: `GET /api/admin/memory/users/{user_id}/facts` → `{"facts": [{"id","content","category","subject","predicate","object","confidence","origin","created_at"}]}`. Auth admin requise (même dépendance que les autres routes admin du fichier).

- [ ] **Step 1: Lire le stub + le pattern d'auth admin du fichier**

Run: `sed -n '240,260p' bot/dashboard/routes/memory.py` ; repérer la dépendance d'auth (ex. `Depends(require_admin)`) utilisée par les routes voisines.

- [ ] **Step 2: Écrire le test** (mock fact_store sur app.state, auth mockée comme les tests admin existants — voir `tests/test_dashboard_routes.py`).

```python
def test_user_facts_route_returns_spo():
    # app + router memory + app.state.wally.fact_store mock
    # fact_store.get_by_user("discord:123") -> [AtomicFact(...)]
    # GET /api/admin/memory/users/discord:123/facts
    # assert body["facts"][0]["content"] == "..."
    ...
```

- [ ] **Step 3: Lancer — échec** ; **Step 4: implémenter** (remplacer le stub) :

```python
@router.get("/memory/users/{user_id}/facts")
async def user_facts(user_id: str, request: Request, _=Depends(require_admin)):
    store = getattr(request.app.state.wally, "fact_store", None)
    if store is None:
        return {"facts": []}
    facts = await store.get_by_user(user_id)
    return {"facts": [{
        "id": f.id, "content": f.content, "category": f.category.value,
        "subject": f.subject, "predicate": f.predicate, "object": f.object_,
        "confidence": f.confidence, "origin": f.origin,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in facts]}
```

- [ ] **Step 5: Lancer — succès** ; **Step 6: Commit** `feat(dashboard): route admin faits S-P-O par utilisateur`.

### Task C2: Route `/api/admin/memory/self`

**Files:**
- Modify: `bot/dashboard/routes/memory.py`
- Test: `tests/test_dashboard_memory_facts.py`

**Interfaces:**
- Produces: `GET /api/admin/memory/self` → `{"goals":[…],"desires":[…],"thoughts":[…],"relationships":[…],"focus":str|None}` (contenus). Source : `search_by_category(GOAL/DESIRE/THOUGHT)`, `get_by_user("wally:self",[REL])`, `get_latest_by_source("wally:self","focus")`.

- [ ] **Step 1: test** (mock fact_store, structure de réponse). **Step 2: échec.**
- [ ] **Step 3: implémenter** :

```python
@router.get("/memory/self")
async def wally_self(request: Request, _=Depends(require_admin)):
    store = getattr(request.app.state.wally, "fact_store", None)
    if store is None:
        return {"goals": [], "desires": [], "thoughts": [], "relationships": [], "focus": None}
    from bot.intelligence.memory.facts import FactCategory, FactStatus
    async def cat(c, n): 
        return [f.content for f in await store.search_by_category(c, status=FactStatus.ACTIVE, limit=n)]
    rels = await store.get_by_user("wally:self", categories=[FactCategory.REL])
    focus = await store.get_latest_by_source("wally:self", "focus")
    return {
        "goals": await cat(FactCategory.GOAL, 10),
        "desires": await cat(FactCategory.DESIRE, 10),
        "thoughts": await cat(FactCategory.THOUGHT, 10),
        "relationships": [r.content for r in rels[:10]],
        "focus": focus.content if focus else None,
    }
```

- [ ] **Step 4: succès** ; **Step 5: Commit** `feat(dashboard): route admin mémoire interne de Wally`.

### Task C3: Front admin — détail utilisateur (faits S-P-O)

**Files:**
- Modify: `bot/dashboard/static/app.js` (détail user, ex-stub « mémoire en refonte »)

- [ ] **Step 1:** Au clic sur un utilisateur (onglet Mémoire › Utilisateurs), `fetch('/api/admin/memory/users/'+id+'/facts')` et rendre une liste : contenu, badge catégorie (couleur), confiance, origine, date. Remplacer le message stub.
- [ ] **Step 2:** Vérifier au navigateur (admin, un user avec des faits). Screenshot.
- [ ] **Step 3:** Commit `feat(admin): détail utilisateur — faits S-P-O mémorisés`.

### Task C4: Front admin — section « Dans la tête de Wally »

**Files:**
- Modify: `bot/dashboard/static/app.js` (onglet Mémoire)

- [ ] **Step 1:** Ajouter un sous-onglet/section « Dans la tête de Wally » qui `fetch('/api/admin/memory/self')` et affiche : Buts, Désirs, Pensées récentes, Affinités, Focus (chaque section = liste, vide → tiret).
- [ ] **Step 2:** Vérifier au navigateur. Screenshot.
- [ ] **Step 3:** Commit `feat(admin): section « tête de Wally » (buts, désirs, pensées, affinités, focus)`.

---

## Vérification finale (toutes phases)

- [ ] `python3 -m pytest -q` → verts sauf les 3 échecs + 16 erreurs costs **préexistants**.
- [ ] `python3 -m py_compile` sur tous les fichiers Python modifiés.
- [ ] Front vérifié au navigateur (public + admin), mobile 390px inclus.
- [ ] Miroir `public-ui/` à jour.
- [ ] Note : déploiement = rebuild image (backend non bind-mount).
