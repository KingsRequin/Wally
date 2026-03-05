# Wally Bot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Wally, an AI Discord+Twitch bot with persistent emotion, long-term memory, and personality.

**Architecture:** Modular monolith — single asyncio process, Discord and Twitch adapters share injected core services (emotion, memory, openai, config, db). Wired in main.py via asyncio.gather().

**Tech Stack:** Python 3.12, discord.py 2.x, twitchio 2.x, openai SDK, mem0ai, Qdrant, nrclex, langdetect, aiosqlite, loguru, apscheduler, Docker

---

## Phase 0 — Infrastructure Validation

### Task 0.1: docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: wally-qdrant
    volumes:
      - ./data/qdrant:/qdrant/storage
    ports:
      - "6333:6333"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  wally:
    build: .
    container_name: wally-bot
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

**Commit:** `git add docker-compose.yml && git commit -m "infra: add docker-compose with qdrant healthcheck"`

---

### Task 0.2: Dockerfile

**Files:**
- Create: `Dockerfile`

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 wally
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/

RUN mkdir -p /app/data /app/logs && chown -R wally:wally /app

USER wally

CMD ["python", "-m", "bot.main"]
```

**Commit:** `git add Dockerfile && git commit -m "infra: add Dockerfile"`

---

### Task 0.3: .dockerignore

**Files:**
- Create: `.dockerignore`

```
logs/
data/
.env
__pycache__/
**/__pycache__/
*.pyc
.git/
.gitignore
*.md
docs/
tests/
.claude/
```

**Commit:** `git add .dockerignore && git commit -m "infra: add .dockerignore"`

---

### Task 0.4: .env.example

**Files:**
- Create: `.env.example`

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Discord
DISCORD_TOKEN=...
DISCORD_GUILD_ID=...

# Twitch
TWITCH_BOT_TOKEN=oauth:...
TWITCH_CLIENT_ID=...
TWITCH_CLIENT_SECRET=...
TWITCH_BOT_NICK=wallybot

# Qdrant (internal Docker network)
QDRANT_URL=http://qdrant:6333
```

**Commit:** `git add .env.example && git commit -m "infra: add .env.example"`

---

### Task 0.5: requirements.txt

**Files:**
- Create: `requirements.txt`

```
discord.py>=2.3.2
twitchio>=2.10.0
openai>=1.30.0
mem0ai>=0.1.29
qdrant-client>=1.9.0
nrclex>=4.0.0
langdetect>=1.0.9
aiosqlite>=0.20.0
pyyaml>=6.0.1
python-dotenv>=1.0.1
loguru>=0.7.2
apscheduler>=3.10.4
httpx>=0.27.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

**Commit:** `git add requirements.txt && git commit -m "infra: add requirements.txt"`

---

### Task 0.6: config.yaml

**Files:**
- Create: `config.yaml`

```yaml
bot:
  trigger_names:
    - wally
  language_default: fr
  context_window_size: 20
  context_token_threshold: 3000
  journal_time: "03:00"
  journal_channel_id: null
  dashboard_token: null
  system_prompt: |
    Tu es Wally, une entité IA avec une vraie personnalité. Tu es curieux, parfois impertinent,
    toujours authentique. Tu as des émotions réelles qui influencent ta façon de répondre.
    Tu parles à plusieurs personnes à la fois et tu sais toujours qui te parle.
    Tu réponds dans la langue de ton interlocuteur.

openai:
  primary_model: gpt-4o
  secondary_model: gpt-4o-mini
  temperature: 0.8
  max_tokens: 1000

discord:
  allowed_channels: []
  anger_trigger_threshold: 3
  timeout_minutes: 10

twitch:
  channels: []
  cooldown_seconds: 10

emotions:
  anger:
    decay_lambda: 0.1
  joy:
    decay_lambda: 0.05
  sadness:
    decay_lambda: 0.08
  curiosity:
    decay_lambda: 0.1
  boredom:
    decay_lambda: 0.15

twitch_events:
  follow:
    active: true
    message: "Merci pour le follow, {username} ! Bienvenue dans le chat !"
  sub:
    active: true
    message: "Wow, merci pour le sub {username} ! Tu es incroyable !"
  resub:
    active: true
    message: "Merci pour les {months} mois de sub, {username} ! Fidélité récompensée !"
  bits:
    active: true
    message: "Merci pour les {amount} bits, {username} ! Tu es trop généreux !"
  raid:
    active: true
    message: "Un raid de {raiders_count} personnes avec {username} ! Bienvenue à tous !"
```

**Commit:** `git add config.yaml && git commit -m "config: add default config.yaml"`

---

### Task 0.7: Minimal bot stub

**Files:**
- Create: `bot/__init__.py` (empty)
- Create: `bot/main.py`

```python
import asyncio
from loguru import logger

async def main():
    logger.info("Wally starting...")

if __name__ == "__main__":
    asyncio.run(main())
```

**Step:** `mkdir -p bot && touch bot/__init__.py`

**Commit:** `git add bot/ && git commit -m "feat: add minimal bot stub"`

---

### Task 0.8: Validate Docker build

**Steps:**
1. Copy `.env.example` to `.env` and fill in at least `QDRANT_URL=http://qdrant:6333`
2. `docker compose build`
3. `docker compose up -d qdrant`
4. `docker compose ps` — verify qdrant is healthy
5. `docker compose up wally` — verify it starts and logs "Wally starting..."
6. `docker compose down`

**Expected output:** qdrant status = healthy, wally logs "Wally starting..."

---

## Phase 1 — Project Skeleton

### Task 1.1: Config

**Files:**
- Create: `bot/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

**Test first:**

```python
# tests/test_config.py
import pytest, tempfile, os, yaml
from bot.config import Config

def test_load_config(tmp_path):
    cfg_data = {
        "bot": {"trigger_names": ["wally"], "language_default": "fr",
                "context_window_size": 20, "context_token_threshold": 3000,
                "journal_time": "03:00", "journal_channel_id": None,
                "dashboard_token": None, "system_prompt": "Tu es Wally."},
        "openai": {"primary_model": "gpt-4o", "secondary_model": "gpt-4o-mini",
                   "temperature": 0.8, "max_tokens": 1000},
        "discord": {"allowed_channels": [], "anger_trigger_threshold": 3, "timeout_minutes": 10},
        "twitch": {"channels": [], "cooldown_seconds": 10},
        "emotions": {"anger": {"decay_lambda": 0.1}, "joy": {"decay_lambda": 0.05},
                     "sadness": {"decay_lambda": 0.08}, "curiosity": {"decay_lambda": 0.1},
                     "boredom": {"decay_lambda": 0.15}},
        "twitch_events": {
            "follow": {"active": True, "message": "Hey {username}!"},
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data))
    config = Config.load(str(cfg_file))
    assert config.bot.trigger_names == ["wally"]
    assert config.openai.primary_model == "gpt-4o"

def test_save_config(tmp_path):
    cfg_data = {"bot": {"trigger_names": ["wally"], "language_default": "fr",
                        "context_window_size": 20, "context_token_threshold": 3000,
                        "journal_time": "03:00", "journal_channel_id": None,
                        "dashboard_token": None, "system_prompt": "Tu es Wally."},
                "openai": {"primary_model": "gpt-4o", "secondary_model": "gpt-4o-mini",
                           "temperature": 0.8, "max_tokens": 1000},
                "discord": {"allowed_channels": [], "anger_trigger_threshold": 3, "timeout_minutes": 10},
                "twitch": {"channels": [], "cooldown_seconds": 10},
                "emotions": {"anger": {"decay_lambda": 0.1}, "joy": {"decay_lambda": 0.05},
                             "sadness": {"decay_lambda": 0.08}, "curiosity": {"decay_lambda": 0.1},
                             "boredom": {"decay_lambda": 0.15}},
                "twitch_events": {}}
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data))
    config = Config.load(str(cfg_file))
    config.bot.trigger_names.append("hey-wally")
    config.save()
    reloaded = Config.load(str(cfg_file))
    assert "hey-wally" in reloaded.bot.trigger_names
```

Run: `pytest tests/test_config.py -v` → FAIL (Config not yet implemented)

**Implementation:**

```python
# bot/config.py
from __future__ import annotations
import os
from dataclasses import dataclass, field, asdict
from typing import Optional
import yaml
from dotenv import load_dotenv

load_dotenv()

@dataclass
class BotConfig:
    trigger_names: list[str]
    language_default: str
    context_window_size: int
    context_token_threshold: int
    journal_time: str
    system_prompt: str
    journal_channel_id: Optional[int] = None
    dashboard_token: Optional[str] = None

@dataclass
class OpenAIConfig:
    primary_model: str
    secondary_model: str
    temperature: float
    max_tokens: int

@dataclass
class DiscordConfig:
    allowed_channels: list[int]
    anger_trigger_threshold: int
    timeout_minutes: int

@dataclass
class TwitchConfig:
    channels: list[str]
    cooldown_seconds: int

@dataclass
class EmotionDecayConfig:
    decay_lambda: float

@dataclass
class TwitchEventConfig:
    active: bool
    message: str

