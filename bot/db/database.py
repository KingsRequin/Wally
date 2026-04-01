from __future__ import annotations
import asyncio
import json
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
    purpose TEXT,
    user_id TEXT
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
    score REAL NOT NULL DEFAULT 0.0,
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

CREATE INDEX IF NOT EXISTS idx_cost_log_ts ON cost_log(timestamp);

CREATE TABLE IF NOT EXISTS daily_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  REAL    NOT NULL,
    channel_id TEXT    NOT NULL,
    author     TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    platform   TEXT    NOT NULL DEFAULT 'discord'
);

CREATE INDEX IF NOT EXISTS idx_daily_log_ts ON daily_log(timestamp);

CREATE TABLE IF NOT EXISTS emotion_peaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    emotion TEXT NOT NULL,
    value REAL NOT NULL,
    trigger_user TEXT,
    trigger_message TEXT,
    channel_id TEXT,
    platform TEXT
);

CREATE INDEX IF NOT EXISTS idx_emotion_peaks_ts ON emotion_peaks(timestamp);

CREATE TABLE IF NOT EXISTS emotional_memory (
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    emotion TEXT NOT NULL,
    affinity REAL NOT NULL DEFAULT 0.0,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL,
    PRIMARY KEY (user_id, platform, emotion)
);

