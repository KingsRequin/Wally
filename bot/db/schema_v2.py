"""DDL pour les tables Wally V2. Appelé au démarrage et dans les tests."""
from __future__ import annotations

import aiosqlite

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS atomic_facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    subject       TEXT,
    predicate     TEXT,
    object        TEXT,
    importance    REAL    NOT NULL DEFAULT 0.5,
    support_count INTEGER NOT NULL DEFAULT 1,
    confidence    REAL    NOT NULL DEFAULT 1.0,
    decay_rate    REAL    NOT NULL DEFAULT 0.01,
    status        TEXT    NOT NULL DEFAULT 'active',
    emotional_context TEXT,
    source        TEXT,
    origin        TEXT,
    expires_at    TEXT,
    scheduled_at  TEXT,
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

CREATE TABLE IF NOT EXISTS cognitive_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    type    TEXT    NOT NULL,
    payload TEXT    NOT NULL
);
-- Pas d'index sur id : INTEGER PRIMARY KEY = alias du rowid, déjà indexé.

-- Suivi/debug du pipeline vocal (STT entendu, réponse de Wally, décisions, latences).
CREATE TABLE IF NOT EXISTS voice_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    type    TEXT    NOT NULL,
    payload TEXT    NOT NULL
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
    platform      TEXT,
    channel_id    TEXT,
    summary       TEXT,
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

-- Recherche plein-texte BM25 (porté de jarvis-OS, remplace Qdrant).
-- Table FTS5 autonome indexée sur le texte rendu du fait (sujet/prédicat/objet/contenu).
-- Tokenizer FR : retire les diacritiques pour matcher "cafe" ↔ "café".
CREATE VIRTUAL TABLE IF NOT EXISTS atomic_facts_fts USING fts5(
    text,
    tokenize='unicode61 remove_diacritics 1'
);

CREATE TRIGGER IF NOT EXISTS atomic_facts_fts_ai AFTER INSERT ON atomic_facts BEGIN
    INSERT INTO atomic_facts_fts(rowid, text) VALUES (
        new.id,
        trim(coalesce(new.subject,'')||' '||coalesce(new.predicate,'')||' '||
             coalesce(new.object,'')||' '||coalesce(new.content,''))
    );
END;

CREATE TRIGGER IF NOT EXISTS atomic_facts_fts_ad AFTER DELETE ON atomic_facts BEGIN
    DELETE FROM atomic_facts_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS atomic_facts_fts_au AFTER UPDATE ON atomic_facts BEGIN
    DELETE FROM atomic_facts_fts WHERE rowid = old.id;
    INSERT INTO atomic_facts_fts(rowid, text) VALUES (
        new.id,
        trim(coalesce(new.subject,'')||' '||coalesce(new.predicate,'')||' '||
             coalesce(new.object,'')||' '||coalesce(new.content,''))
    );
END;

CREATE TABLE IF NOT EXISTS social_rhythm_bins (
    bin_key    TEXT    PRIMARY KEY,
    avg        REAL    NOT NULL DEFAULT 0.0,
    eng        REAL    NOT NULL DEFAULT 0.5,
    days       INTEGER NOT NULL DEFAULT 0,
    eng_obs    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT    NOT NULL
);
"""

# Colonnes ajoutées à atomic_facts pour le modèle S-P-O (porté de jarvis).
# Migration idempotente pour les DB existantes (SQLite n'a pas ADD COLUMN IF NOT EXISTS).
_NEW_COLUMNS: list[tuple[str, str]] = [
    ("subject",       "TEXT"),
    ("predicate",     "TEXT"),
    ("object",        "TEXT"),
    ("importance",    "REAL NOT NULL DEFAULT 0.5"),
    ("support_count", "INTEGER NOT NULL DEFAULT 1"),
    ("origin",        "TEXT"),
    ("expires_at",    "TEXT"),
    ("scheduled_at",  "TEXT"),
]


async def _migrate_atomic_facts(db: aiosqlite.Connection) -> None:
    """Ajoute les colonnes S-P-O manquantes sur une table atomic_facts existante."""
    cursor = await db.execute("PRAGMA table_info(atomic_facts)")
    existing = {row[1] for row in await cursor.fetchall()}
    for name, decl in _NEW_COLUMNS:
        if name not in existing:
            await db.execute(f"ALTER TABLE atomic_facts ADD COLUMN {name} {decl}")


_SESSION_ANALYSES_NEW_COLUMNS = [
    ("platform", "TEXT"),
    ("channel_id", "TEXT"),
    ("summary", "TEXT"),
]


async def _migrate_session_analyses(db: aiosqlite.Connection) -> None:
    """Ajoute les colonnes recall manquantes sur une table session_analyses existante."""
    cursor = await db.execute("PRAGMA table_info(session_analyses)")
    existing = {row[1] for row in await cursor.fetchall()}
    for name, decl in _SESSION_ANALYSES_NEW_COLUMNS:
        if name not in existing:
            await db.execute(f"ALTER TABLE session_analyses ADD COLUMN {name} {decl}")


async def create_v2_tables(db_path: str) -> None:
    """Crée les tables V2 si elles n'existent pas (idempotent)."""
    async with aiosqlite.connect(db_path) as db:
        # Migration d'abord (ajoute les colonnes sur une table pré-existante),
        # puis le script complet (triggers/FTS5 dépendent des colonnes).
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='atomic_facts'"
        )
        if await cursor.fetchone() is not None:
            await _migrate_atomic_facts(db)
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_analyses'"
        )
        if await cursor.fetchone() is not None:
            await _migrate_session_analyses(db)
        # Table morte (jamais écrite — les pensées vivent comme FactCategory.THOUGHT)
        await db.execute("DROP TABLE IF EXISTS thoughts")
        await db.executescript(_SCHEMA_SQL)
        await db.commit()
