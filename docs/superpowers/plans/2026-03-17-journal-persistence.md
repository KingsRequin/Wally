# Journal Persistence — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist all daily messages in SQLite so the journal survives bot restarts, and add a mem0 fallback for when the daily log is empty.

**Architecture:** Add a `daily_log` table in SQLite. `memory.append_message()` writes to it (DB already injected via `set_db()`). The journal reads from `daily_log` (primary), falls back to `memory.get_all_contexts()` (RAM), then to mem0 user facts if both are empty. The mem0 fallback is critical for immediate regeneration tonight.

**Tech Stack:** aiosqlite, mem0, existing DailyJournal/MemoryService patterns.

---

## File Map

| File | Change |
|---|---|
| `bot/db/database.py` | Add `daily_log` table to SCHEMA + migration + `log_daily_message()` + `get_today_messages()` + `cleanup_old_daily_log()` |
| `bot/core/memory.py` | `append_message()` → also call `self._db.log_daily_message()` if db set |
| `bot/core/journal.py` | `generate_and_send()` → use `db.get_today_messages()` then RAM fallback then mem0 fallback |
| `tests/test_database.py` | Tests for `log_daily_message()` and `get_today_messages()` |
| `tests/test_journal.py` | Test journal uses db messages; test mem0 fallback when db empty |
| `tests/test_memory.py` | Test `append_message()` writes to db when db is set |

---

## Task 1 — Add `daily_log` table to Database

**Files:**
- Modify: `bot/db/database.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_database.py — ajouter à la fin

@pytest.mark.asyncio
async def test_daily_log_table_exists(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in tables}
    assert "daily_log" in names
    await db.close()


@pytest.mark.asyncio
async def test_log_daily_message_and_get_today(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    now = time.time()
    await db.log_daily_message("ch1", "Alice", "Bonjour !", now)
    await db.log_daily_message("ch1", "Wally", "Salut Alice !", now + 1)

    msgs = await db.get_today_messages()
    assert len(msgs) == 2
    assert msgs[0]["author"] == "Alice"
    assert msgs[0]["content"] == "Bonjour !"
    assert msgs[1]["author"] == "Wally"
    await db.close()


@pytest.mark.asyncio
async def test_get_today_messages_excludes_yesterday(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    yesterday = time.time() - 86400 - 1
    today = time.time()
    await db.log_daily_message("ch1", "Alice", "Hier", yesterday)
    await db.log_daily_message("ch1", "Bob", "Aujourd'hui", today)

    msgs = await db.get_today_messages()
    assert len(msgs) == 1
    assert msgs[0]["author"] == "Bob"
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_old_daily_log(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    old = time.time() - 8 * 86400
    await db.log_daily_message("ch1", "Alice", "Très vieux", old)
    await db.log_daily_message("ch1", "Bob", "Récent", time.time())

    await db.cleanup_old_daily_log(days=7)
    msgs = await db.fetch_all("SELECT * FROM daily_log")
    assert len(msgs) == 1
    assert msgs[0]["author"] == "Bob"
    await db.close()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py::test_daily_log_table_exists tests/test_database.py::test_log_daily_message_and_get_today tests/test_database.py::test_get_today_messages_excludes_yesterday tests/test_database.py::test_cleanup_old_daily_log -v
```
Expected: FAIL (table does not exist, methods do not exist)

- [ ] **Step 3: Add `daily_log` to SCHEMA in `bot/db/database.py`**

In `SCHEMA`, after the `memory_users` block and before the closing `"""`, add:

```python
CREATE TABLE IF NOT EXISTS daily_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL    NOT NULL,
    channel_id TEXT   NOT NULL,
    author    TEXT    NOT NULL,
    content   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_log_ts ON daily_log(timestamp);
```

- [ ] **Step 4: Add migration in `Database.create()`**

After the existing `memory_users` migration block (around line 88), add:

```python
# Migration: ajouter daily_log si absent (déjà géré par CREATE TABLE IF NOT EXISTS dans SCHEMA)
# Nettoyage automatique des vieilles entrées au démarrage
try:
    await conn.execute(
        "DELETE FROM daily_log WHERE timestamp < ?",
        (time.time() - 7 * 86400,)
    )
    await conn.commit()
except Exception:
    pass  # table absente au premier démarrage — CREATE TABLE IF NOT EXISTS s'en charge
```

- [ ] **Step 5: Add `log_daily_message()`, `get_today_messages()`, `cleanup_old_daily_log()` methods**

At the end of the `Database` class, before the last method or at end of file, add:

```python
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
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py::test_daily_log_table_exists tests/test_database.py::test_log_daily_message_and_get_today tests/test_database.py::test_get_today_messages_excludes_yesterday tests/test_database.py::test_cleanup_old_daily_log -v
```
Expected: PASS

