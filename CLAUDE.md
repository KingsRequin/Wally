# Wally Bot — CLAUDE.md

## Project Overview

Wally is an AI-powered Discord and Twitch bot with persistent emotional state, long-term memory,
and a coherent personality. It runs as a single Python asyncio process (modular monolith) with
two adapter services (Discord, Twitch) sharing injected core services.

Full design doc: `docs/plans/2026-03-05-wally-bot-design.md`

---

## Architecture Decisions

### Modular Monolith
Single asyncio process, clean module boundaries via dependency injection. Discord and Twitch
adapters receive core services (emotion, memory, LLM clients, config) at construction time.
Simple to deploy (one Docker container), no inter-process overhead. At this scale this is the
right tradeoff — distributed complexity is unnecessary.

### discord.py 2.x
Most widely used Python Discord library. Native slash commands, modals, select menus, buttons.
Full asyncio integration. Well-maintained with extensive documentation.

### twitchio 2.x
Only mature async Python Twitch library. Built-in OAuth token refresh. EventSub support for
follow/sub/bits/raid events.

### Direct Qdrant (QdrantMemoryStore)
Long-term memory with vector similarity search. Fully self-hosted (data privacy, no external
dependency). Direct `qdrant-client` access via `QdrantMemoryStore` in `bot/core/memory_store.py`.
Structured payloads (text, category, date, source, platform). Embeddings via OpenAI
`text-embedding-3-small` with LRU cache (2048 entries, SHA-256 keyed) and 30s timeout.
Batch operations for consolidation deletes (`delete_batch()`). Scroll batch size 500.
Qdrant runs as a separate Docker service with a healthcheck; wally waits for `service_healthy`.

### nrclex for emotion detection
Pure Python, no API call, <20ms per message. NRC Lexicon covers anger/joy/sadness etc.
Runs via `asyncio.to_thread()` to avoid blocking the event loop.

### loguru
Structured logging with zero configuration, file rotation built-in, better ergonomics than
stdlib logging. Use exclusively — never use `print()` or `import logging`.

### apscheduler
AsyncIO-native scheduler shared between DailyJournal and ActionScheduler. Single
`AsyncIOScheduler` instance created in `main.py`, passed to both services. No separate
process or queue required.

---

## Directory Structure

