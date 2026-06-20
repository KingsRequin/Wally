"""DDL pour les tables Wally V2. Appelé au démarrage et dans les tests."""
from __future__ import annotations

import aiosqlite

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS atomic_facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    confidence    REAL    NOT NULL DEFAULT 1.0,
    decay_rate    REAL    NOT NULL DEFAULT 0.01,
    status        TEXT    NOT NULL DEFAULT 'active',
    emotional_context TEXT,
    source        TEXT,
    created_at    TEXT    NOT NULL,
    last_seen_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_relations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id       INTEGER NOT NULL REFERENCES atomic_facts(id),
    to_id         INTEGER NOT NULL REFERENCES atomic_facts(id),
    relation_type TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS thoughts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    content       TEXT    NOT NULL,
    meta_decision TEXT,
    emotion_snapshot TEXT,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_upgrades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal      TEXT    NOT NULL,
    message_id    TEXT,
    dm_channel_id TEXT,
    status        TEXT    NOT NULL DEFAULT 'pending',
    created_at    TEXT    NOT NULL,
    decided_at    TEXT
);

CREATE TABLE IF NOT EXISTS session_analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT,
    quality       REAL,
    issues        TEXT,
    successes     TEXT,
    improvement_note TEXT,
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_user_status
    ON atomic_facts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_facts_category
    ON atomic_facts(category);
CREATE INDEX IF NOT EXISTS idx_facts_confidence
    ON atomic_facts(confidence);
CREATE INDEX IF NOT EXISTS idx_upgrades_status
    ON pending_upgrades(status);
"""


async def create_v2_tables(db_path: str) -> None:
    """Crée les tables V2 si elles n'existent pas."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA_SQL)
        await db.commit()