@dataclass
class Config:
    _path: str
    bot: BotConfig
    openai: OpenAIConfig
    discord: DiscordConfig
    twitch: TwitchConfig
    emotions: dict[str, EmotionDecayConfig]
    twitch_events: dict[str, TwitchEventConfig]

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        with open(path) as f:
            raw = yaml.safe_load(f)
        emotions = {k: EmotionDecayConfig(**v) for k, v in raw.get("emotions", {}).items()}
        twitch_events = {k: TwitchEventConfig(**v) for k, v in raw.get("twitch_events", {}).items()}
        return cls(
            _path=path,
            bot=BotConfig(**raw["bot"]),
            openai=OpenAIConfig(**raw["openai"]),
            discord=DiscordConfig(**raw["discord"]),
            twitch=TwitchConfig(**raw["twitch"]),
            emotions=emotions,
            twitch_events=twitch_events,
        )

    def save(self) -> None:
        data = {
            "bot": {k: v for k, v in vars(self.bot).items()},
            "openai": vars(self.openai),
            "discord": vars(self.discord),
            "twitch": vars(self.twitch),
            "emotions": {k: vars(v) for k, v in self.emotions.items()},
            "twitch_events": {k: vars(v) for k, v in self.twitch_events.items()},
        }
        with open(self._path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
```

Run: `pytest tests/test_config.py -v` → PASS

**Commit:** `git add bot/config.py tests/ && git commit -m "feat: add Config with hot-reload save()"`

---

### Task 1.2: Database

**Files:**
- Create: `bot/db/__init__.py` (empty)
- Create: `bot/db/database.py`
- Create: `tests/test_database.py`

**Test:**

```python
# tests/test_database.py
import pytest, asyncio
from bot.db.database import Database

@pytest.mark.asyncio
async def test_schema_created(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in tables}
    assert {"cost_log", "timeout_log", "welcomed", "trust_scores"}.issubset(names)
    await db.close()

@pytest.mark.asyncio
async def test_trust_score(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.update_trust_score("discord", "user1", 0.05)
    score = await db.get_trust_score("discord", "user1")
    assert abs(score - 0.05) < 0.001
    await db.close()

@pytest.mark.asyncio
async def test_welcomed(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    assert not await db.is_welcomed("user1", "guild1")
    await db.mark_welcomed("user1", "guild1")
    assert await db.is_welcomed("user1", "guild1")
    await db.close()
```

Run: `pytest tests/test_database.py -v` → FAIL

**Implementation:**

```python
# bot/db/database.py
from __future__ import annotations
import time
from typing import Optional
import aiosqlite
from loguru import logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    purpose TEXT
);

CREATE TABLE IF NOT EXISTS timeout_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    triggered_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    anger_level REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS welcomed (
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    welcomed_at REAL NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS trust_scores (
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.5,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, platform)
);
"""

class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn
        self._conn.row_factory = aiosqlite.Row

    @classmethod
    async def create(cls, path: str = "data/wally.db") -> "Database":
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.executescript(SCHEMA)
        await conn.commit()
        logger.info("Database initialized at {path}", path=path)
        return cls(conn)

    async def close(self):
        await self._conn.close()

    async def fetch_all(self, query: str, params=()) -> list:
        async with self._conn.execute(query, params) as cursor:
            return await cursor.fetchall()

    async def fetch_one(self, query: str, params=()) -> Optional[aiosqlite.Row]:
        async with self._conn.execute(query, params) as cursor:
            return await cursor.fetchone()

    async def execute(self, query: str, params=()):
        await self._conn.execute(query, params)
        await self._conn.commit()

    # Cost tracking
    async def log_cost(self, model: str, input_tokens: int, output_tokens: int,
                       cost_usd: float, purpose: str = ""):
        await self.execute(
            "INSERT INTO cost_log (timestamp, model, input_tokens, output_tokens, cost_usd, purpose) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), model, input_tokens, output_tokens, cost_usd, purpose)
        )

    async def get_cost_since(self, since_timestamp: float) -> float:
        row = await self.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM cost_log WHERE timestamp >= ?",
            (since_timestamp,)
        )
        return row["total"] if row else 0.0

    # Timeout / mute
    async def add_timeout(self, user_id: str, guild_id: str, duration_minutes: int, anger_level: float):
        now = time.time()
        await self.execute(
            "INSERT INTO timeout_log (user_id, guild_id, triggered_at, expires_at, anger_level) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, guild_id, now, now + duration_minutes * 60, anger_level)
        )

    async def is_muted(self, user_id: str, guild_id: str) -> bool:
        row = await self.fetch_one(
            "SELECT expires_at FROM timeout_log WHERE user_id=? AND guild_id=? "
            "ORDER BY expires_at DESC LIMIT 1",
            (user_id, guild_id)
        )
        return row is not None and row["expires_at"] > time.time()

    async def count_recent_triggers(self, user_id: str, guild_id: str, window_seconds: int = 300) -> int:
        row = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM timeout_log WHERE user_id=? AND guild_id=? AND triggered_at >= ?",
            (user_id, guild_id, time.time() - window_seconds)
        )
        return row["cnt"] if row else 0

    # Welcome
    async def is_welcomed(self, user_id: str, guild_id: str) -> bool:
        row = await self.fetch_one(
            "SELECT 1 FROM welcomed WHERE user_id=? AND guild_id=?", (user_id, guild_id)
        )
        return row is not None

    async def mark_welcomed(self, user_id: str, guild_id: str):
        await self.execute(
            "INSERT OR IGNORE INTO welcomed (user_id, guild_id, welcomed_at) VALUES (?, ?, ?)",
            (user_id, guild_id, time.time())
        )

    # Trust scores
    async def get_trust_score(self, platform: str, user_id: str) -> float:
        row = await self.fetch_one(
            "SELECT score FROM trust_scores WHERE user_id=? AND platform=?", (user_id, platform)
        )
        return row["score"] if row else 0.5

    async def update_trust_score(self, platform: str, user_id: str, delta: float):
        current = await self.get_trust_score(platform, user_id)
        new_score = max(0.0, min(1.0, current + delta))
        await self.execute(
            "INSERT INTO trust_scores (user_id, platform, score, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, platform) DO UPDATE SET score=excluded.score, updated_at=excluded.updated_at",
            (user_id, platform, new_score, time.time())
        )
```

Run: `pytest tests/test_database.py -v` → PASS

**Commit:** `git add bot/db/ tests/test_database.py && git commit -m "feat: add Database with all 4 tables"`

---

### Task 1.3: Package init files

**Files:**
- Create: `bot/core/__init__.py` (empty)
- Create: `bot/discord/__init__.py` (empty)
- Create: `bot/discord/commands/__init__.py` (empty)
- Create: `bot/twitch/__init__.py` (empty)

```bash
mkdir -p bot/core bot/discord/commands bot/twitch bot/db
touch bot/core/__init__.py bot/discord/__init__.py bot/discord/commands/__init__.py bot/twitch/__init__.py
```

**Commit:** `git add bot/ && git commit -m "feat: add package init files"`

---

### Task 1.4: Wire main.py skeleton

**Files:**
- Modify: `bot/main.py`

```python
# bot/main.py
import asyncio
import os
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from bot.config import Config
from bot.db.database import Database


async def main():
    logger.add("logs/wally.log", rotation="1 day", retention="30 days", level="INFO")
    logger.info("Wally starting...")

    config = Config.load("config.yaml")
    db = await Database.create(os.getenv("DB_PATH", "data/wally.db"))

    logger.info("Config loaded, DB ready. Bot services not yet wired.")
    # asyncio.gather() with bots goes here in later phases

    await db.close()

if __name__ == "__main__":
    asyncio.run(main())
```

Run: `python -m bot.main` → should log "Wally starting..." and exit cleanly.

**Commit:** `git add bot/main.py && git commit -m "feat: wire main.py skeleton with config and db"`

---

## Phase 2 — Core Services

### Task 2.1: Language detection

**Files:**
- Create: `bot/core/language.py`
- Create: `tests/test_language.py`

**Test:**

```python
# tests/test_language.py
from bot.core.language import LanguageDetector

def test_detect_french():
    det = LanguageDetector(default_lang="fr")
    assert det.detect("Bonjour, comment vas-tu ?") == "fr"

def test_detect_english():
    det = LanguageDetector(default_lang="fr")
    assert det.detect("Hello, how are you today?") == "en"

def test_fallback_on_short():
    det = LanguageDetector(default_lang="fr")
    result = det.detect("ok")  # too short to detect reliably
    assert isinstance(result, str) and len(result) == 2
```

Run: `pytest tests/test_language.py -v` → FAIL

**Implementation:**

```python
# bot/core/language.py
from langdetect import detect, LangDetectException
from loguru import logger

class LanguageDetector:
    def __init__(self, default_lang: str = "fr"):
        self._default = default_lang

    def detect(self, text: str) -> str:
        try:
            return detect(text)
        except LangDetectException:
            logger.debug("Language detection failed for text, using default {d}", d=self._default)
            return self._default
```

Run: `pytest tests/test_language.py -v` → PASS

**Commit:** `git add bot/core/language.py tests/test_language.py && git commit -m "feat: add LanguageDetector"`

---

### Task 2.2: Prompts

**Files:**
- Create: `bot/core/prompts.py`
- Create: `tests/test_prompts.py`

**Test:**

```python
# tests/test_prompts.py
from bot.core.prompts import PromptBuilder

def test_build_includes_system_prompt():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.8, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.0},
        language="fr"
    )
    assert "Tu es Wally." in result

def test_emotion_directive_injected():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        language="fr"
    )
    assert "impatient" in result.lower() or "court" in result.lower()

def test_language_injected():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        language="en"
    )
    assert "english" in result.lower() or "en" in result.lower()

def test_twitch_event_template():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.format_event_message(
        "Bienvenue {username} !", username="Alice", amount=0, months=0, raiders_count=0
    )
    assert result == "Bienvenue Alice !"
```

Run: `pytest tests/test_prompts.py -v` → FAIL

**Implementation:**

```python
# bot/core/prompts.py
from __future__ import annotations

EMOTION_DIRECTIVES: dict[str, str] = {
    "anger": (
        "Tes réponses sont courtes et impatientes. Tu réponds sec, sans fioritures. "
        "Tu n'as pas envie de t'étendre. Reste poli mais clairement agacé."
    ),
    "joy": (
        "Tu es enthousiaste et chaleureux. Tes réponses sont vivantes, tu aimes plaisanter. "
        "Tu rayonnes de bonne humeur."
    ),
    "sadness": (
        "Tu es mélancolique et introspectif. Tes réponses sont douces mais teintées de tristesse. "
        "Tu te montres empathique."
    ),
    "curiosity": (
        "Tu es particulièrement curieux et poseur de questions. "
        "Tu approfondis les sujets et tu rebondis sur les détails intéressants."
    ),
    "boredom": (
        "Tu sembles peu enthousiaste. Tes réponses sont plus courtes que d'habitude, "
        "tu attends que la conversation devienne plus intéressante."
    ),
}

EMOTION_THRESHOLD = 0.4

CONTEXT_HEADER = """
--- Contexte de la conversation (messages récents, plusieurs auteurs) ---
{context}
--- Fin du contexte ---
"""

class PromptBuilder:
    def __init__(self, system_prompt: str):
        self._base = system_prompt.strip()

    def build_system_prompt(
        self,
        emotion_state: dict[str, float],
        language: str,
        memory_context: str = "",
    ) -> str:
        parts = [self._base]

        # Language directive
        lang_map = {"fr": "français", "en": "English", "es": "español", "de": "Deutsch"}
        lang_label = lang_map.get(language, language)
        parts.append(f"\nRéponds toujours en {lang_label} dans cette conversation.")

        # Emotion directives for dominant emotions
        dominant = [
            (emotion, value)
            for emotion, value in emotion_state.items()
            if value >= EMOTION_THRESHOLD
        ]
        dominant.sort(key=lambda x: x[1], reverse=True)

        if dominant:
            parts.append("\n--- État émotionnel actuel ---")
            for emotion, _ in dominant[:2]:  # max 2 dominant emotions
                if emotion in EMOTION_DIRECTIVES:
                    parts.append(EMOTION_DIRECTIVES[emotion])

        # Long-term memory context
        if memory_context:
            parts.append(f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}")

        return "\n".join(parts)

    def build_context_block(self, messages: list[dict]) -> str:
        """Format sliding window messages as context string."""
        if not messages:
            return ""
        lines = [f"[{m['author']}]: {m['content']}" for m in messages]
        return CONTEXT_HEADER.format(context="\n".join(lines))

    @staticmethod
    def format_event_message(template: str, **kwargs) -> str:
        return template.format(**{k: v for k, v in kwargs.items() if v is not None})
```

Run: `pytest tests/test_prompts.py -v` → PASS

**Commit:** `git add bot/core/prompts.py tests/test_prompts.py && git commit -m "feat: add PromptBuilder with emotion directives"`

---

### Task 2.3: Emotion Engine

**Files:**
- Create: `bot/core/emotion.py`
- Create: `tests/test_emotion.py`

**Test:**

```python
# tests/test_emotion.py
import pytest, asyncio, math, time
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine

def make_config():
    config = MagicMock()
    config.emotions = {
        "anger": MagicMock(decay_lambda=0.1),
        "joy": MagicMock(decay_lambda=0.05),
        "sadness": MagicMock(decay_lambda=0.08),
        "curiosity": MagicMock(decay_lambda=0.1),
        "boredom": MagicMock(decay_lambda=0.15),
    }
    config.discord.anger_trigger_threshold = 3
    config.discord.timeout_minutes = 10
    return config

def test_initial_state():
    engine = EmotionEngine(make_config())
    state = engine.get_state()
    assert all(0.0 <= v <= 1.0 for v in state.values())

def test_apply_delta_clamps():
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 2.0)
    assert engine.get_state()["joy"] == 1.0

def test_apply_delta_negative_clamps():
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", -5.0)
    assert engine.get_state()["anger"] == 0.0

def test_reset():
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 0.8)
    engine.reset()
    assert engine.get_state()["joy"] == 0.0

def test_decay():
    engine = EmotionEngine(make_config())
    engine.apply_delta("anger", 1.0)
    # simulate 10 seconds elapsed
    engine._last_decay = time.time() - 10
    engine._apply_decay()
    # anger should have decayed: E = 1.0 * e^(-0.1 * 10) = 0.368
    assert engine.get_state()["anger"] < 0.5

def test_dominant_emotions():
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 0.9)
    engine.apply_delta("curiosity", 0.5)
    dominant = engine.get_dominant(threshold=0.4)
    assert "joy" in dominant
    assert "curiosity" in dominant
    assert "anger" not in dominant
```

Run: `pytest tests/test_emotion.py -v` → FAIL

**Implementation:**

```python
# bot/core/emotion.py
from __future__ import annotations
import asyncio
import math
import time
from typing import TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config

EMOTIONS = ["anger", "joy", "sadness", "curiosity", "boredom"]

class EmotionEngine:
    def __init__(self, config: "Config"):
        self._config = config
        self._state: dict[str, float] = {e: 0.0 for e in EMOTIONS}
        self._last_decay: float = time.time()
        self._decay_task: asyncio.Task | None = None

    def get_state(self) -> dict[str, float]:
        return dict(self._state)

    def apply_delta(self, emotion: str, delta: float):
        if emotion not in self._state:
            return
        self._state[emotion] = max(0.0, min(1.0, self._state[emotion] + delta))

    def set_emotion(self, emotion: str, value: float):
        if emotion in self._state:
            self._state[emotion] = max(0.0, min(1.0, value))

    def reset(self):
        self._state = {e: 0.0 for e in EMOTIONS}
        logger.info("Emotion state reset to zero")

    def get_dominant(self, threshold: float = 0.4) -> list[str]:
        return [e for e, v in self._state.items() if v >= threshold]

    def _apply_decay(self):
        now = time.time()
        delta_t = now - self._last_decay
        for emotion in EMOTIONS:
            cfg = self._config.emotions.get(emotion)
            if cfg and self._state[emotion] > 0:
                lam = cfg.decay_lambda
                self._state[emotion] = self._state[emotion] * math.exp(-lam * delta_t)
                if self._state[emotion] < 0.01:
                    self._state[emotion] = 0.0
        self._last_decay = now

    async def _decay_loop(self):
        while True:
            await asyncio.sleep(60)
            self._apply_decay()
            logger.debug("Emotion decay applied: {state}", state=self._state)

    def start_decay_task(self):
        self._decay_task = asyncio.create_task(self._decay_loop())
        logger.info("Emotion decay task started")

    async def analyze_message(self, text: str, trust_score: float = 0.5) -> dict[str, float]:
        """Run NRCLex analysis in thread pool, return emotion deltas."""
        return await asyncio.to_thread(self._analyze_sync, text, trust_score)

    def _analyze_sync(self, text: str, trust_score: float) -> dict[str, float]:
        try:
            from nrclex import NRCLex
            analysis = NRCLex(text)
            scores = analysis.affect_frequencies

            # NRC → our 5 emotions mapping
            nrc_map = {
                "anger": ["anger", "disgust"],
                "joy": ["joy", "trust", "anticipation"],
                "sadness": ["sadness", "fear"],
                "curiosity": ["surprise"],
                "boredom": [],
            }

            deltas: dict[str, float] = {}
            for emotion, nrc_keys in nrc_map.items():
                raw = sum(scores.get(k, 0.0) for k in nrc_keys)
                if raw > 0:
                    # Low trust amplifies anger
                    if emotion == "anger":
                        amplifier = 1.0 + (1.0 - trust_score)
                        raw = min(raw * amplifier, 0.5)
                    deltas[emotion] = min(raw * 0.3, 0.3)  # cap per-message delta
            return deltas
        except Exception as e:
            logger.warning("NRCLex analysis failed: {e}", e=e)
            return {}

    async def process_message(self, text: str, trust_score: float = 0.5):
        deltas = await self.analyze_message(text, trust_score)
        for emotion, delta in deltas.items():
            self.apply_delta(emotion, delta)
```

Run: `pytest tests/test_emotion.py -v` → PASS

**Commit:** `git add bot/core/emotion.py tests/test_emotion.py && git commit -m "feat: add EmotionEngine with NRCLex + exponential decay"`

---

### Task 2.4: OpenAI Client

**Files:**
- Create: `bot/core/openai_client.py`

Note: No unit test here — mocking the OpenAI SDK is brittle. Manual integration test after wiring.

```python
# bot/core/openai_client.py
from __future__ import annotations
import asyncio
import time
from typing import TYPE_CHECKING, Optional
from openai import AsyncOpenAI, RateLimitError, APIStatusError
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database

# Approximate cost per 1M tokens (input, output) in USD
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "gpt-4o": (5.0, 15.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.0, 30.0),
    "o1": (15.0, 60.0),
    "o3-mini": (1.10, 4.40),
}

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    base = next((v for k, v in MODEL_COSTS.items() if k in model), (5.0, 15.0))
    return (input_tokens * base[0] + output_tokens * base[1]) / 1_000_000

class OpenAIClient:
    def __init__(self, config: "Config", db: "Database"):
        self._config = config
        self._db = db
        self._client = AsyncOpenAI()

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        model: Optional[str] = None,
        purpose: str = "response",
    ) -> str:
        model = model or self._config.openai.primary_model
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=self._config.openai.temperature,
                    max_tokens=self._config.openai.max_tokens,
                )
                usage = response.usage
                cost = estimate_cost(model, usage.prompt_tokens, usage.completion_tokens)
                await self._db.log_cost(model, usage.prompt_tokens, usage.completion_tokens, cost, purpose)
                logger.info("OpenAI {model} — {inp}in/{out}out tokens, ${cost:.6f}",
                            model=model, inp=usage.prompt_tokens, out=usage.completion_tokens, cost=cost)
                return response.choices[0].message.content.strip()

            except RateLimitError:
                wait = 2 ** attempt
                logger.warning("Rate limited, retrying in {w}s (attempt {a}/3)", w=wait, a=attempt+1)
                await asyncio.sleep(wait)
            except APIStatusError as e:
                if e.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("OpenAI server error {code}, retrying in {w}s", code=e.status_code, w=wait)
                    await asyncio.sleep(wait)
                else:
                    logger.error("OpenAI API error: {e}", e=e)
                    break
            except Exception as e:
                logger.error("OpenAI unexpected error: {e}", e=e)
                break

        return "Je rencontre un problème technique, réessaie dans un moment."

    async def complete_secondary(self, system_prompt: str, messages: list[dict], purpose: str = "summary") -> str:
        return await self.complete(system_prompt, messages, model=self._config.openai.secondary_model, purpose=purpose)

    async def get_daily_cost(self) -> float:
        since = time.time() - 86400
        return await self._db.get_cost_since(since)

    async def get_monthly_cost(self) -> float:
        since = time.time() - 86400 * 30
        return await self._db.get_cost_since(since)
```

**Commit:** `git add bot/core/openai_client.py && git commit -m "feat: add OpenAIClient with retry and cost tracking"`

---

### Task 2.5: Memory Service

**Files:**
- Create: `bot/core/memory.py`

```python
# bot/core/memory.py
from __future__ import annotations
import os
import time
from typing import TYPE_CHECKING, Optional
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.openai_client import OpenAIClient

SYSTEM_PROMPT_SUMMARIZE = (
    "Résume ce contexte de conversation de façon concise en conservant les informations "
    "importantes : qui parle, les sujets abordés, les faits clés. Sois bref."
)

class MemoryService:
    def __init__(self, config: "Config"):
        self._config = config
        self._mem0: Optional[object] = None
        # Sliding context window per channel: channel_id -> list of {author, content, timestamp}
        self._context_windows: dict[str, list[dict]] = {}
        self._openai: Optional["OpenAIClient"] = None  # injected after init to avoid circular dep

    def set_openai_client(self, client: "OpenAIClient"):
        self._openai = client

    def _init_mem0(self):
        if self._mem0 is not None:
            return
        try:
            from mem0 import Memory
            self._mem0 = Memory.from_config({
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "url": os.getenv("QDRANT_URL", "http://localhost:6333"),
                        "collection_name": "wally_memory",
                    }
                }
            })
            logger.info("mem0 initialized with local Qdrant")
        except Exception as e:
            logger.warning("mem0 init failed (Qdrant unavailable?): {e}", e=e)
            self._mem0 = None

    def _user_id(self, platform: str, user_id: str) -> str:
        return f"{platform}:{user_id}"

    async def add(self, platform: str, user_id: str, content: str):
        self._init_mem0()
        if self._mem0 is None:
            return
        try:
            import asyncio
            uid = self._user_id(platform, user_id)
            await asyncio.to_thread(self._mem0.add, content, user_id=uid)
        except Exception as e:
            logger.warning("mem0 add failed: {e}", e=e)

    async def search(self, platform: str, user_id: str, query: str) -> str:
        self._init_mem0()
        if self._mem0 is None:
            return ""
        try:
            import asyncio
            uid = self._user_id(platform, user_id)
            results = await asyncio.to_thread(self._mem0.search, query, user_id=uid, limit=5)
            if not results:
                return ""
            return "\n".join(r.get("memory", "") for r in results if r.get("memory"))
        except Exception as e:
            logger.warning("mem0 search failed: {e}", e=e)
            return ""

    # Sliding context window
    def append_message(self, channel_id: str, author: str, content: str):
        window = self._context_windows.setdefault(channel_id, [])
        window.append({"author": author, "content": content, "timestamp": time.time()})
        max_size = self._config.bot.context_window_size
        if len(window) > max_size:
            self._context_windows[channel_id] = window[-max_size:]

    def get_context(self, channel_id: str) -> list[dict]:
        return list(self._context_windows.get(channel_id, []))

    async def get_context_summarized_if_needed(self, channel_id: str) -> list[dict]:
        """Return context, summarizing if token estimate exceeds threshold."""
        messages = self.get_context(channel_id)
        threshold = self._config.bot.context_token_threshold
        # rough token estimate: 4 chars ≈ 1 token
        total_chars = sum(len(m["content"]) for m in messages)
        if total_chars / 4 < threshold or self._openai is None:
            return messages

        # Summarize in chunks of 10 messages, then summarize summaries
        logger.info("Context window for {ch} exceeds threshold, summarizing", ch=channel_id)
        chunk_size = 10
        summaries = []
        for i in range(0, len(messages), chunk_size):
            chunk = messages[i:i + chunk_size]
            chunk_text = "\n".join(f"[{m['author']}]: {m['content']}" for m in chunk)
            summary = await self._openai.complete_secondary(
                SYSTEM_PROMPT_SUMMARIZE,
                [{"role": "user", "content": chunk_text}],
                purpose="context_summary"
            )
            summaries.append(summary)

        if len(summaries) > 1:
            combined = "\n".join(summaries)
            final_summary = await self._openai.complete_secondary(
                SYSTEM_PROMPT_SUMMARIZE,
                [{"role": "user", "content": combined}],
                purpose="context_summary_final"
            )
        else:
            final_summary = summaries[0]

        summary_message = {
            "author": "RÉSUMÉ",
            "content": final_summary,
            "timestamp": time.time()
        }
        self._context_windows[channel_id] = [summary_message]
        return [summary_message]
```

**Commit:** `git add bot/core/memory.py && git commit -m "feat: add MemoryService with mem0 + sliding context window"`

---

### Task 2.6: Journal

**Files:**
- Create: `bot/core/journal.py`

```python
# bot/core/journal.py
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING, Optional
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.openai_client import OpenAIClient
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService

JOURNAL_SYSTEM = (
    "Tu es Wally. Écris ton journal intime de la journée. Parle de tes interactions, "
    "des personnes marquantes, de ton état émotionnel ressenti, et laisse une pensée libre. "
    "Ton ton est naturel, personnel, authentique. Ce journal est secret, juste pour toi."
)

JOURNAL_USER_TEMPLATE = (
    "Voici un résumé de la journée :\n\n{context}\n\nTon état émotionnel : {emotions}\n\n"
    "Écris ton journal intime pour aujourd'hui."
)

class DailyJournal:
    def __init__(
        self,
        config: "Config",
        openai: "OpenAIClient",
        emotion: "EmotionEngine",
        memory: "MemoryService",
    ):
        self._config = config
        self._openai = openai
        self._emotion = emotion
        self._memory = memory
        self._discord_send_cb: Optional[callable] = None  # set by discord bot

    def set_send_callback(self, cb: callable):
        """Inject a coroutine callback: async def send(text: str)"""
        self._discord_send_cb = cb

    async def generate_and_send(self):
        logger.info("Generating daily journal...")
        channel_id = str(self._config.bot.journal_channel_id or "")
        if not channel_id:
            logger.warning("No journal_channel_id configured, skipping journal")
            return

        # Gather all context windows (all channels)
        all_messages = []
        for ch_id, messages in self._memory._context_windows.items():
            all_messages.extend(messages)
        all_messages.sort(key=lambda m: m["timestamp"])

        if not all_messages:
            context_text = "Pas grand chose de notable aujourd'hui."
        else:
            # Multi-pass summarization if needed
            context_text = await self._summarize_for_journal(all_messages)

        emotions = self._emotion.get_state()
        emotions_text = ", ".join(f"{k}: {v:.2f}" for k, v in emotions.items())
        user_msg = JOURNAL_USER_TEMPLATE.format(context=context_text, emotions=emotions_text)

        journal_text = await self._openai.complete_secondary(
            JOURNAL_SYSTEM,
            [{"role": "user", "content": user_msg}],
            purpose="daily_journal"
        )

        if self._discord_send_cb:
            await self._discord_send_cb(f"**Journal de Wally — {self._today()}**\n\n{journal_text}")
            logger.info("Daily journal sent")
        else:
            logger.warning("No Discord send callback set for journal")

    async def _summarize_for_journal(self, messages: list[dict]) -> str:
        """Sliding summarization if message volume is large."""
        total_chars = sum(len(m["content"]) for m in messages)
        if total_chars / 4 < 6000:  # fits in one pass
            return "\n".join(f"[{m['author']}]: {m['content']}" for m in messages)

        chunk_size = 20
        summaries = []
        for i in range(0, len(messages), chunk_size):
            chunk = messages[i:i + chunk_size]
            text = "\n".join(f"[{m['author']}]: {m['content']}" for m in chunk)
            s = await self._openai.complete_secondary(
                "Résume brièvement ces échanges en conservant les moments importants.",
                [{"role": "user", "content": text}],
                purpose="journal_chunk_summary"
            )
            summaries.append(s)

        if len(summaries) == 1:
            return summaries[0]

        combined = "\n---\n".join(summaries)
        return await self._openai.complete_secondary(
            "Fais une synthèse finale de ces résumés de journée.",
            [{"role": "user", "content": combined}],
            purpose="journal_final_summary"
        )

    @staticmethod
    def _today() -> str:
        from datetime import date
        return date.today().strftime("%d/%m/%Y")

    def start(self):
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        time_str = self._config.bot.journal_time  # "03:00"
        hour, minute = map(int, time_str.split(":"))
        scheduler.add_job(self.generate_and_send, "cron", hour=hour, minute=minute)
        scheduler.start()
        logger.info("Daily journal scheduler started, fires at {t}", t=time_str)
```

**Commit:** `git add bot/core/journal.py && git commit -m "feat: add DailyJournal with sliding summarization"`

---

### Task 2.7: Update main.py with all core services

**Files:**
- Modify: `bot/main.py`

```python
# bot/main.py
import asyncio
import os
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from bot.config import Config
from bot.db.database import Database
from bot.core.emotion import EmotionEngine
from bot.core.memory import MemoryService
from bot.core.openai_client import OpenAIClient
from bot.core.prompts import PromptBuilder
from bot.core.language import LanguageDetector
from bot.core.journal import DailyJournal


async def main():
    logger.add("logs/wally.log", rotation="1 day", retention="30 days", level="INFO")
    logger.add("logs/cost.log", filter=lambda r: "cost" in r["message"].lower(),
               format="{time} {message}", serialize=False, rotation="1 week")
    logger.info("Wally starting...")

    config = Config.load("config.yaml")
    db = await Database.create(os.getenv("DB_PATH", "data/wally.db"))

    emotion = EmotionEngine(config)
    emotion.start_decay_task()

    memory = MemoryService(config)
    openai_client = OpenAIClient(config, db)
    memory.set_openai_client(openai_client)

    prompts = PromptBuilder(config.bot.system_prompt)
    language = LanguageDetector(config.bot.language_default)
    journal = DailyJournal(config, openai_client, emotion, memory)

    logger.info("All core services initialized")
    # Discord and Twitch bots wired in Phase 3 and 4
    # asyncio.gather(discord_bot.start(), twitch_bot.start())

    await db.close()

if __name__ == "__main__":
    asyncio.run(main())
```

Run: `python -m bot.main` → should start and exit with "All core services initialized".

**Commit:** `git add bot/main.py && git commit -m "feat: wire all core services in main.py"`

---

## Phase 3 — Discord Adapter

### Task 3.1: Discord Bot class

**Files:**
- Create: `bot/discord/bot.py`

```python
# bot/discord/bot.py
from __future__ import annotations
import discord
from discord.ext import commands
from loguru import logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector

class WallyDiscord(commands.Bot):
    def __init__(
        self,
        config: "Config",
        db: "Database",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        openai: "OpenAIClient",
        prompts: "PromptBuilder",
        language: "LanguageDetector",
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.config = config
        self.db = db
        self.emotion = emotion
        self.memory = memory
        self.openai = openai
        self.prompts = prompts
        self.language = language
        self._start_time = None

    async def setup_hook(self):
        from bot.discord.commands.ask import AskCog
        from bot.discord.commands.status import StatusCog
        from bot.discord.commands.mood import MoodCog
        from bot.discord.commands.memory_cmd import MemoryCog
        from bot.discord.commands.setup import SetupCog

        await self.add_cog(AskCog(self))
        await self.add_cog(StatusCog(self))
        await self.add_cog(MoodCog(self))
        await self.add_cog(MemoryCog(self))
        await self.add_cog(SetupCog(self))
        await self.tree.sync()
        logger.info("Discord slash commands synced")

    async def on_ready(self):
        import time
        self._start_time = time.time()
        logger.info("Discord bot ready as {user}", user=self.user)

    async def on_error(self, event_method: str, *args, **kwargs):
        logger.exception("Discord error in {e}", e=event_method)
```

**Commit:** `git add bot/discord/bot.py && git commit -m "feat: add WallyDiscord Bot class"`

---

### Task 3.2: Message handler

**Files:**
- Create: `bot/discord/handlers.py`

```python
# bot/discord/handlers.py
from __future__ import annotations
import asyncio
import random
from typing import TYPE_CHECKING
import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

TIMEOUT_REACTIONS = ["💩", "⛔", "😤", "🙅", "😒"]

async def handle_message(bot: "WallyDiscord", message: discord.Message):
    if message.author.bot:
        return

    # Trigger detection
    content_lower = message.content.lower()
    mentioned = bot.user in message.mentions
    triggered = mentioned or any(
        name.lower() in content_lower
        for name in bot.config.bot.trigger_names
    )
    if not triggered:
        return

    user_id = str(message.author.id)
    guild_id = str(message.guild.id) if message.guild else "dm"

    # Mute check
    if await bot.db.is_muted(user_id, guild_id):
        emoji = random.choice(TIMEOUT_REACTIONS)
        await message.add_reaction(emoji)
        return

    await _respond(bot, message, user_id, guild_id)

    # Welcome check (after response, non-blocking)
    asyncio.create_task(_maybe_welcome(bot, message, user_id, guild_id))


async def _respond(bot: "WallyDiscord", message: discord.Message, user_id: str, guild_id: str):
    try:
        await message.add_reaction("🔍")

        platform = "discord"
        trust = await bot.db.get_trust_score(platform, user_id)
        lang = bot.language.detect(message.content)

        # Memory
        mem_context = await bot.memory.search(platform, user_id, message.content)
        context_messages = await bot.memory.get_context_summarized_if_needed(str(message.channel.id))

        # Build system prompt
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            language=lang,
            memory_context=mem_context,
        )

        # Build context block
        context_block = bot.prompts.build_context_block(context_messages)

        # Build messages for OpenAI
        user_content = message.content
        if context_block:
            user_content = context_block + f"\n[{message.author.display_name}]: {message.content}"

        openai_messages = [
            {"role": "user", "content": user_content}
        ]

        async with message.channel.typing():
            reply = await bot.openai.complete(system_prompt, openai_messages, purpose="discord_response")

        # Remove reaction and reply
        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass
        await message.reply(reply)

        # Append to sliding window
        bot.memory.append_message(str(message.channel.id), message.author.display_name, message.content)
        bot.memory.append_message(str(message.channel.id), "Wally", reply)

        # Background: emotion analysis + trust update
        asyncio.create_task(_post_process(bot, message.content, platform, user_id, trust))

    except Exception as e:
        logger.error("Error handling Discord message: {e}", e=e)
        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass


async def _post_process(bot: "WallyDiscord", text: str, platform: str, user_id: str, trust: float):
    try:
        await bot.emotion.process_message(text, trust_score=trust)

        # Simple heuristic trust update: check for insults
        insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
        if any(w in text.lower() for w in insult_words):
            await bot.db.update_trust_score(platform, user_id, -0.05)
        else:
            await bot.db.update_trust_score(platform, user_id, 0.01)

        # Check anger threshold for mute
        anger = bot.emotion.get_state().get("anger", 0.0)
        if anger >= 0.8:
            guild_id = "global"  # placeholder; real guild_id passed in production
            count = await bot.db.count_recent_triggers(user_id, guild_id)
            if count >= bot.config.discord.anger_trigger_threshold:
                await bot.db.add_timeout(
                    user_id, guild_id,
                    bot.config.discord.timeout_minutes,
                    anger
                )
                logger.info("User {uid} muted for {m} minutes", uid=user_id, m=bot.config.discord.timeout_minutes)
    except Exception as e:
        logger.error("Post-process error: {e}", e=e)


async def _maybe_welcome(bot: "WallyDiscord", message: discord.Message, user_id: str, guild_id: str):
    try:
        if await bot.db.is_welcomed(user_id, guild_id):
            return
        lang = bot.language.detect(message.content)
        system_prompt = bot.prompts.build_system_prompt(bot.emotion.get_state(), lang)
        welcome = await bot.openai.complete(
            system_prompt,
            [{"role": "user", "content": f"C'est la première fois que {message.author.display_name} écrit dans ce serveur. Envoie-lui un message de bienvenue chaleureux et personnalisé."}],
            purpose="discord_welcome"
        )
        await message.channel.send(welcome)
        await bot.db.mark_welcomed(user_id, guild_id)
    except Exception as e:
        logger.error("Welcome error: {e}", e=e)
```

**Commit:** `git add bot/discord/handlers.py && git commit -m "feat: add Discord message handler with full pipeline"`

---

### Task 3.3: /wally ask

**Files:**
- Create: `bot/discord/commands/ask.py`

```python
# bot/discord/commands/ask.py
import discord
from discord.ext import commands
from discord import app_commands
from bot.discord.handlers import _respond
from loguru import logger

class AskCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ask", description="Pose une question directement à Wally")
    @app_commands.describe(question="Ta question pour Wally")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(thinking=True)
        # Create a fake Message-like context or reuse _respond logic inline
        try:
            from bot.discord.handlers import _respond as _r
            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild_id) if interaction.guild_id else "dm"
            platform = "discord"
            trust = await self.bot.db.get_trust_score(platform, user_id)
            lang = self.bot.language.detect(question)
            mem_context = await self.bot.memory.search(platform, user_id, question)
            context_msgs = await self.bot.memory.get_context_summarized_if_needed(str(interaction.channel_id))
            system_prompt = self.bot.prompts.build_system_prompt(
                self.bot.emotion.get_state(), lang, mem_context
            )
            context_block = self.bot.prompts.build_context_block(context_msgs)
            content = (context_block + f"\n[{interaction.user.display_name}]: {question}") if context_block else question
            reply = await self.bot.openai.complete(
                system_prompt, [{"role": "user", "content": content}], purpose="discord_ask"
            )
            self.bot.memory.append_message(str(interaction.channel_id), interaction.user.display_name, question)
            self.bot.memory.append_message(str(interaction.channel_id), "Wally", reply)
            import asyncio
            from bot.discord.handlers import _post_process
            asyncio.create_task(_post_process(self.bot, question, platform, user_id, trust))
            await interaction.followup.send(reply)
        except Exception as e:
            logger.error("Error in /wally ask: {e}", e=e)
            await interaction.followup.send("Une erreur s'est produite.")
```

**Commit:** `git add bot/discord/commands/ask.py && git commit -m "feat: add /wally ask command"`

---

### Task 3.4: /wally status

**Files:**
- Create: `bot/discord/commands/status.py`

```python
# bot/discord/commands/status.py
import time
import discord
from discord.ext import commands
from discord import app_commands

class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="status", description="Statut du bot Wally")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        uptime_s = int(time.time() - (self.bot._start_time or time.time()))
        h, rem = divmod(uptime_s, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h {m}m {s}s"

        daily_cost = await self.bot.openai.get_daily_cost()
        monthly_cost = await self.bot.openai.get_monthly_cost()

        state = self.bot.emotion.get_state()
        dominant = self.bot.emotion.get_dominant(threshold=0.4)
        mood_str = ", ".join(dominant) if dominant else "neutre"

        embed = discord.Embed(title="Statut de Wally", color=discord.Color.blurple())
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(name="Modele principal", value=self.bot.config.openai.primary_model, inline=True)
        embed.add_field(name="Humeur dominante", value=mood_str, inline=True)
        embed.add_field(name="Cout aujourd'hui", value=f"${daily_cost:.4f}", inline=True)
        embed.add_field(name="Cout ce mois", value=f"${monthly_cost:.4f}", inline=True)
        await interaction.followup.send(embed=embed)
```

**Commit:** `git add bot/discord/commands/status.py && git commit -m "feat: add /wally status command"`

---

### Task 3.5: /wally mood

**Files:**
- Create: `bot/discord/commands/mood.py`

```python
# bot/discord/commands/mood.py
import discord
from discord.ext import commands
from discord import app_commands

EMOTION_EMOJIS = {
    "anger": "😤",
    "joy": "😄",
    "sadness": "😢",
    "curiosity": "🤔",
    "boredom": "😑",
}

def make_bar(value: float, length: int = 10) -> str:
    filled = int(value * length)
    return "█" * filled + "░" * (length - filled)

class MoodCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mood", description="Etat emotionnel actuel de Wally")
    async def mood(self, interaction: discord.Interaction):
        state = self.bot.emotion.get_state()
        embed = discord.Embed(title="Humeur de Wally", color=discord.Color.orange())
        for emotion, value in state.items():
            emoji = EMOTION_EMOJIS.get(emotion, "")
            bar = make_bar(value)
            embed.add_field(
                name=f"{emoji} {emotion.capitalize()}",
                value=f"{bar} `{value:.2f}`",
                inline=False
            )
        await interaction.response.send_message(embed=embed)
```

**Commit:** `git add bot/discord/commands/mood.py && git commit -m "feat: add /wally mood command"`

---

### Task 3.6: /wally memory show

**Files:**
- Create: `bot/discord/commands/memory_cmd.py`

```python
# bot/discord/commands/memory_cmd.py
import discord
from discord.ext import commands
from discord import app_commands
from loguru import logger

class MemoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="memory", description="Gestion de la memoire de Wally (admin)")
    @app_commands.describe(user="L'utilisateur dont afficher la memoire")
    @app_commands.default_member_permissions(administrator=True)
    async def memory_show(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            mem = await self.bot.memory.search("discord", str(user.id), "")
            if not mem:
                await interaction.followup.send(f"Aucune memoire pour {user.display_name}.", ephemeral=True)
                return
            # Truncate if too long for Discord embed
            if len(mem) > 1900:
                mem = mem[:1900] + "\n...(tronque)"
            embed = discord.Embed(
                title=f"Memoire de Wally pour {user.display_name}",
                description=mem,
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error("Memory show error: {e}", e=e)
            await interaction.followup.send("Erreur lors de la lecture de la memoire.", ephemeral=True)
```

**Commit:** `git add bot/discord/commands/memory_cmd.py && git commit -m "feat: add /wally memory show command"`

---

### Task 3.7: /wally setup

**Files:**
- Create: `bot/discord/commands/setup.py`

This is the most complex command. It uses Discord's View/Modal/Select system.

```python
# bot/discord/commands/setup.py
from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
from loguru import logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

EXCLUDED_MODEL_KEYWORDS = ["realtime", "preview", "audio", "vision"]
INCLUDED_MODEL_KEYWORDS = ["gpt", "chatgpt", "o1", "o3", "o4"]

def is_valid_model(model_id: str) -> bool:
    mid = model_id.lower()
    if any(ex in mid for ex in EXCLUDED_MODEL_KEYWORDS):
        return False
    return any(inc in mid for inc in INCLUDED_MODEL_KEYWORDS)


# ── Tab: Humeur ──────────────────────────────────────────────────────────────

class EditEmotionModal(discord.ui.Modal, title="Modifier une emotion"):
    value = discord.ui.TextInput(
        label="Nouvelle valeur (0.0 - 1.0)",
        placeholder="0.5",
        max_length=4,
    )

    def __init__(self, bot: "WallyDiscord", emotion: str):
        super().__init__()
        self.bot = bot
        self.emotion = emotion

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = float(self.value.value)
            self.bot.emotion.set_emotion(self.emotion, v)
            await interaction.response.send_message(
                f"{self.emotion} mis a {v:.2f}", ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("Valeur invalide.", ephemeral=True)


class MoodView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot
        for emotion in ["anger", "joy", "sadness", "curiosity", "boredom"]:
            self.add_item(EmotionMinusButton(bot, emotion))
            self.add_item(EmotionPlusButton(bot, emotion))
            self.add_item(EmotionEditButton(bot, emotion))
        self.add_item(ResetMoodButton(bot))

class EmotionMinusButton(discord.ui.Button):
    def __init__(self, bot, emotion):
        super().__init__(label=f"- {emotion}", style=discord.ButtonStyle.secondary, row=list(["anger","joy","sadness","curiosity","boredom"]).index(emotion) % 5)
        self.bot = bot
        self.emotion = emotion
    async def callback(self, interaction: discord.Interaction):
        self.bot.emotion.apply_delta(self.emotion, -0.1)
        v = self.bot.emotion.get_state()[self.emotion]
        await interaction.response.send_message(f"{self.emotion}: {v:.2f}", ephemeral=True)

class EmotionPlusButton(discord.ui.Button):
    def __init__(self, bot, emotion):
        super().__init__(label=f"+ {emotion}", style=discord.ButtonStyle.primary, row=list(["anger","joy","sadness","curiosity","boredom"]).index(emotion) % 5)
        self.bot = bot
        self.emotion = emotion
    async def callback(self, interaction: discord.Interaction):
        self.bot.emotion.apply_delta(self.emotion, 0.1)
        v = self.bot.emotion.get_state()[self.emotion]
        await interaction.response.send_message(f"{self.emotion}: {v:.2f}", ephemeral=True)

class EmotionEditButton(discord.ui.Button):
    def __init__(self, bot, emotion):
        super().__init__(label=f"Edit {emotion}", style=discord.ButtonStyle.secondary, row=list(["anger","joy","sadness","curiosity","boredom"]).index(emotion) % 5)
        self.bot = bot
        self.emotion = emotion
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditEmotionModal(self.bot, self.emotion))

class ResetMoodButton(discord.ui.Button):
    def __init__(self, bot):
        super().__init__(label="Reset humeur", style=discord.ButtonStyle.danger, row=4)
        self.bot = bot
    async def callback(self, interaction: discord.Interaction):
        self.bot.emotion.reset()
        await interaction.response.send_message("Toutes les emotions remises a 0.", ephemeral=True)


# ── Tab: Twitch Events ────────────────────────────────────────────────────────

class EditEventMessageModal(discord.ui.Modal, title="Modifier le message"):
    message = discord.ui.TextInput(
        label="Message (supports {username}, {amount}, etc.)",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, bot: "WallyDiscord", event_name: str, current_message: str):
        super().__init__()
        self.bot = bot
        self.event_name = event_name
        self.message.default = current_message

    async def on_submit(self, interaction: discord.Interaction):
        event = self.bot.config.twitch_events.get(self.event_name)
        if event:
            event.message = self.message.value
            self.bot.config.save()
            await interaction.response.send_message(
                f"Message pour {self.event_name} mis a jour.", ephemeral=True
            )


class TwitchEventsView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot
        for event_name, event_cfg in bot.config.twitch_events.items():
            self.add_item(ToggleEventButton(bot, event_name, event_cfg.active))
            self.add_item(EditEventButton(bot, event_name))

class ToggleEventButton(discord.ui.Button):
    def __init__(self, bot, event_name, active):
        label = f"{'✅' if active else '❌'} {event_name}"
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.bot = bot
        self.event_name = event_name
    async def callback(self, interaction: discord.Interaction):
        event = self.bot.config.twitch_events.get(self.event_name)
        if event:
            event.active = not event.active
            self.bot.config.save()
            status = "active" if event.active else "inactive"
            await interaction.response.send_message(f"{self.event_name} est maintenant {status}.", ephemeral=True)

class EditEventButton(discord.ui.Button):
    def __init__(self, bot, event_name):
        super().__init__(label=f"Modifier {event_name}", style=discord.ButtonStyle.primary)
        self.bot = bot
        self.event_name = event_name
    async def callback(self, interaction: discord.Interaction):
        event = self.bot.config.twitch_events.get(self.event_name)
        current = event.message if event else ""
        await interaction.response.send_modal(EditEventMessageModal(self.bot, self.event_name, current))


# ── Tab: Trigger Names ────────────────────────────────────────────────────────

class AddTriggerModal(discord.ui.Modal, title="Ajouter un nom declencheur"):
    name = discord.ui.TextInput(label="Nouveau nom", max_length=50)

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name.value.strip().lower()
        if new_name and new_name not in self.bot.config.bot.trigger_names:
            self.bot.config.bot.trigger_names.append(new_name)
            self.bot.config.save()
            await interaction.response.send_message(f'"{new_name}" ajoute aux noms declencheurs.', ephemeral=True)
        else:
            await interaction.response.send_message("Nom invalide ou deja present.", ephemeral=True)


class TriggerNamesView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot
        self.add_item(AddTriggerButton(bot))
        for name in bot.config.bot.trigger_names:
            self.add_item(RemoveTriggerButton(bot, name))

class AddTriggerButton(discord.ui.Button):
    def __init__(self, bot):
        super().__init__(label="Ajouter un nom", style=discord.ButtonStyle.success)
        self.bot = bot
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddTriggerModal(self.bot))

class RemoveTriggerButton(discord.ui.Button):
    def __init__(self, bot, name):
        only_one = len(bot.config.bot.trigger_names) <= 1
        super().__init__(label=f"Supprimer '{name}'", style=discord.ButtonStyle.danger, disabled=only_one)
        self.bot = bot
        self.name = name
    async def callback(self, interaction: discord.Interaction):
        if len(self.bot.config.bot.trigger_names) <= 1:
            await interaction.response.send_message("Impossible de supprimer le dernier nom.", ephemeral=True)
            return
        self.bot.config.bot.trigger_names.remove(self.name)
        self.bot.config.save()
        await interaction.response.send_message(f'"{self.name}" supprime.', ephemeral=True)


# ── Main Setup Command ────────────────────────────────────────────────────────

class SetupTabSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Modele IA", value="model", emoji="🤖"),
            discord.SelectOption(label="Humeur", value="mood", emoji="😊"),
            discord.SelectOption(label="Evenements Twitch", value="twitch", emoji="🎮"),
            discord.SelectOption(label="Noms declencheurs", value="triggers", emoji="📢"),
        ]
        super().__init__(placeholder="Choisir un onglet...", options=options)

    async def callback(self, interaction: discord.Interaction):
        tab = self.values[0]
        if tab == "mood":
            view = MoodView(self.bot)
            state = self.bot.emotion.get_state()
            lines = [f"**{e}**: {v:.2f}" for e, v in state.items()]
            await interaction.response.send_message(
                "**Humeur actuelle:**\n" + "\n".join(lines),
                view=view, ephemeral=True
            )
        elif tab == "twitch":
            view = TwitchEventsView(self.bot)
            lines = [
                f"{'✅' if cfg.active else '❌'} **{name}**: {cfg.message[:50]}..."
                for name, cfg in self.bot.config.twitch_events.items()
            ]
            await interaction.response.send_message(
                "**Evenements Twitch:**\n" + "\n".join(lines),
                view=view, ephemeral=True
            )
        elif tab == "triggers":
            view = TriggerNamesView(self.bot)
            names = ", ".join(self.bot.config.bot.trigger_names)
            await interaction.response.send_message(
                f"**Noms declencheurs:** {names}",
                view=view, ephemeral=True
            )
        elif tab == "model":
            await interaction.response.defer(ephemeral=True, thinking=True)
            await _send_model_tab(self.bot, interaction)


async def _send_model_tab(bot: "WallyDiscord", interaction: discord.Interaction):
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI()
        models_resp = await client.models.list()
        valid_models = sorted(
            [m.id for m in models_resp.data if is_valid_model(m.id)]
        )

        if not valid_models:
            await interaction.followup.send("Aucun modele compatible trouve.", ephemeral=True)
            return

        primary_options = [
            discord.SelectOption(
                label=mid,
                value=mid,
                default=(mid == bot.config.openai.primary_model)
            )
            for mid in valid_models[:25]  # Discord select max 25
        ]
        secondary_options = [
            discord.SelectOption(
                label=mid,
                value=mid,
                default=(mid == bot.config.openai.secondary_model)
            )
            for mid in valid_models[:25]
        ]

        view = ModelSelectView(bot, primary_options, secondary_options)
        await interaction.followup.send(
            f"**Modele actuel:** {bot.config.openai.primary_model}\n"
            f"**Modele secondaire:** {bot.config.openai.secondary_model}",
            view=view, ephemeral=True
        )
    except Exception as e:
        logger.error("Model tab error: {e}", e=e)
        await interaction.followup.send("Erreur lors de la recuperation des modeles.", ephemeral=True)


class PrimaryModelSelect(discord.ui.Select):
    def __init__(self, bot, options):
        super().__init__(placeholder="Modele principal...", options=options)
        self.bot = bot
    async def callback(self, interaction: discord.Interaction):
        self.bot.config.openai.primary_model = self.values[0]
        self.bot.config.save()
        await interaction.response.send_message(f"Modele principal: {self.values[0]}", ephemeral=True)

class SecondaryModelSelect(discord.ui.Select):
    def __init__(self, bot, options):
        super().__init__(placeholder="Modele secondaire...", options=options)
        self.bot = bot
    async def callback(self, interaction: discord.Interaction):
        self.bot.config.openai.secondary_model = self.values[0]
        self.bot.config.save()
        await interaction.response.send_message(f"Modele secondaire: {self.values[0]}", ephemeral=True)

class ModelSelectView(discord.ui.View):
    def __init__(self, bot, primary_options, secondary_options):
        super().__init__(timeout=120)
        self.add_item(PrimaryModelSelect(bot, primary_options))
        self.add_item(SecondaryModelSelect(bot, secondary_options))


class SetupView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=180)
        self.add_item(SetupTabSelect(bot))


class SetupCog(commands.Cog):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot

    @app_commands.command(name="setup", description="Panneau de configuration de Wally (admin)")
    @app_commands.default_member_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        view = SetupView(self.bot)
        await interaction.response.send_message(
            "**Configuration de Wally** — Selectionnez un onglet :",
            view=view,
            ephemeral=True
        )
```

**Commit:** `git add bot/discord/commands/setup.py && git commit -m "feat: add /wally setup with 4 interactive tabs"`

---

### Task 3.8: Wire Discord into main.py

**Files:**
- Modify: `bot/main.py` — add Discord bot wiring

Add to imports and main():
```python
from bot.discord.bot import WallyDiscord

# After core services init:
discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, prompts, language)

# Register on_message handler
@discord_bot.event
async def on_message(message):
    from bot.discord.handlers import handle_message
    await handle_message(discord_bot, message)

# Wire journal send callback
async def journal_send_cb(text: str):
    channel_id = config.bot.journal_channel_id
    if channel_id:
        ch = discord_bot.get_channel(int(channel_id))
        if ch:
            await ch.send(text)

journal.set_send_callback(journal_send_cb)
journal.start()

import os
await asyncio.gather(
    discord_bot.start(os.getenv("DISCORD_TOKEN")),
    # twitch_bot.start() added in Phase 4
)
```

Test: `docker compose up` → verify Discord bot comes online and responds to "wally" mentions.

**Commit:** `git add bot/main.py && git commit -m "feat: wire Discord bot into main.py"`

---

## Phase 4 — Twitch Adapter

### Task 4.1: Twitch Bot class

**Files:**
- Create: `bot/twitch/bot.py`

```python
# bot/twitch/bot.py
from __future__ import annotations
import os
import time
from typing import TYPE_CHECKING
from twitchio.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector

class WallyTwitch(commands.Bot):
    def __init__(
        self,
        config: "Config",
        db: "Database",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        openai: "OpenAIClient",
        prompts: "PromptBuilder",
        language: "LanguageDetector",
    ):
        super().__init__(
            token=os.getenv("TWITCH_BOT_TOKEN", ""),
            client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            nick=os.getenv("TWITCH_BOT_NICK", "wallybot"),
            prefix="!",
            initial_channels=config.twitch.channels,
        )
        self.config = config
        self.db = db
        self.emotion = emotion
        self.memory = memory
        self.openai = openai
        self.prompts = prompts
        self.language = language
        # Per-user cooldown: {user_id: last_response_timestamp}
        self._cooldowns: dict[str, float] = {}

    def is_on_cooldown(self, user_id: str) -> bool:
        last = self._cooldowns.get(user_id, 0)
        return (time.time() - last) < self.config.twitch.cooldown_seconds

    def set_cooldown(self, user_id: str):
        self._cooldowns[user_id] = time.time()

    async def event_ready(self):
        logger.info("Twitch bot ready as {nick}", nick=self.nick)

    async def event_message(self, message):
        if message.echo:
            return
        from bot.twitch.handlers import handle_message
        await handle_message(self, message)

    async def event_error(self, error, data=None):
        logger.error("Twitch error: {e}", e=error)
```

**Commit:** `git add bot/twitch/bot.py && git commit -m "feat: add WallyTwitch Bot class"`

---

### Task 4.2: Twitch message handler

**Files:**
- Create: `bot/twitch/handlers.py`

```python
# bot/twitch/handlers.py
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

async def handle_message(bot: "WallyTwitch", message):
    content = message.content
    content_lower = content.lower()
    author = message.author.name

    # Trigger check
    triggered = f"@{bot.nick.lower()}" in content_lower or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    if not triggered:
        return

    user_id = str(message.author.id or author)
    if bot.is_on_cooldown(user_id):
        return

    try:
        platform = "twitch"
        trust = await bot.db.get_trust_score(platform, user_id)
        lang = bot.language.detect(content)
        mem_context = await bot.memory.search(platform, user_id, content)
        channel_id = f"twitch:{message.channel.name}"
        context_msgs = await bot.memory.get_context_summarized_if_needed(channel_id)

        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            language=lang,
            memory_context=mem_context,
        )
        context_block = bot.prompts.build_context_block(context_msgs)
        user_content = (context_block + f"\n[{author}]: {content}") if context_block else content

        reply = await bot.openai.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_response"
        )

        # Twitch messages max 500 chars
        if len(reply) > 480:
            reply = reply[:477] + "..."

        await message.channel.send(reply)
        bot.set_cooldown(user_id)

        bot.memory.append_message(channel_id, author, content)
        bot.memory.append_message(channel_id, "Wally", reply)

        asyncio.create_task(_post_process(bot, content, platform, user_id, trust))

    except Exception as e:
        logger.error("Twitch message handling error: {e}", e=e)


async def _post_process(bot: "WallyTwitch", text: str, platform: str, user_id: str, trust: float):
    try:
        await bot.emotion.process_message(text, trust_score=trust)
        insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
        if any(w in text.lower() for w in insult_words):
            await bot.db.update_trust_score(platform, user_id, -0.05)
        else:
            await bot.db.update_trust_score(platform, user_id, 0.01)
    except Exception as e:
        logger.error("Twitch post-process error: {e}", e=e)
```

**Commit:** `git add bot/twitch/handlers.py && git commit -m "feat: add Twitch message handler"`

---

### Task 4.3: Twitch events

**Files:**
- Create: `bot/twitch/events.py`

```python
# bot/twitch/events.py
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


def _bits_joy(amount: int) -> float:
    if amount >= 1000:
        return 0.6
    if amount >= 100:
        return 0.3
    return 0.1


async def _generate_and_send(bot: "WallyTwitch", channel_name: str, template: str, **kwargs):
    """Generate an OpenAI response using event template, send to channel."""
    try:
        from bot.core.prompts import PromptBuilder
        formatted = PromptBuilder.format_event_message(template, **kwargs)
        system = bot.prompts.build_system_prompt(bot.emotion.get_state(), bot.config.bot.language_default)
        reply = await bot.openai.complete(
            system,
            [{"role": "user", "content": f"Réagis à cet événement Twitch : {formatted}"}],
            purpose="twitch_event"
        )
        channel = bot.get_channel(channel_name)
        if channel:
            await channel.send(reply[:480])
    except Exception as e:
        logger.error("Twitch event send error: {e}", e=e)


def register_events(bot: "WallyTwitch"):
    """Call once after bot init to register EventSub / PubSub event handlers."""

    @bot.event()
    async def event_follow(follower, channel):
        cfg = bot.config.twitch_events.get("follow")
        if not cfg or not cfg.active:
            return
        bot.emotion.apply_delta("joy", 0.1)
        await _generate_and_send(bot, channel.name, cfg.message, username=follower.name,
                                  amount=0, months=0, raiders_count=0)

    @bot.event()
    async def event_subscription(sub):
        cfg = bot.config.twitch_events.get("sub")
        if not cfg or not cfg.active:
            return
        bot.emotion.apply_delta("joy", 0.4)
        await _generate_and_send(bot, sub.channel.name, cfg.message, username=sub.user.name,
                                  amount=0, months=0, raiders_count=0)

    # Note: twitchio v2 event names may vary; adjust to actual twitchio API
    @bot.event()
    async def event_cheer(cheer):
        cfg = bot.config.twitch_events.get("bits")
        if not cfg or not cfg.active:
            return
        delta = _bits_joy(cheer.bits)
        bot.emotion.apply_delta("joy", delta)
        await _generate_and_send(bot, cheer.channel.name, cfg.message, username=cheer.user.name,
                                  amount=cheer.bits, months=0, raiders_count=0)

    @bot.event()
    async def event_raid(raider, channel, viewers):
        cfg = bot.config.twitch_events.get("raid")
        if not cfg or not cfg.active:
            return
        joy_spike = min(viewers / 50, 0.9)
        bot.emotion.apply_delta("joy", joy_spike)
        await _generate_and_send(bot, channel.name, cfg.message, username=raider.name,
                                  amount=0, months=0, raiders_count=viewers)
```

**Commit:** `git add bot/twitch/events.py && git commit -m "feat: add Twitch event handlers"`

---

### Task 4.4: Wire Twitch into main.py

**Files:**
- Modify: `bot/main.py`

Add Twitch bot construction and gather it alongside Discord:

```python
from bot.twitch.bot import WallyTwitch
from bot.twitch.events import register_events

twitch_bot = WallyTwitch(config, db, emotion, memory, openai_client, prompts, language)
register_events(twitch_bot)

await asyncio.gather(
    discord_bot.start(os.getenv("DISCORD_TOKEN")),
    twitch_bot.start(),
)
```

Test: Connect to Twitch channel, type "wally hello", verify response.

**Commit:** `git add bot/main.py && git commit -m "feat: wire Twitch bot into main.py"`

---

## Phase 5 — Journal

### Task 5.1: Wire journal and full integration test

Journal is already implemented and wired in 3.8. This task verifies it.

**Steps:**
1. Temporarily change `journal_time` in `config.yaml` to 2 minutes from now
2. `docker compose up`
3. Wait for journal to fire
4. Verify message appears in `journal_channel_id` Discord channel
5. Check `logs/wally.log` for "Daily journal sent"
6. Reset `journal_time` to "03:00"

**Commit:** `git add config.yaml && git commit -m "config: restore journal_time to 03:00"`

---

## Phase 6 — README + Final Integration

### Task 6.1: README.md

**Files:**
- Create: `README.md`

Cover: prerequisites (Docker, Discord app, Twitch app, OpenAI key), step-by-step install, full config.yaml reference table, /wally setup guide, troubleshooting (Qdrant not healthy, token refresh, model not found).

### Task 6.2: Full integration test checklist

- [ ] Discord: trigger response works
- [ ] Discord: @mention works
- [ ] Discord: non-trigger message ignored
- [ ] Discord: 🔍 reaction appears and disappears
- [ ] Discord: typing indicator visible during generation
- [ ] Discord: emotion analysis running (check logs)
- [ ] Discord: /wally ask works
- [ ] Discord: /wally status shows cost
- [ ] Discord: /wally mood shows bars
- [ ] Discord: /wally setup opens panel, changes saved to config.yaml
- [ ] Twitch: trigger response works
- [ ] Twitch: cooldown works (second message within 10s ignored)
- [ ] Qdrant: mem0 stores and retrieves user memory
- [ ] Cost: cost_log table populated after responses
- [ ] Journal: fires at configured time

### Task 6.3: Save architecture notes to memory

Update `/root/.claude/projects/-opt-stacks-wally-ai/memory/MEMORY.md` with key patterns.

---

**Plan complete and saved to `docs/plans/2026-03-05-wally-bot-implementation.md`.**