```
bot/
├── main.py              # Entry point, DI wiring, asyncio.gather()
├── config.py            # Config singleton, hot-reload, config.save()
├── core/
│   ├── emotion.py       # Global emotion state, decay, NRCLex analysis
│   ├── memory.py        # MemoryService: sliding context window, search, consolidation
│   ├── memory_store.py  # QdrantMemoryStore: direct Qdrant access, embeddings, CRUD
│   ├── openai_client.py # Backward-compat shim → redirects to core/llm/openai_client.py
│   ├── prompts.py       # PromptBuilder, load_prompt(), emotion directives
│   ├── language.py      # langdetect wrapper with fallback
│   ├── journal.py       # Daily journal scheduler (apscheduler)
│   ├── sessions.py      # SessionManager: suivi sessions, analyse LLM → mémoire
│   ├── persona.py       # PersonaService: chargement SOUL/IDENTITY/VOICE/EMOTIONS
│   ├── llm/             # Multi-provider LLM abstraction layer
│   │   ├── __init__.py   # Exports: BaseLLMClient, OpenAILLMClient, ClaudeLLMClient, create_llm_client
│   │   ├── base.py       # ABC BaseLLMClient: complete(), complete_with_tools(), complete_structured()
│   │   ├── openai_client.py # OpenAILLMClient: Chat Completions + Responses API + generate_image()
│   │   ├── claude_client.py # ClaudeLLMClient: Anthropic SDK, prompt caching, tool conversion
│   │   └── factory.py    # create_llm_client(LLMRoleConfig, db) factory
│   └── actions/         # ActionService: tâches planifiées via tool calling
│       ├── __init__.py   # Exports publics
│       ├── registry.py   # ActionRegistry: catalogue + ACL par rôle
│       ├── scheduler.py  # ActionScheduler: persistence SQLite + apscheduler
│       ├── executor.py   # ActionExecutor: routing + livraison messages
│       └── service.py    # ActionService: facade LLM, tool definitions
├── discord/
│   ├── bot.py           # discord.py Bot subclass
│   ├── handlers.py      # on_message, welcome logic, timeout reactions
│   └── commands/
│       ├── ask.py       # /wally ask
│       ├── memory_cmd.py # /wally memory show (admin)
│       ├── status.py    # /wally status
│       ├── mood.py      # /wally mood
│       ├── journal_cmd.py # /wally journal [YYYY-MM-DD] (admin, déclenche journal à la demande, date optionnelle pour backfill)
│       ├── persona_cmd.py # /wally reload-persona (admin, recharge fichiers persona)
│       ├── imagine.py   # /wally imagine (image generation + gallery)
│       └── setup.py     # /wally setup (4-tab interactive UI)
├── persona/
│   ├── SOUL.md / IDENTITY.md / VOICE.md / EXEMPLES.md  # blocs persona (ordre canonique)
│   ├── EMOTIONS.md      # directives comportementales par émotion (sections ## emotion_name)
│   ├── WEEKDAYS.md      # directives par jour de la semaine (sections ## monday … sunday)
│   ├── SECONDARIES.md   # directives émotions secondaires (contempt, pride, shame…)
│   ├── COMPOSITES.md    # directives pour combinaisons de 2 émotions dominantes ≥ 0.4
│   └── prompts/         # templates système chargés via load_prompt("name")
├── twitch/
│   ├── bot.py           # twitchio Bot, OAuth refresh, cooldowns
│   ├── events.py        # follow/sub/resub/bits/raid handlers
│   └── handlers.py      # Message routing, per-user cooldown
└── db/
    └── database.py      # aiosqlite: schema init + query helpers
```

---

## Key Conventions

### Async First
- All I/O is async: Discord API, Twitch API, OpenAI API, SQLite (aiosqlite), Qdrant
- CPU-bound work (NRCLex, langdetect) runs in `asyncio.to_thread()`
- Never call blocking code directly in the event loop

### Dependency Injection
Services are created once in `main.py` and passed to adapters at construction:

```python
config = Config.load()
db = await Database.create(config)
emotion = EmotionEngine(config)
memory = MemoryService(config)

# LLM clients — separate primary/secondary/image
primary_llm = create_llm_client(config.llm.primary, db)    # user-facing responses
secondary_llm = create_llm_client(config.llm.secondary, db) # background tasks
image_client = OpenAILLMClient(model=..., db=db)             # always OpenAI for images

discord_bot = WallyDiscord(config, db, emotion, memory, primary_llm, secondary_llm, image_client, ...)
twitch_bot = WallyTwitch(config, db, emotion, memory, primary_llm, secondary_llm, ...)

await asyncio.gather(discord_bot.start(), twitch_bot.start())
```

Bot attributes: `bot.llm` (primary), `bot.llm_secondary` (secondary), `bot.image_client` (OpenAI for images+costs).

### Config Hot-Reload
`config.save()` writes the full in-memory config back to `config.yaml` synchronously.
Any change made via `/wally setup` must call `config.save()` immediately. No restart needed.

### Error Handling
- All top-level event handlers: try/except, log error, continue — never crash
- OpenAI: exponential backoff (1s, 2s, 4s), max 3 retries, then graceful fallback in user's language
- Qdrant unavailable: log WARNING, continue without memory context
- NRCLex/langdetect failure: emotion delta = 0, language = config default

### Logging
Use `loguru` exclusively:

```python
from loguru import logger
logger.info("Response sent to {user}", user=username)
logger.error("OpenAI call failed: {e}", e=str(e))
```

Never use `print()` or `import logging`.

### Author Labels (Discord)
`_author_label(member)` in `handlers.py` formats user identity for LLM context:
`display_name (@username)` when `member.name` differs from `member.display_name`, otherwise
just `display_name`. Used in prelude, context window, fact_extractor, user_content, cold-start
history, and spam warnings. Ensures the LLM sees the unique Discord username alongside nicknames.