- [ ] **Step 7: Run full test suite to check no regressions**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py -v
```
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/db/database.py tests/test_database.py
git commit -m "feat(db): add daily_log table for journal persistence across restarts"
```

---

## Task 2 — Feed `daily_log` from `memory.append_message()`

**Files:**
- Modify: `bot/core/memory.py`
- Modify: `tests/test_memory.py` (or `tests/test_memory_set_db.py`)

- [ ] **Step 1: Write the failing test**

Check `tests/test_memory_set_db.py` for the pattern (db injection tests live there). Add to that file:

```python
# tests/test_memory_set_db.py — ajouter

@pytest.mark.asyncio
async def test_append_message_writes_to_daily_log(tmp_path):
    """append_message doit écrire dans daily_log quand un db est injecté."""
    from bot.core.memory import MemoryService
    from bot.db.database import Database

    config = MagicMock()
    config.bot.context_window_size = 50
    config.bot.prelude_window_size = 10

    db = await Database.create(str(tmp_path / "test.db"))
    memory = MemoryService(config)
    memory.set_db(db)

    memory.append_message("ch1", "Alice", "Bonjour !")
    memory.append_message("ch1", "Wally", "Salut !")

    # Les tâches fire-and-forget sont planifiées mais pas encore exécutées —
    # on cède le contrôle à la boucle d'événements pour les laisser tourner.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    rows = await db.get_today_messages()
    assert len(rows) == 2
    assert rows[0]["author"] == "Alice"
    assert rows[0]["content"] == "Bonjour !"
    assert rows[1]["author"] == "Wally"
    await db.close()


@pytest.mark.asyncio
async def test_append_message_no_db_does_not_crash():
    """append_message sans db injecté ne doit pas lever d'exception."""
    from bot.core.memory import MemoryService

    config = MagicMock()
    config.bot.context_window_size = 50
    config.bot.prelude_window_size = 10

    memory = MemoryService(config)  # pas de set_db()
    memory.append_message("ch1", "Alice", "Test")  # doit fonctionner sans erreur
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_set_db.py::test_append_message_writes_to_daily_log tests/test_memory_set_db.py::test_append_message_no_db_does_not_crash -v
```
Expected: FAIL (daily_log not written)

- [ ] **Step 3: Modify `memory.append_message()` in `bot/core/memory.py`**

Replace the current `append_message` method:

```python
def append_message(self, channel_id: str, author: str, content: str) -> None:
    window = self._context_windows.setdefault(channel_id, [])
    window.append(
        {"author": author, "content": content, "timestamp": time.time()}
    )
    max_size = self._config.bot.context_window_size
    if len(window) > max_size:
        self._context_windows[channel_id] = window[-max_size:]
    if self._db is not None:
        self._fire(self._db.log_daily_message(channel_id, author, content))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_set_db.py::test_append_message_writes_to_daily_log tests/test_memory_set_db.py::test_append_message_no_db_does_not_crash -v
```
Expected: PASS

