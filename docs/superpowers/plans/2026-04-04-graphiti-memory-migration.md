# Graphiti Memory Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer Qdrant par Graphiti/Neo4j comme backend principal de mémoire long-terme, via 3 flags de config permettant une transition progressive sans coupure.

**Architecture:** Trois flags dans `GraphitiConfig` (`memory_write`, `memory_primary`, `memory_dual_read`) commandent le routing dans `MemoryService`. Un nouveau module `bot/core/graph_memory.py` encapsule les deux opérations utilisateur (write + search). Qdrant reste lisible en read-only pendant la transition ; Graphiti gère la déduplication nativement.

**Tech Stack:** Python asyncio, graphiti-core ≥0.28.0, Neo4j (Cypher), pytest + pytest-asyncio, unittest.mock

---

## File Map

| Action | Fichier | Rôle |
|--------|---------|------|
| Modify | `bot/config.py:253` | +3 flags dans `GraphitiConfig` |
| Modify | `bot/core/graph.py` | +2 méthodes : `get_entity_uuid()`, `search_by_entity()` |
| **Create** | `bot/core/graph_memory.py` | `add_user_fact()` + `search_user_facts()` |
| Modify | `bot/core/memory.py` | `set_graph()`, routing dans `add()`, `search()`, `_post_add_maintenance()` |
| Modify | `bot/main.py:112` | `memory.set_graph(graph)` |
| **Create** | `tests/test_graph_memory.py` | Tests du nouveau module |
| Modify | `tests/test_graph.py` | +3 tests pour les nouvelles méthodes graph |
| Modify | `tests/test_memory.py` | +4 tests pour le routing memory |

---

## Task 1: Config flags — 3 nouveaux champs dans GraphitiConfig

**Files:**
- Modify: `bot/config.py:241-253`

- [ ] **Step 1: Lire le fichier avant édition**

```bash
grep -n "graph_context_max_tokens" bot/config.py
```
Expected: `253:    graph_context_max_tokens: int = 400`

- [ ] **Step 2: Ajouter les 3 flags**

Dans `bot/config.py`, après la ligne `graph_context_max_tokens: int = 400` (ligne 253), ajouter :

```python
    memory_write: bool = False      # true = écriture vers Graphiti, Qdrant gelé
    memory_primary: bool = False    # true = lecture depuis Graphiti en priorité
    memory_dual_read: bool = True   # true = merge Graphiti + Qdrant (transition)
```

- [ ] **Step 3: Vérifier l'édition**

```bash
grep -A5 "graph_context_max_tokens" bot/config.py
```
Expected: les 3 nouveaux flags apparaissent sous `graph_context_max_tokens`.

- [ ] **Step 4: Lancer les tests existants**

```bash
pytest tests/test_graph.py -v -q
```
Expected: tous PASS (aucun test ne touche les nouveaux flags encore).

- [ ] **Step 5: Commit**

```bash
git add bot/config.py
git commit -m "feat(config): add memory_write/memory_primary/memory_dual_read flags to GraphitiConfig"
```

---

## Task 2: GraphService — get_entity_uuid() et search_by_entity()

**Files:**
- Modify: `bot/core/graph.py`
- Modify: `tests/test_graph.py`

- [ ] **Step 1: Écrire les tests qui vont échouer**

Ajouter à la fin de `tests/test_graph.py` :