### Environment Variables
All secrets in `.env`. Never hardcode tokens or API keys. Never commit `.env`.

---

## Emotion System

### State
5 emotions, each float 0.0–1.0: `anger`, `joy`, `sadness`, `curiosity`, `boredom`

### Decay
Background task every 60s: `E(t) = E₀ × e^(−λ × Δt)` where Δt is in **hours**.
Each emotion has its own configurable λ in `config.yaml`.
Boredom rises linearly during inactivity: `boredom_rise_per_hour` (default 1.2, configurable per emotion).

### Analysis
NRCLex maps message text to emotion scores. Weighted deltas applied per emotion.
`trust_score` (0.0–1.0, per user per platform) amplifies anger delta for low-trust users.
LLM emotion analysis output parsed via `_extract_json()` — handles raw JSON, markdown code
blocks (` ```json ``` `), and embedded `{...}` in free text.

### Suppression Rules
When an emotion delta is applied, incompatible emotions are partially eroded (`_apply_suppression()`).
Rules in `SUPPRESSION_RULES` (src, tgt, coeff): joy→anger 0.8×, joy→sadness 0.8×, anger→joy 0.4×.
Bidirectional: applying the target emotion also erodes the source.

During each 60s decay tick, **continuous competition** erodes both sides when they coexist:
`extra = state[src] × state[tgt] × COMPETITION_K` (K=0.05) subtracted from each.
At anger=0.65 + joy=0.33 this yields ~0.011/tick, converging in ~1h.
`anger↔boredom` is intentionally absent (coexistence is plausible).

### Prompt Injection
Dominant emotion(s) → behavioral directive injected into system prompt via `prompts.py`.
**Never** write "tu es en colère" — write "tes réponses sont courtes et impatientes".

### Timeout
If a user triggers anger above threshold N times → mute mode for X minutes (in `timeout_log`).
During mute: react only (💩 ⛔ 😤), no text response.
Each message from a muted user increases anger by `spam_anger_delta` (configurable).

### Spam Detection (Discord only)
In-memory tracker `_spam_tracker: dict[(user_id, channel_id), deque[float]]` in `handlers.py`.
Counts message timestamps per user/channel. When `max_messages` exceeded within `window_seconds`:
1. LLM generates warning via `llm_secondary.complete()` (prompt: `spam_warning_system.md`)
2. User muted via `add_timeout()` for `mute_minutes`
3. Memory fact stored via `memory.add()` ("Wally a coupé X pour spam")
4. Tracker reset for that user/channel

Config in `discord.spam_detection`:
```yaml
discord:
  spam_detection:
    enabled: true
    max_messages: 10        # threshold
    window_seconds: 120     # time window
    mute_minutes: 5         # mute duration
    spam_anger_delta: 0.05  # anger increase per muted message
    exempt_channels:        # channels that skip spam detection
      - 1485380606224502844
```

`SpamDetectionConfig` is a nested dataclass in `DiscordConfig`. `Config.load()` pops
`spam_detection` from the discord dict and constructs it separately to handle nesting.
Exempt channels are excluded from tracking entirely. DMs are excluded.

---

## Memory System

### Sliding Context Window
Per-channel list of `{author: str, content: str, timestamp: float}` dicts.
Last N messages (N from config) included in every prompt.
When token count exceeds threshold: summarize via secondary model, replace with summary entry.

### Long-term Memory (QdrantMemoryStore)
Direct Qdrant access via `QdrantMemoryStore` in `bot/core/memory_store.py`. No mem0 middleware.
Namespace: `{platform}:{user_id}` (e.g. `discord:123456789`, `twitch:username`)
Stores: facts, preferences, recurring topics, preferred language.
Discord and Twitch memory are strictly separate per user.

