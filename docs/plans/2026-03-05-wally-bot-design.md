# Wally Bot — Design Document
**Date:** 2026-03-05
**Status:** Approved

---

## Overview

Wally is an AI-powered bot running simultaneously on Discord and Twitch. It has a persistent emotional state, long-term per-user memory, and a coherent personality that evolves naturally over time. It is not a simple chatbot — it has emotions, memory, and a perception of relationships.

---

## Architecture: Modular Monolith

Single Python (3.12+) asyncio process. Discord and Twitch are "adapters" that share injected core services via dependency injection. No inter-process communication, no message queue. Simple to deploy (one Docker container), easy to debug.

```
main.py
  └── wires: Config, Database, EmotionEngine, MemoryService, OpenAIClient
        ├── WallyDiscord(config, db, emotion, memory, openai)
        └── WallyTwitch(config, db, emotion, memory, openai)
              asyncio.gather(discord.start(), twitch.start())
```

---

## Tech Stack

| Concern | Library |
|---|---|
| Discord | discord.py 2.x |
| Twitch | twitchio 2.x |
| AI | openai Python SDK |
| Long-term memory | mem0ai + local Qdrant |
| Emotion detection | nrclex (local, <20ms) |
| Language detection | langdetect |
| Database | aiosqlite (SQLite) |
| Config | pyyaml + python-dotenv |
| Logging | loguru |
| Scheduler | apscheduler (asyncio) |
| Infra | Docker + docker-compose |

---

## Directory Structure

```
wally-ai/
├── bot/
│   ├── main.py                  # Entry point, DI wiring, asyncio.gather
│   ├── config.py                # Config singleton, hot-reload, save()
│   ├── core/
│   │   ├── emotion.py           # Global state, decay, NRCLex analysis
│   │   ├── memory.py            # mem0 wrapper, sliding context window
│   │   ├── openai_client.py     # Completions, cost tracking, retry
│   │   ├── prompts.py           # All system prompt templates + emotion directives
│   │   ├── language.py          # langdetect with fallback
│   │   └── journal.py           # Daily journal (apscheduler)
│   ├── discord/
│   │   ├── bot.py
│   │   ├── handlers.py          # on_message, welcome, timeout reactions
│   │   └── commands/
│   │       ├── ask.py           # /wally ask
│   │       ├── memory_cmd.py    # /wally memory show (admin)
│   │       ├── status.py        # /wally status
│   │       ├── mood.py          # /wally mood
│   │       └── setup.py         # /wally setup (4-tab interactive UI)
│   ├── twitch/
│   │   ├── bot.py               # twitchio Bot, OAuth refresh, cooldowns
│   │   ├── events.py            # follow/sub/resub/bits/raid
│   │   └── handlers.py          # Message routing, per-user cooldown
│   └── db/
│       └── database.py          # aiosqlite schema + queries
├── data/
│   ├── wally.db
│   └── qdrant/                  # Qdrant storage volume
├── logs/
├── docs/plans/
├── config.yaml
├── .env
├── .env.example
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── CLAUDE.md
├── TODO.md
└── README.md
```

---

## Section 2 — Core Services

### Config (bot/config.py)
- Singleton `Config` object loaded from `config.yaml` at startup
- `config.save()` writes full config back to disk immediately (called by /wally setup)
- No restart required for any config change

### Emotion Engine (bot/core/emotion.py)
- Global state: `{anger, joy, sadness, curiosity, boredom}` each 0.0–1.0
- NRCLex analysis per incoming message (via `asyncio.to_thread`, non-blocking)
- Background decay task every 60s: `E(t) = E₀ × e^(−λ × Δt)`, per-emotion λ in config
- `trust_score` (per user, per platform, in DB) amplifies anger delta for low-trust users
- Emotion timeout: anger threshold exceeded N times → mute mode X minutes (reactions only: 💩 ⛔ 😤)
- Dominant emotion(s) injected into system prompt as behavioral directives (never "tu es en colère")

### Memory (bot/core/memory.py)
- Wraps `mem0ai` pointed at local Qdrant (`http://qdrant:6333`)
- Namespaced by `{platform}:{user_id}`
- Sliding context window: last N messages per channel as `{author, content, timestamp}` tuples
- Auto-summarization: when token count exceeds threshold → summarize via secondary model → replace

### OpenAI Client (bot/core/openai_client.py)
- Async wrapper, two models: primary (responses) and secondary (summaries, journal)
- Retry: exponential backoff on 429/5xx, max 3 retries, then graceful fallback
- Every call logged to `cost_log` table: model, input_tokens, output_tokens, cost_usd
- `get_daily_cost()` / `get_monthly_cost()` for /wally status

### Prompts (bot/core/prompts.py)
- All system prompt templates centralized
- `build_system_prompt(emotion_state, user_memory, language)` → final prompt string
- Emotion directive map: dominant emotion → behavioral instruction
- Twitch event message templates with variable support