```python
@pytest.mark.asyncio
async def test_get_entity_uuid_found():
    """get_entity_uuid() returns UUID string when entity exists."""
    svc = GraphService(_make_config())
    svc._ready = True
    svc._graphiti = MagicMock()

    mock_record = MagicMock()
    mock_record.__getitem__ = lambda self, k: "uuid-abc-123" if k == "uuid" else None

    mock_result = MagicMock()
    mock_result.records = [mock_record]
    svc._graphiti.driver = AsyncMock()
    svc._graphiti.driver.execute_query = AsyncMock(return_value=mock_result)

    result = await svc.get_entity_uuid("KingsRequin")
    assert result == "uuid-abc-123"
    svc._graphiti.driver.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_get_entity_uuid_not_found_returns_none():
    """get_entity_uuid() returns None when entity doesn't exist."""
    svc = GraphService(_make_config())
    svc._ready = True
    svc._graphiti = MagicMock()

    mock_result = MagicMock()
    mock_result.records = []
    svc._graphiti.driver = AsyncMock()
    svc._graphiti.driver.execute_query = AsyncMock(return_value=mock_result)

    result = await svc.get_entity_uuid("UnknownUser")
    assert result is None


@pytest.mark.asyncio
async def test_get_entity_uuid_returns_none_when_not_ready():
    """get_entity_uuid() returns None when graph not ready."""
    svc = GraphService(_make_config())
    result = await svc.get_entity_uuid("KingsRequin")
    assert result is None


@pytest.mark.asyncio
async def test_search_by_entity_with_center_node():
    """search_by_entity() calls graphiti.search with center_node_uuid."""
    svc = GraphService(_make_config())
    svc._ready = True
    svc._graphiti = MagicMock()

    mock_edge = MagicMock()
    mock_edge.fact = "KingsRequin aime le café"
    mock_edge.valid_at = None
    mock_edge.invalid_at = None
    svc._graphiti.search = AsyncMock(return_value=[mock_edge])

    results = await svc.search_by_entity("café", "uuid-abc-123", limit=5)
    assert len(results) == 1
    assert results[0]["fact"] == "KingsRequin aime le café"

    call_kwargs = svc._graphiti.search.call_args[1]
    assert call_kwargs.get("center_node_uuid") == "uuid-abc-123"
    assert call_kwargs.get("num_results") == 5


@pytest.mark.asyncio
async def test_search_by_entity_returns_empty_when_not_ready():
    """search_by_entity() returns [] when graph not ready."""
    svc = GraphService(_make_config())
    results = await svc.search_by_entity("café", "uuid-abc-123")
    assert results == []
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_graph.py::test_get_entity_uuid_found tests/test_graph.py::test_get_entity_uuid_not_found_returns_none tests/test_graph.py::test_search_by_entity_with_center_node -v
```
Expected: FAIL avec `AttributeError: 'GraphService' object has no attribute 'get_entity_uuid'`

- [ ] **Step 3: Lire graph.py avant édition**

```bash
grep -n "async def " bot/core/graph.py
```
Repérer la dernière méthode pour insérer après.

- [ ] **Step 4: Ajouter les deux méthodes dans graph.py**

Après la méthode `get_social_context()` (dernière méthode du fichier), ajouter :

```python
    async def get_entity_uuid(self, username: str) -> str | None:
        """Return the Neo4j UUID of an entity by exact or partial name match.

        Returns None if not ready or entity not found (never raises).
        """
        if not self.ready:
            return None
        try:
            gid = self._sanitize_group_id(self._config.graphiti.group_id)
            result = await self._graphiti.driver.execute_query(
                "MATCH (e:Entity {group_id: $gid}) "
                "WHERE toLower(e.name) = toLower($name) "
                "RETURN e.uuid AS uuid LIMIT 1",
                gid=gid,
                name=username,
            )
            if result.records:
                return result.records[0]["uuid"]
            # Fallback: partial match
            result2 = await self._graphiti.driver.execute_query(
                "MATCH (e:Entity {group_id: $gid}) "
                "WHERE toLower(e.name) CONTAINS toLower($name) "
                "RETURN e.uuid AS uuid LIMIT 1",
                gid=gid,
                name=username,
            )
            if result2.records:
                return result2.records[0]["uuid"]
            return None
        except Exception as exc:
            logger.warning("get_entity_uuid failed for {u}: {e}", u=username, e=exc)
            return None

    async def search_by_entity(
        self,
        query: str,
        center_node_uuid: str,
        limit: int = 8,
    ) -> list[dict]:
        """Search the graph centered on a specific entity node.

        Returns list of {"fact": str, "valid_at": str | None} dicts.
        Filters out facts with invalid_at set (superseded facts).
        Returns [] if not ready or on error.
        """
        if not self.ready:
            return []
        try:
            gid = self._sanitize_group_id(self._config.graphiti.group_id)
            edges = await self._graphiti.search(
                query=query,
                group_ids=[gid],
                center_node_uuid=center_node_uuid,
                num_results=limit,
            )
            return [
                {
                    "fact": edge.fact,
                    "valid_at": str(edge.valid_at) if edge.valid_at else None,
                }
                for edge in edges
                if edge.invalid_at is None
            ]
        except Exception as exc:
            logger.warning("search_by_entity failed: {e}", e=exc)
            return []
```

- [ ] **Step 5: Lancer les tests**

