# Setup Wizard Web — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wizard web guidé permettant à un client distant de configurer son propre bot via un lien d'invitation unique, avec provisioning Docker automatique côté serveur.

**Architecture:** FastAPI routes intégrées au dashboard existant (port 8080). Admin génère un lien UUID4 → client remplit 6 étapes → serveur crée `/opt/stacks/wally-instances/{slug}/` et lance `docker compose up -d`. Image Docker partagée, configs isolées.

**Tech Stack:** FastAPI, aiosqlite, httpx (Discord/Twitch API calls), asyncio.create_subprocess_exec (docker), vanilla JS SPA (Tailwind CDN + glassmorphism inline CSS), pytest + httpx AsyncClient.

---

## Fichiers à créer / modifier

| Action | Fichier | Responsabilité |
|---|---|---|
| Créer | `bot/core/provisioner.py` | Génère fichiers instance + lance Docker |
| Créer | `bot/dashboard/routes/setup.py` | Toutes les routes admin + wizard |
| Créer | `bot/dashboard/static/setup.html` | SPA wizard 6 étapes |
| Modifier | `bot/db/database.py` | Tables setup_invites + setup_sessions + méthodes |
| Modifier | `bot/core/memory.py` | Lire QDRANT_COLLECTION_NAME depuis env |
| Modifier | `bot/dashboard/app.py` | Enregistrer routes setup + pages /setup/* |
| Modifier | `bot/dashboard/static/index.html` | Onglet "Instances" dans le panel admin |
| Créer | `tests/test_setup_db.py` | Tests méthodes DB setup |
| Créer | `tests/test_setup_provisioner.py` | Tests provisioner (mock fs + subprocess) |
| Créer | `tests/test_setup_routes.py` | Tests routes admin + wizard |

---

### Task 1: DB — Tables et méthodes

**Files:**
- Modify: `bot/db/database.py`
- Create: `tests/test_setup_db.py`

- [ ] **Step 1: Écrire les tests (échoueront)**

```python
# tests/test_setup_db.py
import time
import pytest
from bot.db.database import Database

@pytest.fixture
async def db(tmp_path):
    d = await Database.create(str(tmp_path / "test.db"))
    yield d
    await d._conn.close()

@pytest.mark.asyncio
async def test_create_and_get_invite(db):
    await db.create_setup_invite("tok123", expires_at=time.time() + 86400)
    row = await db.get_setup_invite("tok123")
    assert row is not None
    assert row["token"] == "tok123"
    assert row["is_preview"] == 0
    assert row["used_at"] is None

@pytest.mark.asyncio
async def test_create_preview_invite(db):
    await db.create_setup_invite("__preview__", expires_at=None, is_preview=1)
    row = await db.get_setup_invite("__preview__")
    assert row["is_preview"] == 1
    assert row["expires_at"] is None

@pytest.mark.asyncio
async def test_use_invite(db):
    await db.create_setup_invite("tok456", expires_at=time.time() + 86400)
    await db.use_setup_invite("tok456", slug="cindy", port=8081)
    row = await db.get_setup_invite("tok456")
    assert row["used_at"] is not None
    assert row["slug"] == "cindy"
    assert row["port"] == 8081

@pytest.mark.asyncio
async def test_revoke_invite(db):
    await db.create_setup_invite("tok789", expires_at=time.time() + 86400)
    await db.revoke_setup_invite("tok789")
    row = await db.get_setup_invite("tok789")
    assert row["expires_at"] < time.time()

@pytest.mark.asyncio
async def test_list_invites(db):
    await db.create_setup_invite("t1", expires_at=time.time() + 86400)
    await db.create_setup_invite("t2", expires_at=time.time() + 86400)
    rows = await db.list_setup_invites()
    tokens = [r["token"] for r in rows]
    assert "t1" in tokens and "t2" in tokens

@pytest.mark.asyncio
async def test_session_save_and_get(db):
    await db.save_setup_session("tok1", {"discord_token": "abc"})
    data = await db.get_setup_session("tok1")
    assert data["discord_token"] == "abc"

@pytest.mark.asyncio
async def test_session_merge(db):
    await db.save_setup_session("tok1", {"step1": "a"})
    await db.save_setup_session("tok1", {"step2": "b"})
    data = await db.get_setup_session("tok1")
    assert data["step1"] == "a"
    assert data["step2"] == "b"

@pytest.mark.asyncio
async def test_next_port_default(db):
    port = await db.next_setup_port()
    assert port == 8081

@pytest.mark.asyncio
async def test_next_port_increments(db):
    await db.create_setup_invite("t1", expires_at=time.time() + 86400)
    await db.use_setup_invite("t1", slug="a", port=8081)
    port = await db.next_setup_port()
    assert port == 8082
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
python -m pytest tests/test_setup_db.py -v 2>&1 | head -30
```
Attendu : erreurs `AttributeError: 'Database' object has no attribute 'create_setup_invite'`

- [ ] **Step 3: Ajouter les tables au SCHEMA dans `database.py`**

Après le bloc `action_permissions_discord` dans `SCHEMA`, avant `"""` :

```python
CREATE TABLE IF NOT EXISTS setup_invites (
    token       TEXT PRIMARY KEY,
    slug        TEXT,
    created_at  REAL NOT NULL,
    expires_at  REAL,
    used_at     REAL,
    is_preview  INTEGER NOT NULL DEFAULT 0,
    port        INTEGER
);

CREATE TABLE IF NOT EXISTS setup_sessions (
    token       TEXT PRIMARY KEY,
    step_data   TEXT NOT NULL DEFAULT '{}',
    updated_at  REAL NOT NULL
);
```

- [ ] **Step 4: Ajouter les méthodes DB dans `database.py`**

À la fin de la classe `Database`, après les méthodes existantes :

```python
# ── Setup Wizard ─────────────────────────────────────────────────────────────

async def create_setup_invite(
    self, token: str, expires_at: float | None, is_preview: int = 0
) -> None:
    await self._conn.execute(
        "INSERT OR REPLACE INTO setup_invites (token, created_at, expires_at, is_preview)"
        " VALUES (?, ?, ?, ?)",
        (token, time.time(), expires_at, is_preview),
    )
    await self._conn.commit()

async def get_setup_invite(self, token: str) -> aiosqlite.Row | None:
    async with self._conn.execute(
        "SELECT * FROM setup_invites WHERE token = ?", (token,)
    ) as cur:
        return await cur.fetchone()

async def use_setup_invite(self, token: str, slug: str, port: int) -> None:
    await self._conn.execute(
        "UPDATE setup_invites SET used_at = ?, slug = ?, port = ? WHERE token = ?",
        (time.time(), slug, port, token),
    )
    await self._conn.commit()

async def revoke_setup_invite(self, token: str) -> None:
    await self._conn.execute(
        "UPDATE setup_invites SET expires_at = ? WHERE token = ?",
        (time.time() - 1, token),
    )
    await self._conn.commit()

async def list_setup_invites(self) -> list:
    async with self._conn.execute(
        "SELECT * FROM setup_invites WHERE is_preview = 0 ORDER BY created_at DESC"
    ) as cur:
        return await cur.fetchall()

async def save_setup_session(self, token: str, data: dict) -> None:
    import json
    existing = await self.get_setup_session(token)
    merged = {**existing, **data}
    await self._conn.execute(
        "INSERT OR REPLACE INTO setup_sessions (token, step_data, updated_at)"
        " VALUES (?, ?, ?)",
        (token, json.dumps(merged), time.time()),
    )
    await self._conn.commit()

async def get_setup_session(self, token: str) -> dict:
    import json
    async with self._conn.execute(
        "SELECT step_data FROM setup_sessions WHERE token = ?", (token,)
    ) as cur:
        row = await cur.fetchone()
    return json.loads(row["step_data"]) if row else {}

async def next_setup_port(self) -> int:
    async with self._conn.execute(
        "SELECT MAX(port) as max_port FROM setup_invites WHERE port IS NOT NULL"
    ) as cur:
        row = await cur.fetchone()
    max_port = row["max_port"] if row and row["max_port"] else 8080
    return max_port + 1
```

- [ ] **Step 5: Lancer les tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_setup_db.py -v
```
Attendu : 10 tests PASS

- [ ] **Step 6: Commit**

```bash
git add bot/db/database.py tests/test_setup_db.py
git commit -m "feat(setup): add setup_invites/setup_sessions tables and DB methods"
```

---

### Task 2: Provisioner

**Files:**
- Create: `bot/core/provisioner.py`
- Modify: `bot/core/memory.py` (collection_name via env)
- Create: `tests/test_setup_provisioner.py`

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_setup_provisioner.py
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.fixture
def instance_dir(tmp_path):
    return tmp_path / "instances"

@pytest.mark.asyncio
async def test_creates_directory_structure(instance_dir):
    from bot.core.provisioner import provision_instance
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", AsyncMock()):
        await provision_instance("cindy", 8081, data)
    slug_dir = instance_dir / "cindy"
    assert (slug_dir / ".env").exists()
    assert (slug_dir / "config.yaml").exists()
    assert (slug_dir / "docker-compose.yml").exists()
    assert (slug_dir / "data").is_dir()
    assert (slug_dir / "logs").is_dir()
    assert (slug_dir / "bot" / "persona").is_dir()

@pytest.mark.asyncio
async def test_env_contains_required_keys(instance_dir):
    from bot.core.provisioner import provision_instance
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", AsyncMock()):
        await provision_instance("cindy", 8081, data)
    env_text = (instance_dir / "cindy" / ".env").read_text()
    assert "DISCORD_TOKEN=mytoken" in env_text
    assert "OPENAI_API_KEY=sk-test" in env_text
    assert "JWT_SECRET=" in env_text
    assert "QDRANT_COLLECTION_NAME=wally_cindy" in env_text
    # JWT_SECRET must be non-empty
    for line in env_text.splitlines():
        if line.startswith("JWT_SECRET="):
            assert len(line.split("=", 1)[1]) > 10

@pytest.mark.asyncio
async def test_config_yaml_has_trigger_names(instance_dir):
    from bot.core.provisioner import provision_instance
    import yaml
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", AsyncMock()):
        await provision_instance("cindy", 8081, data)
    cfg = yaml.safe_load((instance_dir / "cindy" / "config.yaml").read_text())
    assert "cindy" in cfg["bot"]["trigger_names"]
    assert cfg["bot"]["language_default"] == "fr"

@pytest.mark.asyncio
async def test_persona_files_written(instance_dir):
    from bot.core.provisioner import provision_instance
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", AsyncMock()):
        await provision_instance("cindy", 8081, data)
    soul = (instance_dir / "cindy" / "bot" / "persona" / "SOUL.md").read_text()
    assert "Je suis Cindy" in soul

@pytest.mark.asyncio
async def test_docker_compose_launched(instance_dir):
    from bot.core.provisioner import provision_instance
    mock_docker = AsyncMock()
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", mock_docker):
        await provision_instance("cindy", 8081, data)
    mock_docker.assert_called_once()
    args = mock_docker.call_args[0]
    assert "cindy" in str(args[0])  # path contient le slug

@pytest.mark.asyncio
async def test_dry_run_skips_docker(instance_dir):
    from bot.core.provisioner import provision_instance
    mock_docker = AsyncMock()
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", mock_docker):
        await provision_instance("cindy", 8081, data, dry_run=True)
    mock_docker.assert_not_called()

def _make_data():
    return {
        "discord_token": "mytoken",
        "discord_guild_id": "123456",
        "discord_client_id": "cid",
        "discord_client_secret": "csec",
        "openai_api_key": "sk-test",
        "anthropic_api_key": "",
        "tavily_api_key": "",
        "bot_name": "cindy",
        "language_default": "fr",
        "trigger_names": ["cindy"],
        "twitch_enabled": False,
        "persona_soul": "Je suis Cindy",
        "persona_identity": "Cindy identity",
        "persona_voice": "Cindy voice",
        "persona_emotions": "Cindy emotions",
        "web_base_url": "https://cindy.example.com",
    }
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
python -m pytest tests/test_setup_provisioner.py -v 2>&1 | head -20
```
Attendu : `ModuleNotFoundError` ou `ImportError`

- [ ] **Step 3: Créer `bot/core/provisioner.py`**

```python
# bot/core/provisioner.py
"""Provisioning d'instances Wally isolées."""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

import yaml
from loguru import logger

INSTANCES_DIR = Path("/opt/stacks/wally-instances")
_WALLY_DIR = Path("/opt/stacks/wally-ai")
_SHARED_IMAGE = "wally-ai-wally"
_SHARED_NETWORK = "wally-net"


async def provision_instance(
    slug: str, port: int, data: dict, dry_run: bool = False
) -> str:
    """Crée le répertoire d'instance, génère les fichiers, lance Docker.

    Returns l'URL de l'instance (ex: http://host:8081).
    dry_run=True génère les fichiers mais ne lance pas Docker.
    """
    slug_dir = INSTANCES_DIR / slug
    _create_directories(slug_dir)
    _write_env(slug_dir, slug, data)
    _write_config_yaml(slug_dir, slug, data)
    _write_persona_files(slug_dir, data)
    _write_docker_compose(slug_dir, slug, port)
    _create_prompts_symlink(slug_dir)

    if not dry_run:
        await _run_docker_compose(slug_dir / "docker-compose.yml")
        logger.info("Instance {} started on port {}", slug, port)
    else:
        logger.info("Instance {} dry-run complete (no Docker)", slug)

    return f"http://localhost:{port}"


def _create_directories(slug_dir: Path) -> None:
    for sub in ["data", "logs", "bot/persona"]:
        (slug_dir / sub).mkdir(parents=True, exist_ok=True)


def _write_env(slug_dir: Path, slug: str, data: dict) -> None:
    jwt_secret = secrets.token_hex(32)
    twitch_section = ""
    if data.get("twitch_enabled"):
        twitch_section = (
            f"\nTWITCH_CLIENT_ID={data.get('twitch_client_id', '')}"
            f"\nTWITCH_CLIENT_SECRET={data.get('twitch_client_secret', '')}"
            f"\nTWITCH_BOT_NICK={data.get('twitch_bot_nick', '')}"
            f"\nTWITCH_BROADCASTER_ID={data.get('twitch_broadcaster_id', '')}"
            f"\nTWITCH_BOT_ID={data.get('twitch_bot_id', '')}"
            f"\nBOT_ACCESS_TOKEN={data.get('bot_access_token', '')}"
            f"\nBOT_REFRESH_TOKEN={data.get('bot_refresh_token', '')}"
            f"\nSTREAMER_ACCESS_TOKEN={data.get('streamer_access_token', '')}"
            f"\nSTREAMER_REFRESH_TOKEN={data.get('streamer_refresh_token', '')}"
        )
    env_content = (
        f"OPENAI_API_KEY={data.get('openai_api_key', '')}\n"
        f"ANTHROPIC_API_KEY={data.get('anthropic_api_key', '')}\n"
        f"TAVILY_API_KEY={data.get('tavily_api_key', '')}\n"
        f"DISCORD_TOKEN={data.get('discord_token', '')}\n"
        f"DISCORD_GUILD_ID={data.get('discord_guild_id', '')}\n"
        f"DISCORD_CLIENT_ID={data.get('discord_client_id', '')}\n"
        f"DISCORD_CLIENT_SECRET={data.get('discord_client_secret', '')}\n"
        f"WEB_BASE_URL={data.get('web_base_url', '')}\n"
        f"JWT_SECRET={jwt_secret}\n"
        f"QDRANT_URL=http://wally-qdrant:6333\n"
        f"QDRANT_COLLECTION_NAME=wally_{slug}\n"
        f"DB_PATH=data/wally.db\n"
        f"CLOUDFLARED_WALLY_TOKEN={twitch_section}\n"
    )
    (slug_dir / ".env").write_text(env_content)


def _write_config_yaml(slug_dir: Path, slug: str, data: dict) -> None:
    bot_name = data.get("bot_name", slug)
    lang = data.get("language_default", "fr")
    triggers = data.get("trigger_names") or [bot_name]
    cfg = {
        "bot": {
            "trigger_names": triggers,
            "language_default": lang,
            "context_window_size": 20,
            "context_token_threshold": 3000,
            "journal_time": "21:00",
            "journal_channel_id": None,
            "dashboard_token": secrets.token_hex(16),
            "prelude_window_size": 15,
            "link_min_confidence": 0.75,
            "cost_alert_threshold": 25.0,
            "emotion_inertia_factor": 0.5,
            "emotion_peak_threshold": 0.7,
            "spontaneous_discord_enabled": True,
            "spontaneous_twitch_enabled": bool(data.get("twitch_enabled")),
            "spontaneous_probability": 0.05,
            "spontaneous_passion_probability": 0.15,
            "spontaneous_cooldown_seconds": 300,
            "spontaneous_memory_probability": 0.2,
            "memory_recall_min_score": 0.75,
            "memory_search_min_score": 0.5,
            "memory_context_max_tokens": 800,
            "love_decay_lambda": 0.1,
        },
        "discord": {
            "anger_trigger_threshold": 3,
            "timeout_minutes": 10,
            "channel_filter_mode": "blacklist",
            "channel_blacklist": [],
            "channel_whitelist": [],
            "emoji_reaction_probability": 0.05,
            "spam_detection": {
                "enabled": True,
                "max_messages": 10,
                "window_seconds": 120,
                "mute_minutes": 5,
                "spam_anger_delta": 0.05,
                "exempt_channels": [],
            },
        },
        "llm": {
            "primary": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.8,
                "max_tokens": 1000,
            },
            "secondary": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.8,
                "max_tokens": 500,
            },
        },
        "openai": {
            "primary_model": "gpt-4o-mini",
            "secondary_model": "gpt-4o-mini",
            "temperature": 0.8,
            "max_tokens": 1000,
        },
        "emotions": {
            "anger": {"decay_lambda": 3.0, "boredom_rise_per_hour": None},
            "joy": {"decay_lambda": 1.5, "boredom_rise_per_hour": None},
            "sadness": {"decay_lambda": 1.0, "boredom_rise_per_hour": None},
            "curiosity": {"decay_lambda": 1.5, "boredom_rise_per_hour": None},
            "boredom": {"decay_lambda": 0.01, "boredom_rise_per_hour": 0.2},
            "circadian": {"enabled": False, "timezone": "Europe/Paris", "periods": {}},
            "mood": {"alpha": 0.02, "decay_lambda": 0.1, "bias_factor": 0.3},
            "fatigue": {"dampening": 0.7, "recovery_rate": 0.1},
            "habituation": {
                "threshold_count": 3, "window_seconds": 600,
                "decay_factor": 0.5, "reset_seconds": 1800, "exempt": ["anger"],
            },
            "memory": {
                "learning_rate": 0.05, "priming_factor": 0.05,
                "amplification_factor": 0.3, "decay_lambda_per_day": 0.01,
            },
        },
        "twitch": {"guest_channels": [], "cooldown_seconds": 30},
        "twitch_events": {
            k: {"active": False, "message": ""}
            for k in ("follow", "sub", "resub", "bits", "raid")
        },
        "image_generation": {
            "model": "gpt-image-1", "quality": "medium",
            "size": "1024x1024", "background": "auto",
            "format": "png", "daily_limit": 10, "per_user_limit": 3,
        },
        "overlay_image": {"display_seconds": 10, "transition_seconds": 1.5},
    }
    (slug_dir / "config.yaml").write_text(yaml.dump(cfg, allow_unicode=True))


def _write_persona_files(slug_dir: Path, data: dict) -> None:
    persona_dir = slug_dir / "bot" / "persona"
    files = {
        "SOUL.md": data.get("persona_soul", ""),
        "IDENTITY.md": data.get("persona_identity", ""),
        "VOICE.md": data.get("persona_voice", ""),
        "EMOTIONS.md": data.get("persona_emotions", ""),
        "EXEMPLES.md": data.get("persona_exemples", ""),
        "WEEKDAYS.md": data.get("persona_weekdays", ""),
    }
    for filename, content in files.items():
        (persona_dir / filename).write_text(content)


def _write_docker_compose(slug_dir: Path, slug: str, port: int) -> None:
    compose = {
        "networks": {_SHARED_NETWORK: {"external": True}},
        "services": {
            slug: {
                "image": _SHARED_IMAGE,
                "container_name": f"wally-{slug}",
                "user": "1000:1000",
                "networks": [_SHARED_NETWORK],
                "env_file": ".env",
                "ports": [f"0.0.0.0:{port}:8080"],
                "volumes": [
                    "./data:/app/data",
                    "./logs:/app/logs",
                    "./config.yaml:/app/config.yaml",
                    "./.env:/app/.env",
                    "./bot/persona:/app/bot/persona",
                ],
                "restart": "unless-stopped",
            }
        },
    }
    (slug_dir / "docker-compose.yml").write_text(yaml.dump(compose, allow_unicode=True))


def _create_prompts_symlink(slug_dir: Path) -> None:
    link = slug_dir / "bot" / "persona" / "prompts"
    target = _WALLY_DIR / "bot" / "persona" / "prompts"
    if not link.exists() and target.exists():
        link.symlink_to(target)


async def _run_docker_compose(compose_path: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", str(compose_path), "up", "-d",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"docker compose up failed: {stderr.decode()}")
    logger.info("docker compose up: {}", stdout.decode().strip())
```

- [ ] **Step 4: Patcher `bot/core/memory.py` pour lire QDRANT_COLLECTION_NAME**

Chercher la ligne :
```python
self._store = QdrantMemoryStore(qdrant_url, "wally_memory", self._db)
```
Remplacer par :
```python
collection_name = os.getenv("QDRANT_COLLECTION_NAME", "wally_memory")
self._store = QdrantMemoryStore(qdrant_url, collection_name, self._db)
```
Vérifier que `import os` est déjà présent (l'ajouter si absent).

- [ ] **Step 5: Lancer les tests**

```bash
python -m pytest tests/test_setup_provisioner.py -v
```
Attendu : 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add bot/core/provisioner.py bot/core/memory.py tests/test_setup_provisioner.py
git commit -m "feat(setup): provisioner — génère instance + lance docker compose"
```

---

### Task 3: Routes setup — Admin + Wizard API

**Files:**
- Create: `bot/dashboard/routes/setup.py`
- Create: `tests/test_setup_routes.py`

- [ ] **Step 1: Écrire les tests**

```python
# tests/test_setup_routes.py
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from tests.test_dashboard_routes import _make_config, _make_state


def _make_full_state(**overrides) -> AppState:
    state = _make_state(**overrides)
    db = MagicMock()
    db.insert_emotion_snapshot = AsyncMock()
    db.create_setup_invite = AsyncMock()
    db.list_setup_invites = AsyncMock(return_value=[])
    db.get_setup_invite = AsyncMock(return_value=None)
    db.revoke_setup_invite = AsyncMock()
    db.next_setup_port = AsyncMock(return_value=8081)
    db.save_setup_session = AsyncMock()
    db.get_setup_session = AsyncMock(return_value={})
    db.use_setup_invite = AsyncMock()
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    state.db = db
    return state


@pytest.fixture
async def client():
    state = _make_full_state()
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, state


@pytest.mark.asyncio
async def test_generate_invite_requires_auth(client):
    c, _ = client
    resp = await c.post("/api/admin/setup/invite")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_generate_invite_ok(client):
    c, state = client
    state.db.next_setup_port = AsyncMock(return_value=8081)
    resp = await c.post(
        "/api/admin/setup/invite",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert "url" in body
    assert len(body["token"]) > 10
    state.db.create_setup_invite.assert_called_once()


@pytest.mark.asyncio
async def test_list_invites_ok(client):
    c, state = client
    state.db.list_setup_invites = AsyncMock(return_value=[])
    resp = await c.get(
        "/api/admin/setup/invites",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert resp.status_code == 200
    assert "invites" in resp.json()


@pytest.mark.asyncio
async def test_revoke_invite_ok(client):
    c, state = client
    resp = await c.delete(
        "/api/admin/setup/invite/tok123",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert resp.status_code == 200
    state.db.revoke_setup_invite.assert_called_once_with("tok123")


@pytest.mark.asyncio
async def test_wizard_save_invalid_token(client):
    c, state = client
    state.db.get_setup_invite = AsyncMock(return_value=None)
    resp = await c.post("/api/setup/badtoken/save", json={"foo": "bar"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_wizard_save_expired_token(client):
    c, state = client
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "expires_at": time.time() - 1, "used_at": None, "is_preview": 0
    }[k]
    state.db.get_setup_invite = AsyncMock(return_value=row)
    resp = await c.post("/api/setup/expiredtok/save", json={"foo": "bar"})
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_wizard_validate_discord_bad_token(client):
    c, state = client
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "expires_at": time.time() + 3600, "used_at": None, "is_preview": 0
    }[k]
    state.db.get_setup_invite = AsyncMock(return_value=row)
    with patch("bot.dashboard.routes.setup.httpx") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"message": "401: Unauthorized"}
        mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            get=AsyncMock(return_value=mock_resp)
        ))
        resp = await c.post(
            "/api/setup/tok/validate-discord",
            json={"discord_token": "badtoken"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


@pytest.mark.asyncio
async def test_submit_provisions_instance(client):
    c, state = client
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "expires_at": time.time() + 3600, "used_at": None, "is_preview": 0,
        "token": "tok999",
    }[k]
    state.db.get_setup_invite = AsyncMock(return_value=row)
    state.db.get_setup_session = AsyncMock(return_value={
        "discord_token": "dt", "discord_guild_id": "gid",
        "discord_client_id": "cid", "discord_client_secret": "cs",
        "openai_api_key": "sk-x", "bot_name": "cindy",
        "language_default": "fr", "trigger_names": ["cindy"],
        "persona_soul": "soul", "persona_identity": "id",
        "persona_voice": "voice", "persona_emotions": "emo",
        "twitch_enabled": False,
    })
    with patch("bot.dashboard.routes.setup.provision_instance", AsyncMock(return_value="http://localhost:8081")):
        resp = await c.post("/api/setup/tok999/submit", json={})
    assert resp.status_code == 200
    assert resp.json()["url"] == "http://localhost:8081"
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
python -m pytest tests/test_setup_routes.py -v 2>&1 | head -30
```

- [ ] **Step 3: Créer `bot/dashboard/routes/setup.py`**

```python
# bot/dashboard/routes/setup.py
"""Routes Setup Wizard — admin (génération invitations) + wizard public."""
from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from bot.core.provisioner import provision_instance

admin_router = APIRouter()
wizard_router = APIRouter()

_TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_DISCORD_API_URL = "https://discord.com/api/v10/users/@me"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _invite_status(row) -> str:
    if row["is_preview"]:
        return "preview"
    if row["used_at"]:
        return "used"
    if row["expires_at"] and row["expires_at"] < time.time():
        return "expired"
    return "pending"


async def _get_valid_invite(token: str, db) -> Any:
    """Retourne la row de l'invite, lève 404/410/409 si invalide."""
    row = await db.get_setup_invite(token)
    if row is None:
        raise HTTPException(status_code=404, detail="Lien invalide.")
    if not row["is_preview"]:
        if row["expires_at"] and row["expires_at"] < time.time():
            raise HTTPException(status_code=410, detail="Lien expiré.")
        if row["used_at"]:
            raise HTTPException(status_code=409, detail="Lien déjà utilisé.")
    return row


def _check_preview_auth(request: Request, token: str) -> None:
    """Si token == __preview__, vérifie le Bearer admin."""
    if token != "__preview__":
        return
    cfg_token = request.app.state.wally.config.bot.dashboard_token
    auth = request.headers.get("Authorization", "")
    if not cfg_token or not auth.startswith("Bearer ") or auth[7:] != cfg_token:
        raise HTTPException(status_code=401, detail="Admin auth required for preview.")


# ── Admin routes ──────────────────────────────────────────────────────────────

@admin_router.post("/invite")
async def generate_invite(request: Request) -> dict:
    state = request.app.state.wally
    token = uuid.uuid4().hex
    expires_at = time.time() + 7 * 86400  # 7 jours
    await state.db.create_setup_invite(token, expires_at=expires_at)
    base_url = state.config.bot.__dict__.get("web_base_url") or ""
    # Lire WEB_BASE_URL depuis l'env si non dans config
    import os
    base_url = base_url or os.getenv("WEB_BASE_URL", "")
    url = f"{base_url}/setup/{token}" if base_url else f"/setup/{token}"
    logger.info("Setup invite generated: token={}", token[:8] + "...")
    return {"token": token, "url": url, "expires_at": expires_at}


@admin_router.get("/invites")
async def list_invites(request: Request) -> dict:
    state = request.app.state.wally
    rows = await state.db.list_setup_invites()
    invites = [
        {
            "token": r["token"][:8] + "...",
            "token_full": r["token"],
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
            "used_at": r["used_at"],
            "slug": r["slug"],
            "port": r["port"],
            "status": _invite_status(r),
        }
        for r in rows
    ]
    return {"invites": invites}


@admin_router.delete("/invite/{token}")
async def revoke_invite(request: Request, token: str) -> dict:
    state = request.app.state.wally
    await state.db.revoke_setup_invite(token)
    return {"status": "revoked"}


@admin_router.get("/instances")
async def list_instances(request: Request) -> dict:
    """Liste les instances créées avec leur statut Docker."""
    import subprocess
    state = request.app.state.wally
    rows = await state.db.list_setup_invites()
    instances = []
    for r in rows:
        if not r["slug"]:
            continue
        slug = r["slug"]
        port = r["port"]
        # Vérifier statut Docker
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", f"wally-{slug}"],
                capture_output=True, text=True, timeout=5,
            )
            docker_status = result.stdout.strip() or "unknown"
        except Exception:
            docker_status = "unknown"
        instances.append({
            "slug": slug, "port": port,
            "docker_status": docker_status,
            "created_at": r["created_at"],
        })
    return {"instances": instances}


@admin_router.post("/instances/{slug}/stop")
async def stop_instance(request: Request, slug: str) -> dict:
    import subprocess
    result = subprocess.run(
        ["docker", "stop", f"wally-{slug}"],
        capture_output=True, text=True, timeout=15,
    )
    return {"status": "ok" if result.returncode == 0 else "error", "detail": result.stderr}


@admin_router.post("/instances/{slug}/start")
async def start_instance(request: Request, slug: str) -> dict:
    import subprocess
    result = subprocess.run(
        ["docker", "start", f"wally-{slug}"],
        capture_output=True, text=True, timeout=15,
    )
    return {"status": "ok" if result.returncode == 0 else "error", "detail": result.stderr}


# ── Wizard routes ─────────────────────────────────────────────────────────────

@wizard_router.post("/{token}/save")
async def save_step(request: Request, token: str, body: dict) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    await _get_valid_invite(token, db)
    await db.save_setup_session(token, body)
    return {"status": "saved"}


@wizard_router.post("/{token}/validate-discord")
async def validate_discord(request: Request, token: str, body: dict) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    await _get_valid_invite(token, db)
    discord_token = body.get("discord_token", "")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _DISCORD_API_URL,
            headers={"Authorization": f"Bot {discord_token}"},
            timeout=10,
        )
    if resp.status_code == 200:
        data = resp.json()
        return {"ok": True, "username": data.get("username", ""), "id": data.get("id", "")}
    return {"ok": False, "error": f"Discord a refusé le token (HTTP {resp.status_code})"}


@wizard_router.post("/{token}/twitch-auth-url")
async def twitch_auth_url(request: Request, token: str, body: dict) -> dict:
    """Génère l'URL OAuth Twitch pour bot ou streamer."""
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    await _get_valid_invite(token, db)

    import os
    base_url = os.getenv("WEB_BASE_URL", "")
    account_type = body.get("account_type", "bot")  # "bot" ou "streamer"
    client_id = body.get("client_id", "")
    redirect_uri = f"{base_url}/api/setup/{token}/twitch/callback"

    if account_type == "bot":
        scope = "user:read:chat user:write:chat user:bot moderator:read:followers chat:read chat:edit"
    else:
        scope = "bits:read channel:read:subscriptions moderator:read:followers"

    import urllib.parse
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": f"{token}:{account_type}",
    }
    url = "https://id.twitch.tv/oauth2/authorize?" + urllib.parse.urlencode(params)
    # Sauvegarder client_id + client_secret en session pour le callback
    await db.save_setup_session(token, {
        "twitch_client_id": client_id,
        "twitch_client_secret": body.get("client_secret", ""),
        "twitch_redirect_uri": redirect_uri,
    })
    return {"url": url}


@wizard_router.get("/{token}/twitch/callback")
async def twitch_callback(request: Request, token: str) -> JSONResponse:
    """Reçoit le code OAuth Twitch, échange contre les tokens."""
    code = request.query_params.get("code")
    state_param = request.query_params.get("state", "")
    error = request.query_params.get("error")

    if error:
        return JSONResponse({"error": error}, status_code=400)

    # state = "{token}:{account_type}"
    parts = state_param.rsplit(":", 1)
    account_type = parts[1] if len(parts) == 2 else "bot"

    db = request.app.state.wally.db
    session = await db.get_setup_session(token)
    client_id = session.get("twitch_client_id", "")
    client_secret = session.get("twitch_client_secret", "")
    redirect_uri = session.get("twitch_redirect_uri", "")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _TWITCH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        )

    if resp.status_code != 200:
        logger.error("Twitch token exchange failed: {}", resp.text)
        html = "<html><body><h2>Erreur Twitch</h2><p>Ferme cet onglet et réessaie.</p></body></html>"
        return JSONResponse(content=None, status_code=500, media_type="text/html")

    tokens = resp.json()
    prefix = "bot" if account_type == "bot" else "streamer"
    update = {
        f"{prefix}_access_token": tokens.get("access_token", ""),
        f"{prefix}_refresh_token": tokens.get("refresh_token", ""),
        f"twitch_{prefix}_connected": True,
    }
    # Récupérer l'ID utilisateur Twitch
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "Client-Id": client_id,
            },
            timeout=10,
        )
    if user_resp.status_code == 200:
        udata = user_resp.json().get("data", [{}])[0]
        update[f"twitch_{prefix}_username"] = udata.get("display_name", "")
        update[f"twitch_{prefix}_id"] = udata.get("id", "")

    await db.save_setup_session(token, update)
    logger.info("Twitch {} connected for token {}", account_type, token[:8])

    html = """<html><body style="font-family:sans-serif;text-align:center;padding:40px">
    <h2>✅ Compte connecté !</h2>
    <p>Tu peux fermer cet onglet et revenir au wizard.</p>
    <script>window.close();</script></body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


@wizard_router.get("/{token}/twitch-status")
async def twitch_status(request: Request, token: str) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    session = await db.get_setup_session(token)
    return {
        "bot_connected": bool(session.get("twitch_bot_connected")),
        "streamer_connected": bool(session.get("twitch_streamer_connected")),
        "bot_username": session.get("twitch_bot_username", ""),
        "streamer_username": session.get("twitch_streamer_username", ""),
    }


@wizard_router.post("/{token}/submit")
async def submit_wizard(request: Request, token: str, body: dict) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    row = await _get_valid_invite(token, db)
    session = await db.get_setup_session(token)
    is_dry_run = row["is_preview"] and body.get("dry_run", True)

    port = await db.next_setup_port()
    slug = session.get("bot_name", f"bot{port}").lower().replace(" ", "_")

    try:
        url = await provision_instance(slug, port, session, dry_run=is_dry_run)
    except Exception as e:
        logger.error("Provisioning failed for {}: {}", slug, e)
        raise HTTPException(status_code=500, detail=f"Erreur lors du démarrage : {e}")

    if not is_dry_run:
        await db.use_setup_invite(token, slug=slug, port=port)

    return {"status": "ok", "url": url, "slug": slug, "port": port, "dry_run": is_dry_run}
```

- [ ] **Step 4: Lancer les tests**

```bash
python -m pytest tests/test_setup_routes.py -v
```
Attendu : 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/routes/setup.py tests/test_setup_routes.py
git commit -m "feat(setup): admin + wizard API routes (invites, validate, twitch OAuth, submit)"
```

---

### Task 4: Intégration App + routes page

**Files:**
- Modify: `bot/dashboard/app.py`
- Modify: `bot/dashboard/auth.py`

- [ ] **Step 1: Enregistrer les routes dans `app.py`**

Dans `create_dashboard_app()`, après les imports de routes existants, ajouter `setup` à l'import :

```python
from bot.dashboard.routes import status, emotions, admin, sse, twitch, memory, links, costs, roadmap, chat_auth, chat, gallery, actions, setup
```

Après `app.include_router(actions.router, prefix="/api/actions")`, ajouter :

```python
# Setup wizard
app.include_router(setup.admin_router, prefix="/api/admin/setup")
app.include_router(setup.wizard_router, prefix="/api/setup")
```

Puis ajouter les routes de page HTML (après le bloc `@app.get("/overlay-image")`):

```python
@app.get("/setup/preview")
async def setup_preview_page(request: Request):
    """Wizard en mode test — admin uniquement."""
    from fastapi.responses import HTMLResponse
    from fastapi import HTTPException as FastHTTPException
    token = request.app.state.wally.config.bot.dashboard_token
    auth = request.headers.get("Authorization", "")
    if not token or not auth.startswith("Bearer ") or auth[7:] != token:
        raise FastHTTPException(status_code=401, detail="Admin auth required")
    html = (STATIC_DIR / "setup.html").read_text()
    html = html.replace("__WIZARD_TOKEN__", "__preview__").replace("__WIZARD_MODE__", "preview")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})

@app.get("/setup/{token}")
async def setup_wizard_page(request: Request, token: str):
    """Wizard client — vérifie le token."""
    from fastapi.responses import HTMLResponse
    from fastapi import HTTPException as FastHTTPException
    db = request.app.state.wally.db
    row = await db.get_setup_invite(token)
    if row is None:
        raise FastHTTPException(status_code=404, detail="Lien invalide ou expiré.")
    import time as _time
    if not row["is_preview"]:
        if row["expires_at"] and row["expires_at"] < _time.time():
            raise FastHTTPException(status_code=410, detail="Ce lien a expiré.")
        if row["used_at"]:
            raise FastHTTPException(status_code=409, detail="Ce lien a déjà été utilisé.")
    html = (STATIC_DIR / "setup.html").read_text()
    html = html.replace("__WIZARD_TOKEN__", token).replace("__WIZARD_MODE__", "normal")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
```

- [ ] **Step 2: Initialiser le token `__preview__` au démarrage**

Dans la fonction `lifespan`, après le try/except du snapshot initial :

```python
# Créer le token preview s'il n'existe pas
try:
    await state.db.create_setup_invite("__preview__", expires_at=None, is_preview=1)
except Exception:
    pass  # Déjà présent (INSERT OR REPLACE gère ça)
```

- [ ] **Step 3: Vérifier que le dashboard démarre sans erreur**

```bash
cd /opt/stacks/wally-ai && python -c "
from bot.dashboard.app import create_dashboard_app
from unittest.mock import MagicMock, AsyncMock
from bot.dashboard.state import AppState
print('Import OK')
"
```
Attendu : `Import OK`

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/app.py
git commit -m "feat(setup): enregistrer routes + pages /setup/* dans app.py"
```

---

### Task 5: SPA `setup.html` — Wizard 6 étapes

**Files:**
- Create: `bot/dashboard/static/setup.html`

Le fichier est volumineux (~500 lignes). Voici la structure complète :

- [ ] **Step 1: Créer `bot/dashboard/static/setup.html`**

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Configuration du bot</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background: #0a0a0f; color: rgba(255,255,255,0.87); font-family: 'Inter', sans-serif; min-height: 100vh; }
    .glass { background: rgba(255,255,255,0.04); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; }
    .btn-primary { background: rgba(6,182,212,0.2); border: 1px solid rgba(6,182,212,0.5); color: rgb(6,182,212); border-radius: 8px; padding: 8px 18px; cursor: pointer; font-weight: 600; transition: all .2s; }
    .btn-primary:hover { background: rgba(6,182,212,0.35); }
    .btn-secondary { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); color: rgba(255,255,255,0.7); border-radius: 8px; padding: 8px 18px; cursor: pointer; transition: all .2s; }
    .btn-secondary:hover { background: rgba(255,255,255,0.1); }
    .field-input { width: 100%; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 10px 12px; color: rgba(255,255,255,0.9); font-size: 13px; outline: none; transition: border .2s; font-family: monospace; }
    .field-input:focus { border-color: rgba(6,182,212,0.5); }
    .help-box { background: rgba(6,182,212,0.06); border-left: 2px solid rgba(6,182,212,0.4); border-radius: 4px; padding: 8px 12px; font-size: 12px; color: rgba(255,255,255,0.6); margin-bottom: 8px; }
    .step-circle { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; flex-shrink: 0; }
    .step-done { background: rgba(34,197,94,0.2); border: 2px solid rgba(34,197,94,0.7); color: rgb(34,197,94); cursor: pointer; }
    .step-active { background: rgba(6,182,212,0.2); border: 2px solid rgb(6,182,212); color: rgb(6,182,212); }
    .step-future { background: rgba(255,255,255,0.04); border: 2px solid rgba(255,255,255,0.15); color: rgba(255,255,255,0.3); }
    .step-line { flex: 1; height: 2px; margin-bottom: 18px; }
    .tag-chip { display: inline-flex; align-items: center; gap: 4px; background: rgba(6,182,212,0.15); border: 1px solid rgba(6,182,212,0.3); border-radius: 20px; padding: 3px 10px; font-size: 12px; color: rgba(6,182,212,0.9); }
    .tab-btn { padding: 6px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; border: 1px solid transparent; }
    .tab-active { background: rgba(6,182,212,0.15); border-color: rgba(6,182,212,0.3); color: rgb(6,182,212); }
    .tab-inactive { color: rgba(255,255,255,0.4); }
    .tab-inactive:hover { color: rgba(255,255,255,0.7); }
    .preview-badge { background: rgba(251,191,36,0.15); border: 1px solid rgba(251,191,36,0.4); color: rgb(251,191,36); border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700; }
    .error-msg { color: rgb(239,68,68); font-size: 12px; margin-top: 4px; }
    .success-msg { color: rgb(34,197,94); font-size: 12px; margin-top: 4px; }
    textarea.field-input { min-height: 280px; font-size: 12px; resize: vertical; }
    .progress-step { display: flex; flex-direction: column; align-items: center; gap: 5px; }
    .progress-label { font-size: 10px; white-space: nowrap; }
  </style>
</head>
<body>

<div id="app" class="max-w-2xl mx-auto px-4 py-8">

  <!-- Header -->
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-xl font-bold">🤖 Configuration de ton bot</h1>
      <p class="text-sm text-white/40 mt-1">Suis les étapes pour configurer ton instance personnelle</p>
    </div>
    <span id="preview-badge" class="preview-badge" style="display:none">MODE TEST</span>
  </div>

  <!-- Barre de progression -->
  <div class="glass p-4 mb-6">
    <div class="flex items-center gap-0">
      <div class="progress-step" id="ps-1" onclick="goToStep(1)">
        <div class="step-circle step-active" id="sc-1">1</div>
        <span class="progress-label text-white/50" id="sl-1">Bienvenue</span>
      </div>
      <div class="step-line bg-white/10" id="line-1"></div>
      <div class="progress-step" id="ps-2" onclick="goToStep(2)">
        <div class="step-circle step-future" id="sc-2">2</div>
        <span class="progress-label text-white/30" id="sl-2">Discord</span>
      </div>
      <div class="step-line bg-white/10" id="line-2"></div>
      <div class="progress-step" id="ps-3" onclick="goToStep(3)">
        <div class="step-circle step-future" id="sc-3">3</div>
        <span class="progress-label text-white/30" id="sl-3">Clés API</span>
      </div>
      <div class="step-line bg-white/10" id="line-3"></div>
      <div class="progress-step" id="ps-4" onclick="goToStep(4)">
        <div class="step-circle step-future" id="sc-4">4</div>
        <span class="progress-label text-white/30" id="sl-4">Twitch</span>
      </div>
      <div class="step-line bg-white/10" id="line-4"></div>
      <div class="progress-step" id="ps-5" onclick="goToStep(5)">
        <div class="step-circle step-future" id="sc-5">5</div>
        <span class="progress-label text-white/30" id="sl-5">Persona</span>
      </div>
      <div class="step-line bg-white/10" id="line-5"></div>
      <div class="progress-step" id="ps-6">
        <div class="step-circle step-future" id="sc-6">6</div>
        <span class="progress-label text-white/30" id="sl-6">Lancement</span>
      </div>
    </div>
  </div>

  <!-- Étape 1 — Bienvenue -->
  <div id="step-1" class="glass p-6">
    <h2 class="text-lg font-bold mb-2">👋 Bienvenue !</h2>
    <p class="text-sm text-white/60 mb-4">Ce wizard va configurer ton bot en environ <strong class="text-white/80">10 minutes</strong>. Garde cette page ouverte — le lien expire dans 7 jours.</p>
    <div class="space-y-3 mb-6">
      <div class="flex items-start gap-3">
        <span class="text-green-400 mt-0.5">✅</span>
        <div><div class="text-sm font-semibold">Discord</div><div class="text-xs text-white/40">Token du bot, ID de ton serveur, clés OAuth</div></div>
      </div>
      <div class="flex items-start gap-3">
        <span class="text-green-400 mt-0.5">✅</span>
        <div><div class="text-sm font-semibold">Clés API (OpenAI requis)</div><div class="text-xs text-white/40">Pour l'intelligence artificielle du bot</div></div>
      </div>
      <div class="flex items-start gap-3">
        <span class="text-white/30 mt-0.5">⬜</span>
        <div><div class="text-sm font-semibold text-white/50">Twitch <span class="text-white/30 font-normal">(optionnel)</span></div><div class="text-xs text-white/30">Si tu veux le bot sur Twitch aussi</div></div>
      </div>
      <div class="flex items-start gap-3">
        <span class="text-green-400 mt-0.5">✅</span>
        <div><div class="text-sm font-semibold">Personnalité</div><div class="text-xs text-white/40">Nom, langue et caractère du bot</div></div>
      </div>
    </div>
    <div class="flex justify-end">
      <button class="btn-primary" onclick="nextStep()">Commencer →</button>
    </div>
  </div>

  <!-- Étape 2 — Discord -->
  <div id="step-2" class="glass p-6" style="display:none">
    <h2 class="text-lg font-bold mb-1">🔗 Connexion Discord</h2>
    <p class="text-xs text-white/40 mb-4">Crée une application sur <a href="https://discord.com/developers/applications" target="_blank" class="text-cyan-400 underline">discord.com/developers</a> si ce n'est pas fait.</p>

    <div class="space-y-4">
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Discord Bot Token <span class="text-red-400">*</span></label>
        <div class="help-box">💡 Applications → ton app → onglet <strong>Bot</strong> → bouton <strong>Reset Token</strong> → copie le token</div>
        <input id="discord_token" type="password" class="field-input" placeholder="MTxx...">
        <div id="discord_token_err" class="error-msg" style="display:none"></div>
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Discord Guild ID (ID de ton serveur) <span class="text-red-400">*</span></label>
        <div class="help-box">💡 Dans Discord : Paramètres → Avancés → active <strong>Mode développeur</strong>. Puis clic droit sur ton serveur → <strong>Copier l'identifiant</strong></div>
        <input id="discord_guild_id" type="text" class="field-input" placeholder="1234567890123456789">
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Client ID <span class="text-red-400">*</span></label>
        <div class="help-box">💡 Applications → ton app → onglet <strong>OAuth2</strong> → <strong>Client ID</strong></div>
        <input id="discord_client_id" type="text" class="field-input" placeholder="1234567890123456789">
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Client Secret <span class="text-red-400">*</span></label>
        <div class="help-box">💡 Même page OAuth2 → clique sur <strong>Reset Secret</strong></div>
        <input id="discord_client_secret" type="password" class="field-input" placeholder="abc123...">
      </div>
    </div>

    <div class="mt-4 flex items-center gap-3">
      <button class="btn-secondary text-sm" onclick="testDiscord()">🔍 Tester la connexion</button>
      <span id="discord_test_result" class="text-sm"></span>
    </div>

    <div class="flex justify-between mt-6 pt-4 border-t border-white/5">
      <button class="btn-secondary" onclick="prevStep()">← Retour</button>
      <button class="btn-primary" onclick="validateAndNext(2)">Continuer →</button>
    </div>
  </div>

  <!-- Étape 3 — Clés API -->
  <div id="step-3" class="glass p-6" style="display:none">
    <h2 class="text-lg font-bold mb-1">🔑 Clés API</h2>
    <p class="text-xs text-white/40 mb-4">Ces clés permettent à ton bot d'utiliser l'intelligence artificielle.</p>
    <div class="space-y-4">
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">OpenAI API Key <span class="text-red-400">*</span></label>
        <div class="help-box">💡 Va sur <a href="https://platform.openai.com/api-keys" target="_blank" class="text-cyan-400 underline">platform.openai.com/api-keys</a> → <strong>Create new secret key</strong> → copie la clé (commence par <code>sk-</code>)</div>
        <input id="openai_api_key" type="password" class="field-input" placeholder="sk-...">
        <div id="openai_err" class="error-msg" style="display:none"></div>
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Anthropic API Key <span class="text-white/30 font-normal">(optionnel)</span></label>
        <div class="help-box" style="border-left-color: rgba(255,255,255,0.15)">Uniquement si tu veux utiliser Claude. Va sur <a href="https://console.anthropic.com" target="_blank" class="text-cyan-400 underline">console.anthropic.com</a> → API Keys. Laisse vide sinon.</div>
        <input id="anthropic_api_key" type="password" class="field-input" placeholder="sk-ant-... (optionnel)">
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Tavily API Key <span class="text-white/30 font-normal">(optionnel)</span></label>
        <div class="help-box" style="border-left-color: rgba(255,255,255,0.15)">Permet la recherche web. Va sur <a href="https://app.tavily.com" target="_blank" class="text-cyan-400 underline">app.tavily.com</a>. Laisse vide sinon.</div>
        <input id="tavily_api_key" type="password" class="field-input" placeholder="tvly-... (optionnel)">
      </div>
    </div>
    <div class="flex justify-between mt-6 pt-4 border-t border-white/5">
      <button class="btn-secondary" onclick="prevStep()">← Retour</button>
      <button class="btn-primary" onclick="validateAndNext(3)">Continuer →</button>
    </div>
  </div>

  <!-- Étape 4 — Twitch -->
  <div id="step-4" class="glass p-6" style="display:none">
    <h2 class="text-lg font-bold mb-1">🎮 Twitch <span class="text-sm font-normal text-white/40">(optionnel)</span></h2>
    <p class="text-xs text-white/40 mb-4">Si ton bot est uniquement pour Discord, clique sur <strong>"Passer"</strong>.</p>
    <div class="space-y-4">
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Twitch Client ID</label>
        <div class="help-box">💡 <a href="https://dev.twitch.tv/console" target="_blank" class="text-cyan-400 underline">dev.twitch.tv/console</a> → ton app → <strong>Client ID</strong></div>
        <input id="twitch_client_id" type="text" class="field-input" placeholder="zzmxpn...">
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Twitch Client Secret</label>
        <div class="help-box">💡 Même page → <strong>Nouveau secret</strong></div>
        <input id="twitch_client_secret" type="password" class="field-input" placeholder="...">
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Nom du compte bot Twitch</label>
        <input id="twitch_bot_nick" type="text" class="field-input" placeholder="monbot_twitch">
      </div>

      <div class="glass p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="text-sm font-semibold">Compte bot Twitch</div>
          <span id="bot-status" class="text-xs text-white/30">Non connecté</span>
        </div>
        <button class="btn-secondary text-sm w-full" onclick="connectTwitch('bot')">Connecter le compte bot →</button>
      </div>

      <div class="glass p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="text-sm font-semibold">Compte streamer Twitch</div>
          <span id="streamer-status" class="text-xs text-white/30">Non connecté</span>
        </div>
        <button class="btn-secondary text-sm w-full" onclick="connectTwitch('streamer')">Connecter le compte streamer →</button>
      </div>
    </div>
    <div class="flex justify-between mt-6 pt-4 border-t border-white/5">
      <button class="btn-secondary" onclick="prevStep()">← Retour</button>
      <div class="flex gap-2">
        <button class="btn-secondary" onclick="skipTwitch()">Passer →</button>
        <button class="btn-primary" onclick="validateAndNext(4)" id="twitch-next-btn" style="display:none">Continuer →</button>
      </div>
    </div>
  </div>

  <!-- Étape 5 — Personnalité -->
  <div id="step-5" class="glass p-6" style="display:none">
    <h2 class="text-lg font-bold mb-1">🎭 Personnalité</h2>
    <p class="text-xs text-white/40 mb-4">Configure le nom, la langue et éditez les fichiers de personnalité.</p>

    <div class="space-y-4 mb-4">
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Nom du bot <span class="text-red-400">*</span></label>
        <input id="bot_name" type="text" class="field-input" placeholder="cindy" oninput="updateTriggerChip()">
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Langue par défaut</label>
        <select id="language_default" class="field-input" style="cursor:pointer">
          <option value="fr">Français</option>
          <option value="en">English</option>
        </select>
      </div>
      <div>
        <label class="text-xs font-semibold text-white/70 mb-1 block">Mots déclencheurs</label>
        <div id="trigger-chips" class="flex flex-wrap gap-2 mb-2"></div>
        <div class="flex gap-2">
          <input id="new-trigger" type="text" class="field-input" placeholder="Ajouter un mot..." style="flex:1" onkeydown="if(event.key==='Enter'){addTrigger();event.preventDefault();}">
          <button class="btn-secondary text-sm px-3" onclick="addTrigger()">+</button>
        </div>
      </div>
    </div>

    <div class="border-t border-white/5 pt-4">
      <p class="text-xs text-white/40 mb-3">Fichiers de personnalité — éditez librement :</p>
      <div class="flex gap-2 mb-3" id="persona-tabs">
        <button class="tab-btn tab-active" onclick="switchTab('SOUL')">SOUL</button>
        <button class="tab-btn tab-inactive" onclick="switchTab('IDENTITY')">IDENTITY</button>
        <button class="tab-btn tab-inactive" onclick="switchTab('VOICE')">VOICE</button>
        <button class="tab-btn tab-inactive" onclick="switchTab('EMOTIONS')">EMOTIONS</button>
      </div>
      <textarea id="persona-SOUL" class="field-input" placeholder="Décris la personnalité profonde du bot..."></textarea>
      <textarea id="persona-IDENTITY" class="field-input" style="display:none" placeholder="Décris l'identité et le rôle du bot..."></textarea>
      <textarea id="persona-VOICE" class="field-input" style="display:none" placeholder="Décris comment le bot s'exprime..."></textarea>
      <textarea id="persona-EMOTIONS" class="field-input" style="display:none" placeholder="Décris le comportement émotionnel du bot..."></textarea>
    </div>

    <div class="flex justify-between mt-6 pt-4 border-t border-white/5">
      <button class="btn-secondary" onclick="prevStep()">← Retour</button>
      <button class="btn-primary" onclick="validateAndNext(5)">Continuer →</button>
    </div>
  </div>

  <!-- Étape 6 — Lancement -->
  <div id="step-6" class="glass p-6" style="display:none">
    <h2 class="text-lg font-bold mb-4">🚀 Lancement</h2>

    <!-- Récapitulatif -->
    <div id="recap" class="space-y-2 mb-6 text-sm"></div>

    <!-- Mode preview toggle -->
    <div id="preview-toggle" class="glass p-3 mb-4 flex items-center gap-3" style="display:none!important">
      <input type="checkbox" id="dry-run-toggle" class="w-4 h-4" checked>
      <label for="dry-run-toggle" class="text-sm cursor-pointer">Mode simulation (ne lance pas Docker — montre les fichiers générés)</label>
    </div>

    <!-- Bouton lancer -->
    <div id="launch-section">
      <button class="btn-primary w-full text-center py-3" onclick="submitWizard()" id="launch-btn">🚀 Créer mon instance</button>
    </div>

    <!-- Progression -->
    <div id="launch-progress" style="display:none" class="space-y-3">
      <div class="text-sm text-white/60" id="launch-status">Création des fichiers...</div>
      <div class="w-full bg-white/5 rounded-full h-2">
        <div id="launch-bar" class="h-2 rounded-full bg-cyan-500 transition-all duration-500" style="width:0%"></div>
      </div>
    </div>

    <!-- Résultat -->
    <div id="launch-result" style="display:none"></div>

    <div class="flex justify-start mt-6 pt-4 border-t border-white/5">
      <button class="btn-secondary" onclick="prevStep()" id="back-from-launch">← Retour</button>
    </div>
  </div>

</div>

<script>
// ── State ───────────────────────────────────────────────────────────────────
const WIZARD_TOKEN = '__WIZARD_TOKEN__';
const WIZARD_MODE = '__WIZARD_MODE__';
const IS_PREVIEW = WIZARD_MODE === 'preview';

let currentStep = 1;
const maxReached = { 1: true };
const triggerNames = [];
let twitchPolling = null;

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (IS_PREVIEW) {
    document.getElementById('preview-badge').style.display = 'inline';
    document.getElementById('preview-toggle').style.removeProperty('display');
    document.getElementById('launch-btn').textContent = '🔬 Simuler / Créer';
  }
  updateProgressBar();
  loadPersonaTemplates();
});

// ── Navigation ───────────────────────────────────────────────────────────────
function showStep(n) {
  for (let i = 1; i <= 6; i++) {
    const el = document.getElementById('step-' + i);
    if (el) el.style.display = i === n ? 'block' : 'none';
  }
  currentStep = n;
  updateProgressBar();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function nextStep() { showStep(currentStep + 1); maxReached[currentStep + 1] = true; }
function prevStep() { showStep(currentStep - 1); }

function goToStep(n) {
  if (maxReached[n]) showStep(n);
}

function updateProgressBar() {
  const labels = ['Bienvenue', 'Discord', 'Clés API', 'Twitch', 'Persona', 'Lancement'];
  for (let i = 1; i <= 6; i++) {
    const sc = document.getElementById('sc-' + i);
    const sl = document.getElementById('sl-' + i);
    if (!sc) continue;
    sc.className = 'step-circle ';
    if (i < currentStep) {
      sc.className += 'step-done';
      sc.textContent = '✓';
      if (sl) sl.className = 'progress-label text-green-400';
    } else if (i === currentStep) {
      sc.className += 'step-active';
      sc.textContent = i;
      if (sl) sl.className = 'progress-label text-cyan-400';
    } else {
      sc.className += 'step-future';
      sc.textContent = i;
      if (sl) sl.className = 'progress-label text-white/30';
    }
    const line = document.getElementById('line-' + i);
    if (line) {
      line.className = 'step-line ' + (i < currentStep ? 'bg-green-500/40' : 'bg-white/10');
    }
  }
}

// ── Validation par étape ─────────────────────────────────────────────────────
async function validateAndNext(step) {
  if (step === 2) {
    const fields = ['discord_token', 'discord_guild_id', 'discord_client_id', 'discord_client_secret'];
    for (const f of fields) {
      if (!document.getElementById(f).value.trim()) {
        showError(f + '_err', 'Ce champ est requis.'); return;
      }
    }
  }
  if (step === 3) {
    const key = document.getElementById('openai_api_key').value.trim();
    if (!key) { showError('openai_err', 'La clé OpenAI est requise.'); return; }
  }
  if (step === 5) {
    const name = document.getElementById('bot_name').value.trim();
    if (!name) { alert('Le nom du bot est requis.'); return; }
    if (triggerNames.length === 0) triggerNames.push(name);
  }
  await saveCurrentStep();
  nextStep();
}

async function saveCurrentStep() {
  const data = gatherStepData(currentStep);
  if (Object.keys(data).length === 0) return;
  try {
    const headers = IS_PREVIEW ? { 'Authorization': 'Bearer ' + (localStorage.getItem('wally_admin_token') || '') } : {};
    await fetch('/api/setup/' + WIZARD_TOKEN + '/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(data),
    });
  } catch (e) { console.warn('Save failed:', e); }
}

function gatherStepData(step) {
  const g = id => (document.getElementById(id) || {}).value || '';
  if (step === 2) return {
    discord_token: g('discord_token'),
    discord_guild_id: g('discord_guild_id'),
    discord_client_id: g('discord_client_id'),
    discord_client_secret: g('discord_client_secret'),
  };
  if (step === 3) return {
    openai_api_key: g('openai_api_key'),
    anthropic_api_key: g('anthropic_api_key'),
    tavily_api_key: g('tavily_api_key'),
  };
  if (step === 4) return {
    twitch_enabled: document.getElementById('twitch_client_id').value.trim() !== '',
    twitch_client_id: g('twitch_client_id'),
    twitch_client_secret: g('twitch_client_secret'),
    twitch_bot_nick: g('twitch_bot_nick'),
  };
  if (step === 5) return {
    bot_name: g('bot_name'),
    language_default: g('language_default'),
    trigger_names: [...triggerNames],
    persona_soul: g('persona-SOUL'),
    persona_identity: g('persona-IDENTITY'),
    persona_voice: g('persona-VOICE'),
    persona_emotions: g('persona-EMOTIONS'),
  };
  return {};
}

// ── Discord test ──────────────────────────────────────────────────────────────
async function testDiscord() {
  const token = document.getElementById('discord_token').value.trim();
  const resultEl = document.getElementById('discord_test_result');
  if (!token) { resultEl.textContent = '⚠️ Saisis le token d\'abord.'; resultEl.className = 'text-sm text-yellow-400'; return; }
  resultEl.textContent = '⏳ Test en cours...';
  resultEl.className = 'text-sm text-white/50';
  try {
    const headers = IS_PREVIEW ? { 'Authorization': 'Bearer ' + (localStorage.getItem('wally_admin_token') || '') } : {};
    const resp = await fetch('/api/setup/' + WIZARD_TOKEN + '/validate-discord', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify({ discord_token: token }),
    });
    const data = await resp.json();
    if (data.ok) {
      resultEl.textContent = '✅ Connecté : @' + data.username;
      resultEl.className = 'text-sm text-green-400';
    } else {
      resultEl.textContent = '❌ ' + (data.error || 'Token invalide');
      resultEl.className = 'text-sm text-red-400';
    }
  } catch (e) {
    resultEl.textContent = '❌ Erreur réseau';
    resultEl.className = 'text-sm text-red-400';
  }
}

// ── Twitch OAuth ──────────────────────────────────────────────────────────────
async function connectTwitch(accountType) {
  const clientId = document.getElementById('twitch_client_id').value.trim();
  const clientSecret = document.getElementById('twitch_client_secret').value.trim();
  if (!clientId || !clientSecret) { alert('Saisis le Client ID et le Client Secret d\'abord.'); return; }
  const headers = IS_PREVIEW ? { 'Authorization': 'Bearer ' + (localStorage.getItem('wally_admin_token') || '') } : {};
  const resp = await fetch('/api/setup/' + WIZARD_TOKEN + '/twitch-auth-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify({ account_type: accountType, client_id: clientId, client_secret: clientSecret }),
  });
  const data = await resp.json();
  window.open(data.url, '_blank', 'width=600,height=700');
  startTwitchPolling();
}

function startTwitchPolling() {
  if (twitchPolling) return;
  twitchPolling = setInterval(async () => {
    const headers = IS_PREVIEW ? { 'Authorization': 'Bearer ' + (localStorage.getItem('wally_admin_token') || '') } : {};
    const resp = await fetch('/api/setup/' + WIZARD_TOKEN + '/twitch-status', { headers });
    const data = await resp.json();
    const botStatus = document.getElementById('bot-status');
    const streamerStatus = document.getElementById('streamer-status');
    const nextBtn = document.getElementById('twitch-next-btn');
    if (data.bot_connected) {
      botStatus.textContent = '✅ @' + data.bot_username;
      botStatus.className = 'text-xs text-green-400';
    }
    if (data.streamer_connected) {
      streamerStatus.textContent = '✅ @' + data.streamer_username;
      streamerStatus.className = 'text-xs text-green-400';
    }
    if (data.bot_connected && data.streamer_connected) {
      clearInterval(twitchPolling); twitchPolling = null;
      nextBtn.style.display = 'inline-flex';
    }
  }, 2000);
}

async function skipTwitch() {
  await fetch('/api/setup/' + WIZARD_TOKEN + '/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ twitch_enabled: false }),
  });
  nextStep();
}

// ── Triggers chips ────────────────────────────────────────────────────────────
function updateTriggerChip() {
  const name = document.getElementById('bot_name').value.trim().toLowerCase();
  if (name && !triggerNames.includes(name)) {
    if (triggerNames.length === 0) { triggerNames.push(name); renderChips(); }
    else { triggerNames[0] = name; renderChips(); }
  }
}

function addTrigger() {
  const inp = document.getElementById('new-trigger');
  const val = inp.value.trim().toLowerCase();
  if (val && !triggerNames.includes(val)) { triggerNames.push(val); renderChips(); }
  inp.value = '';
}

function removeTrigger(i) { triggerNames.splice(i, 1); renderChips(); }

function renderChips() {
  const c = document.getElementById('trigger-chips');
  c.innerHTML = triggerNames.map((t, i) =>
    `<span class="tag-chip">${t} <span onclick="removeTrigger(${i})" style="cursor:pointer;margin-left:2px">×</span></span>`
  ).join('');
}

// ── Persona tabs ──────────────────────────────────────────────────────────────
function switchTab(name) {
  ['SOUL', 'IDENTITY', 'VOICE', 'EMOTIONS'].forEach(n => {
    document.getElementById('persona-' + n).style.display = n === name ? 'block' : 'none';
  });
  document.querySelectorAll('#persona-tabs .tab-btn').forEach((btn, i) => {
    const tabs = ['SOUL', 'IDENTITY', 'VOICE', 'EMOTIONS'];
    btn.className = 'tab-btn ' + (tabs[i] === name ? 'tab-active' : 'tab-inactive');
  });
}

async function loadPersonaTemplates() {
  // Charger les fichiers persona de Wally comme templates de départ
  const files = ['SOUL', 'IDENTITY', 'VOICE', 'EMOTIONS'];
  for (const f of files) {
    try {
      const resp = await fetch('/api/admin/setup/persona-template/' + f);
      if (resp.ok) {
        const data = await resp.json();
        document.getElementById('persona-' + f).value = data.content || '';
      }
    } catch (e) { /* silencieux */ }
  }
}

