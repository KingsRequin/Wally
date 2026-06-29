# Consolidation nocturne de la mémoire — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une passe quotidienne nocturne qui relit les conversations du jour pour en extraire les faits durables ratés en live et produire un résumé de session par canal, réinjecté au prompt (cross-session recall).

**Architecture:** Un nouveau `MemoryConsolidator` lit les messages de session du jour (`db.get_recent_session_messages`), les groupe par canal, et pour chaque canal réutilise `FactExtractor._extract_facts` (extraction S-P-O + réconciliation déjà testée) puis génère un résumé LLM stocké dans la table `session_analyses` ressuscitée. Le job est ajouté au scheduler existant du `DailyJournal`. Un bloc « Sessions précédentes » lit ces résumés et les injecte dans le contexte mémoire du prompt.

**Tech Stack:** Python asyncio, aiosqlite (FTS5/SQLite), apscheduler (`AsyncIOScheduler`, trigger `"cron"`), DeepSeek `complete_structured`, loguru.

## Global Constraints

- Logging : **loguru uniquement** (`from loguru import logger`), jamais `print` ni `import logging`.
- Tout I/O async ; aucun appel bloquant dans l'event loop.
- Tous les chemins de consolidation sont **non-fatals** : `try/except` qui log WARNING et continue, jamais de crash.
- LLM = `secondary_llm` (DeepSeek) via `complete_structured(system_prompt, messages, schema, schema_name=..., purpose=...)`.
- Convention mémoire : `user_id` brut côté appelant ; `_extract_facts` gère le namespacing en interne. Ne pas préfixer.
- Commentaires en français, style du code environnant.

---

### Task 1 : Schéma `session_analyses` étendu + retrait table morte `thoughts`

