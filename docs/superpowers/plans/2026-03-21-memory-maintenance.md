# Memory Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un système de scoring/complétude des souvenirs avec questions en attente, et un nettoyage quotidien automatique des mémoires périmées.

**Architecture:** Deux mécanismes dans le pipeline existant : (1) évaluation fire-and-forget à chaque `memory.add()` via LLM secondaire → stockage de questions en DB, injection dans le prompt ; (2) cron de nettoyage 30min avant le journal qui passe en revue les souvenirs par utilisateur via LLM secondaire.

**Tech Stack:** Python, aiosqlite, mem0, OpenAI (secondary model), APScheduler

**Spec:** `docs/superpowers/specs/2026-03-21-memory-maintenance-design.md`

---

## File Structure

### New files
| File | Responsibility |
|---|---|
| `bot/persona/prompts/memory_evaluate_system.md` | Prompt LLM pour évaluer la complétude d'un souvenir et résoudre les questions en attente |
| `bot/persona/prompts/memory_cleanup_system.md` | Prompt LLM pour le nettoyage quotidien des souvenirs |
| `tests/test_memory_maintenance.py` | Tests pour le scoring, les questions, et le nettoyage |

### Modified files
| File | Changes |
|---|---|
| `bot/db/database.py` | Table `memory_questions` dans SCHEMA + 6 méthodes CRUD |
| `bot/core/memory.py` | `_evaluate_memory()`, `get_pending_question_directive()` |
| `bot/core/journal.py` | `run_memory_cleanup()`, second cron dans `start()` |
| `bot/discord/handlers.py` | Injection de la directive question dans `_respond()` |
| `bot/twitch/handlers.py` | Idem pour Twitch |
| `bot/dashboard/static/app.js` | Section mémoire de l'onglet Info |

---

### Task 1: Table `memory_questions` et méthodes CRUD

**Files:**
- Modify: `bot/db/database.py` (SCHEMA ~line 185, puis après les méthodes memory_users ~line 520)
- Test: `tests/test_memory_maintenance.py`

- [ ] **Step 1: Write failing tests for DB methods**

Create `tests/test_memory_maintenance.py`:

```python
# tests/test_memory_maintenance.py
import time
import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_insert_and_get_pending_question(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "déménage le 1er", "Quel mois ?", "high")
    q = await db.get_pending_question("discord:123")
    assert q is not None
    assert q["question"] == "Quel mois ?"
    assert q["priority"] == "high"
    assert q["attempts"] == 0
    assert q["resolved"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_priority_order(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem1", "Low question", "low")
    await db.insert_memory_question("discord:123", "mem2", "High question", "high")
    await db.insert_memory_question("discord:123", "mem3", "Medium question", "medium")
    q = await db.get_pending_question("discord:123")
    assert q["question"] == "High question"
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_none_when_empty(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    q = await db.get_pending_question("discord:999")
    assert q is None
    await db.close()


@pytest.mark.asyncio
async def test_increment_attempts(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem", "Question?", "high")
    q = await db.get_pending_question("discord:123")
    await db.increment_question_attempts(q["id"])
    q2 = await db.get_pending_question("discord:123")
    assert q2["attempts"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_max_attempts_excludes_question(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem", "Question?", "high")
    q = await db.get_pending_question("discord:123")
    for _ in range(3):
        await db.increment_question_attempts(q["id"])
    q2 = await db.get_pending_question("discord:123", max_attempts=3)
    assert q2 is None
    await db.close()


@pytest.mark.asyncio
async def test_resolve_question(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem", "Question?", "high")
    q = await db.get_pending_question("discord:123")
    await db.resolve_question(q["id"])
    q2 = await db.get_pending_question("discord:123")
    assert q2 is None
    await db.close()


@pytest.mark.asyncio
async def test_get_all_pending_questions(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem1", "Q1?", "high")
    await db.insert_memory_question("discord:123", "mem2", "Q2?", "low")
    await db.insert_memory_question("discord:456", "mem3", "Q3?", "medium")
    qs = await db.get_all_pending_questions("discord:123")
    assert len(qs) == 2
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_old_questions(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    # Insert an old resolved question
    await db.execute(
        "INSERT INTO memory_questions (user_id, memory_text, question, priority, attempts, resolved, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("discord:123", "mem", "Old Q?", "low", 0, 1, time.time() - 40 * 86400),
    )
    # Insert a recent unresolved question
    await db.insert_memory_question("discord:123", "mem2", "New Q?", "high")
    await db.cleanup_old_questions(max_age_days=30)
    qs = await db.get_all_pending_questions("discord:123")
    assert len(qs) == 1
    assert qs[0]["question"] == "New Q?"
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_old_questions_purges_unresolved_old(tmp_path):
    """Old unresolved questions (> max_age_days) should also be purged."""
    db = await Database.create(str(tmp_path / "test.db"))
    # Insert an old UNRESOLVED question
    await db.execute(
        "INSERT INTO memory_questions (user_id, memory_text, question, priority, attempts, resolved, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("discord:123", "mem", "Old unresolved Q?", "high", 2, 0, time.time() - 40 * 86400),
    )
    await db.cleanup_old_questions(max_age_days=30)
    qs = await db.get_all_pending_questions("discord:123")
    assert len(qs) == 0
    await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py -v`
