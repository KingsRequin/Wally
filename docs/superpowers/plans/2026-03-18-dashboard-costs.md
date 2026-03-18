# Dashboard Costs Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin "COÛTS" tab to the Wally dashboard showing OpenAI spending with KPIs, daily graph, breakdowns by model/purpose/user, and configurable alert threshold with badge.

**Architecture:** Add `user_id` column to `cost_log`, propagate through `OpenAIClient.complete()` to all callers, add new DB aggregation methods, create `costs.py` route file, extend frontend HTML/JS with canvas graph and polling badge.

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, vanilla JS + Canvas API, pytest + httpx

**Spec:** `docs/superpowers/specs/2026-03-18-dashboard-costs-design.md`

---

### Task 1: Add `cost_alert_threshold` to BotConfig

**Files:**
- Modify: `bot/config.py:9-18` (BotConfig dataclass)
- Modify: `config.yaml:1-11` (add default value)
- Modify: `bot/dashboard/routes/admin.py:56-72` (handle new field in update_config)

- [ ] **Step 1: Add field to BotConfig**

In `bot/config.py`, add `cost_alert_threshold` to the `BotConfig` dataclass:

```python
@dataclass
class BotConfig:
    trigger_names: list[str]
    language_default: str
    context_window_size: int
    context_token_threshold: int
    journal_time: str
    journal_channel_id: Optional[int] = None
    dashboard_token: Optional[str] = None
    prelude_window_size: int = 15
    link_min_confidence: float = 0.75
    cost_alert_threshold: float = 25.0
```

- [ ] **Step 2: Add default to config.yaml**

Add `cost_alert_threshold: 25.0` under the `bot:` section in `config.yaml`.

- [ ] **Step 3: Handle in update_config route**

In `bot/dashboard/routes/admin.py`, inside the `if "bot" in body:` block (after the `trigger_names` handling at line 71), add:

```python
        if "cost_alert_threshold" in d:
            val = float(d["cost_alert_threshold"])
            if val <= 0:
                raise HTTPException(status_code=400, detail="cost_alert_threshold must be > 0")
            cfg.bot.cost_alert_threshold = val
```

- [ ] **Step 4: Run existing tests to verify no regression**

Run: `python -m pytest tests/test_dashboard_routes.py -v`
Expected: all existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/config.py config.yaml bot/dashboard/routes/admin.py
git commit -m "feat(config): add cost_alert_threshold to BotConfig"
```

---

### Task 2: Add `user_id` column to `cost_log` + DB aggregation methods

**Files:**
- Modify: `bot/db/database.py:14-22` (schema) and `bot/db/database.py:112-134` (migration block) and `bot/db/database.py:153-174` (cost methods)
- Test: `tests/test_dashboard_costs.py` (new file — DB method tests via routes in Task 4)

- [ ] **Step 1: Add `user_id` to schema + index**

In `bot/db/database.py`, modify the `cost_log` CREATE TABLE to add the column, and add an index after it:

```sql
CREATE TABLE IF NOT EXISTS cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    purpose TEXT,
    user_id TEXT
);
```

Add after the existing `CREATE INDEX IF NOT EXISTS idx_emotion_history_ts ...` line (line 71):

```sql
CREATE INDEX IF NOT EXISTS idx_cost_log_ts ON cost_log(timestamp);
```

- [ ] **Step 2: Add migration for existing databases**

In the `Database.create()` method, after the existing `memory_users` migration block (line 118-123), add:

```python
        # Migration: ajouter user_id à cost_log si absent
        try:
            await conn.execute("ALTER TABLE cost_log ADD COLUMN user_id TEXT")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass  # colonne déjà présente
        # Migration: index sur cost_log.timestamp
        try:
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_log_ts ON cost_log(timestamp)")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass
```

- [ ] **Step 3: Update `log_cost()` to accept `user_id`**

```python
    async def log_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        purpose: str = "",
        user_id: str | None = None,
    ):
        await self.execute(
            "INSERT INTO cost_log "
            "(timestamp, model, input_tokens, output_tokens, cost_usd, purpose, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), model, input_tokens, output_tokens, cost_usd, purpose, user_id),
        )
