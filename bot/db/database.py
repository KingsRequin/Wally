from __future__ import annotations
import asyncio
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

CREATE TABLE IF NOT EXISTS daily_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  REAL    NOT NULL,
    channel_id TEXT    NOT NULL,
    author     TEXT    NOT NULL,
    content    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_log_ts ON daily_log(timestamp);

CREATE TABLE IF NOT EXISTS user_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id TEXT NOT NULL,
    alias_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    resolved_at REAL,
    UNIQUE(canonical_id, alias_id)
);
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
        # Nettoyage automatique des vieilles entrées daily_log au démarrage
        try:
            await conn.execute(
                "DELETE FROM daily_log WHERE timestamp < ?",
                (time.time() - 7 * 86400,)
            )
            await conn.commit()
        except Exception:
            pass  # table absente au premier démarrage — CREATE TABLE IF NOT EXISTS s'en charge
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

    async def get_emotion_snapshots_since(self, since: float) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT * FROM emotion_history WHERE snapshot_at >= ? ORDER BY snapshot_at ASC",
            (since,),
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

    async def sync_memory_users_from_qdrant(self, qdrant_url: str) -> int:
        """Imports into memory_users the user_ids found in Qdrant.

        Returns the number of newly inserted users.
        Silent if Qdrant is unavailable.
        """
        try:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=qdrant_url)
            user_ids: set[str] = set()
            offset = None
            while True:
                points, next_offset = await asyncio.to_thread(
                    client.scroll,
                    collection_name="wally_memory",
                    limit=100,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                for point in points:
                    uid = (point.payload or {}).get("user_id")
                    if uid and isinstance(uid, str) and ":" in uid:
                        platform_prefix = uid.split(":")[0]
                        if platform_prefix:  # skip malformed entries with empty prefix
                            user_ids.add(uid)
                if next_offset is None:
                    break
                offset = next_offset

            inserted = 0
            before = {u["user_id"] for u in await self.list_memory_users()}
            for uid in user_ids:
                platform = uid.split(":")[0]
                await self.upsert_memory_user(uid, platform, username="")
                if uid not in before:
                    inserted += 1

            if inserted:
                logger.info("sync_memory_users_from_qdrant: {n} nouveaux utilisateurs importés", n=inserted)
            return inserted

        except Exception as exc:
            logger.warning("sync_memory_users_from_qdrant échoué: {e}", e=exc)
            return 0

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

    # ── Daily log (journal persistence) ──────────────────────────────────────────

    async def log_daily_message(
        self, channel_id: str, author: str, content: str, timestamp: float | None = None
    ) -> None:
        await self.execute(
            "INSERT INTO daily_log (timestamp, channel_id, author, content) VALUES (?, ?, ?, ?)",
            (timestamp if timestamp is not None else time.time(), channel_id, author, content),
        )

    async def get_today_messages(self) -> list[dict]:
        midnight = datetime.now(_TZ_DB).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        rows = await self.fetch_all(
            "SELECT timestamp, channel_id, author, content FROM daily_log "
            "WHERE timestamp >= ? ORDER BY timestamp ASC",
            (midnight,),
        )
        return [
            {
                "timestamp": float(row["timestamp"]),
                "channel_id": row["channel_id"],
                "author": row["author"],
                "content": row["content"],
            }
            for row in rows
        ]

    async def cleanup_old_daily_log(self, days: int = 7) -> None:
        cutoff = time.time() - days * 86400
        await self.execute("DELETE FROM daily_log WHERE timestamp < ?", (cutoff,))

    # ── User links (account linking) ─────────────────────────────────────────

    async def upsert_link_proposal(
        self, canonical_id: str, alias_id: str, confidence: float
    ) -> None:
        """Insère ou met à jour une proposition de liaison (status=pending, update confidence)."""
        async with self._conn.execute(
            """INSERT INTO user_links (canonical_id, alias_id, confidence, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)
               ON CONFLICT(canonical_id, alias_id)
               DO UPDATE SET confidence=excluded.confidence, status='pending', created_at=excluded.created_at""",
            (canonical_id, alias_id, confidence, time.time()),
        ):
            pass
        await self._conn.commit()

    async def list_link_proposals(self, status: str | None = None) -> list[dict]:
        """Retourne les propositions de liaison.

        Chaque dict contient: id, canonical_id, alias_id, confidence, status, created_at, resolved_at.
        """
        if status:
            cursor = await self._conn.execute(
                "SELECT id, canonical_id, alias_id, confidence, status, created_at, resolved_at "
                "FROM user_links WHERE status = ? ORDER BY confidence DESC",
                (status,),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT id, canonical_id, alias_id, confidence, status, created_at, resolved_at "
                "FROM user_links ORDER BY confidence DESC"
            )
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "canonical_id": r[1],
                "alias_id": r[2],
                "confidence": r[3],
                "status": r[4],
                "created_at": r[5],
                "resolved_at": r[6],
            }
            for r in rows
        ]

    async def accept_link(self, link_id: int) -> dict | None:
        """Marque la liaison comme acceptée, retourne canonical_id et alias_id."""
        cursor = await self._conn.execute(
            "UPDATE user_links SET status='accepted', resolved_at=? WHERE id=? RETURNING canonical_id, alias_id",
            (time.time(), link_id),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return {"canonical_id": row[0], "alias_id": row[1]} if row else None

    async def reject_link(self, link_id: int) -> None:
        """Marque la liaison comme rejetée."""
        await self._conn.execute(
            "UPDATE user_links SET status='rejected', resolved_at=? WHERE id=?",
            (time.time(), link_id),
        )
        await self._conn.commit()

    async def get_alias_map(self) -> dict[str, str]:
        """Retourne {alias_id: canonical_id} pour toutes les liaisons acceptées."""
        cursor = await self._conn.execute(
            "SELECT alias_id, canonical_id FROM user_links WHERE status='accepted'"
        )
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}
