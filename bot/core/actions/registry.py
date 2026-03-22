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