```bash
pytest tests/test_graph.py -v -q
```
Expected: tous PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/core/graph.py tests/test_graph.py
git commit -m "feat(graph): add get_entity_uuid() and search_by_entity() for user memory search"
```

---

## Task 3: graph_memory.py — add_user_fact() et search_user_facts()

**Files:**
- Create: `bot/core/graph_memory.py`
- Create: `tests/test_graph_memory.py`

- [ ] **Step 1: Écrire les tests qui vont échouer**

Créer `tests/test_graph_memory.py` :

```python
# tests/test_graph_memory.py
"""Tests for bot/core/graph_memory.py — user fact write/search helpers."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date


@pytest.fixture
def mock_graph():
    g = AsyncMock()
    g.ready = True
    g.add_episode = AsyncMock(return_value={"entities": [], "edges": []})
    g.get_entity_uuid = AsyncMock(return_value=None)
    g.search_by_entity = AsyncMock(return_value=[])
    g.search = AsyncMock(return_value=[])
    return g


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.graphiti.group_id = "discord:default"
    cfg.graphiti.memory_context_max_tokens = 800
    return cfg


@pytest.mark.asyncio
async def test_add_user_fact_calls_graph_add_episode(mock_graph, mock_config):
    """add_user_fact() calls graph.add_episode with correct name and body."""
    from bot.core.graph_memory import add_user_fact

    alias_cache = {}
    await add_user_fact(
        graph=mock_graph,
        config=mock_config,
        platform="discord",
        user_id="123456",
        username="KingsRequin",
        content="préfère le café au thé",
        category="PREF",
        alias_cache=alias_cache,
    )

    mock_graph.add_episode.assert_called_once()
    call_kwargs = mock_graph.add_episode.call_args[1]
    assert "KingsRequin" in call_kwargs["name"]
    assert "PREF" in call_kwargs["name"]
    assert call_kwargs["body"] == "KingsRequin : préfère le café au thé"
    assert "KingsRequin" in call_kwargs["source_desc"]


@pytest.mark.asyncio
async def test_add_user_fact_includes_aliases_in_source_desc(mock_graph, mock_config):
    """add_user_fact() injects known aliases into source_description."""
    from bot.core.graph_memory import add_user_fact

    alias_cache = {
        "nickname:requin": "discord:123456",
        "nickname:kings": "discord:123456",
        "nickname:other": "discord:999",
    }
    await add_user_fact(
        graph=mock_graph,
        config=mock_config,
        platform="discord",
        user_id="123456",
        username="KingsRequin",
        content="joue à Valorant",
        category="FAIT",
        alias_cache=alias_cache,
    )

    call_kwargs = mock_graph.add_episode.call_args[1]
    source_desc = call_kwargs["source_desc"]
    # Aliases belonging to this user should appear in source_desc
    assert "requin" in source_desc.lower() or "kings" in source_desc.lower()


@pytest.mark.asyncio
async def test_add_user_fact_does_nothing_when_graph_not_ready(mock_config):
    """add_user_fact() is a no-op when graph.ready is False."""
    from bot.core.graph_memory import add_user_fact

    graph = AsyncMock()
    graph.ready = False

    await add_user_fact(
        graph=graph,
        config=mock_config,
        platform="discord",
        user_id="123456",
        username="KingsRequin",
        content="aime le café",
        category="PREF",
        alias_cache={},
    )
    graph.add_episode.assert_not_called()


@pytest.mark.asyncio
async def test_search_user_facts_with_entity_uuid(mock_graph, mock_config):
    """search_user_facts() uses search_by_entity when UUID is found."""
    from bot.core.graph_memory import search_user_facts

    mock_graph.get_entity_uuid = AsyncMock(return_value="uuid-abc")
    mock_graph.search_by_entity = AsyncMock(return_value=[
        {"fact": "KingsRequin aime le café", "valid_at": "2026-04-01"},
        {"fact": "KingsRequin joue à Valorant", "valid_at": None},
    ])

    result = await search_user_facts(
        graph=mock_graph,
        config=mock_config,
        username="KingsRequin",
        query="café",
    )

    mock_graph.search_by_entity.assert_called_once_with("café", "uuid-abc", limit=8)
    assert "KingsRequin aime le café" in result
    assert "2026-04-01" in result


@pytest.mark.asyncio
async def test_search_user_facts_fallback_no_uuid(mock_graph, mock_config):
    """search_user_facts() falls back to graph.search when UUID not found."""
    from bot.core.graph_memory import search_user_facts

    mock_graph.get_entity_uuid = AsyncMock(return_value=None)
    mock_graph.search = AsyncMock(return_value=[
        {"fact": "KingsRequin aime le café", "valid_at": None},
    ])

    result = await search_user_facts(
        graph=mock_graph,
        config=mock_config,
        username="KingsRequin",
        query="café",
    )

    mock_graph.search_by_entity.assert_not_called()
    mock_graph.search.assert_called_once()
    assert "KingsRequin aime le café" in result


@pytest.mark.asyncio
async def test_search_user_facts_returns_empty_string_when_no_results(mock_graph, mock_config):
    """search_user_facts() returns empty string when graph has no matching facts."""
    from bot.core.graph_memory import search_user_facts

    mock_graph.get_entity_uuid = AsyncMock(return_value=None)
    mock_graph.search = AsyncMock(return_value=[])

    result = await search_user_facts(
        graph=mock_graph,
        config=mock_config,
        username="KingsRequin",
        query="café",
    )
    assert result == ""
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_graph_memory.py -v
```
Expected: FAIL avec `ModuleNotFoundError: No module named 'bot.core.graph_memory'`

- [ ] **Step 3: Créer bot/core/graph_memory.py**

```python
# bot/core/graph_memory.py
"""Graphiti-backed user memory helpers.