```

- [ ] **Step 4: Add `get_daily_costs()` method**

Add after `get_cost_since()` (after line 174):

```python
    async def get_daily_costs(self, since_ts: float, until_ts: float | None = None) -> list[dict]:
        """Coûts agrégés par jour (date ISO, cost_usd total)."""
        end = until_ts or time.time()
        rows = await self.fetch_all(
            "SELECT DATE(timestamp, 'unixepoch', 'localtime') AS date, "
            "SUM(cost_usd) AS cost "
            "FROM cost_log WHERE timestamp >= ? AND timestamp <= ? "
            "GROUP BY date ORDER BY date ASC",
            (since_ts, end),
        )
        return [{"date": r["date"], "cost": round(float(r["cost"]), 6)} for r in rows]
```

- [ ] **Step 5: Add `get_cost_breakdown()` method**

```python
    async def get_cost_breakdown(self, since_ts: float, group_by: str) -> list[dict]:
        """Agrège les coûts par model, purpose, ou user_id.

        group_by doit être 'model', 'purpose', ou 'user_id' (validé par l'appelant).
        """
        allowed = {"model", "purpose", "user_id"}
        if group_by not in allowed:
            raise ValueError(f"group_by must be one of {allowed}")
        rows = await self.fetch_all(
            f"SELECT {group_by} AS grp, SUM(cost_usd) AS total, COUNT(*) AS count "
            f"FROM cost_log WHERE timestamp >= ? "
            f"GROUP BY {group_by} ORDER BY total DESC",
            (since_ts,),
        )
        return [
            {"key": r["grp"], "total": round(float(r["total"]), 6), "count": int(r["count"])}
            for r in rows
        ]
```

- [ ] **Step 6: Add `get_cost_stats()` method**

```python
    async def get_cost_stats(self, since_ts: float) -> dict:
        """Total et nombre d'appels depuis since_ts."""
        row = await self.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS count "
            "FROM cost_log WHERE timestamp >= ?",
            (since_ts,),
        )
        total = float(row["total"]) if row else 0.0
        count = int(row["count"]) if row else 0
        return {"total": round(total, 6), "count": count}
```

- [ ] **Step 7: Run existing tests to verify no regression**

Run: `python -m pytest tests/ -v`
Expected: all 110+ existing tests PASS

- [ ] **Step 8: Commit**

```bash
git add bot/db/database.py
git commit -m "feat(db): add user_id to cost_log + aggregation methods"
```

---

### Task 3: Propagate `user_id` through OpenAI client to callers

**Files:**
- Modify: `bot/core/openai_client.py:61-63` (`_complete_responses_api` signature)
- Modify: `bot/core/openai_client.py:110-117` (`complete` signature)
- Modify: `bot/core/openai_client.py:186-199` (`complete_secondary` signature)
- Modify: `bot/discord/handlers.py:216-218` (pass user_id)
- Modify: `bot/discord/commands/ask.py:51-55` (pass user_id)
- Modify: `bot/twitch/handlers.py:87-91` (pass user_id)
- Modify: `bot/twitch/events.py:44-48` (pass user_id)

- [ ] **Step 1: Add `user_id` param to `_complete_responses_api`**

In `bot/core/openai_client.py`, change the signature at line 61-63:

```python
    async def _complete_responses_api(
        self, model: str, messages: list[dict], purpose: str, user_id: str | None = None
    ) -> str:
```

And update the `log_cost` call inside it (line 74-80) to pass `user_id`:

```python
            await self._db.log_cost(
                model,
                response.usage.input_tokens,
                response.usage.output_tokens,
                cost,
                purpose,
                user_id=user_id,
            )
```

- [ ] **Step 2: Add `user_id` param to `complete()`**

Change the signature at line 110-117:

```python
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        model: Optional[str] = None,
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
    ) -> str:
```

Pass it to `_complete_responses_api` at line 130:

```python
                return await self._complete_responses_api(model, full_messages, purpose, user_id=user_id)
