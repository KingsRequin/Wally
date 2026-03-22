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
adapters receive core services (emotion, memory, openai_client, config) at construction time.
Simple to deploy (one Docker container), no inter-process overhead. At this scale this is the
right tradeoff — distributed complexity is unnecessary.

### discord.py 2.x
Most widely used Python Discord library. Native slash commands, modals, select menus, buttons.
Full asyncio integration. Well-maintained with extensive documentation.

### twitchio 2.x
Only mature async Python Twitch library. Built-in OAuth token refresh. EventSub support for
follow/sub/bits/raid events.

### mem0 + local Qdrant
Long-term memory with vector similarity search. Fully self-hosted (data privacy, no external
dependency). Python-native API. Qdrant is mem0's recommended backend. Qdrant runs as a separate
Docker service with a healthcheck; wally waits for `service_healthy`.

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
│   ├── memory.py        # mem0 wrapper, sliding context window
│   ├── openai_client.py # Completions, image generation, cost tracking, retry logic
│   ├── prompts.py       # PromptBuilder, load_prompt(), emotion directives
│   ├── language.py      # langdetect wrapper with fallback
│   ├── journal.py       # Daily journal scheduler (apscheduler)
│   ├── sessions.py      # SessionManager: suivi sessions, analyse LLM → mem0
│   ├── persona.py       # PersonaService: chargement SOUL/IDENTITY/VOICE/EMOTIONS
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
│       ├── journal_cmd.py # /wally journal (admin, déclenche journal à la demande)
│       ├── persona_cmd.py # /wally reload-persona (admin, recharge fichiers persona)
│       ├── imagine.py   # /wally imagine (image generation + gallery)
│       └── setup.py     # /wally setup (4-tab interactive UI)
├── persona/
│   ├── SOUL.md / IDENTITY.md / VOICE.md / EXEMPLES.md  # blocs persona (ordre canonique)
│   ├── EMOTIONS.md      # directives comportementales par émotion (sections ## emotion_name)
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
- All I/O is async: Discord API, Twitch API, OpenAI API, SQLite (aiosqlite), mem0/Qdrant
- CPU-bound work (NRCLex, langdetect) runs in `asyncio.to_thread()`
- Never call blocking code directly in the event loop

### Dependency Injection
Services are created once in `main.py` and passed to adapters at construction:

```python
config = Config.load()
db = await Database.create(config)
emotion = EmotionEngine(config)
memory = MemoryService(config)
openai_client = OpenAIClient(config, db)

discord_bot = WallyDiscord(config, db, emotion, memory, openai_client)
twitch_bot = WallyTwitch(config, db, emotion, memory, openai_client)

await asyncio.gather(discord_bot.start(), twitch_bot.start())
```

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
1. LLM generates warning via `complete_secondary()` (prompt: `spam_warning_system.md`)
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

### Long-term Memory (mem0)
Namespace: `{platform}:{user_id}` (e.g. `discord:123456789`, `twitch:username`)
Stores: facts, preferences, recurring topics, preferred language.
Discord and Twitch memory are strictly separate per user.

### Memory API Convention
`memory.add(platform, user_id, ...)` — `user_id` must be the RAW id (e.g. `"610550333042589752"`),
never the prefixed form (`"discord:610550333042589752"`). The method builds `platform:user_id`
internally via `_user_id()`. A guard logs warnings on double-prefix but callers must pass raw ids.
Same rule applies to `memory.search()`, `memory.get_all()`, `memory.delete_user_memories()`.

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

### Qdrant Manual Cleanup
When fixing Qdrant entries (double-prefix, orphans), use `qdrant_client.set_payload()` to update
`user_id` in place. Do NOT go through `MemoryService` methods — the `_user_id()` guard will
strip prefixes and cause unintended deletions. Direct Qdrant client is the safe path for data fixes.

### Trust Score
Stored in `trust_scores` table (aiosqlite). Range 0.0–1.0.
Positive interactions: +0.01. Repeated insults: -0.05.
Updated after every response, not in real-time during generation.

---

## Database Tables

| Table | Purpose |
|---|---|
| `cost_log` | Every OpenAI API call: model, tokens, cost_usd, purpose |
| `timeout_log` | Emotion mute per user per guild |
| `welcomed` | First-message welcome tracking per user per guild |
| `trust_scores` | Long-term trust per user per platform |
| `gallery_images` | Generated images: prompt, title, username, file_path, cost |
| `gallery_votes` | Flame votes per image per user (toggle) |
| `action_tasks` | Tâches planifiées: type, schedule, payload, status, creator, target |
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

## Image Generation

`OpenAIClient.generate_image()` calls OpenAI Images API with retry logic (3 attempts, backoff).
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

---

## PersonaService

`PersonaService` charge SOUL → IDENTITY → VOICE → EXEMPLES en un bloc unique injecté dans le prompt.
`EMOTIONS.md` est parsé en `{emotion: directive}` — sections délimitées par `## emotion_name`.
`/wally reload-persona` recharge tous les fichiers sans redémarrage.

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
weekday directives). The handler calls `complete_secondary()` with the reminder content as
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
analyse LLM via `complete_secondary()` → extrait les faits durables par participant → `memory.add()`.
Ne stocke que les sessions de ≥ 2 messages. Format d'analyse : `### pseudo\n- fait\n...`