- [ ] **Step 5: Run full memory test suite**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory.py tests/test_memory_set_db.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/memory.py tests/test_memory_set_db.py
git commit -m "feat(memory): persist daily messages to SQLite daily_log for journal resilience"
```

---

## Task 3 — Update journal to use `daily_log` + Discord history + mem0 fallback

**Files:**
- Modify: `bot/core/journal.py`
- Modify: `bot/main.py`
- Modify: `tests/test_journal.py`

La logique de sources du journal devient (par ordre de priorité) :
1. **Priorité 1** : `db.get_today_messages()` — messages SQLite persistés du jour (toutes plateformes)
2. **Priorité 2** : `_fetch_history_cb()` — callback Discord channel history (lecture API Discord, toute la journée, survit aux redémarrages) — **c'est ce qui permet la régénération ce soir**
3. **Priorité 3** : `memory.get_all_contexts()` — fenêtres RAM (si aucune des précédentes n'est disponible)
4. **Priorité 4** : mem0 user facts via `memory.get_all()` pour chaque utilisateur connu — dernier recours

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_journal.py — ajouter

def make_deps_with_db(journal_channel_id=12345, journal_time="03:00",
                      db_messages=None):
    config, openai, emotion, memory = make_deps(journal_channel_id, journal_time)
    memory.get_all_contexts = MagicMock(return_value=[])  # RAM vide

    db = MagicMock()
    if db_messages is None:
        db_messages = [
            {"author": "Alice", "content": "Hello from DB", "timestamp": 1000.0},
        ]
    db.get_today_messages = AsyncMock(return_value=db_messages)
    db.get_today_emotion_snapshots = AsyncMock(return_value=[])
    db.list_memory_users = AsyncMock(return_value=[])

    return config, openai, emotion, memory, db


def _get_journal_user_msg(openai_mock) -> str:
    """Extrait le contenu du message utilisateur envoyé lors du dernier appel journal."""
    call_args = openai_mock.complete_secondary.call_args_list
    journal_call = [c for c in call_args if c.kwargs.get("purpose") == "daily_journal"]
    assert journal_call, "complete_secondary should be called with purpose=daily_journal"
    return journal_call[0].args[1][0]["content"]


@pytest.mark.asyncio
async def test_journal_uses_db_messages_when_available():
    """Le journal doit utiliser daily_log quand des messages sont disponibles."""
    config, openai, emotion, memory, db = make_deps_with_db()
    journal = DailyJournal(config, openai, emotion, memory, db)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    assert "Hello from DB" in _get_journal_user_msg(openai)


@pytest.mark.asyncio
async def test_journal_falls_back_to_discord_history_when_db_empty():
    """Quand daily_log vide, le journal doit utiliser le callback Discord history."""
    config, openai, emotion, memory, db = make_deps_with_db(db_messages=[])
    history_messages = [
        {"author": "Bob", "content": "Message depuis Discord history", "timestamp": 2000.0},
    ]
    history_cb = AsyncMock(return_value=history_messages)

    journal = DailyJournal(config, openai, emotion, memory, db)
    journal.set_send_callback(AsyncMock())
    journal.set_history_callback(history_cb)

    await journal.generate_and_send()

    history_cb.assert_called_once()
    assert "Message depuis Discord history" in _get_journal_user_msg(openai)


@pytest.mark.asyncio
async def test_journal_falls_back_to_ram_when_no_db_no_history():
    """Sans db et sans history callback, le journal utilise get_all_contexts() (RAM)."""
    config, openai, emotion, memory = make_deps()
    # memory.get_all_contexts retourne des messages (défini dans make_deps)
    journal = DailyJournal(config, openai, emotion, memory, db=None)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    openai.complete_secondary.assert_called()


@pytest.mark.asyncio
async def test_journal_uses_mem0_fallback_when_all_sources_empty():
    """Quand toutes les sources sont vides, le journal utilise les souvenirs mem0."""
    config, openai, emotion, memory, db = make_deps_with_db(db_messages=[])
    history_cb = AsyncMock(return_value=[])  # Discord history vide aussi
    db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:123", "platform": "discord", "username": "Alice"}
    ])
    memory.get_all = AsyncMock(return_value="Alice aime les chats.")

    journal = DailyJournal(config, openai, emotion, memory, db)
    journal.set_send_callback(AsyncMock())
    journal.set_history_callback(history_cb)

    await journal.generate_and_send()

    assert "Alice aime les chats." in _get_journal_user_msg(openai)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_journal_uses_db_messages_when_available tests/test_journal.py::test_journal_falls_back_to_discord_history_when_db_empty tests/test_journal.py::test_journal_falls_back_to_ram_when_no_db_no_history tests/test_journal.py::test_journal_uses_mem0_fallback_when_all_sources_empty -v
```
Expected: FAIL (méthode `set_history_callback` inexistante, logique des sources absente)

- [ ] **Step 3: Update `DailyJournal` in `bot/core/journal.py`**

**3a.** Dans `__init__`, ajouter `self._fetch_history_cb: Optional[Callable[..., Any]] = None` juste après `self._send_cb`.

**3b.** Ajouter la méthode `set_history_callback` juste après `set_send_callback` :

```python
def set_history_callback(self, cb: Callable[..., Any]) -> None:
    """Inject an async callable: async def fetch_history() -> list[dict]
    Appelé quand daily_log est vide pour lire l'historique Discord du jour."""
    self._fetch_history_cb = cb
```

**3c.** Remplacer les lignes 143-147 de `generate_and_send()` (la partie qui construit `all_messages` / `context_text`) par :

```python
# Source 1 : daily_log SQLite (survit aux redémarrages, toutes plateformes)
if self._db is not None:
    try:
        db_messages = await self._db.get_today_messages()
    except Exception as exc:
        logger.warning("Failed to get daily_log messages: {e}", e=exc)
        db_messages = []
else:
    db_messages = []

# Source 2 : Discord channel history (lecture API, toute la journée)
if not db_messages and self._fetch_history_cb is not None:
    try:
        db_messages = await self._fetch_history_cb()
        if db_messages:
            logger.info(
                "Journal: using Discord history fallback ({n} messages)",
                n=len(db_messages),
            )
    except Exception as exc:
        logger.warning("Journal Discord history fallback failed: {e}", e=exc)
        db_messages = []

# Source 3 : fenêtres RAM (depuis le dernier démarrage)
ram_messages = self._memory.get_all_contexts()
all_messages = db_messages if db_messages else ram_messages

if all_messages:
    context_text = await self._build_context_text(all_messages)
else:
    # Source 4 : souvenirs mem0 de tous les utilisateurs connus
    context_text = await self._build_mem0_fallback_context()
    if not context_text:
        context_text = "Pas grand chose de notable aujourd'hui."
```