```

And to `log_cost` in the chat completions branch at line 145-146:

```python
                await self._db.log_cost(
                    model, usage.prompt_tokens, usage.completion_tokens, cost, purpose,
                    user_id=user_id,
                )
```

- [ ] **Step 3: Add `user_id` param to `complete_secondary()`**

Change the signature at line 186-199:

```python
    async def complete_secondary(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "summary",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
    ) -> str:
        return await self.complete(
            system_prompt,
            messages,
            model=self._config.openai.secondary_model,
            purpose=purpose,
            image_urls=image_urls,
            user_id=user_id,
        )
```

- [ ] **Step 4: Pass user_id in discord/handlers.py**

At line 216-218, change:

```python
            reply = await bot.openai.complete(
                system_prompt, openai_messages, purpose="discord_response",
                image_urls=image_urls or None,
                user_id=f"discord:{message.author.id}",
            )
```

- [ ] **Step 5: Pass user_id in discord/commands/ask.py**

At line 51-55, change:

```python
            reply = await self.bot.openai.complete(
                system_prompt,
                [{"role": "user", "content": content}],
                purpose="discord_ask",
                user_id=f"discord:{interaction.user.id}",
            )
```

- [ ] **Step 6: Pass user_id in twitch/handlers.py**

At line 87-91, change:

```python
        reply = await bot.openai.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_response",
            user_id=f"twitch:{author}",
        )
```

- [ ] **Step 7: Pass user_id in twitch/events.py**

At line 44-48 — events don't always have a user. Pass when available:

```python
        event_user_id = f"twitch:{kwargs.get('username', '')}" if kwargs.get('username') else None
        reply = await bot.openai.complete(
            system,
            [{"role": "user", "content": f"Réagis à cet événement Twitch : {formatted}"}],
            purpose="twitch_event",
            user_id=event_user_id,
        )