Expected: FAIL — `memory_questions` table doesn't exist, methods not defined

- [ ] **Step 3: Add table to SCHEMA and implement CRUD methods**

In `bot/db/database.py`, add to `SCHEMA` (before the closing `"""`):

```sql
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
```

Then add these methods to the `Database` class (after the `upsert_memory_user` method, around line 520):

```python
    # ── Memory questions ───────────────────────────────────────────────────

    async def insert_memory_question(
        self, user_id: str, memory_text: str, question: str, priority: str = "medium"
    ) -> None:
        await self.execute(
            "INSERT INTO memory_questions (user_id, memory_text, question, priority, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, memory_text, question, priority, time.time()),
        )

    async def get_pending_question(
        self, user_id: str, max_attempts: int = 3
    ) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT * FROM memory_questions"
            " WHERE user_id = ? AND resolved = 0 AND attempts < ?"
            " ORDER BY"
            "   CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,"
            "   created_at ASC"
            " LIMIT 1",
            (user_id, max_attempts),
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
            "UPDATE memory_questions SET attempts = attempts + 1 WHERE id = ?",
            (question_id,),
        )

    async def resolve_question(self, question_id: int) -> None:
        await self.execute(
            "UPDATE memory_questions SET resolved = 1 WHERE id = ?",
            (question_id,),
        )

    async def cleanup_old_questions(self, max_age_days: int = 30) -> None:
        cutoff = time.time() - max_age_days * 86400
        await self.execute(
            "DELETE FROM memory_questions WHERE resolved = 1 OR created_at < ?",
            (cutoff,),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/db/database.py tests/test_memory_maintenance.py
git commit -m "feat: add memory_questions table and CRUD methods"
```

---

### Task 2: Prompts LLM pour évaluation et nettoyage

**Files:**
- Create: `bot/persona/prompts/memory_evaluate_system.md`
- Create: `bot/persona/prompts/memory_cleanup_system.md`

- [ ] **Step 1: Create `memory_evaluate_system.md`**

```markdown
Tu es le module de mémoire de Wally. Tu reçois un souvenir qui vient d'être enregistré sur un utilisateur, ainsi que la liste des questions en attente pour cet utilisateur (avec leurs IDs).

## Tâche 1 : Évaluer la complétude du nouveau souvenir

Critères d'incomplétude :
- Dates vagues ("le 1er", "bientôt", "la semaine prochaine" sans précision)
- Lieux non spécifiés ("déménage" sans dire où)
- Références ambiguës ("son projet" sans préciser lequel)
- Événements sans contexte temporel ("va se marier" — quand ?)

## Tâche 2 : Vérifier si le nouveau souvenir répond à des questions en attente

Si le nouveau souvenir contient l'information demandée par une question en attente, inclus son ID dans le champ "resolves".

## Format de réponse

{"complete": true/false, "questions": [{"question": "...", "priority": "high|medium|low"}], "resolves": [id1, id2]}

Priority :
- high : info cruciale manquante (date d'un événement imminent, lieu d'un déménagement)
- medium : info utile mais pas urgente (quel type de jeu exactement)
- low : détail bonus (pourquoi il aime ça)

Max 2 questions. Retourne UNIQUEMENT le JSON, sans préambule.
```

