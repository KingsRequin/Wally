from __future__ import annotations

import time
from typing import TYPE_CHECKING

import aiosqlite
from loguru import logger


class GalleryMixin:
    _conn: aiosqlite.Connection

    # Declared for type checking (implemented in Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Gallery ───────────────────────────────────────────────────────────────

    async def insert_gallery_image(
        self,
        id: str,
        title: str | None,
        prompt: str,
        revised_prompt: str | None,
        username: str,
        user_id: str,
        platform: str,
        file_path: str,
        model: str,
        quality: str,
        size: str,
        cost_usd: float,
    ) -> None:
        await self.execute(
            "INSERT INTO gallery_images "
            "(id, title, prompt, revised_prompt, username, user_id, platform, "
            " file_path, model, quality, size, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, title, prompt, revised_prompt, username, user_id, platform,
             file_path, model, quality, size, cost_usd),
        )

    async def delete_gallery_image(self, image_id: str) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM gallery_images WHERE id = ?", (image_id,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_gallery_images(
        self,
        search: str | None = None,
        sort_by: str = "date",
        user_filter: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        conditions = []
        params: list = []
        if search:
            conditions.append("(gi.prompt LIKE ? OR gi.title LIKE ? OR gi.username LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        if user_filter:
            conditions.append("gi.username = ?")
            params.append(user_filter)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        if sort_by == "votes":
            order = "COALESCE(v.votes, 0) DESC, gi.created_at DESC"
        else:
            order = "gi.created_at DESC"

        params.extend([limit, offset])
        sql = (
            "SELECT gi.*, COALESCE(v.votes, 0) AS votes "
            "FROM gallery_images gi "
            "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
            "  ON v.image_id = gi.id "
            f"{where} "
            f"ORDER BY {order} "
            "LIMIT ? OFFSET ?"
        )
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_gallery_image(self, image_id: str) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT gi.*, COALESCE(v.votes, 0) AS votes "
            "FROM gallery_images gi "
            "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
            "  ON v.image_id = gi.id "
            "WHERE gi.id = ?",
            (image_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))

    async def toggle_gallery_vote(self, image_id: str, user_id: str) -> bool:
        """Toggle a vote. Returns True if the vote was added, False if removed."""
        cursor = await self._conn.execute(
            "SELECT 1 FROM gallery_votes WHERE image_id = ? AND user_id = ?",
            (image_id, user_id),
        )
        exists = await cursor.fetchone()
        if exists:
            await self._conn.execute(
                "DELETE FROM gallery_votes WHERE image_id = ? AND user_id = ?",
                (image_id, user_id),
            )
            await self._conn.commit()
            return False
        else:
            await self._conn.execute(
                "INSERT INTO gallery_votes (image_id, user_id) VALUES (?, ?)",
                (image_id, user_id),
            )
            await self._conn.commit()
            return True

    async def update_gallery_title(self, image_id: str, title: str) -> None:
        await self.execute(
            "UPDATE gallery_images SET title = ? WHERE id = ?",
            (title, image_id),
        )

    async def get_user_image_count_today(self, user_id: str) -> int:
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM gallery_images "
            "WHERE user_id = ? AND date(created_at) = date('now')",
            (user_id,),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_total_image_count_today(self) -> int:
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM gallery_images WHERE date(created_at) = date('now')"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_random_gallery_image(self, filter_mode: str = "all") -> dict | None:
        """Return a random gallery image.

        filter_mode:
          "top"    -- weighted random favouring highly-voted images
          "recent" -- restricted to images created in the last 48 hours
          "all"    -- any image
        """
        if filter_mode == "top":
            sql = (
                "SELECT gi.*, COALESCE(v.votes, 0) AS votes "
                "FROM gallery_images gi "
                "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
                "  ON v.image_id = gi.id "
                "ORDER BY RANDOM() * 1.0 / (COALESCE(v.votes, 0) + 1) "
                "LIMIT 1"
            )
            params: tuple = ()
        elif filter_mode == "recent":
            sql = (
                "SELECT gi.*, COALESCE(v.votes, 0) AS votes "
                "FROM gallery_images gi "
                "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
                "  ON v.image_id = gi.id "
                "WHERE gi.created_at >= datetime('now', '-48 hours') "
                "ORDER BY RANDOM() LIMIT 1"
            )
            params = ()
        else:
            sql = (
                "SELECT gi.*, COALESCE(v.votes, 0) AS votes "
                "FROM gallery_images gi "
                "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
                "  ON v.image_id = gi.id "
                "ORDER BY RANDOM() LIMIT 1"
            )
            params = ()
        cursor = await self._conn.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))

    async def get_gallery_images_for_date(self, date_str: str) -> list[dict]:
        """Return all gallery images created on the given date (YYYY-MM-DD)."""
        cursor = await self._conn.execute(
            "SELECT gi.*, COALESCE(v.votes, 0) AS votes "
            "FROM gallery_images gi "
            "LEFT JOIN (SELECT image_id, COUNT(*) AS votes FROM gallery_votes GROUP BY image_id) v "
            "  ON v.image_id = gi.id "
            "WHERE date(gi.created_at) = ? "
            "ORDER BY gi.created_at ASC",
            (date_str,),
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def has_voted(self, image_id: str, user_id: str) -> bool:
        cursor = await self._conn.execute(
            "SELECT 1 FROM gallery_votes WHERE image_id = ? AND user_id = ?",
            (image_id, user_id),
        )
        return (await cursor.fetchone()) is not None