Two public functions, zero module-level state:
  - add_user_fact()     — write a categorised user fact as an episode
  - search_user_facts() — search facts for a given username
"""
from __future__ import annotations

from datetime import datetime, timezone
from loguru import logger


async def add_user_fact(
    graph,
    config,
    platform: str,
    user_id: str,
    username: str,
    content: str,
    category: str,
    alias_cache: dict[str, str],
) -> None:
    """Ingest a user fact into Graphiti as a named episode.

    Fire-and-forget safe: all exceptions are caught and logged.
    Does nothing when graph.ready is False.
    """
    if not graph or not graph.ready:
        return
    try:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        name = f"{username} — {category} — {date_str}"
        body = f"{username} : {content}"

        # Collect aliases that map to this user's platform:user_id
        raw_uid = f"{platform}:{user_id}"
        known_aliases = [
            alias.split(":", 1)[1]
            for alias, canonical in alias_cache.items()
            if canonical == raw_uid and alias.startswith("nickname:")
        ]
        alias_str = (
            f" Alias connus : {', '.join(known_aliases)}." if known_aliases else ""
        )
        source_desc = (
            f"Souvenir {platform}. Utilisateur : {username} ({platform}:{user_id}).{alias_str}"
        )

        await graph.add_episode(
            content=content,
            author=username,
            name=name,
            body=body,
            source_desc=source_desc,
            group_id=config.graphiti.group_id,
        )
        logger.debug("Graph memory added [{u}|{cat}]: {c}", u=username, cat=category, c=content[:80])
    except Exception as exc:
        logger.warning("graph_memory.add_user_fact failed for {u}: {e}", u=username, e=exc)


async def search_user_facts(
    graph,
    config,
    username: str,
    query: str,
    limit: int = 8,
) -> str:
    """Search Graphiti for facts about a specific user.

    Returns a plain string in the same format as Qdrant memory (one fact per line).
    Returns "" on error or when graph not ready.
    """
    if not graph or not graph.ready:
        return ""
    try:
        uuid = await graph.get_entity_uuid(username)
        if uuid:
            results = await graph.search_by_entity(query, uuid, limit=limit)
        else:
            # Fallback: prefix query with username for scoped search
            raw = await graph.search(f"{username} {query}", num_results=limit)
            # graph.search returns list[dict] with keys fact/valid_at/invalid_at/name
            results = [
                {"fact": r.get("fact", ""), "valid_at": r.get("valid_at")}
                for r in raw
                if r.get("invalid_at") is None
            ]

        if not results:
            return ""

        lines = []
        for r in results:
            fact = r.get("fact", "").strip()
            if not fact:
                continue
            valid_at = r.get("valid_at")
            if valid_at:
                # Truncate to date only if it's a full datetime string
                date_part = str(valid_at)[:10]
                lines.append(f"{fact} [depuis {date_part}]")
            else:
                lines.append(fact)
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("graph_memory.search_user_facts failed for {u}: {e}", u=username, e=exc)
        return ""
```

- [ ] **Step 4: Corriger l'appel add_episode — lire la signature exacte**

La méthode `graph.add_episode()` dans `bot/core/graph.py` prend `(content, author, source, group_id, update_communities)` — pas `name`, `body`, `source_desc`. Il faut adapter `add_user_fact()` pour utiliser le format `body` comme `content` et `source_desc` comme `source` :

Remplacer le bloc `await graph.add_episode(...)` dans `graph_memory.py` par :

```python
        await graph.add_episode(
            content=body,
            author=username,
            source=source_desc,
            group_id=config.graphiti.group_id,
        )
```

Et adapter les tests pour mocker `add_episode` avec les bons kwargs :

```python
    call_kwargs = mock_graph.add_episode.call_args[1]
    assert "KingsRequin" in call_kwargs["content"]
    assert call_kwargs["content"] == "KingsRequin : préfère le café au thé"
    assert "KingsRequin" in call_kwargs["source"]
```

> **Note :** `graph.add_episode()` reçoit `name` et `body` séparément dans la spec Graphiti mais `GraphService.add_episode()` les construit en interne. On passe `content=body` et laisse GraphService formater.

- [ ] **Step 5: Lancer les tests**

```bash
pytest tests/test_graph_memory.py -v
```
Expected: tous PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/core/graph_memory.py tests/test_graph_memory.py
git commit -m "feat(graph_memory): add add_user_fact() and search_user_facts() for Graphiti memory backend"
```

---

## Task 4: MemoryService — set_graph() + routing dans add()

**Files:**
- Modify: `bot/core/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Écrire les tests qui vont échouer**

Repérer la fin de `tests/test_memory.py` et ajouter :

```python
# ── Graphiti routing tests ─────────────────────────────────────────────────

def _make_memory_with_graph(memory_write=False, memory_primary=False, memory_dual_read=True):
    """Helper: MemoryService with graph set and config flags."""
    from bot.core.memory import MemoryService
    from unittest.mock import MagicMock, AsyncMock

    config = MagicMock()
    config.bot.memory_search_min_score = 0.5
    config.bot.memory_context_max_tokens = 800
    config.graphiti.memory_write = memory_write
    config.graphiti.memory_primary = memory_primary
    config.graphiti.memory_dual_read = memory_dual_read
    config.graphiti.group_id = "discord:default"

    svc = MemoryService(config)

    graph = AsyncMock()
    graph.ready = True
    svc.set_graph(graph)

    return svc, graph


@pytest.mark.asyncio
async def test_set_graph_stores_reference():
    """set_graph() stores the graph service reference."""
    from bot.core.memory import MemoryService
    from unittest.mock import MagicMock, AsyncMock

    config = MagicMock()
    svc = MemoryService(config)
    graph = AsyncMock()
    svc.set_graph(graph)
    assert svc._graph is graph


@pytest.mark.asyncio
async def test_add_routes_to_graphiti_when_memory_write_true():
    """add() calls graph_memory.add_user_fact when memory_write=True."""
    svc, graph = _make_memory_with_graph(memory_write=True)

    with patch("bot.core.memory.graph_memory") as mock_gm:
        mock_gm.add_user_fact = AsyncMock()
        await svc.add("discord", "123456", "aime le café", username="KingsRequin", category="PREF")

    mock_gm.add_user_fact.assert_called_once()
    call_kwargs = mock_gm.add_user_fact.call_args[1]
    assert call_kwargs["username"] == "KingsRequin"
    assert call_kwargs["content"] == "aime le café"
    assert call_kwargs["category"] == "PREF"


@pytest.mark.asyncio
async def test_add_skips_qdrant_when_memory_write_true():
    """add() does NOT call _store.upsert when memory_write=True."""
    svc, graph = _make_memory_with_graph(memory_write=True)
    svc._store = MagicMock()
    svc._store.upsert = AsyncMock()

    with patch("bot.core.memory.graph_memory") as mock_gm:
        mock_gm.add_user_fact = AsyncMock()
        await svc.add("discord", "123456", "aime le café", username="KingsRequin")

    svc._store.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_add_uses_qdrant_when_memory_write_false():
    """add() calls _store.upsert (Qdrant) when memory_write=False (default)."""
    svc, graph = _make_memory_with_graph(memory_write=False)
    svc._store = MagicMock()
    svc._store.upsert = AsyncMock()
    svc._store_init_attempted = True  # skip lazy init

    await svc.add("discord", "123456", "aime le café", username="KingsRequin")

    svc._store.upsert.assert_called_once()
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_memory.py::test_set_graph_stores_reference tests/test_memory.py::test_add_routes_to_graphiti_when_memory_write_true -v
```
Expected: FAIL avec `AttributeError: 'MemoryService' object has no attribute 'set_graph'`

- [ ] **Step 3: Lire memory.py avant édition**

```bash
grep -n "def set_openai_client\|def set_db\|def _fire\|async def add\b" bot/core/memory.py
```

- [ ] **Step 4: Ajouter set_graph() dans MemoryService**

Après `set_db()` (ligne ~79), ajouter :

```python
    def set_graph(self, graph) -> None:
        self._graph = graph
```

Et dans `__init__`, ajouter l'initialisation :

```python
        self._graph = None
```

(chercher `self._openai = None` dans `__init__` et ajouter `self._graph = None` juste dessous)

- [ ] **Step 5: Ajouter l'import de graph_memory et le routing dans add()**

En haut de `bot/core/memory.py`, ajouter l'import :

```python
from bot.core import graph_memory
```

Dans `add()` (ligne ~162), au début de la méthode, avant `self._init_store()` :

```python
    async def add(self, platform: str, user_id: str, content: str,
                  username: str = "", emotion_context: str = "",
                  category: str = "") -> None:
        # Route to Graphiti when memory_write flag is enabled
        if getattr(self._config.graphiti, "memory_write", False) and self._graph:
            self._fire(graph_memory.add_user_fact(
                graph=self._graph,
                config=self._config,
                platform=platform,
                user_id=user_id,
                username=username,
                content=content,
                category=category or "FAIT",
                alias_cache=self._alias_cache,
            ))
            return
        # Existing Qdrant path below (unchanged)
        self._init_store()
        ...
```

- [ ] **Step 6: Lancer les tests**

```bash
pytest tests/test_memory.py -v -q
```
Expected: tous PASS.

- [ ] **Step 7: Commit**

```bash
git add bot/core/memory.py tests/test_memory.py
git commit -m "feat(memory): add set_graph() and route add() to Graphiti when memory_write=True"
```

---

## Task 5: MemoryService — routing dans search() + _merge_contexts()

**Files:**
- Modify: `bot/core/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Écrire les tests qui vont échouer**

Ajouter dans `tests/test_memory.py` :

```python
@pytest.mark.asyncio
async def test_search_returns_graphiti_when_memory_primary_true():
    """search() calls graph_memory.search_user_facts when memory_primary=True."""
    svc, graph = _make_memory_with_graph(memory_primary=True, memory_dual_read=False)

    with patch("bot.core.memory.graph_memory") as mock_gm:
        mock_gm.search_user_facts = AsyncMock(return_value="KingsRequin aime le café")
        result = await svc.search("discord", "123456", "café", username_hint="KingsRequin")

    mock_gm.search_user_facts.assert_called_once()
    assert "KingsRequin aime le café" in result


@pytest.mark.asyncio
async def test_search_dual_read_merges_results():
    """search() merges Graphiti + Qdrant results when memory_primary=True + dual_read=True."""
    svc, graph = _make_memory_with_graph(memory_primary=True, memory_dual_read=True)
    svc._store = MagicMock()
    svc._store.search = AsyncMock(return_value=[
        MagicMock(text="souvenir qdrant", score=0.8),
    ])
    svc._store_init_attempted = True

    with patch("bot.core.memory.graph_memory") as mock_gm:
        mock_gm.search_user_facts = AsyncMock(return_value="fait graphiti")
        result = await svc.search("discord", "123456", "test", username_hint="KingsRequin")

    assert "fait graphiti" in result
    assert "souvenir qdrant" in result


@pytest.mark.asyncio
async def test_search_uses_qdrant_when_memory_primary_false():
    """search() uses Qdrant only when memory_primary=False (default)."""
    svc, graph = _make_memory_with_graph(memory_primary=False)
    svc._store = MagicMock()
    svc._store.search = AsyncMock(return_value=[
        MagicMock(text="souvenir qdrant", score=0.9),
    ])
    svc._store_init_attempted = True

    with patch("bot.core.memory.graph_memory") as mock_gm:
        mock_gm.search_user_facts = AsyncMock(return_value="fait graphiti")
        result = await svc.search("discord", "123456", "test")

    mock_gm.search_user_facts.assert_not_called()
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_memory.py::test_search_returns_graphiti_when_memory_primary_true tests/test_memory.py::test_search_dual_read_merges_results -v
```
Expected: FAIL (signature de search() sans `username_hint` ou routing manquant).

- [ ] **Step 3: Ajouter username_hint à search() et le routing**

Lire la signature actuelle de `search()` dans `memory.py` (ligne ~462), puis modifier :

```python
    async def search(
        self, platform: str, user_id: str, query: str,
        context_messages: list[dict] | None = None,
        username_hint: str = "",
    ) -> str:
        # Route to Graphiti when memory_primary flag is enabled
        if getattr(self._config.graphiti, "memory_primary", False) and self._graph:
            graphiti_ctx = await graph_memory.search_user_facts(
                graph=self._graph,
                config=self._config,
                username=username_hint or user_id,
                query=query,
            )
            if getattr(self._config.graphiti, "memory_dual_read", True):
                qdrant_ctx = await self._qdrant_search(platform, user_id, query, context_messages)
                return self._merge_contexts(graphiti_ctx, qdrant_ctx)
            return graphiti_ctx
        # Existing Qdrant path (renamed to helper)
        return await self._qdrant_search(platform, user_id, query, context_messages)
```

- [ ] **Step 4: Extraire _qdrant_search() depuis l'ancien body de search()**

Renommer le corps actuel de `search()` (tout le code Qdrant) en `_qdrant_search()` :

```python
    async def _qdrant_search(
        self, platform: str, user_id: str, query: str,
        context_messages: list[dict] | None = None,
    ) -> str:
        """Existing Qdrant search logic — unchanged."""
        self._init_store()
        if self._store is None:
            return ""
        if not query or not query.strip():
            return ""
        # ... (tout le code existant de search() à partir de self._init_store())
```

- [ ] **Step 5: Ajouter _merge_contexts()**

À la fin de la classe `MemoryService`, ajouter :

```python
    @staticmethod
    def _merge_contexts(graphiti_ctx: str, qdrant_ctx: str) -> str:
        """Merge Graphiti and Qdrant memory contexts.

        Graphiti first (recent, deduplicated), Qdrant below separated by ---
        Returns empty string if both are empty.
        """
        parts = []
        if graphiti_ctx and graphiti_ctx.strip():
            parts.append(graphiti_ctx.strip())
        if qdrant_ctx and qdrant_ctx.strip():
            parts.append(qdrant_ctx.strip())
        return "\n---\n".join(parts)
```

- [ ] **Step 6: Lancer les tests**

```bash
pytest tests/test_memory.py -v -q
```
Expected: tous PASS.

- [ ] **Step 7: Vérifier que les callers de search() fonctionnent toujours**

```bash
grep -rn "memory\.search(" bot/ --include="*.py" | grep -v "test_"
```
Vérifier que tous les appels ont au plus `platform, user_id, query, context_messages` — le nouveau `username_hint` est optionnel (défaut `""`), rétrocompatible.

Ensuite mettre à jour les handlers qui connaissent le username pour passer `username_hint` :

```bash
grep -n "memory.search(" bot/discord/handlers.py bot/twitch/handlers.py
```

Pour chaque appel `memory.search(platform, user_id, query, ...)`, si le username est disponible, ajouter `username_hint=username`.

- [ ] **Step 8: Lancer les tests complets**

```bash
pytest -v -q
```
Expected: tous PASS.

- [ ] **Step 9: Commit**

```bash
git add bot/core/memory.py tests/test_memory.py bot/discord/handlers.py bot/twitch/handlers.py
git commit -m "feat(memory): route search() to Graphiti when memory_primary=True, add _merge_contexts()"
```

---

## Task 6: MemoryService — skip _post_add_maintenance() quand memory_write=True

**Files:**
- Modify: `bot/core/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Écrire le test qui va échouer**

Ajouter dans `tests/test_memory.py` :

```python
@pytest.mark.asyncio
async def test_post_add_maintenance_skipped_when_memory_write_true():
    """_post_add_maintenance() returns early when memory_write=True (Graphiti deduplicates natively)."""
    svc, graph = _make_memory_with_graph(memory_write=True)
    svc._store = MagicMock()
    svc._store.get_all = AsyncMock(return_value=[])
    svc._store_init_attempted = True

    # Should return immediately without calling get_all
    await svc._post_add_maintenance("discord:123456", "test content")

    svc._store.get_all.assert_not_called()
```

- [ ] **Step 2: Vérifier que le test échoue**

```bash
pytest tests/test_memory.py::test_post_add_maintenance_skipped_when_memory_write_true -v
```
Expected: FAIL (get_all est appelé même quand memory_write=True).

- [ ] **Step 3: Modifier _post_add_maintenance()**

Dans `bot/core/memory.py`, au début de `_post_add_maintenance()` (ligne ~247), ajouter le guard :

```python
    async def _post_add_maintenance(self, uid: str, content: str) -> None:
        """Run consolidation (if threshold exceeded) or evaluation — single get_all."""
        # Graphiti handles deduplication natively — skip Qdrant maintenance
        if getattr(self._config.graphiti, "memory_write", False):
            return
        if self._store is None:
            return
        # ... reste du code existant inchangé
```

- [ ] **Step 4: Lancer les tests**

```bash
pytest tests/test_memory.py -v -q
```
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/core/memory.py tests/test_memory.py
git commit -m "feat(memory): skip Qdrant consolidation in _post_add_maintenance when memory_write=True"
```

---

## Task 7: main.py — wirer memory.set_graph(graph)

**Files:**
- Modify: `bot/main.py:112`

- [ ] **Step 1: Lire main.py autour de la ligne 112**

```bash
grep -n "memory\." bot/main.py | head -20
```

- [ ] **Step 2: Ajouter memory.set_graph(graph)**

Après `memory.set_db(db)` (ligne ~112), ajouter :

```python
    memory.set_graph(graph)
```

Le bloc résultant doit ressembler à :

```python
    memory.set_openai_client(secondary_llm)
    memory.set_db(db)
    memory.set_graph(graph)
    await memory.load_aliases(db)
```

- [ ] **Step 3: Lancer les tests complets**

```bash
pytest -v -q
```
Expected: tous PASS.

- [ ] **Step 4: Vérifier le type-check**

```bash
python -m py_compile bot/main.py bot/core/memory.py bot/core/graph_memory.py bot/core/graph.py bot/config.py
```
Expected: aucune sortie (zéro erreur de syntaxe).

- [ ] **Step 5: Commit**

```bash
git add bot/main.py
git commit -m "feat(main): wire memory.set_graph(graph) for Graphiti memory routing"
```

---

## Task 8: Vérification end-to-end et config YAML

**Files:**
- Modify: `config.yaml` (documentation — ne pas committer les flags activés)

- [ ] **Step 1: Vérifier la config YAML actuelle**

```bash
grep -A5 "graphiti:" config.yaml
```

- [ ] **Step 2: Confirmer que les flags sont bien absents (default = false/true)**

Les flags `memory_write`, `memory_primary`, `memory_dual_read` ont des valeurs par défaut dans le dataclass. Aucune modification de `config.yaml` nécessaire pour le déploiement initial — les valeurs par défaut sont :
- `memory_write: false` → Qdrant actif
- `memory_primary: false` → Qdrant primary
- `memory_dual_read: true` → prêt pour lecture hybride

- [ ] **Step 3: Lancer la suite de tests complète**

```bash
pytest -v --tb=short 2>&1 | tail -20
```
Expected: tous PASS, aucune régression.

- [ ] **Step 4: Build et deploy**

```bash
docker compose build wally && docker compose up -d wally
```

- [ ] **Step 5: Vérifier les logs de démarrage**

```bash
docker compose logs wally --tail=30
```
Expected: `MemoryService and LLM clients initialized` sans erreur.

- [ ] **Step 6: Commit final (si config.yaml modifié)**

```bash
git add config.yaml  # seulement si des changes ont été faits
git commit -m "chore: document Graphiti memory migration config flags (all disabled by default)"
```

---

## Plan de transition post-déploiement

| Étape | Action | Commande dashboard ou config.yaml |
|-------|--------|-----------------------------------|
| **Jour 0** | Deploy — valider les logs | flags à leurs defaults |
| **Jour 1** | Activer l'écriture Graphiti | `memory_write: true` via dashboard |
| **Semaine 2** | Lecture hybride | `memory_primary: true` |
| **Semaine 6+** | Graphiti seul | `memory_dual_read: false` |

Rollback instantané : remettre `memory_write: false` via dashboard.
