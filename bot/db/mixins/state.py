from __future__ import annotations

import time
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    pass


class StateMixin:
    """Petits états qui doivent survivre à un redémarrage.

    Volontairement minuscule : une clé, une valeur texte. Pour ce qui n'a ni la
    forme d'un fait mémorisé, ni celle d'un réglage de `config.yaml` — le dernier
    salon vocal rejoint, par exemple, qui n'est ni une préférence ni un souvenir.
    """

    _conn: aiosqlite.Connection

    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    async def set_state(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, str(value), time.time()),
        )

    async def get_state(self, key: str) -> str | None:
        row = await self.fetch_one("SELECT value FROM bot_state WHERE key = ?", (key,))
        return row["value"] if row else None
