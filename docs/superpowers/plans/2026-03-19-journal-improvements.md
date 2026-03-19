# Journal Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 12 improvements to Wally's daily journal: dynamic length, richer summaries, pseudo preservation, injected stats, emotion peaks, narrative continuity, multi-platform distinction, top participants, comparative emotion weather, visual emotion chart, primary model for generation, and `/wally test` command.

**Architecture:** Incremental enrichment of the existing `DailyJournal` pipeline. Each feature adds data sources or modifies prompts without restructuring the core flow. New SQL tables (`emotion_peaks`, `journal_archive`) and a migration on `daily_log` (add `platform` column). TDD throughout.

**Tech Stack:** Python 3.11+, aiosqlite, matplotlib (new), discord.py 2.x, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-19-journal-improvements-design.md`

---

### Task 1: DB schema — new tables and migration

**Files:**
- Modify: `bot/db/database.py`
- Test: `tests/test_journal_improvements.py` (create)

- [ ] **Step 1: Write failing tests for new DB methods**

```python
# tests/test_journal_improvements.py
import time
import pytest
from bot.db.database import Database


@pytest.fixture
async def db(tmp_path):
    d = await Database.create(str(tmp_path / "test.db"))
    yield d
    await d.close()


# ── emotion_peaks ──

@pytest.mark.asyncio
async def test_insert_and_get_emotion_peaks(db):
    now = time.time()
    await db.insert_emotion_peak(
        timestamp=now, emotion="joy", value=0.85,
        trigger_user="Alice", trigger_message="LOL",
        channel_id="ch1", platform="discord",
    )
    peaks = await db.get_emotion_peaks_since(now - 10)
    assert len(peaks) == 1
    assert peaks[0]["emotion"] == "joy"
    assert peaks[0]["value"] == 0.85
    assert peaks[0]["trigger_user"] == "Alice"


@pytest.mark.asyncio
async def test_get_emotion_peaks_filters_by_time(db):
    old = time.time() - 100000
    await db.insert_emotion_peak(old, "anger", 0.9, "Bob", "grrr", "ch1", "discord")
    peaks = await db.get_emotion_peaks_since(time.time() - 10)
    assert len(peaks) == 0


# ── journal_archive ──

@pytest.mark.asyncio
async def test_insert_and_get_journal(db):
    await db.insert_journal("2026-03-19", "Mon journal.", 2)
    j = await db.get_yesterday_journal("2026-03-20")
    assert j is not None
    assert j["content"] == "Mon journal."
    assert j["word_count"] == 2


@pytest.mark.asyncio
async def test_get_yesterday_journal_returns_none_when_missing(db):
    j = await db.get_yesterday_journal("2026-03-20")
    assert j is None


@pytest.mark.asyncio
async def test_insert_journal_duplicate_date_replaces(db):
    await db.insert_journal("2026-03-19", "V1", 1)
    await db.insert_journal("2026-03-19", "V2", 1)
    j = await db.get_yesterday_journal("2026-03-20")
    assert j["content"] == "V2"


# ── daily_log platform migration ──

@pytest.mark.asyncio
async def test_daily_log_has_platform_column(db):
    await db.log_daily_message("ch1", "Alice", "Hello", platform="twitch")
    rows = await db.get_today_messages()
    assert any(r.get("platform") == "twitch" for r in rows)


@pytest.mark.asyncio
async def test_daily_log_platform_defaults_to_discord(db):
    await db.log_daily_message("ch1", "Alice", "Hello")
    rows = await db.get_today_messages()
    assert rows[0].get("platform") == "discord"


# ── emotion_averages ──

@pytest.mark.asyncio
async def test_get_emotion_averages(db):
    now = time.time()
    await db.insert_emotion_snapshot({"anger": 0.2, "joy": 0.6, "sadness": 0.0, "curiosity": 0.4, "boredom": 0.1})
    await db.insert_emotion_snapshot({"anger": 0.4, "joy": 0.8, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.3})
    avgs = await db.get_emotion_averages(now - 10)
    assert avgs is not None
    assert abs(avgs["anger"] - 0.3) < 0.01
    assert abs(avgs["joy"] - 0.7) < 0.01


