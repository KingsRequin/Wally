from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import aiosqlite
from loguru import logger


class ActionMixin:
    _conn: aiosqlite.Connection

    # Declared for type checking (implemented in Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Action Tasks ──────────────────────────────────────────────────────

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

    # ── Action Permissions ────────────────────────────────────────────────

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

    # ── Setup Wizard ─────────────────────────────────────────────────────────────

    async def create_setup_invite(
        self, token: str, expires_at: float | None, is_preview: int = 0
    ) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO setup_invites (token, created_at, expires_at, is_preview)"
            " VALUES (?, ?, ?, ?)",
            (token, time.time(), expires_at, is_preview),
        )
        await self._conn.commit()

    async def get_setup_invite(self, token: str) -> aiosqlite.Row | None:
        async with self._conn.execute(
            "SELECT * FROM setup_invites WHERE token = ?", (token,)
        ) as cur:
            return await cur.fetchone()

    async def use_setup_invite(self, token: str, slug: str, port: int) -> None:
        await self._conn.execute(
            "UPDATE setup_invites SET used_at = ?, slug = ?, port = ? WHERE token = ?",
            (time.time(), slug, port, token),
        )
        await self._conn.commit()

    async def revoke_setup_invite(self, token: str) -> None:
        await self._conn.execute(
            "UPDATE setup_invites SET expires_at = ? WHERE token = ?",
            (-1, token),  # sentinel: -1 means revoked, distinguishable from expired
        )
        await self._conn.commit()

    async def list_setup_invites(self) -> list:
        async with self._conn.execute(
            "SELECT * FROM setup_invites WHERE is_preview = 0 ORDER BY created_at DESC"
        ) as cur:
            return await cur.fetchall()

    async def save_setup_session(self, token: str, data: dict) -> None:
        existing = await self.get_setup_session(token)
        merged = {**existing, **data}
        await self._conn.execute(
            "INSERT OR REPLACE INTO setup_sessions (token, step_data, updated_at)"
            " VALUES (?, ?, ?)",
            (token, json.dumps(merged), time.time()),
        )
        await self._conn.commit()

    async def get_setup_session(self, token: str) -> dict:
        async with self._conn.execute(
            "SELECT step_data FROM setup_sessions WHERE token = ?", (token,)
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row["step_data"]) if row else {}

    async def next_setup_port(self) -> int:
        async with self._conn.execute(
            "SELECT MAX(port) as max_port FROM setup_invites WHERE port IS NOT NULL"
        ) as cur:
            row = await cur.fetchone()
        max_port = row["max_port"] if row and row["max_port"] else 8080
        return max_port + 1
