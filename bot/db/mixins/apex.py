from __future__ import annotations

import time
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    pass


class ApexMixin:
    """Les comptes Apex déclarés par les gens.

    Un compte par personne : `identity` (« twitch:123 », « discord:456 ») est la
    clé. `display_name` garde le pseudo de plateforme au moment de la liaison,
    pour que « les stats de xeforce » retrouve le compte sans dépendre du
    système d'alias.
    """

    _conn: aiosqlite.Connection

    # Déclarés pour le type-check (implémentés dans Database)
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    async def apex_link_account(
        self,
        *,
        identity: str,
        display_name: str,
        apex_name: str,
        apex_platform: str,
        uid: str | None = None,
    ) -> None:
        """Associe un compte Apex à quelqu'un. Redéclarer remplace l'ancien."""
        await self.execute(
            """
            INSERT INTO apex_accounts (identity, display_name, apex_name, apex_platform, uid, linked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity) DO UPDATE SET
                display_name = excluded.display_name,
                apex_name    = excluded.apex_name,
                apex_platform= excluded.apex_platform,
                uid          = excluded.uid,
                linked_at    = excluded.linked_at
            """,
            (identity, display_name, apex_name, apex_platform, uid, time.time()),
        )

    async def apex_get_account(self, identity: str) -> "aiosqlite.Row | None":
        return await self.fetch_one(
            "SELECT * FROM apex_accounts WHERE identity = ?", (identity,)
        )

    async def apex_find_by_display_name(self, display_name: str) -> "aiosqlite.Row | None":
        """Le compte de la personne qui portait ce pseudo, casse ignorée."""
        if not display_name:
            return None
        return await self.fetch_one(
            "SELECT * FROM apex_accounts WHERE lower(display_name) = lower(?) "
            "ORDER BY linked_at DESC LIMIT 1",
            (display_name,),
        )
