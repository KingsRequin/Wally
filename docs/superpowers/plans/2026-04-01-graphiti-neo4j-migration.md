# Chantier A — Migration Graphiti + Neo4j + Signaux sociaux

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le système mémoire plat (Qdrant-only) par un graphe de connaissances temporel (Graphiti + Neo4j), ajouter la capture de signaux sociaux Discord, et visualiser le graphe social dans le dashboard.

**Architecture:** Graphiti comme moteur de graphe au-dessus de Neo4j. Qdrant conservé en parallèle pendant la transition. Nouveau module `bot/core/graph.py` comme façade. Signaux sociaux dans `bot/discord/social.py`. Visualisation via neovis.js dans un nouvel onglet dashboard.

**Tech Stack:** graphiti-core, neo4j (Community 5.x), neovis.js, Python 3.11, asyncio

---

## Phases

| Phase | Scope | Dépendances |
|-------|-------|-------------|
| **1. Infrastructure** | Neo4j + Graphiti dans docker-compose, client Python | Aucune |
| **2. Ingestion** | add_episode() dans le FactExtractor | Phase 1 |
| **3. Recherche** | Graphiti.search() remplace Qdrant search | Phase 2 |
| **4. Signaux sociaux** | Capture vocal/réactions/mentions/threads/jeux | Phase 1 |
| **5. Score d'affinité** | Calcul et injection dans les prompts | Phases 3+4 |
| **6. Visualisation** | Page /graph avec neovis.js | Phases 1+4 |

---

## File Map

| Action | Fichier | Responsabilité |
|--------|---------|----------------|
| Create | `bot/core/graph.py` | GraphService: façade Graphiti, init, add_episode, search, affinity |
| Modify | `bot/main.py` | Wiring GraphService, injection dans bots |
| Modify | `docker-compose.yml` | Service neo4j |
| Modify | `Dockerfile` | pip install graphiti-core |
| Modify | `requirements.txt` ou `pyproject.toml` | Dépendance graphiti-core |
| Modify | `config.yaml` | Section graphiti: |
| Modify | `bot/config.py` | GraphitiConfig dataclass |
| Modify | `bot/core/fact_extractor.py` | Appel add_episode() après extraction |
| Modify | `bot/discord/handlers.py` | Injection contexte graphe, search migration |
| Modify | `bot/twitch/handlers.py` | Idem |
| Modify | `bot/core/prompts.py` | Nouveau bloc graphe dans system prompt |
| Create | `bot/discord/social.py` | Capture signaux sociaux (vocal, réactions, etc.) |
| Modify | `bot/discord/bot.py` | Enregistrer les event listeners social |
| Create | `bot/dashboard/routes/graph.py` | API endpoints graphe social |
| Modify | `bot/dashboard/static/app.js` | Page /graph avec neovis.js |
| Modify | `bot/core/provisioner.py` | Neo4j dans les instances provisionnées |
| Create | `tests/test_graph.py` | Tests GraphService |
| Create | `tests/test_social.py` | Tests signaux sociaux |

---

### Task 1: Infrastructure — Neo4j dans docker-compose

**Files:**
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`
- Modify: `config.yaml`
- Modify: `bot/config.py`

- [ ] **Step 1: Ajouter neo4j au docker-compose**

Dans `docker-compose.yml`, ajouter le service :

```yaml
  neo4j:
    image: neo4j:5-community
    restart: unless-stopped
    environment:
      - NEO4J_AUTH=${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-changeme}
      - NEO4J_server_memory_heap_initial__size=512m
      - NEO4J_server_memory_heap_max__size=512m
      - NEO4J_server_memory_pagecache_size=256m
      - NEO4J_PLUGINS=["apoc"]
    volumes:
      - neo4j_data:/data
    ports:
      - "${NEO4J_BROWSER_PORT:-7474}:7474"
      - "${NEO4J_BOLT_PORT:-7687}:7687"
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 5
```

Ajouter `neo4j_data` au bloc `volumes:`. Ajouter `neo4j` aux `depends_on` du service `wally`.

- [ ] **Step 2: Ajouter graphiti-core au Dockerfile**

Dans `Dockerfile`, ajouter `graphiti-core` aux dépendances pip. Vérifier la version openai requise (`>=1.91.0`) et mettre à jour si nécessaire.

- [ ] **Step 3: Ajouter la config graphiti**

Dans `config.yaml`, ajouter :

```yaml
graphiti:
  enabled: false
  neo4j_uri: bolt://neo4j:7687
  neo4j_user: neo4j
  neo4j_password: changeme
  llm_model: gpt-5-nano
  community_detection: false
  group_id: "discord:default"
