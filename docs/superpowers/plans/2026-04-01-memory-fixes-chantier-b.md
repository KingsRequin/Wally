# Chantier B — Corrections mémoire ciblées

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger 5 bugs/lacunes du système mémoire existant sans changer l'architecture.

**Architecture:** Corrections ciblées dans memory.py, database.py, handlers.py et app.js. Pas de nouvelle dépendance. Le pipeline existant (FactExtractor → Qdrant → consolidation) reste en place.

**Tech Stack:** Python 3.11, aiosqlite, asyncio, Qdrant, FastAPI, vanilla JS

---

## File Map

| Action | Fichier | Responsabilité |
|--------|---------|----------------|
| Modify | `bot/core/memory.py:258-309` | B1: compteur post-consolidation |
| Modify | `bot/core/memory.py:57-71` | B2: ajout `_maintenance_locks` |
| Modify | `bot/core/memory.py:245-256` | B2: verrou dans `_post_add_maintenance` |
| Modify | `bot/db/database.py:209-218` | B2: contrainte UNIQUE sur questions |
| Modify | `bot/db/database.py:947-954` | B2: INSERT OR IGNORE |
| Modify | `bot/core/memory.py:370-388` | B3: résolution sémantique à l'injection |
| Modify | `bot/discord/handlers.py:23-74` | B4: descriptions tools améliorées |
| Create | `bot/persona/prompts/memory_tools_directive.md` | B4: directive system prompt |
| Modify | `bot/core/prompts.py:265-270` | B4: injection directive outils |
| Modify | `bot/dashboard/static/app.js:5467-5471` | B5: renommage onglets |
| Modify | `bot/dashboard/static/app.js:2676-2687` | B5: sous-titre global |
| Modify | `bot/dashboard/static/app.js:5538-5549` | B5: sous-titre notes |
| Test | `tests/test_memory_maintenance.py` | Tests B1, B2, B3 |

---

### Task 1: B1 — Compteur dashboard après consolidation

**Files:**
- Modify: `bot/core/memory.py:258-309`
- Test: `tests/test_memory_maintenance.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/test_memory_maintenance.py` :

```python
@pytest.mark.asyncio
async def test_consolidate_updates_memory_count(tmp_path):
    """After consolidation, memory_count in DB should reflect the new Qdrant count."""
    from unittest.mock import AsyncMock, MagicMock
    from bot.core.memory import MemoryService
    from bot.core.memory_store import MemoryRecord

    config = MagicMock()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5

    svc = MemoryService(config)
    db = await Database.create(str(tmp_path / "test.db"))
    svc._db = db

    # Seed a memory user
    await db.upsert_memory_user("discord:123", "discord", "TestUser")
    await db.execute("UPDATE memory_users SET memory_count=30 WHERE user_id=?", ("discord:123",))

    # Mock store to return count=1 after consolidation
    mock_store = AsyncMock()
    mock_store.count = AsyncMock(return_value=1)
    mock_store.upsert = AsyncMock()
    mock_store.delete_batch = AsyncMock(return_value=26)
    svc._store = mock_store

    # Mock LLM
    svc._openai = AsyncMock()
    svc._openai.complete = AsyncMock(return_value="- Fait consolidé 1\n- Fait consolidé 2")

    # Create fake records
    records = [MemoryRecord(id=str(i), text=f"Fact {i}", metadata={}) for i in range(26)]

    await svc._consolidate("discord:123", records)

    # Verify memory_count was updated
    cursor = await db._conn.execute(
        "SELECT memory_count FROM memory_users WHERE user_id=?", ("discord:123",)
    )
    row = await cursor.fetchone()
    assert row[0] == 1, f"Expected memory_count=1 after consolidation, got {row[0]}"

    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_consolidate_updates_memory_count -v`
Expected: FAIL — `memory_count` is still 30 because `_consolidate()` doesn't update it.

- [ ] **Step 3: Write minimal implementation**

In `bot/core/memory.py`, add after the `logger.info("Memory consolidated...")` line (after line 307), before the `except` block:

```python
            # Update cached memory count in DB
            if self._db is not None:
                try:
                    new_count = await self._store.count(uid)
                    await self._db.execute(
                        "UPDATE memory_users SET memory_count=? WHERE user_id=?",
                        (new_count, uid),
                    )
                except Exception:
                    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_consolidate_updates_memory_count -v`
Expected: PASS

