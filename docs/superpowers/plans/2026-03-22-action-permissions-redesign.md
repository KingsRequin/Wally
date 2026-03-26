# Action Permissions Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split reminder into one-shot/recurring types and replace fixed Discord role hierarchy with real per-guild multi-select roles.

**Architecture:** New `action_permissions_discord` table stores (action_type, guild_id, role_id) tuples. Registry caches them in-memory. Discord bot exposes real guild roles via API. Dashboard gets multi-select chip UI per guild.

**Tech Stack:** Python 3.11, aiosqlite, discord.py 2.x, FastAPI, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-22-action-permissions-redesign.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `bot/db/database.py` | New table + CRUD for `action_permissions_discord`. Stop writing `min_role_discord`. |
| `bot/core/actions/registry.py` | In-memory cache `_discord_perms`. New Discord permission check. `guild_id` on public methods. |
| `bot/core/actions/service.py` | Route `reminder` → `reminder_recurring` by schedule type. Pass `guild_id`. |
| `bot/main.py` | Register `reminder_recurring` handler. |
| `bot/discord/handlers.py` | `_resolve_discord_roles` returns real role IDs. Pass `guild_id`. |
| `bot/dashboard/routes/actions.py` | Discord roles endpoint. Discord permission CRUD endpoint. |
| `bot/dashboard/static/app.js` | Multi-select chip UI per guild. Fetch real roles. |
| `tests/test_action_registry.py` | New tests for Discord guild-based permissions. |
| `tests/test_action_service.py` | Tests for reminder type routing. |

---

### Task 1: Database — New Table + Methods

**Files:**
- Modify: `bot/db/database.py:258-263` (SCHEMA), `bot/db/database.py:1630-1651` (methods)
- Test: `tests/test_action_registry.py` (later task)

- [ ] **Step 1: Add `action_permissions_discord` table to SCHEMA**

In `bot/db/database.py`, add after the `action_permissions` CREATE TABLE block (line 263):

```sql
CREATE TABLE IF NOT EXISTS action_permissions_discord (
    action_type TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    role_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (action_type, guild_id, role_id)
);
```

- [ ] **Step 2: Add DB methods for discord permissions**

Add to `bot/db/database.py` after `upsert_action_permission`:

```python
async def list_discord_permissions(self, action_type: str | None = None) -> list[dict]:
    if action_type:
        return await self.fetch_all(
            "SELECT * FROM action_permissions_discord WHERE action_type = ? ORDER BY guild_id, role_name",
            (action_type,),
        )
    return await self.fetch_all("SELECT * FROM action_permissions_discord ORDER BY action_type, guild_id, role_name")

async def get_discord_permissions(self, action_type: str, guild_id: str) -> list[dict]:
    return await self.fetch_all(
        "SELECT * FROM action_permissions_discord WHERE action_type = ? AND guild_id = ?",
        (action_type, guild_id),
    )

async def set_discord_permissions(self, action_type: str, guild_id: str, roles: list[dict]) -> None:
    """Replace all Discord role permissions for (action_type, guild_id)."""
    await self.execute(
        "DELETE FROM action_permissions_discord WHERE action_type = ? AND guild_id = ?",
        (action_type, guild_id),
    )
    for role in roles:
        await self.execute(
            "INSERT INTO action_permissions_discord (action_type, guild_id, role_id, role_name) VALUES (?, ?, ?, ?)",
            (action_type, guild_id, role["role_id"], role.get("role_name", "")),
        )

async def delete_discord_permissions(self, action_type: str) -> None:
    await self.execute("DELETE FROM action_permissions_discord WHERE action_type = ?", (action_type,))
```

- [ ] **Step 3: Update `upsert_action_permission` to stop writing `min_role_discord`**

Keep the method signature (for backward compat) but the `min_role_discord` param becomes ignored for new logic. Actually, keep writing it for now — the column still exists. The registry will just stop reading it for Discord. No change needed here.