Each Qdrant point has a structured payload:
```json
{"text": "...", "user_id": "discord:123", "category": "PREF", "date": "2026-03-25",
 "source": "fact_extractor", "platform": "discord", "created_at": "..."}
```
Categories: `FAIT` (biographical), `PREF` (preference), `LANG` (language), `REL` (relationship).
`search_relationships()` uses native Qdrant filtering on `category=REL`.

Embeddings via `text-embedding-3-small`, cost tracked via `db.log_cost()`.
Collection auto-created on first connect if missing.

### Memory API Convention
`memory.add(platform, user_id, ...)` — `user_id` must be the RAW id (e.g. `"610550333042589752"`),
never the prefixed form (`"discord:610550333042589752"`). The method builds `platform:user_id`
internally via `_user_id()`. A guard logs warnings on double-prefix but callers must pass raw ids.
Same rule applies to `memory.search()`, `memory.get_all()`, `memory.delete_user_memories()`.

Dashboard routes access the store directly via `memory.store` property (returns `QdrantMemoryStore`).
This bypasses `_user_id()` resolution — callers must pass the full `platform:user_id` namespace.

### Platform Auto-Fix
`Database._fix_platform(user_id, platform)` detects cross-platform ID mismatches by ID length:
Discord snowflakes are ≥13 digits, Twitch numeric IDs are ≤12 digits. If the prefix doesn't
match the ID format (e.g. `twitch:610550333042589752`), it swaps to the correct platform and
logs a warning. Applied in `upsert_memory_user()` and Qdrant sync.

### FactExtractor — Third-party Resolution
`_extract_facts()` injects both `list_aliases()` and `list_memory_users()` into the LLM prompt
so it can resolve mentions of users not present in the conversation (e.g. "Azrael" → "Azraël").
Without this, facts about absent users end up under `unknown:<nickname>`.

### FactExtractor — Media/URL Pre-filter
`_is_memorable()` in `fact_extractor.py` gates every message before it enters the extraction
buffer. It rejects: short messages (<15 chars), emoji-only, interjections, and **media/GIF URLs**.
`_is_media_url_only()` detects messages that are just URLs from known media hosts (Tenor, Giphy,
Imgur, Discord CDN, TikTok, Twitch clips, YouTube Shorts) with no meaningful surrounding text.
The LLM prompts (`fact_extraction_system.md`, `emotion.py`) also explicitly instruct the model
to ignore GIF/media links — defense in depth against junk memory entries.

### Legacy Payload Compatibility
`_point_to_record()` reads text with fallback chain: `text` → `data` → `memory`.
Old mem0 payloads stored text in `data`; the migration script (`scripts/migrate_mem0_to_qdrant.py`)
rewrites them to the structured format. Run it if old memories don't appear in the dashboard.

### Qdrant Manual Cleanup
When fixing Qdrant entries (double-prefix, orphans), use `memory.store.update_payload()` to update
`user_id` in place. Do NOT go through `MemoryService` methods — the `_user_id()` guard will
strip prefixes and cause unintended deletions. Direct store access is the safe path for data fixes.

### Spontaneous Memory Recall
Two mechanisms allow Wally to reference old memories naturally:

**1. Spontaneous trigger (Discord + Twitch):**
In the spontaneous intervention block of each handler, after `_check_spontaneous_trigger()`
returns `None` and cooldown is elapsed, `memory.search_top_match()` does a single Qdrant
query on the message author. If the best match scores >= `memory_recall_min_score` (0.75)
and `random.random() < spontaneous_memory_probability` (0.2), Wally fires a spontaneous
response with the recalled memory injected as context.
- Rate-limited via `_memory_check_cooldowns` (1 Qdrant query per 60s per channel)
- Uses the main `_spontaneous_cooldowns` to avoid overlap with passion/emotion triggers
- `prelude_snapshot` passed from caller (captured before `append_prelude`) to avoid duplication
  of the triggering message in the LLM prompt

**2. Normal response directive:**
`memory_recall_directive.md` is injected in `build_system_prompt()` after the memory block
when `memory_context` is non-empty. Encourages the LLM to reference memories naturally
("ça me rappelle quand tu parlais de...") without reciting them verbatim.

