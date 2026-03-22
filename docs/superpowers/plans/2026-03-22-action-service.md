# ActionService Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the LLM to create, cancel, and list scheduled tasks via tool calling, with role-based ACL, SQLite persistence, and dashboard management.

**Architecture:** 3 services (ActionRegistry, ActionScheduler, ActionExecutor) + 1 facade (ActionService) in `bot/core/actions/`. Shared `AsyncIOScheduler` singleton with `DailyJournal`. Tool integration follows the existing `WebSearchService`/`ApexLegendsService` pattern in handlers.

**Tech Stack:** Python asyncio, aiosqlite, apscheduler (AsyncIOScheduler), FastAPI, loguru

**Spec:** `docs/superpowers/specs/2026-03-22-action-service-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `bot/core/actions/__init__.py` | Public exports: `ActionService`, `ActionRegistry`, `ActionScheduler`, `ActionExecutor`, `ActionDefinition` |
| `bot/core/actions/registry.py` | Action catalog + role-based permissions (DB-backed) |
| `bot/core/actions/scheduler.py` | SQLite persistence + apscheduler job management |
| `bot/core/actions/executor.py` | Action routing + message delivery to Discord/Twitch/Web |
| `bot/core/actions/service.py` | LLM facade: tool definitions, validation, rate limiting |
| `bot/dashboard/routes/actions.py` | REST API: tasks CRUD, permissions management |
| `tests/test_action_registry.py` | Registry + ACL tests |
| `tests/test_action_scheduler.py` | Scheduler persistence + reload tests |
| `tests/test_action_executor.py` | Executor routing + delivery tests |
| `tests/test_action_service.py` | Facade: tool defs, validation, rate limit, search cancel |
| `tests/test_action_dashboard.py` | Dashboard API endpoint tests |

### Modified files
| File | Changes |
|------|---------|
| `bot/db/database.py` | Add `action_tasks` + `action_permissions` tables to SCHEMA, add helper methods |
| `bot/main.py` | Shared scheduler singleton, ActionService DI wiring, boot sequence |
| `bot/core/journal.py` | Accept external scheduler instead of creating its own |
| `bot/discord/handlers.py` | Add action tools to tool collection + executor routing + role resolution |
| `bot/twitch/handlers.py` | Same as Discord handlers |
| `bot/dashboard/state.py` | Add `action_service` field to `AppState` |
| `bot/dashboard/app.py` | Register actions router |
| `bot/dashboard/static/app.js` | Add "Actions" tab with tasks + permissions views |
| `bot/dashboard/static/style.css` | Glassmorphism styles for action cards + status badges |

---

## Task 1: Database Schema — `action_tasks` and `action_permissions`

**Files:**
- Modify: `bot/db/database.py` (SCHEMA at line 13, migrations at line 249, new helpers after line 299)
- Test: `tests/test_action_registry.py` (new)

- [ ] **Step 1: Add tables to SCHEMA string**

In `bot/db/database.py`, append these two tables at the end of the `SCHEMA` string (before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS action_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    creator_id TEXT NOT NULL,
    creator_platform TEXT NOT NULL,
    target_channel TEXT,
    target_platform TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    schedule_type TEXT NOT NULL,
    schedule_spec TEXT NOT NULL DEFAULT '{}',
    max_executions INTEGER,
    execution_count INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    next_run_at TEXT,
    last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS action_permissions (
    action_type TEXT PRIMARY KEY,
    min_role_discord TEXT NOT NULL DEFAULT 'admin',
    min_role_twitch TEXT NOT NULL DEFAULT 'admin',
    enabled INTEGER NOT NULL DEFAULT 1
);
```

- [ ] **Step 2: Add DB helper methods**

Add these methods to the `Database` class after the existing helpers:

```python
# --- Action Tasks ---

async def insert_action_task(
    self,
    action_type: str,
    description: str,
    creator_id: str,
    creator_platform: str,
    target_channel: str | None,
    target_platform: str | None,
    payload: str,
    schedule_type: str,
    schedule_spec: str,
    max_executions: int | None,
    status: str,
    created_at: str,
    updated_at: str,
    next_run_at: str | None,
) -> int:
    cursor = await self._conn.execute(
        """INSERT INTO action_tasks
           (action_type, description, creator_id, creator_platform,
            target_channel, target_platform, payload,
            schedule_type, schedule_spec, max_executions,
            status, created_at, updated_at, next_run_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            action_type, description, creator_id, creator_platform,
            target_channel, target_platform, payload,
            schedule_type, schedule_spec, max_executions,
            status, created_at, updated_at, next_run_at,
        ),
    )
    await self._conn.commit()
    return cursor.lastrowid

async def get_action_task(self, task_id: int) -> dict | None:
    return await self.fetch_one(
        "SELECT * FROM action_tasks WHERE id = ?", (task_id,)
    )

async def list_action_tasks(
    self,
    status: str | None = None,
    creator_id: str | None = None,
    creator_platform: str | None = None,
    action_type: str | None = None,
) -> list[dict]:
    query = "SELECT * FROM action_tasks WHERE 1=1"
    params: list = []
    if status and status != "all":
        query += " AND status = ?"
        params.append(status)
    if creator_id:
        query += " AND creator_id = ? AND creator_platform = ?"
        params.append(creator_id)
        params.append(creator_platform or "")
    if action_type:
        query += " AND action_type = ?"
        params.append(action_type)
    query += " ORDER BY created_at DESC"
    return await self.fetch_all(query, tuple(params))

async def update_action_task(self, task_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [task_id]
    await self.execute(
        f"UPDATE action_tasks SET {sets} WHERE id = ?", tuple(vals)
    )

async def search_action_tasks(
    self, query: str, creator_id: str, creator_platform: str
) -> list[dict]:
    return await self.fetch_all(
        """SELECT * FROM action_tasks
           WHERE description LIKE ? AND creator_id = ? AND creator_platform = ?
           AND status IN ('active', 'paused')
           ORDER BY created_at DESC""",
        (f"%{query}%", creator_id, creator_platform),
    )

async def count_user_action_tasks(
    self, creator_id: str, creator_platform: str
) -> int:
    row = await self.fetch_one(
        """SELECT COUNT(*) as cnt FROM action_tasks
           WHERE creator_id = ? AND creator_platform = ?
           AND status IN ('active', 'paused')""",
        (creator_id, creator_platform),
    )
    return row["cnt"] if row else 0

async def get_active_action_tasks(self) -> list[dict]:
    return await self.fetch_all(
        "SELECT * FROM action_tasks WHERE status = 'active' ORDER BY next_run_at"
    )

# --- Action Permissions ---

async def get_action_permission(self, action_type: str) -> dict | None:
    return await self.fetch_one(
        "SELECT * FROM action_permissions WHERE action_type = ?",
        (action_type,),
    )

async def list_action_permissions(self) -> list[dict]:
    return await self.fetch_all("SELECT * FROM action_permissions ORDER BY action_type")

async def upsert_action_permission(
    self, action_type: str, min_role_discord: str = "admin",
    min_role_twitch: str = "admin", enabled: int = 1
) -> None:
    await self.execute(
        """INSERT INTO action_permissions (action_type, min_role_discord, min_role_twitch, enabled)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(action_type) DO UPDATE SET
             min_role_discord = excluded.min_role_discord,
             min_role_twitch = excluded.min_role_twitch,
             enabled = excluded.enabled""",
        (action_type, min_role_discord, min_role_twitch, enabled),
    )
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `pytest tests/ -x -q`
Expected: All existing tests pass (no schema conflicts).

- [ ] **Step 4: Commit**

```bash
git add bot/db/database.py
git commit -m "feat(db): add action_tasks and action_permissions tables with helpers"
```

---

## Task 2: ActionRegistry — Action Catalog + Permissions

**Files:**
- Create: `bot/core/actions/__init__.py`
- Create: `bot/core/actions/registry.py`
- Test: `tests/test_action_registry.py`

- [ ] **Step 1: Write failing tests for ActionRegistry**

Create `tests/test_action_registry.py`:

```python
"""Tests for ActionRegistry — action catalog and role-based permissions."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.actions.registry import ActionRegistry, ActionDefinition


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.list_action_permissions = AsyncMock(return_value=[])
    db.upsert_action_permission = AsyncMock()
    db.get_action_permission = AsyncMock(return_value=None)
    return db


def _make_definition(name: str = "reminder", desc: str = "Send a reminder") -> ActionDefinition:
    return ActionDefinition(
        name=name,
        description=desc,
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        handler=AsyncMock(return_value="done"),
    )


@pytest.mark.asyncio
async def test_register_and_get(mock_db):
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    defn = _make_definition()
    await reg.register("reminder", defn)
    assert reg.get("reminder") is defn
    assert reg.get("nonexistent") is None


@pytest.mark.asyncio
async def test_register_creates_default_permission(mock_db):
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    mock_db.upsert_action_permission.assert_called_once_with(
        "reminder", min_role_discord="admin", min_role_twitch="admin", enabled=1
    )


@pytest.mark.asyncio
async def test_check_permission_discord_hierarchy(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "moderator", "min_role_twitch": "admin", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())

    # admin >= moderator → allowed
    assert reg.check_permission("reminder", "discord", ["admin"]) is True
    # moderator >= moderator → allowed
    assert reg.check_permission("reminder", "discord", ["moderator"]) is True
    # subscriber < moderator → denied
    assert reg.check_permission("reminder", "discord", ["subscriber"]) is False
    # everyone < moderator → denied
    assert reg.check_permission("reminder", "discord", ["everyone"]) is False


@pytest.mark.asyncio
async def test_check_permission_twitch_hierarchy(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "admin", "min_role_twitch": "vip", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())

    assert reg.check_permission("reminder", "twitch", ["moderator"]) is True
    assert reg.check_permission("reminder", "twitch", ["vip"]) is True
    assert reg.check_permission("reminder", "twitch", ["subscriber"]) is False


@pytest.mark.asyncio
async def test_check_permission_disabled_action(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "everyone", "min_role_twitch": "everyone", "enabled": 0}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())

    assert reg.check_permission("reminder", "discord", ["admin"]) is False


@pytest.mark.asyncio
async def test_check_permission_unknown_action(mock_db):
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    assert reg.check_permission("nonexistent", "discord", ["admin"]) is False


@pytest.mark.asyncio
async def test_list_available(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "everyone", "min_role_twitch": "admin", "enabled": 1},
        {"action_type": "web_search", "min_role_discord": "moderator", "min_role_twitch": "admin", "enabled": 1},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition("reminder"))
    await reg.register("web_search", _make_definition("web_search", "Search the web"))

    available = reg.list_available("discord", ["subscriber"])
    assert len(available) == 1
    assert available[0].name == "reminder"

    available_mod = reg.list_available("discord", ["moderator"])
    assert len(available_mod) == 2


@pytest.mark.asyncio
async def test_update_permission(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "admin", "min_role_twitch": "admin", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())

    await reg.update_permission("reminder", "discord", "everyone")
    assert reg.check_permission("reminder", "discord", ["everyone"]) is True


@pytest.mark.asyncio
async def test_set_enabled(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "everyone", "min_role_twitch": "everyone", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())

    assert reg.check_permission("reminder", "discord", ["everyone"]) is True
    await reg.set_enabled("reminder", False)
    assert reg.check_permission("reminder", "discord", ["everyone"]) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_action_registry.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `bot/core/actions/__init__.py`**

```python
from bot.core.actions.registry import ActionDefinition, ActionRegistry

__all__ = ["ActionDefinition", "ActionRegistry"]
```

(Will be extended in later tasks as more classes are added.)

- [ ] **Step 4: Implement `bot/core/actions/registry.py`**

```python
"""ActionRegistry — action catalog and role-based permission management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from loguru import logger


