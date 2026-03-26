# Action Permissions Redesign — Spec

## Summary

Split reminder action type into `reminder` (one-shot) and `reminder_recurring` (interval/cron).
Replace the fixed Discord role hierarchy with real Discord server roles, per-guild, multi-select.
Keep Twitch permissions unchanged (fixed hierarchy) but also split by reminder type.

## 1. Action Type Split

### New types
- `reminder` — schedule type `once` only
- `reminder_recurring` — schedule types `interval` and `cron`

### Routing
`ActionService.create()` overrides the LLM-provided `action_type` based on `schedule.type`:
- If `action_type == "reminder"` and `schedule.type` in (`interval`, `cron`) → treat as `reminder_recurring`
- If `action_type == "reminder_recurring"` and `schedule.type == "once"` → treat as `reminder`

The LLM tool definition keeps only `reminder` in the enum. The service routes internally based on schedule type.
The LLM does not need to know about `reminder_recurring` — the split is purely for permissions.

### Handler registration
Both types share the same `_reminder_handler` in `main.py`. Two `register()` calls with the same handler.

### Existing data
Existing `action_tasks` rows with `action_type = "reminder"` and recurring schedule types are left as-is.
Only new tasks get the split type. No data migration needed.

## 2. Discord Permissions — Per-Guild Real Roles

### New DB table

```sql
CREATE TABLE IF NOT EXISTS action_permissions_discord (
    action_type TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    role_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (action_type, guild_id, role_id)
);
```

- `role_id = "everyone"` is the special "no role required" entry.
- Multiple rows per (action_type, guild_id) = multi-select.
- `role_name` is best-effort, updated when saved via dashboard. Not authoritative.

### `min_role_discord` column — kept but ignored
The `min_role_discord` column stays in `action_permissions` for SQLite compatibility (no DROP COLUMN).
Code stops reading/writing it. The column becomes dead weight, harmless.

### Default permissions for new action types
When `register()` creates a new action type, no rows are inserted into `action_permissions_discord`.
This means no Discord guild has permission → effectively admin-only (since "no rows = denied unless admin").
Admin configures permissions via the dashboard after registration.

## 3. Discord Role Fetching

### No separate storage
The API endpoint reads directly from `discord_bot.guilds` (discord.py's internal gateway cache) on each call.
No separate `_guild_roles` dict needed — discord.py keeps guild state up to date via gateway events,
so newly created roles appear automatically.

### API endpoint
`GET /api/actions/discord-roles` → `{"guilds": [{"id": "...", "name": "...", "roles": [{"id": "...", "name": "...", "color": "#hex"}]}]}`

- Iterates `discord_bot.guilds`, reads `guild.roles`.
- Excludes `@everyone` (default role) and bot-managed roles.
- Adds `everyone` as virtual option with `id: "everyone"` at the top of each guild's list.
- The discord bot reference is available via `request.app.state.wally.discord_bot`.

## 4. Permission Check Changes

### `_resolve_discord_roles` (handlers.py)
Returns the member's actual role IDs as strings, plus `"everyone"`:
```python
def _resolve_discord_roles(member) -> list[str]:
    roles = ["everyone"]
    roles.extend(str(r.id) for r in member.roles if not r.is_default())
    if member.guild_permissions.administrator:
        roles.append("admin")
    return roles
```

### `guild_id` propagation
- `execute_tool()` signature gains `guild_id: str | None = None`.
- Discord handler passes `str(message.guild.id)` if `message.guild` else `None`.
- Twitch handler passes `None` (Twitch uses fixed hierarchy, guild_id ignored).
- DMs: `guild_id = None` → Discord permission check falls back to admin-only.
- `ActionService.create()` and `check_permission()` also gain `guild_id`.

### `ActionRegistry.check_permission` (registry.py)
Gains `guild_id: str | None = None` parameter.

For Discord:
1. If `guild_id` is None → denied (unless user has `"admin"` in roles).
2. Look up in-memory cache for `(action_type, guild_id)` → set of allowed role IDs.
3. If no entries → denied (unless user has `"admin"` in roles).
4. If `"everyone"` in allowed set → grant.
5. Otherwise → grant if intersection of user's role IDs and allowed role IDs is non-empty.

For Twitch: unchanged (fixed hierarchy with `min_role_twitch`).

### In-memory cache for Discord permissions
`ActionRegistry` gains `_discord_perms: dict[tuple[str, str], set[str]]` keyed by `(action_type, guild_id)`.
Loaded at boot via `load_permissions()`. Updated in-memory + DB on dashboard changes.
`check_permission` stays synchronous — no DB hit on the hot path.

### `list_available` method
Also gains `guild_id` parameter. Passes it through to `check_permission`.

## 5. Dashboard UI Changes

### Permissions tab layout
Each action type gets an expandable row:
- **Action name** | **Enabled** toggle | **Twitch** dropdown (fixed hierarchy)
- Expanded section: per-guild Discord role selection
  - Guild name header
  - Multi-select chips/tags with role names and color dots
  - `everyone` option at the top of each guild
  - Selected roles shown as removable chips

### API changes
- `GET /api/actions/permissions` — returns permissions with nested `discord_roles: {guild_id: [{role_id, role_name}]}` per action type
- `PUT /api/actions/permissions/{action_type}/discord` — body: `{"guild_id": "...", "role_ids": ["...", "..."]}`
  - Replaces all role entries for that (action_type, guild_id) pair
  - Also updates `role_name` for each role_id from the available roles
- `PUT /api/actions/permissions/{action_type}` — handles `min_role_twitch` and `enabled` only (no longer writes `min_role_discord`)
- `GET /api/actions/discord-roles` — returns available roles per guild

## 6. Files to Modify

| File | Change |
|------|--------|
| `bot/core/actions/service.py` | Route `reminder` → `reminder_recurring` based on schedule type. Pass `guild_id` through. |
| `bot/core/actions/registry.py` | New in-memory cache `_discord_perms`. New `check_permission` logic for Discord. Load/store discord role permissions. Keep `DISCORD_ROLE_HIERARCHY` removed. Add `guild_id` to `check_permission`, `list_available`. |
| `bot/main.py` | Register both `reminder` and `reminder_recurring` with same handler. |
| `bot/db/database.py` | New table `action_permissions_discord`. New CRUD methods. Stop writing `min_role_discord`. |
| `bot/discord/handlers.py` | `_resolve_discord_roles` returns real role IDs. Pass `guild_id` to `execute_tool`. |
| `bot/dashboard/routes/actions.py` | New endpoint for discord roles. Update permission endpoints. |
| `bot/dashboard/static/app.js` | Multi-select UI with role chips per guild. Fetch real roles. Remove hardcoded `DISCORD_ROLES`. |
| Tests | Update mocks for new permission model, new action types. |

## 7. Out of Scope

- Twitch role changes
- Migration of existing `min_role_discord` values to new table
- Migration of existing `action_tasks` rows with `action_type = "reminder"` + recurring schedule