Config:
```yaml
bot:
  spontaneous_memory_probability: 0.2  # chance de trigger sur souvenir pertinent
  memory_recall_min_score: 0.75        # score Qdrant minimum (élevé car non sollicité)
```

`search_top_match(platform, user_id, query) -> tuple[str, float] | None` — single Qdrant
query (no dual-query fan-out), returns best match with raw score. Returns `None` on error.

### Memory Context Budget
`mem_context` is assembled with a token budget (`memory_context_max_tokens`, default 800).
Parts are prioritized: (1) semantic memories, (2) relationships, (3) global memories,
(4) pending questions, (5) jokes, (6) opinions. Lower-priority parts are truncated when budget
is exceeded. `assemble_memory_context()` in `prompts.py` handles this.

Trust and love scores are injected in a separate `--- Relation ---` block (outside the budget)
via the `relationship_context` parameter of `build_system_prompt()`.

Config:
```yaml
bot:
  memory_search_min_score: 0.5      # min Qdrant score for normal responses (was 0.3)
  memory_context_max_tokens: 800    # token budget for memory context block
```

### Trust Score
Stored in `trust_scores` table (aiosqlite). Range 0.0–1.0.
Positive interactions: +0.01. Repeated insults: -0.05.
Updated after every response, not in real-time during generation.

---

## Database Tables

| Table | Purpose |
|---|---|
| `cost_log` | Every LLM API call (OpenAI + Claude): model, tokens, cost_usd, purpose |
| `timeout_log` | Emotion mute per user per guild |
| `welcomed` | First-message welcome tracking per user per guild |
| `trust_scores` | Long-term trust per user per platform |
| `gallery_images` | Generated images: prompt, title, username, file_path, cost |
| `gallery_votes` | Flame votes per image per user (toggle) |
| `action_tasks` | Tâches planifiées: type, schedule, payload, status, creator, target |
| `memory_users` | User metadata: user_id, platform, username, avatar_url, last_updated |
| `action_permissions` | ACL par type d'action: rôle min Twitch, enabled (`min_role_discord` kept but ignored) |
| `action_permissions_discord` | Rôles Discord autorisés par (action_type, guild_id, role_id) — multi-select |

---

## Twitch Bits Joy Tiers

| Amount | Joy Delta |
|---|---|
| 1–99 | +0.1 |
| 100–999 | +0.3 |
| 1000+ | +0.6 (max) |

### Twitch Curiosity Triggers
- **Follow burst**: ≥5 follows in 60s → curiosity +0.2 (détecté via `_recent_follows` deque)
- **Massive raid**: ≥50 viewers → curiosity +`min(viewers/100, 0.5)`

### Stream Awareness
`WallyTwitch._poll_stream_info()` polls the home stream every 60s. Cached in `_stream_info`
dict (live, title, category, viewers, started_at). Injected into the system prompt situation
block via `PromptBuilder` when `stream_live` is True.

### !mood Command (Twitch)
`!mood` in any channel → Wally replies with all 5 emotion values as a formatted string.
Sends via IRC (`irc_channel.send()`) for guest channels, via EventSub API for the home channel.

### Bot Filter (Twitch)
In `handle_message()`, before passive capture, Wally ignores messages from:
1. A hardcoded set of known bot usernames (`nightbot`, `streamelements`, `moobot`, etc.)
2. Any chatter whose badges include `set_id == "bot"` (official Twitch bot badge)
This filter runs after the self-message filter and before `append_prelude` / `fact_extractor`.

---

## /wally setup Model Filter

Include model IDs containing: `gpt`, `chatgpt`, `o1`, `o3`, `o4`
Exclude model IDs containing: `realtime`, `preview`, `audio`, `vision`

---

## Docker

Two services: `wally` (main bot) and `qdrant` (vector DB).
Qdrant healthcheck: `curl -f http://localhost:6333/healthz`
Wally `depends_on: qdrant: condition: service_healthy`
Config and data mounted as volumes — no rebuild needed for config changes.

