# Improved Memory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the session-based memory extraction with a two-level system: piggyback fact extraction on emotion analysis for triggered messages + intelligent batch extraction for all messages, with alias resolution and dashboard management.

**Architecture:** New `FactExtractor` service replaces `SessionManager`. It accumulates messages in per-channel buffers, flushes them in smart batches (5 messages or conversation pause), and extracts facts via LLM with structured outputs. `EmotionEngine._analyze_llm` is extended to also extract facts on triggered messages. A `user_aliases` DB table + LLM auto-learning resolves nicknames.

**Tech Stack:** Python 3.11+, asyncio, OpenAI structured outputs, aiosqlite, mem0, FastAPI (dashboard routes)

**Spec:** `docs/superpowers/specs/2026-03-20-memory-improvement-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `bot/core/fact_extractor.py` | **New.** Pre-filter (`_is_memorable`), per-channel buffer, flush logic, batch LLM extraction, alias resolution, orphan reconciliation, `analyze_channel_messages()` |
| `bot/core/openai_client.py` | **Modified.** Add `complete_secondary_structured()` method |
| `bot/core/emotion.py` | **Modified.** `_analyze_llm` uses structured outputs, adds `user_facts` field |
| `bot/core/memory.py` | **Modified.** `load_aliases()` loads from `user_aliases` table too, add `delete_user_memories()` |
| `bot/core/sessions.py` | **Deleted.** Replaced by `FactExtractor` |
| `bot/db/database.py` | **Modified.** `user_aliases` table, migration `session_messages`, alias CRUD |
| `bot/main.py` | **Modified.** DI wiring for `FactExtractor`, remove `SessionManager` |
| `bot/discord/handlers.py` | **Modified.** Use `fact_extractor.record_message()`, piggyback in `_post_process` |
| `bot/discord/bot.py` | **Modified.** Replace `session_manager` attribute with `fact_extractor` |
| `bot/discord/commands/scan_cmd.py` | **Modified.** Use `fact_extractor.analyze_channel_messages()` |
| `bot/discord/commands/ask.py` | **Modified.** Use `fact_extractor.record_message()` |
| `bot/twitch/handlers.py` | **Modified.** Use `fact_extractor.record_message()`, piggyback in `_post_process` |
| `bot/dashboard/state.py` | **Modified.** Add `fact_extractor` optional field |
| `bot/dashboard/routes/memory.py` | **Modified.** Add alias API routes |
| `bot/persona/prompts/fact_extraction_system.md` | **New.** Batch extraction prompt template |
| `tests/test_fact_extractor.py` | **New.** Tests for `FactExtractor` |
| `tests/test_structured_outputs.py` | **New.** Tests for `complete_secondary_structured()` |

---

### Task 1: `complete_secondary_structured()` in OpenAIClient

**Files:**
- Modify: `bot/core/openai_client.py`
- Test: `tests/test_structured_outputs.py`

- [ ] **Step 1: Write the test file**

```python
# tests/test_structured_outputs.py
from __future__ import annotations
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.openai_client import OpenAIClient

SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "value": {"type": "number"},
    },
    "required": ["name", "value"],
    "additionalProperties": False,
}


@pytest.fixture
def client():
    config = MagicMock()
    config.openai.primary_model = "gpt-4o"
    config.openai.secondary_model = "gpt-4o-mini"
    config.openai.temperature = 0.7
    config.openai.max_tokens = 1000
    config.openai.reasoning_effort = None
    config.openai.text_verbosity = None
    db = AsyncMock()
    db.log_cost = AsyncMock()
    with patch("bot.core.openai_client.AsyncOpenAI"):
        return OpenAIClient(config, db)


@pytest.mark.asyncio
async def test_structured_chat_completions(client):
    """Chat Completions API path returns parsed dict."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].finish_reason = "stop"
    mock_response.choices[0].message.content = '{"name": "test", "value": 42}'
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5
    mock_response.usage.prompt_tokens_details = None

    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.complete_secondary_structured(
        "system prompt",
        [{"role": "user", "content": "test"}],
        schema=SIMPLE_SCHEMA,
        schema_name="test_schema",
        purpose="test",
    )

    assert result == {"name": "test", "value": 42}
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert "response_format" in call_kwargs
    assert call_kwargs["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_structured_truncated_response_raises(client):
    """Truncated response (finish_reason=length) should raise."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].finish_reason = "length"
    mock_response.choices[0].message.content = '{"name": "trun'
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5
    mock_response.usage.prompt_tokens_details = None

    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    with pytest.raises(Exception, match="truncated"):
        await client.complete_secondary_structured(
            "system prompt",
            [{"role": "user", "content": "test"}],
            schema=SIMPLE_SCHEMA,
        )


@pytest.mark.asyncio
async def test_structured_responses_api(client):
    """Responses API path (o1/o3/o4/gpt-5 models) returns parsed dict."""
    # Override to use a Responses API model
    client._config.openai.secondary_model = "o4-mini"

    mock_response = MagicMock()
    mock_response.output_text = '{"name": "resp", "value": 99}'
    mock_response.status = "completed"
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_response.usage.input_tokens_details = None

    client._client.responses.create = AsyncMock(return_value=mock_response)

    result = await client.complete_secondary_structured(
        "system prompt",
        [{"role": "user", "content": "test"}],
        schema=SIMPLE_SCHEMA,
        schema_name="test_schema",
        purpose="test",
    )

    assert result == {"name": "resp", "value": 99}
    call_kwargs = client._client.responses.create.call_args.kwargs
    assert "text" in call_kwargs
    assert call_kwargs["text"]["format"]["type"] == "json_schema"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_structured_outputs.py -v`
Expected: FAIL — `complete_secondary_structured` does not exist yet

- [ ] **Step 3: Implement `complete_secondary_structured()`**

Add to `bot/core/openai_client.py` after the `complete_secondary()` method (around line 492):

```python
async def complete_secondary_structured(
    self,
    system_prompt: str,
    messages: list[dict],
    schema: dict,
    schema_name: str = "response",
    purpose: str = "structured",
    user_id: str | None = None,
) -> dict:
    """Complete with OpenAI structured outputs — returns parsed dict.

    Uses json_schema response format to guarantee valid JSON matching the schema.
    Raises on total failure or truncated response — caller must handle.
    """
    model = self._config.openai.secondary_model
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    if _uses_responses_api(model):
        return await self._structured_responses_api(
            model, full_messages, schema, schema_name, purpose, user_id
        )
    return await self._structured_chat_completions(
        model, full_messages, schema, schema_name, purpose, user_id
    )

