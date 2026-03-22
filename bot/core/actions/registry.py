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

    def check_permission(self, action_type: str, platform: str, user_roles: list[str]) -> bool:
        perm = self._permissions.get(action_type)
        if perm is None:
            return False
        if not perm.enabled:
            return False
        hierarchy = DISCORD_ROLE_HIERARCHY if platform == "discord" else TWITCH_ROLE_HIERARCHY
        min_role = perm.min_role_discord if platform == "discord" else perm.min_role_twitch
        min_level = _role_level(min_role, hierarchy)
        user_max_level = max((_role_level(r, hierarchy) for r in user_roles), default=-1)
        return user_max_level >= min_level

    def list_available(self, platform: str, user_roles: list[str]) -> list[ActionDefinition]:
        return [
            defn for action_type, defn in self._actions.items()
            if self.check_permission(action_type, platform, user_roles)
        ]

    async def update_permission(self, action_type: str, platform: str, min_role: str) -> None:
        perm = self._permissions.get(action_type)
        if perm is None:
            return
        if platform == "discord":
            perm.min_role_discord = min_role
        else:
            perm.min_role_twitch = min_role
        await self._db.upsert_action_permission(
            action_type, min_role_discord=perm.min_role_discord,
            min_role_twitch=perm.min_role_twitch, enabled=int(perm.enabled),
        )

    async def set_enabled(self, action_type: str, enabled: bool) -> None:
        perm = self._permissions.get(action_type)
        if perm is None:
            return
        perm.enabled = enabled
        await self._db.upsert_action_permission(
            action_type, min_role_discord=perm.min_role_discord,
            min_role_twitch=perm.min_role_twitch, enabled=int(enabled),
        )