Web dashboard on port 8080, FastAPI + vanilla JS SPA.
Auth: Bearer token for admin, Discord OAuth2 JWT for web chat.
GZip compression via `GZipMiddleware(minimum_size=1000)`.
Memory users endpoint paginated (limit/offset, default 50, max 200).

---

## Dashboard Design System — Glassmorphism

The dashboard uses a **glassmorphism** design. All new components must follow this style.

- **Backgrounds**: `rgba(255, 255, 255, 0.03)` to `0.05` with `backdrop-filter: blur(10px)`
- **Borders**: `1px solid rgba(255, 255, 255, 0.08)` — thin, subtle, never hard white
- **Border-radius**: `12px` to `16px` — rounded
- **Shadows**: `0 4px 6px rgba(0, 0, 0, 0.1)` — soft gaussian, never offset
- **Accent**: `#06b6d4` (cyan) for active states
- **Hover**: subtle glow/brightness, NOT offset shadow collapse
- **No neobrutalism**: no 3px solid borders, no `4px 4px 0px` offset shadows, no 0px radius

Emotion colors: anger `#ef4444`, joy `#eab308`, curiosity `#22c55e`, sadness `#3b82f6`, boredom `#a855f7`.

---

## LLM Abstraction Layer

Multi-provider LLM abstraction in `bot/core/llm/`. Supports OpenAI and Anthropic Claude
simultaneously — different providers can be used for primary (user-facing) and secondary
(background tasks) roles.

### BaseLLMClient (ABC)
Three abstract methods — all providers must implement:
- `complete(system_prompt, messages, ...) -> str`
- `complete_with_tools(system_prompt, messages, tools, tool_executor, ...) -> tuple[str, list[str]]`
- `complete_structured(system_prompt, messages, schema, ...) -> dict`

### Tool Format Convention
Tools are always passed in **OpenAI Chat Completions format** (canonical):
`{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}`
Each provider converts internally (Claude converts to `input_schema` format).

### OpenAILLMClient
Handles both Chat Completions API (gpt-4o) and Responses API (o1/o3/o4/gpt-5) via
`_uses_responses_api()` routing. Also hosts `generate_image()` (OpenAI-specific, not in ABC).

**Responses API reasoning budget**: `max_output_tokens` is shared between reasoning tokens and
visible text. When `reasoning_effort` is set, `max_output_tokens` is **omitted** from the API
call to let the model manage its own budget. Otherwise small models (e.g. gpt-5-nano) can
consume the entire budget on reasoning and return empty text.

### ClaudeLLMClient
- **Prompt caching**: system prompt wrapped with `cache_control: {"type": "ephemeral"}`
- **Extended thinking**: configurable via `thinking_type` — `disabled` (default), `adaptive` (with effort level), or `enabled` (with fixed budget_tokens). Temperature forced to 1 when thinking is active. Thinking blocks are preserved in tool use loops for reasoning continuity. Incompatible with `complete_structured()` (forced `tool_choice`), so thinking is disabled there.
- **Tool calling**: converts OpenAI tool format → Claude format, handles tool_use/tool_result flow
- **Structured output**: uses forced `tool_choice` with schema as `input_schema` (no native JSON mode)
- **Retry logic**: exponential backoff on RateLimitError and 5xx, same pattern as OpenAI

### Config
```yaml
llm:
  primary:
    provider: "claude"           # or "openai"
    model: "claude-sonnet-4-6-20260301"
    temperature: 1.0
    max_tokens: 1000
    thinking_type: "adaptive"    # Claude-specific: disabled/enabled/adaptive
    thinking_effort: "medium"    # Claude adaptive: low/medium/high
    thinking_budget_tokens: 10000 # Claude enabled: fixed token budget
  secondary:
    provider: "openai"
    model: "gpt-5.1-mini"
    temperature: 0.8
    max_tokens: 1000
    reasoning_effort: "medium"   # OpenAI-specific, ignored by Claude
    text_verbosity: "medium"     # OpenAI-specific, ignored by Claude
```