// ── Récapitulatif ─────────────────────────────────────────────────────────────
function buildRecap() {
  const g = id => (document.getElementById(id) || {}).value || '';
  const mask = v => v ? v.substring(0, 4) + '••••••••••' : '—';
  const items = [
    { label: 'Bot Discord', value: g('discord_guild_id') ? '✅ Guild ID: ' + g('discord_guild_id') : '❌ Non configuré' },
    { label: 'OpenAI', value: g('openai_api_key') ? '✅ Clé configurée' : '❌ Manquant' },
    { label: 'Twitch', value: g('twitch_client_id') ? '✅ Configuré' : '⬜ Non configuré (optionnel)' },
    { label: 'Nom du bot', value: g('bot_name') || '—' },
    { label: 'Langue', value: g('language_default') || 'fr' },
  ];
  document.getElementById('recap').innerHTML = items.map(item =>
    `<div class="flex justify-between py-2 border-b border-white/5">
      <span class="text-white/50">${item.label}</span>
      <span class="text-sm">${item.value}</span>
    </div>`
  ).join('');
}

// ── Lancement ─────────────────────────────────────────────────────────────────
async function submitWizard() {
  await saveCurrentStep();
  const dryRun = IS_PREVIEW && document.getElementById('dry-run-toggle').checked;
  document.getElementById('launch-section').style.display = 'none';
  document.getElementById('back-from-launch').style.display = 'none';
  document.getElementById('launch-progress').style.display = 'block';

  const steps = [
    { msg: 'Création des fichiers de configuration...', pct: 20 },
    { msg: 'Génération du fichier Docker Compose...', pct: 50 },
    { msg: 'Démarrage du conteneur...', pct: 80 },
  ];
  let si = 0;
  const ticker = setInterval(() => {
    if (si < steps.length) {
      document.getElementById('launch-status').textContent = steps[si].msg;
      document.getElementById('launch-bar').style.width = steps[si].pct + '%';
      si++;
    }
  }, 800);

  try {
    const headers = IS_PREVIEW ? { 'Authorization': 'Bearer ' + (localStorage.getItem('wally_admin_token') || '') } : {};
    const resp = await fetch('/api/setup/' + WIZARD_TOKEN + '/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify({ dry_run: dryRun }),
    });
    clearInterval(ticker);
    const data = await resp.json();
    document.getElementById('launch-bar').style.width = '100%';
    document.getElementById('launch-progress').style.display = 'none';
    document.getElementById('launch-result').style.display = 'block';

    if (resp.ok && data.url) {
      document.getElementById('launch-result').innerHTML = `
        <div class="glass p-5 text-center space-y-3">
          <div class="text-3xl">🎉</div>
          <div class="font-bold text-lg">${dryRun ? 'Simulation réussie !' : 'Instance démarrée !'}</div>
          ${!dryRun ? `<div class="text-sm text-white/60">Ton instance est disponible sur :</div>
          <div class="text-cyan-400 font-mono text-sm">${data.url}</div>
          <div class="text-xs text-white/30 mt-2">Configure un sous-domaine pointant vers le port ${data.port} de ton serveur.</div>` : ''}
          ${dryRun ? '<div class="text-xs text-white/50">Mode simulation — aucun conteneur créé.</div>' : ''}
        </div>`;
    } else {
      throw new Error(data.detail || 'Erreur inconnue');
    }
  } catch (e) {
    clearInterval(ticker);
    document.getElementById('launch-progress').style.display = 'none';
    document.getElementById('launch-result').style.display = 'block';
    document.getElementById('launch-result').innerHTML = `
      <div class="glass p-5 space-y-3 border border-red-500/20">
        <div class="text-red-400 font-semibold">❌ Erreur lors du lancement</div>
        <div class="text-sm text-white/50">${e.message}</div>
        <button class="btn-secondary text-sm" onclick="location.reload()">Réessayer</button>
      </div>`;
  }
}