DISCORD_ROLE_HIERARCHY = ["everyone", "subscriber", "moderator", "admin"]
TWITCH_ROLE_HIERARCHY = ["everyone", "subscriber", "vip", "moderator", "admin"]


def _role_level(role: str, hierarchy: list[str]) -> int:
    try:
        return hierarchy.index(role)
    except ValueError:
        return -1


@dataclass
class ActionDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Coroutine]


@dataclass
class _PermissionEntry:
    min_role_discord: str = "admin"
    min_role_twitch: str = "admin"
    enabled: bool = True


class ActionRegistry:
    def __init__(self, db) -> None:
        self._db = db
        self._actions: dict[str, ActionDefinition] = {}
        self._permissions: dict[str, _PermissionEntry] = {}

    async def load_permissions(self) -> None:
        rows = await self._db.list_action_permissions()
        for row in rows:
            self._permissions[row["action_type"]] = _PermissionEntry(
                min_role_discord=row["min_role_discord"],
                min_role_twitch=row["min_role_twitch"],
                enabled=bool(row["enabled"]),
            )
        logger.info("Loaded {} action permissions", len(self._permissions))

    async def register(self, action_type: str, definition: ActionDefinition) -> None:
        self._actions[action_type] = definition
        if action_type not in self._permissions:
            self._permissions[action_type] = _PermissionEntry()
            await self._db.upsert_action_permission(
                action_type, min_role_discord="admin", min_role_twitch="admin", enabled=1
            )
            logger.info("Registered action '{}' with default admin permissions", action_type)

    def get(self, action_type: str) -> ActionDefinition | None:
        return self._actions.get(action_type)

    def check_permission(
        self, action_type: str, platform: str, user_roles: list[str]
    ) -> bool:
        perm = self._permissions.get(action_type)
        if perm is None:
            return False
        if not perm.enabled:
            return False

        hierarchy = (
            DISCORD_ROLE_HIERARCHY if platform == "discord" else TWITCH_ROLE_HIERARCHY
        )
        min_role = perm.min_role_discord if platform == "discord" else perm.min_role_twitch
        min_level = _role_level(min_role, hierarchy)

        user_max_level = max(
            (_role_level(r, hierarchy) for r in user_roles), default=-1
        )
        return user_max_level >= min_level

    def list_available(
        self, platform: str, user_roles: list[str]
    ) -> list[ActionDefinition]:
        return [
            defn
            for action_type, defn in self._actions.items()
            if self.check_permission(action_type, platform, user_roles)
        ]

    async def update_permission(
        self, action_type: str, platform: str, min_role: str
    ) -> None:
        perm = self._permissions.get(action_type)
        if perm is None:
            return
        if platform == "discord":
            perm.min_role_discord = min_role
        else:
            perm.min_role_twitch = min_role
        await self._db.upsert_action_permission(
            action_type,
            min_role_discord=perm.min_role_discord,
            min_role_twitch=perm.min_role_twitch,
            enabled=int(perm.enabled),
        )

    async def set_enabled(self, action_type: str, enabled: bool) -> None:
        perm = self._permissions.get(action_type)
        if perm is None:
            return
        perm.enabled = enabled
        await self._db.upsert_action_permission(
            action_type,
            min_role_discord=perm.min_role_discord,
            min_role_twitch=perm.min_role_twitch,
            enabled=int(enabled),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_action_registry.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/core/actions/__init__.py bot/core/actions/registry.py tests/test_action_registry.py
git commit -m "feat(actions): add ActionRegistry with role-based permissions"
```

---

## Task 3: ActionScheduler — Persistence + Job Management

**Files:**
- Create: `bot/core/actions/scheduler.py`
- Modify: `bot/core/actions/__init__.py` (add export)
- Test: `tests/test_action_scheduler.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_action_scheduler.py`:

```python
"""Tests for ActionScheduler — SQLite persistence + apscheduler orchestration."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from bot.core.actions.scheduler import ActionScheduler

TZ = ZoneInfo("Europe/Paris")


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.insert_action_task = AsyncMock(return_value=1)
    db.update_action_task = AsyncMock()
    db.get_action_task = AsyncMock(return_value=None)
    db.get_active_action_tasks = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mock_executor():
    return AsyncMock()


@pytest.fixture
def mock_apscheduler():
    sched = MagicMock()
    sched.add_job = MagicMock(return_value=MagicMock(id="job_1"))
    sched.remove_job = MagicMock()
    sched.get_job = MagicMock(return_value=None)
    return sched


@pytest.fixture
def scheduler(mock_db, mock_executor, mock_apscheduler):
    return ActionScheduler(mock_db, mock_executor, mock_apscheduler)


@pytest.mark.asyncio
async def test_schedule_once_task(scheduler, mock_db):
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    task_id = await scheduler.schedule(
        action_type="reminder",
        description="Buy bread",
        creator_id="123",
        creator_platform="discord",
        target_channel="456",
        target_platform="discord",
        payload='{"message": "Buy bread!"}',
        schedule_type="once",
        schedule_spec=f'{{"run_at": "{run_at}"}}',
        max_executions=1,
    )
    assert task_id == 1
    mock_db.insert_action_task.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_interval_task(scheduler, mock_db, mock_apscheduler):
    task_id = await scheduler.schedule(
        action_type="reminder",
        description="Drink water",
        creator_id="123",
        creator_platform="discord",
        target_channel="456",
        target_platform="discord",
        payload='{"message": "Drink water!"}',
        schedule_type="interval",
        schedule_spec='{"minutes": 30}',
        max_executions=None,
    )
    assert task_id == 1
    mock_apscheduler.add_job.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_task(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {"id": 1, "status": "active"}
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler.cancel(1)
    mock_db.update_action_task.assert_called_once()
    call_kwargs = mock_db.update_action_task.call_args
    assert call_kwargs[1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_pause_and_resume(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {"id": 1, "status": "active"}
    mock_apscheduler.get_job.return_value = MagicMock()

    await scheduler.pause(1)
    assert mock_db.update_action_task.call_args[1]["status"] == "paused"

    mock_db.get_action_task.return_value = {"id": 1, "status": "paused",
        "schedule_type": "interval", "schedule_spec": '{"minutes": 30}',
        "action_type": "reminder", "payload": '{}',
        "target_channel": "456", "target_platform": "discord",
        "creator_id": "123", "creator_platform": "discord",
        "description": "test", "max_executions": None,
        "execution_count": 0, "consecutive_failures": 0,
        "last_error": None, "created_at": "", "updated_at": "",
        "next_run_at": None, "last_run_at": None}
    await scheduler.resume(1)
    assert mock_db.update_action_task.call_args[1]["status"] == "active"


@pytest.mark.asyncio
async def test_reload_marks_missed_once_tasks(scheduler, mock_db):
    past_time = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
    mock_db.get_active_action_tasks.return_value = [
        {
            "id": 1, "schedule_type": "once", "next_run_at": past_time,
            "status": "active", "action_type": "reminder",
            "schedule_spec": f'{{"run_at": "{past_time}"}}',
            "payload": '{}', "target_channel": "456",
            "target_platform": "discord", "creator_id": "123",
            "creator_platform": "discord", "description": "test",
            "max_executions": 1, "execution_count": 0,
            "consecutive_failures": 0, "last_error": None,
            "created_at": "", "updated_at": "", "last_run_at": None,
        },
    ]
    await scheduler.reload_all()
    mock_db.update_action_task.assert_called_once()
    assert mock_db.update_action_task.call_args[1]["status"] == "missed"


@pytest.mark.asyncio
async def test_reload_reschedules_recurring_tasks(scheduler, mock_db, mock_apscheduler):
    past_time = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
    mock_db.get_active_action_tasks.return_value = [
        {
            "id": 2, "schedule_type": "interval", "next_run_at": past_time,
            "status": "active", "action_type": "reminder",
            "schedule_spec": '{"minutes": 30}',
            "payload": '{}', "target_channel": "456",
            "target_platform": "discord", "creator_id": "123",
            "creator_platform": "discord", "description": "test",
            "max_executions": None, "execution_count": 5,
            "consecutive_failures": 0, "last_error": None,
            "created_at": "", "updated_at": "", "last_run_at": None,
        },
    ]
    await scheduler.reload_all()
    # Should reschedule, NOT mark as missed
    mock_apscheduler.add_job.assert_called_once()
    # Should NOT update status to missed
    for call in mock_db.update_action_task.call_args_list:
        assert call[1].get("status") != "missed"


@pytest.mark.asyncio
async def test_on_job_complete_increments_count(scheduler, mock_db):
    mock_db.get_action_task.return_value = {
        "id": 1, "execution_count": 2, "max_executions": 10,
        "consecutive_failures": 0, "schedule_type": "interval",
        "schedule_spec": '{"minutes": 30}', "status": "active",
    }
    await scheduler._on_job_executed(1, "Reminder sent!")
    call_kwargs = mock_db.update_action_task.call_args[1]
    assert call_kwargs["execution_count"] == 3
    assert call_kwargs["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_on_job_complete_auto_completes_at_max(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {
        "id": 1, "execution_count": 9, "max_executions": 10,
        "consecutive_failures": 0, "schedule_type": "interval",
        "schedule_spec": '{"minutes": 30}', "status": "active",
    }
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler._on_job_executed(1, "Done")
    call_kwargs = mock_db.update_action_task.call_args[1]
    assert call_kwargs["status"] == "completed"


@pytest.mark.asyncio
async def test_on_job_failure_once_task_marks_missed(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {
        "id": 1, "execution_count": 0, "max_executions": 1,
        "consecutive_failures": 0, "schedule_type": "once",
        "schedule_spec": '{"run_at": "2026-03-23T18:00:00"}', "status": "active",
    }
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler._on_job_failed(1, "API down")
    call_kwargs = mock_db.update_action_task.call_args[1]
    assert call_kwargs["status"] == "missed"


@pytest.mark.asyncio
async def test_on_job_failure_auto_pauses_after_3(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {
        "id": 1, "execution_count": 5, "max_executions": None,
        "consecutive_failures": 2, "schedule_type": "interval",
        "schedule_spec": '{"minutes": 30}', "status": "active",
    }
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler._on_job_failed(1, "Connection refused")
    call_kwargs = mock_db.update_action_task.call_args[1]
    assert call_kwargs["status"] == "paused"
    assert call_kwargs["consecutive_failures"] == 3
    assert "Connection refused" in call_kwargs["last_error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_action_scheduler.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `bot/core/actions/scheduler.py`**

```python
"""ActionScheduler — SQLite persistence + apscheduler job management."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

TZ = ZoneInfo("Europe/Paris")


class ActionScheduler:
    def __init__(self, db, executor, apscheduler) -> None:
        self._db = db
        self._executor = executor
        self._scheduler = apscheduler

    async def schedule(
        self,
        action_type: str,
        description: str,
        creator_id: str,
        creator_platform: str,
        target_channel: str | None,
        target_platform: str | None,
        payload: str,
        schedule_type: str,
        schedule_spec: str,
        max_executions: int | None,
    ) -> int:
        now = datetime.now(TZ).isoformat()
        spec = json.loads(schedule_spec)
        next_run = self._compute_next_run(schedule_type, spec)

        task_id = await self._db.insert_action_task(
            action_type=action_type,
            description=description,
            creator_id=creator_id,
            creator_platform=creator_platform,
            target_channel=target_channel,
            target_platform=target_platform,
            payload=payload,
            schedule_type=schedule_type,
            schedule_spec=schedule_spec,
            max_executions=max_executions,
            status="active",
            created_at=now,
            updated_at=now,
            next_run_at=next_run,
        )
        self._add_apscheduler_job(task_id, schedule_type, spec)
        logger.info("Scheduled action task {} ({}): {}", task_id, action_type, description)
        return task_id

    async def cancel(self, task_id: int) -> None:
        now = datetime.now(TZ).isoformat()
        self._remove_job(task_id)
        await self._db.update_action_task(task_id, status="cancelled", updated_at=now)
        logger.info("Cancelled action task {}", task_id)

    async def pause(self, task_id: int) -> None:
        now = datetime.now(TZ).isoformat()
        self._remove_job(task_id)
        await self._db.update_action_task(task_id, status="paused", updated_at=now)
        logger.info("Paused action task {}", task_id)

    async def resume(self, task_id: int) -> None:
        task = await self._db.get_action_task(task_id)
        if not task or task["status"] != "paused":
            return
        now = datetime.now(TZ).isoformat()
        spec = json.loads(task["schedule_spec"])
        next_run = self._compute_next_run(task["schedule_type"], spec)
        self._add_apscheduler_job(task_id, task["schedule_type"], spec)
        await self._db.update_action_task(
            task_id, status="active", updated_at=now, next_run_at=next_run
        )
        logger.info("Resumed action task {}", task_id)

    async def execute_now(self, task_id: int) -> str:
        task = await self._db.get_action_task(task_id)
        if not task:
            return "Task not found"
        return await self._run_task(task)

    async def reload_all(self) -> None:
        tasks = await self._db.get_active_action_tasks()
        now = datetime.now(TZ)
        missed_count = 0
        scheduled_count = 0

        for task in tasks:
            next_run_str = task.get("next_run_at")
            is_past = False
            if next_run_str:
                try:
                    next_run_dt = datetime.fromisoformat(next_run_str)
                    if next_run_dt.tzinfo is None:
                        next_run_dt = next_run_dt.replace(tzinfo=TZ)
                    is_past = next_run_dt < now
                except (ValueError, TypeError):
                    is_past = False

            if task["schedule_type"] == "once" and is_past:
                await self._db.update_action_task(
                    task["id"],
                    status="missed",
                    updated_at=now.isoformat(),
                )
                missed_count += 1
            else:
                spec = json.loads(task["schedule_spec"])
                self._add_apscheduler_job(
                    task["id"], task["schedule_type"], spec
                )
                scheduled_count += 1

        logger.info(
            "Reloaded action tasks: {} scheduled, {} missed",
            scheduled_count, missed_count,
        )

    async def _on_job_executed(self, task_id: int, result: str) -> None:
        task = await self._db.get_action_task(task_id)
        if not task:
            return
        now = datetime.now(TZ).isoformat()
        new_count = task["execution_count"] + 1
        updates: dict = {
            "execution_count": new_count,
            "consecutive_failures": 0,
            "last_run_at": now,
            "updated_at": now,
        }
        max_exec = task.get("max_executions")
        if max_exec is not None and new_count >= max_exec:
            updates["status"] = "completed"
            self._remove_job(task_id)
            logger.info("Action task {} completed ({}/{} executions)", task_id, new_count, max_exec)
        else:
            spec = json.loads(task.get("schedule_spec", "{}"))
            next_run = self._compute_next_run(task["schedule_type"], spec)
            updates["next_run_at"] = next_run

        await self._db.update_action_task(task_id, **updates)

    async def _on_job_failed(self, task_id: int, error: str) -> None:
        task = await self._db.get_action_task(task_id)
        if not task:
            return
        now = datetime.now(TZ).isoformat()
        failures = task["consecutive_failures"] + 1
        updates: dict = {
            "consecutive_failures": failures,
            "last_error": error,
            "last_run_at": now,
            "updated_at": now,
        }
        # Once tasks that fail are immediately marked missed (spec requirement)
        if task["schedule_type"] == "once":
            updates["status"] = "missed"
            self._remove_job(task_id)
            logger.warning("Once task {} marked missed after failure: {}", task_id, error)
        elif failures >= 3:
            updates["status"] = "paused"
            self._remove_job(task_id)
            logger.warning("Action task {} auto-paused after {} failures: {}", task_id, failures, error)
        await self._db.update_action_task(task_id, **updates)

    async def _run_task(self, task: dict) -> str:
        try:
            result = await self._executor.execute(task)
            await self._on_job_executed(task["id"], result)
            return result
        except Exception as e:
            error_msg = str(e)
            await self._on_job_failed(task["id"], error_msg)
            return f"Error: {error_msg}"

    def _add_apscheduler_job(
        self, task_id: int, schedule_type: str, spec: dict
    ) -> None:
        job_id = f"action_task_{task_id}"
        if schedule_type == "once":
            run_at_str = spec.get("run_at", "")
            run_at = datetime.fromisoformat(run_at_str)
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=TZ)
            self._scheduler.add_job(
                self._trigger_job, "date", run_date=run_at,
                args=[task_id], id=job_id, replace_existing=True,
            )
        elif schedule_type == "interval":
            minutes = spec.get("minutes", 30)
            self._scheduler.add_job(
                self._trigger_job, "interval", minutes=minutes,
                args=[task_id], id=job_id, replace_existing=True,
            )
        elif schedule_type == "cron":
            cron_kwargs = {}
            if "hour" in spec:
                cron_kwargs["hour"] = spec["hour"]
            if "minute" in spec:
                cron_kwargs["minute"] = spec["minute"]
            if "day_of_week" in spec:
                cron_kwargs["day_of_week"] = spec["day_of_week"]
            self._scheduler.add_job(
                self._trigger_job, "cron",
                args=[task_id], id=job_id, replace_existing=True,
                timezone=TZ, **cron_kwargs,
            )

    async def _trigger_job(self, task_id: int) -> None:
        task = await self._db.get_action_task(task_id)
        if not task or task["status"] != "active":
            return
        await self._run_task(task)

    def _remove_job(self, task_id: int) -> None:
        job_id = f"action_task_{task_id}"
        try:
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
        except Exception:
            pass

    def _compute_next_run(self, schedule_type: str, spec: dict) -> str | None:
        now = datetime.now(TZ)
        if schedule_type == "once":
            return spec.get("run_at")
        elif schedule_type == "interval":
            minutes = spec.get("minutes", 30)
            return (now + timedelta(minutes=minutes)).isoformat()
        elif schedule_type == "cron":
            # Approximate; apscheduler handles the real scheduling
            return None
        return None