async def _structured_responses_api(
    self, model: str, messages: list[dict], schema: dict,
    schema_name: str, purpose: str, user_id: str | None,
) -> dict:
    kwargs: dict = {
        "model": model,
        "input": messages,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
            }
        },
    }
    effort = self._config.openai.reasoning_effort
    if effort and effort != "none":
        kwargs["reasoning"] = {"effort": effort}
    if self._config.openai.max_tokens:
        kwargs["max_output_tokens"] = self._config.openai.max_tokens

    for attempt in range(3):
        try:
            response = await self._client.responses.create(**kwargs)
            # Check for truncation
            if response.status != "completed":
                raise RuntimeError(
                    f"Structured output truncated (status={response.status})"
                )
            text = response.output_text
            if response.usage:
                try:
                    cached = response.usage.input_tokens_details.cached_tokens or 0
                except (AttributeError, TypeError):
                    cached = 0
                cost = estimate_cost(
                    model, response.usage.input_tokens,
                    response.usage.output_tokens, cached_input_tokens=cached,
                )
                await self._db.log_cost(
                    model, response.usage.input_tokens,
                    response.usage.output_tokens, cost, purpose, user_id=user_id,
                )
            return json.loads(text)
        except (RateLimitError, APIStatusError) as exc:
            if isinstance(exc, APIStatusError) and exc.status_code < 500:
                raise
            wait = 2 ** attempt
            logger.warning("Structured API error, retrying in {w}s: {e}", w=wait, e=exc)
            await asyncio.sleep(wait)
    raise RuntimeError("Structured output failed after 3 retries")

async def _structured_chat_completions(
    self, model: str, messages: list[dict], schema: dict,
    schema_name: str, purpose: str, user_id: str | None,
) -> dict:
    for attempt in range(3):
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self._config.openai.temperature,
                max_completion_tokens=self._config.openai.max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
            choice = response.choices[0]
            if choice.finish_reason == "length":
                raise RuntimeError("Structured output truncated (finish_reason=length)")
            usage = response.usage
            try:
                cached = usage.prompt_tokens_details.cached_tokens or 0
            except (AttributeError, TypeError):
                cached = 0
            cost = estimate_cost(
                model, usage.prompt_tokens, usage.completion_tokens,
                cached_input_tokens=cached,
            )
            await self._db.log_cost(
                model, usage.prompt_tokens, usage.completion_tokens,
                cost, purpose, user_id=user_id,
            )
            return json.loads(choice.message.content)
        except RateLimitError:
            wait = 2 ** attempt
            logger.warning("Rate limited (structured), retrying in {w}s", w=wait)
            await asyncio.sleep(wait)
        except APIStatusError as exc:
            if exc.status_code >= 500:
                wait = 2 ** attempt
                logger.warning("Server error (structured), retrying in {w}s", w=wait)
                await asyncio.sleep(wait)
            else:
                raise
    raise RuntimeError("Structured output failed after 3 retries")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_structured_outputs.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add bot/core/openai_client.py tests/test_structured_outputs.py
git commit -m "feat(openai): add complete_secondary_structured() with JSON schema support"
```

---

### Task 2: DB migration — `user_aliases` table + `session_messages.is_reply`

**Files:**
- Modify: `bot/db/database.py`
- Test: `tests/test_db_aliases.py` (new)

- [ ] **Step 1: Write the test file**

```python
# tests/test_db_aliases.py
from __future__ import annotations
import asyncio
import time
import pytest
from bot.db.database import Database