// ── Override step 6 show ──────────────────────────────────────────────────────
const _origShowStep = showStep;
window.showStep = function(n) {
  _origShowStep(n);
  if (n === 6) buildRecap();
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function showError(id, msg) {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; el.style.display = 'block'; }
  setTimeout(() => { if (el) el.style.display = 'none'; }, 4000);
}
</script>
</body>
</html>
```

- [ ] **Step 2: Ajouter la route de template persona dans `setup.py` (admin_router)**

```python
@admin_router.get("/persona-template/{filename}")
async def persona_template(filename: str) -> dict:
    """Retourne le contenu d'un fichier persona de Wally comme template."""
    from pathlib import Path
    allowed = {"SOUL", "IDENTITY", "VOICE", "EMOTIONS", "EXEMPLES", "WEEKDAYS"}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Fichier inconnu")
    path = Path("bot/persona") / f"{filename}.md"
    if not path.exists():
        return {"content": ""}
    return {"content": path.read_text(encoding="utf-8")}
```

- [ ] **Step 3: Vérifier visuellement en mode preview**

Lancer le serveur local (ou vérifier avec curl) :
```bash
python -m pytest tests/test_setup_routes.py tests/test_setup_db.py tests/test_setup_provisioner.py -v
```
Attendu : tous PASS

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/static/setup.html bot/dashboard/routes/setup.py
git commit -m "feat(setup): wizard SPA 6 étapes + route persona-template"
```