```

- [ ] **Step 4: Update `__init__.py` exports**

```python
from bot.core.actions.registry import ActionDefinition, ActionRegistry
from bot.core.actions.scheduler import ActionScheduler

__all__ = ["ActionDefinition", "ActionRegistry", "ActionScheduler"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_action_scheduler.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/core/actions/scheduler.py bot/core/actions/__init__.py tests/test_action_scheduler.py
git commit -m "feat(actions): add ActionScheduler with persistence and job management"
```

---

## Task 4: ActionExecutor — Action Routing + Message Delivery

**Files:**
- Create: `bot/core/actions/executor.py`
- Modify: `bot/core/actions/__init__.py` (add export)
- Test: `tests/test_action_executor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_action_executor.py`:

```python
"""Tests for ActionExecutor — action routing and message delivery."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from bot.core.actions.executor import ActionExecutor
from bot.core.actions.registry import ActionDefinition, ActionRegistry


@pytest.fixture
def mock_registry():
    reg = MagicMock(spec=ActionRegistry)
    handler = AsyncMock(return_value="Reminder sent!")
    defn = ActionDefinition(
        name="reminder", description="Send a reminder",
        parameters={}, handler=handler,
    )
    reg.get = MagicMock(return_value=defn)
    return reg


@pytest.fixture
def mock_discord_bot():
    bot = MagicMock()
    channel = AsyncMock()
    channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=channel)
    return bot


@pytest.fixture
def mock_twitch_bot():
    bot = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=channel)
    return bot


@pytest.fixture
def executor(mock_registry):
    ex = ActionExecutor(mock_registry)
    return ex


@pytest.mark.asyncio
async def test_execute_calls_handler(executor, mock_registry):
    executor.set_bots(MagicMock(), MagicMock())
    task = {
        "id": 1, "action_type": "reminder",
        "payload": '{"message": "Buy bread"}',
        "target_platform": "discord", "target_channel": "123",
        "creator_id": "456", "creator_platform": "discord",
    }
    result = await executor.execute(task)
    assert result == "Reminder sent!"
    mock_registry.get.assert_called_with("reminder")


@pytest.mark.asyncio
async def test_execute_unknown_action(executor):
    executor.set_bots(MagicMock(), MagicMock())
    executor._registry.get = MagicMock(return_value=None)
    task = {
        "id": 1, "action_type": "unknown",
        "payload": '{}', "target_platform": "discord",
        "target_channel": "123", "creator_id": "456",
        "creator_platform": "discord",
    }
    result = await executor.execute(task)
    assert "Unknown action" in result


@pytest.mark.asyncio
async def test_execute_without_bots_returns_error(executor):
    task = {
        "id": 1, "action_type": "reminder",
        "payload": '{"message": "test"}',
        "target_platform": "discord", "target_channel": "123",
        "creator_id": "456", "creator_platform": "discord",
    }
    result = await executor.execute(task)
    assert "not available" in result.lower() or "not set" in result.lower()


@pytest.mark.asyncio
async def test_deliver_discord(executor, mock_discord_bot):
    executor.set_bots(mock_discord_bot, MagicMock())
    await executor.deliver("Hello!", "discord", "123", dm=False)
    mock_discord_bot.get_channel.assert_called_with(123)


@pytest.mark.asyncio
async def test_deliver_twitch(executor, mock_twitch_bot):
    executor.set_bots(MagicMock(), mock_twitch_bot)
    await executor.deliver("Hello!", "twitch", "general", dm=False)
    mock_twitch_bot.get_channel.assert_called_with("general")


@pytest.mark.asyncio
async def test_handler_exception_is_caught(executor):
    executor.set_bots(MagicMock(), MagicMock())
    handler = AsyncMock(side_effect=RuntimeError("API down"))
    defn = ActionDefinition(name="broken", description="", parameters={}, handler=handler)
    executor._registry.get = MagicMock(return_value=defn)
    task = {
        "id": 1, "action_type": "broken", "payload": '{}',
        "target_platform": "discord", "target_channel": "123",
        "creator_id": "456", "creator_platform": "discord",
    }
    with pytest.raises(RuntimeError, match="API down"):
        await executor.execute(task)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_action_executor.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `bot/core/actions/executor.py`**

```python
"""ActionExecutor — action routing and message delivery."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger


class ActionExecutor:
    def __init__(self, registry) -> None:
        self._registry = registry
        self._discord_bot = None
        self._twitch_bot = None

    def set_bots(self, discord_bot, twitch_bot) -> None:
        self._discord_bot = discord_bot
        self._twitch_bot = twitch_bot

    async def execute(self, task: dict) -> str:
        if self._discord_bot is None and self._twitch_bot is None:
            logger.warning("ActionExecutor: bots not set, cannot execute task {}", task["id"])
            return "Error: bots not set, delivery not available"

        action_type = task["action_type"]
        defn = self._registry.get(action_type)
        if defn is None:
            return f"Unknown action type: {action_type}"

        payload = json.loads(task.get("payload", "{}"))
        target = {
            "platform": task.get("target_platform"),
            "channel_id": task.get("target_channel"),
            "creator_id": task.get("creator_id"),
            "creator_platform": task.get("creator_platform"),
        }

        # Call the handler — let exceptions propagate for the scheduler to handle
        result = await defn.handler(payload, target)

        # Deliver result to target channel
        if result and target["platform"] and target["channel_id"]:
            try:
                await self.deliver(
                    str(result), target["platform"], target["channel_id"], dm=False
                )
            except Exception as e:
                logger.error("Failed to deliver result for task {}: {}", task["id"], e)

        return str(result) if result else "OK"

    async def deliver(
        self, message: str, platform: str, channel_id: str, dm: bool = False
    ) -> None:
        if platform == "discord":
            if self._discord_bot is None:
                logger.warning("Discord bot not available for delivery")
                return
            try:
                channel = self._discord_bot.get_channel(int(channel_id))
            except (ValueError, TypeError):
                channel = None
            if channel:
                await channel.send(message)
            else:
                logger.warning("Discord channel {} not found", channel_id)
        elif platform == "twitch":
            if self._twitch_bot is None:
                logger.warning("Twitch bot not available for delivery")
                return
            channel = self._twitch_bot.get_channel(channel_id)
            if channel:
                await channel.send(message)
            else:
                logger.warning("Twitch channel {} not found", channel_id)
        else:
            logger.warning("Unsupported delivery platform: {}", platform)
```

- [ ] **Step 4: Update `__init__.py` exports**

Add `ActionExecutor` to exports in `bot/core/actions/__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_action_executor.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/core/actions/executor.py bot/core/actions/__init__.py tests/test_action_executor.py
git commit -m "feat(actions): add ActionExecutor with routing and message delivery"
```

---

## Task 5: ActionService — LLM Facade + Tool Definitions

**Files:**
- Create: `bot/core/actions/service.py`
- Modify: `bot/core/actions/__init__.py` (add export)
- Test: `tests/test_action_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_action_service.py`:

```python
"""Tests for ActionService — LLM facade, tool definitions, validation."""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from bot.core.actions.service import ActionService

TZ = ZoneInfo("Europe/Paris")


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.check_permission = MagicMock(return_value=True)
    reg.list_available = MagicMock(return_value=[])
    return reg


@pytest.fixture
def mock_scheduler():
    sched = AsyncMock()
    sched.schedule = AsyncMock(return_value=1)
    sched.cancel = AsyncMock()
    return sched


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.count_user_action_tasks = AsyncMock(return_value=0)
    db.search_action_tasks = AsyncMock(return_value=[])
    db.list_action_tasks = AsyncMock(return_value=[])
    db.get_action_task = AsyncMock(return_value=None)
    return db


@pytest.fixture
def service(mock_registry, mock_scheduler, mock_db):
    return ActionService(mock_registry, mock_scheduler, mock_db)


def test_get_tool_definitions(service):
    tools = service.get_tool_definitions()
    assert len(tools) == 3
    names = {t["function"]["name"] for t in tools}
    assert names == {"create_action_task", "cancel_action_task", "list_action_tasks"}


@pytest.mark.asyncio
async def test_create_task_success(service, mock_scheduler):
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "Buy bread",
            "payload": {"message": "Buy bread!"},
            "schedule": {"type": "once", "run_at": run_at},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "created"
    assert result["task_id"] == 1


@pytest.mark.asyncio
async def test_create_task_missing_schedule(service):
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "Buy bread",
            "payload": {"message": "Buy bread!"},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "need_more_info"
    assert "schedule" in str(result["missing"])


@pytest.mark.asyncio
async def test_create_task_permission_denied(service, mock_registry):
    mock_registry.check_permission = MagicMock(return_value=False)
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "schedule": {"type": "once", "run_at": run_at},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "denied"


@pytest.mark.asyncio
async def test_create_task_rate_limited(service, mock_db):
    mock_db.count_user_action_tasks = AsyncMock(return_value=10)
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "schedule": {"type": "once", "run_at": run_at},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "rate_limited"


@pytest.mark.asyncio
async def test_create_task_past_run_at_rejected(service):
    past = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "schedule": {"type": "once", "run_at": past},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "error"
    assert "past" in result["message"].lower() or "passé" in result["message"].lower()


@pytest.mark.asyncio
async def test_create_task_interval_too_short(service):
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "schedule": {"type": "interval", "interval_minutes": 2},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_cancel_by_id(service, mock_scheduler, mock_db):
    mock_db.get_action_task = AsyncMock(return_value={
        "id": 1, "description": "test", "creator_id": "123",
        "creator_platform": "discord", "status": "active",
    })
    result = await service.cancel(
        task_id=1, user_id="123", platform="discord", user_roles=["everyone"]
    )
    assert result["status"] == "cancelled"
    mock_scheduler.cancel.assert_called_with(1)


@pytest.mark.asyncio
async def test_cancel_by_search_single_match(service, mock_scheduler, mock_db):
    mock_db.search_action_tasks = AsyncMock(return_value=[
        {"id": 42, "description": "Rappel pain", "status": "active",
         "creator_id": "123", "creator_platform": "discord"}
    ])
    result = await service.cancel(
        search_query="pain", user_id="123", platform="discord", user_roles=["everyone"]
    )
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_by_search_ambiguous(service, mock_db):
    mock_db.search_action_tasks = AsyncMock(return_value=[
        {"id": 1, "description": "Rappel pain", "status": "active",
         "creator_id": "123", "creator_platform": "discord"},
        {"id": 2, "description": "Rappel pain de mie", "status": "active",
         "creator_id": "123", "creator_platform": "discord"},
    ])
    result = await service.cancel(
        search_query="pain", user_id="123", platform="discord", user_roles=["everyone"]
    )
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2


@pytest.mark.asyncio
async def test_cancel_by_search_not_found(service, mock_db):
    mock_db.search_action_tasks = AsyncMock(return_value=[])
    result = await service.cancel(
        search_query="inexistant", user_id="123", platform="discord", user_roles=["everyone"]
    )
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_list_tasks(service, mock_db):
    mock_db.list_action_tasks = AsyncMock(return_value=[
        {"id": 1, "action_type": "reminder", "description": "test",
         "status": "active", "next_run_at": "2026-03-23T18:00:00",
         "execution_count": 0, "max_executions": 1},
    ])
    result = await service.list_tasks(user_id="123", platform="discord")
    assert result["status"] == "ok"
    assert len(result["tasks"]) == 1


@pytest.mark.asyncio
async def test_execute_tool_routing(service):
    service.create = AsyncMock(return_value={"status": "created", "task_id": 1})
    result = await service.execute_tool(
        "create_action_task",
        {"action_type": "reminder", "description": "test",
         "schedule": {"type": "once", "run_at": "2026-12-01T10:00:00"}},
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "created"


@pytest.mark.asyncio
async def test_create_task_defaults_target_to_origin(service, mock_scheduler):
    """When target is omitted, it should default to the originating channel."""
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "payload": {"message": "hello"},
            "schedule": {"type": "once", "run_at": run_at},
            # No target specified
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="789",
    )
    assert result["status"] == "created"
    # Verify scheduler was called with the default channel
    call_kwargs = mock_scheduler.schedule.call_args[1]
    assert call_kwargs["target_channel"] == "789"
    assert call_kwargs["target_platform"] == "discord"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_action_service.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `bot/core/actions/service.py`**

```python
"""ActionService — LLM facade exposing tool definitions for action tasks."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

TZ = ZoneInfo("Europe/Paris")

MAX_TASKS_PER_USER = 10
MIN_INTERVAL_MINUTES = 5
PAST_GRACE_SECONDS = 30

CREATE_TOOL = {
    "type": "function",
    "function": {
        "name": "create_action_task",
        "description": "Créer une tâche planifiée (rappel, recherche web, génération d'image...)",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["reminder", "web_search", "image_generate"],
                    "description": "Type d'action à exécuter",
                },
                "description": {
                    "type": "string",
                    "description": "Description en langage naturel de la tâche",
                },
                "payload": {
                    "type": "object",
                    "description": "Paramètres de l'action (message, query, prompt...)",
                },
                "schedule": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["once", "interval", "cron"]},
                        "run_at": {"type": "string", "description": "ISO datetime (Europe/Paris) pour once"},
                        "interval_minutes": {"type": "integer", "description": "Intervalle en minutes (min 5)"},
                        "cron_hour": {"type": "integer"},
                        "cron_minute": {"type": "integer"},
                        "cron_day_of_week": {"type": "string", "description": "mon,tue,wed,thu,fri,sat,sun"},
                        "max_executions": {"type": ["integer", "null"], "description": "Max exécutions (null=infini)"},
                    },
                    "required": ["type"],
                },
                "target": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "enum": ["discord", "twitch", "web"]},
                        "channel_id": {"type": "string"},
                        "dm": {"type": "boolean", "description": "Envoyer en DM au créateur"},
                    },
                },
            },
            "required": ["action_type", "description"],
            "additionalProperties": False,
        },
    },
}

CANCEL_TOOL = {
    "type": "function",
    "function": {
        "name": "cancel_action_task",
        "description": "Annuler une tâche planifiée par ID ou par description",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID de la tâche à annuler"},
                "search_query": {"type": "string", "description": "Recherche par description"},
            },
            "additionalProperties": False,
        },
    },
}

LIST_TOOL = {
    "type": "function",
    "function": {
        "name": "list_action_tasks",
        "description": "Lister les tâches planifiées",
        "parameters": {
            "type": "object",
            "properties": {
                "status_filter": {"type": "string", "enum": ["active", "paused", "all"], "default": "active"},
                "own_only": {"type": "boolean", "default": True, "description": "Mes tâches uniquement"},
            },
            "additionalProperties": False,
        },
    },
}


class ActionService:
    def __init__(self, registry, scheduler, db) -> None:
        self._registry = registry
        self._scheduler = scheduler
        self._db = db

    def get_tool_definitions(self) -> list[dict]:
        return [CREATE_TOOL, CANCEL_TOOL, LIST_TOOL]

    async def execute_tool(
        self, name: str, args: dict, user_id: str, platform: str,
        user_roles: list[str], channel_id: str | None = None,
    ) -> dict:
        if name == "create_action_task":
            return await self.create(args, user_id, platform, user_roles, channel_id)
        elif name == "cancel_action_task":
            return await self.cancel(
                task_id=args.get("task_id"),
                search_query=args.get("search_query"),
                user_id=user_id, platform=platform, user_roles=user_roles,
            )
        elif name == "list_action_tasks":
            return await self.list_tasks(
                user_id=user_id, platform=platform,
                status_filter=args.get("status_filter", "active"),
                own_only=args.get("own_only", True),
                user_roles=user_roles,
            )
        return {"status": "error", "message": f"Unknown tool: {name}"}

    async def create(
        self, task_data: dict, user_id: str, platform: str,
        user_roles: list[str], channel_id: str | None = None,
    ) -> dict:
        action_type = task_data.get("action_type", "")

        # Permission check
        if not self._registry.check_permission(action_type, platform, user_roles):
            return {"status": "denied", "message": f"Action {action_type} non autorisée pour votre rôle."}

        # Rate limit
        count = await self._db.count_user_action_tasks(user_id, platform)
        if count >= MAX_TASKS_PER_USER:
            return {"status": "rate_limited", "message": f"Maximum {MAX_TASKS_PER_USER} tâches actives atteint."}

        # Validate schedule
        schedule = task_data.get("schedule")
        if not schedule:
            return {
                "status": "need_more_info",
                "missing": ["schedule"],
                "message": "Je dois savoir quand exécuter cette tâche.",
            }

        schedule_type = schedule.get("type", "")
        missing = []

        if schedule_type == "once":
            run_at = schedule.get("run_at")
            if not run_at:
                missing.append("schedule.run_at")
            else:
                try:
                    run_at_dt = datetime.fromisoformat(run_at)
                    if run_at_dt.tzinfo is None:
                        run_at_dt = run_at_dt.replace(tzinfo=TZ)
                    grace = datetime.now(TZ) - timedelta(seconds=PAST_GRACE_SECONDS)
                    if run_at_dt < grace:
                        return {"status": "error", "message": "L'heure spécifiée est dans le passé."}
                except ValueError:
                    return {"status": "error", "message": "Format de date invalide."}

        elif schedule_type == "interval":
            interval = schedule.get("interval_minutes")
            if not interval:
                missing.append("schedule.interval_minutes")
            elif interval < MIN_INTERVAL_MINUTES:
                return {"status": "error", "message": f"Intervalle minimum: {MIN_INTERVAL_MINUTES} minutes."}

        elif schedule_type == "cron":
            if "cron_hour" not in schedule and "cron_minute" not in schedule:
                missing.append("schedule.cron_hour")
                missing.append("schedule.cron_minute")

        if missing:
            return {
                "status": "need_more_info",
                "missing": missing,
                "message": "Il me manque des informations pour planifier cette tâche.",
            }

        # Default target to originating channel
        target = task_data.get("target", {})
        target_platform = target.get("platform", platform)
        target_channel = target.get("channel_id", channel_id)

        # Build schedule_spec
        spec: dict = {}
        if schedule_type == "once":
            spec["run_at"] = schedule["run_at"]
        elif schedule_type == "interval":
            spec["minutes"] = schedule["interval_minutes"]
        elif schedule_type == "cron":
            if "cron_hour" in schedule:
                spec["hour"] = schedule["cron_hour"]
            if "cron_minute" in schedule:
                spec["minute"] = schedule["cron_minute"]
            if "cron_day_of_week" in schedule:
                spec["day_of_week"] = schedule["cron_day_of_week"]

        payload = task_data.get("payload", {})
        max_executions = schedule.get("max_executions")
        if schedule_type == "once" and max_executions is None:
            max_executions = 1

        task_id = await self._scheduler.schedule(
            action_type=action_type,
            description=task_data.get("description", ""),
            creator_id=user_id,
            creator_platform=platform,
            target_channel=target_channel,
            target_platform=target_platform,
            payload=json.dumps(payload),
            schedule_type=schedule_type,
            schedule_spec=json.dumps(spec),
            max_executions=max_executions,
        )

        return {
            "status": "created",
            "task_id": task_id,
            "description": task_data.get("description", ""),
            "next_run_at": spec.get("run_at"),
        }

    async def cancel(
        self, task_id: int | None = None, search_query: str | None = None,
        user_id: str = "", platform: str = "", user_roles: list[str] | None = None,
    ) -> dict:
        if task_id is not None:
            task = await self._db.get_action_task(task_id)
            if not task:
                return {"status": "not_found", "message": "Tâche introuvable."}
            is_admin = "admin" in (user_roles or [])
            if not is_admin and (task["creator_id"] != user_id or task["creator_platform"] != platform):
                return {"status": "denied", "message": "Cette tâche ne vous appartient pas."}
            await self._scheduler.cancel(task_id)
            return {"status": "cancelled", "task": {"id": task["id"], "description": task["description"]}}

        if search_query:
            results = await self._db.search_action_tasks(search_query, user_id, platform)
            if len(results) == 0:
                return {"status": "not_found", "message": "Aucune tâche correspondante trouvée."}
            if len(results) == 1:
                await self._scheduler.cancel(results[0]["id"])
                return {"status": "cancelled", "task": {"id": results[0]["id"], "description": results[0]["description"]}}
            return {
                "status": "ambiguous",
                "candidates": [{"id": r["id"], "description": r["description"]} for r in results],
            }

        return {"status": "error", "message": "task_id ou search_query requis."}

    # --- Dashboard facade methods (avoid private access from routes) ---

    async def pause_task(self, task_id: int) -> None:
        await self._scheduler.pause(task_id)

    async def resume_task(self, task_id: int) -> None:
        await self._scheduler.resume(task_id)

    async def execute_task_now(self, task_id: int) -> str:
        return await self._scheduler.execute_now(task_id)

    async def update_permission(self, action_type: str, platform: str, min_role: str) -> None:
        await self._registry.update_permission(action_type, platform, min_role)

    async def set_action_enabled(self, action_type: str, enabled: bool) -> None:
        await self._registry.set_enabled(action_type, enabled)

    async def list_tasks(
        self, user_id: str = "", platform: str = "",
        status_filter: str = "active", own_only: bool = True,
        user_roles: list[str] | None = None,
    ) -> dict:
        is_admin = "admin" in (user_roles or [])
        creator_id = user_id if (own_only or not is_admin) else None
        creator_platform = platform if creator_id else None

        rows = await self._db.list_action_tasks(
            status=status_filter if status_filter != "all" else None,
            creator_id=creator_id,
            creator_platform=creator_platform,
        )
        tasks = [
            {
                "id": r["id"],
                "action_type": r["action_type"],
                "description": r["description"],
                "status": r["status"],
                "next_run_at": r.get("next_run_at"),
                "execution_count": r.get("execution_count", 0),
                "max_executions": r.get("max_executions"),
            }
            for r in rows
        ]
        return {"status": "ok", "tasks": tasks}
```

- [ ] **Step 4: Update `__init__.py` exports**

Add `ActionService` to `bot/core/actions/__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_action_service.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run all action tests together**

Run: `pytest tests/test_action_*.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add bot/core/actions/service.py bot/core/actions/__init__.py tests/test_action_service.py
git commit -m "feat(actions): add ActionService facade with tool definitions and validation"
```

---

## Task 6: DI Wiring + Shared Scheduler + Boot Sequence

**Files:**
- Modify: `bot/main.py` (lines 80–285)
- Modify: `bot/core/journal.py` (lines 662–691, accept external scheduler)
- Modify: `bot/dashboard/state.py` (line 25, add field)

- [ ] **Step 1: Modify `bot/core/journal.py` to accept external scheduler**

Change the `start()` method (line 662) to accept an optional external scheduler.

The current code is:
```python
def start(self) -> None:
    self._scheduler = AsyncIOScheduler()
    # ... add_job calls ...
    self._scheduler.start()
```

Change to:
```python
def start(self, scheduler=None) -> None:
    owns_scheduler = scheduler is None
    if owns_scheduler:
        self._scheduler = AsyncIOScheduler()
    else:
        self._scheduler = scheduler

    raw = self._config.bot.journal_time
    if isinstance(raw, int):
        hour, minute = divmod(raw, 60)
    else:
        time_str = str(raw)
        hour, minute = map(int, time_str.split(":"))

    self._scheduler.add_job(
        self.generate_and_send, "cron", hour=hour, minute=minute,
        id="daily_journal", replace_existing=True,
    )

    cleanup_dt = datetime(2000, 1, 1, hour, minute) - timedelta(minutes=30)
    self._scheduler.add_job(
        self.run_memory_cleanup, "cron",
        hour=cleanup_dt.hour, minute=cleanup_dt.minute,
        id="memory_cleanup", replace_existing=True,
    )

    # Only start if we own the scheduler (no shared scheduler provided)
    if owns_scheduler:
        self._scheduler.start()
```

This is backward-compatible: existing tests that call `journal.start()` with no arguments still work (creates + starts its own scheduler). When a shared scheduler is passed, it only adds jobs without starting.

Also update existing journal tests if any mock `AsyncIOScheduler` — verify `tests/test_journal.py` still passes after the change.

- [ ] **Step 2: Add `action_service` to `bot/dashboard/state.py`**

Add after the existing optional fields (around line 37):

```python
action_service: Optional["ActionService"] = None
```

- [ ] **Step 3: Wire ActionService in `bot/main.py`**

After the existing service creation block (around line 113), add:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.core.actions import ActionRegistry, ActionScheduler, ActionExecutor, ActionService, ActionDefinition

# Shared scheduler
shared_scheduler = AsyncIOScheduler()

# Action services
action_registry = ActionRegistry(db)
await action_registry.load_permissions()

action_executor = ActionExecutor(action_registry)

action_scheduler = ActionScheduler(db, action_executor, shared_scheduler)

action_service = ActionService(action_registry, action_scheduler, db)
```

After Discord/Twitch bot creation (around line 237), add:

```python
discord_bot.action_service = action_service
if twitch_bot is not None:
    twitch_bot.action_service = action_service

# Late injection of bots into executor (twitch_bot may be None)
action_executor.set_bots(discord_bot, twitch_bot)
```

Change journal start to use shared scheduler:

```python
journal.start(scheduler=shared_scheduler)
```

After journal start, add reload and start:

```python
await action_scheduler.reload_all()
shared_scheduler.start()
```

Add `action_service` to `AppState` constructor:

```python
dashboard_state = AppState(
    ...,
    action_service=action_service,
)
```

Register built-in actions:

```python
async def _reminder_handler(payload: dict, target: dict) -> str:
    return payload.get("message", "Rappel!")

await action_registry.register("reminder", ActionDefinition(
    name="reminder",
    description="Envoyer un message de rappel",
    parameters={"type": "object", "properties": {"message": {"type": "string"}}},
    handler=_reminder_handler,
))

# web_search and image_generate are listed in the tool enum but their handlers
# will be registered in future sub-projects. For now, the LLM can only create
# "reminder" tasks. If it tries web_search/image_generate, the executor returns
# "Unknown action type" which the LLM can relay to the user.
#
# Similarly, the open_task_modal Discord tool (spec section "Modal Discord") is
# deferred to a later iteration — the need_more_info flow covers the same UX.
```

- [ ] **Step 4: Run existing tests to verify no regressions**

Run: `pytest tests/ -x -q`
Expected: All tests PASS (no regressions from journal.py changes).

- [ ] **Step 5: Commit**

```bash
git add bot/main.py bot/core/journal.py bot/dashboard/state.py
git commit -m "feat(actions): wire ActionService into DI with shared scheduler"
```

---

## Task 7: Handler Integration — Discord + Twitch

**Files:**
- Modify: `bot/discord/handlers.py` (lines 433–468)
- Modify: `bot/twitch/handlers.py` (lines 222–243)

- [ ] **Step 1: Add role resolution helper**

Create a small helper function at the top of `bot/discord/handlers.py` (after imports):

```python
def _resolve_discord_roles(member) -> list[str]:
    """Map Discord member roles to the action permission hierarchy."""
    roles = ["everyone"]
    if any(r.name.lower() in ("subscriber", "sub", "abonné") for r in member.roles):
        roles.append("subscriber")
    if member.guild_permissions.manage_messages or any(
        r.name.lower() in ("moderator", "mod", "modérateur") for r in member.roles
    ):
        roles.append("moderator")
    if member.guild_permissions.administrator:
        roles.append("admin")
    return roles
```

Similarly in `bot/twitch/handlers.py`:

```python
def _resolve_twitch_roles(badges: list) -> list[str]:
    """Map Twitch badges to the action permission hierarchy."""
    roles = ["everyone"]
    badge_names = {b.id if hasattr(b, 'id') else str(b) for b in badges}
    if "subscriber" in badge_names:
        roles.append("subscriber")
    if "vip" in badge_names:
        roles.append("vip")
    if "moderator" in badge_names:
        roles.append("moderator")
    if "broadcaster" in badge_names:
        roles.append("admin")
    return roles
```

- [ ] **Step 2: Add action tools to tool collection in Discord handler**

In `bot/discord/handlers.py`, after the apex_api tool block (around line 440), add:

```python
action_service = getattr(bot, "action_service", None)
if action_service:
    tools.extend(action_service.get_tool_definitions())
```

- [ ] **Step 3: Add action tool executor in Discord handler**

In `_tool_executor` function (around line 444), add before the `return f"Unknown tool: {name}"` line:

```python
if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
    user_roles = _resolve_discord_roles(message.author)
    # Check config admin list too
    admin_ids = getattr(bot.config, "admin_ids", [])
    if str(message.author.id) in [str(a) for a in admin_ids]:
        user_roles.append("admin")
    result = await action_service.execute_tool(
        name, args,
        user_id=str(message.author.id),
        platform="discord",
        user_roles=user_roles,
        channel_id=str(message.channel.id),
    )
    return json.dumps(result)
```

- [ ] **Step 4: Same for Twitch handler**

In `bot/twitch/handlers.py`, add tool collection (after line 229):

```python
action_service = getattr(bot, "action_service", None)
if action_service:
    tools.extend(action_service.get_tool_definitions())
```

And in the tool executor (before `return f"Unknown tool: {name}"`):

```python
if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
    badges = getattr(payload.chatter, "badges", []) or []
    user_roles = _resolve_twitch_roles(badges)
    result = await action_service.execute_tool(
        name, args,
        user_id=str(payload.chatter.id),
        platform="twitch",
        user_roles=user_roles,
        channel_id=channel_name,
    )
    return json.dumps(result)
```

- [ ] **Step 5: Run existing handler tests**

Run: `pytest tests/test_discord_commands.py tests/ -x -q`
Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add bot/discord/handlers.py bot/twitch/handlers.py
git commit -m "feat(actions): integrate action tools into Discord and Twitch handlers"
```

---

## Task 8: Dashboard API — Actions Routes

**Files:**
- Create: `bot/dashboard/routes/actions.py`
- Modify: `bot/dashboard/app.py` (register router)
- Test: `tests/test_action_dashboard.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_action_dashboard.py`:

```python
"""Tests for dashboard action endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from bot.dashboard.routes.actions import router


def _make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/actions")

    state = MagicMock()
    state.db = AsyncMock()
    state.db.list_action_tasks = AsyncMock(return_value=[
        {"id": 1, "action_type": "reminder", "description": "test",
         "status": "active", "creator_id": "123", "creator_platform": "discord",
         "target_channel": "456", "target_platform": "discord",
         "payload": '{}', "schedule_type": "once", "schedule_spec": '{}',
         "max_executions": 1, "execution_count": 0, "consecutive_failures": 0,
         "last_error": None, "created_at": "2026-03-22T10:00:00",
         "updated_at": "2026-03-22T10:00:00", "next_run_at": "2026-03-23T18:00:00",
         "last_run_at": None},
    ])
    state.db.get_action_task = AsyncMock(return_value={
        "id": 1, "status": "active", "description": "test",
    })
    state.db.list_action_permissions = AsyncMock(return_value=[
        {"action_type": "reminder", "min_role_discord": "everyone",
         "min_role_twitch": "admin", "enabled": 1},
    ])

    action_service = MagicMock()
    action_service.cancel = AsyncMock(return_value={"status": "cancelled", "task": {"id": 1, "description": "test"}})
    action_service.pause_task = AsyncMock()
    action_service.resume_task = AsyncMock()
    action_service.execute_task_now = AsyncMock(return_value="OK")
    action_service.update_permission = AsyncMock()
    action_service.set_action_enabled = AsyncMock()

    state.action_service = action_service
    app.state.wally = state
    return app


def test_list_tasks():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/actions/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 1


def test_cancel_task():
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/api/actions/tasks/1/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_pause_task():
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/api/actions/tasks/1/pause")
    assert resp.status_code == 200


def test_resume_task():
    app = _make_app()
    client = TestClient(app)
    resp = client.post("/api/actions/tasks/1/resume")
    assert resp.status_code == 200


def test_list_permissions():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/actions/permissions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["permissions"]) == 1


def test_update_permission():
    app = _make_app()
    client = TestClient(app)
    resp = client.put(
        "/api/actions/permissions/reminder",
        json={"min_role_discord": "moderator", "min_role_twitch": "vip", "enabled": True},
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_action_dashboard.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `bot/dashboard/routes/actions.py`**

```python
"""Dashboard API routes for action task management."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: str | None = None,
    platform: str | None = None,
    creator: str | None = None,
    action_type: str | None = None,
) -> dict:
    state = request.app.state.wally
    rows = await state.db.list_action_tasks(
        status=status, creator_id=creator, action_type=action_type,
    )
    return {"tasks": [dict(r) for r in rows]}


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    task = await state.db.get_action_task(task_id)
    if not task:
        return {"error": "not found"}
    return {"task": task}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    await state.action_service.cancel(task_id=task_id, user_id="", platform="", user_roles=["admin"])
    return {"status": "ok"}


