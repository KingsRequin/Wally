from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import aiosqlite
from loguru import logger


class TrustMixin:
    _conn: aiosqlite.Connection

    # Declared for type checking (implemented in Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Timeout / mute ───────────────────────────────────────────────────────

    async def add_timeout(
        self,
        user_id: str,
        guild_id: str,
        duration_minutes: int,
        anger_level: float,
    ):
        now = time.time()
        await self.execute(
            "INSERT INTO timeout_log "
            "(user_id, guild_id, triggered_at, expires_at, anger_level) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, guild_id, now, now + duration_minutes * 60, anger_level),
        )

    async def is_muted(self, user_id: str, guild_id: str) -> bool:
        row = await self.fetch_one(
            "SELECT expires_at FROM timeout_log "
            "WHERE user_id=? AND guild_id=? "
            "ORDER BY expires_at DESC LIMIT 1",
            (user_id, guild_id),
        )
        return row is not None and float(row["expires_at"]) > time.time()

    async def count_recent_triggers(
        self, user_id: str, guild_id: str, window_seconds: int = 300
    ) -> int:
        row = await self.fetch_one(
            "SELECT COUNT(*) AS cnt FROM timeout_log "
            "WHERE user_id=? AND guild_id=? AND triggered_at >= ?",
            (user_id, guild_id, time.time() - window_seconds),
        )
        return int(row["cnt"]) if row else 0

    # ── Welcome tracking ─────────────────────────────────────────────────────

    async def is_welcomed(self, user_id: str, guild_id: str) -> bool:
        row = await self.fetch_one(
            "SELECT 1 FROM welcomed WHERE user_id=? AND guild_id=?",
            (user_id, guild_id),
        )
        return row is not None

    async def mark_welcomed(self, user_id: str, guild_id: str):
        await self.execute(
            "INSERT OR IGNORE INTO welcomed (user_id, guild_id, welcomed_at) "
            "VALUES (?, ?, ?)",
            (user_id, guild_id, time.time()),
        )

    # ── Trust scores ─────────────────────────────────────────────────────────

    async def get_trust_score(self, platform: str, user_id: str) -> float:
        row = await self.fetch_one(
            "SELECT score FROM trust_scores WHERE user_id=? AND platform=?",
            (user_id, platform),
        )
        return float(row["score"]) if row else 0.0

    async def update_trust_score(self, platform: str, user_id: str, delta: float):
        current = await self.get_trust_score(platform, user_id)
        new_score = max(0.0, min(1.0, current + delta))
        await self.execute(
            "INSERT INTO trust_scores (user_id, platform, score, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, platform) DO UPDATE SET "
            "score=excluded.score, updated_at=excluded.updated_at",
            (user_id, platform, new_score, time.time()),
        )

    # ── Love scores ────────────────────────────────────────────────────────────

    async def get_love_score(self, platform: str, user_id: str, decay_lambda: float = 0.1) -> float:
        """Retourne le love score avec lazy decay applique."""
        cursor = await self._conn.execute(
            "SELECT love, love_updated_at FROM trust_scores WHERE user_id=? AND platform=?",
            (user_id, platform),
        )
        row = await cursor.fetchone()
        if not row or row["love"] is None:
            return 0.0
        love = float(row["love"])
        updated_at = float(row["love_updated_at"] or 0)
        if love <= 0 or updated_at <= 0:
            return 0.0
        # Lazy decay
        elapsed_days = (time.time() - updated_at) / 86400.0
        if elapsed_days > 0:
            decayed = love * math.exp(-decay_lambda * elapsed_days)
            if decayed < 0.01:
                decayed = 0.0
            # Save decayed value back if significant change
            if abs(decayed - love) > 0.01:
                await self.execute(
                    "UPDATE trust_scores SET love=?, love_updated_at=? WHERE user_id=? AND platform=?",
                    (decayed, time.time(), user_id, platform),
                )
            return round(decayed, 3)
        return round(love, 3)

    async def get_trust_scores_batch(
        self, users: list[tuple[str, str]],
    ) -> dict[tuple[str, str], float]:
        """Fetch trust scores for multiple (platform, user_id) pairs in one query."""
        if not users:
            return {}
        rows = await self.fetch_all("SELECT platform, user_id, score FROM trust_scores")
        lookup = {(r["platform"], r["user_id"]): float(r["score"]) for r in rows}
        return {(p, uid): lookup.get((p, uid), 0.0) for p, uid in users}

    async def get_love_scores_batch(
        self, users: list[tuple[str, str]], decay_lambda: float = 0.1,
    ) -> dict[tuple[str, str], float]:
        """Fetch love scores for multiple (platform, user_id) pairs in one query with lazy decay."""
        if not users:
            return {}
        rows = await self.fetch_all(
            "SELECT platform, user_id, love, love_updated_at FROM trust_scores"
        )
        now = time.time()
        result: dict[tuple[str, str], float] = {}
        for r in rows:
            love = float(r["love"] or 0)
            updated_at = float(r["love_updated_at"] or 0)
            if love <= 0 or updated_at <= 0:
                result[(r["platform"], r["user_id"])] = 0.0
                continue
            elapsed_days = (now - updated_at) / 86400.0
            if elapsed_days > 0:
                decayed = love * math.exp(-decay_lambda * elapsed_days)
                if decayed < 0.01:
                    decayed = 0.0
            else:
                decayed = love
            result[(r["platform"], r["user_id"])] = round(decayed, 3)
        user_set = set(users)
        return {k: result.get(k, 0.0) for k in user_set}

    async def update_love_score(self, platform: str, user_id: str, delta: float, decay_lambda: float = 0.1) -> None:
        """Met a jour le love score -- applique decay, puis ajoute delta, clamp [0, 1]."""
        current = await self.get_love_score(platform, user_id, decay_lambda)
        new_value = max(0.0, min(1.0, current + delta))
        await self.execute(
            "INSERT INTO trust_scores (user_id, platform, score, updated_at, love, love_updated_at) "
            "VALUES (?, ?, 0.0, ?, ?, ?) "
            "ON CONFLICT(user_id, platform) DO UPDATE SET love=?, love_updated_at=?",
            (user_id, platform, time.time(), new_value, time.time(), new_value, time.time()),
        )