@pytest.fixture
async def db(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_upsert_and_get_alias(db):
    await db.upsert_alias("rekin", "discord:123", "KingsRequin", "llm", 0.9)
    aliases = await db.list_aliases()
    assert len(aliases) == 1
    assert aliases[0]["nickname"] == "rekin"
    assert aliases[0]["canonical_uid"] == "discord:123"
    assert aliases[0]["source"] == "llm"


@pytest.mark.asyncio
async def test_manual_alias_not_overwritten_by_llm(db):
    await db.upsert_alias("rekin", "discord:123", "KingsRequin", "manual", 1.0)
    await db.upsert_alias("rekin", "discord:456", "Other", "llm", 0.95)
    aliases = await db.list_aliases()
    assert len(aliases) == 1
    assert aliases[0]["canonical_uid"] == "discord:123"  # manual preserved


@pytest.mark.asyncio
async def test_delete_alias(db):
    await db.upsert_alias("rekin", "discord:123", "KingsRequin", "llm", 0.9)
    await db.delete_alias("rekin")
    aliases = await db.list_aliases()
    assert len(aliases) == 0


@pytest.mark.asyncio
async def test_get_alias_map(db):
    await db.upsert_alias("rekin", "discord:123", "KingsRequin", "llm", 0.9)
    await db.upsert_alias("azra", "discord:456", "Azrel", "manual", 1.0)
    alias_map = await db.get_nickname_alias_map()
    assert alias_map == {"rekin": "discord:123", "azra": "discord:456"}


@pytest.mark.asyncio
async def test_list_unresolved_aliases(db):
    # No unresolved aliases initially
    unresolved = await db.list_unresolved_aliases()
    assert len(unresolved) == 0


@pytest.mark.asyncio
async def test_session_messages_has_is_reply(db):
    """Verify session_messages table has is_reply column after migration."""
    await db.execute(
        "INSERT INTO session_messages (channel_id, platform, user_id, display_name, content, timestamp, is_reply) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("ch1", "discord", "u1", "User1", "hello", time.time(), 1),
    )
    rows = await db.fetchall(
        "SELECT is_reply FROM session_messages WHERE channel_id = ?", ("ch1",)
    )
    assert rows[0]["is_reply"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_db_aliases.py -v`
Expected: FAIL — methods and table don't exist

- [ ] **Step 3: Add `user_aliases` table to schema and migration**

In `bot/db/database.py`, add to `SCHEMA` string (after `chat_refresh_tokens` table, before closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS user_aliases (
    nickname     TEXT PRIMARY KEY,
    canonical_uid TEXT NOT NULL,
    display_name TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'llm',
    confidence   REAL NOT NULL DEFAULT 0.0,
    created_at   REAL NOT NULL
);
```

In the `Database.create()` method or `_migrate()` method, add migration to add `is_reply` to `session_messages`:

```python
# Migration: add is_reply to session_messages
try:
    await db.execute(
        "ALTER TABLE session_messages ADD COLUMN is_reply INTEGER DEFAULT 0"
    )
except Exception:
    pass  # Column already exists
```

- [ ] **Step 4: Add alias CRUD methods to `Database`**

Add these methods to the `Database` class:

```python
async def upsert_alias(
    self, nickname: str, canonical_uid: str, display_name: str,
    source: str, confidence: float,
) -> None:
    nickname = nickname.lower().strip()
    # Don't overwrite manual aliases with LLM aliases
    if source == "llm":
        existing = await self.fetchone(
            "SELECT source FROM user_aliases WHERE nickname = ?", (nickname,)
        )
        if existing and existing["source"] == "manual":
            return
    await self.execute(
        "INSERT OR REPLACE INTO user_aliases "
        "(nickname, canonical_uid, display_name, source, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (nickname, canonical_uid, display_name, source, confidence, time.time()),
    )

async def delete_alias(self, nickname: str) -> None:
    await self.execute(
        "DELETE FROM user_aliases WHERE nickname = ?", (nickname.lower().strip(),)
    )

async def list_aliases(self, canonical_uid: str | None = None) -> list[dict]:
    if canonical_uid:
        rows = await self.fetchall(
            "SELECT * FROM user_aliases WHERE canonical_uid = ? ORDER BY nickname",
            (canonical_uid,),
        )
    else:
        rows = await self.fetchall("SELECT * FROM user_aliases ORDER BY nickname")
    return [dict(r) for r in rows]

async def get_nickname_alias_map(self) -> dict[str, str]:
    rows = await self.fetchall("SELECT nickname, canonical_uid FROM user_aliases")
    return {r["nickname"]: r["canonical_uid"] for r in rows}

async def list_unresolved_aliases(self) -> list[dict]:
    """List memory_users with user_id starting with 'unknown:'."""
    rows = await self.fetchall(
        "SELECT * FROM memory_users WHERE user_id LIKE 'unknown:%' ORDER BY last_updated DESC"
    )
    return [dict(r) for r in rows]

async def delete_session_messages_before(self, channel_id: str, cutoff_ts: float) -> None:
    """Delete session messages older than cutoff for partial flush cleanup."""
    await self.execute(
        "DELETE FROM session_messages WHERE channel_id = ? AND timestamp <= ?",
        (channel_id, cutoff_ts),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_db_aliases.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add bot/db/database.py tests/test_db_aliases.py
git commit -m "feat(db): add user_aliases table and alias CRUD methods"
```

---

### Task 3: Pre-filter `_is_memorable()`

**Files:**
- Create: `bot/core/fact_extractor.py` (initial file with just the filter)
- Test: `tests/test_fact_extractor.py` (new)

- [ ] **Step 1: Write the test file**

```python
# tests/test_fact_extractor.py
from __future__ import annotations
import pytest

from bot.core.fact_extractor import _is_memorable


class TestIsMemorableFilter:
    def test_short_message_rejected(self):
        assert _is_memorable("salut") is False
        assert _is_memorable("yo") is False
        assert _is_memorable("ok bro") is False  # < 15 chars

    def test_emoji_only_rejected(self):
        assert _is_memorable("😂😂😂") is False
        assert _is_memorable("🔥🔥") is False

    def test_single_interjection_rejected(self):
        assert _is_memorable("lol") is False
        assert _is_memorable("mdrrr") is False
        assert _is_memorable("ptdrrr") is False
        assert _is_memorable("xdddd") is False
        assert _is_memorable("hahaha") is False
        assert _is_memorable("okkk") is False
        assert _is_memorable("ggg") is False
        assert _is_memorable("ouiii") is False
        assert _is_memorable("nooon") is False
        assert _is_memorable("^^") is False
        assert _is_memorable("+1") is False
        assert _is_memorable("rip") is False
        assert _is_memorable("aaah") is False
        assert _is_memorable("ooooh") is False

    def test_all_interjections_rejected(self):
        # All words are interjections → rejected (even if > 15 chars total)
        assert _is_memorable("non non non non") is False
        assert _is_memorable("lol mdr ptdr xd") is False

    def test_interjection_with_content_passes(self):
        assert _is_memorable("mdr c'est trop vrai ce que tu dis") is True
        assert _is_memorable("oui je suis développeur Python") is True
        assert _is_memorable("lol j'habite à Marseille") is True

    def test_informative_message_passes(self):
        assert _is_memorable("je suis développeur Python depuis 3 ans") is True
        assert _is_memorable("j'habite à Lyon, je bosse dans une startup") is True
        assert _is_memorable("franchement j'adore le metal scandinave") is True

    def test_medium_message_passes(self):
        assert _is_memorable("c'est vraiment intéressant comme approche") is True

    def test_whitespace_handling(self):
        assert _is_memorable("  lol  ") is False
        assert _is_memorable("  mdr  ") is False
        assert _is_memorable("  je suis dev  ") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_fact_extractor.py::TestIsMemorableFilter -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement `_is_memorable()`**

Create `bot/core/fact_extractor.py`:

```python
# bot/core/fact_extractor.py
from __future__ import annotations

import re
import unicodedata

# ── Pre-filter: decide if a message is worth extracting facts from ──────────

_MIN_LENGTH = 15

# Regex patterns for stretchable interjections (matched per-word)
_INTERJECTION_PATTERNS = [
    re.compile(r"^lo+l+$"),
    re.compile(r"^md(r+)$"),
    re.compile(r"^ptd(r+)$"),
    re.compile(r"^x+d+$"),
    re.compile(r"^ha(ha)+$"),
    re.compile(r"^o+k+$"),
    re.compile(r"^gg+$"),
    re.compile(r"^wp+$"),
    re.compile(r"^a+h+$"),
    re.compile(r"^o+h+$"),
    re.compile(r"^ri+p+$"),
    re.compile(r"^ou+i+$"),
    re.compile(r"^no+n+$"),
    re.compile(r"^\^{2,}$"),
    re.compile(r"^\+1$"),
]


def _is_emoji_only(text: str) -> bool:
    """Return True if text is composed only of emoji and whitespace."""
    for ch in text:
        if ch.isspace():
            continue
        if unicodedata.category(ch) not in ("So", "Sk", "Mn", "Cf"):
            return False
    return True


def _is_interjection(word: str) -> bool:
    """Return True if a single word matches any interjection pattern."""
    return any(p.match(word) for p in _INTERJECTION_PATTERNS)


def _is_memorable(text: str) -> bool:
    """Return True if a message is worth accumulating for fact extraction."""
    text = text.strip()
    if len(text) < _MIN_LENGTH:
        return False
    if _is_emoji_only(text):
        return False
    # Split into words and check if ALL are interjections
    words = text.lower().split()
    if not words:
        return False
    if all(_is_interjection(w) for w in words):
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_fact_extractor.py::TestIsMemorableFilter -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot/core/fact_extractor.py tests/test_fact_extractor.py
git commit -m "feat(memory): add pre-filter _is_memorable() for fact extraction"
```

---

### Task 4: Fact extraction prompt template

**Files:**
- Create: `bot/persona/prompts/fact_extraction_system.md`

- [ ] **Step 1: Create the prompt template**

```markdown
Tu es le module d'extraction de faits de Wally, un bot Discord et Twitch. Tu analyses des paquets de messages pour extraire les informations durables sur les participants.

## Ce que tu reçois
- Une conversation (format [pseudo]: message)
- La liste des participants connus du salon avec leurs identifiants
- Les alias déjà connus (surnoms → utilisateurs)

## Ce que tu dois extraire

### Faits durables (par personne détectée)
- Centres d'intérêt et passions mentionnés
- Préférences explicites (outils, langages, genres, habitudes)
- Faits biographiques (métier, localisation, situation si mentionnés)
- Opinions ou positions exprimées sur un sujet
- Traits de personnalité observables (humour, curiosité, expertise…)

### Résolution de surnoms (aliases)
Quand un participant utilise un surnom pour parler de quelqu'un, essaie de le résoudre vers un participant connu du salon. Exemples :
- "Kings" → "KingsRequin" (si KingsRequin est dans la liste des participants)
- "Rekin" → "KingsRequin" (variante phonétique)

Indique ta confiance (0.0–1.0) dans chaque résolution.

## Ce que tu ignores
- Les messages de Wally (le bot)
- Les humeurs passagères et réactions ponctuelles
- Les blagues sans contenu informatif
- Les informations personnelles sensibles (adresse, téléphone, données financières)
- Tout ce qui ne dit rien de durable sur une personne

## Règles
- `target_user_id` est obligatoire si tu peux résoudre la personne vers un participant connu. Sinon, mets null.
- Ne résous un surnom que si tu es raisonnablement confiant (>= 0.7).
- Si aucun fait durable n'est détecté, retourne des listes vides.
- Les faits doivent être des phrases courtes et factuelles.
```

- [ ] **Step 2: Commit**

```bash
git add bot/persona/prompts/fact_extraction_system.md
git commit -m "feat(memory): add fact extraction prompt template"
```

---

### Task 5: `FactExtractor` — buffer, flush logic, batch extraction

**Files:**
- Modify: `bot/core/fact_extractor.py`
- Test: `tests/test_fact_extractor.py` (extend)

- [ ] **Step 1: Write buffer and flush tests**

Add to `tests/test_fact_extractor.py`:

```python
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.fact_extractor import FactExtractor


def _make_fact_extractor():
    config = MagicMock()
    memory = MagicMock()
    memory.add = AsyncMock()
    memory._alias_cache = {}
    memory.add_alias = MagicMock()
    openai = AsyncMock()
    openai.complete_secondary_structured = AsyncMock(return_value={
        "facts": [],
        "aliases": [],
    })
    db = AsyncMock()
    db.upsert_alias = AsyncMock()
    db.list_aliases = AsyncMock(return_value=[])
    db.insert_session_message = AsyncMock()
    db.delete_session_messages = AsyncMock()
    return FactExtractor(config, memory, openai, db)


class TestFactExtractorBuffer:
    @pytest.mark.asyncio
    async def test_non_memorable_not_buffered(self):
        fe = _make_fact_extractor()
        fe.record_message("ch1", "discord", "u1", "User1", "lol", is_reply=False)
        assert len(fe._buffers.get("ch1", {}).get("messages", [])) == 0

    @pytest.mark.asyncio
    async def test_memorable_message_buffered(self):
        fe = _make_fact_extractor()
        fe.record_message(
            "ch1", "discord", "u1", "User1",
            "je suis développeur Python depuis 5 ans",
            is_reply=False,
        )
        assert len(fe._buffers["ch1"]["messages"]) == 1

    @pytest.mark.asyncio
    async def test_reply_activates_chain(self):
        fe = _make_fact_extractor()
        fe.record_message(
            "ch1", "discord", "u1", "User1",
            "oui je suis d'accord avec toi sur ce point",
            is_reply=True,
        )
        assert fe._buffers["ch1"]["reply_chain_active"] is True

    @pytest.mark.asyncio
    async def test_flush_at_5_messages(self):
        fe = _make_fact_extractor()
        fe._flush_buffer = AsyncMock()
        for i in range(5):
            fe.record_message(
                "ch1", "discord", f"u{i}", f"User{i}",
                f"Message informatif numéro {i} avec du contenu intéressant",
                is_reply=False,
            )
        # Give async tasks a chance to run
        await asyncio.sleep(0.05)
        fe._flush_buffer.assert_called()


class TestFactExtractorAnalyzeChannel:
    @pytest.mark.asyncio
    async def test_analyze_channel_messages(self):
        fe = _make_fact_extractor()
        fe._openai.complete_secondary_structured = AsyncMock(return_value={
            "facts": [
                {"target": "Alice", "target_user_id": "discord:111", "facts": ["Dev Python"]},
            ],
            "aliases": [],
        })

        # Create mock discord messages
        msg1 = MagicMock()
        msg1.author.bot = False
        msg1.author.id = 111
        msg1.author.display_name = "Alice"
        msg1.content = "je suis dev Python"
        msg1.created_at.timestamp.return_value = time.time()

        msg2 = MagicMock()
        msg2.author.bot = False
        msg2.author.id = 222
        msg2.author.display_name = "Bob"
        msg2.content = "moi je préfère Rust"
        msg2.created_at.timestamp.return_value = time.time()

        result = await fe.analyze_channel_messages(
            [msg1, msg2], "discord", "ch1", bot_user_id=999
        )
        assert result >= 0
        fe._openai.complete_secondary_structured.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_fact_extractor.py -v -k "Buffer or AnalyzeChannel"`
Expected: FAIL — `FactExtractor` class does not exist

- [ ] **Step 3: Implement `FactExtractor` class**

Extend `bot/core/fact_extractor.py` with the full class. Add these imports at the top:

```python
import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from loguru import logger
from bot.core.prompts import load_prompt

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient
```

Add the schema constant and prompt loading:

```python
_FACT_EXTRACTION_SYSTEM = load_prompt(
    "fact_extraction_system",
    fallback=(
        "Tu es le module d'extraction de faits de Wally. "
        "Extrais les faits durables par participant. Format JSON."
    ),
)

FACT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "target_user_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "facts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["target", "target_user_id", "facts"],
                "additionalProperties": False,
            },
        },
        "aliases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nickname": {"type": "string"},
                    "resolved_to": {"type": "string"},
                    "resolved_user_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "confidence": {"type": "number"},
                },
                "required": ["nickname", "resolved_to", "resolved_user_id", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["facts", "aliases"],
    "additionalProperties": False,
}