@router.post("/tasks/{task_id}/pause")
async def pause_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    await state.action_service.pause_task(task_id)
    return {"status": "ok"}


@router.post("/tasks/{task_id}/resume")
async def resume_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    await state.action_service.resume_task(task_id)
    return {"status": "ok"}


@router.post("/tasks/{task_id}/execute")
async def execute_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    result = await state.action_service.execute_task_now(task_id)
    return {"status": "ok", "result": result}


@router.get("/permissions")
async def list_permissions(request: Request) -> dict:
    state = request.app.state.wally
    perms = await state.db.list_action_permissions()
    return {"permissions": [dict(p) for p in perms]}


@router.put("/permissions/{action_type}")
async def update_permission(request: Request, action_type: str) -> dict:
    state = request.app.state.wally
    body = await request.json()
    svc = state.action_service

    if "min_role_discord" in body:
        await svc.update_permission(action_type, "discord", body["min_role_discord"])
    if "min_role_twitch" in body:
        await svc.update_permission(action_type, "twitch", body["min_role_twitch"])
    if "enabled" in body:
        await svc.set_action_enabled(action_type, bool(body["enabled"]))

    return {"status": "ok"}
```

- [ ] **Step 4: Register router in `bot/dashboard/app.py`**

Find the router registration section and add:

```python
from bot.dashboard.routes.actions import router as actions_router
app.include_router(actions_router, prefix="/api/actions")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_action_dashboard.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/routes/actions.py bot/dashboard/app.py tests/test_action_dashboard.py
git commit -m "feat(dashboard): add action tasks and permissions API endpoints"
```

---

## Task 9: Dashboard Frontend — Actions Tab

**Files:**
- Modify: `bot/dashboard/static/app.js`
- Modify: `bot/dashboard/static/style.css`

- [ ] **Step 1: Add Actions tab to navigation**

In `app.js`, find the admin navigation section and add an "Actions" tab button following the existing pattern.

- [ ] **Step 2: Add `renderActionsTab()` function**

Add a function that fetches `/api/actions/tasks` and `/api/actions/permissions` and renders two sub-tabs:

**Tasks sub-tab:**
- Card grid layout (same as memory tab)
- Each card shows: description, action_type badge, status badge (colored), creator, next_run_at, execution_count/max_executions
- Status badge colors: active=#06b6d4, paused=#eab308, completed=#22c55e, cancelled=#666, missed=#ef4444
- Action buttons per card: Pause/Resume toggle, Cancel (with confirm), Execute Now

**Permissions sub-tab:**
- Table with rows per action_type
- Columns: action name, enabled toggle, Discord role dropdown, Twitch role dropdown
- Dropdowns: everyone/subscriber/moderator/admin for Discord, everyone/subscriber/vip/moderator/admin for Twitch
- Changes call `PUT /api/actions/permissions/{action_type}` immediately

- [ ] **Step 3: Add tab to `showTab()` switch**

In the `showTab()` function, add:
```javascript
case 'actions':
    renderActionsTab();
    break;