**3d.** Ajouter la méthode `_build_mem0_fallback_context()` après `_build_context_text()` :

```python
async def _build_mem0_fallback_context(self) -> str:
    """Fallback final : souvenirs mem0 de tous les utilisateurs connus."""
    if self._db is None:
        return ""
    try:
        users = await self._db.list_memory_users()
    except Exception as exc:
        logger.warning("Failed to list memory users for journal fallback: {e}", e=exc)
        return ""

    if not users:
        return ""

    parts: list[str] = []
    for user in users:
        uid_full = user["user_id"]   # e.g. "discord:123456"
        platform = user["platform"]
        username = user.get("username") or uid_full
        raw_id = uid_full[len(platform) + 1:]  # "discord:123" → "123"
        try:
            facts = await self._memory.get_all(platform, raw_id)
        except Exception:
            continue
        if facts:
            parts.append(f"[{username}] {facts}")

    if not parts:
        return ""

    logger.info("Journal fallback: using mem0 facts for {n} user(s)", n=len(parts))
    return "Souvenirs des utilisateurs (mémoire long-terme) :\n" + "\n".join(parts)
```

- [ ] **Step 4: Brancher le history callback dans `bot/main.py`**

Après `journal.set_send_callback(journal_send_cb)` (ligne ~116), ajouter :

```python
async def journal_history_cb() -> list[dict]:
    """Lit l'historique de tous les canaux Discord autorisés depuis minuit."""
    from bot.discord.handlers import _is_channel_allowed
    from datetime import datetime
    from zoneinfo import ZoneInfo
    midnight = datetime.now(ZoneInfo("Europe/Paris")).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    messages: list[dict] = []
    for guild in discord_bot.guilds:
        for channel in guild.text_channels:
            if not _is_channel_allowed(config, channel.id):
                continue
            try:
                async for msg in channel.history(after=midnight, limit=2000):
                    if not msg.content.strip():
                        continue
                    messages.append({
                        "author": msg.author.display_name,
                        "content": msg.content,
                        "timestamp": msg.created_at.timestamp(),
                    })
            except Exception as exc:
                logger.debug(
                    "Journal history: cannot read channel {ch}: {e}",
                    ch=channel.id, e=exc,
                )
    messages.sort(key=lambda m: m["timestamp"])
    return messages

journal.set_history_callback(journal_history_cb)
```

- [ ] **Step 5: Run the new journal tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_journal_uses_db_messages_when_available tests/test_journal.py::test_journal_falls_back_to_discord_history_when_db_empty tests/test_journal.py::test_journal_falls_back_to_ram_when_no_db_no_history tests/test_journal.py::test_journal_uses_mem0_fallback_when_all_sources_empty -v
```
Expected: PASS

- [ ] **Step 6: Run full journal test suite**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/journal.py bot/main.py tests/test_journal.py
git commit -m "feat(journal): add Discord history fallback + daily_log SQLite, survives restarts"
```

---

## Task 4 — Full test suite + verification

- [ ] **Step 1: Run the full test suite**

```bash
cd /opt/stacks/wally-ai && python -m pytest --tb=short -q
```
Expected: tous les tests PASS (pas de régression)

- [ ] **Step 2: Commit final si nécessaire**

Si des ajustements mineurs ont été faits après les commits précédents :

```bash
cd /opt/stacks/wally-ai && git add -p
git commit -m "fix: minor adjustments after full test suite run"
```

---

## Régénérer le journal de ce soir (post-déploiement)

Une fois les 3 tâches déployées (bot redémarré) :

1. Le journal utilisera le fallback mem0 automatiquement (daily_log vide, RAM vide)
2. Déclencher manuellement via Discord : `/wally journal`
3. Le journal sera généré depuis les faits mem0 des utilisateurs connus aujourd'hui

**Données disponibles dans mem0 pour ce soir :**
- Session 02:58 — canal 1075769353770897528, 1 participant
- Session 12:00 — canal 875421532351000627, 1 participant
- Session 14:28 — canal 875421532351000627, 3/7 participants (grosse session ~5900 tokens)
- Session 16:20 — canal 938504877464768603, 3/4 participants

La conversation du matin (12:08–12:57) est partiellement récupérée via la session 14:28.