**Files:**
- Modify: `bot/db/schema_v2.py` (le `_SCHEMA_SQL`, la fonction `create_v2_tables`, ajout d'une migration défensive)
- Test: `tests/test_session_analyses_schema.py` (créer)

**Interfaces:**
- Consumes: `create_v2_tables(db_path: str) -> None` (existant), pattern `_migrate_atomic_facts` (existant).
- Produces: table `session_analyses` avec colonnes `platform TEXT`, `channel_id TEXT`, `summary TEXT` en plus des existantes ; table `thoughts` supprimée.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_analyses_schema.py
import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_session_analyses_has_new_columns(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    rows = await db.fetch_all("PRAGMA table_info(session_analyses)")
    cols = {r["name"] for r in rows}
    assert {"platform", "channel_id", "summary"} <= cols
    await db.close()


@pytest.mark.asyncio
async def test_thoughts_table_dropped(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='thoughts'"
    )
    assert rows == []
    await db.close()


@pytest.mark.asyncio
async def test_migration_idempotent_on_legacy_table(tmp_path):
    # Simule une vieille DB avec l'ancien schéma session_analyses (sans les colonnes)
    import aiosqlite
    path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(path) as raw:
        await raw.execute(
            "CREATE TABLE session_analyses ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, quality REAL, "
            "issues TEXT, successes TEXT, improvement_note TEXT, created_at TEXT NOT NULL)"
        )
        await raw.execute("CREATE TABLE thoughts (id INTEGER PRIMARY KEY, content TEXT, created_at TEXT)")
        await raw.commit()
    # create_v2_tables doit migrer sans lever, deux fois de suite
    from bot.db.schema_v2 import create_v2_tables
    await create_v2_tables(path)
    await create_v2_tables(path)  # idempotent
    db = await Database.create(path)
    rows = await db.fetch_all("PRAGMA table_info(session_analyses)")
    cols = {r["name"] for r in rows}
    assert {"platform", "channel_id", "summary"} <= cols
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_session_analyses_schema.py -q`
Expected: FAIL (colonnes absentes / table `thoughts` encore présente).

- [ ] **Step 3: Write minimal implementation**

Dans `bot/db/schema_v2.py` :

1. Dans `_SCHEMA_SQL`, remplacer le bloc `CREATE TABLE ... session_analyses (...)` par la version étendue :
```sql
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
```
2. Retirer entièrement le bloc `CREATE TABLE ... thoughts (...)` de `_SCHEMA_SQL`.
3. Ajouter une fonction de migration (à côté de `_migrate_atomic_facts`) :
```python
_SESSION_ANALYSES_NEW_COLUMNS = [
    ("platform", "TEXT"),
    ("channel_id", "TEXT"),
    ("summary", "TEXT"),
]


async def _migrate_session_analyses(db: "aiosqlite.Connection") -> None:
    """Ajoute les colonnes recall manquantes sur une table session_analyses existante."""
    cursor = await db.execute("PRAGMA table_info(session_analyses)")
    existing = {row[1] for row in await cursor.fetchall()}
    for name, decl in _SESSION_ANALYSES_NEW_COLUMNS:
        if name not in existing:
            await db.execute(f"ALTER TABLE session_analyses ADD COLUMN {name} {decl}")
```
4. Dans `create_v2_tables`, après la migration `atomic_facts` et avant `executescript`, ajouter :
```python
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_analyses'"
        )
        if await cursor.fetchone() is not None:
            await _migrate_session_analyses(db)
        # Table morte (jamais écrite — les pensées vivent comme FactCategory.THOUGHT)
        await db.execute("DROP TABLE IF EXISTS thoughts")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_session_analyses_schema.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add bot/db/schema_v2.py tests/test_session_analyses_schema.py
git commit -m "feat(memory): schéma session_analyses étendu (recall) + retrait table morte thoughts"
```

---

### Task 2 : Helpers DB `insert_session_analysis` + `get_recent_session_summaries`

**Files:**
- Modify: `bot/db/mixins/social.py` (à côté de `get_recent_session_messages`)
- Test: `tests/test_session_analyses.py` (créer)

**Interfaces:**
- Consumes: `self.execute(sql, params)`, `self.fetch_all(sql, params)` (helpers Database existants).
- Produces:
  - `insert_session_analysis(session_id: str, platform: str, channel_id: str, summary: str) -> None` (upsert : remplace tout enregistrement de même `session_id`).
  - `get_recent_session_summaries(platform: str, channel_id: str, limit: int = 3) -> list[dict]` → list de `{"summary": str, "created_at": str}`, plus récents d'abord.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_analyses.py
import pytest
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables


async def _make_db(tmp_path):
    """DB de test avec tables V1 + V2 (comme en prod via bootstrap)."""
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    return db


@pytest.mark.asyncio
async def test_insert_and_get_summary(tmp_path):
    db = await _make_db(tmp_path)
    await db.insert_session_analysis("discord:111:2026-06-29", "discord", "111", "On a parlé d'Apex.")
    out = await db.get_recent_session_summaries("discord", "111")
    assert len(out) == 1
    assert out[0]["summary"] == "On a parlé d'Apex."
    await db.close()


@pytest.mark.asyncio
async def test_upsert_replaces_same_session_id(tmp_path):
    db = await _make_db(tmp_path)
    await db.insert_session_analysis("discord:111:2026-06-29", "discord", "111", "v1")
    await db.insert_session_analysis("discord:111:2026-06-29", "discord", "111", "v2")
    out = await db.get_recent_session_summaries("discord", "111")
    assert len(out) == 1
    assert out[0]["summary"] == "v2"
    await db.close()


@pytest.mark.asyncio
async def test_channel_isolation(tmp_path):
    db = await _make_db(tmp_path)
    await db.insert_session_analysis("discord:111:2026-06-29", "discord", "111", "salon A")
    await db.insert_session_analysis("discord:222:2026-06-29", "discord", "222", "salon B")
    out = await db.get_recent_session_summaries("discord", "111")
    assert [o["summary"] for o in out] == ["salon A"]
    await db.close()


@pytest.mark.asyncio
async def test_limit_and_order(tmp_path):
    db = await _make_db(tmp_path)
    for i in range(5):
        await db.insert_session_analysis(f"discord:111:day{i}", "discord", "111", f"jour {i}")
    out = await db.get_recent_session_summaries("discord", "111", limit=2)
    assert len(out) == 2
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_session_analyses.py -q`
Expected: FAIL (`AttributeError: insert_session_analysis`).

- [ ] **Step 3: Write minimal implementation**

Dans `bot/db/mixins/social.py`, ajouter à la classe `SocialMixin` (après `get_recent_session_messages`) :
```python
    async def insert_session_analysis(
        self, session_id: str, platform: str, channel_id: str, summary: str
    ) -> None:
        """Écrit le résumé de session (upsert par session_id : un seul par canal/jour)."""
        import time
        await self.execute(
            "DELETE FROM session_analyses WHERE session_id = ?", (session_id,)
        )
        await self.execute(
            "INSERT INTO session_analyses "
            "(session_id, platform, channel_id, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, platform, channel_id, summary, str(time.time())),
        )

    async def get_recent_session_summaries(
        self, platform: str, channel_id: str, limit: int = 3
    ) -> list[dict]:
        """Retourne les derniers résumés de session d'un canal (recall cross-session)."""
        rows = await self.fetch_all(
            "SELECT summary, created_at FROM session_analyses "
            "WHERE platform = ? AND channel_id = ? AND summary IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (platform, channel_id, limit),
        )
        return [{"summary": r["summary"], "created_at": r["created_at"]} for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_session_analyses.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add bot/db/mixins/social.py tests/test_session_analyses.py
git commit -m "feat(memory): helpers DB insert/get résumés de session (recall)"
```

---

### Task 3 : `MemoryConsolidator` + prompt de résumé

**Files:**
- Create: `bot/intelligence/memory/consolidator.py`
- Create: `bot/persona/prompts/memory_session_summary.md`
- Test: `tests/test_memory_consolidator.py` (créer)

**Interfaces:**
- Consumes:
  - `db.get_recent_session_messages(since: float) -> list[dict]` (clés `channel_id, platform, user_id, display_name, content, timestamp`).
  - `fact_extractor._extract_facts(messages: list[dict], platform: str, channel_id: str, origin=None) -> int`.
  - `llm_secondary.complete_structured(system_prompt, messages, schema, schema_name=..., purpose=...) -> dict`.
  - `db.insert_session_analysis(session_id, platform, channel_id, summary)` (Task 2).
  - `load_prompt(name)` de `bot.intelligence.prompts`.
- Produces: `MemoryConsolidator(db, llm_secondary, fact_extractor, memory)` avec `async consolidate_day(since: float | None = None) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory_consolidator.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.memory.consolidator import MemoryConsolidator


def _make(rows):
    db = MagicMock()
    db.get_recent_session_messages = AsyncMock(return_value=rows)
    db.insert_session_analysis = AsyncMock()
    fact_extractor = MagicMock()
    fact_extractor._extract_facts = AsyncMock(return_value=1)
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"summary": "résumé test"})
    memory = MagicMock()
    return MemoryConsolidator(db, llm, fact_extractor, memory), db, fact_extractor, llm


def _msg(ch, uid="1", name="Alice", content="coucou les amis ça va"):
    return {"channel_id": ch, "platform": "discord", "user_id": uid,
            "display_name": name, "content": content, "timestamp": 1.0}


@pytest.mark.asyncio
async def test_no_messages_is_noop():
    c, db, fx, llm = _make([])
    await c.consolidate_day(since=0.0)
    fx._extract_facts.assert_not_awaited()
    db.insert_session_analysis.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_below_two_messages_skipped():
    c, db, fx, llm = _make([_msg("A")])
    await c.consolidate_day(since=0.0)
    fx._extract_facts.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_extracts_and_summarizes():
    rows = [_msg("A", "1"), _msg("A", "2", "Bob")]
    c, db, fx, llm = _make(rows)
    await c.consolidate_day(since=0.0)
    fx._extract_facts.assert_awaited_once()
    args = fx._extract_facts.await_args.args
    assert args[1] == "discord" and args[2] == "A"
    db.insert_session_analysis.assert_awaited_once()
    ins = db.insert_session_analysis.await_args.args
    assert ins[1] == "discord" and ins[2] == "A" and ins[3] == "résumé test"


@pytest.mark.asyncio
async def test_channels_isolated_on_error():
    rows = [_msg("A", "1"), _msg("A", "2"), _msg("B", "1"), _msg("B", "2")]
    c, db, fx, llm = _make(rows)
    # Le canal A lève, B doit quand même être traité
    async def boom(messages, platform, channel_id, origin=None):
        if channel_id == "A":
            raise RuntimeError("extract fail A")
        return 1
    fx._extract_facts.side_effect = boom
    await c.consolidate_day(since=0.0)
    # B a produit un résumé malgré l'échec de A
    inserted_channels = [call.args[2] for call in db.insert_session_analysis.await_args_list]
    assert "B" in inserted_channels and "A" not in inserted_channels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_memory_consolidator.py -q`
Expected: FAIL (`ModuleNotFoundError: bot.intelligence.memory.consolidator`).

- [ ] **Step 3: Write minimal implementation**

`bot/persona/prompts/memory_session_summary.md` :
```markdown
Tu es la mémoire de {{BOT_NAME}}. On te donne la transcription d'une conversation.

Rédige un résumé court (2 à 4 phrases, en français) de ce qui s'est dit, du point de vue de {{BOT_NAME}} : les sujets abordés, ce qui compte pour s'en souvenir plus tard, l'ambiance. Pas de liste, pas de méta-commentaire. Écris comme un souvenir, pas comme un compte-rendu.
```

`bot/intelligence/memory/consolidator.py` :
```python
# bot/intelligence/memory/consolidator.py
"""Consolidation nocturne de la mémoire.

Relit les conversations du jour (messages de session persistés), en extrait les
faits durables via le pipeline existant (FactExtractor._extract_facts →
MemoryIngest, dédupé) et produit un résumé par canal stocké dans
session_analyses pour le recall cross-session.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from bot.intelligence.prompts import load_prompt

if TYPE_CHECKING:
    from bot.intelligence.fact_extractor import FactExtractor
    from bot.intelligence.memory.service import MemoryService

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Résumé 2-4 phrases de la conversation, comme un souvenir.",
        }
    },
    "required": ["summary"],
}


class MemoryConsolidator:
    def __init__(self, db, llm_secondary, fact_extractor: "FactExtractor", memory: "MemoryService"):
        self._db = db
        self._llm = llm_secondary
        self._fact_extractor = fact_extractor
        self._memory = memory

    async def consolidate_day(self, since: float | None = None) -> None:
        """Passe nocturne : faits + résumés pour chaque canal actif du jour."""
        if self._db is None:
            return
        if since is None:
            now = datetime.now()
            since = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        try:
            rows = await self._db.get_recent_session_messages(since)
        except Exception as e:  # noqa: BLE001 — non-fatal
            logger.warning("Consolidation : lecture des messages échouée : {e}", e=e)
            return
        if not rows:
            logger.debug("Consolidation : aucun message à consolider")
            return

        by_channel: dict[str, dict] = {}
        for r in rows:
            ch = by_channel.setdefault(
                r["channel_id"], {"platform": r["platform"], "messages": []}
            )
            ch["messages"].append(r)

        for channel_id, data in by_channel.items():
            try:
                await self._consolidate_channel(channel_id, data["platform"], data["messages"])
            except Exception as e:  # noqa: BLE001 — un canal ne doit pas casser les autres
                logger.warning("Consolidation canal {c} échouée : {e}", c=channel_id, e=e)
        logger.info("Consolidation nocturne terminée : {n} canal(aux)", n=len(by_channel))

    async def _consolidate_channel(self, channel_id: str, platform: str, messages: list[dict]) -> None:
        if len(messages) < 2:
            return
        # (a) Faits durables — pipeline existant, réconciliation dédupe
        await self._fact_extractor._extract_facts(
            messages, platform, channel_id, origin="consolidation"
        )
        # (b) Résumé de session pour le recall
        summary = await self._summarize(messages)
        if summary:
            session_id = f"{platform}:{channel_id}:{datetime.now().strftime('%Y-%m-%d')}"
            await self._db.insert_session_analysis(session_id, platform, channel_id, summary)

    async def _summarize(self, messages: list[dict]) -> str | None:
        convo = "\n".join(f"{m['display_name']}: {m['content']}" for m in messages)
        try:
            result = await self._llm.complete_structured(
                load_prompt("memory_session_summary"),
                [{"role": "user", "content": convo}],
                _SUMMARY_SCHEMA,
                schema_name="session_summary",
                purpose="memory_consolidation",
            )
        except Exception as e:  # noqa: BLE001 — non-fatal, on garde les faits extraits
            logger.warning("Consolidation : résumé LLM échoué : {e}", e=e)
            return None
        return (result.get("summary") or "").strip() or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_memory_consolidator.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/memory/consolidator.py bot/persona/prompts/memory_session_summary.md tests/test_memory_consolidator.py
git commit -m "feat(memory): MemoryConsolidator — faits + résumé de session par canal"
```

---

### Task 4 : Brancher la consolidation sur le scheduler du journal

**Files:**
- Modify: `bot/intelligence/journal.py` (`DailyJournal.__init__`, nouvelle méthode `set_consolidator`, `start`)
- Test: `tests/test_journal_consolidation.py` (créer)

**Interfaces:**
- Consumes: `MemoryConsolidator.consolidate_day` (Task 3) ; `self._scheduler.add_job(...)` (apscheduler, trigger `"cron"`).
- Produces: `DailyJournal.set_consolidator(consolidator) -> None` ; un job `id="memory_consolidation"` ajouté dans `start()` quand un consolidator est présent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_journal_consolidation.py
import pytest
from unittest.mock import MagicMock
from bot.intelligence.journal import DailyJournal


def _journal():
    config = MagicMock()
    config.bot.journal_time = "21:00"
    j = DailyJournal(config, MagicMock(), MagicMock(), MagicMock(), MagicMock(), db=MagicMock())
    return j


def test_set_consolidator_then_start_registers_job():
    j = _journal()
    consolidator = MagicMock()
    j.set_consolidator(consolidator)
    sched = MagicMock()
    j.start(scheduler=sched)
    ids = {c.kwargs.get("id") for c in sched.add_job.call_args_list}
    assert "memory_consolidation" in ids


def test_start_without_consolidator_has_no_consolidation_job():
    j = _journal()
    sched = MagicMock()
    j.start(scheduler=sched)
    ids = {c.kwargs.get("id") for c in sched.add_job.call_args_list}
    assert "memory_consolidation" not in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_journal_consolidation.py -q`
Expected: FAIL (`AttributeError: set_consolidator`).

- [ ] **Step 3: Write minimal implementation**

Dans `bot/intelligence/journal.py` :

1. Dans `DailyJournal.__init__`, après `self._bg_tasks = set()`, ajouter :
```python
        self._consolidator = None
```
2. Ajouter la méthode (près de `set_send_callback`) :
```python
    def set_consolidator(self, consolidator) -> None:
        """Injecte le MemoryConsolidator lancé par le cron nocturne."""
        self._consolidator = consolidator
```
3. Dans `start`, juste après le bloc qui ajoute le job `memory_cleanup` (avant le `if owns_scheduler: self._scheduler.start()`), ajouter :
```python
        if self._consolidator is not None:
            self._scheduler.add_job(
                self._consolidator.consolidate_day,
                "cron",
                hour=hour,
                minute=minute,
                id="memory_consolidation",
                replace_existing=True,
            )
            logger.info("Consolidation nocturne planifiée à {t}", t=time_str)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_journal_consolidation.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/journal.py tests/test_journal_consolidation.py
git commit -m "feat(memory): planifie la consolidation nocturne sur le scheduler du journal"
```

---

### Task 5 : Câblage bootstrap (création + injection)

**Files:**
- Modify: `bot/bootstrap.py` (après la construction de `fact_extractor`, ~ligne 184)

**Interfaces:**
- Consumes: `MemoryConsolidator(db, secondary_llm, fact_extractor, memory)` (Task 3) ; `journal.set_consolidator` (Task 4).
- Produces: rien de nouveau pour les autres tâches — câblage runtime.

- [ ] **Step 1: Write the implementation** (intégration — vérifiée par la suite complète + démarrage)

Dans `bot/bootstrap.py`, juste après `logger.info("FactExtractor initialized")` :
```python
    # ── Consolidation nocturne de la mémoire ──────────────────────────────────
    from bot.intelligence.memory.consolidator import MemoryConsolidator
    consolidator = MemoryConsolidator(db, secondary_llm, fact_extractor, memory)
    journal.set_consolidator(consolidator)
    logger.info("MemoryConsolidator initialized")
```

- [ ] **Step 2: Run the full suite (no regression)**

Run: `python3 -m pytest -q`
Expected: tous verts (le bot se construit ; aucun ImportError).

- [ ] **Step 3: Smoke test du démarrage**

Run: `python3 -c "import bot.bootstrap; import bot.intelligence.memory.consolidator; print('imports OK')"`
Expected: `imports OK`.

- [ ] **Step 4: Commit**

```bash
git add bot/bootstrap.py
git commit -m "feat(memory): câble MemoryConsolidator dans le bootstrap"
```

---

### Task 6 : Recall — bloc « Sessions précédentes » dans le prompt

**Files:**
- Modify: `bot/intelligence/prompts.py` (helper pur `build_session_recall_block`)
- Modify: `bot/discord/handlers.py` (assemblage `memory_parts`, ~ligne 1228-1267)
- Test: `tests/test_session_recall_block.py` (créer)

**Interfaces:**
- Consumes: `db.get_recent_session_summaries(platform, channel_id, limit)` (Task 2).
- Produces: `build_session_recall_block(summaries: list[dict]) -> str` dans `prompts.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_recall_block.py
from bot.intelligence.prompts import build_session_recall_block


def test_empty_summaries_returns_empty():
    assert build_session_recall_block([]) == ""


def test_block_lists_summaries():
    block = build_session_recall_block(
        [{"summary": "On a parlé d'Apex."}, {"summary": "Bob était de mauvaise humeur."}]
    )
    assert "Sessions précédentes" in block
    assert "On a parlé d'Apex." in block
    assert "Bob était de mauvaise humeur." in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_session_recall_block.py -q`
Expected: FAIL (`ImportError: build_session_recall_block`).

- [ ] **Step 3: Write minimal implementation**

Dans `bot/intelligence/prompts.py`, ajouter :
```python
def build_session_recall_block(summaries: list[dict]) -> str:
    """Construit le bloc 'Sessions précédentes' (recall cross-session). Vide si rien."""
    if not summaries:
        return ""
    lines = ["--- Sessions précédentes dans ce salon ---"]
    for s in summaries:
        text = (s.get("summary") or "").strip()
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines) if len(lines) > 1 else ""
```

Dans `bot/discord/handlers.py`, dans l'assemblage `memory_parts` (après la `# Priority 1` et avant `assemble_memory_context`), ajouter :
```python
    # Priority 2: Résumés de sessions précédentes (cross-session recall)
    try:
        summaries = await bot.db.get_recent_session_summaries(
            platform, str(message.channel.id), limit=3
        )
        recall_block = build_session_recall_block(summaries)
        if recall_block:
            memory_parts.append((2, recall_block))
    except Exception:
        pass
```
Vérifier que `build_session_recall_block` est importé en tête de `handlers.py` depuis `bot.intelligence.prompts` (ajouter à l'import existant de ce module).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_session_recall_block.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: tous verts (handlers Discord OK).

- [ ] **Step 6: Commit**

```bash
git add bot/intelligence/prompts.py bot/discord/handlers.py tests/test_session_recall_block.py
git commit -m "feat(memory): recall cross-session — bloc Sessions précédentes dans le prompt"
```

---

### Task 7 : Recall côté Twitch (parité)

**Files:**
- Modify: `bot/twitch/handlers.py` (assemblage du contexte mémoire, miroir de Discord)

**Interfaces:**
- Consumes: `build_session_recall_block` (Task 6), `db.get_recent_session_summaries` (Task 2).

- [ ] **Step 1: Localiser l'assemblage `memory_parts` côté Twitch**

Run: `grep -n "memory_parts\|assemble_memory_context\|get_recent_jokes" bot/twitch/handlers.py`
Expected: localise le bloc équivalent à Discord.

- [ ] **Step 2: Write the implementation**

Dans `bot/twitch/handlers.py`, au même endroit que les autres `memory_parts.append(...)`, ajouter le même bloc qu'en Task 6 en adaptant la source du canal (l'identifiant de canal Twitch utilisé localement, ex. `channel_name`/`str(channel_id)` selon le code existant) et `platform="twitch"`. Importer `build_session_recall_block` depuis `bot.intelligence.prompts`.

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest -q`
Expected: tous verts.

- [ ] **Step 4: Commit**

```bash
git add bot/twitch/handlers.py
git commit -m "feat(memory): recall cross-session côté Twitch (parité Discord)"
```

---

## Self-Review

**Spec coverage :**
- Déclencheur nocturne sur scheduler journal → Task 4. ✓
- Source `get_recent_session_messages` → Task 3. ✓
- Réutilisation `_extract_facts` / réconciliation → Task 3. ✓
- Résumé de session dans `session_analyses` ressuscitée → Tasks 1+2+3. ✓
- Réinjection budgétée/cloisonnée au prompt → Task 6 (budget via `assemble_memory_context` existant, priorité 2 ; cloisonné par `channel_id`) + Task 7 (Twitch). ✓
- Non-fatal partout → `try/except` dans Tasks 3 & 6. ✓
- Retrait table morte `thoughts` → Task 1. ✓
- Migration idempotente → Task 1 (test dédié). ✓

**Note de couverture (spec §8) :** la réconciliation 2 étages est déjà couverte par `tests/intelligence/core/memory/test_ingest.py` (existant). Aucun test spéculatif decay/scoring ajouté — hors du chemin de cette feature ; à traiter dans un suivi dédié si besoin.

**Placeholder scan :** Task 7 step 2 décrit une adaptation locale (identifiant de canal Twitch) sans coller le code exact car il dépend du nom de variable réel dans `twitch/handlers.py` — l'étape 1 le fait localiser d'abord ; le bloc à insérer est identique à Task 6 (montré). Pas d'autre placeholder.

**Type consistency :** `insert_session_analysis(session_id, platform, channel_id, summary)` et `get_recent_session_summaries(platform, channel_id, limit)` cohérents entre Task 2 (définition), Task 3 (appel) et Task 6 (appel). `consolidate_day(since=None)` cohérent entre Task 3 (def) et Task 4 (job). `build_session_recall_block(summaries)` cohérent Task 6/7.
