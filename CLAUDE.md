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
AsyncIO-native scheduler for the daily journal cron. No separate process or queue required.

---

## Directory Structure

```
bot/
├── main.py              # Entry point, DI wiring, asyncio.gather()
├── config.py            # Config singleton, hot-reload, config.save()
├── core/
│   ├── emotion.py       # Global emotion state, decay, NRCLex analysis
│   ├── memory.py        # mem0 wrapper, sliding context window
│   ├── openai_client.py # Completions, cost tracking, retry logic
│   ├── prompts.py       # All system prompt templates, emotion directives
│   ├── language.py      # langdetect wrapper with fallback
│   └── journal.py       # Daily journal scheduler (apscheduler)
├── discord/
│   ├── bot.py           # discord.py Bot subclass
│   ├── handlers.py      # on_message, welcome logic, timeout reactions
│   └── commands/
│       ├── ask.py       # /wally ask
│       ├── memory_cmd.py # /wally memory show (admin)
│       ├── status.py    # /wally status
│       ├── mood.py      # /wally mood
│       └── setup.py     # /wally setup (4-tab interactive UI)
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
Background task every 60s: `E(t) = E₀ × e^(−λ × Δt)`
Each emotion has its own configurable λ in `config.yaml`.

### Analysis
NRCLex maps message text to emotion scores. Weighted deltas applied per emotion.
`trust_score` (0.0–1.0, per user per platform) amplifies anger delta for low-trust users.

### Prompt Injection
Dominant emotion(s) → behavioral directive injected into system prompt via `prompts.py`.
**Never** write "tu es en colère" — write "tes réponses sont courtes et impatientes".

### Timeout
If a user triggers anger above threshold N times → mute mode for X minutes (in `timeout_log`).
During mute: react only (💩 ⛔ 😤), no text response.

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

---

## Twitch Bits Joy Tiers

| Amount | Joy Delta |
|---|---|
| 1–99 | +0.1 |
| 100–999 | +0.3 |
| 1000+ | +0.6 (max) |

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

Web dashboard token field exists in `config.yaml` but dashboard is not implemented.