_FLUSH_THRESHOLD = 5
_SAFETY_CAP = 15
_PARTIAL_KEEP = 5
_MAX_AGE_SECONDS = 600  # 10 minutes
_REPLY_PAUSE_SECONDS = 180  # 3 minutes
```

Add the `FactExtractor` class:

```python
class FactExtractor:
    def __init__(
        self,
        config: "Config",
        memory: "MemoryService",
        openai: "OpenAIClient",
        db=None,
    ):
        self._config = config
        self._memory = memory
        self._openai = openai
        self._db = db
        self._buffers: dict[str, dict] = {}
        self._bg_tasks: set[asyncio.Task] = set()

    def _fire(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t

    def _get_buffer(self, channel_id: str) -> dict:
        if channel_id not in self._buffers:
            self._buffers[channel_id] = {
                "messages": [],
                "reply_chain_active": False,
                "last_activity": time.time(),
                "flush_task": None,
                "flush_lock": asyncio.Lock(),
                "platform": "discord",
            }
        return self._buffers[channel_id]

    def record_message(
        self,
        channel_id: str,
        platform: str,
        user_id: str,
        display_name: str,
        content: str,
        is_reply: bool = False,
    ) -> None:
        buf = self._get_buffer(channel_id)
        buf["last_activity"] = time.time()
        buf["platform"] = platform

        if is_reply:
            buf["reply_chain_active"] = True

        if not _is_memorable(content):
            return

        buf["messages"].append({
            "author": display_name,
            "user_id": user_id,
            "content": content,
            "timestamp": time.time(),
            "is_reply": is_reply,
        })

        # Persist to DB
        if self._db is not None:
            self._fire(self._db.insert_session_message(
                channel_id, platform, user_id, display_name, content, time.time(),
            ))

        msg_count = len(buf["messages"])

        # Safety cap: flush partial
        if msg_count >= _SAFETY_CAP:
            self._fire(self._do_flush(channel_id, partial=True))
            return

        # Normal mode: flush at threshold
        if not buf["reply_chain_active"] and msg_count >= _FLUSH_THRESHOLD:
            self._fire(self._do_flush(channel_id))
            return

        # Conversation mode or below threshold: schedule timeout flush
        self._schedule_flush(channel_id)

    def _schedule_flush(self, channel_id: str) -> None:
        buf = self._get_buffer(channel_id)
        if buf["flush_task"] and not buf["flush_task"].done():
            buf["flush_task"].cancel()

        delay = _REPLY_PAUSE_SECONDS if buf["reply_chain_active"] else _MAX_AGE_SECONDS
        task = asyncio.create_task(self._delayed_flush(channel_id, delay))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        buf["flush_task"] = task

    async def _delayed_flush(self, channel_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        buf = self._buffers.get(channel_id)
        if buf and buf["messages"]:
            await self._do_flush(channel_id)

    async def _do_flush(self, channel_id: str, partial: bool = False) -> None:
        buf = self._buffers.get(channel_id)
        if not buf or not buf["messages"]:
            return

        async with buf["flush_lock"]:
            messages = buf["messages"]
            if not messages:
                return

            if partial:
                to_flush = messages[:_SAFETY_CAP - _PARTIAL_KEEP]
                buf["messages"] = messages[_SAFETY_CAP - _PARTIAL_KEEP:]
            else:
                to_flush = list(messages)
                buf["messages"] = []

            buf["reply_chain_active"] = False

            # Cancel pending flush task
            if buf["flush_task"] and not buf["flush_task"].done():
                buf["flush_task"].cancel()
                buf["flush_task"] = None

        await self._extract_facts(to_flush, buf["platform"], channel_id)

        # Cleanup persisted messages
        if self._db is not None:
            try:
                if partial:
                    # Delete only the flushed messages (by timestamp cutoff)
                    cutoff = to_flush[-1]["timestamp"]
                    await self._db.delete_session_messages_before(channel_id, cutoff)
                else:
                    await self._db.delete_session_messages(channel_id)
            except Exception as e:
                logger.warning("Failed to cleanup buffer messages: {e}", e=e)

    async def _extract_facts(
        self, messages: list[dict], platform: str, channel_id: str,
    ) -> int:
        if not messages:
            return 0
        try:
            # Build conversation text
            conversation = "\n".join(
                f"[{m['author']}]: {m['content']}" for m in messages
            )
            # Build participant list
            participants = {}
            for m in messages:
                if m["user_id"] not in participants:
                    participants[m["user_id"]] = m["author"]

            participant_lines = "\n".join(
                f"- {name} (ID: {uid})" for uid, name in participants.items()
            )

            # Get known aliases
            known_aliases = ""
            if self._db is not None:
                aliases = await self._db.list_aliases()
                if aliases:
                    known_aliases = "\nAlias connus:\n" + "\n".join(
                        f"- {a['nickname']} → {a['display_name']} ({a['canonical_uid']})"
                        for a in aliases
                    )

            user_content = (
                f"Participants du salon:\n{participant_lines}\n"
                f"{known_aliases}\n\n"
                f"Conversation:\n{conversation}"
            )

            result = await self._openai.complete_secondary_structured(
                _FACT_EXTRACTION_SYSTEM,
                [{"role": "user", "content": user_content}],
                schema=FACT_EXTRACTION_SCHEMA,
                schema_name="fact_extraction",
                purpose="fact_extraction",
            )

            stored = 0
            for entry in result.get("facts", []):
                facts_text = "\n".join(entry.get("facts", []))
                if not facts_text:
                    continue
                target_uid = entry.get("target_user_id")
                if target_uid:
                    await self._memory.add(
                        platform, target_uid.split(":")[-1] if ":" in target_uid else target_uid,
                        facts_text,
                        username=entry.get("target", ""),
                    )
                    stored += 1
                else:
                    # Store under unknown:{nickname}
                    nickname = entry.get("target", "unknown").lower()
                    await self._memory.add(
                        "unknown", nickname, facts_text,
                        username=entry.get("target", ""),
                    )

            # Process aliases
            for alias in result.get("aliases", []):
                if alias.get("confidence", 0) >= 0.8 and alias.get("resolved_user_id"):
                    nickname = alias["nickname"].lower()
                    if self._db is not None:
                        await self._db.upsert_alias(
                            nickname, alias["resolved_user_id"],
                            alias["resolved_to"], "llm", alias["confidence"],
                        )
                    self._memory.add_alias(
                        f"nickname:{nickname}", alias["resolved_user_id"]
                    )
                    # Reconcile orphans
                    self._fire(self._reconcile_orphan_facts(
                        nickname, alias["resolved_user_id"],
                    ))

            logger.info(
                "Fact extraction: {n} users stored from {m} messages in {ch}",
                n=stored, m=len(messages), ch=channel_id,
            )
            return stored

        except Exception as e:
            logger.error("Fact extraction failed: {e}", e=e)
            return 0

    async def _reconcile_orphan_facts(
        self, nickname: str, canonical_uid: str,
    ) -> None:
        """Migrate memories from unknown:{nickname} to the canonical user."""
        try:
            memories_text = await self._memory.get_all("unknown", nickname)
            if not memories_text:
                return
            # Re-add under canonical user
            platform = canonical_uid.split(":")[0] if ":" in canonical_uid else "unknown"
            raw_id = canonical_uid.split(":")[-1] if ":" in canonical_uid else canonical_uid
            await self._memory.add(platform, raw_id, memories_text)
            # Delete orphan memories via public MemoryService method
            await self._memory.delete_user_memories("unknown", nickname)
            logger.info(
                "Reconciled orphan facts: unknown:{nick} → {uid}",
                nick=nickname, uid=canonical_uid,
            )
        except Exception as e:
            logger.warning("Orphan reconciliation failed: {e}", e=e)

    async def analyze_channel_messages(
        self,
        messages: list,
        platform: str,
        channel_id: str,
        bot_user_id: int,
    ) -> int:
        """Analyze Discord messages and extract facts (replacement for SessionManager method).

        Used by /wally scan command. Returns number of participants with stored facts.
        """
        filtered = []
        for msg in messages:
            if msg.author.bot and msg.author.id != bot_user_id:
                continue
            if not msg.content.strip():
                continue
            filtered.append(msg)

        human_count = sum(1 for m in filtered if not m.author.bot)
        if human_count < 2:
            raise ValueError(
                f"Pas assez de messages humains pour analyser : {human_count} (minimum 2)"
            )

        converted = [
            {
                "author": msg.author.display_name,
                "user_id": str(msg.author.id),
                "content": msg.content,
                "timestamp": msg.created_at.timestamp(),
                "is_reply": False,
            }
            for msg in filtered
        ]

        return await self._extract_facts(converted, platform, channel_id)

    async def flush_all(self) -> None:
        """Flush all non-empty buffers. Call before shutdown."""
        for channel_id, buf in list(self._buffers.items()):
            if buf["messages"]:
                await self._do_flush(channel_id)
        logger.info("All fact extraction buffers flushed")

    async def restore_buffers(self) -> int:
        """Restore buffers from DB after restart."""
        if self._db is None:
            return 0
        since = time.time() - _MAX_AGE_SECONDS
        try:
            rows = await self._db.get_recent_session_messages(since)
        except Exception as e:
            logger.warning("Failed to restore buffers: {e}", e=e)
            return 0
        if not rows:
            return 0

        channels: dict[str, list[dict]] = {}
        for row in rows:
            channels.setdefault(row["channel_id"], []).append(row)

        restored = 0
        for channel_id, msgs in channels.items():
            buf = self._get_buffer(channel_id)
            buf["platform"] = msgs[0]["platform"]
            for msg in msgs:
                buf["messages"].append({
                    "author": msg["display_name"],
                    "user_id": msg["user_id"],
                    "content": msg["content"],
                    "timestamp": msg["timestamp"],
                    "is_reply": msg.get("is_reply", False),
                })
            buf["last_activity"] = msgs[-1]["timestamp"]
            self._schedule_flush(channel_id)
            restored += 1

        logger.info("Buffers restored: {n} channels, {m} messages", n=restored, m=len(rows))
        return restored
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_fact_extractor.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add bot/core/fact_extractor.py tests/test_fact_extractor.py bot/persona/prompts/fact_extraction_system.md
git commit -m "feat(memory): FactExtractor with buffer, flush logic, batch extraction"
```

---

### Task 6: Piggyback on emotion analysis — `_analyze_llm` structured outputs + `user_facts`

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion_user_facts.py` (new)

- [ ] **Step 1: Write the test**

```python
# tests/test_emotion_user_facts.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.emotion import EmotionEngine


@pytest.fixture
def engine():
    config = MagicMock()
    config.emotions = {}
    config.bot.emotion_inertia_factor = 0.5
    config.bot.emotion_peak_threshold = 0.7
    db = AsyncMock()
    e = EmotionEngine(config, db=db)
    openai = AsyncMock()
    e.set_openai_client(openai)
    return e


@pytest.mark.asyncio
async def test_process_message_returns_user_facts(engine):
    engine._openai.complete_secondary_structured = AsyncMock(return_value={
        "deltas": {"anger": 0.0, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": [],
        "trust_delta": 0.02,
        "love_delta": 0.01,
        "user_facts": ["Développeur Python", "Habite à Lyon"],
    })

    result = await engine.process_message(
        "je suis dev Python, j'habite à Lyon",
        trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "salut"}],
    )

    assert result is not None
    assert result["user_facts"] == ["Développeur Python", "Habite à Lyon"]
    assert result["trust_delta"] == 0.02


@pytest.mark.asyncio
async def test_process_message_empty_facts(engine):
    engine._openai.complete_secondary_structured = AsyncMock(return_value={
        "deltas": {"anger": 0.0, "joy": 0.05, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": [],
        "trust_delta": 0.01,
        "love_delta": 0.0,
        "user_facts": [],
    })

    result = await engine.process_message(
        "lol c'est marrant",
        trust_score=0.5,
        context_messages=[{"author": "Bob", "content": "hey"}],
    )

    assert result is not None
    assert result["user_facts"] == []


@pytest.mark.asyncio
async def test_fallback_no_user_facts(engine):
    """When LLM is unavailable, fallback returns no user_facts."""
    engine._openai = None
    result = await engine.process_message("test message", trust_score=0.5)
    assert result is None  # NRCLex fallback returns None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion_user_facts.py -v`
Expected: FAIL — `_analyze_llm` doesn't use structured outputs yet

- [ ] **Step 3: Modify `_analyze_llm` in `emotion.py`**

Add schema constant after imports:

```python
_EMOTION_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "deltas": {
            "type": "object",
            "properties": {
                "anger": {"type": "number"},
                "joy": {"type": "number"},
                "sadness": {"type": "number"},
                "curiosity": {"type": "number"},
                "boredom": {"type": "number"},
            },
            "required": ["anger", "joy", "sadness", "curiosity", "boredom"],
            "additionalProperties": False,
        },
        "new_words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "emotion": {"type": "string"},
                    "delta": {"type": "number"},
                },
                "required": ["word", "emotion", "delta"],
                "additionalProperties": False,
            },
        },
        "trust_delta": {"type": "number"},
        "love_delta": {"type": "number"},
        "user_facts": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["deltas", "new_words", "trust_delta", "love_delta", "user_facts"],
    "additionalProperties": False,
}
```

Replace `_analyze_llm` method — key changes:
1. Add `user_facts` paragraph to system prompt
2. Replace `complete_secondary()` → `complete_secondary_structured()`
3. Remove `json.loads()`, use direct dict access
4. Return `user_facts` in output

```python
async def _analyze_llm(
    self, text: str, trust_score: float, context_messages: list[dict],
    image_urls: list[str] | None = None,
) -> tuple[dict[str, float], list[dict], float, float, list[str]]:
    """Analyse émotionnelle via LLM — retourne (deltas, new_words, trust_delta, love_delta, user_facts)."""
    system_prompt = (
        # ... (keep existing prompt text) ...
        "\n\n## Extraction de faits\n"
        "Retourne aussi \"user_facts\" : une liste de faits durables sur l'utilisateur "
        "qui envoie le message déclencheur (centres d'intérêt, préférences, faits "
        "biographiques, opinions). Liste vide si rien de durable."
        # ... (rest of existing prompt) ...
    )
    # ... (keep existing context_lines / user_msg construction) ...

    # Branching: structured outputs when no images, fallback when images present
    # (complete_secondary_structured does not support image_urls)
    if image_urls:
        # Fallback: complete_secondary + json.loads (images need multimodal content blocks)
        raw = await self._openai.complete_secondary(
            system_prompt,
            [{"role": "user", "content": user_msg}],
            purpose="emotion_analysis",
            image_urls=image_urls,
        )
        parsed = json.loads(raw)
    else:
        parsed = await self._openai.complete_secondary_structured(
            system_prompt,
            [{"role": "user", "content": user_msg}],
            schema=_EMOTION_ANALYSIS_SCHEMA,
            schema_name="emotion_analysis",
            purpose="emotion_analysis",
        )
    raw_deltas = parsed["deltas"]
    deltas = {
        e: min(max(float(raw_deltas.get(e, 0.0)), 0.0), MAX_DELTA_PER_MESSAGE)
        for e in EMOTIONS
    }
    new_words = parsed.get("new_words", [])
    trust_delta = max(-0.1, min(0.1, float(parsed.get("trust_delta", 0.0))))
    love_delta = max(0.0, min(0.1, float(parsed.get("love_delta", 0.0))))
    user_facts = parsed.get("user_facts", [])
    return deltas, new_words, trust_delta, love_delta, user_facts
```

**Image branching:** When `image_urls` is present, we fall back to `complete_secondary()` + `json.loads()` because structured outputs don't support multimodal content blocks. The `.get()` with defaults handles the case where the non-structured response omits a field.

Update `process_message` to pass `user_facts` through in its return value:

```python
# In process_message, after _analyze_llm call:
deltas, new_words, trust_delta, love_delta, user_facts = await self._analyze_llm(...)
# ...
return {"trust_delta": trust_delta, "love_delta": love_delta, "user_facts": user_facts}
```

**Exact insertion point for the user_facts paragraph in the system prompt:**
Insert BEFORE the `## Format de sortie` section (before line 366 of current emotion.py), add:

```python
"\n\n## Extraction de faits\n"
"Retourne aussi \"user_facts\" : une liste de faits durables sur l'utilisateur "
"qui envoie le message déclencheur (centres d'intérêt, préférences, faits "
"biographiques, opinions exprimées). Liste vide si rien de durable.\n"
```

And update the `## Format de sortie` example to include `"user_facts": []`:

```python
'"new_words": [{"word": "...", "emotion": "...", "delta": 0.0}], '
'"trust_delta": 0.0, "love_delta": 0.0, "user_facts": []}'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion_user_facts.py -v`
Expected: all PASS

- [ ] **Step 5: Run existing emotion tests to check for regressions**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v -k "emotion" --tb=short`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add bot/core/emotion.py tests/test_emotion_user_facts.py
git commit -m "feat(emotion): structured outputs + user_facts extraction in _analyze_llm"
```

---

### Task 7: Integration — wire `FactExtractor` into main flow

**Files:**
- Modify: `bot/main.py`
- Modify: `bot/discord/bot.py`
- Modify: `bot/discord/handlers.py`
- Modify: `bot/discord/commands/scan_cmd.py`
- Modify: `bot/discord/commands/ask.py`
- Modify: `bot/twitch/handlers.py`
- Modify: `bot/core/memory.py`
- Modify: `bot/dashboard/state.py`

- [ ] **Step 1: Update `bot/discord/bot.py` and `bot/twitch/bot.py`**

In `bot/discord/bot.py`, replace `self.session_manager = None` with:

```python
self.fact_extractor = None  # set by main.py after construction
```

In `bot/twitch/bot.py`, add after `self.dashboard_state = None`:

```python
self.fact_extractor = None  # set by main.py after construction
```

- [ ] **Step 2: Update `bot/main.py`**

Replace SessionManager import and initialization with FactExtractor:

```python
# Replace:
from bot.core.sessions import SessionManager
session_manager = SessionManager(memory, openai_client, db=db)
await session_manager.restore_sessions()
logger.info("SessionManager initialized")

# With:
from bot.core.fact_extractor import FactExtractor
fact_extractor = FactExtractor(config, memory, openai_client, db=db)
await fact_extractor.restore_buffers()
logger.info("FactExtractor initialized")
```

Replace all `session_manager` references:
```python
# Replace:
discord_bot.session_manager = session_manager
# With:
discord_bot.fact_extractor = fact_extractor

# Replace:
twitch_bot.session_manager = session_manager
# With:
twitch_bot.fact_extractor = fact_extractor
```

- [ ] **Step 3: Update `bot/discord/handlers.py`**

In `handle_message()`, replace:
```python
if getattr(bot, "session_manager", None) is not None:
    bot.session_manager.record_message(
        str(message.channel.id),
        "discord",
        user_id,
        message.author.display_name,
        message.content,
    )
```
With:
```python
if getattr(bot, "fact_extractor", None) is not None:
    bot.fact_extractor.record_message(
        str(message.channel.id),
        "discord",
        user_id,
        message.author.display_name,
        message.content,
        is_reply=message.reference is not None,
    )
```

Add `display_name` parameter to `_post_process()` signature (line 473):
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
    display_name: str = "",  # NEW
) -> None:
```

Update the call site in `_respond()` (around line 459) to pass `display_name=message.author.display_name`.

In `_post_process()`, add after the trust/love updates:
```python
if llm_deltas and llm_deltas.get("user_facts"):
    await bot.memory.add(
        platform, user_id,
        "\n".join(llm_deltas["user_facts"]),
        username=display_name,
    )
```

- [ ] **Step 4: Update `bot/twitch/handlers.py`**

Replace:
```python
if getattr(bot, "session_manager", None) is not None:
    bot.session_manager.record_message(channel_id, "twitch", user_id, author, content)
```
With:
```python
if getattr(bot, "fact_extractor", None) is not None:
    bot.fact_extractor.record_message(channel_id, "twitch", user_id, author, content, is_reply=False)
```

In `_post_process()`, add after the trust/love updates:
```python
if llm_deltas and llm_deltas.get("user_facts"):
    await bot.memory.add(platform, user_id, "\n".join(llm_deltas["user_facts"]))
```

- [ ] **Step 5: Update `bot/discord/commands/scan_cmd.py`**

Replace:
```python
if getattr(self.bot, "session_manager", None) is None:
```
With:
```python
if getattr(self.bot, "fact_extractor", None) is None:
```

Replace:
```python
stored = await self.bot.session_manager.analyze_channel_messages(
```
With:
```python
stored = await self.bot.fact_extractor.analyze_channel_messages(
```

- [ ] **Step 6: Update `bot/discord/commands/ask.py`**

Replace:
```python
if getattr(self.bot, "session_manager", None) is not None:
    self.bot.session_manager.record_message(
        channel_id_str, "discord", user_id,
        interaction.user.display_name, question,
    )
```
With:
```python
if getattr(self.bot, "fact_extractor", None) is not None:
    self.bot.fact_extractor.record_message(
        channel_id_str, "discord", user_id,
        interaction.user.display_name, question,
        is_reply=False,
    )
```

- [ ] **Step 7: Update `bot/core/memory.py` — load nickname aliases + add `delete_user_memories()`**

In `load_aliases()`, add after the existing alias loading:

```python
# Also load nickname aliases from user_aliases table
try:
    nickname_map = await db.get_nickname_alias_map()
    for nickname, canonical_uid in nickname_map.items():
        self._alias_cache[f"nickname:{nickname}"] = canonical_uid
    logger.info("Nickname aliases loaded: {n}", n=len(nickname_map))
except Exception as e:
    logger.warning("Failed to load nickname aliases: {e}", e=e)
```

Add `delete_user_memories()` method (public API for deleting all memories of a user):

```python
async def delete_user_memories(self, platform: str, user_id: str) -> None:
    """Delete all mem0 memories for a user. Used by orphan reconciliation."""
    self._init_mem0()
    if self._mem0 is None:
        return
    try:
        uid = self._user_id(platform, user_id)
        results = await asyncio.to_thread(self._mem0.get_all, user_id=uid)
        if isinstance(results, dict):
            results = results.get("results", [])
        for r in results:
            if r.get("id"):
                try:
                    await asyncio.to_thread(self._mem0.delete, r["id"])
                except Exception:
                    pass
        logger.info("Deleted memories for {uid}", uid=uid)
    except Exception as exc:
        logger.warning("Failed to delete memories for {p}:{u}: {e}", p=platform, u=user_id, e=exc)
```

- [ ] **Step 8: Update `bot/dashboard/state.py`**

Add optional `fact_extractor` field:

```python
# Add to TYPE_CHECKING imports:
from bot.core.fact_extractor import FactExtractor

# Add to AppState dataclass:
fact_extractor: Optional["FactExtractor"] = None
```

Update `main.py` to pass it:
```python
dashboard_state = AppState(
    ...,
    fact_extractor=fact_extractor,
)
```

- [ ] **Step 9: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short`
Expected: all PASS (some session tests may fail — handled in Task 8)

- [ ] **Step 10: Commit**

```bash
git add bot/main.py bot/discord/bot.py bot/discord/handlers.py bot/discord/commands/scan_cmd.py bot/discord/commands/ask.py bot/twitch/handlers.py bot/core/memory.py bot/dashboard/state.py
git commit -m "feat(memory): wire FactExtractor into main flow, replace SessionManager"
```

---

### Task 8: Migrate session tests + cleanup

**Files:**
- Delete: `bot/core/sessions.py`
- Modify: `tests/test_sessions.py` → adapt or delete
- Modify: `tests/test_sessions_username.py` → adapt or delete
- Modify: `tests/test_session_persistence.py` → adapt or delete

- [ ] **Step 1: Check which session tests are still relevant**

Read each test file. Tests that test `analyze_channel_messages` logic should be adapted to use `FactExtractor.analyze_channel_messages()`. Tests purely about SessionManager internals can be deleted.

- [ ] **Step 2: Adapt or delete session tests**

For each test file:
- If it tests `record_message` + session analysis → adapt to use `FactExtractor`
- If it tests `analyze_channel_messages` → adapt to use `FactExtractor.analyze_channel_messages()`
- If it tests session timeout/restore → adapt to test buffer flush/restore
- Delete any tests that are purely SessionManager-specific with no equivalent

- [ ] **Step 3: Delete `bot/core/sessions.py`**

```bash
rm bot/core/sessions.py
```

- [ ] **Step 4: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove SessionManager, migrate tests to FactExtractor"
```

---

### Task 9: Dashboard — alias API routes

**Files:**
- Modify: `bot/dashboard/routes/memory.py`
- Test: `tests/test_dashboard_memory_routes.py` (extend)

- [ ] **Step 1: Add alias routes to `bot/dashboard/routes/memory.py`**

```python
# ── GET /memory/aliases ──────────────────────────────────────────────────────

@router.get("/memory/aliases")
async def list_aliases(request: Request):
    state = request.app.state.wally
    aliases = await state.db.list_aliases()
    unresolved = await state.db.list_unresolved_aliases()

    # Count facts for unresolved aliases
    mem0 = None
    try:
        mem0 = _get_mem0(request)
    except Exception:
        pass

    unresolved_with_facts = []
    for u in unresolved:
        fact_count = 0
        if mem0:
            try:
                results = await asyncio.to_thread(mem0.get_all, user_id=u["user_id"])
                results = _unwrap(results)
                fact_count = len([r for r in results if r.get("memory")])
            except Exception:
                pass
        unresolved_with_facts.append({**u, "fact_count": fact_count})

    return {"aliases": aliases, "unresolved": unresolved_with_facts}


# ── POST /memory/aliases ─────────────────────────────────────────────────────

class AddAliasRequest(BaseModel):
    nickname: str
    canonical_uid: str
    display_name: str = ""


@router.post("/memory/aliases")
async def add_alias(body: AddAliasRequest, request: Request):
    state = request.app.state.wally
    nickname = body.nickname.strip().lower()
    if not nickname or not body.canonical_uid.strip():
        raise HTTPException(400, detail="nickname et canonical_uid requis")

    await state.db.upsert_alias(
        nickname, body.canonical_uid.strip(),
        body.display_name.strip(), "manual", 1.0,
    )
    state.memory.add_alias(f"nickname:{nickname}", body.canonical_uid.strip())

    # Reconcile orphan facts if applicable
    fe = getattr(state, "fact_extractor", None)
    if fe:
        asyncio.create_task(fe._reconcile_orphan_facts(nickname, body.canonical_uid.strip()))

    return {"status": "ok"}


# ── DELETE /memory/aliases/{nickname} ────────────────────────────────────────

@router.delete("/memory/aliases/{nickname}")
async def delete_alias(nickname: str, request: Request):
    state = request.app.state.wally
    await state.db.delete_alias(nickname)
    state.memory.remove_alias(f"nickname:{nickname}")
    return {"deleted": True}


# ── POST /memory/aliases/{nickname}/resolve ──────────────────────────────────

class ResolveAliasRequest(BaseModel):
    canonical_uid: str
    display_name: str = ""


@router.post("/memory/aliases/{nickname}/resolve")
async def resolve_alias(nickname: str, body: ResolveAliasRequest, request: Request):
    state = request.app.state.wally
    nickname = nickname.strip().lower()
    canonical_uid = body.canonical_uid.strip()

    if not canonical_uid:
        raise HTTPException(400, detail="canonical_uid requis")

    await state.db.upsert_alias(
        nickname, canonical_uid, body.display_name.strip(), "manual", 1.0,
    )
    state.memory.add_alias(f"nickname:{nickname}", canonical_uid)

    fe = getattr(state, "fact_extractor", None)
    if fe:
        asyncio.create_task(fe._reconcile_orphan_facts(nickname, canonical_uid))

    return {"status": "ok", "resolved": f"{nickname} → {canonical_uid}"}
```

- [ ] **Step 2: Write tests for alias routes**

Add to `tests/test_dashboard_memory_routes.py` or create new test file with FastAPI TestClient mocks following existing patterns.

- [ ] **Step 3: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_memory_routes.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/routes/memory.py tests/test_dashboard_memory_routes.py
git commit -m "feat(dashboard): add alias management API routes"
```

---

### Task 10: Final integration test + cleanup

- [ ] **Step 1: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short`
Expected: all PASS

- [ ] **Step 2: Check for any remaining `session_manager` references**

Run: `grep -r "session_manager" bot/ --include="*.py"`
Expected: No results (all replaced with `fact_extractor`)

- [ ] **Step 3: Check for any remaining `sessions` imports**

Run: `grep -r "from bot.core.sessions" bot/ tests/ --include="*.py"`
Expected: No results

- [ ] **Step 4: Verify `sessions.py` is deleted**

Run: `ls bot/core/sessions.py 2>/dev/null && echo "EXISTS" || echo "DELETED"`
Expected: DELETED

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "chore: final cleanup after memory improvement migration"
```