`LLMRoleConfig` dataclass in `config.py`. Factory `create_llm_client(role_config, db)` in
`bot/core/llm/factory.py`. Dashboard admin panel has provider dropdown per role — changing
provider recreates the LLM client in-place without restart.

### Backward Compatibility
- `bot/core/openai_client.py` is a shim that re-exports `OpenAILLMClient as OpenAIClient`
- Legacy `openai:` section in config.yaml still loaded, kept in sync with `llm:` section
- `config.openai.primary_model` still works for reading

### Cost Tracking
Both providers log costs via `db.log_cost()` with the same schema. Claude costs include
cache read (90% discount) and cache write (25% surcharge) token accounting.

---

## Image Generation

`OpenAILLMClient.generate_image()` calls OpenAI Images API with retry logic (3 attempts, backoff).
Images stored on disk in `data/gallery/`, metadata in `gallery_images` table.
Pricing in `IMAGE_COSTS` dict, cost logged via `log_cost(purpose="image_generation")`.

Config: `config.image_generation` — model, quality, size, background, format, daily_limit, per_user_limit.

Endpoints:
- Discord: `/wally imagine <prompt>` — loading GIF + rotating phrases during generation, then final embed with flame/edit buttons
- Web chat: `/imagine <prompt>` via WebSocket slash command
- Twitch: `!image` triggers overlay display of random gallery image
- Gallery: public browsable page with search, sort by date/votes, flame voting
- OBS overlay: `/overlay-image` page with Animate.css, SSE-driven, credit overlay showing username

Loading UX: random GIF from `data/loading_gifs/`, phrases from `data/loading_phrases.txt`,
rotated every 5s while the image generates. Final image replaces the loading embed in-place.

### Image Memory

When a user sends an image, the system ensures Wally remembers it:

**Enriched content tags** — In `handle_message()`, messages with image attachments get a
descriptive tag in the context window, prelude, and fact extractor:
- Image-only message → `[a envoyé une image]` (or `[a envoyé N images]`)
- Text + image → `texte [+ une image]`
These tags are >15 chars, so they pass `_is_memorable()` and enter fact extraction.

**LLM image description** — In `_post_process()` (background), when `image_urls` is present,
`llm_secondary.complete()` generates a 1-sentence description (prompt: `image_describe_system.md`).
Stored as a memory fact: `"{display_name} a envoyé une image : {description}"`.
This allows Wally to recall what was in the image in future conversations.

---

## PersonaService

`PersonaService` charge SOUL → IDENTITY → VOICE → EXEMPLES en un bloc unique injecté dans le prompt.
`EMOTIONS.md` est parsé en `{emotion: directive}` — sections délimitées par `## emotion_name`.
`WEEKDAYS.md` est parsé en `{day: directive}` — sections `## monday` … `## sunday`.
`SECONDARIES.md` est parsé en `{key: directive}` — émotions secondaires (contempt, pride, shame…).
`COMPOSITES.md` est parsé en `{paire: directive}` — clés triées alphabétiquement (`anger_joy`, `curiosity_sadness`…).
Déclenché quand les deux émotions dominantes sont ≥ 0.4 simultanément. Priorité sur les directives atomiques.
`/wally reload-persona` recharge tous les fichiers sans redémarrage.

### Dashboard — Gestion des prompts
Onglet **Prompts** dans le panel admin : éditeur pour les fichiers persona et les templates système.
- **Persona** : SOUL, IDENTITY, VOICE, EXEMPLES, EMOTIONS, WEEKDAYS, SECONDARIES, COMPOSITES
- **Prompts système** : templates `bot/persona/prompts/*.md` (fact_extraction, journal, spam_warning…)
- Sélecteur de bot : bot principal ou instance par slug
- Compteur de tokens live + estimation du coût par appel (primary + secondary depuis config)
- Sauvegarde recharge `PersonaService` en live (bot principal uniquement, sans redémarrage)
Routes : `GET/POST /api/admin/prompts`, `GET/POST /api/admin/prompts/persona/{filename}`, `GET/POST /api/admin/prompts/system/{filename}`