```

- [ ] **Step 8: Run existing tests**

Run: `python -m pytest tests/ -v`
Expected: all existing tests PASS (user_id is optional everywhere)

- [ ] **Step 9: Commit**

```bash
git add bot/core/openai_client.py bot/discord/handlers.py bot/discord/commands/ask.py bot/twitch/handlers.py bot/twitch/events.py
git commit -m "feat(openai): propagate user_id through complete() to cost_log"
```

---

### Task 4: Create costs API routes + tests (TDD)

**Files:**
- Create: `bot/dashboard/routes/costs.py`
- Modify: `bot/dashboard/app.py:66,79` (register router)
- Create: `tests/test_dashboard_costs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_dashboard_costs.py`:

```python
"""Tests des routes API coûts du dashboard."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import (
    BotConfig, OpenAIConfig, DiscordConfig, TwitchConfig,
    EmotionDecayConfig, TwitchEventConfig,
)

HEADERS = {"Authorization": "Bearer testtoken"}


def _make_config():
    cfg = MagicMock()
    cfg.bot = BotConfig(
        trigger_names=["wally"],
        language_default="fr",
        context_window_size=20,
        context_token_threshold=3000,
        journal_time="03:00",
        dashboard_token="testtoken",
        cost_alert_threshold=25.0,
    )
    cfg.openai = OpenAIConfig(
        primary_model="gpt-4o", secondary_model="gpt-4o-mini",
        temperature=0.8, max_tokens=1000,
    )
    cfg.discord = DiscordConfig(anger_trigger_threshold=3, timeout_minutes=10)
    cfg.twitch = TwitchConfig(guest_channels=[], cooldown_seconds=10)
    cfg.emotions = {
        "anger": EmotionDecayConfig(decay_lambda=0.1),
        "joy": EmotionDecayConfig(decay_lambda=0.05),
        "sadness": EmotionDecayConfig(decay_lambda=0.08),
        "curiosity": EmotionDecayConfig(decay_lambda=0.1),
        "boredom": EmotionDecayConfig(decay_lambda=0.15),
    }
    cfg.twitch_events = {"follow": TwitchEventConfig(active=True, message="Hey {username}!")}
    cfg.save = MagicMock()
    return cfg


def _make_state(**overrides) -> AppState:
    emotion = MagicMock()
    emotion.get_state.return_value = {
        "anger": 0.1, "joy": 0.7, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0
    }
    db = MagicMock()
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.insert_emotion_snapshot = AsyncMock()
    state = AppState(
        config=_make_config(),
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


# ── Auth ──────────────────────────────────────────────────────────────────────

async def test_costs_auth_required(client):
    """Tous les endpoints costs refusent sans token."""
    for path in ["/api/admin/costs/summary", "/api/admin/costs/daily",
                 "/api/admin/costs/breakdown/model", "/api/admin/costs/breakdown/purpose",
                 "/api/admin/costs/top-users", "/api/admin/costs/alert"]:
        r = await client.get(path)
        assert r.status_code == 401, f"{path} should require auth"


# ── Summary ───────────────────────────────────────────────────────────────────

async def test_costs_summary(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(side_effect=[
        {"total": 12.50, "count": 100},   # current period
        {"total": 15.00, "count": 120},   # previous period
    ])
    r = await client.get("/api/admin/costs/summary", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 12.50
    assert data["msg_count"] == 100
    assert data["avg_per_msg"] == 0.125
    assert data["prev_total"] == 15.00
    assert data["pct_change"] == pytest.approx(-16.67, abs=0.01)


async def test_costs_summary_empty_db(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 0.0, "count": 0})
    r = await client.get("/api/admin/costs/summary", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0.0
    assert data["avg_per_msg"] == 0.0
    assert data["pct_change"] == 0.0


# ── Daily ─────────────────────────────────────────────────────────────────────

async def test_costs_daily(client):
    db = client._transport.app.state.wally.db
    db.get_daily_costs = AsyncMock(side_effect=[
        [{"date": "2026-03-17", "cost": 0.5}, {"date": "2026-03-18", "cost": 0.8}],
        [{"date": "2026-02-17", "cost": 0.3}, {"date": "2026-02-18", "cost": 0.6}],
    ])
    r = await client.get("/api/admin/costs/daily?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data["current"]) == 2
    assert len(data["previous"]) == 2


# ── Breakdown model ───────────────────────────────────────────────────────────

async def test_costs_breakdown_model(client):
    db = client._transport.app.state.wally.db
    db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "gpt-4o", "total": 8.20, "count": 50},
        {"key": "gpt-4o-mini", "total": 3.15, "count": 80},
    ])
    r = await client.get("/api/admin/costs/breakdown/model?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["model"] == "gpt-4o"
    assert data[0]["total"] == 8.20


# ── Breakdown purpose ────────────────────────────────────────────────────────

async def test_costs_breakdown_purpose(client):
    db = client._transport.app.state.wally.db
    db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "discord_response", "total": 5.0, "count": 40},
        {"key": "discord_ask", "total": 2.0, "count": 15},
        {"key": "twitch_response", "total": 0.4, "count": 5},
        {"key": "session_analysis", "total": 2.0, "count": 20},
        {"key": "emotion_analysis", "total": 1.2, "count": 30},
        {"key": "daily_journal", "total": 1.0, "count": 1},
        {"key": "memory_consolidation", "total": 0.5, "count": 5},
        {"key": "unknown_purpose", "total": 0.1, "count": 1},
    ])
    r = await client.get("/api/admin/costs/breakdown/purpose?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    categories = {d["category"]: d["total"] for d in data}
    assert "Réponses" in categories
    assert "Analyse" in categories
    assert "Journal" in categories
    assert "Mémoire" in categories
    assert "Autre" in categories
    assert categories["Réponses"] == pytest.approx(7.4)


# ── Top users ─────────────────────────────────────────────────────────────────

async def test_costs_top_users(client):
    db = client._transport.app.state.wally.db
    db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "discord:123", "total": 4.20, "count": 30},
        {"key": "twitch:luna", "total": 3.10, "count": 25},
        {"key": None, "total": 1.50, "count": 15},
    ])
    db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:123", "username": "Azrael", "platform": "discord",
         "last_updated": 0, "trust_score": 0.5},
    ])
    r = await client.get("/api/admin/costs/top-users?days=30&limit=10", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    assert data[0]["username"] == "Azrael"
    assert data[2]["username"] == "Système"


# ── Alert ─────────────────────────────────────────────────────────────────────

async def test_costs_alert_ok(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 10.0, "count": 50})
    r = await client.get("/api/admin/costs/alert", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["threshold"] == 25.0
    assert data["current_total"] == 10.0
    assert data["pct_used"] == 40.0
    assert data["status"] == "ok"


async def test_costs_alert_warning(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 18.0, "count": 80})
    r = await client.get("/api/admin/costs/alert", headers=HEADERS)
    data = r.json()
    assert data["status"] == "warning"


async def test_costs_alert_critical(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 22.0, "count": 90})
    r = await client.get("/api/admin/costs/alert", headers=HEADERS)
    data = r.json()
    assert data["status"] == "critical"


async def test_costs_avg_no_division_by_zero(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 0.0, "count": 0})
    r = await client.get("/api/admin/costs/summary", headers=HEADERS)
    data = r.json()
    assert data["avg_per_msg"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dashboard_costs.py -v`
Expected: FAIL — `costs` module not found / routes not registered

- [ ] **Step 3: Create `bot/dashboard/routes/costs.py`**

```python
# bot/dashboard/routes/costs.py
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Request

router = APIRouter()

PURPOSE_CATEGORIES = {
    "discord_response": "Réponses",
    "discord_ask": "Réponses",
    "twitch_response": "Réponses",
    "twitch_event": "Réponses",
    "session_analysis": "Analyse",
    "emotion_analysis": "Analyse",
    "memory_consolidation": "Mémoire",
    "context_summary": "Mémoire",
    "context_summary_final": "Mémoire",
    "daily_journal": "Journal",
    "journal_chunk_summary": "Journal",
    "journal_final_summary": "Journal",
}


def _since_ts(days: int) -> float:
    """Timestamp Unix il y a N jours."""
    return time.time() - days * 86400


@router.get("/costs/summary")
async def costs_summary(request: Request) -> dict:
    db = request.app.state.wally.db
    now = time.time()
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

    current = await db.get_cost_stats(month_start)
    # Mois précédent : même durée en arrière
    prev_start = (datetime.now().replace(day=1) - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    prev = await db.get_cost_stats(prev_start)

    total = current["total"]
    count = current["count"]
    avg = round(total / count, 6) if count > 0 else 0.0
    prev_total = prev["total"]
    pct_change = round((total - prev_total) / prev_total * 100, 2) if prev_total > 0 else 0.0

    return {
        "total": total,
        "avg_per_msg": avg,
        "msg_count": count,
        "prev_total": prev_total,
        "pct_change": pct_change,
    }


@router.get("/costs/daily")
async def costs_daily(request: Request, days: int = 30) -> dict:
    db = request.app.state.wally.db
    now = time.time()
    current = await db.get_daily_costs(_since_ts(days))
    previous = await db.get_daily_costs(_since_ts(days * 2), _since_ts(days))
    return {"current": current, "previous": previous}


@router.get("/costs/breakdown/model")
async def costs_breakdown_model(request: Request, days: int = 30) -> list:
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "model")
    return [{"model": r["key"], "total": r["total"], "count": r["count"]} for r in rows]


@router.get("/costs/breakdown/purpose")
async def costs_breakdown_purpose(request: Request, days: int = 30) -> list:
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "purpose")
    # Regroup into categories
    categories: dict[str, dict] = {}
    for r in rows:
        cat = PURPOSE_CATEGORIES.get(r["key"] or "", "Autre")
        if cat not in categories:
            categories[cat] = {"category": cat, "total": 0.0, "count": 0}
        categories[cat]["total"] = round(categories[cat]["total"] + r["total"], 6)
        categories[cat]["count"] += r["count"]
    return sorted(categories.values(), key=lambda x: x["total"], reverse=True)


@router.get("/costs/top-users")
async def costs_top_users(request: Request, days: int = 30, limit: int = 10) -> list:
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "user_id")

    # Resolve usernames via memory_users
    all_users = await db.list_memory_users()
    username_map = {u["user_id"]: u["username"] for u in all_users if u.get("username")}

    result = []
    for r in rows[:limit]:
        uid = r["key"]
        if uid is None:
            username = "Système"
        else:
            username = username_map.get(uid) or uid
        result.append({
            "user_id": uid,
            "username": username,
            "total": r["total"],
            "count": r["count"],
        })
    return result


@router.get("/costs/alert")
async def costs_alert(request: Request) -> dict:
    state = request.app.state.wally
    threshold = state.config.bot.cost_alert_threshold
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    stats = await state.db.get_cost_stats(month_start)

    current = stats["total"]
    pct = round(current / threshold * 100, 1) if threshold > 0 else 0.0
    if pct >= 80:
        status = "critical"
    elif pct >= 60:
        status = "warning"
    else:
        status = "ok"

    return {
        "threshold": threshold,
        "current_total": current,
        "pct_used": pct,
        "status": status,
    }
```

- [ ] **Step 4: Register router in `app.py`**

In `bot/dashboard/app.py`, line 66, add `costs` to the import:

```python
    from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, costs
```

Line 79 (after the `links` router), add:

```python
    app.include_router(costs.router, prefix="/api/admin")
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_dashboard_costs.py -v`
Expected: all tests PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add bot/dashboard/routes/costs.py bot/dashboard/app.py tests/test_dashboard_costs.py
git commit -m "feat(dashboard): costs API routes with TDD tests"
```

---

### Task 5: Frontend — COÛTS tab HTML + JS

**Files:**
- Modify: `bot/dashboard/static/index.html` (add tab + markup)
- Modify: `bot/dashboard/static/app.js` (add fetch logic, canvas graph, badge polling)

- [ ] **Step 1: Add tab button in `index.html`**

Find the tab bar in `index.html`. The "COÛTS" tab was previously disabled. Replace the disabled tab with an active one. Add the tab content section with the KPI/graph/breakdown layout per the spec (Layout A):

- 4 KPI cards in a row
- Full-width canvas graph with `7J | 30J | 90J` selector
- 3-column grid: model breakdown, purpose breakdown, top users
- Alert bar below

The tab button should have `id="tab-costs"` and include a badge span `<span id="costs-badge" class="tab-badge" style="display:none"></span>`.

- [ ] **Step 2: Add JS logic in `app.js`**

Add a `loadCosts()` function that:
1. Fetches `/api/admin/costs/summary`, `/api/admin/costs/daily?days=N`, `/api/admin/costs/breakdown/model?days=N`, `/api/admin/costs/breakdown/purpose?days=N`, `/api/admin/costs/top-users?days=N`, `/api/admin/costs/alert` in parallel
2. Populates the 4 KPI cards with values from summary
3. Draws the daily cost graph on a canvas element (same pattern as the emotion graph — line chart with axes, ticks, and legend)
4. Draws a dashed line for the previous period data
5. Populates the 3 breakdown columns as sorted lists with proportional bars
6. Updates the alert bar color and percentage
7. Shows/hides the badge on the tab button

Add a `pollCostsBadge()` function that fetches `/api/admin/costs/alert` and shows/hides the badge. Call it on page load and on every tab switch.

Add range selector buttons (`7J`, `30J`, `90J`) that re-trigger `loadCosts()` with the selected range.

- [ ] **Step 3: Test manually in browser**

Open `http://localhost:8080` in a browser. Verify:
- The COÛTS tab appears in the admin section
- Clicking it loads data (may show zeros if no cost_log entries)
- Graph renders without errors
- Badge appears when alert is critical
- Range selector buttons switch the graph period

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/app.js
git commit -m "feat(dashboard): costs tab frontend with canvas graph and alert badge"
```

---

### Task 6: Integration verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 2: Verify no import/startup errors**

Run: `python -c "from bot.dashboard.routes.costs import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Final commit (if any fixups needed)**

```bash
git add -A
git commit -m "fix: costs tab integration fixups"
```
