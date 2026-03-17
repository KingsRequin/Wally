from __future__ import annotations
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

_TZ_DB = ZoneInfo("Europe/Paris")

import aiosqlite
from loguru import logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    purpose TEXT
);

CREATE TABLE IF NOT EXISTS timeout_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    triggered_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    anger_level REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS welcomed (
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    welcomed_at REAL NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS trust_scores (
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.5,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, platform)
);

CREATE TABLE IF NOT EXISTS emotion_state (
    emotion    TEXT PRIMARY KEY,
    value      REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS emotion_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at REAL NOT NULL,
    anger       REAL NOT NULL DEFAULT 0.0,
    joy         REAL NOT NULL DEFAULT 0.0,
    sadness     REAL NOT NULL DEFAULT 0.0,
    curiosity   REAL NOT NULL DEFAULT 0.0,
    boredom     REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS memory_users (
    user_id      TEXT PRIMARY KEY,
    platform     TEXT NOT NULL,
    last_updated REAL NOT NULL,
    username     TEXT
);

CREATE INDEX IF NOT EXISTS idx_emotion_history_ts ON emotion_history(snapshot_at);
"""


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    @classmethod
    async def create(cls, path: str = "data/wally.db") -> "Database":
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.executescript(SCHEMA)
        await conn.commit()
        # Migration: ajouter username à memory_users si absent
        try:
            await conn.execute("ALTER TABLE memory_users ADD COLUMN username TEXT")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass  # colonne déjà présente
        logger.info("Database initialized at {path}", path=path)
        return cls(conn)

    async def close(self):
        await self._conn.close()

    async def fetch_all(self, query: str, params=()) -> list:
        async with self._conn.execute(query, params) as cursor:
            return await cursor.fetchall()

    async def fetch_one(self, query: str, params=()) -> Optional[aiosqlite.Row]:
        async with self._conn.execute(query, params) as cursor:
            return await cursor.fetchone()

    async def execute(self, query: str, params=()):
        await self._conn.execute(query, params)
        await self._conn.commit()

    # ── Cost tracking ────────────────────────────────────────────────────────

    async def log_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        purpose: str = "",
    ):
        await self.execute(
            "INSERT INTO cost_log "
            "(timestamp, model, input_tokens, output_tokens, cost_usd, purpose) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), model, input_tokens, output_tokens, cost_usd, purpose),
        )

    async def get_cost_since(self, since_timestamp: float) -> float:
        row = await self.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total "
            "FROM cost_log WHERE timestamp >= ?",
            (since_timestamp,),
        )
        return float(row["total"]) if row else 0.0

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
        return float(row["score"]) if row else 0.5

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

    # ── Emotion persistence ───────────────────────────────────────────────────

    async def load_emotion_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_state")
        return {row["emotion"]: float(row["value"]) for row in rows}

    async def save_emotion_state(self, state: dict[str, float]) -> None:
        now = time.time()
        for emotion, value in state.items():
            await self.execute(
                "INSERT INTO emotion_state (emotion, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (emotion, value, now),
            )

    async def insert_emotion_snapshot(self, state: dict[str, float]) -> None:
        await self.execute(
            "INSERT INTO emotion_history "
            "(snapshot_at, anger, joy, sadness, curiosity, boredom) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                state.get("anger", 0.0),
                state.get("joy", 0.0),
                state.get("sadness", 0.0),
                state.get("curiosity", 0.0),
                state.get("boredom", 0.0),
            ),
        )

    async def get_today_emotion_snapshots(self) -> list[dict]:
        midnight = datetime.now(_TZ_DB).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        rows = await self.fetch_all(
            "SELECT * FROM emotion_history WHERE snapshot_at >= ? ORDER BY snapshot_at ASC",
            (midnight,),
        )
        return [dict(row) for row in rows]

    async def cleanup_old_emotion_history(self, days: int = 7) -> None:
        cutoff = time.time() - days * 86400
        await self.execute(
            "DELETE FROM emotion_history WHERE snapshot_at < ?",
            (cutoff,),
        )

    # ── Memory users tracking ─────────────────────────────────────────────────────

    async def upsert_memory_user(self, user_id: str, platform: str, username: str = "") -> None:
        await self.execute(
            "INSERT INTO memory_users(user_id, platform, last_updated, username) VALUES(?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            "   last_updated=excluded.last_updated,"
            "   username=COALESCE(NULLIF(excluded.username,''), memory_users.username)",
            (user_id, platform, time.time(), username or None),
        )

    async def list_memory_users(self, q: str | None = None) -> list[dict]:
        # LEFT JOIN avec trust_scores : la clé memory_users.user_id est "platform:raw_id"
        # alors que trust_scores.user_id est "raw_id" — on extrait via SUBSTR.
        sql = (
            "SELECT m.user_id, m.platform, m.last_updated, m.username, "
            "COALESCE(t.score, 0.5) AS trust_score "
            "FROM memory_users m "
            "LEFT JOIN trust_scores t "
            "  ON t.platform = m.platform "
            "  AND t.user_id = SUBSTR(m.user_id, LENGTH(m.platform) + 2)"
        )
        params: tuple = ()
        if q:
            sql += " WHERE (m.user_id LIKE ? OR m.username LIKE ?)"
            params = (f"%{q}%", f"%{q}%")
        sql += " ORDER BY m.last_updated DESC"
        async with self._conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [
            {
                "user_id": r["user_id"],
                "platform": r["platform"],
                "last_updated": r["last_updated"],
                "username": r["username"],
                "trust_score": round(float(r["trust_score"]), 2),
            }
            for r in rows
        ]