```

Dans `bot/config.py`, ajouter un `GraphitiConfig` dataclass et le charger dans `Config.load()`.

```python
@dataclass
class GraphitiConfig:
    enabled: bool = False
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"
    llm_model: str = "gpt-5-nano"
    community_detection: bool = False
    group_id: str = "discord:default"
```

- [ ] **Step 4: Ajouter les env vars au .env.example**

```
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme
NEO4J_BROWSER_PORT=7474
NEO4J_BOLT_PORT=7687
```

- [ ] **Step 5: Tester que neo4j démarre**

```bash
docker compose up -d neo4j
docker compose logs neo4j --tail 20
# Vérifier "Started." dans les logs
curl -s http://localhost:7474 | head -5
```

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml Dockerfile config.yaml bot/config.py
git commit -m "feat(graph): add Neo4j service and GraphitiConfig"
```

---

### Task 2: GraphService — façade Graphiti

**Files:**
- Create: `bot/core/graph.py`
- Modify: `bot/main.py`
- Create: `tests/test_graph.py`

- [ ] **Step 1: Créer bot/core/graph.py**

```python
"""GraphService — Graphiti facade for Wally's knowledge graph."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config, GraphitiConfig

# Lazy imports to avoid crash when graphiti not installed
_graphiti_available = False
try:
    from graphiti_core import Graphiti
    from graphiti_core.llm_client import LLMConfig, OpenAIClient
    from graphiti_core.nodes import EpisodeType
    _graphiti_available = True
except ImportError:
    pass


class GraphService:
    """Facade over Graphiti for knowledge graph operations."""

    def __init__(self, config: "Config"):
        self._config = config
        self._graphiti: Any | None = None
        self._ready = False

    async def initialize(self) -> bool:
        """Connect to Neo4j and build indices. Returns True if successful."""
        gc: GraphitiConfig = self._config.graphiti
        if not gc.enabled or not _graphiti_available:
            logger.info("GraphService disabled (enabled={e}, available={a})",
                        e=gc.enabled, a=_graphiti_available)
            return False
        try:
            llm_client = OpenAIClient(config=LLMConfig(
                model=gc.llm_model,
                small_model=gc.llm_model,
            ))
            self._graphiti = Graphiti(
                uri=gc.neo4j_uri,
                user=gc.neo4j_user,
                password=gc.neo4j_password,
                llm_client=llm_client,
            )
            await self._graphiti.build_indices_and_constraints()
            self._ready = True
            logger.info("GraphService connected to Neo4j at {uri}", uri=gc.neo4j_uri)
            return True
        except Exception as exc:
            logger.warning("GraphService init failed: {e}", e=exc)
            self._graphiti = None
            self._ready = False
            return False

    @property
    def ready(self) -> bool:
        return self._ready and self._graphiti is not None

    async def add_episode(
        self,
        content: str,
        author: str,
        source: str = "discord",
        group_id: str | None = None,
        update_communities: bool = False,
    ) -> dict | None:
        """Ingest a message into the knowledge graph.

        Returns extracted entities/edges summary or None on failure.
        """
        if not self.ready:
            return None
        try:
            gid = group_id or self._config.graphiti.group_id
            result = await self._graphiti.add_episode(
                name=f"{source} message",
                episode_body=f"{author}: {content}",
                source_description=f"{source} chat",
                source=EpisodeType.message,
                reference_time=datetime.now(timezone.utc),
                group_id=gid,
                update_communities=update_communities,
            )
            entities = [n.name for n in result.nodes] if result.nodes else []
            edges = [e.fact for e in result.edges] if result.edges else []
            logger.debug(
                "Graph episode added: {n} entities, {e} edges",
                n=len(entities), e=len(edges),
            )
            return {"entities": entities, "edges": edges}
        except Exception as exc:
            logger.warning("Graph add_episode failed: {e}", e=exc)
            return None

    async def search(
        self,
        query: str,
        group_id: str | None = None,
        num_results: int = 10,
    ) -> list[dict]:
        """Search the knowledge graph. Returns list of {fact, score} dicts."""
        if not self.ready:
            return []
        try:
            gid = group_id or self._config.graphiti.group_id
            edges = await self._graphiti.search(
                query=query,
                group_ids=[gid],
                num_results=num_results,
            )
            return [
                {
                    "fact": edge.fact,
                    "name": edge.name,
                    "valid_at": str(edge.valid_at) if edge.valid_at else None,
                    "invalid_at": str(edge.invalid_at) if edge.invalid_at else None,
                }
                for edge in edges
            ]
        except Exception as exc:
            logger.warning("Graph search failed: {e}", e=exc)
            return []

    async def close(self) -> None:
        """Shutdown Graphiti and close Neo4j connection."""
        if self._graphiti is not None:
            try:
                await self._graphiti.close()
            except Exception:
                pass
            self._graphiti = None
            self._ready = False
```

