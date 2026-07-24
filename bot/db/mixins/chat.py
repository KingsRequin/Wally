from __future__ import annotations

import time

import aiosqlite


class ChatMixin:
    _conn: aiosqlite.Connection

    # Declared for type checking (implemented in Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Chat connections ──────────────────────────────────────────

    async def insert_chat_connection(
        self, discord_id: str, username: str, avatar_url: str | None
    ) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO chat_connections (discord_id, username, avatar_url, connected_at)"
            " VALUES (?, ?, ?, ?)",
            (discord_id, username, avatar_url, time.time()),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def update_chat_disconnection(self, conn_id: int, message_count: int) -> None:
        await self.execute(
            "UPDATE chat_connections SET disconnected_at = ?, message_count = ? WHERE id = ?",
            (time.time(), message_count, conn_id),
        )

    async def increment_chat_connection_messages(self, conn_id: int) -> None:
        await self.execute(
            "UPDATE chat_connections SET message_count = message_count + 1 WHERE id = ?",
            (conn_id,),
        )

    async def list_chat_connections(self, limit: int = 50) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM chat_connections ORDER BY connected_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # ── Web chat messages ─────────────────────────────────────────────────────

    async def insert_chat_message(self, sender_id, username, avatar_url, content, is_wally, created_at):
        cursor = await self._conn.execute(
            "INSERT INTO chat_messages (sender_id, username, avatar_url, content, is_wally, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sender_id, username, avatar_url, content, int(is_wally), created_at))
        await self._conn.commit()
        return cursor.lastrowid

    async def load_chat_history(self, limit=50):
        cursor = await self._conn.execute("SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,))
        rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]

    async def load_chat_history_for_day(self, date_str: str):
        """Load chat messages for a specific day (YYYY-MM-DD format)."""
        import datetime
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        start = dt.replace(hour=0, minute=0, second=0).timestamp()
        end = start + 86400
        cursor = await self._conn.execute(
            "SELECT * FROM chat_messages WHERE created_at >= ? AND created_at < ? ORDER BY id ASC",
            (start, end),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def list_chat_session_dates(self):
        """Return list of dates (YYYY-MM-DD) that have chat messages, most recent first."""
        cursor = await self._conn.execute(
            "SELECT DISTINCT date(created_at, 'unixepoch', 'localtime') as day "
            "FROM chat_messages ORDER BY day DESC"
        )
        rows = await cursor.fetchall()
        return [row["day"] for row in rows]

    async def load_chat_messages_for_user(self, discord_id: str, limit: int = 100) -> list[dict]:
        """Messages web envoyés par un utilisateur (is_wally=0), plus récents d'abord."""
        cursor = await self._conn.execute(
            "SELECT * FROM chat_messages WHERE sender_id = ? AND is_wally = 0 "
            "ORDER BY created_at DESC LIMIT ?",
            (f"discord:{discord_id}", limit))
        return [dict(row) for row in await cursor.fetchall()]

    async def cleanup_old_chat_messages(self, days=30):
        cutoff = time.time() - days * 86400
        await self._conn.execute("DELETE FROM chat_messages WHERE created_at < ?", (cutoff,))
        await self._conn.commit()

    # ── Chat refresh tokens ───────────────────────────────────────────────────

    async def store_refresh_token(self, token_hash, discord_id, username, avatar_url, expires_at):
        await self._conn.execute(
            "INSERT OR REPLACE INTO chat_refresh_tokens (token_hash, discord_id, username, avatar_url, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash, discord_id, username, avatar_url, expires_at))
        await self._conn.commit()

    async def get_refresh_token(self, token_hash):
        cursor = await self._conn.execute(
            "SELECT * FROM chat_refresh_tokens WHERE token_hash = ? AND expires_at > ?",
            (token_hash, time.time()))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_refresh_token(self, token_hash):
        await self._conn.execute("DELETE FROM chat_refresh_tokens WHERE token_hash = ?", (token_hash,))
        await self._conn.commit()

    async def cleanup_expired_refresh_tokens(self):
        await self._conn.execute("DELETE FROM chat_refresh_tokens WHERE expires_at < ?", (time.time(),))
        await self._conn.commit()

    # ── Chat bans ─────────────────────────────────────────────────────────────

    async def ban_chat_user(self, discord_id: str, username: str | None = None, reason: str | None = None) -> None:
        did = str(discord_id)
        await self._conn.execute(
            "INSERT OR REPLACE INTO chat_bans (discord_id, username, reason, banned_at) VALUES (?, ?, ?, ?)",
            (did, username, reason, time.time()))
        # Révoque les refresh tokens du banni → accès web coupé immédiatement
        await self._conn.execute("DELETE FROM chat_refresh_tokens WHERE discord_id = ?", (did,))
        await self._conn.commit()

    async def unban_chat_user(self, discord_id: str) -> None:
        await self._conn.execute("DELETE FROM chat_bans WHERE discord_id = ?", (str(discord_id),))
        await self._conn.commit()

    async def is_chat_user_banned(self, discord_id: str) -> bool:
        cursor = await self._conn.execute(
            "SELECT 1 FROM chat_bans WHERE discord_id = ?", (str(discord_id),))
        return await cursor.fetchone() is not None

    async def list_chat_bans(self) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM chat_bans ORDER BY banned_at DESC")
        return [dict(row) for row in await cursor.fetchall()]