```

- [ ] **Step 4: Add glassmorphism styles**

In `style.css`, add styles for action cards following the design system:

```css
.action-card {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 1rem;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.action-status-badge {
    padding: 2px 8px;
    border-radius: 8px;
    font-size: 0.75rem;
    font-weight: 600;
}
.action-status-badge.active { background: rgba(6, 182, 212, 0.2); color: #06b6d4; }
.action-status-badge.paused { background: rgba(234, 179, 8, 0.2); color: #eab308; }
.action-status-badge.completed { background: rgba(34, 197, 94, 0.2); color: #22c55e; }
.action-status-badge.cancelled { background: rgba(102, 102, 102, 0.2); color: #999; }
.action-status-badge.missed { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
```

- [ ] **Step 5: Manual test in browser**

Start the dashboard and verify:
1. Actions tab appears in admin mode
2. Tasks list loads and displays correctly
3. Permissions table loads and dropdowns work
4. Pause/Resume/Cancel/Execute actions call the API

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/static/app.js bot/dashboard/static/style.css
git commit -m "feat(dashboard): add Actions tab with task management and permissions UI"
```

---

## Task 10: Full Integration Test + Cleanup

**Files:**
- Run all tests
- Verify bot starts without errors

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS (existing + new action tests).

- [ ] **Step 2: Verify bot starts**

Run: `cd /opt/stacks/wally-ai && python -c "from bot.core.actions import ActionService, ActionRegistry, ActionScheduler, ActionExecutor, ActionDefinition; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 3: Review all new files for consistency**

Verify:
- All files use `loguru` (no `print()` or `import logging`)
- All async I/O uses `await`
- No hardcoded secrets
- Error handling follows project conventions (try/except, log, continue)

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: cleanup and verify ActionService integration"
```