- [ ] **Step 2: Wiring dans main.py**

Ajouter après l'init de MemoryService :

```python
from bot.core.graph import GraphService

graph = GraphService(config)
await graph.initialize()
```

Passer `graph` aux bots Discord et Twitch comme attribut `bot.graph`.

- [ ] **Step 3: Test basique**

```python
# tests/test_graph.py
import pytest
from unittest.mock import MagicMock
from bot.core.graph import GraphService


def test_graph_service_disabled_by_default():
    config = MagicMock()
    config.graphiti.enabled = False
    svc = GraphService(config)
    assert not svc.ready


@pytest.mark.asyncio
async def test_graph_service_not_ready_without_init():
    config = MagicMock()
    config.graphiti.enabled = False
    svc = GraphService(config)
    result = await svc.add_episode("hello", "Alice")
    assert result is None
    results = await svc.search("hello")
    assert results == []
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_graph.py -v
```

- [ ] **Step 5: Commit**

```bash
git add bot/core/graph.py bot/main.py tests/test_graph.py
git commit -m "feat(graph): add GraphService facade over Graphiti"
```

---

### Task 3: Ingestion — add_episode dans le FactExtractor

**Files:**
- Modify: `bot/core/fact_extractor.py`

- [ ] **Step 1: Passer GraphService au FactExtractor**

Dans `bot/core/fact_extractor.py`, ajouter `graph` au constructeur. Le stocker comme `self._graph`.

Dans `bot/main.py`, passer `graph` au FactExtractor lors de sa construction.

- [ ] **Step 2: Appeler add_episode après l'extraction de faits**

Dans `_do_flush()`, après l'appel à `_extract_facts()` et avant le stockage des faits dans Qdrant, ajouter un appel fire-and-forget :

```python
# Ingest into knowledge graph (non-blocking)
if self._graph and self._graph.ready:
    for msg in messages:
        asyncio.create_task(
            self._graph.add_episode(
                content=msg["content"],
                author=msg["author"],
                source=platform,
                group_id=f"{platform}:{channel_id}" if channel_id else None,
            )
        )
```

Note : on garde le stockage Qdrant existant en parallèle. Les deux systèmes tournent simultanément.

- [ ] **Step 3: Test**

Écrire un test qui vérifie que `graph.add_episode` est appelé quand le graph est ready, et pas appelé quand il ne l'est pas. Mock both graph and memory.

- [ ] **Step 4: Commit**

```bash
git add bot/core/fact_extractor.py bot/main.py tests/
git commit -m "feat(graph): ingest messages into knowledge graph via FactExtractor"
```

---

### Task 4: Recherche — contexte graphe dans les prompts

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/twitch/handlers.py`
- Modify: `bot/core/prompts.py`

- [ ] **Step 1: Ajouter graph search dans le handler Discord**

Dans `bot/discord/handlers.py`, après la recherche mémoire Qdrant existante (`memory.search()`), ajouter :

```python
# Knowledge graph context (Graphiti)
graph_context = ""
if hasattr(bot, 'graph') and bot.graph.ready:
    try:
        graph_results = await bot.graph.search(
            query=content,
            group_id=f"discord:{message.guild.id}" if message.guild else None,
            num_results=5,
        )
        if graph_results:
            facts = [r["fact"] for r in graph_results if r.get("fact")]
            if facts:
                graph_context = "\n--- Connaissances du graphe ---\n" + "\n".join(f"- {f}" for f in facts)
    except Exception:
        pass