### Language (bot/core/language.py)
- `detect(text)` → ISO language code
- Falls back to config default on failure
- Preferred language persisted to mem0 per user

### Journal (bot/core/journal.py)
- apscheduler fires daily at configured time
- Gathers day's highlights from sliding context + emotion history
- If volume exceeds secondary model context: multi-pass sliding summarization (chunks → summary of summaries → final journal)
- Posts to configured Discord channel via secondary model

---

## Section 3 — Discord Adapter

### Message Pipeline (on trigger or @mention)
1. Ignore bots
2. Check trigger names (case-insensitive) or @mention → else ignore
3. Check timeout mute → react with expressive emote, return
4. Add 🔍 reaction to source message
5. `channel.typing()` context
6. Build prompt: system (emotion + memory) + sliding window (with author names) + message
7. OpenAI call (with retry)
8. Remove 🔍 reaction, send reply
9. Append `{author, content, timestamp}` to sliding window
10. Background: emotion analysis, trust_score update

### Welcome
On each message: check `welcomed` table. If first message in guild → generate personalized welcome via OpenAI → send → mark as welcomed.

### Slash Commands
| Command | Access | Description |
|---|---|---|
| `/wally ask [question]` | Everyone | Direct question, full pipeline (no trigger check) |
| `/wally memory show [user]` | Admin | Show mem0 entries for target user |
| `/wally status` | Everyone | Uptime, model, mood summary, cost today/month |
| `/wally mood` | Everyone | 5 emotion bars as Discord embed |
| `/wally setup` | Admin | Interactive 4-tab config panel |

### /wally setup Tabs
- **Modele IA**: fetch `/v1/models`, filter `gpt|chatgpt|o1|o3|o4`, exclude `realtime|preview|audio|vision`. Two select menus (primary + secondary). Cost per 1k tokens shown.
- **Humeur**: 5 emotions with [−]/[+] buttons (step 0.1), modal edit, [Reset] button
- **Evenements Twitch**: toggle + "Modifier le message" modal per event
- **Noms declencheurs**: list with [Supprimer] (min 1), [Ajouter un nom] modal

---

## Section 4 — Twitch Adapter

### Message Pipeline
1. Ignore self
2. Check trigger names or @wally → else ignore
3. Check per-user cooldown (default 10s) → ignore silently if active
4. Full pipeline: language detect, build prompt, OpenAI call, reply
5. Append to sliding window, background emotion analysis + trust_score update

### OAuth
- Token loaded from `.env`
- twitchio built-in refresh hook handles expiry automatically

### Events (all configurable active/inactive)
| Event | Joy Delta | Behavior |
|---|---|---|
| Follow | +0.1 | OpenAI-generated welcome via template |
| Sub | +0.4 | Enthusiastic contextual message |
| Resub | +0.3 | Contextual with `{months}` |
| Bits 1-99 | +0.1 | Proportional thank-you |
| Bits 100-999 | +0.3 | Proportional thank-you |
| Bits 1000+ | +0.6 | Proportional thank-you (max +0.6) |
| Raid | min(raiders/50, 0.9) | Message with `{raiders_count}` |

---

## Section 5 — Data Layer & Infrastructure

### SQLite Schema
```sql
cost_log(id, timestamp, model, input_tokens, output_tokens, cost_usd, purpose)
timeout_log(id, user_id, guild_id, triggered_at, expires_at, anger_level)
welcomed(user_id, guild_id, welcomed_at)
trust_scores(user_id, platform, score REAL, updated_at)
```

### docker-compose.yml
```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    volumes: [./data/qdrant:/qdrant/storage]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  wally:
    build: .
    depends_on:
      qdrant:
        condition: service_healthy
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config.yaml:/app/config.yaml
    restart: unless-stopped
```

### Dockerfile
- Base: `python:3.12-slim`
- Non-root user
- requirements.txt layer before source copy (cache-friendly)
- Entrypoint: `python -m bot.main`

### .dockerignore
Excludes: `logs/`, `data/`, `.env`, `__pycache__/`, `.git/`

### Logging (loguru)
- Console: INFO+ (WARNING+ in production)
- `logs/wally.log`: daily rotation, 30-day retention
- `logs/cost.log`: JSON lines per OpenAI call

---

## Section 6 — Error Handling & Project Docs

### Resilience
- Discord: auto-reconnect via discord.py; `on_error` logs, never crashes
- Twitch: twitchio auto-reconnect; failed event handlers log and continue
- OpenAI: exponential backoff, 3 retries, graceful fallback in user's language
- Qdrant unavailable: log WARNING, continue without memory context
- NRCLex/langdetect failure: delta=0, language=default

### Project Docs
- `CLAUDE.md`: architecture decisions, conventions, patterns
- `TODO.md`: phased task list with checkboxes (stop after each task for confirmation)
- `README.md`: prerequisites, install, config reference, /wally setup guide, troubleshooting