- [ ] **Step 5: Run all memory maintenance tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/core/memory.py tests/test_memory_maintenance.py
git commit -m "fix(memory): update memory_count after consolidation"
```

---

### Task 2: B2 — Questions en double (verrou + contrainte UNIQUE)

**Files:**
- Modify: `bot/core/memory.py:57-71` (add `_maintenance_locks`)
- Modify: `bot/core/memory.py:245-256` (add lock in `_post_add_maintenance`)
- Modify: `bot/db/database.py:209-218` (UNIQUE constraint)
- Modify: `bot/db/database.py:947-954` (INSERT OR IGNORE)
- Test: `tests/test_memory_maintenance.py`

- [ ] **Step 1: Write the failing test for UNIQUE constraint**

Ajouter dans `tests/test_memory_maintenance.py` :

```python
@pytest.mark.asyncio
async def test_duplicate_question_ignored(tmp_path):
    """Inserting the same question twice should not create a duplicate."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem1", "Quel âge ?", "high")
    await db.insert_memory_question("discord:123", "mem2", "Quel âge ?", "medium")
    pending = await db.get_all_pending_questions("discord:123")
    assert len(pending) == 1, f"Expected 1 question, got {len(pending)}"
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_duplicate_question_ignored -v`
Expected: FAIL — `len(pending) == 2`

- [ ] **Step 3: Add UNIQUE constraint + migration**

In `bot/db/database.py`, add a migration after the existing `last_attempt_at` migration (around line 425):

```python
            # Migration: add UNIQUE constraint on (user_id, question) for memory_questions
            try:
                await self._conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_questions_unique_q"
                    " ON memory_questions(user_id, question)"
                )
                await self._conn.commit()
            except Exception:
                pass
```

In `bot/db/database.py`, change `insert_memory_question` (line 947) from `INSERT INTO` to `INSERT OR IGNORE INTO`:

```python
    async def insert_memory_question(
        self, user_id: str, memory_text: str, question: str, priority: str = "medium"
    ) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO memory_questions (user_id, memory_text, question, priority, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, memory_text, question, priority, time.time()),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_duplicate_question_ignored -v`
Expected: PASS

- [ ] **Step 5: Add maintenance lock**

In `bot/core/memory.py`, add to `__init__` (after line 71):

```python
        # Verrou par utilisateur pour sérialiser les maintenances (évite les questions en double)
        self._maintenance_locks: dict[str, asyncio.Lock] = {}
```

Replace `_post_add_maintenance` (lines 245-256) with:

```python
    async def _post_add_maintenance(self, uid: str, content: str) -> None:
        """Run consolidation (if threshold exceeded) or evaluation — single get_all."""
        if self._store is None:
            return
        lock = self._maintenance_locks.setdefault(uid, asyncio.Lock())
        async with lock:
            try:
                all_records = await self._store.get_all(uid)
                if len(all_records) > _CONSOLIDATION_THRESHOLD:
                    await self._consolidate(uid, all_records)
                else:
                    await self._evaluate(uid, content, all_records)
            except Exception as exc:
                logger.warning("Post-add maintenance failed for {uid}: {e}", uid=uid, e=exc)
```

- [ ] **Step 6: Write test for lock serialization**

```python
@pytest.mark.asyncio
async def test_maintenance_lock_exists():
    """MemoryService should have a _maintenance_locks dict."""
    from unittest.mock import MagicMock
    from bot.core.memory import MemoryService

    config = MagicMock()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5

    svc = MemoryService(config)
    assert hasattr(svc, "_maintenance_locks")
    assert isinstance(svc._maintenance_locks, dict)
```

- [ ] **Step 7: Run all memory tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py tests/test_memory.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/core/memory.py bot/db/database.py tests/test_memory_maintenance.py
git commit -m "fix(memory): prevent duplicate questions with asyncio lock + UNIQUE constraint"
```

---

### Task 3: B3 — Questions pas marquées comme résolues

**Files:**
- Modify: `bot/core/memory.py:370-388` (`get_pending_question_directive`)
- Test: `tests/test_memory_maintenance.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_question_auto_resolved_by_semantic_match(tmp_path):
    """A pending question should be auto-resolved if a memory already answers it."""
    from unittest.mock import AsyncMock, MagicMock
    from bot.core.memory import MemoryService

    config = MagicMock()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5

    svc = MemoryService(config)
    db = await Database.create(str(tmp_path / "test.db"))
    svc._db = db

    # Insert a pending question
    await db.insert_memory_question("discord:123", "déménage bientôt", "Dans quelle ville ?", "high")

    # Mock store with a search that finds a matching memory
    mock_store = AsyncMock()
    mock_store.search = AsyncMock(return_value=[
        MagicMock(text="Déménage à Lyon en avril", score=0.90)
    ])
    svc._store = mock_store

    # Call get_pending_question_directive — should auto-resolve and return ""
    directive = await svc.get_pending_question_directive("discord", "123")
    assert directive == "", f"Expected empty directive (auto-resolved), got: {directive}"

    # Verify question is resolved in DB
    q = await db.get_pending_question("discord:123")
    assert q is None, "Question should have been resolved"

    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_question_auto_resolved_by_semantic_match -v`
Expected: FAIL — directive is not empty, question still pending.

- [ ] **Step 3: Implement semantic auto-resolution**

Replace `get_pending_question_directive` (lines 370-388) with:

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

            # Auto-resolve if a stored memory already answers the question
            if self._store is not None:
                try:
                    results = await self._store.search(uid, q["question"], top_k=1)
                    if results and results[0].score >= 0.85:
                        await self._db.resolve_question(q["id"])
                        logger.debug(
                            "Question {id} auto-resolved by semantic match (score={s:.2f})",
                            id=q["id"],
                            s=results[0].score,
                        )
                        return ""
                except Exception:
                    pass  # Non-critical, continue with injection

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

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py::test_question_auto_resolved_by_semantic_match -v`
Expected: PASS

- [ ] **Step 5: Write test for low-score (no auto-resolve)**

```python
@pytest.mark.asyncio
async def test_question_not_resolved_by_low_score(tmp_path):
    """A pending question should NOT be auto-resolved if semantic score is below threshold."""
    from unittest.mock import AsyncMock, MagicMock
    from bot.core.memory import MemoryService

    config = MagicMock()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5

    svc = MemoryService(config)
    db = await Database.create(str(tmp_path / "test.db"))
    svc._db = db

    await db.insert_memory_question("discord:123", "déménage bientôt", "Dans quelle ville ?", "high")

    mock_store = AsyncMock()
    mock_store.search = AsyncMock(return_value=[
        MagicMock(text="Aime les pizzas", score=0.40)
    ])
    svc._store = mock_store

    directive = await svc.get_pending_question_directive("discord", "123")
    assert "Dans quelle ville" in directive
    await db.close()
```

- [ ] **Step 6: Run all tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_maintenance.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/core/memory.py tests/test_memory_maintenance.py
git commit -m "fix(memory): auto-resolve questions when semantic match found in existing memories"
```

---

### Task 4: B4 — Notes persistantes (tool descriptions + directive)

**Files:**
- Modify: `bot/discord/handlers.py:23-74` (tool descriptions)
- Create: `bot/persona/prompts/memory_tools_directive.md`
- Modify: `bot/core/prompts.py:265-270` (inject directive)

- [ ] **Step 1: Update tool descriptions**

In `bot/discord/handlers.py`, replace `_NOTE_TOOLS` (lines 23-74) with:

```python
_NOTE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_persistent_note",
            "description": (
                "Quand quelqu'un te demande de retenir, noter ou mémoriser quelque chose "
                "qui concerne tout le serveur ou la communauté (un événement, une règle, "
                "une info partagée, un engagement que tu prends), utilise cet outil. "
                "La note sera injectée dans TOUTES tes futures conversations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre court et unique de la note"},
                    "content": {"type": "string", "description": "Contenu de la note"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_persistent_note",
            "description": "Supprimer une note persistante par son titre",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre exact de la note à supprimer"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_memory",
            "description": (
                "Quand quelqu'un te demande de retenir, noter ou mémoriser quelque chose "
                "qui le concerne personnellement (préférence, fait biographique, opinion, "
                "habitude, info privée), utilise cet outil. Le souvenir sera associé "
                "uniquement à cet utilisateur."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Fait ou information à retenir sur cet utilisateur, formulé comme une phrase factuelle courte",
                    },
                },
                "required": ["content"],
            },
        },
    },
]
```

- [ ] **Step 2: Create memory tools directive prompt**

Create `bot/persona/prompts/memory_tools_directive.md`:

```markdown
Si quelqu'un te demande de retenir, noter ou mémoriser quelque chose, tu DOIS utiliser un outil :
- `save_user_memory` pour une info personnelle (préférence, fait bio, opinion)
- `save_persistent_note` pour une info communautaire (événement serveur, règle, engagement)
Ne réponds JAMAIS "je m'en souviendrai" ou "c'est noté" sans avoir appelé l'outil correspondant.
```

- [ ] **Step 3: Inject directive in system prompt**

In `bot/core/prompts.py`, after the persistent notes injection block (after line 270), add:

```python
        # Memory tools directive — always injected
        _memory_tools_directive = load_prompt("memory_tools_directive")
        if _memory_tools_directive:
            parts.append(f"\n--- Directive mémoire ---\n{_memory_tools_directive}")
```

Note: `load_prompt` is already imported and used in this file. Verify it's available at module level.

- [ ] **Step 4: Verify load_prompt works for the new file**

Run: `cd /opt/stacks/wally-ai && python -c "from bot.core.prompts import load_prompt; print(load_prompt('memory_tools_directive')[:50])"`
Expected: Output starts with "Si quelqu'un te demande"

- [ ] **Step 5: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/discord/handlers.py bot/persona/prompts/memory_tools_directive.md bot/core/prompts.py
git commit -m "fix(memory): improve tool descriptions so LLM uses save_persistent_note/save_user_memory"
```

---

### Task 5: B5 — Renommer Notes/Global dans le dashboard

**Files:**
- Modify: `bot/dashboard/static/app.js:5467-5471` (sub-tab labels)
- Modify: `bot/dashboard/static/app.js:2676-2687` (global tab title+subtitle)
- Modify: `bot/dashboard/static/app.js:5538-5549` (notes tab title)

- [ ] **Step 1: Rename sub-tab labels**

In `bot/dashboard/static/app.js`, replace the sub-nav pills (lines 5468-5471):

Old:
```javascript
        <button class="mem-subnav-pill" data-subtab="global" onclick="switchMemoireSubTab('global')">Globale</button>
        <button class="mem-subnav-pill" data-subtab="dashboard" onclick="switchMemoireSubTab('dashboard')">Questions</button>
        <button class="mem-subnav-pill" data-subtab="notes" onclick="switchMemoireSubTab('notes')">Notes persistantes</button>
```

New:
```javascript
        <button class="mem-subnav-pill" data-subtab="global" onclick="switchMemoireSubTab('global')">Mémoire communautaire</button>
        <button class="mem-subnav-pill" data-subtab="dashboard" onclick="switchMemoireSubTab('dashboard')">Questions</button>
        <button class="mem-subnav-pill" data-subtab="notes" onclick="switchMemoireSubTab('notes')">Notes du bot</button>
```

- [ ] **Step 2: Update global tab title and subtitle**

In `bot/dashboard/static/app.js`, replace the global tab header (lines 2683-2687):

Old:
```javascript
          <h2 style="margin:0;font-size:1.3rem">Memoire globale</h2>
          <p style="margin:4px 0 0;font-size:0.82rem;color:var(--text-muted)">
            Connaissances partagees par toute la communaute (liens, regles, infos serveur).
            Consultees automatiquement a chaque requete.
          </p>
```

New:
```javascript
          <h2 style="margin:0;font-size:1.3rem">Mémoire communautaire</h2>
          <p style="margin:4px 0 0;font-size:0.82rem;color:var(--text-muted)">
            Faits sur le serveur et la communauté, retrouvés par pertinence sémantique.
            Seuls les faits pertinents au message en cours sont injectés.
          </p>
```

- [ ] **Step 3: Update notes tab title**

In `bot/dashboard/static/app.js`, replace the notes card title (line 5549):

Old:
```javascript
    html += '<div class="card"><div class="card-title">NOTES (' + notes.length + ')</div><div id="notes-list">';
```

New:
```javascript
    html += '<div class="card"><div class="card-title">NOTES DU BOT (' + notes.length + ')</div><div id="notes-list">';
```

- [ ] **Step 4: Add subtitle to notes tab**

In `bot/dashboard/static/app.js`, after the "AJOUTER UNE NOTE" card (after line 5544), add a subtitle:

Old:
```javascript
  html += '<button class="btn btn-sm" onclick="saveNewNote()">Enregistrer</button>';
  html += '</div></div>';
```

New:
```javascript
  html += '<button class="btn btn-sm" onclick="saveNewNote()">Enregistrer</button>';
  html += '</div></div>';
  html += '<p style="color:rgba(255,255,255,0.4);font-size:0.82rem;margin:0 0 12px;padding:0 4px">Règles et engagements toujours injectés dans chaque conversation. Pour les infos critiques que le bot doit garder en tête.</p>';
```

- [ ] **Step 5: Verify in browser**

Run: `cd /opt/stacks/wally-ai && docker compose up -d --build`
Check: Navigate to dashboard → Mémoire tab. Verify sub-tabs show "Mémoire communautaire" and "Notes du bot" with their subtitles.

- [ ] **Step 6: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/dashboard/static/app.js
git commit -m "ui(dashboard): rename Notes/Global tabs for clarity"
```

---

### Task 6: Push to GitHub (backup before chantier A)

- [ ] **Step 1: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 2: Push**

```bash
cd /opt/stacks/wally-ai
git push origin main
```