- [ ] **Step 2: Create `memory_cleanup_system.md`**

```markdown
Tu es le gestionnaire de mémoire long-terme de Wally. Nous sommes le {date}.
Tu reçois la liste numérotée des souvenirs stockés pour un utilisateur.

Analyse chaque souvenir et identifie :

1. **Périmés** — faits qui ne sont probablement plus vrais ou pertinents :
   - Événements passés ("déménage le 1er mars" et nous sommes en avril)
   - États temporaires révolus ("est en vacances jusqu'au 15")
   - Infos devenues caduques par un souvenir plus récent

2. **À reformuler** — faits dont la formulation peut être améliorée :
   - Trop vagues → reformuler plus précisément
   - Temporels devenus permanents → reformuler au présent ("a déménagé à Lyon" → "Habite à Lyon")

3. **Questions** — informations incomplètes à clarifier :
   - Dates vagues, lieux manquants, références ambiguës

Retourne un JSON valide :
{"delete": [0, 3], "update": [{"index": 2, "new_text": "..."}], "questions": [{"question": "...", "priority": "high|medium|low"}]}

Les indices correspondent à la position dans la liste (commençant à 0).
Si rien à faire, retourne {"delete": [], "update": [], "questions": []}.
Retourne UNIQUEMENT le JSON, sans préambule.
```

- [ ] **Step 3: Commit**

```bash
git add bot/persona/prompts/memory_evaluate_system.md bot/persona/prompts/memory_cleanup_system.md
git commit -m "feat: add LLM prompts for memory evaluation and cleanup"
```

---

### Task 3: `_evaluate_memory()` dans MemoryService

**Files:**
- Modify: `bot/core/memory.py` (après `_maybe_consolidate`, ~line 274)
- Test: `tests/test_memory_maintenance.py` (ajout de tests)

- [ ] **Step 1: Write failing tests for `_evaluate_memory`**

Append to `tests/test_memory_maintenance.py`:

```python
from unittest.mock import MagicMock, AsyncMock, patch
from bot.core.memory import MemoryService


def make_config(window_size=5, token_threshold=100):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
    config.bot.prelude_window_size = 15
    config.openai.secondary_model = "gpt-4o-mini"
    return config


@pytest.mark.asyncio
async def test_evaluate_memory_incomplete_creates_question(tmp_path):
    """When LLM says memory is incomplete, questions are inserted in DB."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value='{"complete": false, "questions": [{"question": "Quel mois ?", "priority": "high"}], "resolves": []}')
    svc.set_openai_client(mock_openai)

    await svc._evaluate_memory("discord:123", "déménage le 1er")

    q = await db.get_pending_question("discord:123")
    assert q is not None
    assert q["question"] == "Quel mois ?"
    await db.close()


@pytest.mark.asyncio
async def test_evaluate_memory_complete_no_question(tmp_path):
    """When LLM says memory is complete, no question is created."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value='{"complete": true, "questions": [], "resolves": []}')
    svc.set_openai_client(mock_openai)

    await svc._evaluate_memory("discord:123", "Habite à Lyon depuis 2020")

    q = await db.get_pending_question("discord:123")
    assert q is None
    await db.close()


@pytest.mark.asyncio
async def test_evaluate_memory_resolves_existing_questions(tmp_path):
    """When LLM says new memory resolves an existing question, it's marked resolved."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    await db.insert_memory_question("discord:123", "déménage le 1er", "Quel mois ?", "high")
    q = await db.get_pending_question("discord:123")
    qid = q["id"]

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(
        return_value=f'{{"complete": true, "questions": [], "resolves": [{qid}]}}'
    )
    svc.set_openai_client(mock_openai)

    await svc._evaluate_memory("discord:123", "Déménage le 1er mars 2026 à Lyon")

    q2 = await db.get_pending_question("discord:123")
    assert q2 is None  # resolved
    await db.close()


@pytest.mark.asyncio
async def test_evaluate_memory_handles_invalid_json(tmp_path):
    """Invalid JSON from LLM should not crash."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value="not valid json")
    svc.set_openai_client(mock_openai)

    # Should not raise
    await svc._evaluate_memory("discord:123", "some memory")
    await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_evaluate_memory_incomplete_creates_question -v`