- [ ] **Step 4: Verify DB creates correctly**

Run: `python3 -c "import asyncio; from bot.db.database import Database; asyncio.run(Database.create.__wrapped__(None))" 2>&1 || echo "OK - just checking import"`

Run: `python3 -m pytest tests/test_action_service.py tests/test_action_scheduler.py tests/test_action_executor.py tests/test_action_registry.py -x -q`
Expected: All existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add bot/db/database.py
git commit -m "feat(db): add action_permissions_discord table and CRUD methods"
```

---

### Task 2: Registry — In-Memory Cache + Guild-Based Permission Check

**Files:**
- Modify: `bot/core/actions/registry.py`
- Test: `tests/test_action_registry.py`

- [ ] **Step 1: Write failing tests for guild-based Discord permissions**

Add to `tests/test_action_registry.py`:

```python
@pytest.mark.asyncio
async def test_check_permission_discord_guild_roles(mock_db):
    """Discord permissions use guild-specific role IDs."""
    registry = ActionRegistry(mock_db)
    defn = _make_definition("reminder")
    mock_db.list_discord_permissions = AsyncMock(return_value=[
        {"action_type": "reminder", "guild_id": "guild1", "role_id": "role_100", "role_name": "Streamer"},
        {"action_type": "reminder", "guild_id": "guild1", "role_id": "role_200", "role_name": "VIP"},
    ])
    mock_db.list_action_permissions = AsyncMock(return_value=[
        {"action_type": "reminder", "min_role_discord": "admin", "min_role_twitch": "admin", "enabled": 1},
    ])
    await registry.load_permissions()
    await registry.register("reminder", defn)

    # User has role_100 → granted
    assert registry.check_permission("reminder", "discord", ["everyone", "role_100"], guild_id="guild1")
    # User has role_999 → denied
    assert not registry.check_permission("reminder", "discord", ["everyone", "role_999"], guild_id="guild1")
    # User has admin → always granted
    assert registry.check_permission("reminder", "discord", ["everyone", "admin"], guild_id="guild1")


@pytest.mark.asyncio
async def test_check_permission_discord_everyone_role(mock_db):
    """'everyone' in allowed roles grants access to all."""
    registry = ActionRegistry(mock_db)
    defn = _make_definition("reminder")
    mock_db.list_discord_permissions = AsyncMock(return_value=[
        {"action_type": "reminder", "guild_id": "guild1", "role_id": "everyone", "role_name": "everyone"},
    ])
    mock_db.list_action_permissions = AsyncMock(return_value=[
        {"action_type": "reminder", "min_role_discord": "admin", "min_role_twitch": "admin", "enabled": 1},
    ])
    await registry.load_permissions()
    await registry.register("reminder", defn)

    assert registry.check_permission("reminder", "discord", ["everyone"], guild_id="guild1")


@pytest.mark.asyncio
async def test_check_permission_discord_no_guild_id(mock_db):
    """No guild_id (DMs) → denied unless admin."""
    registry = ActionRegistry(mock_db)
    defn = _make_definition("reminder")
    mock_db.list_discord_permissions = AsyncMock(return_value=[])
    mock_db.list_action_permissions = AsyncMock(return_value=[
        {"action_type": "reminder", "min_role_discord": "admin", "min_role_twitch": "admin", "enabled": 1},
    ])
    await registry.load_permissions()
    await registry.register("reminder", defn)

    assert not registry.check_permission("reminder", "discord", ["everyone"], guild_id=None)
    assert registry.check_permission("reminder", "discord", ["admin"], guild_id=None)


