# Improved Memory — Real-time Fact Extraction & Alias Resolution

**Date:** 2026-03-20
**Status:** Approved

## Problem

Wally's current memory system only extracts durable facts about users at session close
(20 min inactivity timeout via `SessionManager`). This means:

- Facts explicitly stated in conversation are only captured after a long delay
- Facts said in messages where Wally is not mentioned may be missed entirely
- Implicit behavioral patterns (recurring topics, time-of-day presence) are never captured
- Nicknames and aliases (e.g. "Rekin" for "KingsRequin") are not resolved

## Solution Overview

Replace the `SessionManager` with a two-level extraction system:

1. **Piggyback on emotion analysis** — For triggered messages, the existing LLM emotion
   analysis (`_analyze_llm`) also extracts `user_facts` about the message author. Near-zero
   additional cost.

2. **Batch intelligent extraction** — A new `FactExtractor` service accumulates all messages
   (trigger or not) in per-channel buffers. Buffers are flushed to the secondary LLM in
   smart batches that respect conversation boundaries (Discord reply chains). The LLM extracts
   facts about the author AND people mentioned/discussed, and resolves nicknames to known users.

Both levels use OpenAI structured outputs to guarantee valid JSON responses.

---

## Section 1 — Pre-filter

A lightweight Python filter that decides if a message is worth accumulating in the buffer.

**Rules:**
- Message < 15 characters -> rejected
- Message composed only of emojis -> rejected
- Message matching regex interjection patterns (full message match, after strip + lowercase):
  - `lo+l+` (lol, loool, lolll)
  - `md(r+)` (mdr, mdrrr)
  - `ptd(r+)` (ptdr, ptdrrr)
  - `x+d+` (xd, xxdd, xddd)
  - `ha(ha)+` (haha, hahaha)
  - `o+k+` (ok, ookk)
  - `gg+` (gg, ggg)
  - `wp+` (wp, wpp)
  - `a+h+`, `o+h+` (ah, aah, oooh)
  - `ri+p+` (rip, riip)
  - `ou+i+`, `no+n+` (oui, ouiii, non, nooon)
  - `\^\^+` (^^, ^^^)
  - `\+1` (+1)
- **Multi-word rule:** The message is split into words. Each word is tested against the regex
  patterns. If ALL words match interjection patterns, the message is rejected. If at least one
  word does NOT match any interjection pattern, the message passes. Examples:
  - "oui merci" -> "merci" is not an interjection -> passes
  - "non non non" -> all words match `no+n+` -> rejected
  - "mdr c'est vrai" -> "c'est" and "vrai" are not interjections -> passes

**Location:** `_is_memorable(text: str) -> bool` in `bot/core/fact_extractor.py`

---

## Section 2 — Batch Intelligent (SessionManager replacement)

**New component:** `FactExtractor` in `bot/core/fact_extractor.py`, injected via DI in `main.py`.

**Buffer per channel:**
```
channel_id -> {
    messages: list[{author, user_id, content, timestamp, is_reply}],
    reply_chain_active: bool,
    last_activity: float,
    flush_task: asyncio.Task | None,
    flush_lock: asyncio.Lock       # prevents concurrent flushes on same channel
}
```

**Accumulation logic:**
1. Every message in an allowed channel goes through `record_message()` (same signature as
   `SessionManager.record_message` + `is_reply: bool` flag for Discord replies)
2. If `_is_memorable(content)` returns False -> message not added to buffer (but `last_activity`
   is updated)
3. If message is a reply -> `reply_chain_active = True`

**Flush logic:**
- **Normal mode (no reply chain):** buffer reaches 5 memorable messages -> immediate flush
- **Conversation mode (reply chain active):** wait 3 min of channel inactivity then flush
  the entire batch. Timer resets on each new message.
- **Safety cap:** buffer reaches 15 messages without flush (very long conversation) -> partial
  flush of the first 10, keep last 5 as context for next batch
- **Max timeout:** buffer has messages older than 10 min without reaching 5 -> flush what we have
- **Concurrency:** A per-channel `asyncio.Lock` (`flush_lock`) guards all flush operations.
  When a flush is in progress, new messages accumulate but no new flush is started until the
  current one completes.