```

- [ ] **Step 2: Injecter dans le system prompt**

Dans `bot/core/prompts.py`, ajouter un paramètre `graph_context: str = ""` à `build_system_prompt()`. L'injecter après le `memory_context` :

```python
if graph_context:
    parts.append(graph_context)
```

- [ ] **Step 3: Même chose pour Twitch**

Même pattern dans `bot/twitch/handlers.py`.

- [ ] **Step 4: Tests**

Vérifier que `build_system_prompt()` inclut le graph_context quand fourni.

- [ ] **Step 5: Commit**

```bash
git add bot/discord/handlers.py bot/twitch/handlers.py bot/core/prompts.py tests/
git commit -m "feat(graph): inject knowledge graph context into system prompts"
```

---

### Task 5: Signaux sociaux — module social.py

**Files:**
- Create: `bot/discord/social.py`
- Modify: `bot/discord/bot.py`
- Create: `tests/test_social.py`

- [ ] **Step 1: Créer bot/discord/social.py**

Module qui capture 6 types de signaux sociaux Discord et les stocke comme arêtes dans Neo4j.

```python
"""Social signal capture — feeds Discord social interactions into the knowledge graph."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.core.graph import GraphService
    import discord


class SocialTracker:
    """Tracks social interactions and flushes to the knowledge graph."""

    FLUSH_INTERVAL = 300  # 5 minutes

    def __init__(self, graph: "GraphService"):
        self._graph = graph
        # Buffers: (user_a, user_b, signal_type) -> {count, metadata}
        self._buffer: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "last_seen": 0.0, "metadata": {}}
        )
        # Voice state: channel_id -> {user_id: join_time}
        self._voice_sessions: dict[int, dict[int, float]] = defaultdict(dict)
        self._flush_task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the periodic flush loop."""
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        """Periodically flush buffered signals to Neo4j."""
        while True:
            await asyncio.sleep(self.FLUSH_INTERVAL)
            await self.flush()

    async def flush(self) -> None:
        """Write buffered signals to the knowledge graph."""
        if not self._graph.ready or not self._buffer:
            return
        buffer = dict(self._buffer)
        self._buffer.clear()
        for (user_a, user_b, signal_type), data in buffer.items():
            try:
                # Store as an episode describing the social signal
                content = self._format_signal(user_a, user_b, signal_type, data)
                await self._graph.add_episode(
                    content=content,
                    author="system",
                    source="social_tracker",
                )
            except Exception as exc:
                logger.debug("Social signal flush failed: {e}", e=exc)

    def _format_signal(self, user_a: str, user_b: str, signal_type: str, data: dict) -> str:
        """Format a social signal as natural language for Graphiti ingestion."""
        count = data["count"]
        meta = data.get("metadata", {})
        templates = {
            "voice": f"{user_a} et {user_b} ont passé du temps en vocal ensemble ({count} sessions)",
            "reply": f"{user_a} a répondu à {user_b} ({count} fois)",
            "mention": f"{user_a} a mentionné {user_b} ({count} fois)",
            "reaction": f"{user_a} a réagi aux messages de {user_b} ({count} fois)",
            "thread": f"{user_a} et {user_b} ont participé au même thread ({count} fois)",
            "game": f"{user_a} et {user_b} ont joué à {meta.get('game', 'un jeu')} ensemble ({count} fois)",
        }
        return templates.get(signal_type, f"{user_a} interagit avec {user_b}")

    def _key(self, a: str, b: str) -> tuple[str, str]:
        """Normalize pair order (alphabetical) for consistent keys."""
        return (min(a, b), max(a, b))

    # ── Event handlers ──

    def on_reply(self, author_name: str, replied_to_name: str) -> None:
        a, b = self._key(author_name, replied_to_name)
        self._buffer[(a, b, "reply")]["count"] += 1
        self._buffer[(a, b, "reply")]["last_seen"] = time.time()

    def on_mention(self, author_name: str, mentioned_name: str) -> None:
        a, b = self._key(author_name, mentioned_name)
        self._buffer[(a, b, "mention")]["count"] += 1
        self._buffer[(a, b, "mention")]["last_seen"] = time.time()

    def on_reaction(self, reactor_name: str, message_author_name: str) -> None:
        if reactor_name == message_author_name:
            return
        a, b = self._key(reactor_name, message_author_name)
        self._buffer[(a, b, "reaction")]["count"] += 1
        self._buffer[(a, b, "reaction")]["last_seen"] = time.time()

    def on_thread_message(self, author_name: str, other_participant: str) -> None:
        if author_name == other_participant:
            return
        a, b = self._key(author_name, other_participant)
        self._buffer[(a, b, "thread")]["count"] += 1
        self._buffer[(a, b, "thread")]["last_seen"] = time.time()

    def on_game_together(self, user_a_name: str, user_b_name: str, game: str) -> None:
        a, b = self._key(user_a_name, user_b_name)
        key = (a, b, "game")
        self._buffer[key]["count"] += 1
        self._buffer[key]["last_seen"] = time.time()
        self._buffer[key]["metadata"]["game"] = game

    def on_voice_join(self, channel_id: int, user_id: int, display_name: str) -> None:
        """Track when a user joins a voice channel."""
        self._voice_sessions[channel_id][user_id] = time.time()

    def on_voice_leave(self, channel_id: int, user_id: int, display_name: str) -> None:
        """When a user leaves voice, record co-presence with others still in channel."""
        join_time = self._voice_sessions.get(channel_id, {}).pop(user_id, None)
        if join_time is None:
            return
        # Record co-presence with everyone still in the channel
        for other_uid in self._voice_sessions.get(channel_id, {}):
            # We'd need display_name mapping — for now just use IDs
            a, b = self._key(str(user_id), str(other_uid))
            self._buffer[(a, b, "voice")]["count"] += 1
            self._buffer[(a, b, "voice")]["last_seen"] = time.time()

    async def stop(self) -> None:
        """Stop flush loop and final flush."""
        if self._flush_task:
            self._flush_task.cancel()
            self._flush_task = None
        await self.flush()