Expected: FAIL — `_evaluate_memory` not defined or doesn't work yet

- [ ] **Step 3: Implement `_evaluate_memory` in `memory.py`**

Add imports at the top of `bot/core/memory.py`:

```python
import json
```

Add the prompt loader after the existing `_CONSOLIDATION_SYSTEM` loader (~line 44):

```python
_EVALUATE_SYSTEM = load_prompt(
    "memory_evaluate_system",
    fallback=(
        "Tu es le module de mémoire de Wally. Évalue la complétude du souvenir. "
        'Retourne {"complete": true/false, "questions": [], "resolves": []}'
    ),
)
```

Add the method to `MemoryService` class (after `_maybe_consolidate`):

```python
    async def _evaluate_memory(self, uid: str, content: str) -> None:
        """Evaluate memory completeness and create follow-up questions if needed."""
        if self._openai is None or self._db is None:
            return
        try:
            # Get existing pending questions for context
            pending = await self._db.get_all_pending_questions(uid)
            pending_block = ""
            if pending:
                lines = [f"- [ID {q['id']}] {q['question']}" for q in pending]
                pending_block = "\nQuestions en attente :\n" + "\n".join(lines)

            user_msg = f"Nouveau souvenir : {content}{pending_block}"
            raw = await self._openai.complete_secondary(
                _EVALUATE_SYSTEM,
                [{"role": "user", "content": user_msg}],
                purpose="memory_evaluate",
            )
            result = json.loads(raw)

            # Insert new questions
            for q in result.get("questions", []):
                question = q.get("question", "").strip()
                priority = q.get("priority", "medium")
                if question and priority in ("high", "medium", "low"):
                    await self._db.insert_memory_question(uid, content, question, priority)
                    logger.debug("Memory question created for {uid}: {q}", uid=uid, q=question)

            # Resolve answered questions
            for qid in result.get("resolves", []):
                if isinstance(qid, int):
                    await self._db.resolve_question(qid)
                    logger.debug("Memory question {id} resolved by new memory", id=qid)

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.debug("Memory evaluate parse error: {e}", e=exc)
        except Exception as exc:
            logger.warning("Memory evaluate failed: {e}", e=exc)
```

Then wire it into `add()` — add after the `account_linker` block (~line 173, after `self._fire(account_linker.analyze_new_user(...))`):

```python
            self._fire(self._evaluate_memory(uid, content))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py -v`