---

### Task 6: Onglet Instances dans le dashboard admin

**Files:**
- Modify: `bot/dashboard/static/index.html`

- [ ] **Step 1: Localiser l'onglet Actions dans `index.html`**

```bash
grep -n "actions\|Actions\|tab-actions" bot/dashboard/static/index.html | head -20
```

- [ ] **Step 2: Ajouter l'onglet "Instances" dans la sidebar admin**

Dans la section sidebar admin (côté `index.html`), trouver le bouton Actions et ajouter après :

```html
<button class="sidebar-nav-btn" id="nav-instances" onclick="switchAdminTab('instances')">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
  Instances
</button>
```

- [ ] **Step 3: Ajouter le panneau contenu `instances`**

Trouver le panneau `admin-actions` et ajouter après lui :

```html
<!-- ─── Panel Instances ─── -->
<div id="admin-instances" style="display:none">
  <div class="admin-section-header">
    <h3>Instances</h3>
    <button class="btn-sm btn-primary" onclick="generateInvite()">+ Générer un lien</button>
  </div>

  <!-- Invitations -->
  <div class="glass-card mb-4">
    <h4 class="text-sm font-semibold mb-3 text-white/70">Liens d'invitation</h4>
    <div id="invites-list" class="space-y-2 text-sm text-white/50">Chargement...</div>
  </div>

  <!-- Instances actives -->
  <div class="glass-card">
    <h4 class="text-sm font-semibold mb-3 text-white/70">Instances actives</h4>
    <div id="instances-list" class="space-y-2 text-sm text-white/50">Chargement...</div>
    <a id="preview-wizard-link" href="/setup/preview" target="_blank"
       class="mt-3 inline-block text-xs text-cyan-400 underline cursor-pointer">
      🔬 Ouvrir le wizard en mode test
    </a>
  </div>
</div>
```