### Prompt Templates
`load_prompt("name")` charge `bot/persona/prompts/name.md` avec fallback chaîne vide.
Les templates sont chargés au niveau module (variables globales) pour éviter les I/O répétées.

---

## ActionService

Allows the LLM to create, cancel, and list scheduled tasks via tool calling.

### Architecture
4 services in `bot/core/actions/`:
- **ActionRegistry** — action catalog + role-based permissions (DB-backed, in-memory cache)
- **ActionScheduler** — SQLite persistence + apscheduler job management (shared scheduler)
- **ActionExecutor** — routes to action handlers, delivers results to Discord/Twitch channels
- **ActionService** — LLM facade, exposes 3 tools: `create_action_task`, `cancel_action_task`, `list_action_tasks`

### Action Types
- `reminder` — one-shot reminders (schedule type `once`)
- `reminder_recurring` — recurring reminders (schedule types `interval`/`cron`)
- The LLM only sees `reminder` in the tool enum. `ActionService.create()` auto-routes to
  `reminder_recurring` based on `schedule.type`. Both share the same handler.

### Reminder Handler
Reminders are **generated by the LLM** through the full response pipeline (persona, emotions,
weekday directives). The handler calls `secondary_llm.complete()` with the reminder content as
context, so Wally formulates the message in his own voice and current mood. Discord reminders
include a `<@creator_id>` mention. Falls back to raw message on LLM failure.

### Permission Model
- **Discord**: Per-guild, multi-select real Discord roles. Stored in `action_permissions_discord`
  table as `(action_type, guild_id, role_id)` tuples. Cached in-memory in `ActionRegistry._discord_perms`.
  `"everyone"` is a special role_id that grants access to all. `"admin"` always bypasses. DMs denied.
- **Twitch**: Fixed hierarchy `everyone` < `subscriber` < `vip` < `moderator` < `admin`.
  Stored as `min_role_twitch` in `action_permissions` table.

### `_resolve_discord_roles` (handlers.py)
Returns the member's **actual Discord role IDs** as strings, plus `"everyone"` and `"admin"` if
the member has administrator permission. No longer maps to abstract role names.

### Schedule Types
- `once` — single execution at a specific datetime (Europe/Paris timezone)
- `interval` — recurring every N minutes (minimum 5)
- `cron` — cron-style (hour, minute, day_of_week)

### Safety
- Rate limit: max 10 active+paused tasks per user
- Past `run_at` rejected (30s grace window)
- Once tasks that fail → marked `missed`; recurring tasks auto-pause after 3 consecutive failures
- Tasks survive restart: `reload_all()` at boot reschedules active tasks, marks missed `once` tasks

### Dashboard
Admin tab "Actions" with three sub-tabs:
- **Tâches** — active/paused tasks as card grid, pause/resume/cancel/execute actions
- **Terminées** — completed/cancelled/missed tasks (read-only)
- **Permissions** — per action type: enabled toggle, Twitch role dropdown, Discord multi-select
  role chips per guild (fetched from bot's guild cache via `/api/actions/discord-roles`)

### SSE Real-Time Updates
`/api/admin/sse/actions` broadcasts events (created, cancelled, paused, resumed, executed,
failed, completed) via fan-out queues. Dashboard auto-refreshes the active sub-tab.
`ActionScheduler` calls `broadcast_action_event()` on every state change via `on_change` callback.

### Handler Integration
Same pattern as WebSearchService: `getattr(bot, "action_service", None)` → tools added to
`complete_with_tools()`. Discord handler adds ⏱️ reaction when action tools are called.
Role resolution via `_resolve_discord_roles()` / `_resolve_twitch_roles()`.

---

## SessionManager

Suit les conversations par canal. Après 20min d'inactivité (`SESSION_TIMEOUT_SECONDS`) :
analyse LLM via `secondary_llm.complete()` → extrait les faits durables par participant → `memory.add()`.
Ne stocke que les sessions de ≥ 2 messages. Format d'analyse : `### pseudo\n- fait\n...`