**`analyze_channel_messages()` method:**
FactExtractor must also expose an `analyze_channel_messages()` method equivalent to
`SessionManager.analyze_channel_messages()`, used by `/wally scan`. It takes a list of
Discord messages, converts them, and runs the batch fact extraction prompt directly
(bypassing the buffer/flush logic). Returns the number of participants with stored facts.

**Replaces:**
- `SessionManager` is removed
- `session_manager.record_message()` calls in `handlers.py` redirect to
  `fact_extractor.record_message()`
- `session_messages` DB table is migrated: add `is_reply INTEGER DEFAULT 0` column, clear
  stale data from the old SessionManager format on first startup
- `restore_sessions()` -> `fact_extractor.restore_buffers()`

---

## Section 3 — LLM Batch Fact Extraction

**At flush time**, the buffer is sent to the secondary model via `complete_secondary_structured()`.

**Prompt input:**
- The conversation (`[pseudo]: message` format)
- List of known channel participants with their user_id (from prelude + buffer)
- Known aliases from DB for these participants

**Prompt template:** `bot/persona/prompts/fact_extraction_system.md`

**JSON schema (structured output):**
```json
{
  "type": "object",
  "properties": {
    "facts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "target": { "type": "string" },
          "target_user_id": { "anyOf": [{"type": "string"}, {"type": "null"}] },
          "facts": {
            "type": "array",
            "items": { "type": "string" }
          }
        },
        "required": ["target", "target_user_id", "facts"],
        "additionalProperties": false
      }
    },
    "aliases": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "nickname": { "type": "string" },
          "resolved_to": { "type": "string" },
          "resolved_user_id": { "anyOf": [{"type": "string"}, {"type": "null"}] },
          "confidence": { "type": "number" }
        },
        "required": ["nickname", "resolved_to", "resolved_user_id", "confidence"],
        "additionalProperties": false
      }
    }
  },
  "required": ["facts", "aliases"],
  "additionalProperties": false
}
```

**Prompt rules:**
- Extract durable facts (interests, preferences, biographical info, opinions)
- Extract facts about the author AND people mentioned/discussed
- Resolve nicknames to known participants — only if high confidence
- Ignore transient moods, jokes without content, sensitive info
- `target_user_id` can be null if the LLM cannot resolve

**After response:**
1. For each `facts` entry with a `target_user_id` -> `memory.add(platform, user_id, facts_joined)`
2. For each `facts` entry without `target_user_id` -> stored with `unknown:{nickname}` as
   temporary key (reconcilable later when alias is known)
3. For each alias with `confidence >= 0.8` -> inserted in `user_aliases` DB table + cached
   in `MemoryService._alias_cache`

---

## Section 4 — Piggyback on Emotion Analysis

For **triggered** messages, `_post_process` already calls `emotion.process_message()` ->
`_analyze_llm()` with the secondary model.

**Modifications to `_analyze_llm` in `emotion.py`:**

- System prompt gets an additional paragraph for `user_facts` extraction
- `complete_secondary()` replaced by `complete_secondary_structured()` with full schema
- Manual `json.loads()` + defensive `.get()` replaced by direct dict access
- Value clamps on deltas remain as safety guards

**Structured output schema for emotion analysis:**
```json
{
  "type": "object",
  "properties": {
    "deltas": {
      "type": "object",
      "properties": {
        "anger":     { "type": "number" },
        "joy":       { "type": "number" },
        "sadness":   { "type": "number" },
        "curiosity": { "type": "number" },
        "boredom":   { "type": "number" }
      },
      "required": ["anger", "joy", "sadness", "curiosity", "boredom"],
      "additionalProperties": false
    },
    "new_words": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "word":    { "type": "string" },
          "emotion": { "type": "string" },
          "delta":   { "type": "number" }
        },
        "required": ["word", "emotion", "delta"],
        "additionalProperties": false
      }
    },
    "trust_delta": { "type": "number" },
    "love_delta":  { "type": "number" },
    "user_facts": {
      "type": "array",
      "items": { "type": "string" }
    }
  },
  "required": ["deltas", "new_words", "trust_delta", "love_delta", "user_facts"],
  "additionalProperties": false
}
```