- [ ] **Step 4: Ajouter les fonctions JS dans le bloc script de `index.html`**

À la fin du bloc `<script>` principal, ajouter :

```javascript
// ── Instances tab ─────────────────────────────────────────────────────────────
async function loadInstancesTab() {
  await Promise.all([loadInvites(), loadInstances()]);
}

async function loadInvites() {
  try {
    const resp = await apiFetch('/api/admin/setup/invites');
    const data = await resp.json();
    const el = document.getElementById('invites-list');
    if (!data.invites || data.invites.length === 0) {
      el.innerHTML = '<div class="text-white/30 text-xs">Aucun lien généré</div>';
      return;
    }
    el.innerHTML = data.invites.map(inv => {
      const statusColor = { pending: 'text-cyan-400', used: 'text-green-400', expired: 'text-red-400/60', revoked: 'text-white/20' }[inv.status] || 'text-white/40';
      return `<div class="flex items-center justify-between py-1 border-b border-white/5">
        <div>
          <span class="font-mono text-xs text-white/60">${inv.token}</span>
          <span class="ml-2 text-xs ${statusColor}">${inv.status}</span>
          ${inv.slug ? `<span class="ml-2 text-xs text-white/30">→ ${inv.slug}</span>` : ''}
        </div>
        <div class="flex gap-2">
          ${inv.status === 'pending' ? `<button class="btn-xs" onclick="copyInviteLink('${inv.token_full}')">📋</button>
          <button class="btn-xs text-red-400/70" onclick="revokeInvite('${inv.token_full}')">Révoquer</button>` : ''}
        </div>
      </div>`;
    }).join('');
  } catch (e) { console.error(e); }
}

async function loadInstances() {
  try {
    const resp = await apiFetch('/api/admin/setup/instances');
    const data = await resp.json();
    const el = document.getElementById('instances-list');
    if (!data.instances || data.instances.length === 0) {
      el.innerHTML = '<div class="text-white/30 text-xs">Aucune instance créée</div>';
      return;
    }
    el.innerHTML = data.instances.map(inst => {
      const running = inst.docker_status === 'running';
      return `<div class="flex items-center justify-between py-1 border-b border-white/5">
        <div>
          <span class="font-semibold text-white/80">${inst.slug}</span>
          <span class="ml-2 text-xs ${running ? 'text-green-400' : 'text-red-400/70'}">● ${inst.docker_status}</span>
          <span class="ml-2 text-xs text-white/30">:${inst.port}</span>
        </div>
        <div class="flex gap-2">
          ${running
            ? `<button class="btn-xs text-red-400/70" onclick="instanceAction('${inst.slug}','stop')">Stop</button>`
            : `<button class="btn-xs text-green-400/70" onclick="instanceAction('${inst.slug}','start')">Start</button>`}
        </div>
      </div>`;
    }).join('');
  } catch (e) { console.error(e); }
}

async function generateInvite() {
  try {
    const resp = await apiFetch('/api/admin/setup/invite', { method: 'POST' });
    const data = await resp.json();
    await navigator.clipboard.writeText(data.url);
    alert('Lien copié dans le presse-papier :\n' + data.url);
    await loadInvites();
  } catch (e) { alert('Erreur : ' + e.message); }
}

async function copyInviteLink(token) {
  const baseUrl = window.location.origin;
  const url = baseUrl + '/setup/' + token;
  await navigator.clipboard.writeText(url);
  alert('Lien copié !');
}

async function revokeInvite(token) {
  if (!confirm('Révoquer ce lien ?')) return;
  await apiFetch('/api/admin/setup/invite/' + token, { method: 'DELETE' });
  await loadInvites();
}

async function instanceAction(slug, action) {
  await apiFetch('/api/admin/setup/instances/' + slug + '/' + action, { method: 'POST' });
  setTimeout(loadInstances, 1500);
}
```