```

- [ ] **Step 2: Enregistrer les event listeners dans bot.py**

Dans `bot/discord/bot.py`, ajouter les événements Discord :

```python
# In setup_hook or __init__:
from bot.discord.social import SocialTracker
self.social = SocialTracker(self.graph)
self.social.start()

# Event: voice state
@self.event
async def on_voice_state_update(member, before, after):
    if before.channel != after.channel:
        if before.channel:
            self.social.on_voice_leave(before.channel.id, member.id, member.display_name)
        if after.channel:
            self.social.on_voice_join(after.channel.id, member.id, member.display_name)

# Event: reactions
@self.event
async def on_reaction_add(reaction, user):
    if not user.bot and reaction.message.author != user:
        self.social.on_reaction(user.display_name, reaction.message.author.display_name)

# Event: presence (game activity)
@self.event
async def on_presence_update(before, after):
    # Check if user started playing a game
    if after.activity and after.activity.type == discord.ActivityType.playing:
        game = after.activity.name
        # Check other members in same guild playing same game
        for member in after.guild.members:
            if member != after and member.activity and member.activity.name == game:
                self.social.on_game_together(after.display_name, member.display_name, game)
```

Dans `handlers.py`, ajouter les appels pour reply/mention/thread :

```python
# In on_message handler, after existing logic:
if message.reference and message.reference.resolved:
    bot.social.on_reply(message.author.display_name, message.reference.resolved.author.display_name)
for mentioned in message.mentions:
    if not mentioned.bot:
        bot.social.on_mention(message.author.display_name, mentioned.display_name)
if message.thread:
    # Track thread co-participation with recent thread members
    ...
```

- [ ] **Step 3: Tests**

```python
# tests/test_social.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from bot.discord.social import SocialTracker


