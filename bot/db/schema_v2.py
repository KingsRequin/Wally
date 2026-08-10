"""DDL pour les tables Wally V2. Appelé au démarrage et dans les tests."""
from __future__ import annotations

import aiosqlite
from loguru import logger

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
    decided_at    TEXT,
    -- Ce que la capacité livrée DONNE à Wally, rédigé à la première personne et au
    -- présent (cf. `_migrate_pending_upgrades`). Rempli à la livraison, NULL avant.
    capability    TEXT
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
-- Index PARTIEL : `get_due_facts` tourne à chaque tick cognitif et n'était
-- couvert par rien — EXPLAIN donnait `SCAN atomic_facts` + tri temporaire sur
-- 14 391 lignes, pour 47 qui portent réellement un `scheduled_at`. Le filtre
-- partiel garde l'index minuscule.
CREATE INDEX IF NOT EXISTS idx_facts_scheduled
    ON atomic_facts(scheduled_at) WHERE scheduled_at IS NOT NULL;

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

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id    TEXT PRIMARY KEY,
    portrait   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Articles RSS captés comme stimulus externe (friction) ou base de connaissance.
-- `role` = 'stimulus' (amorce de pensée idle, éphémère) | 'knowledge' (cherchable
-- quand le sujet est mentionné). `injected_at` NULL tant que l'article n'a pas
-- encore traversé les pensées (dédup du stimulus). Timestamps REAL epoch, comme
-- les tables de log (web_search_log/scrape_log).
CREATE TABLE IF NOT EXISTS rss_articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_name    TEXT    NOT NULL,
    role         TEXT    NOT NULL DEFAULT 'stimulus',
    guid         TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    summary      TEXT,
    link         TEXT,
    lang         TEXT    NOT NULL DEFAULT 'fr',
    published_at TEXT,
    published_ts REAL,
    fetched_at   REAL    NOT NULL,
    injected_at  REAL,
    UNIQUE(feed_name, guid)
);
CREATE INDEX IF NOT EXISTS idx_rss_role_injected ON rss_articles(role, injected_at);
CREATE INDEX IF NOT EXISTS idx_rss_fetched ON rss_articles(fetched_at);

-- Recherche plein-texte BM25 pour le recall « knowledge » (titre + résumé).
-- Même tokenizer FR sans diacritiques que atomic_facts_fts.
CREATE VIRTUAL TABLE IF NOT EXISTS rss_articles_fts USING fts5(
    text,
    tokenize='unicode61 remove_diacritics 1'
);

CREATE TRIGGER IF NOT EXISTS rss_articles_fts_ai AFTER INSERT ON rss_articles BEGIN
    INSERT INTO rss_articles_fts(rowid, text) VALUES (
        new.id, trim(coalesce(new.title,'')||' '||coalesce(new.summary,'')));
END;

CREATE TRIGGER IF NOT EXISTS rss_articles_fts_ad AFTER DELETE ON rss_articles BEGIN
    DELETE FROM rss_articles_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS rss_articles_fts_au AFTER UPDATE ON rss_articles BEGIN
    DELETE FROM rss_articles_fts WHERE rowid = old.id;
    INSERT INTO rss_articles_fts(rowid, text) VALUES (
        new.id, trim(coalesce(new.title,'')||' '||coalesce(new.summary,'')));
END;
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


async def _migrate_pending_upgrades(db: aiosqlite.Connection) -> None:
    """Ajoute `capability` : ce que la capacité livrée DONNE à Wally, au présent.

    Sans elle, son prompt ne peut lui parler qu'en termes de demandes passées
    (« tu as demandé X, c'est livré ») — une formulation qu'il requalifie dès
    qu'un désir la contredit, comme le 2026-08-09.
    """
    cursor = await db.execute("PRAGMA table_info(pending_upgrades)")
    existing = {row[1] for row in await cursor.fetchall()}
    if "capability" not in existing:
        await db.execute("ALTER TABLE pending_upgrades ADD COLUMN capability TEXT")


async def _migrate_rss_articles(db: aiosqlite.Connection) -> None:
    """Ajoute published_ts (date de publication epoch, triable) si absent."""
    cursor = await db.execute("PRAGMA table_info(rss_articles)")
    existing = {row[1] for row in await cursor.fetchall()}
    if "published_ts" not in existing:
        await db.execute("ALTER TABLE rss_articles ADD COLUMN published_ts REAL")


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
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rss_articles'"
        )
        if await cursor.fetchone() is not None:
            await _migrate_rss_articles(db)
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_upgrades'"
        )
        if await cursor.fetchone() is not None:
            await _migrate_pending_upgrades(db)
        # Table morte (jamais écrite — les pensées vivent comme FactCategory.THOUGHT)
        await db.execute("DROP TABLE IF EXISTS thoughts")
        await db.executescript(_SCHEMA_SQL)
        await db.commit()
        await _poser_unicite_faits(db)


async def _poser_unicite_faits(db) -> None:
    """Unicité des faits ACTIFS au contenu identique, posée à part.

    Volontairement HORS de `_SCHEMA_SQL` : `executescript` est atomique, et un
    index unique refusé pour cause de doublons préexistants ferait échouer TOUT
    le reste — donc le démarrage. Ici l'échec est local et journalisé ; la passe
    `merge_exact_duplicates()` repliera les doublons la nuit suivante et l'index
    se posera au boot d'après.

    Filet de dernier recours, pas la dédup principale : `LOWER(TRIM(...))` est
    plus lâche que `_normalize()` (qui retire aussi la ponctuation). Il attrape
    ce que le verrou applicatif rate — deux ingests concurrents passant le test
    d'existence avant que l'un n'ait inséré.
    """
    try:
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_actif_unique "
            "ON atomic_facts(user_id, category, LOWER(TRIM(content))) "
            "WHERE status = 'active'"
        )
        await db.commit()
    except (aiosqlite.OperationalError, aiosqlite.IntegrityError) as exc:
        logger.warning(
            "Unicité des faits actifs non posée ({e}) — des doublons exacts "
            "subsistent, le ménage nocturne les repliera", e=exc,
        )