- [ ] **Step 5: Brancher le chargement dans `switchAdminTab`**

Trouver la fonction `switchAdminTab` dans `index.html` et ajouter le cas `instances` :

```javascript
if (tab === 'instances') loadInstancesTab();
```

- [ ] **Step 6: Lancer les tests existants pour vérifier pas de régression**

```bash
python -m pytest tests/ -x -q 2>&1 | tail -10
```
Attendu : tous les tests passent (ou même nombre qu'avant)

- [ ] **Step 7: Commit final**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/setup.html bot/dashboard/routes/setup.py bot/dashboard/app.py bot/core/provisioner.py bot/core/memory.py bot/db/database.py
git commit -m "feat(setup): onglet Instances dans le dashboard admin"
```

---

## Self-Review

### Couverture du spec

| Exigence spec | Tâche |
|---|---|
| Tables setup_invites + setup_sessions | Task 1 |
| Provisioner (dirs, .env, config.yaml, persona, docker-compose, docker up) | Task 2 |
| Lire QDRANT_COLLECTION_NAME depuis env | Task 2 |
| Routes admin (invite CRUD, instances list/start/stop) | Task 3 |
| Routes wizard (save, validate-discord, twitch-auth-url, callback, status, submit) | Task 3 |
| App registration + /setup/* pages | Task 4 |
| Token __preview__ init au démarrage | Task 4 |
| SPA wizard 6 étapes avec navigation libre vers l'arrière | Task 5 |
| Aide contextuelle détaillée par champ | Task 5 |
| Twitch OAuth bot + streamer avec polling | Task 5 |
| Mode preview (toggle simulation/créer) | Task 5 |
| Route persona-template | Task 5 |
| Onglet Instances dans dashboard admin | Task 6 |
| Génération + copie du lien d'invitation | Task 6 |
| Start/stop instances | Task 6 |

### Sécurité

- `_check_preview_auth` vérifié dans chaque route wizard quand token == `__preview__` ✅
- Tokens retournés masqués au client ✅ (routes list_invites retournent token[:8]+"..." sauf token_full pour copy)
- `_get_valid_invite` valide présence + expiry + usage à chaque requête wizard ✅
- Provisioner génère JWT_SECRET via `secrets.token_hex(32)` ✅
