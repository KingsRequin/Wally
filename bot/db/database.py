from __future__ import annotations
import asyncio
import json
import time
from datetime import datetime
from typing import Optional

import aiosqlite
from loguru import logger

from bot.db.mixins import (
    CostMixin,
    EmotionMixin,
    TrustMixin,
    MemoryMixin,
    SocialMixin,
    ChatMixin,
    GalleryMixin,
    ActionMixin,
)

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

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    url TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scrape_log_ts ON scrape_log(timestamp);

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

CREATE TABLE IF NOT EXISTS topics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    summary       TEXT,
    participants  TEXT,
    opinion       TEXT,
    mention_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at  REAL    NOT NULL,
    created_at    REAL    NOT NULL
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


class Database(
    CostMixin,
    EmotionMixin,
    TrustMixin,
    MemoryMixin,
    SocialMixin,
    ChatMixin,
    GalleryMixin,
    ActionMixin,
):
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
        # Migration: add chart_path to journal_archive
        try:
            await conn.execute("ALTER TABLE journal_archive ADD COLUMN chart_path TEXT DEFAULT NULL")
            await conn.commit()
        except aiosqlite.OperationalError:
            pass  # colonne déjà présente
        logger.info("Database initialized at {path}", path=path)
        return cls(conn)

    async def close(self):
        await self._conn.close()

    # ── Core query helpers ───────────────────────────────────────────────────

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

    async def get_persistent_note(self, title: str) -> str | None:
        async with self._conn.execute(
            "SELECT content FROM persistent_notes WHERE title = ?", (title.strip(),)
        ) as cursor:
            row = await cursor.fetchone()
        return row["content"] if row else None

    async def get_persistent_notes(self) -> list[dict]:
        async with self._conn.execute(
            "SELECT id, title, content, created_at, updated_at FROM persistent_notes ORDER BY updated_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]