**After response:**
- If `user_facts` non-empty -> `memory.add(platform, user_id, "\n".join(user_facts))`
- `process_message()` return dict changes from `{"trust_delta", "love_delta"}` to
  `{"trust_delta", "love_delta", "user_facts"}`
- Message is still sent to `FactExtractor` buffer to capture facts about OTHER people mentioned

**Fallback:** NRCLex fallback (when LLM unavailable) returns no `user_facts` -> empty list,
no storage.

---

## Section 5 — Alias Resolution & Storage

**New DB table `user_aliases`:**

| Column | Type | Description |
|---|---|---|
| `nickname` | TEXT PK | Detected nickname (lowercase) |
| `canonical_uid` | TEXT | Resolved user_id (e.g. `discord:123456`) |
| `display_name` | TEXT | Display name (e.g. `KingsRequin`) |
| `source` | TEXT | `"llm"` or `"manual"` |
| `confidence` | REAL | 0.0-1.0, only relevant for `source=llm` |
| `created_at` | REAL | timestamp |

**LLM-detected alias flow:**
1. Batch extraction returns alias with confidence
2. If `confidence >= 0.8` AND alias doesn't already exist with `source=manual` -> upsert in DB
3. Added to `MemoryService._alias_cache`
4. Facts extracted for the nickname are automatically stored under the canonical user_id

**Manual alias flow (dashboard):**
- Insert in DB with `source=manual`, `confidence=1.0`
- Added to cache
- Manual alias is never overwritten by LLM alias

**Alias deletion (dashboard):**
- Delete from DB + `MemoryService.remove_alias()`

**Unresolved facts:**
- Facts about unknown persons stored with `user_id="unknown:{nickname}"` in mem0
- When an alias `nickname -> discord:xxx` is created later, `_reconcile_orphan_facts()`
  migrates memories from `unknown:{nickname}` to the correct user_id (background task)

**`_reconcile_orphan_facts()` algorithm:**
1. Called when a new alias is created (by LLM or manually) for a nickname that has `unknown:*` data
2. `mem0.get_all(user_id="unknown:{nickname}")` -> retrieve all orphan memories
3. For each orphan memory: `mem0.add(memory_text, user_id=canonical_uid)` -> re-add under correct user
4. Delete all orphan memories: `mem0.delete(id)` for each retrieved memory
5. Idempotent: if `unknown:{nickname}` has no memories, no-op
6. Runs as a background task via `_fire()` — does not block the alias creation response
7. Logs the number of migrated memories

**Startup:**
- `memory.load_aliases(db)` loads from `user_aliases` table in addition to existing
  `account_links` table

---

## Section 6 — Dashboard (Alias Management)

**Existing page:** `/dashboard/memory`

### User alias section

In each user's memory card, an "Known aliases" block:
- List of associated nicknames with source (`llm`/`manual`) and confidence
- Button to delete an alias
- Field to add an alias manually

### Unresolved aliases section