CREATE TABLE IF NOT EXISTS emotion_mood (
    emotion TEXT PRIMARY KEY,
    value REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS emotion_fatigue (
    emotion TEXT PRIMARY KEY,
    value REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

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

CREATE TABLE IF NOT EXISTS session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_msgs_channel ON session_messages(channel_id);

CREATE TABLE IF NOT EXISTS web_search_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    query TEXT NOT NULL,
    results_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_web_search_log_ts ON web_search_log(timestamp);

CREATE TABLE IF NOT EXISTS jokes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    reaction_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS opinions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL UNIQUE,
    opinion TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id TEXT NOT NULL,
    username TEXT NOT NULL,
    avatar_url TEXT,
    content TEXT NOT NULL,
    is_wally BOOLEAN DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at);

CREATE TABLE IF NOT EXISTS chat_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    username TEXT NOT NULL,
    avatar_url TEXT,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS user_aliases (
    nickname     TEXT PRIMARY KEY,
    canonical_uid TEXT NOT NULL,
    display_name TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'llm',
    confidence   REAL NOT NULL DEFAULT 0.0,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    memory_text TEXT NOT NULL,
    question TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    attempts INTEGER NOT NULL DEFAULT 0,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_questions_user ON memory_questions(user_id, resolved);
CREATE INDEX IF NOT EXISTS idx_memory_questions_priority ON memory_questions(user_id, resolved, priority, created_at);

CREATE TABLE IF NOT EXISTS chat_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id TEXT NOT NULL,
    username TEXT NOT NULL,
    avatar_url TEXT,
    connected_at REAL NOT NULL,
    disconnected_at REAL,
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chat_connections_time ON chat_connections(connected_at DESC);

CREATE TABLE IF NOT EXISTS gallery_images (
    id TEXT PRIMARY KEY,
    title TEXT,
    prompt TEXT NOT NULL,
    revised_prompt TEXT,
    username TEXT NOT NULL,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    file_path TEXT NOT NULL,
    model TEXT NOT NULL,
    quality TEXT NOT NULL,
    size TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_gallery_created ON gallery_images(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gallery_user ON gallery_images(username);

CREATE TABLE IF NOT EXISTS gallery_votes (
    image_id TEXT NOT NULL REFERENCES gallery_images(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (image_id, user_id)
);

CREATE TABLE IF NOT EXISTS action_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    creator_id TEXT NOT NULL,
    creator_platform TEXT NOT NULL,
    target_channel TEXT,
    target_platform TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    schedule_type TEXT NOT NULL,
    schedule_spec TEXT NOT NULL DEFAULT '{}',
    max_executions INTEGER,
    execution_count INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    next_run_at TEXT,
    last_run_at TEXT
);

CREATE TABLE IF NOT EXISTS action_permissions (
    action_type TEXT PRIMARY KEY,
    min_role_discord TEXT NOT NULL DEFAULT 'admin',
    min_role_twitch TEXT NOT NULL DEFAULT 'admin',
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS action_permissions_discord (
    action_type TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    role_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (action_type, guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS setup_invites (
    token       TEXT PRIMARY KEY,
    slug        TEXT,
    created_at  REAL NOT NULL,
    expires_at  REAL,
    used_at     REAL,
    is_preview  INTEGER NOT NULL DEFAULT 0,
    port        INTEGER
);

CREATE TABLE IF NOT EXISTS setup_sessions (
    token       TEXT PRIMARY KEY,
    step_data   TEXT NOT NULL DEFAULT '{}',
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS persistent_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL UNIQUE,
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS twitch_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT    NOT NULL,
    joined_at   REAL    NOT NULL,
    left_at     REAL,
    duration_s  INTEGER,
    msg_count   INTEGER DEFAULT 0,
    summary     TEXT
);
"""


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    @classmethod
    async def create(cls, path: str = "data/wally.db") -> "Database":
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(SCHEMA)
        await conn.commit()
        # Migration: ajouter username à memory_users si absent
        try:
            await conn.execute("ALTER TABLE memory_users ADD COLUMN username TEXT")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass  # colonne déjà présente
        # Migration: ajouter user_id à cost_log si absent
        try:
            await conn.execute("ALTER TABLE cost_log ADD COLUMN user_id TEXT")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass  # colonne déjà présente
        # Migration: index sur cost_log.timestamp
        try:
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_log_ts ON cost_log(timestamp)")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass
        # Migration: ajouter platform à daily_log si absent
        try:
            await conn.execute("ALTER TABLE daily_log ADD COLUMN platform TEXT NOT NULL DEFAULT 'discord'")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass
        # Migration: add love columns to trust_scores
        try:
            await conn.execute("ALTER TABLE trust_scores ADD COLUMN love REAL DEFAULT 0.0")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass
        try:
            await conn.execute("ALTER TABLE trust_scores ADD COLUMN love_updated_at REAL DEFAULT 0")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass
        # Migration: add is_reply to session_messages if absent
        try:
            await conn.execute("ALTER TABLE session_messages ADD COLUMN is_reply INTEGER DEFAULT 0")
            await conn.commit()
        except Exception:
            pass  # Column already exists
        # Migration: add avatar_url to memory_users
        try:
            await conn.execute("ALTER TABLE memory_users ADD COLUMN avatar_url TEXT DEFAULT NULL")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass
        # Migration: add memory_count to memory_users
        try:
            await conn.execute("ALTER TABLE memory_users ADD COLUMN memory_count INTEGER DEFAULT 0")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass
        # Nettoyage automatique des vieilles entrées daily_log au démarrage
        try:
            await conn.execute(
                "DELETE FROM daily_log WHERE timestamp < ?",
                (time.time() - 7 * 86400,)
            )
            await conn.commit()
        except aiosqlite.OperationalError:
            pass  # table absente au premier démarrage — CREATE TABLE IF NOT EXISTS s'en charge
        # Migration: trust score baseline 0.5 → 0.0
        try:
            await conn.execute(
                "ALTER TABLE trust_scores ADD COLUMN trust_v2_migrated INTEGER DEFAULT 0"
            )
            await conn.commit()
            # Column just created → migration not yet run
            await conn.execute(
                "UPDATE trust_scores SET score = MAX(score - 0.5, 0.0)"
            )
            await conn.commit()
            logger.info("Trust score migration applied: all scores shifted by -0.5")
        except aiosqlite.OperationalError:
            pass  # Column already exists → migration already applied
        # Migration: add last_attempt_at to memory_questions
        try:
            await conn.execute(
                "ALTER TABLE memory_questions ADD COLUMN last_attempt_at REAL DEFAULT NULL"
            )
            await conn.commit()
        except aiosqlite.OperationalError:
            pass
        # Migration: add UNIQUE constraint on (user_id, question) for memory_questions
        try:
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_questions_unique_q"
                " ON memory_questions(user_id, question)"
            )
            await conn.commit()
        except Exception:
            pass
        logger.info("Database initialized at {path}", path=path)
        return cls(conn)

    # ── Twitch visits ─────────────────────────────────────────────────────────────

    async def start_twitch_visit(self, channel: str) -> int:
        """Démarre une visite sur une chaîne invitée. Retourne l'id de la ligne."""
        now = time.time()
        cursor = await self._conn.execute(
            "INSERT INTO twitch_visits (channel, joined_at) VALUES (?, ?)",
            (channel, now),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def end_twitch_visit(
        self,
        visit_id: int,
        left_at: float,
        msg_count: int,
        summary: str | None,
    ) -> None:
        """Complète une visite avec durée, comptage et résumé LLM."""
        joined_at = await self._get_visit_joined_at(visit_id)
        await self._conn.execute(
            "UPDATE twitch_visits SET left_at = ?, duration_s = ?, msg_count = ?, summary = ? WHERE id = ?",
            (left_at, int(left_at - joined_at), msg_count, summary, visit_id),
        )
        await self._conn.commit()

    async def _get_visit_joined_at(self, visit_id: int) -> float:
        """Helper interne : récupère joined_at pour calculer duration_s."""
        row = await self.fetch_one(
            "SELECT joined_at FROM twitch_visits WHERE id = ?", (visit_id,)
        )
        if row is None:
            logger.warning("_get_visit_joined_at: visit_id {id} not found, duration_s will be 0", id=visit_id)
            return time.time()
        return float(row["joined_at"])

    async def get_twitch_visits_for_date(self, date_str: str) -> list[dict]:
        """Retourne les visites dont joined_at tombe dans la journée (Europe/Paris).

        date_str : format YYYY-MM-DD
        """
        from datetime import date as date_type
        target = date_type.fromisoformat(date_str)
        midnight = datetime.combine(target, datetime.min.time(), tzinfo=_TZ_DB).timestamp()
        end = midnight + 86400
        rows = await self.fetch_all(
            "SELECT * FROM twitch_visits WHERE joined_at >= ? AND joined_at < ? ORDER BY joined_at ASC",
            (midnight, end),
        )
        return [dict(row) for row in rows]

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

    # ── Persistent notes ─────────────────────────────────────────────────────

    async def upsert_persistent_note(self, title: str, content: str) -> None:
        now = time.time()
        await self._conn.execute(
            """
            INSERT INTO persistent_notes (title, content, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(title) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at
            """,
            (title.strip(), content.strip(), now, now),
        )
        await self._conn.commit()

    async def delete_persistent_note(self, title: str) -> bool:
        async with self._conn.execute(
            "DELETE FROM persistent_notes WHERE title = ?", (title.strip(),)
        ) as cursor:
            affected = cursor.rowcount
        await self._conn.commit()
        return affected > 0

    async def get_persistent_notes(self) -> list[dict]:
        async with self._conn.execute(
            "SELECT id, title, content, created_at, updated_at FROM persistent_notes ORDER BY updated_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Cost tracking ────────────────────────────────────────────────────────

    async def log_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        purpose: str = "",
        user_id: str | None = None,
    ):
        await self.execute(
            "INSERT INTO cost_log "
            "(timestamp, model, input_tokens, output_tokens, cost_usd, purpose, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), model, input_tokens, output_tokens, cost_usd, purpose, user_id),
        )

    async def get_cost_since(self, since_timestamp: float) -> float:
        row = await self.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total "
            "FROM cost_log WHERE timestamp >= ?",
            (since_timestamp,),
        )
        return float(row["total"]) if row else 0.0

    async def get_daily_costs(self, since_ts: float, until_ts: float | None = None) -> list[dict]:
        """Coûts agrégés par jour (date ISO, cost_usd total)."""
        end = until_ts or time.time()
        rows = await self.fetch_all(
            "SELECT DATE(timestamp, 'unixepoch', 'localtime') AS date, "
            "SUM(cost_usd) AS cost "
            "FROM cost_log WHERE timestamp >= ? AND timestamp <= ? "
            "GROUP BY date ORDER BY date ASC",
            (since_ts, end),
        )
        return [{"date": r["date"], "cost": round(float(r["cost"]), 6)} for r in rows]

    async def get_cost_breakdown(self, since_ts: float, group_by: str) -> list[dict]:
        """Agrège les coûts par model, purpose, ou user_id."""
        allowed = {"model", "purpose", "user_id"}
        if group_by not in allowed:
            raise ValueError(f"group_by must be one of {allowed}")
        rows = await self.fetch_all(
            f"SELECT {group_by} AS grp, SUM(cost_usd) AS total, COUNT(*) AS count "
            f"FROM cost_log WHERE timestamp >= ? "
            f"GROUP BY {group_by} ORDER BY total DESC",
            (since_ts,),
        )
        return [
            {"key": r["grp"], "total": round(float(r["total"]), 6), "count": int(r["count"])}
            for r in rows
        ]

    async def get_cost_stats(self, since_ts: float, until_ts: float | None = None) -> dict:
        """Total et nombre d'appels entre since_ts et until_ts."""
        if until_ts is not None:
            row = await self.fetch_one(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS count "
                "FROM cost_log WHERE timestamp >= ? AND timestamp < ?",
                (since_ts, until_ts),
            )
        else:
            row = await self.fetch_one(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS count "
                "FROM cost_log WHERE timestamp >= ?",
                (since_ts,),
            )
        total = float(row["total"]) if row else 0.0
        count = int(row["count"]) if row else 0
        return {"total": round(total, 6), "count": count}

    async def get_cost_logs_paginated(
        self,
        since_ts: float,
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        """Journal paginé des appels LLM avec résolution username."""
        offset = (page - 1) * limit
        rows = await self.fetch_all(
            "SELECT cl.timestamp, cl.model, cl.input_tokens, cl.output_tokens, "
            "cl.cost_usd, cl.purpose, cl.user_id, mu.username "
            "FROM cost_log cl "
            "LEFT JOIN memory_users mu ON mu.user_id = cl.user_id "
            "WHERE cl.timestamp >= ? "
            "ORDER BY cl.timestamp DESC "
            "LIMIT ? OFFSET ?",
            (since_ts, limit, offset),
        )
        count_row = await self.fetch_one(
            "SELECT COUNT(*) AS n FROM cost_log WHERE timestamp >= ?",
            (since_ts,),
        )
        total = count_row["n"] if count_row else 0
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "logs": [
                {
                    "datetime": datetime.fromtimestamp(r["timestamp"], tz=_TZ_DB).strftime("%Y-%m-%d %H:%M:%S"),
                    "model": r["model"] or "",
                    "input_tokens": r["input_tokens"] or 0,
                    "output_tokens": r["output_tokens"] or 0,
                    "cost_usd": round(float(r["cost_usd"]), 6),
                    "purpose": r["purpose"] or "",
                    "user_id": r["user_id"] or "",
                    "username": r["username"] or "",
                }
                for r in rows
            ],
        }

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
        """Retourne le love score avec lazy decay appliqué."""
        import math
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
        import math
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
        """Met à jour le love score — applique decay, puis ajoute delta, clamp [0, 1]."""
        current = await self.get_love_score(platform, user_id, decay_lambda)
        new_value = max(0.0, min(1.0, current + delta))
        await self.execute(
            "INSERT INTO trust_scores (user_id, platform, score, updated_at, love, love_updated_at) "
            "VALUES (?, ?, 0.0, ?, ?, ?) "
            "ON CONFLICT(user_id, platform) DO UPDATE SET love=?, love_updated_at=?",
            (user_id, platform, time.time(), new_value, time.time(), new_value, time.time()),
        )

    # ── Emotion persistence ───────────────────────────────────────────────────

    async def load_emotion_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_state")
        return {row["emotion"]: float(row["value"]) for row in rows}

    async def save_emotion_state(self, state: dict[str, float]) -> None:
        if not state:
            return
        now = time.time()
        query = (
            "INSERT INTO emotion_state (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
        )
        params = [(emotion, value, now) for emotion, value in state.items()]
        await self._conn.executemany(query, params)
        await self._conn.commit()

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

    # ── Emotional memory & mood/fatigue persistence ──────────────────────────────

    async def upsert_emotional_memory(
        self, user_id: str, platform: str, emotion: str, affinity: float, interaction_count: int,
    ) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        await self.execute(
            "INSERT INTO emotional_memory (user_id, platform, emotion, affinity, interaction_count, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, platform, emotion) DO UPDATE SET "
            "affinity=excluded.affinity, interaction_count=excluded.interaction_count, last_updated=excluded.last_updated",
            (user_id, platform, emotion, affinity, interaction_count, now),
        )

    async def get_emotional_memory(self, user_id: str, platform: str) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT emotion, affinity, interaction_count, last_updated "
            "FROM emotional_memory WHERE user_id = ? AND platform = ?",
            (user_id, platform),
        )
        return [dict(r) for r in rows]

    async def save_mood_state(self, state: dict[str, float]) -> None:
        now = time.time()
        query = (
            "INSERT INTO emotion_mood (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
        )
        params = [(e, v, now) for e, v in state.items()]
        await self._conn.executemany(query, params)
        await self._conn.commit()

    async def load_mood_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_mood")
        return {row["emotion"]: float(row["value"]) for row in rows}

    async def save_fatigue_state(self, state: dict[str, float]) -> None:
        now = time.time()
        query = (
            "INSERT INTO emotion_fatigue (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
        )
        params = [(e, v, now) for e, v in state.items()]
        await self._conn.executemany(query, params)
        await self._conn.commit()

    async def load_fatigue_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_fatigue")
        return {row["emotion"]: float(row["value"]) for row in rows}

    # ── Memory users tracking ─────────────────────────────────────────────────────

    @staticmethod
    def _fix_platform(user_id: str, platform: str) -> tuple[str, str]:
        """Ensure platform matches the raw ID format in user_id.

        Discord snowflakes are 17-20 digit integers.
        Twitch numeric IDs are typically ≤12 digits.
        If the raw ID doesn't match the claimed platform, swap to the correct one.
        """
        if ":" not in user_id:
            return user_id, platform

        prefix, raw = user_id.split(":", 1)
        if not raw.isdigit():
            return user_id, platform

        digits = len(raw)
        is_snowflake = digits >= 13  # Discord snowflakes: 17-20 digits, never <13
        is_twitch_id = digits <= 12  # Twitch numeric IDs: up to ~10 digits

        fixed_platform = prefix
        if prefix == "twitch" and is_snowflake:
            fixed_platform = "discord"
            user_id = f"discord:{raw}"
            logger.warning(
                "Platform fix: {old} → {new} (snowflake detected in twitch ns)",
                old=f"twitch:{raw}", new=user_id,
            )
        elif prefix == "discord" and is_twitch_id:
            fixed_platform = "twitch"
            user_id = f"twitch:{raw}"
            logger.warning(
                "Platform fix: {old} → {new} (short ID detected in discord ns)",
                old=f"discord:{raw}", new=user_id,
            )

        return user_id, fixed_platform

    async def upsert_memory_user(
        self, user_id: str, platform: str, username: str = "", avatar_url: str = "",
    ) -> None:
        user_id, platform = self._fix_platform(user_id, platform)
        await self.execute(
            "INSERT INTO memory_users(user_id, platform, last_updated, username, avatar_url)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            "   last_updated=excluded.last_updated,"
            "   platform=excluded.platform,"
            "   username=COALESCE(NULLIF(excluded.username,''), memory_users.username),"
            "   avatar_url=COALESCE(NULLIF(excluded.avatar_url,''), memory_users.avatar_url)",
            (user_id, platform, time.time(), username or None, avatar_url or None),
        )

    # ── Memory questions ───────────────────────────────────────────────────

    async def insert_memory_question(
        self, user_id: str, memory_text: str, question: str, priority: str = "medium"
    ) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO memory_questions (user_id, memory_text, question, priority, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, memory_text, question, priority, time.time()),
        )

    async def get_pending_question(
        self, user_id: str, max_attempts: int = 3, retry_after_seconds: float = 86400.0
    ) -> dict | None:
        retry_cutoff = time.time() - retry_after_seconds
        cursor = await self._conn.execute(
            "SELECT * FROM memory_questions"
            " WHERE user_id = ? AND resolved = 0"
            "   AND (attempts < ? OR (last_attempt_at IS NOT NULL AND last_attempt_at < ?))"
            " ORDER BY"
            "   CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,"
            "   created_at ASC"
            " LIMIT 1",
            (user_id, max_attempts, retry_cutoff),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_pending_questions(self, user_id: str) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM memory_questions WHERE user_id = ? AND resolved = 0",
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def increment_question_attempts(self, question_id: int) -> None:
        await self.execute(
            "UPDATE memory_questions SET attempts = attempts + 1, last_attempt_at = ? WHERE id = ?",
            (time.time(), question_id),
        )

    async def resolve_question(self, question_id: int) -> None:
        await self.execute(
            "UPDATE memory_questions SET resolved = 1 WHERE id = ?",
            (question_id,),
        )

    async def update_question(self, question_id: int, question: str) -> None:
        await self.execute(
            "UPDATE memory_questions SET question = ? WHERE id = ?",
            (question, question_id),
        )

    async def delete_question(self, question_id: int) -> None:
        await self.execute(
            "DELETE FROM memory_questions WHERE id = ?",
            (question_id,),
        )

    async def cleanup_old_questions(self, max_age_days: int = 30) -> None:
        cutoff = time.time() - max_age_days * 86400
        await self.execute(
            "DELETE FROM memory_questions WHERE resolved = 1 OR created_at < ?",
            (cutoff,),
        )

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

    async def get_last_interaction(self, user_id: str) -> float | None:
        """Retourne le timestamp de la dernière interaction d'un utilisateur, ou None."""
        cursor = await self._conn.execute(
            "SELECT last_updated FROM memory_users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return float(row["last_updated"]) if row else None

    async def insert_joke(self, content: str, channel_id: str, platform: str, reaction_count: int) -> None:
        """Stocke une blague réussie."""
        await self.execute(
            "INSERT INTO jokes (content, channel_id, platform, reaction_count, created_at) VALUES (?,?,?,?,?)",
            (content, channel_id, platform, reaction_count, time.time()),
        )

    async def get_recent_jokes(self, channel_id: str, limit: int = 3) -> list[str]:
        """Retourne les dernières blagues réussies du canal."""
        cursor = await self._conn.execute(
            "SELECT content FROM jokes WHERE channel_id=? ORDER BY created_at DESC LIMIT ?",
            (channel_id, limit),
        )
        rows = await cursor.fetchall()
        return [row["content"] for row in rows]

    async def upsert_opinion(self, topic: str, opinion: str) -> None:
        """Insère ou met à jour une opinion sur un sujet."""
        now = time.time()
        await self.execute(
            "INSERT INTO opinions (topic, opinion, created_at, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(topic) DO UPDATE SET opinion=excluded.opinion, updated_at=excluded.updated_at",
            (topic, opinion, now, now),
        )

    async def get_opinions(self, limit: int = 10) -> list[dict]:
        """Retourne les opinions les plus récemment mises à jour."""
        cursor = await self._conn.execute(
            "SELECT topic, opinion FROM opinions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [{"topic": row["topic"], "opinion": row["opinion"]} for row in rows]

    async def cleanup_opinions(self, max_age_days: int = 30, max_count: int = 10) -> None:
        """Supprime les opinions expirées et garde les max_count plus récentes."""
        cutoff = time.time() - max_age_days * 86400
        await self.execute("DELETE FROM opinions WHERE updated_at < ?", (cutoff,))
        # Keep only max_count most recent
        await self.execute(
            "DELETE FROM opinions WHERE id NOT IN "
            "(SELECT id FROM opinions ORDER BY updated_at DESC LIMIT ?)",
            (max_count,),
        )

    async def delete_memory_user(self, user_id: str) -> None:
        """Supprime un utilisateur de memory_users (après fusion de comptes)."""
        await self.execute("DELETE FROM memory_users WHERE user_id = ?", (user_id,))

    async def sync_memory_users_from_qdrant(self, qdrant_url: str, collection_name: str | None = None) -> int:
        """Imports into memory_users the user_ids found in Qdrant.

        Returns the number of newly inserted users.
        Silent if Qdrant is unavailable.
        collection_name defaults to QDRANT_COLLECTION_NAME env var (fallback: "wally_memory").
        """
        import os
        if collection_name is None:
            collection_name = os.getenv("QDRANT_COLLECTION_NAME", "wally_memory")
        try:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=qdrant_url)
            user_ids: set[str] = set()
            offset = None
            while True:
                points, next_offset = await asyncio.to_thread(
                    client.scroll,
                    collection_name=collection_name,
                    limit=100,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                for point in points:
                    uid = (point.payload or {}).get("user_id")
                    if uid and isinstance(uid, str) and ":" in uid:
                        parts = uid.split(":")
                        # Fix double-prefix (e.g. "discord:discord:123" → "discord:123")
                        if len(parts) >= 3 and parts[0] == parts[1]:
                            uid = f"{parts[0]}:{':'.join(parts[2:])}"
                            logger.warning("Sync: fixed double-prefix → {uid}", uid=uid)
                        # Fix cross-platform IDs before adding
                        platform_prefix = uid.split(":")[0]
                        uid, platform_prefix = self._fix_platform(uid, platform_prefix)
                        if platform_prefix:  # skip malformed entries with empty prefix
                            user_ids.add(uid)
                if next_offset is None:
                    break
                offset = next_offset

            inserted = 0
            before = {u["user_id"] for u in await self.list_memory_users()}
            # Ne pas recréer les alias déjà liés (sinon ils réapparaissent en double)
            alias_map = await self.get_alias_map()
            alias_ids = set(alias_map.keys())
            from bot.core.memory import GLOBAL_USER_ID
            for uid in user_ids:
                if uid == GLOBAL_USER_ID:
                    continue  # namespace global — pas un vrai utilisateur
                if uid in alias_ids:
                    continue  # alias lié — ne pas recréer dans memory_users
                if uid in before:
                    continue  # déjà connu — ne pas écraser last_updated
                platform = uid.split(":")[0]
                await self.upsert_memory_user(uid, platform, username="")
                inserted += 1

            if inserted:
                logger.info("sync_memory_users_from_qdrant: {n} nouveaux utilisateurs importés", n=inserted)
            return inserted

        except Exception as exc:
            logger.warning("sync_memory_users_from_qdrant échoué: {e}", e=exc)
            return 0

    async def list_memory_users(self, q: str | None = None, include_no_memory: bool = False) -> list[dict]:
        # LEFT JOIN avec trust_scores : la clé memory_users.user_id est "platform:raw_id"
        # alors que trust_scores.user_id est "raw_id" — on extrait via SUBSTR.
        sql = (
            "SELECT m.user_id, m.platform, m.last_updated, m.username, m.avatar_url, "
            "COALESCE(m.memory_count, 0) AS memory_count, "
            "COALESCE(t.score, 0.0) AS trust_score, 1 AS in_memory_users "
            "FROM memory_users m "
            "LEFT JOIN trust_scores t "
            "  ON t.platform = m.platform "
            "  AND t.user_id = SUBSTR(m.user_id, LENGTH(m.platform) + 2)"
        )
        params: list = []
        if q:
            sql += " WHERE (m.user_id LIKE ? OR m.username LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])

        if include_no_memory:
            # UNION avec trust_scores pour les utilisateurs sans mémoire
            union = (
                " UNION ALL "
                "SELECT (t2.platform || ':' || t2.user_id) AS user_id, "
                "t2.platform, t2.updated_at AS last_updated, NULL AS username, "
                "NULL AS avatar_url, 0 AS memory_count, "
                "t2.score AS trust_score, 0 AS in_memory_users "
                "FROM trust_scores t2 "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM memory_users m2 "
                "  WHERE m2.user_id = t2.platform || ':' || t2.user_id"
                ") AND NOT EXISTS ("
                "  SELECT 1 FROM user_links ul "
                "  WHERE ul.alias_id = t2.platform || ':' || t2.user_id "
                "  AND ul.status = 'accepted'"
                ")"
            )
            if q:
                union += " AND (t2.user_id LIKE ? OR t2.platform || ':' || t2.user_id LIKE ?)"
                params.extend([f"%{q}%", f"%{q}%"])
            sql += union

        sql += " ORDER BY in_memory_users DESC, last_updated DESC"
        async with self._conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
        return [
            {
                "user_id": r["user_id"],
                "platform": r["platform"],
                "last_updated": r["last_updated"],
                "username": r["username"],
                "avatar_url": r["avatar_url"] if "avatar_url" in r.keys() else None,
                "memory_count": r["memory_count"],
                "trust_score": round(float(r["trust_score"]), 2),
                "in_memory_users": bool(r["in_memory_users"]),
            }
            for r in rows
        ]

    # ── Daily log (journal persistence) ──────────────────────────────────────────

    async def log_daily_message(
        self, channel_id: str, author: str, content: str,
        timestamp: float | None = None, platform: str = "discord",
    ) -> None:
        await self.execute(
            "INSERT INTO daily_log (timestamp, channel_id, author, content, platform) VALUES (?, ?, ?, ?, ?)",
            (timestamp if timestamp is not None else time.time(), channel_id, author, content, platform),
        )

    async def get_today_messages(self) -> list[dict]:
        midnight = datetime.now(_TZ_DB).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        rows = await self.fetch_all(
            "SELECT timestamp, channel_id, author, content, platform FROM daily_log "
            "WHERE timestamp >= ? ORDER BY timestamp ASC",
            (midnight,),
        )
        return [
            {
                "timestamp": float(row["timestamp"]),
                "channel_id": row["channel_id"],
                "author": row["author"],
                "content": row["content"],
                "platform": row["platform"] if "platform" in row.keys() else "discord",
            }
            for row in rows
        ]

    async def get_messages_for_date(self, target_date: date) -> list[dict]:
        """Return daily_log messages for a specific date (Europe/Paris)."""
        midnight = datetime.combine(target_date, datetime.min.time(), tzinfo=_TZ_DB).timestamp()
        end = midnight + 86400
        rows = await self.fetch_all(
            "SELECT timestamp, channel_id, author, content, platform FROM daily_log "
            "WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp ASC",
            (midnight, end),
        )
        return [
            {
                "timestamp": float(row["timestamp"]),
                "channel_id": row["channel_id"],
                "author": row["author"],
                "content": row["content"],
                "platform": row["platform"] if "platform" in row.keys() else "discord",
            }
            for row in rows
        ]

    async def cleanup_old_daily_log(self, days: int = 7) -> None:
        cutoff = time.time() - days * 86400
        await self.execute("DELETE FROM daily_log WHERE timestamp < ?", (cutoff,))

    # ── Emotion peaks ──────────────────────────────────────────────────────

    async def insert_emotion_peak(
        self, timestamp: float, emotion: str, value: float,
        trigger_user: str = "", trigger_message: str = "",
        channel_id: str = "", platform: str = "",
    ) -> None:
        await self.execute(
            "INSERT INTO emotion_peaks "
            "(timestamp, emotion, value, trigger_user, trigger_message, channel_id, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp, emotion, value, trigger_user, trigger_message, channel_id, platform),
        )

    async def get_emotion_peaks_since(self, since: float) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT timestamp, emotion, value, trigger_user, trigger_message, channel_id, platform "
            "FROM emotion_peaks WHERE timestamp >= ? ORDER BY timestamp ASC",
            (since,),
        )
        return [
            {
                "timestamp": float(r["timestamp"]),
                "emotion": r["emotion"],
                "value": float(r["value"]),
                "trigger_user": r["trigger_user"],
                "trigger_message": r["trigger_message"],
                "channel_id": r["channel_id"],
                "platform": r["platform"],
            }
            for r in rows
        ]

    # ── Journal archive ────────────────────────────────────────────────────

    async def insert_journal(self, date: str, content: str, word_count: int) -> None:
        await self.execute(
            "INSERT INTO journal_archive (date, content, word_count, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET content=excluded.content, "
            "word_count=excluded.word_count, created_at=excluded.created_at",
            (date, content, word_count, time.time()),
        )

    async def get_yesterday_journal(self, today: str | None = None) -> dict | None:
        """Returns yesterday's journal entry, or None if not found.
        today: ISO 8601 date string (YYYY-MM-DD). Defaults to today."""
        if today is None:
            today = datetime.now(_TZ_DB).strftime("%Y-%m-%d")
        from datetime import date as date_type, timedelta
        yesterday = (date_type.fromisoformat(today) - timedelta(days=1)).isoformat()
        row = await self.fetch_one(
            "SELECT date, content, word_count FROM journal_archive WHERE date = ?",
            (yesterday,),
        )
        if row is None:
            return None
        return {"date": row["date"], "content": row["content"], "word_count": int(row["word_count"])}

    # ── Emotion averages ──────────────────────────────────────────────────

    async def get_emotion_averages(self, since: float) -> dict | None:
        row = await self.fetch_one(
            "SELECT AVG(anger) AS anger, AVG(joy) AS joy, AVG(sadness) AS sadness, "
            "AVG(curiosity) AS curiosity, AVG(boredom) AS boredom "
            "FROM emotion_history WHERE snapshot_at >= ?",
            (since,),
        )
        if row is None or row["anger"] is None:
            return None
        return {
            "anger": float(row["anger"]),
            "joy": float(row["joy"]),
            "sadness": float(row["sadness"]),
            "curiosity": float(row["curiosity"]),
            "boredom": float(row["boredom"]),
        }

    # ── User links (account linking) ─────────────────────────────────────────

    async def upsert_link_proposal(
        self, canonical_id: str, alias_id: str, confidence: float
    ) -> None:
        """Insère ou met à jour une proposition de liaison (status=pending, update confidence).

        Ne touche pas aux liens déjà acceptés ou rejetés — seules les propositions
        pending voient leur confidence mise à jour.
        """
        async with self._conn.execute(
            """INSERT INTO user_links (canonical_id, alias_id, confidence, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)
               ON CONFLICT(canonical_id, alias_id)
               DO UPDATE SET confidence=excluded.confidence, created_at=excluded.created_at
               WHERE user_links.status = 'pending'""",
            (canonical_id, alias_id, confidence, time.time()),
        ):
            pass
        await self._conn.commit()

    async def list_link_proposals(self, status: str | None = None) -> list[dict]:
        """Retourne les propositions de liaison.

        Chaque dict contient: id, canonical_id, alias_id, confidence, status,
        created_at, resolved_at, canonical_username, alias_username.
        """
        base = (
            "SELECT l.id, l.canonical_id, l.alias_id, l.confidence, l.status, "
            "l.created_at, l.resolved_at, "
            "mc.username AS canonical_username, ma.username AS alias_username "
            "FROM user_links l "
            "LEFT JOIN memory_users mc ON mc.user_id = l.canonical_id "
            "LEFT JOIN memory_users ma ON ma.user_id = l.alias_id"
        )
        if status:
            query = f"{base} WHERE l.status = ? ORDER BY l.confidence DESC"
            cursor = await self._conn.execute(query, (status,))
        else:
            query = f"{base} ORDER BY l.confidence DESC"
            cursor = await self._conn.execute(query)
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
                "canonical_username": r[7],
                "alias_username": r[8],
            }
            for r in rows
        ]

    async def get_link_proposal(self, link_id: int) -> dict | None:
        """Retourne une proposition de liaison par ID, ou None."""
        base = (
            "SELECT l.id, l.canonical_id, l.alias_id, l.confidence, l.status, "
            "l.created_at, l.resolved_at, "
            "mc.username AS canonical_username, ma.username AS alias_username "
            "FROM user_links l "
            "LEFT JOIN memory_users mc ON mc.user_id = l.canonical_id "
            "LEFT JOIN memory_users ma ON ma.user_id = l.alias_id "
            "WHERE l.id = ?"
        )
        cursor = await self._conn.execute(base, (link_id,))
        r = await cursor.fetchone()
        if r is None:
            return None
        return {
            "id": r[0], "canonical_id": r[1], "alias_id": r[2],
            "confidence": r[3], "status": r[4], "created_at": r[5],
            "resolved_at": r[6], "canonical_username": r[7], "alias_username": r[8],
        }

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

    async def get_platform_users(self, platform: str) -> list[dict]:
        """Retourne les utilisateurs d'une plateforme depuis memory_users.

        Chaque dict contient 'raw_id' (sans préfixe) et 'username' (peut être None).
        """
        cursor = await self._conn.execute(
            "SELECT user_id, username FROM memory_users WHERE platform = ?",
            (platform,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "raw_id": r[0].split(":", 1)[1] if ":" in r[0] else r[0],
                "username": r[1],
                "full_id": r[0],
            }
            for r in rows
        ]

    # ── Session persistence ───────────────────────────────────────────────────

    async def insert_session_message(
        self,
        channel_id: str,
        platform: str,
        user_id: str,
        display_name: str,
        content: str,
        timestamp: float,
    ) -> None:
        await self.execute(
            "INSERT INTO session_messages "
            "(channel_id, platform, user_id, display_name, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (channel_id, platform, user_id, display_name, content, timestamp),
        )

    async def get_recent_session_messages(self, since: float) -> list[dict]:
        """Retourne les messages de session plus récents que `since`."""
        rows = await self.fetch_all(
            "SELECT channel_id, platform, user_id, display_name, content, timestamp "
            "FROM session_messages WHERE timestamp >= ? ORDER BY timestamp ASC",
            (since,),
        )
        return [
            {
                "channel_id": r["channel_id"],
                "platform": r["platform"],
                "user_id": r["user_id"],
                "display_name": r["display_name"],
                "content": r["content"],
                "timestamp": float(r["timestamp"]),
            }
            for r in rows
        ]

    async def delete_session_messages(self, channel_id: str) -> None:
        """Supprime les messages de session d'un canal (après analyse)."""
        await self.execute(
            "DELETE FROM session_messages WHERE channel_id = ?", (channel_id,)
        )

    # ── Web search log ────────────────────────────────────────────────────────

    async def log_web_search(self, query: str, results_count: int) -> None:
        await self.execute(
            "INSERT INTO web_search_log (timestamp, query, results_count) VALUES (?, ?, ?)",
            (time.time(), query, results_count),
        )

    async def count_web_searches_this_month(self) -> int:
        now = datetime.now(_TZ_DB)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        row = await self.fetch_one(
            "SELECT COUNT(*) AS cnt FROM web_search_log WHERE timestamp >= ?",
            (month_start.timestamp(),),
        )
        return int(row["cnt"]) if row else 0

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

    # ── User aliases (nickname resolution) ────────────────────────────────────

    async def upsert_alias(
        self,
        nickname: str,
        canonical_uid: str,
        display_name: str,
        source: str,
        confidence: float,
    ) -> None:
        """Insert or update an alias mapping.

        If source == 'llm', an existing alias with source == 'manual' is NOT overwritten.
        """
        nickname = nickname.lower().strip()
        if source == "llm":
            existing = await self.fetch_one(
                "SELECT source FROM user_aliases WHERE nickname = ?", (nickname,)
            )
            if existing and existing["source"] == "manual":
                return  # manual entries are protected from LLM overwrites
        await self.execute(
            "INSERT INTO user_aliases (nickname, canonical_uid, display_name, source, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(nickname) DO UPDATE SET "
            "canonical_uid=excluded.canonical_uid, display_name=excluded.display_name, "
            "source=excluded.source, confidence=excluded.confidence, created_at=excluded.created_at",
            (nickname, canonical_uid, display_name, source, confidence, time.time()),
        )

    async def delete_alias(self, nickname: str) -> None:
        """Delete an alias by nickname."""
        await self.execute(
            "DELETE FROM user_aliases WHERE nickname = ?", (nickname.lower().strip(),)
        )

    async def list_aliases(self, canonical_uid: str | None = None) -> list[dict]:
        """Return all aliases, optionally filtered by canonical_uid."""
        if canonical_uid is not None:
            rows = await self.fetch_all(
                "SELECT nickname, canonical_uid, display_name, source, confidence, created_at "
                "FROM user_aliases WHERE canonical_uid = ? ORDER BY created_at DESC",
                (canonical_uid,),
            )
        else:
            rows = await self.fetch_all(
                "SELECT nickname, canonical_uid, display_name, source, confidence, created_at "
                "FROM user_aliases ORDER BY created_at DESC",
            )
        return [
            {
                "nickname": r["nickname"],
                "canonical_uid": r["canonical_uid"],
                "display_name": r["display_name"],
                "source": r["source"],
                "confidence": float(r["confidence"]),
                "created_at": float(r["created_at"]),
            }
            for r in rows
        ]

    async def get_nickname_alias_map(self) -> dict[str, str]:
        """Return {nickname: canonical_uid} for all aliases."""
        rows = await self.fetch_all(
            "SELECT nickname, canonical_uid FROM user_aliases"
        )
        return {r["nickname"]: r["canonical_uid"] for r in rows}

    async def list_unresolved_aliases(self) -> list[dict]:
        """Return memory_users rows where user_id LIKE 'unknown:%'."""
        rows = await self.fetch_all(
            "SELECT user_id, platform, last_updated, username "
            "FROM memory_users WHERE user_id LIKE 'unknown:%' ORDER BY last_updated DESC",
        )
        return [
            {
                "user_id": r["user_id"],
                "platform": r["platform"],
                "last_updated": float(r["last_updated"]),
                "username": r["username"],
            }
            for r in rows
        ]

    async def delete_session_messages_before(self, channel_id: str, cutoff_ts: float) -> None:
        """Delete session messages for a channel older than cutoff_ts."""
        await self.execute(
            "DELETE FROM session_messages WHERE channel_id = ? AND timestamp <= ?",
            (channel_id, cutoff_ts),
        )

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
          "top"    — weighted random favouring highly-voted images
          "recent" — restricted to images created in the last 48 hours
          "all"    — any image
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