@pytest.mark.asyncio
async def test_check_permission_discord_no_rows_for_guild(mock_db):
    """No permission rows for guild → denied unless admin."""
    registry = ActionRegistry(mock_db)
    defn = _make_definition("reminder")
    mock_db.list_discord_permissions = AsyncMock(return_value=[])
    mock_db.list_action_permissions = AsyncMock(return_value=[
        {"action_type": "reminder", "min_role_discord": "admin", "min_role_twitch": "admin", "enabled": 1},
    ])
    await registry.load_permissions()
    await registry.register("reminder", defn)

    assert not registry.check_permission("reminder", "discord", ["everyone", "role_100"], guild_id="guild1")
    assert registry.check_permission("reminder", "discord", ["admin"], guild_id="guild1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_action_registry.py -x -q`
Expected: FAIL — `check_permission` does not accept `guild_id`.

- [ ] **Step 3: Implement registry changes**

Rewrite `bot/core/actions/registry.py`:

```python
"""ActionRegistry — action catalog and role-based permission management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from loguru import logger


TWITCH_ROLE_HIERARCHY = ["everyone", "subscriber", "vip", "moderator", "admin"]


def _twitch_role_level(role: str) -> int:
    try:
        return TWITCH_ROLE_HIERARCHY.index(role)
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
    min_role_twitch: str = "admin"
    enabled: bool = True


class ActionRegistry:
    def __init__(self, db) -> None:
        self._db = db
        self._actions: dict[str, ActionDefinition] = {}
        self._permissions: dict[str, _PermissionEntry] = {}
        # Discord: (action_type, guild_id) → set of allowed role_ids
        self._discord_perms: dict[tuple[str, str], set[str]] = {}

    async def load_permissions(self) -> None:
        rows = await self._db.list_action_permissions()
        for row in rows:
            self._permissions[row["action_type"]] = _PermissionEntry(
                min_role_twitch=row["min_role_twitch"],
                enabled=bool(row["enabled"]),
            )
        # Load Discord guild-based permissions
        discord_rows = await self._db.list_discord_permissions()
        self._discord_perms.clear()
        for row in discord_rows:
            key = (row["action_type"], row["guild_id"])
            self._discord_perms.setdefault(key, set()).add(row["role_id"])
        logger.info("Loaded {} action permissions, {} discord guild entries",
                     len(self._permissions), len(self._discord_perms))

    async def register(self, action_type: str, definition: ActionDefinition) -> None:
        self._actions[action_type] = definition
        if action_type not in self._permissions:
            self._permissions[action_type] = _PermissionEntry()
            await self._db.upsert_action_permission(
                action_type, min_role_discord="admin", min_role_twitch="admin", enabled=1
            )
            logger.info("Registered action '{}' with default permissions", action_type)

    def get(self, action_type: str) -> ActionDefinition | None:
        return self._actions.get(action_type)

    def check_permission(self, action_type: str, platform: str,
                         user_roles: list[str], guild_id: str | None = None) -> bool:
        perm = self._permissions.get(action_type)
        if perm is None:
            return False
        if not perm.enabled:
            return False

        if platform == "discord":
            return self._check_discord_permission(action_type, user_roles, guild_id)
        else:
            return self._check_twitch_permission(perm, user_roles)

    def _check_discord_permission(self, action_type: str, user_roles: list[str],
                                   guild_id: str | None) -> bool:
        # Admin always passes
        if "admin" in user_roles:
            return True
        # No guild (DMs) → denied
        if guild_id is None:
            return False
        allowed = self._discord_perms.get((action_type, guild_id))
        if not allowed:
            return False
        if "everyone" in allowed:
            return True
        return bool(set(user_roles) & allowed)

    def _check_twitch_permission(self, perm: _PermissionEntry, user_roles: list[str]) -> bool:
        min_level = _twitch_role_level(perm.min_role_twitch)
        user_max = max((_twitch_role_level(r) for r in user_roles), default=-1)
        return user_max >= min_level

    def list_available(self, platform: str, user_roles: list[str],
                       guild_id: str | None = None) -> list[ActionDefinition]:
        return [
            defn for action_type, defn in self._actions.items()
            if self.check_permission(action_type, platform, user_roles, guild_id=guild_id)
        ]

    async def update_permission(self, action_type: str, platform: str, min_role: str) -> None:
        perm = self._permissions.get(action_type)
        if perm is None:
            return
        if platform == "twitch":
            perm.min_role_twitch = min_role
            await self._db.upsert_action_permission(
                action_type, min_role_discord="admin",
                min_role_twitch=perm.min_role_twitch, enabled=int(perm.enabled),
            )

    async def update_discord_permission(self, action_type: str, guild_id: str,
                                         roles: list[dict]) -> None:
        """Replace Discord roles for (action_type, guild_id). Updates cache + DB."""
        role_ids = {r["role_id"] for r in roles}
        self._discord_perms[(action_type, guild_id)] = role_ids
        await self._db.set_discord_permissions(action_type, guild_id, roles)

    async def get_discord_roles_for_action(self, action_type: str) -> dict[str, list[dict]]:
        """Return {guild_id: [{role_id, role_name}]} for an action type."""
        rows = await self._db.list_discord_permissions(action_type)
        result: dict[str, list[dict]] = {}
        for row in rows:
            result.setdefault(row["guild_id"], []).append(
                {"role_id": row["role_id"], "role_name": row["role_name"]}
            )
        return result

    async def set_enabled(self, action_type: str, enabled: bool) -> None:
        perm = self._permissions.get(action_type)
        if perm is None:
            return
        perm.enabled = enabled
        await self._db.upsert_action_permission(
            action_type, min_role_discord="admin",
            min_role_twitch=perm.min_role_twitch, enabled=int(enabled),
        )
```

- [ ] **Step 4: Fix existing tests that use old `check_permission` signature**

Update existing `test_check_permission_discord_hierarchy` to pass `guild_id` and set up `_discord_perms`. Update `mock_db` fixture to include `list_discord_permissions = AsyncMock(return_value=[])`.

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/test_action_registry.py -x -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add bot/core/actions/registry.py tests/test_action_registry.py
git commit -m "feat(registry): guild-based Discord permissions with in-memory cache"
```

---

### Task 3: Service — Reminder Type Routing + guild_id

**Files:**
- Modify: `bot/core/actions/service.py`
- Test: `tests/test_action_service.py`

- [ ] **Step 1: Write failing test for reminder routing**

Add to `tests/test_action_service.py`:

```python
@pytest.mark.asyncio
async def test_create_reminder_recurring_routes_by_schedule(service, mock_scheduler, mock_registry):
    """Reminder with interval/cron schedule routes to reminder_recurring type."""
    mock_registry.check_permission = MagicMock(return_value=True)
    mock_scheduler.schedule = AsyncMock(return_value=42)
    task_data = {
        "action_type": "reminder",
        "description": "Test recurring",
        "payload": {"message": "Hello"},
        "schedule": {"type": "interval", "interval_minutes": 10},
    }
    result = await service.create(task_data, "user1", "discord", ["admin"], "chan1", guild_id="guild1")
    assert result["status"] == "created"
    # Verify scheduler was called with reminder_recurring
    call_kwargs = mock_scheduler.schedule.call_args
    assert call_kwargs.kwargs.get("action_type") == "reminder_recurring" or call_kwargs[1].get("action_type") == "reminder_recurring"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_action_service.py::test_create_reminder_recurring_routes_by_schedule -x -v`

- [ ] **Step 3: Implement routing in service.py**

In `ActionService.create()`, after extracting `action_type` and `schedule`, add routing logic:

```python
# Route reminder to reminder_recurring based on schedule type
schedule_type = schedule.get("type", "")
if action_type == "reminder" and schedule_type in ("interval", "cron"):
    action_type = "reminder_recurring"
elif action_type == "reminder_recurring" and schedule_type == "once":
    action_type = "reminder"
```

Add `guild_id` parameter to `execute_tool()`, `create()`. Pass `guild_id` to `check_permission()`.

Update `execute_tool` to pass `guild_id`:
```python
async def execute_tool(
    self, name: str, args: dict, user_id: str, platform: str,
    user_roles: list[str], channel_id: str | None = None,
    guild_id: str | None = None,
) -> dict:
    if name == "create_action_task":
        return await self.create(args, user_id, platform, user_roles, channel_id, guild_id=guild_id)
    ...
```

Update `create` signature:
```python
async def create(
    self, task_data: dict, user_id: str, platform: str,
    user_roles: list[str], channel_id: str | None = None,
    guild_id: str | None = None,
) -> dict:
```

Pass `guild_id` to `check_permission`:
```python
if not self._registry.check_permission(action_type, platform, user_roles, guild_id=guild_id):
```

- [ ] **Step 4: Fix existing tests**

Update `service` fixture and existing tests to pass `guild_id` where needed. Update `mock_registry.check_permission` calls.

- [ ] **Step 5: Run all service tests**

Run: `python3 -m pytest tests/test_action_service.py -x -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add bot/core/actions/service.py tests/test_action_service.py
git commit -m "feat(service): route reminder→reminder_recurring by schedule type, add guild_id"
```

---

### Task 4: Register `reminder_recurring` Handler + Discord Handler Changes

**Files:**
- Modify: `bot/main.py`, `bot/discord/handlers.py`

- [ ] **Step 1: Register `reminder_recurring` in main.py**

After the existing `reminder` registration, add:

```python
await action_registry.register("reminder_recurring", ActionDefinition(
    name="reminder_recurring",
    description="Envoyer un message de rappel récurrent",
    parameters={"type": "object", "properties": {"message": {"type": "string"}}},
    handler=_reminder_handler,
))
```

- [ ] **Step 2: Update `_resolve_discord_roles` in handlers.py**

Replace the existing function:

```python
def _resolve_discord_roles(member) -> list[str]:
    """Return member's actual Discord role IDs plus 'everyone' and 'admin' if applicable."""
    roles = ["everyone"]
    roles.extend(str(r.id) for r in member.roles if not r.is_default())
    if member.guild_permissions.administrator:
        roles.append("admin")
    return roles
```

- [ ] **Step 3: Pass `guild_id` to `execute_tool` in handlers.py**

Find the `execute_tool` call (around line 497) and add `guild_id`:

```python
guild_id = str(message.guild.id) if message.guild else None
result = await action_service.execute_tool(
    name, args,
    user_id=str(message.author.id),
    platform="discord",
    user_roles=user_roles,
    channel_id=str(message.channel.id),
    guild_id=guild_id,
)
```

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass (696+).

- [ ] **Step 5: Commit**

```bash
git add bot/main.py bot/discord/handlers.py
git commit -m "feat: register reminder_recurring, real Discord role IDs, pass guild_id"
```

---

### Task 5: Dashboard API — Discord Roles Endpoint + Permission CRUD

**Files:**
- Modify: `bot/dashboard/routes/actions.py`

- [ ] **Step 1: Add discord roles endpoint**

```python
@router.get("/discord-roles")
async def discord_roles(request: Request) -> dict:
    state = request.app.state.wally
    bot = state.discord_bot
    if bot is None:
        return {"guilds": []}
    guilds = []
    for guild in bot.guilds:
        roles = [{"id": "everyone", "name": "everyone", "color": "#99aab5"}]
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if role.is_default() or role.is_bot_managed():
                continue
            color = f"#{role.color.value:06x}" if role.color.value else "#99aab5"
            roles.append({"id": str(role.id), "name": role.name, "color": color})
        guilds.append({"id": str(guild.id), "name": guild.name, "roles": roles})
    return {"guilds": guilds}
```

- [ ] **Step 2: Add discord permission update endpoint**

```python
@router.put("/permissions/{action_type}/discord")
async def update_discord_permission(request: Request, action_type: str) -> dict:
    state = request.app.state.wally
    body = await request.json()
    guild_id = body.get("guild_id", "")
    role_ids = body.get("role_ids", [])
    if not guild_id:
        return {"error": "guild_id required"}
    # Build roles list with names from bot cache
    roles = []
    for rid in role_ids:
        roles.append({"role_id": rid, "role_name": _resolve_role_name(state, guild_id, rid)})
    await state.action_service._registry.update_discord_permission(action_type, guild_id, roles)
    return {"status": "ok"}


def _resolve_role_name(state, guild_id: str, role_id: str) -> str:
    if role_id == "everyone":
        return "everyone"
    bot = state.discord_bot
    if bot is None:
        return ""
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return ""
    role = guild.get_role(int(role_id))
    return role.name if role else ""
```

- [ ] **Step 3: Update `list_permissions` to include discord roles**

```python
@router.get("/permissions")
async def list_permissions(request: Request) -> dict:
    state = request.app.state.wally
    rows = await state.db.list_action_permissions()
    perms = []
    for r in rows:
        p = dict(r)
        # Add discord roles per guild
        discord_roles = await state.action_service._registry.get_discord_roles_for_action(r["action_type"])
        p["discord_roles"] = discord_roles
        perms.append(p)
    return {"permissions": perms}
```

- [ ] **Step 4: Update existing `update_permission` to handle twitch only**

Remove `min_role_discord` handling from the existing PUT endpoint:

```python
@router.put("/permissions/{action_type}")
async def update_permission(request: Request, action_type: str) -> dict:
    state = request.app.state.wally
    body = await request.json()
    svc = state.action_service
    if "min_role_twitch" in body:
        await svc.update_permission(action_type, "twitch", body["min_role_twitch"])
    if "enabled" in body:
        await svc.set_action_enabled(action_type, bool(body["enabled"]))
    return {"status": "ok"}
```

- [ ] **Step 5: Run dashboard tests**

Run: `python3 -m pytest tests/test_dashboard_routes.py -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/routes/actions.py
git commit -m "feat(dashboard): discord roles endpoint + per-guild permission CRUD"
```

---

### Task 6: Dashboard Frontend — Multi-Select Role Chips

**Files:**
- Modify: `bot/dashboard/static/app.js`

- [ ] **Step 1: Remove hardcoded `DISCORD_ROLES` array**

Remove line: `var DISCORD_ROLES = ['everyone', 'subscriber', 'moderator', 'admin'];`

- [ ] **Step 2: Add global state for Discord guild roles**

At the top of the actions section:

```javascript
let _discordGuildRoles = []; // [{id, name, roles: [{id, name, color}]}]
```

- [ ] **Step 3: Add function to fetch Discord roles**

```javascript
async function loadDiscordRoles() {
  var r = await apiFetch('/api/actions/discord-roles');
  if (!r || !r.ok) return;
  var data = await r.json();
  _discordGuildRoles = data.guilds || [];
}
```

- [ ] **Step 4: Rewrite `_buildPermRow` for per-guild multi-select**

Replace the existing `_buildPermRow` function with one that:
- Shows action name, enabled toggle, Twitch dropdown (unchanged)
- For Discord: shows a section per guild with multi-select chip UI
- Each guild has a dropdown to add roles + chips for selected roles
- Chips show role name with color dot and remove button
- `everyone` always appears first

```javascript
function _buildPermRow(p) {
  var actionType = p.action_type;
  var enabled = p.enabled !== false && p.enabled !== 0;
  var discordRoles = p.discord_roles || {};

  var container = document.createElement('div');
  container.className = 'action-perm-row';

  // Header: action name + enabled + twitch
  var header = document.createElement('div');
  header.className = 'action-perm-header';

  var nameSpan = document.createElement('span');
  nameSpan.className = 'action-perm-name';
  nameSpan.textContent = actionType;
  header.appendChild(nameSpan);

  // Enabled toggle
  var toggleLabel = document.createElement('label');
  toggleLabel.className = 'action-toggle';
  var checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = enabled;
  checkbox.addEventListener('change', function() { updateActionPerm(actionType, 'enabled', this.checked); });
  var trackSpan = document.createElement('span');
  trackSpan.className = 'action-toggle-track';
  var thumbSpan = document.createElement('span');
  thumbSpan.className = 'action-toggle-thumb';
  trackSpan.appendChild(thumbSpan);
  toggleLabel.appendChild(checkbox);
  toggleLabel.appendChild(trackSpan);
  header.appendChild(toggleLabel);

  // Twitch dropdown
  var twitchSelect = document.createElement('select');
  twitchSelect.className = 'neo-select action-perm-select';
  TWITCH_ROLES.forEach(function(role) {
    var opt = document.createElement('option');
    opt.value = role;
    opt.textContent = role;
    if (p.min_role_twitch === role) opt.selected = true;
    twitchSelect.appendChild(opt);
  });
  twitchSelect.addEventListener('change', function() { updateActionPerm(actionType, 'min_role_twitch', this.value); });
  var twitchWrap = document.createElement('div');
  twitchWrap.className = 'action-perm-twitch';
  var twitchLabel = document.createElement('span');
  twitchLabel.className = 'action-perm-platform-label';
  twitchLabel.textContent = 'Twitch';
  twitchWrap.appendChild(twitchLabel);
  twitchWrap.appendChild(twitchSelect);
  header.appendChild(twitchWrap);

  container.appendChild(header);

  // Discord guilds section
  _discordGuildRoles.forEach(function(guild) {
    var guildSection = document.createElement('div');
    guildSection.className = 'action-perm-guild';

    var guildLabel = document.createElement('div');
    guildLabel.className = 'action-perm-guild-label';
    guildLabel.textContent = guild.name;
    guildSection.appendChild(guildLabel);

    var selectedRoles = (discordRoles[guild.id] || []).map(function(r) { return r.role_id; });

    // Chips container
    var chipsDiv = document.createElement('div');
    chipsDiv.className = 'action-role-chips';

    function renderChips() {
      chipsDiv.textContent = '';
      selectedRoles.forEach(function(rid) {
        var roleInfo = guild.roles.find(function(r) { return r.id === rid; });
        if (!roleInfo) return;
        var chip = document.createElement('span');
        chip.className = 'action-role-chip';
        var dot = document.createElement('span');
        dot.className = 'action-role-dot';
        dot.style.backgroundColor = roleInfo.color;
        chip.appendChild(dot);
        chip.appendChild(document.createTextNode(roleInfo.name));
        var removeBtn = document.createElement('button');
        removeBtn.className = 'action-role-chip-remove';
        removeBtn.textContent = '\u00d7';
        removeBtn.addEventListener('click', function() {
          selectedRoles = selectedRoles.filter(function(r) { return r !== rid; });
          saveDiscordPerm(actionType, guild.id, selectedRoles);
          renderChips();
          renderDropdown();
        });
        chip.appendChild(removeBtn);
        chipsDiv.appendChild(chip);
      });
    }

    // Add role dropdown
    var addSelect = document.createElement('select');
    addSelect.className = 'neo-select action-perm-add-role';

    function renderDropdown() {
      addSelect.textContent = '';
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = '+ Ajouter un r\u00f4le';
      placeholder.disabled = true;
      placeholder.selected = true;
      addSelect.appendChild(placeholder);
      guild.roles.forEach(function(role) {
        if (selectedRoles.indexOf(role.id) !== -1) return;
        var opt = document.createElement('option');
        opt.value = role.id;
        opt.textContent = role.name;
        addSelect.appendChild(opt);
      });
    }

    addSelect.addEventListener('change', function() {
      if (!this.value) return;
      selectedRoles.push(this.value);
      saveDiscordPerm(actionType, guild.id, selectedRoles);
      renderChips();
      renderDropdown();
    });

    renderChips();
    renderDropdown();

    guildSection.appendChild(chipsDiv);
    guildSection.appendChild(addSelect);
    container.appendChild(guildSection);
  });

  return container;
}
```

- [ ] **Step 5: Add `saveDiscordPerm` function**

```javascript
async function saveDiscordPerm(actionType, guildId, roleIds) {
  var r = await apiFetch('/api/actions/permissions/' + encodeURIComponent(actionType) + '/discord', {
    method: 'PUT',
    body: JSON.stringify({ guild_id: guildId, role_ids: roleIds }),
  });
  if (!r || !r.ok) { toast('Erreur mise \u00e0 jour permission Discord', 'error'); return; }
  toast('Permission Discord mise \u00e0 jour', 'success');
}
```

- [ ] **Step 6: Update `loadActionPermissions` to use div layout instead of table**

The permissions list now uses divs (not a table) since each row has variable height with guild sections:

```javascript
async function loadActionPermissions() {
  var container = document.getElementById('actions-perms-content');
  if (!container) return;
  container.textContent = '';
  var loading = document.createElement('div');
  loading.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
  loading.textContent = 'Chargement...';
  container.appendChild(loading);

  await loadDiscordRoles();
  var r = await apiFetch('/api/actions/permissions');
  if (!r || !r.ok) {
    loading.textContent = 'Erreur de chargement';
    return;
  }
  var data = await r.json();
  var perms = data.permissions || [];

  container.textContent = '';

  if (perms.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
    empty.textContent = 'Aucune permission configur\u00e9e';
    container.appendChild(empty);
    return;
  }

  var list = document.createElement('div');
  list.className = 'action-perms-list';
  perms.forEach(function(p) {
    list.appendChild(_buildPermRow(p));
  });
  container.appendChild(list);
}
```

- [ ] **Step 7: Add CSS for role chips and guild sections**

Add to the existing `<style>` in `index.html` or in app.js inline styles. Glassmorphism style per CLAUDE.md:

```css
.action-perm-row { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 16px; margin-bottom: 12px; }
.action-perm-header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.action-perm-name { font-weight: 600; min-width: 160px; }
.action-perm-platform-label { font-size: 0.85em; color: rgba(255,255,255,0.5); margin-right: 6px; }
.action-perm-twitch { display: flex; align-items: center; gap: 6px; }
.action-perm-guild { margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.05); }
.action-perm-guild-label { font-size: 0.85em; color: rgba(255,255,255,0.5); margin-bottom: 8px; }
.action-role-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.action-role-chip { display: inline-flex; align-items: center; gap: 4px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 4px 10px; font-size: 0.85em; }
.action-role-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.action-role-chip-remove { background: none; border: none; color: rgba(255,255,255,0.5); cursor: pointer; padding: 0 2px; font-size: 1.1em; }
.action-role-chip-remove:hover { color: #ef4444; }
.action-perm-add-role { max-width: 200px; }
```

- [ ] **Step 8: Commit**

```bash
git add bot/dashboard/static/app.js bot/dashboard/static/index.html
git commit -m "feat(dashboard): multi-select role chips per Discord guild for action permissions"
```

---

### Task 7: Integration Test + Build

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 2: Build and deploy**

```bash
docker compose build --no-cache
docker compose up -d
```

- [ ] **Step 3: Verify bot starts cleanly**

```bash
sleep 5 && docker compose logs wally --tail 30
```

Expected: No errors. "Loaded X action permissions, Y discord guild entries" in logs.

- [ ] **Step 4: Test on dashboard**

Open Actions → Permissions tab. Verify:
- `reminder` and `reminder_recurring` appear as separate rows
- Each row shows Discord guilds with role multi-select
- Adding/removing roles works
- Twitch dropdown still works

- [ ] **Step 5: Final commit if any fixes needed**