A new block at the top of the page "Unresolved aliases":
- Lists all `unknown:*` with the number of stored facts for each
- For each unresolved alias:
  - Shows associated facts (to help admin guess who it is)
  - Dropdown with known users -> "Associate" button
  - "Delete" button (if it's noise)
- When associated -> calls `_reconcile_orphan_facts()` in backend, alias inserted in
  `user_aliases` with `source=manual`

### API routes

New routes in `bot/dashboard/routes/memory.py`:

| Method | Route | Action |
|---|---|---|
| `GET` | `/api/aliases` | List all aliases (resolved + unresolved) |
| `POST` | `/api/aliases` | Add alias manually |
| `DELETE` | `/api/aliases/{nickname}` | Delete an alias |
| `POST` | `/api/aliases/{nickname}/resolve` | Resolve an `unknown:*` alias to a user_id |

---

## Section 7 — `complete_secondary_structured()` in OpenAIClient

**New method in `bot/core/openai_client.py`:**

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
```

**Behavior by API:**
- **Responses API** (o1, o3, o4, gpt-5):
  `text={"format": {"type": "json_schema", "name": schema_name, "schema": schema}}`
- **Chat Completions API** (other models):
  `response_format={"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema}}`

**Return:** Parsed Python dict (`json.loads(response_text)`).

**Finish reason check:** Before parsing, the method must verify that the response completed
normally (`finish_reason == "stop"` for Chat Completions, `"end_turn"` for Responses API).
If the response was truncated (`finish_reason == "length"`), the JSON may be invalid despite
structured outputs — in this case, raise an exception instead of attempting to parse.

**Retry/fallback:** Same logic as `complete()` — 3 attempts with exponential backoff.
On total failure, raises an exception (no fallback string) — caller handles it.

**Cost logging:** Same pattern as `complete()`.

---

## Section 8 — Main Flow Integration

**`main.py` — DI wiring:**
```python
fact_extractor = FactExtractor(config, memory, openai_client, db)
discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, fact_extractor)
twitch_bot = WallyTwitch(config, db, emotion, memory, openai_client, fact_extractor)
```

**`handlers.py` — `handle_message()`:**

Replace `session_manager.record_message(...)` with:
```python
if getattr(bot, "fact_extractor", None) is not None:
    bot.fact_extractor.record_message(
        str(message.channel.id), "discord", user_id,
        message.author.display_name, message.content,
        is_reply=message.reference is not None,
    )
```

This block stays BEFORE the `triggered` check — all messages (trigger or not) are recorded.

**`_post_process()` — piggyback:**
```python
if llm_deltas and llm_deltas.get("user_facts"):
    await bot.memory.add(
        platform, user_id,
        "\n".join(llm_deltas["user_facts"]),
        username=message.author.display_name,
    )
```

**Twitch — `twitch/handlers.py`:**
Same pattern. `is_reply=False` always (Twitch has no reply chains).

**SessionManager removal:**
- `bot/core/sessions.py` deleted
- References in `main.py`, `handlers.py`, `bot.py` cleaned up
- `session_messages` DB table reused by `FactExtractor`
- `restore_sessions()` -> `fact_extractor.restore_buffers()`

---

## Files Impacted

| File | Action | Description |
|---|---|---|
| `bot/core/fact_extractor.py` | **New** | FactExtractor: pre-filter, buffer, batch, flush, alias resolution, orphan reconciliation |
| `bot/core/openai_client.py` | **Modified** | Add `complete_secondary_structured()` |
| `bot/core/emotion.py` | **Modified** | `_analyze_llm` -> structured outputs + `user_facts` field |
| `bot/core/sessions.py` | **Deleted** | Replaced by FactExtractor |
| `bot/core/memory.py` | **Modified** | `load_aliases()` loads from `user_aliases` too |
| `bot/main.py` | **Modified** | DI for FactExtractor, remove SessionManager |
| `bot/discord/handlers.py` | **Modified** | `record_message` -> fact_extractor, piggyback in `_post_process` |
| `bot/discord/bot.py` | **Modified** | `fact_extractor` replaces `session_manager` |
| `bot/discord/commands/scan_cmd.py` | **Modified** | Use `fact_extractor.analyze_channel_messages()` instead of `session_manager` |
| `bot/discord/commands/ask.py` | **Modified** | `record_message` -> `fact_extractor` |
| `bot/twitch/bot.py` | **Modified** | Same |
| `bot/twitch/handlers.py` | **Modified** | `record_message` -> fact_extractor |
| `bot/dashboard/state.py` | **Modified** | Add `fact_extractor` reference for alias API routes |
| `bot/db/database.py` | **Modified** | `user_aliases` table, alias CRUD queries, `_reconcile_orphan_facts` |
| `bot/dashboard/routes/memory.py` | **Modified** | Alias API routes + resolution |
| `bot/persona/prompts/fact_extraction_system.md` | **New** | Batch extraction prompt |
| `tests/` | **New + Modified** | FactExtractor tests, SessionManager test migration |