def test_reply_tracked():
    graph = MagicMock()
    graph.ready = False
    tracker = SocialTracker(graph)
    tracker.on_reply("Alice", "Bob")
    tracker.on_reply("Alice", "Bob")
    key = ("Alice", "Bob", "reply")
    assert tracker._buffer[key]["count"] == 2


def test_self_reaction_ignored():
    graph = MagicMock()
    graph.ready = False
    tracker = SocialTracker(graph)
    tracker.on_reaction("Alice", "Alice")
    assert len(tracker._buffer) == 0


def test_key_normalization():
    graph = MagicMock()
    tracker = SocialTracker(graph)
    tracker.on_mention("Bob", "Alice")
    tracker.on_mention("Alice", "Bob")
    # Both should end up in the same key (alphabetical order)
    key = ("Alice", "Bob", "mention")
    assert tracker._buffer[key]["count"] == 2


@pytest.mark.asyncio
async def test_flush_clears_buffer():
    graph = AsyncMock()
    graph.ready = True
    graph.add_episode = AsyncMock(return_value=None)
    tracker = SocialTracker(graph)
    tracker.on_reply("Alice", "Bob")
    await tracker.flush()
    assert len(tracker._buffer) == 0
    graph.add_episode.assert_called_once()
```

- [ ] **Step 4: Commit**

```bash
git add bot/discord/social.py bot/discord/bot.py bot/discord/handlers.py tests/test_social.py
git commit -m "feat(social): capture voice/reply/mention/reaction/game signals for knowledge graph"
```

---

### Task 6: Score d'affinité

**Files:**
- Modify: `bot/core/graph.py`
- Modify: `config.yaml`

- [ ] **Step 1: Ajouter la méthode get_affinity dans GraphService**

```python
async def get_affinity(self, user_a: str, user_b: str, group_id: str | None = None) -> float:
    """Calculate affinity score between two users based on graph edges."""
    if not self.ready:
        return 0.0
    try:
        gid = group_id or self._config.graphiti.group_id
        # Search for edges involving both users
        edges = await self._graphiti.search(
            query=f"{user_a} {user_b}",
            group_ids=[gid],
            num_results=20,
        )
        weights = self._config.graphiti.affinity_weights
        score = 0.0
        for edge in edges:
            fact = (edge.fact or "").lower()
            if "vocal" in fact:
                score += weights.get("voice", 3.0)
            elif "répondu" in fact:
                score += weights.get("reply", 2.0)
            elif "mentionné" in fact:
                score += weights.get("mention", 1.5)
            elif "réagi" in fact:
                score += weights.get("reaction", 1.0)
            elif "thread" in fact:
                score += weights.get("thread", 1.0)
            elif "joué" in fact:
                score += weights.get("game", 2.5)
        return score
    except Exception as exc:
        logger.warning("Affinity calculation failed: {e}", e=exc)
        return 0.0
```

- [ ] **Step 2: Config des poids**

```yaml
graphiti:
  affinity_weights:
    voice: 3.0
    reply: 2.0
    mention: 1.5
    reaction: 1.0
    thread: 1.0
    game: 2.5
```

- [ ] **Step 3: Injection dans les prompts**

Dans les handlers, après le graph_context, ajouter un bloc affinité pour les utilisateurs mentionnés dans la conversation courante.

- [ ] **Step 4: Commit**

```bash
git add bot/core/graph.py config.yaml bot/config.py
git commit -m "feat(graph): affinity score calculation from social graph edges"
```

---

### Task 7: API dashboard pour le graphe social

**Files:**
- Create: `bot/dashboard/routes/graph.py`
- Modify: `bot/dashboard/routes/__init__.py` ou équivalent

- [ ] **Step 1: Créer les endpoints API**

```python
# bot/dashboard/routes/graph.py
"""Social graph API endpoints."""
from fastapi import APIRouter, Request
from loguru import logger

router = APIRouter(prefix="/api/social-graph", tags=["graph"])