@pytest.mark.asyncio
async def test_get_emotion_averages_empty(db):
    avgs = await db.get_emotion_averages(time.time() - 10)
    assert avgs is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py -v`
Expected: FAIL — missing methods `insert_emotion_peak`, `get_emotion_peaks_since`, `insert_journal`, `get_yesterday_journal`, `get_emotion_averages`, and `log_daily_message` doesn't accept `platform`

- [ ] **Step 3: Add tables to SCHEMA and implement DB methods**

In `bot/db/database.py`:

Add to `SCHEMA` string before the closing `"""`:
```sql
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

CREATE TABLE IF NOT EXISTS journal_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
```

Update `daily_log` in SCHEMA to include platform:
```sql
CREATE TABLE IF NOT EXISTS daily_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  REAL    NOT NULL,
    channel_id TEXT    NOT NULL,
    author     TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    platform   TEXT    NOT NULL DEFAULT 'discord'
);
```

Add migration in `Database.create()` after existing migrations:
```python
# Migration: ajouter platform à daily_log si absent
try:
    await conn.execute("ALTER TABLE daily_log ADD COLUMN platform TEXT NOT NULL DEFAULT 'discord'")
    await conn.commit()
except aiosqlite.OperationalError:
    pass
```

Update `log_daily_message`:
```python
async def log_daily_message(
    self, channel_id: str, author: str, content: str,
    timestamp: float | None = None, platform: str = "discord",
) -> None:
    await self.execute(
        "INSERT INTO daily_log (timestamp, channel_id, author, content, platform) VALUES (?, ?, ?, ?, ?)",
        (timestamp if timestamp is not None else time.time(), channel_id, author, content, platform),
    )
```

Update `get_today_messages` to include platform:
```python
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
```

Add new methods:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `cd /opt/stacks/wally-ai && python -m pytest --tb=short -q`
Expected: ALL PASS (110+ tests)

- [ ] **Step 6: Commit**

```bash
git add bot/db/database.py tests/test_journal_improvements.py
git commit -m "feat(db): add emotion_peaks, journal_archive tables + daily_log platform migration"
```

---

### Task 2: Update prompts (F2 + F3 + F1 partial)

**Files:**
- Modify: `bot/persona/prompts/journal_system.md`
- Modify: `bot/persona/prompts/journal_chunk_system.md`
- Modify: `bot/persona/prompts/journal_final_system.md`

- [ ] **Step 1: Update `journal_chunk_system.md`**

Replace the full content with:
```markdown
Tu es le module de mémoire de Wally, un bot Discord. Tu reçois un bloc de messages d'une conversation et tu en extrais un résumé factuel destiné à alimenter le journal quotidien.

Instructions :
Priorité décroissante de ce que tu gardes :
1. Moments émotionnellement chargés (rires, tensions, surprises)
2. Échanges insolites ou mémorables
3. Informations utiles sur les participants (centres d'intérêt, opinions)
4. Sujets abordés et leur issue

Supprime : salutations, répétitions, messages sans contenu informatif.

Mentionne toujours qui a dit ou fait quoi par son pseudo exact — jamais "un utilisateur", "quelqu'un", ou "une personne".

Si le bloc ne contient rien de notable (que des salutations ou messages vides), retourne une ligne : "Échanges sans contenu notable."

Longueur : 5 à 10 lignes, texte brut, pas de titre ni de liste à puces.
```

- [ ] **Step 2: Update `journal_final_system.md`**

Replace the full content with:
```markdown
Tu es le module de mémoire de Wally, un bot Discord. Tu reçois plusieurs résumés de blocs de conversation couvrant une journée entière.

Instructions :
- Produis une synthèse narrative cohérente en 10 à 20 lignes
- Préserve la chronologie (début → fin de journée) et les personnages importants
- Mentionne toujours qui a dit ou fait quoi par son pseudo exact — jamais "un utilisateur", "quelqu'un", ou "une personne"
- Fais ressortir les thèmes récurrents et les moments les plus significatifs
- Si deux thèmes distincts coexistent (ex. matin technique, soir détente), conserve l'ordre chronologique plutôt que de regrouper par thème
- Texte brut, pas de titre ni de liste à puces

Cette synthèse alimente directement le journal intime de Wally — elle doit avoir la texture d'une matière narrative vivante, pas d'un compte-rendu administratif.
```

- [ ] **Step 3: Update `journal_system.md`**

Replace the line `- Longueur totale : 200 à 350 mots répartis sur les 3 chapitres` with:
```
- Longueur totale : respecte la fourchette de mots indiquée dans le contexte ci-dessous, répartie sur les 3 chapitres
```

Also add after `- Si l'arc émotionnel est absent ou plat, concentre-toi sur les rencontres et la pensée du soir`:
```
- Si un journal de la veille est fourni, fais-y référence naturellement si c'est pertinent ("hier je parlais de...", "la suite de..."). Ne force pas la référence si rien ne s'y prête.
```

- [ ] **Step 4: Commit**

```bash
git add bot/persona/prompts/journal_system.md bot/persona/prompts/journal_chunk_system.md bot/persona/prompts/journal_final_system.md
git commit -m "feat(prompts): richer summaries (F2), preserve pseudos (F3), dynamic length placeholder (F1)"
```

---

### Task 3: Propagate platform in `append_message` (F7)

**Files:**
- Modify: `bot/core/memory.py:278-287`
- Modify: `bot/discord/handlers.py:284-287`
- Modify: `bot/twitch/handlers.py:141-142`
- Test: `tests/test_journal_improvements.py` (add tests)

- [ ] **Step 1: Write failing test**

Add to `tests/test_journal_improvements.py`:
```python
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from bot.core.memory import MemoryService


@pytest.mark.asyncio
async def test_append_message_passes_platform_to_db():
    config = MagicMock()
    config.bot.context_window_size = 20
    memory = MemoryService(config)
    db = MagicMock()
    db.log_daily_message = AsyncMock()
    memory.set_db(db)

    memory.append_message("ch1", "Alice", "Hello", platform="twitch")

    # Let fire-and-forget task run
    await asyncio.sleep(0.05)

    db.log_daily_message.assert_called_once()
    _, kwargs = db.log_daily_message.call_args
    assert kwargs.get("platform") == "twitch" or db.log_daily_message.call_args[0][-1] == "twitch"


@pytest.mark.asyncio
async def test_append_message_platform_defaults_to_discord():
    config = MagicMock()
    config.bot.context_window_size = 20
    memory = MemoryService(config)
    db = MagicMock()
    db.log_daily_message = AsyncMock()
    memory.set_db(db)

    memory.append_message("ch1", "Alice", "Hello")

    await asyncio.sleep(0.05)

    db.log_daily_message.assert_called_once()
    # platform should default to "discord"
    call_str = str(db.log_daily_message.call_args)
    assert "discord" in call_str
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py::test_append_message_passes_platform_to_db -v`
Expected: FAIL — `append_message()` doesn't accept `platform`

- [ ] **Step 3: Update `MemoryService.append_message`**

In `bot/core/memory.py`, change the method signature:
```python
def append_message(self, channel_id: str, author: str, content: str, platform: str = "discord") -> None:
    window = self._context_windows.setdefault(channel_id, [])
    window.append(
        {"author": author, "content": content, "timestamp": time.time()}
    )
    max_size = self._config.bot.context_window_size
    if len(window) > max_size:
        self._context_windows[channel_id] = window[-max_size:]
    if self._db is not None:
        self._fire(self._db.log_daily_message(channel_id, author, content, platform=platform))
```

- [ ] **Step 4: Update Discord handlers to pass platform="discord"**

In `bot/discord/handlers.py`, lines 284-287, change:
```python
bot.memory.append_message(
    str(message.channel.id), message.author.display_name, stored_content, platform="discord"
)
bot.memory.append_message(str(message.channel.id), "Wally", reply, platform="discord")
```

- [ ] **Step 5: Update Twitch handlers to pass platform="twitch"**

In `bot/twitch/handlers.py`, lines 141-142, change:
```python
bot.memory.append_message(channel_id, author, content, platform="twitch")
bot.memory.append_message(channel_id, "Wally", reply, platform="twitch")
```

- [ ] **Step 6: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py -v && python -m pytest --tb=short -q`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add bot/core/memory.py bot/discord/handlers.py bot/twitch/handlers.py tests/test_journal_improvements.py
git commit -m "feat(memory): propagate platform through append_message to daily_log (F7)"
```

---

### Task 4: Emotion peak detection (F5)

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_journal_improvements.py` (add tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_journal_improvements.py`:
```python
from bot.core.emotion import EmotionEngine


@pytest.mark.asyncio
async def test_process_message_logs_peak_above_threshold(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    config = MagicMock()
    config.emotions = {}
    config.bot = MagicMock()
    config.bot.emotion_peak_threshold = 0.7

    engine = EmotionEngine(config, db=db)
    # Force joy high so that any positive delta crosses threshold
    engine._state["joy"] = 0.65

    # Simulate NRCLex returning a delta that pushes joy above 0.7
    async def fake_analyze(text, trust_score=0.5):
        return {"joy": 0.1}

    engine.analyze_message = fake_analyze

    await engine.process_message("super cool gg", trust_score=0.5)

    # Wait for fire-and-forget task
    import asyncio
    await asyncio.sleep(0.1)

    peaks = await db.get_emotion_peaks_since(time.time() - 10)
    assert len(peaks) >= 1
    assert peaks[0]["emotion"] == "joy"
    await db.close()


@pytest.mark.asyncio
async def test_peak_antispam_prevents_duplicate(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    config = MagicMock()
    config.emotions = {}
    config.bot = MagicMock()
    config.bot.emotion_peak_threshold = 0.7

    engine = EmotionEngine(config, db=db)
    engine._state["joy"] = 0.65

    async def fake_analyze(text, trust_score=0.5):
        return {"joy": 0.1}

    engine.analyze_message = fake_analyze

    await engine.process_message("super cool gg", trust_score=0.5)
    import asyncio
    await asyncio.sleep(0.1)

    # Second call immediately — should be blocked by anti-spam
    engine._state["joy"] = 0.65
    await engine.process_message("encore plus cool", trust_score=0.5)
    await asyncio.sleep(0.1)

    peaks = await db.get_emotion_peaks_since(time.time() - 10)
    assert len(peaks) == 1  # Only one peak, second blocked
    await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py::test_process_message_logs_peak_above_threshold -v`
Expected: FAIL

- [ ] **Step 3: Implement peak detection in EmotionEngine**

In `bot/core/emotion.py`, add to `__init__`:
```python
# Peak detection anti-spam cache: emotion → timestamp of last peak
self._last_peak_ts: dict[str, float] = {}
self._bg_tasks: set[asyncio.Task] = set()
```

Add helper method:
```python
def _fire(self, coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    self._bg_tasks.add(t)
    t.add_done_callback(self._bg_tasks.discard)
    return t

async def _maybe_log_peak(
    self, emotion: str, old_value: float, new_value: float,
    trigger_user: str = "", trigger_message: str = "",
    channel_id: str = "", platform: str = "",
) -> None:
    """Log an emotion peak if it crosses the threshold."""
    threshold = getattr(self._config.bot, "emotion_peak_threshold", 0.7)
    if new_value <= threshold or new_value <= old_value:
        return
    now = time.time()
    last = self._last_peak_ts.get(emotion, 0.0)
    if now - last < 300:  # 5 minute anti-spam
        return
    self._last_peak_ts[emotion] = now
    if self._db is not None:
        try:
            await self._db.insert_emotion_peak(
                now, emotion, new_value,
                trigger_user, trigger_message, channel_id, platform,
            )
            logger.info(
                "Emotion peak logged: {e}={v:.0%} triggered by {u}",
                e=emotion, v=new_value, u=trigger_user or "unknown",
            )
        except Exception as exc:
            logger.warning("Failed to log emotion peak: {e}", e=exc)
```

Update `process_message()` to detect peaks after applying deltas. Add before `return` (LLM path) and at end (NRCLex fallback path):
```python
# After applying deltas, check for peaks
state_after = self.get_state()
for emotion in deltas:
    if deltas[emotion] > 0:
        self._fire(self._maybe_log_peak(
            emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
        ))
```

The full `process_message` becomes:
```python
async def process_message(
    self, text: str, trust_score: float = 0.5, context_messages: list[dict] | None = None,
    image_urls: list[str] | None = None,
    trigger_user: str = "", channel_id: str = "", platform: str = "",
) -> None:
    self.record_interaction()
    state_before = self.get_state()
    if self._openai is not None and context_messages:
        try:
            deltas, new_words = await self._analyze_llm(
                text, trust_score, context_messages, image_urls=image_urls
            )
            for emotion, delta in deltas.items():
                self.apply_delta(emotion, delta)
            if new_words:
                await self._learn_words(new_words)
            # Check for peaks
            state_after = self.get_state()
            for emotion, delta in deltas.items():
                if delta > 0:
                    self._fire(self._maybe_log_peak(
                        emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
                        trigger_user=trigger_user, trigger_message=text,
                        channel_id=channel_id, platform=platform,
                    ))
            return
        except Exception as exc:
            logger.warning("LLM emotion analysis failed, using fallback: {e}", e=exc)
    # Fallback : NRCLex + FR_EMOTION_WORDS
    deltas = await self.analyze_message(text, trust_score)
    for emotion, delta in deltas.items():
        self.apply_delta(emotion, delta)
    state_after = self.get_state()
    for emotion, delta in deltas.items():
        if delta > 0:
            self._fire(self._maybe_log_peak(
                emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
                trigger_user=trigger_user, trigger_message=text,
                channel_id=channel_id, platform=platform,
            ))
```

- [ ] **Step 4: Update callers to pass trigger context**

In `bot/discord/handlers.py` `_post_process`, update the `process_message` call:
```python
await bot.emotion.process_message(
    text, trust_score=trust, context_messages=context_messages,
    image_urls=image_urls,
    trigger_user=user_id, channel_id=str(message_channel_id),
    platform="discord",
)
```

Note: `_post_process` doesn't have `message` object, so pass `user_id` and add a `message_channel_id` parameter. Update `_post_process` signature to add `channel_id: str = ""`:
```python
async def _post_process(
    bot: "WallyDiscord",
    text: str,
    platform: str,
    user_id: str,
    guild_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
    image_urls: list[str] | None = None,
    channel_id: str = "",
) -> None:
```

And update the call site in `_respond` (line 295):
```python
_fire(_post_process(
    bot, text_content, platform, user_id, guild_id, trust, context_messages,
    image_urls=image_urls or None,
    channel_id=str(message.channel.id),
))
```

In `bot/twitch/handlers.py` `_post_process`, similarly add `channel_id` and `trigger_user`:
```python
async def _post_process(
    bot: "WallyTwitch",
    text: str,
    platform: str,
    user_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
    channel_id: str = "",
) -> None:
    try:
        await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            trigger_user=user_id, channel_id=channel_id, platform="twitch",
        )
```

Update the call in `handle_message`:
```python
_fire(_post_process(bot, content, platform, user_id, trust, context_msgs, channel_id=channel_id))
```

- [ ] **Step 5: Update Twitch events.py for peak detection on direct `apply_delta` calls**

In `bot/twitch/events.py`, every `bot.emotion.apply_delta("joy", ...)` call should be followed by a peak check. Add a helper and update each event handler. Add at module level:

```python
def _check_peak(bot, emotion: str, old_val: float, delta: float, username: str = "", event_name: str = ""):
    """Fire-and-forget peak check for Twitch events."""
    new_val = min(1.0, old_val + delta)
    if hasattr(bot.emotion, '_maybe_log_peak'):
        from bot.twitch.handlers import _fire
        _fire(bot.emotion._maybe_log_peak(
            emotion, old_val, new_val,
            trigger_user=username,
            trigger_message=f"[Twitch {event_name}]",
            channel_id="", platform="twitch",
        ))
```

Then at each `apply_delta` call site, add the peak check before applying:
```python
old_joy = bot.emotion.get_state().get("joy", 0.0)
bot.emotion.apply_delta("joy", delta)
_check_peak(bot, "joy", old_joy, delta, username=username, event_name="follow")
```

Apply this pattern for: follow (0.1), subscribe (0.4), resub (0.3), gift_sub (0.5), bits (variable), raid (variable).

- [ ] **Step 6: Add `emotion_peak_threshold` to config.yaml**

Add to `config.yaml` under `bot:`:
```yaml
  emotion_peak_threshold: 0.7
```

- [ ] **Step 7: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py -v && python -m pytest --tb=short -q`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add bot/core/emotion.py bot/discord/handlers.py bot/twitch/handlers.py bot/twitch/events.py config.yaml tests/test_journal_improvements.py
git commit -m "feat(emotion): detect and log emotion peaks with anti-spam (F5)"
```

---

### Task 5: Stats block + top participants + dynamic length (F4, F8, F1)

**Files:**
- Modify: `bot/core/journal.py`
- Test: `tests/test_journal_improvements.py` (add tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_journal_improvements.py`:
```python
from bot.core.journal import _build_stats_block, _get_word_range


def test_build_stats_block_basic():
    messages = [
        {"author": "Alice", "content": "Hello", "timestamp": 1710800000.0, "platform": "discord"},
        {"author": "Bob", "content": "Hi", "timestamp": 1710803600.0, "platform": "discord"},
        {"author": "Alice", "content": "Sup", "timestamp": 1710807200.0, "platform": "twitch"},
    ]
    block = _build_stats_block(messages)
    assert "Messages : 3" in block
    assert "Participants : 2" in block
    assert "Alice (2 msgs)" in block
    assert "Discord" in block or "discord" in block


def test_build_stats_block_empty():
    block = _build_stats_block([])
    assert block == ""


def test_get_word_range():
    assert _get_word_range(10) == "150 à 250"
    assert _get_word_range(49) == "150 à 250"
    assert _get_word_range(50) == "250 à 400"
    assert _get_word_range(150) == "250 à 400"
    assert _get_word_range(151) == "400 à 600"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py::test_build_stats_block_basic -v`
Expected: FAIL — `_build_stats_block` doesn't exist

- [ ] **Step 3: Implement `_build_stats_block` and `_get_word_range`**

In `bot/core/journal.py`, add these module-level functions:

```python
from collections import Counter
from datetime import datetime as _dt


def _get_word_range(message_count: int) -> str:
    if message_count < 50:
        return "150 à 250"
    if message_count <= 150:
        return "250 à 400"
    return "400 à 600"


def _build_active_hours(messages: list[dict]) -> str:
    """Build human-readable active hour ranges from messages."""
    if not messages:
        return ""
    hours: set[int] = set()
    for m in messages:
        ts = m.get("timestamp", 0)
        if ts:
            hours.add(_dt.fromtimestamp(ts, tz=_TZ_JOURNAL).hour)
    if not hours:
        return ""
    sorted_hours = sorted(hours)
    ranges: list[str] = []
    start = prev = sorted_hours[0]
    for h in sorted_hours[1:]:
        if h - prev <= 1:
            prev = h
        else:
            ranges.append(f"{start}h-{prev + 1}h" if start != prev else f"{start}h")
            start = prev = h
    ranges.append(f"{start}h-{prev + 1}h" if start != prev else f"{start}h")
    return ", ".join(ranges)


def _build_stats_block(messages: list[dict]) -> str:
    if not messages:
        return ""
    count = len(messages)
    authors = Counter(m["author"] for m in messages)
    unique = len(authors)
    top5 = ", ".join(f"{name} ({n} msgs)" for name, n in authors.most_common(5))
    active = _build_active_hours(messages)

    lines = [
        "Statistiques de la journée :",
        f"- Messages : {count}",
        f"- Participants : {unique}",
    ]
    if active:
        lines.append(f"- Activité : {active}")

    # Platform breakdown
    platforms = Counter(m.get("platform", "discord") for m in messages)
    if len(platforms) > 1:
        breakdown = ", ".join(f"{p.capitalize()} ({n})" for p, n in platforms.most_common())
        lines.append(f"- Plateformes : {breakdown}")

    lines.append(f"- Top participants : {top5}")
    return "\n".join(lines)
```

- [ ] **Step 4: Update `_CHUNK_SIZE` constant**

Change `_CHUNK_SIZE = 20` to `_CHUNK_SIZE = 30`.

- [ ] **Step 5: Update the fallback string for `_JOURNAL_SYSTEM`**

Change the fallback in `_JOURNAL_SYSTEM` (lines 32-35):
```python
_JOURNAL_SYSTEM = load_prompt(
    "journal_system",
    fallback=(
        "Tu es Wally, un bot de chat Discord. Chaque soir tu écris ton journal intime.\n\n"
        "Rédige une entrée de journal en 3 à 5 paragraphes, à la première personne, "
        "ton sincère et introspectif. Respecte la fourchette de mots indiquée dans le contexte."
    ),
)
```

Also update `_CHUNK_SYSTEM` fallback:
```python
_CHUNK_SYSTEM = load_prompt(
    "journal_chunk_system",
    fallback=(
        "Tu es le module de mémoire de Wally. Résume le bloc de messages en 5 à 10 lignes, "
        "texte brut, sans titre. Mentionne toujours qui a dit ou fait quoi par son pseudo exact."
    ),
)
```

And `_FINAL_SYSTEM` fallback:
```python
_FINAL_SYSTEM = load_prompt(
    "journal_final_system",
    fallback=(
        "Tu es le module de mémoire de Wally. Synthétise les résumés en 10 à 20 lignes, "
        "texte brut, sans titre. Mentionne toujours qui a dit ou fait quoi par son pseudo exact."
    ),
)
```

- [ ] **Step 6: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py -v && python -m pytest --tb=short -q`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add bot/core/journal.py tests/test_journal_improvements.py
git commit -m "feat(journal): stats block (F4), top participants (F8), dynamic length helper (F1), chunk size 30 (F2)"
```

---

### Task 6: Wire everything into `generate_and_send` (F1, F4, F5, F6, F9, F11)

**Files:**
- Modify: `bot/core/journal.py`
- Test: `tests/test_journal_improvements.py` (add tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_journal_improvements.py`:
```python
@pytest.mark.asyncio
async def test_journal_injects_stats_and_word_range(tmp_path):
    """Stats block, word range, and peaks are injected in the journal prompt."""
    from unittest.mock import MagicMock, AsyncMock
    from bot.core.journal import DailyJournal

    db_inst = await Database.create(str(tmp_path / "test.db"))
    now = time.time()
    # Insert messages into daily_log
    for i in range(60):
        await db_inst.log_daily_message("ch1", "Alice" if i % 2 == 0 else "Bob", f"msg {i}", platform="discord")
    # Insert a peak
    await db_inst.insert_emotion_peak(now, "joy", 0.85, "Alice", "LOL", "ch1", "discord")
    # Insert yesterday's journal
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    await db_inst.insert_journal(yesterday, "Journal d'hier : tout était calme.", 6)

    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "03:00"
    config.bot.emotion_peak_threshold = 0.7

    openai_mock = MagicMock()
    openai_mock.complete_secondary = AsyncMock(return_value="Summary text.")

    captured_journal_prompt = []
    async def fake_complete(system, messages, purpose="", **kwargs):
        captured_journal_prompt.append(messages[0]["content"])
        return "Generated journal text"

    openai_mock.complete = fake_complete

    emotion = MagicMock()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.1, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[])

    journal = DailyJournal(config, openai_mock, emotion, memory, db=db_inst)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send()

    assert len(captured_journal_prompt) == 1
    prompt = captured_journal_prompt[0]
    assert "Messages : 60" in prompt
    assert "250 à 400" in prompt
    await db_inst.close()


@pytest.mark.asyncio
async def test_journal_archives_after_send(tmp_path):
    from unittest.mock import MagicMock, AsyncMock
    from bot.core.journal import DailyJournal

    db_inst = await Database.create(str(tmp_path / "test.db"))
    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "03:00"
    config.bot.emotion_peak_threshold = 0.7
    openai_mock = MagicMock()
    openai_mock.complete_secondary = AsyncMock(return_value="Summary.")
    openai_mock.complete = AsyncMock(return_value="Mon journal du jour.")
    emotion = MagicMock()
    emotion.get_state = MagicMock(return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[{"author": "A", "content": "hi", "timestamp": 1000.0}])

    journal = DailyJournal(config, openai_mock, emotion, memory, db=db_inst)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send()

    from datetime import date
    today = date.today().isoformat()
    row = await db_inst.fetch_one("SELECT * FROM journal_archive WHERE date = ?", (today,))
    assert row is not None
    assert "Mon journal du jour." in row["content"]
    await db_inst.close()


@pytest.mark.asyncio
async def test_journal_archive_false_does_not_archive(tmp_path):
    from unittest.mock import MagicMock, AsyncMock
    from bot.core.journal import DailyJournal

    db_inst = await Database.create(str(tmp_path / "test.db"))
    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "03:00"
    config.bot.emotion_peak_threshold = 0.7
    openai_mock = MagicMock()
    openai_mock.complete_secondary = AsyncMock(return_value="Summary.")
    openai_mock.complete = AsyncMock(return_value="Test journal.")
    emotion = MagicMock()
    emotion.get_state = MagicMock(return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[{"author": "A", "content": "hi", "timestamp": 1000.0}])

    journal = DailyJournal(config, openai_mock, emotion, memory, db=db_inst)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send(archive=False)

    from datetime import date
    today = date.today().isoformat()
    row = await db_inst.fetch_one("SELECT * FROM journal_archive WHERE date = ?", (today,))
    assert row is None
    await db_inst.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py::test_journal_archives_after_send -v`
Expected: FAIL

- [ ] **Step 3: Rewrite `generate_and_send` with all enrichments**

In `bot/core/journal.py`, update `generate_and_send`:

```python
async def generate_and_send(self, archive: bool = True) -> None:
    channel_id = self._config.bot.journal_channel_id
    if not channel_id:
        logger.warning("No journal_channel_id configured, skipping journal")
        return

    logger.info("Generating daily journal...")

    # Source 1 : daily_log SQLite
    if self._db is not None:
        try:
            db_messages = await self._db.get_today_messages()
        except Exception as exc:
            logger.warning("Failed to get daily_log messages: {e}", e=exc)
            db_messages = []
    else:
        db_messages = []

    # Source 2 : Discord channel history
    if not db_messages and self._fetch_history_cb is not None:
        try:
            db_messages = await self._fetch_history_cb()
            if db_messages:
                logger.info("Journal: using Discord history fallback ({n} messages)", n=len(db_messages))
        except Exception as exc:
            logger.warning("Journal Discord history fallback failed: {e}", e=exc)
            db_messages = []

    # Source 3 : fenêtres RAM
    ram_messages = self._memory.get_all_contexts()
    all_messages = db_messages if db_messages else ram_messages
    if not db_messages and ram_messages:
        logger.info("Journal: using RAM context fallback ({n} messages)", n=len(ram_messages))

    if all_messages:
        context_text = await self._build_context_text(all_messages)
    else:
        context_text = await self._build_mem0_fallback_context()
        if not context_text:
            logger.warning("Journal: all sources empty — generating with no conversation context")
            context_text = "Pas grand chose de notable aujourd'hui."

    # ── Stats block (F4, F8) ──
    stats_block = _build_stats_block(all_messages) if all_messages else ""

    # ── Dynamic word range (F1) ──
    word_range = _get_word_range(len(all_messages)) if all_messages else "150 à 250"

    # ── Emotion peaks (F5) ──
    peaks_block = ""
    if self._db is not None:
        try:
            peaks = await self._db.get_emotion_peaks_since(time.time() - 86400)
            if peaks:
                peak_lines = []
                for p in peaks:
                    ts = datetime.fromtimestamp(p["timestamp"], tz=_TZ_JOURNAL)
                    name_fr = _EMOTION_FR.get(p["emotion"], p["emotion"])
                    pct = int(p["value"] * 100)
                    user = p.get("trigger_user") or "inconnu"
                    msg = p.get("trigger_message") or ""
                    msg_short = msg[:80] + "…" if len(msg) > 80 else msg
                    peak_lines.append(
                        f"- {ts.strftime('%Hh%M')} — pic de {name_fr} ({pct}%) "
                        f"déclenché par {user} : \"{msg_short}\""
                    )
                peaks_block = "Moments forts émotionnels :\n" + "\n".join(peak_lines)
        except Exception as exc:
            logger.warning("Failed to get emotion peaks for journal: {e}", e=exc)

    # ── Emotion arc ──
    try:
        snapshots = await self._db.get_emotion_snapshots_since(time.time() - 86400) if self._db else []
    except Exception as exc:
        logger.warning("Failed to get emotion snapshots for journal: {e}", e=exc)
        snapshots = []

    arc = _build_emotion_arc(snapshots)

    # ── Comparative emotion weather (F9) ──
    weather_block = ""
    if self._db is not None:
        try:
            week_avgs = await self._db.get_emotion_averages(time.time() - 7 * 86400)
            day_avgs = await self._db.get_emotion_averages(time.time() - 86400)
            if week_avgs and day_avgs:
                diffs = []
                for emotion in ["anger", "joy", "sadness", "curiosity", "boredom"]:
                    delta = day_avgs[emotion] - week_avgs[emotion]
                    if abs(delta) >= 0.10:
                        name_fr = _EMOTION_FR.get(emotion, emotion)
                        sign = "+" if delta > 0 else ""
                        pct = int(delta * 100)
                        direction = "plus haute que d'habitude" if delta > 0 else "en baisse"
                        diffs.append(f"{name_fr} {direction} ({sign}{pct}%)")
                if diffs:
                    weather_block = "Comparé à la semaine : " + ", ".join(diffs)
        except Exception as exc:
            logger.warning("Failed to compute emotion weather: {e}", e=exc)

    # ── Yesterday's journal (F6) ──
    yesterday_block = ""
    if self._db is not None:
        try:
            yesterday = await self._db.get_yesterday_journal()
            if yesterday:
                yesterday_block = f"Ton journal d'hier :\n{yesterday['content']}"
        except Exception as exc:
            logger.warning("Failed to get yesterday's journal: {e}", e=exc)

    # ── Current emotion state ──
    emotions = self._emotion.get_state()
    emotions_text = ", ".join(
        f"{_EMOTION_FR.get(k, k)}: {int(v * 100)}%" for k, v in emotions.items()
    )

    # ── Build user prompt ──
    sections = [
        f"Fourchette de mots pour cette entrée : {word_range} mots.",
    ]
    if stats_block:
        sections.append(stats_block)
    sections.append(f"Voici un résumé de la journée :\n\n{context_text}")
    if peaks_block:
        sections.append(peaks_block)
    if arc:
        sections.append(arc)
    if weather_block:
        sections.append(weather_block)
    sections.append(f"Ton état émotionnel actuel : {emotions_text}")
    if yesterday_block:
        sections.append(yesterday_block)
    sections.append("Écris ton journal intime pour aujourd'hui.")

    user_msg = "\n\n".join(sections)

    # ── Generate with primary model (F11) ──
    journal_text = await self._openai.complete(
        _JOURNAL_SYSTEM,
        [{"role": "user", "content": user_msg}],
        purpose="daily_journal",
    )

    formatted = f"# Journal de Wally — {self._today()}\n\n{journal_text}"
    if self._send_cb:
        for chunk in _split_for_discord(formatted):
            await self._send_cb(chunk)
        logger.info("Daily journal sent to channel {ch}", ch=channel_id)
    else:
        logger.warning("No send callback set for journal — generated but not sent")

    # ── Archive (F6) ──
    if archive and self._db is not None:
        try:
            word_count = len(journal_text.split())
            await self._db.insert_journal(
                date.today().isoformat(), journal_text, word_count,
            )
            logger.info("Journal archived ({n} words)", n=word_count)
        except Exception as exc:
            logger.warning("Failed to archive journal: {e}", e=exc)
```

- [ ] **Step 4: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py -v && python -m pytest --tb=short -q`
Expected: ALL PASS

- [ ] **Step 5: Fix existing tests for new signatures**

The existing `tests/test_journal.py` must be updated because:
- `generate_and_send` now uses `complete()` instead of `complete_secondary()` for the final journal
- The send callback now receives `**kwargs` (for `file=`)
- Config needs `emotion_peak_threshold`

In `tests/test_journal.py`:

Update `make_deps`:
```python
def make_deps(journal_channel_id=12345, journal_time="03:00"):
    config = MagicMock()
    config.bot.journal_channel_id = journal_channel_id
    config.bot.journal_time = journal_time
    config.bot.emotion_peak_threshold = 0.7

    openai = MagicMock()
    openai.complete_secondary = AsyncMock(return_value="Journal entry text.")
    openai.complete = AsyncMock(return_value="Journal entry text.")
    # ... rest unchanged
```

Update all `set_send_callback` lambdas to accept `**kw`:
```python
journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
```

Update `_get_journal_user_msg` to check `complete()` first:
```python
def _get_journal_user_msg(openai_mock) -> str:
    if openai_mock.complete.called:
        call_args = openai_mock.complete.call_args_list
        journal_call = [c for c in call_args if c.kwargs.get("purpose") == "daily_journal"]
        if journal_call:
            return journal_call[0].args[1][0]["content"]
    call_args = openai_mock.complete_secondary.call_args_list
    journal_call = [c for c in call_args if c.kwargs.get("purpose") == "daily_journal"]
    assert journal_call, "complete/complete_secondary should be called with purpose=daily_journal"
    return journal_call[0].args[1][0]["content"]
```

Update `make_deps_with_db` to include `config.bot.emotion_peak_threshold = 0.7`.

- [ ] **Step 6: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest --tb=short -q`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add bot/core/journal.py tests/test_journal_improvements.py tests/test_journal.py
git commit -m "feat(journal): wire stats, peaks, weather, archive, yesterday, dynamic length, primary model (F1/F4/F5/F6/F9/F11)"
```

---

### Task 7: Emotion chart image (F10)

**Files:**
- Modify: `bot/core/journal.py`
- Modify: `bot/main.py`
- Modify: `requirements.txt`
- Test: `tests/test_journal_improvements.py` (add test)

- [ ] **Step 1: Add matplotlib to requirements.txt**

Add after the `# Scheduler` block:
```
# Chart generation
matplotlib>=3.8.0
```

- [ ] **Step 2: Install matplotlib**

Run: `cd /opt/stacks/wally-ai && pip install matplotlib>=3.8.0`

- [ ] **Step 3: Write failing test**

Add to `tests/test_journal_improvements.py`:
```python
from bot.core.journal import _generate_emotion_chart


def test_generate_emotion_chart_returns_bytes():
    import time
    now = time.time()
    snapshots = [
        {"snapshot_at": now - 7200, "anger": 0.1, "joy": 0.6, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0},
        {"snapshot_at": now - 3600, "anger": 0.0, "joy": 0.8, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.1},
        {"snapshot_at": now, "anger": 0.2, "joy": 0.5, "sadness": 0.1, "curiosity": 0.4, "boredom": 0.0},
    ]
    buf = _generate_emotion_chart(snapshots)
    assert buf is not None
    data = buf.getvalue()
    assert len(data) > 1000  # should be a valid PNG
    assert data[:4] == b'\x89PNG'


def test_generate_emotion_chart_returns_none_with_less_than_2():
    assert _generate_emotion_chart([]) is None
    assert _generate_emotion_chart([{"snapshot_at": 0, "anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}]) is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py::test_generate_emotion_chart_returns_bytes -v`
Expected: FAIL

- [ ] **Step 5: Implement `_generate_emotion_chart`**

In `bot/core/journal.py`, add:
```python
from io import BytesIO


_EMOTION_COLORS = {
    "anger": "#ff3333",
    "joy": "#ffdd00",
    "curiosity": "#00ccff",
    "sadness": "#7777ff",
    "boredom": "#888888",
}


def _generate_emotion_chart(snapshots: list[dict]) -> BytesIO | None:
    """Generate a dark-themed emotion chart. Returns PNG as BytesIO, or None if < 2 snapshots."""
    if len(snapshots) < 2:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    times = [datetime.fromtimestamp(s["snapshot_at"], tz=_TZ_JOURNAL) for s in snapshots]

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a1a")
    ax.set_facecolor("#1a1a1a")

    for emotion in EMOTIONS:
        values = [s[emotion] * 100 for s in snapshots]
        color = _EMOTION_COLORS.get(emotion, "#ffffff")
        label = _EMOTION_FR.get(emotion, emotion).capitalize()
        ax.plot(times, values, color=color, label=label, linewidth=2)

    ax.set_ylim(0, 100)
    ax.set_ylabel("Intensité (%)", color="#aaaaaa", fontsize=10)
    ax.set_xlabel("")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Hh", tz=_TZ_JOURNAL))
    ax.tick_params(colors="#aaaaaa")
    ax.grid(True, color="#333333", linewidth=0.5, alpha=0.5)
    for spine in ax.spines.values():
        spine.set_color("#444444")

    ax.legend(loc="upper right", fontsize=9, facecolor="#1a1a1a", edgecolor="#444444", labelcolor="#ffffff")
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor="#1a1a1a", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf
```

Also import `EMOTIONS` at the top of journal.py if not already:
```python
from bot.core.emotion import EMOTIONS
```

- [ ] **Step 6: Update `generate_and_send` to send the chart**

In `generate_and_send`, after generating the chart data, before sending the text:
```python
# ── Emotion chart image (F10) ──
chart_buf = _generate_emotion_chart(snapshots) if snapshots else None

formatted = f"# Journal de Wally — {self._today()}\n\n{journal_text}"
if self._send_cb:
    if chart_buf:
        await self._send_cb("", file=chart_buf)
    for chunk in _split_for_discord(formatted):
        await self._send_cb(chunk)
```

Update `set_send_callback` type hint and the callback signature in `main.py`:
```python
def set_send_callback(self, cb: Callable[..., Any]) -> None:
    """Inject an async callable: async def send(text: str, file: BytesIO | None = None) -> None"""
    self._send_cb = cb
```

- [ ] **Step 7: Update `journal_send_cb` in main.py**

```python
async def journal_send_cb(text: str, file=None) -> None:
    channel_id = config.bot.journal_channel_id
    if channel_id:
        ch = discord_bot.get_channel(channel_id)
        if ch:
            if file and not text:
                import discord as _discord
                await ch.send(file=_discord.File(file, filename="emotions_jour.png"))
            elif file:
                import discord as _discord
                await ch.send(text, file=_discord.File(file, filename="emotions_jour.png"))
            else:
                await ch.send(text)
```

- [ ] **Step 8: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py -v && python -m pytest --tb=short -q`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add bot/core/journal.py bot/main.py requirements.txt tests/test_journal_improvements.py
git commit -m "feat(journal): emotion chart image with matplotlib (F10)"
```

---

### Task 8: `/wally test` command (F12)

**Files:**
- Create: `bot/discord/commands/test_cmd.py`
- Modify: `bot/discord/bot.py`
- Test: `tests/test_journal_improvements.py` (add test)

- [ ] **Step 1: Write failing test**

Add to `tests/test_journal_improvements.py`:
```python
@pytest.mark.asyncio
async def test_test_command_cog_exists():
    from bot.discord.commands.test_cmd import TestCog
    assert TestCog is not None
```

- [ ] **Step 2: Create `bot/discord/commands/test_cmd.py`**

```python
# bot/discord/commands/test_cmd.py
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class TestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="test",
        description="Teste une fonctionnalité de Wally (admin)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        feature="Fonctionnalité à tester",
        channel="Salon où envoyer le résultat",
    )
    @app_commands.choices(feature=[
        app_commands.Choice(name="Journal", value="journal"),
    ])
    async def test_feature(
        self,
        interaction: discord.Interaction,
        feature: app_commands.Choice[str],
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)

        if feature.value == "journal":
            await self._test_journal(interaction, channel)
        else:
            await interaction.followup.send(
                f"Fonctionnalité inconnue : {feature.value}", ephemeral=True
            )

    async def _test_journal(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
    ) -> None:
        try:
            journal = self.bot.journal
            if journal is None:
                await interaction.followup.send(
                    "Journal non initialisé.", ephemeral=True
                )
                return

            # Temporarily override send callback to target chosen channel
            original_cb = journal._send_cb

            async def test_send_cb(text: str, file=None) -> None:
                if file and not text:
                    await channel.send(
                        file=discord.File(file, filename="emotions_jour.png")
                    )
                elif file:
                    await channel.send(
                        text, file=discord.File(file, filename="emotions_jour.png")
                    )
                else:
                    await channel.send(f"[TEST] {text}")

            journal._send_cb = test_send_cb
            try:
                await journal.generate_and_send(archive=False)
            finally:
                journal._send_cb = original_cb

            await interaction.followup.send(
                f"Journal de test envoyé dans {channel.mention}.", ephemeral=True
            )
        except Exception as e:
            logger.error("Error in test journal: {e}", e=e)
            await interaction.followup.send(
                "Erreur lors de la génération du journal de test.", ephemeral=True
            )
```

- [ ] **Step 3: Register the cog in `bot/discord/bot.py`**

In `setup_hook`, add:
```python
from bot.discord.commands.test_cmd import TestCog
await self.add_cog(TestCog(self))
```

- [ ] **Step 4: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal_improvements.py -v && python -m pytest --tb=short -q`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add bot/discord/commands/test_cmd.py bot/discord/bot.py tests/test_journal_improvements.py
git commit -m "feat(discord): /wally test command for journal testing (F12)"
```

---

### Task 9: Update TODO.md

**Files:**
- Modify: `TODO.md`

- [ ] **Step 1: Check off completed items in TODO.md**

Mark as done all 6 items in the "CERVEAU — Journal quotidien" section plus document the extra features implemented.

- [ ] **Step 2: Commit**

```bash
git add TODO.md
git commit -m "docs: mark journal improvements as complete in TODO"
```