Expected: All 13 tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add bot/core/memory.py tests/test_memory_maintenance.py
git commit -m "feat: add memory evaluation with follow-up questions"
```

---

### Task 4: `get_pending_question_directive()` et injection dans les handlers

**Files:**
- Modify: `bot/core/memory.py` (nouvelle méthode)
- Modify: `bot/discord/handlers.py:_respond` (~line 305, après les opinions)
- Modify: `bot/twitch/handlers.py` (~line 146, après les opinions)
- Test: `tests/test_memory_maintenance.py` (ajout)

- [ ] **Step 1: Write failing test for `get_pending_question_directive`**

Append to `tests/test_memory_maintenance.py`:

```python
@pytest.mark.asyncio
async def test_get_pending_question_directive_returns_directive(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    await db.insert_memory_question("discord:123", "mem", "Quel mois ?", "high")
    directive = await svc.get_pending_question_directive("discord", "123")
    assert "Quel mois ?" in directive
    assert "Si l'occasion se présente" in directive

    # Check attempts was incremented
    q = await db.get_pending_question("discord:123")
    assert q["attempts"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_directive_empty_when_none(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    directive = await svc.get_pending_question_directive("discord", "999")
    assert directive == ""
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_directive_no_db(tmp_path):
    svc = MemoryService(make_config())
    # No db set
    directive = await svc.get_pending_question_directive("discord", "123")
    assert directive == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_get_pending_question_directive_returns_directive -v`
Expected: FAIL — method not defined

- [ ] **Step 3: Implement `get_pending_question_directive` in `memory.py`**

Add to `MemoryService` class:

```python
    async def get_pending_question_directive(self, platform: str, user_id: str) -> str:
        """Return a prompt directive for the most important pending question, or ''."""
        if self._db is None:
            return ""
        try:
            uid = self._user_id(platform, user_id)
            q = await self._db.get_pending_question(uid)
            if not q:
                return ""
            await self._db.increment_question_attempts(q["id"])
            return (
                f"\n--- Question en attente ---\n"
                f"Si l'occasion se présente naturellement dans la conversation, "
                f"essaie de savoir : {q['question']}\n"
                f"Ne force pas — si le sujet ne vient pas, laisse tomber."
            )
        except Exception as exc:
            logger.warning("get_pending_question_directive failed: {e}", e=exc)
            return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Inject directive into Discord handler**

In `bot/discord/handlers.py`, in `_respond()`, after the opinions `except Exception: pass` block and **before** `context_messages = await bot.memory.get_context_summarized_if_needed(...)` (~line 316), add:

```python
        # Inject pending memory question directive
        try:
            question_directive = await bot.memory.get_pending_question_directive(platform, user_id)
            if question_directive:
                mem_context = (mem_context + question_directive) if mem_context else question_directive.strip()
        except Exception:
            pass
```

- [ ] **Step 6: Inject directive into Twitch handler**

In `bot/twitch/handlers.py`, after the opinions `except Exception: pass` block and **before** `context_msgs = await bot.memory.get_context_summarized_if_needed(channel_id)` (~line 148), add the same code:

```python
        # Inject pending memory question directive
        try:
            question_directive = await bot.memory.get_pending_question_directive(platform, user_id)
            if question_directive:
                mem_context = (mem_context + question_directive) if mem_context else question_directive.strip()
        except Exception:
            pass
```

- [ ] **Step 7: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add bot/core/memory.py bot/discord/handlers.py bot/twitch/handlers.py tests/test_memory_maintenance.py
git commit -m "feat: inject pending memory questions into conversation prompts"
```

---

### Task 5: Nettoyage quotidien dans `DailyJournal`

**Files:**
- Modify: `bot/core/journal.py` (nouvelles méthodes + cron)
- Test: `tests/test_memory_maintenance.py` (ajout)

- [ ] **Step 1: Write failing tests for `run_memory_cleanup`**

Append to `tests/test_memory_maintenance.py`:

```python
from bot.core.journal import DailyJournal


def make_journal_deps(tmp_path, db=None):
    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "21:00"
    config.openai.secondary_model = "gpt-4o-mini"
    openai_client = MagicMock()
    emotion = MagicMock()
    memory = MagicMock()
    memory._mem0 = MagicMock()
    memory._init_mem0 = MagicMock()
    return config, openai_client, emotion, memory


@pytest.mark.asyncio
async def test_memory_cleanup_deletes_expired(tmp_path):
    """Cleanup should delete memories identified as expired by LLM."""
    db = await Database.create(str(tmp_path / "test.db"))
    config, openai_client, emotion, memory = make_journal_deps(tmp_path)

    journal = DailyJournal(config, openai_client, emotion, memory, db=db)

    # Register a user
    await db.upsert_memory_user("discord:123", "discord", "Alice")

    # Mock mem0.get_all to return 6 memories with IDs
    fake_memories = [
        {"id": f"id_{i}", "memory": f"Souvenir {i}"} for i in range(6)
    ]
    memory._mem0.get_all = MagicMock(return_value={"results": fake_memories})
    memory._mem0.delete = MagicMock()
    memory._mem0.add = MagicMock()

    # LLM says delete index 0 and 3
    openai_client.complete_secondary = AsyncMock(
        return_value='{"delete": [0, 3], "update": [], "questions": []}'
    )

    await journal.run_memory_cleanup()

    # Verify delete was called for id_0 and id_3
    delete_calls = [c.args[0] for c in memory._mem0.delete.call_args_list]
    assert "id_0" in delete_calls
    assert "id_3" in delete_calls
    assert len(delete_calls) == 2
    await db.close()


@pytest.mark.asyncio
async def test_memory_cleanup_updates_memories(tmp_path):
    """Cleanup should update memories identified for reformulation by LLM."""
    db = await Database.create(str(tmp_path / "test.db"))
    config, openai_client, emotion, memory = make_journal_deps(tmp_path)

    journal = DailyJournal(config, openai_client, emotion, memory, db=db)
    await db.upsert_memory_user("discord:123", "discord", "Alice")

    fake_memories = [
        {"id": f"id_{i}", "memory": f"Souvenir {i}"} for i in range(6)
    ]
    memory._mem0.get_all = MagicMock(return_value={"results": fake_memories})
    memory._mem0.delete = MagicMock()
    memory._mem0.add = MagicMock()

    openai_client.complete_secondary = AsyncMock(
        return_value='{"delete": [], "update": [{"index": 1, "new_text": "Reformulé"}], "questions": []}'
    )

    await journal.run_memory_cleanup()

    # Old memory deleted
    memory._mem0.delete.assert_called_once_with("id_1")
    # New text added
    memory._mem0.add.assert_called_once()
    call_args = memory._mem0.add.call_args
    assert call_args.args[0] == "Reformulé"
    await db.close()


@pytest.mark.asyncio
async def test_memory_cleanup_skips_few_memories(tmp_path):
    """Users with < 5 memories should be skipped."""
    db = await Database.create(str(tmp_path / "test.db"))
    config, openai_client, emotion, memory = make_journal_deps(tmp_path)

    journal = DailyJournal(config, openai_client, emotion, memory, db=db)
    await db.upsert_memory_user("discord:123", "discord", "Alice")

    fake_memories = [{"id": "id_0", "memory": "Only one"}]
    memory._mem0.get_all = MagicMock(return_value={"results": fake_memories})

    openai_client.complete_secondary = AsyncMock()

    await journal.run_memory_cleanup()

    # LLM should NOT have been called
    openai_client.complete_secondary.assert_not_called()
    await db.close()


@pytest.mark.asyncio
async def test_memory_cleanup_creates_questions(tmp_path):
    """Cleanup should create questions identified by LLM."""
    db = await Database.create(str(tmp_path / "test.db"))
    config, openai_client, emotion, memory = make_journal_deps(tmp_path)

    journal = DailyJournal(config, openai_client, emotion, memory, db=db)
    await db.upsert_memory_user("discord:123", "discord", "Alice")

    fake_memories = [
        {"id": f"id_{i}", "memory": f"Souvenir {i}"} for i in range(6)
    ]
    memory._mem0.get_all = MagicMock(return_value={"results": fake_memories})
    memory._mem0.delete = MagicMock()

    openai_client.complete_secondary = AsyncMock(
        return_value='{"delete": [], "update": [], "questions": [{"question": "Depuis quand ?", "priority": "medium"}]}'
    )

    await journal.run_memory_cleanup()

    q = await db.get_pending_question("discord:123")
    assert q is not None
    assert q["question"] == "Depuis quand ?"
    await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_memory_cleanup_deletes_expired -v`
Expected: FAIL — `run_memory_cleanup` not defined

- [ ] **Step 3: Implement `run_memory_cleanup` in `journal.py`**

Add imports at the top of `bot/core/journal.py`:

```python
import json as _json
```

Add prompt loader after the existing `_FINAL_SYSTEM` (~line 55):

```python
_CLEANUP_SYSTEM = load_prompt(
    "memory_cleanup_system",
    fallback=(
        "Tu es le gestionnaire de mémoire long-terme de Wally. Analyse les souvenirs, "
        'identifie les périmés et à reformuler. Retourne un JSON : '
        '{"delete": [], "update": [], "questions": []}'
    ),
)
```

Add the `run_memory_cleanup` method to `DailyJournal` class (before `generate_and_send`):

```python
    async def run_memory_cleanup(self) -> None:
        """Passe en revue les souvenirs des utilisateurs actifs et nettoie."""
        if self._db is None:
            logger.warning("Memory cleanup: no DB available, skipping")
            return

        self._memory._init_mem0()
        if self._memory._mem0 is None:
            logger.warning("Memory cleanup: mem0 unavailable, skipping")
            return

        try:
            users = await self._db.list_memory_users()
        except Exception as exc:
            logger.warning("Memory cleanup: failed to list users: {e}", e=exc)
            return

        # Max 20 users, sorted by last_updated (most recent first)
        users = sorted(users, key=lambda u: u.get("last_updated", 0), reverse=True)[:20]
        today_str = date.today().strftime("%d/%m/%Y")
        cleanup_prompt = _CLEANUP_SYSTEM.replace("{date}", today_str)

        total_deleted = 0
        total_updated = 0
        total_questions = 0

        for user in users:
            uid = user["user_id"]
            try:
                results = await asyncio.to_thread(self._memory._mem0.get_all, user_id=uid)
                if isinstance(results, dict):
                    results = results.get("results", [])
                if len(results) < 5:
                    continue

                # Build numbered list for LLM
                numbered = "\n".join(
                    f"{i}. {r.get('memory', '')}" for i, r in enumerate(results)
                )
                raw = await self._openai.complete_secondary(
                    cleanup_prompt,
                    [{"role": "user", "content": numbered}],
                    purpose="memory_cleanup",
                )
                actions = _json.loads(raw)

                # Apply deletions
                for idx in actions.get("delete", []):
                    if isinstance(idx, int) and 0 <= idx < len(results):
                        mem_id = results[idx].get("id")
                        if mem_id:
                            await asyncio.to_thread(self._memory._mem0.delete, mem_id)
                            total_deleted += 1

                # Apply updates (delete old + add new, bypass memory.add)
                for upd in actions.get("update", []):
                    idx = upd.get("index")
                    new_text = upd.get("new_text", "").strip()
                    if isinstance(idx, int) and 0 <= idx < len(results) and new_text:
                        old_id = results[idx].get("id")
                        if old_id:
                            await asyncio.to_thread(self._memory._mem0.delete, old_id)
                            await asyncio.to_thread(
                                self._memory._mem0.add, new_text, user_id=uid
                            )
                            total_updated += 1

                # Create questions
                for q in actions.get("questions", []):
                    question = q.get("question", "").strip()
                    priority = q.get("priority", "medium")
                    if question and priority in ("high", "medium", "low"):
                        await self._db.insert_memory_question(uid, "", question, priority)
                        total_questions += 1

            except (_json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.debug("Memory cleanup parse error for {uid}: {e}", uid=uid, e=exc)
            except Exception as exc:
                logger.warning("Memory cleanup failed for {uid}: {e}", uid=uid, e=exc)

        # Cleanup old resolved questions
        await self._db.cleanup_old_questions(max_age_days=30)

        logger.info(
            "Memory cleanup done: {d} deleted, {u} updated, {q} questions created",
            d=total_deleted, u=total_updated, q=total_questions,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py -v`
Expected: All 20 tests PASS

- [ ] **Step 5: Add cleanup cron to `start()`**

In `DailyJournal.start()` (~line 542), after the existing `add_job` for `generate_and_send`, add:

```python
        # Memory cleanup 30 min before journal
        cleanup_dt = datetime(2000, 1, 1, hour, minute) - timedelta(minutes=30)
        self._scheduler.add_job(
            self.run_memory_cleanup,
            "cron",
            hour=cleanup_dt.hour,
            minute=cleanup_dt.minute,
        )
        logger.info(
            "Memory cleanup scheduler started, fires at {h:02d}:{m:02d}",
            h=cleanup_dt.hour, m=cleanup_dt.minute,
        )
```

Also add `timedelta` to the imports at the top of `journal.py`:

```python
from datetime import date, datetime, timedelta
```

- [ ] **Step 6: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add bot/core/journal.py tests/test_memory_maintenance.py
git commit -m "feat: add daily memory cleanup cron (30min before journal)"
```

---

### Task 6: Mise à jour de l'onglet Info du dashboard

**Files:**
- Modify: `bot/dashboard/static/app.js` (~line 2868, section Mémoire)

- [ ] **Step 1: Add maintenance paragraph to memory section**

In `bot/dashboard/static/app.js`, after the global memory paragraph (line 2868, after the `</p>` of the global memory paragraph), add:

```html
          <p><strong>Maintenance automatique</strong> — Wally ne se contente pas de stocker des souvenirs, il les entretient. Chaque nouveau souvenir est évalué pour sa complétude : si une information est vague ou incomplète (une date sans mois, un lieu non précisé), Wally note une question à poser et la glisse naturellement dans une prochaine conversation. Chaque soir, 30 minutes avant son journal, il fait le tri : il supprime les faits périmés, reformule les vagues, et identifie de nouvelles questions. Maximum 1 question par conversation, maximum 3 tentatives — Wally insiste, mais pas trop.</p>
```

- [ ] **Step 2: Add technical details to the details block**

In the same file, inside the `<details>` block of the memory section (after the sliding window `<p>` around line 2891), add:

```html
              <p class="jd-tech-note"><strong>Memory scoring</strong> : chaque <code>memory.add()</code> déclenche un appel LLM secondaire (<code>_evaluate_memory</code>) qui évalue la complétude du souvenir. Les questions générées sont stockées dans la table <code>memory_questions</code> et injectées dans le prompt (max 1 par conversation, max 3 tentatives). Si le nouveau souvenir répond à une question existante, elle est automatiquement résolue.</p>
              <p class="jd-tech-note"><strong>Nettoyage quotidien</strong> : cron 30min avant le journal (<code>run_memory_cleanup</code>). Passe en revue les souvenirs des 20 utilisateurs les plus actifs, identifie les faits périmés/vagues via LLM, et applique suppressions + reformulations. Appelle <code>mem0</code> directement pour éviter les cascades avec la consolidation.</p>
```

- [ ] **Step 3: Verify dashboard loads correctly**

Run: `cd /opt/stacks/wally-ai && python -c "from bot.dashboard.static import app; print('OK')" 2>/dev/null || echo "Static file, check syntax manually"`

Verify the JS file has no syntax errors by checking the string is well-formed (no unescaped quotes breaking template literals).

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat: update Info tab with memory maintenance documentation"
```

---

### Task 7: Vérification finale et bump cache

**Files:**
- Possibly: `bot/dashboard/static/app.js` (cache version)

- [ ] **Step 1: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v`
Expected: All tests pass (110 existing + ~19 new)

- [ ] **Step 2: Verify bot starts correctly**

Run: `cd /opt/stacks/wally-ai && timeout 10 python -c "from bot.core.memory import MemoryService, _EVALUATE_SYSTEM; print('Memory OK:', bool(_EVALUATE_SYSTEM)); from bot.core.journal import DailyJournal, _CLEANUP_SYSTEM; print('Journal OK:', bool(_CLEANUP_SYSTEM))"`
Expected: Both print `OK: True`

- [ ] **Step 3: Bump static cache version if needed**

Check the current cache version in `app.js` and bump it (e.g., `v3` → `v4`) to force browsers to reload the updated Info tab.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: bump static cache version for memory maintenance release"
```