@router.get("/nodes")
async def get_nodes(request: Request):
    """Return all entity nodes for the social graph visualization."""
    graph = request.app.state.graph
    if not graph or not graph.ready:
        return {"nodes": [], "edges": []}
    try:
        # Query Neo4j directly for visualization data
        driver = graph._graphiti._driver
        async with driver.session() as session:
            # Get User entities
            result = await session.run(
                "MATCH (n:Entity) "
                "WHERE n.group_id = $gid "
                "RETURN n.uuid AS id, n.name AS name, n.summary AS summary, "
                "       labels(n) AS labels "
                "LIMIT 200",
                {"gid": graph._config.graphiti.group_id},
            )
            nodes = [dict(record) async for record in result]

            # Get relationships
            result = await session.run(
                "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
                "WHERE a.group_id = $gid AND r.invalid_at IS NULL "
                "RETURN a.uuid AS source, b.uuid AS target, "
                "       r.name AS type, r.fact AS fact "
                "LIMIT 500",
                {"gid": graph._config.graphiti.group_id},
            )
            edges = [dict(record) async for record in result]

        return {"nodes": nodes, "edges": edges}
    except Exception as exc:
        logger.warning("Social graph query failed: {e}", e=exc)
        return {"nodes": [], "edges": []}


@router.get("/affinity/{user_a}/{user_b}")
async def get_affinity(user_a: str, user_b: str, request: Request):
    """Get affinity score between two users."""
    graph = request.app.state.graph
    if not graph or not graph.ready:
        return {"score": 0.0}
    score = await graph.get_affinity(user_a, user_b)
    return {"score": score}
```

- [ ] **Step 2: Monter le router dans l'app FastAPI**

- [ ] **Step 3: Commit**

```bash
git add bot/dashboard/routes/graph.py
git commit -m "feat(dashboard): add social graph API endpoints"
```

---

### Task 8: Visualisation — page /graph avec neovis.js

**Files:**
- Modify: `bot/dashboard/static/app.js`
- Modify: templates HTML si nécessaire

- [ ] **Step 1: Ajouter le CDN neovis.js**

Dans le HTML du dashboard, ajouter :
```html
<script src="https://unpkg.com/neovis.js@2.1.0/dist/neovis-without-dependencies.js"></script>
```

Ou mieux, télécharger le fichier et le servir depuis `bot/dashboard/static/`.

- [ ] **Step 2: Créer la page graphe dans app.js**

Route publique accessible aux membres Discord authentifiés. Rendu avec neovis.js connecté via l'API backend `/api/social-graph/nodes` (pas de connexion Bolt directe).

Fonctionnalités :
- Noeuds colorés et dimensionnés par centralité
- Arêtes colorées par type (vocal=violet, réponses=bleu, réactions=jaune, jeux=vert)
- Épaisseur proportionnelle au compteur
- Clic noeud → panneau latéral (résumé, relations)
- Filtres par type et période
- Style glassmorphism

- [ ] **Step 3: Ajouter l'onglet dans la navigation**

Nouveau sous-onglet "Graphe social" dans la section Mémoire du dashboard.

- [ ] **Step 4: Auth Discord pour la page publique**

Vérifier que la page est accessible aux membres Discord authentifiés (JWT existant), pas seulement aux admins.

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/static/
git commit -m "feat(dashboard): social graph visualization with neovis.js"
```

---

### Task 9: Multi-instance — Neo4j dans le provisioner

**Files:**
- Modify: `bot/core/provisioner.py`

- [ ] **Step 1: Ajouter neo4j au docker-compose des instances**

Dans `provision_instance()`, ajouter le service `neo4j` au docker-compose template des instances. Utiliser un port différent par instance (`NEO4J_BOLT_PORT`, `NEO4J_BROWSER_PORT`).

- [ ] **Step 2: Ajouter les env vars neo4j au .env des instances**

- [ ] **Step 3: Commit**

```bash
git add bot/core/provisioner.py
git commit -m "feat(provisioner): add Neo4j service to provisioned instances"
```

---

### Task 10: Tests d'intégration + push final

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

- [ ] **Step 2: Test manuel**

```bash
docker compose up -d --build
# Vérifier Neo4j Browser sur :7474
# Vérifier que le bot démarre sans erreur
# Envoyer un message et vérifier les logs "Graph episode added"
```

- [ ] **Step 3: Activer graphiti dans config**

Mettre `graphiti.enabled: true` dans `config.yaml`.

- [ ] **Step 4: Push**

```bash
git push origin main
```
