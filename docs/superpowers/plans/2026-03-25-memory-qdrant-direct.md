# Memory Qdrant Direct — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer mem0 par un accès direct Qdrant avec métadonnées structurées, corriger les bugs mémoire, ajouter un budget token et élargir le filtre interjections.

**Architecture:** Nouvelle classe `QdrantMemoryStore` dans `bot/core/memory_store.py` qui encapsule `qdrant_client`. `MemoryService` utilise le store au lieu de mem0. Migration one-shot des payloads existants. Budget token appliqué dans les handlers lors de l'assemblage du `mem_context`.

**Tech Stack:** qdrant-client, openai (embeddings), aiosqlite, pytest

**Spec:** `docs/superpowers/specs/2026-03-25-memory-qdrant-direct-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `bot/core/memory_store.py` | Create | QdrantMemoryStore — embedding, upsert, search, get_all, delete |
| `bot/core/memory.py` | Modify | Rewire de `_mem0` vers `_store`, fusion consolidate+evaluate |
| `bot/core/fact_extractor.py` | Modify | Catégorie individuelle par fait, interjections élargies |
| `bot/core/prompts.py` | Modify | Séparation trust/love dans bloc Relation |
| `bot/core/journal.py` | Modify | Cleanup via `_store` au lieu de `_mem0` |
| `bot/config.py` | Modify | Nouveaux champs config |
| `bot/discord/handlers.py` | Modify | Budget token sur `mem_context` |
| `bot/twitch/handlers.py` | Modify | Budget token sur `mem_context` |
| `bot/dashboard/routes/memory.py` | Modify | Rewire `_get_mem0()` → store |
| `bot/dashboard/routes/links.py` | Modify | Merge mémoire via store |
| `bot/dashboard/routes/chat.py` | Modify | Chat memories via store |
| `bot/db/database.py` | Modify | `sync_memory_users_from_qdrant()` payload field |
| `scripts/migrate_mem0_to_qdrant.py` | Create | Migration one-shot des payloads |
| `tests/test_memory_store.py` | Create | Tests QdrantMemoryStore |
| `tests/test_memory.py` | Modify | Mocks mem0 → store |
| `tests/test_memory_maintenance.py` | Modify | Idem |
| `tests/test_memory_set_db.py` | Modify | Idem |
| `tests/test_memory_tag.py` | Modify | Idem |
| `tests/test_journal.py` | Modify | Idem |
| `tests/test_dashboard_memory_routes.py` | Modify | Idem |
| `tests/test_dashboard_links.py` | Modify | Idem |
| `tests/test_proactive_recall.py` | Modify | Idem |

---

## Task 1: QdrantMemoryStore — Core Class

**Files:**
- Create: `bot/core/memory_store.py`
- Create: `tests/test_memory_store.py`

### Step 1: Write tests for QdrantMemoryStore

- [ ] **1.1: Create test file with fixtures**

```python
# tests/test_memory_store.py
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.memory_store import QdrantMemoryStore, MemoryMetadata, MemoryRecord


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.log_cost = AsyncMock()
    return db


@pytest.fixture
def store(mock_db):
    with patch("bot.core.memory_store.QdrantClient") as MockQdrant, \
         patch("bot.core.memory_store.openai") as mock_openai:
        mock_client = MagicMock()
        MockQdrant.return_value = mock_client
        s = QdrantMemoryStore(
            qdrant_url="http://localhost:6333",
            collection_name="wally_memory",
            db=mock_db,
        )
        s._client = mock_client
        s._openai = mock_openai
        yield s
```

- [ ] **1.2: Write test for upsert**

```python
@pytest.mark.asyncio
async def test_upsert_generates_embedding_and_stores(store, mock_db):
    store._openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1] * 1536)]
    )

    meta = MemoryMetadata(
        user_id="discord:123",
        category="PREF",
        date="2026-03-25",
        source="fact_extractor",
        platform="discord",
    )
    point_id = await store.upsert("discord:123", "Aime le café", meta)

    assert point_id is not None
    store._client.upsert.assert_called_once()
    mock_db.log_cost.assert_called_once()
```

- [ ] **1.3: Write test for search with score filtering**

```python
@pytest.mark.asyncio
async def test_search_filters_by_min_score(store):
    store._openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1] * 1536)]
    )
    store._client.search.return_value = [
        MagicMock(id="a", score=0.8, payload={"text": "Bon souvenir", "user_id": "discord:123"}),
        MagicMock(id="b", score=0.3, payload={"text": "Vague", "user_id": "discord:123"}),
    ]

    results = await store.search("café", user_id="discord:123", min_score=0.5)

    assert len(results) == 1
    assert results[0].text == "Bon souvenir"
```

- [ ] **1.4: Write test for search with category filter**

```python
@pytest.mark.asyncio
async def test_search_with_category_filter(store):
    store._openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1] * 1536)]
    )
    store._client.search.return_value = [
        MagicMock(id="a", score=0.9, payload={"text": "Alice et Bob sont amis", "user_id": "discord:123", "category": "REL"}),
    ]

    results = await store.search("relations", user_id="discord:123", filters={"category": "REL"})

    # Verify Qdrant was called with a filter
    call_kwargs = store._client.search.call_args
    assert call_kwargs is not None
```

- [ ] **1.5: Write test for get_all**

```python
@pytest.mark.asyncio
async def test_get_all_returns_all_user_memories(store):
    store._client.scroll.return_value = (
        [
            MagicMock(id="a", payload={"text": "Fait 1", "user_id": "discord:123", "category": "FAIT"}),
            MagicMock(id="b", payload={"text": "Fait 2", "user_id": "discord:123", "category": "PREF"}),
        ],
        None,  # no next offset
    )

    records = await store.get_all("discord:123")

    assert len(records) == 2
    assert records[0].text == "Fait 1"
```

- [ ] **1.6: Write test for count**

```python
@pytest.mark.asyncio
async def test_count_returns_point_count(store):
    store._client.count.return_value = MagicMock(count=15)

    result = await store.count("discord:123")

    assert result == 15
```

- [ ] **1.7: Write test for delete and delete_by_user**

```python
@pytest.mark.asyncio
async def test_delete_single_point(store):
    await store.delete("point-uuid")
    store._client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_by_user(store):
    await store.delete_by_user("discord:123")
    store._client.delete.assert_called_once()
```

- [ ] **1.8: Write test for update (re-embed)**

```python
@pytest.mark.asyncio
async def test_update_re_embeds_and_replaces(store, mock_db):
    store._openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.2] * 1536)]
    )

    meta = MemoryMetadata(
        user_id="discord:123", category="PREF",
        date="2026-03-25", source="manual", platform="discord",
    )
    await store.update("point-uuid", "Nouveau texte", meta)

    store._client.upsert.assert_called_once()
    mock_db.log_cost.assert_called_once()
```

- [ ] **1.9: Write test for reset**

```python
@pytest.mark.asyncio
async def test_reset_deletes_all_points(store):
    await store.reset()
    store._client.delete.assert_called_once()
```

- [ ] **1.10: Run tests to verify they fail**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.core.memory_store'`

### Step 2: Implement QdrantMemoryStore

- [ ] **2.1: Create `bot/core/memory_store.py`**

```python
"""Direct Qdrant memory store — replaces mem0."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import openai
from loguru import logger
from qdrant_client import QdrantClient, models


@dataclass
class MemoryMetadata:
    user_id: str
    category: str = "FAIT"
    date: str = ""
    source: str = "unknown"
    platform: str = ""
    created_at: str = ""

    def to_payload(self, text: str) -> dict[str, Any]:
        return {
            "text": text,
            "user_id": self.user_id,
            "category": self.category,
            "date": self.date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": self.source,
            "platform": self.platform,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class MemoryRecord:
    id: str
    text: str
    user_id: str
    category: str = "FAIT"
    date: str = ""
    source: str = ""
    platform: str = ""
    created_at: str = ""
    score: float = 0.0


_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536
# Cost per token for text-embedding-3-small (as of 2026)
_EMBEDDING_COST_PER_TOKEN = 0.00000002


class QdrantMemoryStore:
    def __init__(self, qdrant_url: str, collection_name: str, db: Any):
        self._url = qdrant_url
        self._collection = collection_name
        self._db = db
        self._client: QdrantClient | None = None

    def _ensure_client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(url=self._url)
        return self._client

    async def _embed(self, text: str) -> list[float]:
        """Generate embedding via OpenAI and log cost."""
        response = await asyncio.to_thread(
            openai.embeddings.create,
            model=_EMBEDDING_MODEL,
            input=text,
        )
        embedding = response.data[0].embedding
        total_tokens = getattr(response.usage, "total_tokens", 0)
        if self._db and total_tokens:
            await self._db.log_cost(
                model=_EMBEDDING_MODEL,
                prompt_tokens=total_tokens,
                completion_tokens=0,
                cost_usd=total_tokens * _EMBEDDING_COST_PER_TOKEN,
                purpose="embedding",
            )
        return embedding

    def _build_filter(
        self, user_id: str | None = None, filters: dict | None = None
    ) -> models.Filter | None:
        conditions = []
        if user_id:
            conditions.append(
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(value=user_id),
                )
            )
        if filters:
            for key, value in filters.items():
                conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    )
                )
        if not conditions:
            return None
        return models.Filter(must=conditions)

    def _point_to_record(self, point: Any, score: float = 0.0) -> MemoryRecord:
        payload = point.payload or {}
        return MemoryRecord(
            id=str(point.id),
            text=payload.get("text", payload.get("memory", "")),
            user_id=payload.get("user_id", ""),
            category=payload.get("category", "FAIT"),
            date=payload.get("date", ""),
            source=payload.get("source", ""),
            platform=payload.get("platform", ""),
            created_at=payload.get("created_at", ""),
            score=score,
        )

    async def upsert(self, user_id: str, text: str, metadata: MemoryMetadata) -> str:
        client = self._ensure_client()
        embedding = await self._embed(text)
        point_id = str(uuid.uuid4())
        payload = metadata.to_payload(text)

        await asyncio.to_thread(
            client.upsert,
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )
        logger.debug("Qdrant upsert: {uid} -> {text:.60}", uid=user_id, text=text)
        return point_id

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 10,
        min_score: float = 0.5,
        filters: dict | None = None,
    ) -> list[MemoryRecord]:
        client = self._ensure_client()
        embedding = await self._embed(query)
        qfilter = self._build_filter(user_id, filters)

        hits = await asyncio.to_thread(
            client.search,
            collection_name=self._collection,
            query_vector=embedding,
            query_filter=qfilter,
            limit=limit,
            score_threshold=min_score,
        )
        return [self._point_to_record(h, score=h.score) for h in hits]

    async def get_all(
        self, user_id: str, filters: dict | None = None
    ) -> list[MemoryRecord]:
        client = self._ensure_client()
        qfilter = self._build_filter(user_id, filters)
        records: list[MemoryRecord] = []
        offset = None

        while True:
            points, next_offset = await asyncio.to_thread(
                client.scroll,
                collection_name=self._collection,
                scroll_filter=qfilter,
                limit=100,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            records.extend(self._point_to_record(p) for p in points)
            if next_offset is None:
                break
            offset = next_offset

        return records

    async def count(self, user_id: str, filters: dict | None = None) -> int:
        client = self._ensure_client()
        qfilter = self._build_filter(user_id, filters)
        result = await asyncio.to_thread(
            client.count,
            collection_name=self._collection,
            count_filter=qfilter,
            exact=True,
        )
        return result.count

    async def delete(self, point_id: str) -> None:
        client = self._ensure_client()
        await asyncio.to_thread(
            client.delete,
            collection_name=self._collection,
            points_selector=models.PointIdsList(points=[point_id]),
        )

    async def delete_by_user(self, user_id: str) -> None:
        client = self._ensure_client()
        await asyncio.to_thread(
            client.delete,
            collection_name=self._collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="user_id",
                            match=models.MatchValue(value=user_id),
                        )
                    ]
                )
            ),
        )

    async def update(self, point_id: str, text: str, metadata: MemoryMetadata) -> None:
        client = self._ensure_client()
        embedding = await self._embed(text)
        payload = metadata.to_payload(text)

        await asyncio.to_thread(
            client.upsert,
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )

    async def update_payload(self, point_id: str, payload: dict) -> None:
        client = self._ensure_client()
        await asyncio.to_thread(
            client.set_payload,
            collection_name=self._collection,
            payload=payload,
            points=[point_id],
        )

    async def reset(self) -> None:
        """Delete and recreate the collection (full reset)."""
        client = self._ensure_client()
        info = await asyncio.to_thread(
            client.get_collection, self._collection
        )
        vectors_config = info.config.params.vectors
        await asyncio.to_thread(client.delete_collection, self._collection)
        await asyncio.to_thread(
            client.create_collection,
            collection_name=self._collection,
            vectors_config=vectors_config,
        )
```

- [ ] **2.2: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_store.py -v`
Expected: All tests PASS

- [ ] **2.3: Commit**

```bash
git add bot/core/memory_store.py tests/test_memory_store.py
git commit -m "feat(memory): add QdrantMemoryStore — direct Qdrant access layer"
```

---

## Task 2: Config Updates

**Files:**
- Modify: `bot/config.py`
- Modify: `config.yaml`

- [ ] **2.1: Add new config fields to `BotConfig` in `bot/config.py`**

Add after the existing `memory_recall_min_score` field:

```python
memory_search_min_score: float = 0.5
memory_context_max_tokens: int = 800
```

- [ ] **2.2: Add new config values to `config.yaml`**

Add under `bot:` section:

```yaml
memory_search_min_score: 0.5
memory_context_max_tokens: 800
```

- [ ] **2.3: Run existing config tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -k "config" -v`
Expected: PASS

- [ ] **2.4: Commit**

```bash
git add bot/config.py config.yaml
git commit -m "feat(config): add memory_search_min_score and memory_context_max_tokens"
```

---

## Task 3: Rewire MemoryService

**Files:**
- Modify: `bot/core/memory.py`

This is the biggest task. Replace `self._mem0` with `self._store` (QdrantMemoryStore) throughout `MemoryService`.

- [ ] **3.1: Replace `_init_mem0()` with `_init_store()`**

Replace the entire `_init_mem0()` method (lines 87-121) with:

```python
def _init_store(self):
    """Initialize QdrantMemoryStore (lazy, thread-safe)."""
    if self._store is not None:
        return
    try:
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self._store = QdrantMemoryStore(
            qdrant_url=qdrant_url,
            collection_name="wally_memory",
            db=self._db,
        )
        logger.info("QdrantMemoryStore initialized at {url}", url=qdrant_url)
    except Exception as e:
        logger.error("Failed to init QdrantMemoryStore: {e}", e=e)
        self._store = None
```

Update `__init__` to replace `self._mem0 = None` with `self._store = None`.

Add import: `from bot.core.memory_store import QdrantMemoryStore, MemoryMetadata, MemoryRecord`

- [ ] **3.2: Rewrite `add()` method**

Replace the mem0 call with:

```python
async def add(self, platform, user_id, content, username="", emotion_context="", category=""):
    self._init_store()
    if not self._store:
        return

    uid = self._user_id(platform, user_id)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build content with date prefix and emotion context (same as before)
    full_content = f"[{date_str}]"
    if emotion_context:
        full_content += f" [{emotion_context}]"
    full_content += f" {content}"

    metadata = MemoryMetadata(
        user_id=uid,
        category=category or "FAIT",
        date=date_str,
        source="fact_extractor",
        platform=platform,
    )

    point_id = await self._store.upsert(uid, full_content, metadata)
    if point_id:
        logger.debug("Memory added for {uid}: {text:.60}", uid=uid, text=content)
        await self._db.upsert_memory_user(uid, platform, username)
        self._fire(self._post_add_maintenance(uid, full_content))
        # Keep existing account linker call pattern:
        if self._account_linker and uid not in self._alias_cache.values():
            self._fire(self._account_linker.analyze_new_user(platform, user_id, username))
```

- [ ] **3.3: Rewrite `search()` with configurable min_score**

Replace `_MIN_SEARCH_SCORE` usage with `self._config.bot.memory_search_min_score`:

```python
async def search(self, platform, user_id, query, context_messages=None):
    self._init_store()
    if not self._store:
        return ""

    uid = self._user_id(platform, user_id)
    min_score = self._config.bot.memory_search_min_score

    # Primary query
    primary_task = self._store.search(query, user_id=uid, min_score=min_score)

    # Secondary context query (if available)
    secondary_results = []
    if context_messages:
        context_text = " ".join(
            m["content"] for m in context_messages[-5:]
            if m.get("author", "").lower() != "wally"
        )
        if context_text.strip():
            primary_results, secondary_results = await asyncio.gather(
                primary_task,
                self._store.search(context_text, user_id=uid, min_score=min_score),
                return_exceptions=True,
            )
        else:
            primary_results = await primary_task
    else:
        primary_results = await primary_task

    # Handle exceptions
    if isinstance(primary_results, Exception):
        logger.warning("Primary search failed: {e}", e=primary_results)
        primary_results = []
    if isinstance(secondary_results, Exception):
        secondary_results = []

    # Deduplicate by text, keep highest score
    seen: dict[str, float] = {}
    all_results = (primary_results or []) + (secondary_results or [])
    for r in all_results:
        if r.text not in seen or r.score > seen[r.text]:
            seen[r.text] = r.score

    memories = sorted(seen.keys(), key=lambda t: seen[t], reverse=True)
    return "\n".join(memories)
```

- [ ] **3.4: Rewrite `search_top_match()`**

```python
async def search_top_match(self, platform, user_id, query):
    self._init_store()
    if not self._store:
        return None

    uid = self._user_id(platform, user_id)
    results = await self._store.search(
        query, user_id=uid, limit=3,
        min_score=self._config.bot.memory_search_min_score,
    )
    if results:
        return (results[0].text, results[0].score)
    return None
```

- [ ] **3.5: Rewrite `search_relationships()` with native filter + semantic search**

```python
async def search_relationships(self, platform, participants, context=""):
    self._init_store()
    if not self._store:
        return ""

    rel_memories = []
    query = context or " ".join(participants)
    for raw_id in participants:
        uid = self._user_id(platform, raw_id)
        results = await self._store.search(
            query, user_id=uid,
            filters={"category": "REL"},
            limit=10,
            min_score=self._config.bot.memory_search_min_score,
        )
        rel_memories.extend(r.text for r in results)

    return "\n".join(rel_memories) if rel_memories else ""
```

- [ ] **3.6: Rewrite `search_global()`**

```python
async def search_global(self, query):
    self._init_store()
    if not self._store:
        return ""

    min_score = self._config.bot.memory_search_min_score
    results = await self._store.search(query, user_id=GLOBAL_USER_ID, min_score=min_score)
    return "\n".join(r.text for r in results)
```

- [ ] **3.7: Rewrite `get_all()`**

```python
async def get_all(self, platform, user_id):
    self._init_store()
    if not self._store:
        return ""

    uid = self._user_id(platform, user_id)
    records = await self._store.get_all(uid)
    return "\n".join(r.text for r in records)
```

- [ ] **3.8: Rewrite `add_global()`**

```python
async def add_global(self, content, source="fact_extractor"):
    self._init_store()
    if not self._store:
        return

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    full_content = f"[{date_str}] {content}"
    metadata = MemoryMetadata(
        user_id=GLOBAL_USER_ID,
        category="FAIT",
        date=date_str,
        source=source,
        platform="global",
    )
    await self._store.upsert(GLOBAL_USER_ID, full_content, metadata)
```

- [ ] **3.9: Rewrite `reset_all()`**

```python
async def reset_all(self):
    self._context_windows.clear()
    self._prelude_windows.clear()
    self._init_store()
    if self._store:
        await self._store.reset()
```

- [ ] **3.10: Rewrite `delete_user_memories()`**

```python
async def delete_user_memories(self, platform, user_id):
    self._init_store()
    if not self._store:
        return
    uid = self._user_id(platform, user_id)
    await self._store.delete_by_user(uid)
    logger.info("Deleted all memories for {uid}", uid=uid)
```

- [ ] **3.11: Implement `_post_add_maintenance()` (fusion consolidate+evaluate)**

Replace both `_maybe_consolidate()` and `_evaluate_memory()` with:

```python
async def _post_add_maintenance(self, user_id: str, new_text: str):
    """Single background task: consolidation OR evaluation (not both)."""
    try:
        count = await self._store.count(user_id)

        if count > _CONSOLIDATION_THRESHOLD:
            all_memories = await self._store.get_all(user_id)
            await self._consolidate(user_id, all_memories)
        else:
            all_memories = await self._store.get_all(user_id)
            pending_questions = await self._db.get_all_pending_questions(user_id)
            await self._evaluate(user_id, new_text, all_memories, pending_questions)
    except Exception as e:
        logger.warning("Post-add maintenance failed for {uid}: {e}", uid=user_id, e=e)
```

Update `_consolidate()` to use `self._store` instead of `self._mem0`:
- `get_all` → already passed as parameter
- Add new consolidated text via `self._store.upsert()`
- Delete old entries via `self._store.delete(record.id)`

Update `_evaluate()` to accept `all_memories` and `pending_questions` as parameters instead of fetching them internally.

- [ ] **3.12: Expose `_store` as a public property for dashboard access**

```python
@property
def store(self) -> QdrantMemoryStore | None:
    """Public access to the Qdrant store (used by dashboard routes)."""
    self._init_store()
    return self._store
```

- [ ] **3.13: Remove all `_mem0` references**

Search and remove: `self._mem0`, `_init_mem0`, any `from mem0` import.

- [ ] **3.14: Run memory tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_memory.py -v`
Expected: Many failures (mocks still target mem0) — this is expected, fixed in Task 9.

- [ ] **3.15: Commit**

```bash
git add bot/core/memory.py
git commit -m "feat(memory): rewire MemoryService from mem0 to QdrantMemoryStore"
```

---

## Task 4: Rewire Journal Cleanup

**Files:**
- Modify: `bot/core/journal.py`

- [ ] **4.1: Update `run_memory_cleanup()` to use store**

Replace all `self._memory._mem0.get_all(user_id=uid)` calls with `await self._memory.store.get_all(uid)`.
Replace `self._memory._mem0.delete(mem_id)` with `await self._memory.store.delete(mem_id)`.
Replace `self._memory._mem0.add(new_text, user_id=uid)` with:

```python
metadata = MemoryMetadata(
    user_id=uid,
    category="FAIT",
    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    source="cleanup",
    platform=uid.split(":")[0],
)
await self._memory.store.upsert(uid, new_text, metadata)
```

Replace the initialization check from `self._memory._init_mem0()` / `self._memory._mem0 is None` with `self._memory.store is None`.

Add import: `from bot.core.memory_store import MemoryMetadata`

- [ ] **4.2: Update `_build_mem0_fallback_context()` if it accesses `_mem0` directly**

If this method accesses `_mem0`, rewire to `self._memory.store`. If it only calls `self._memory.get_all()`, no change needed (already rewired in Task 3).

- [ ] **4.3: Run journal tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py -v`
Expected: Failures from old mocks — fixed in Task 9.

- [ ] **4.4: Commit**

```bash
git add bot/core/journal.py
git commit -m "feat(memory): rewire journal cleanup to use QdrantMemoryStore"
```

---

## Task 5: Rewire Dashboard Routes

**Files:**
- Modify: `bot/dashboard/routes/memory.py`
- Modify: `bot/dashboard/routes/links.py`
- Modify: `bot/dashboard/routes/chat.py`

- [ ] **5.1: Replace `_get_mem0()` helper in `memory.py`**

```python
def _get_store(request: Request):
    """Get QdrantMemoryStore or raise 503."""
    state = request.app.state.wally
    store = state.memory.store
    if store is None:
        raise HTTPException(503, detail="Qdrant store not available")
    return store
```

- [ ] **5.2: Replace all `mem0.get_all()` calls in `memory.py`**

Pattern: `mem0.get_all(user_id=uid)` → `await store.get_all(uid)`

The response format changes: instead of `results[i]["memory"]` and `results[i]["id"]`, use `records[i].text` and `records[i].id`.

- [ ] **5.3: Replace `mem0.add()` calls in `memory.py`**

```python
# Before: await asyncio.to_thread(mem0.add, content, user_id=uid, metadata=meta)
# After:
metadata = MemoryMetadata(user_id=uid, category=cat, date=date_str, source="manual", platform=plat)
await store.upsert(uid, content, metadata)
```

- [ ] **5.4: Replace `mem0.update()` calls in `memory.py`**

```python
# Before: await asyncio.to_thread(mem0.update, memory_id, content)
# After:
metadata = MemoryMetadata(user_id=uid, category=cat, date=date_str, source="manual", platform=plat)
await store.update(memory_id, content, metadata)
```

- [ ] **5.5: Replace `mem0.delete()` and `mem0.delete_all()` calls**

```python
# Before: await asyncio.to_thread(mem0.delete, memory_id)
# After: await store.delete(memory_id)

# Before: await asyncio.to_thread(mem0.delete_all, user_id=uid)
# After: await store.delete_by_user(uid)
```

- [ ] **5.6: Replace `mem0.search()` calls**

```python
# Before: await asyncio.to_thread(mem0.search, q, user_id=uid, limit=3)
# After: results = await store.search(q, user_id=uid, limit=3, min_score=0.3)
# Note: dashboard search can use a lower min_score than normal responses
```

- [ ] **5.7: Rewire `routes/links.py` merge operation**

Replace direct `state.memory._mem0` access with `state.memory.store`:

```python
store = state.memory.store
if store is None:
    return

records = await store.get_all(alias_id)
for rec in records:
    if rec.text:
        meta = MemoryMetadata(
            user_id=canonical_id, category=rec.category,
            date=rec.date, source=rec.source, platform=rec.platform,
        )
        await store.upsert(canonical_id, rec.text, meta)

await store.delete_by_user(alias_id)
```

- [ ] **5.8: Rewire `routes/chat.py` memories endpoint**

Replace `state.memory._mem0` access with `state.memory.store`:

```python
store = state.memory.store
if store is None:
    return {"memories": []}

records = await store.get_all(user_id)
# Include alias memories
for alias_id in alias_ids:
    records.extend(await store.get_all(alias_id))

return {"memories": [{"id": r.id, "memory": r.text} for r in records]}
```

- [ ] **5.9: Commit**

```bash
git add bot/dashboard/routes/memory.py bot/dashboard/routes/links.py bot/dashboard/routes/chat.py
git commit -m "feat(dashboard): rewire all routes from mem0 to QdrantMemoryStore"
```

---

## Task 6: Fix Category Bug in FactExtractor

**Files:**
- Modify: `bot/core/fact_extractor.py`

- [ ] **6.1: Replace dominant_category with per-fact category**

In `_extract_facts()`, replace the batch category logic (around line 473):

```python
# REMOVE this:
# categories = [fi.get("category", "FAIT") for fi in fact_items]
# dominant_category = max(set(categories), key=categories.count) if categories else "FAIT"

# CHANGE the loop to pass individual categories:
for fi in fact_items:
    fact_text = fi.get("fact", "")
    category = fi.get("category", "FAIT")
    if not fact_text:
        continue
    # ... existing logic to determine user_id ...
    await self._memory.add(plat, raw_id, fact_text, category=category)
```

This replaces the single `memory.add()` call per user with one call per fact item, each with its own category.

- [ ] **6.2: Run fact extractor tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -k "fact" -v`
Expected: PASS (or failures from mock changes — addressed in Task 9)

- [ ] **6.3: Commit**

```bash
git add bot/core/fact_extractor.py
git commit -m "fix(memory): store individual category per fact instead of batch dominant"
```

---

## Task 7: Interjections Filter Expansion

**Files:**
- Modify: `bot/core/fact_extractor.py`

- [ ] **7.1: Add English interjection patterns**

Add to `_INTERJECTION_PATTERNS` list after the existing French patterns:

```python
    # English / franglais
    re.compile(r"^su+re+$"),      # sure, suuure
    re.compile(r"^ye+a+h+$"),     # yeah, yeaah
    re.compile(r"^ye+p+$"),       # yep, yeep
    re.compile(r"^no+pe+$"),      # nope, noope
    re.compile(r"^na+h+$"),       # nah, naah
    re.compile(r"^l+m+a+o+$"),    # lmao, lmaaoo
    re.compile(r"^l+m+f+a+o+$"), # lmfao
    re.compile(r"^ro+fl+$"),      # rofl
    re.compile(r"^bru+h+$"),      # bruh, bruuh
    re.compile(r"^da+mn+$"),      # damn, daamn
    re.compile(r"^ni+ce+$"),      # nice, niice
    re.compile(r"^co+l+$"),       # cool, coool
    re.compile(r"^tru+e+$"),      # true, truue
    re.compile(r"^fr+$"),         # fr, frr
    re.compile(r"^idk$"),         # idk
    re.compile(r"^ikr$"),         # ikr
    re.compile(r"^ngl$"),         # ngl
    re.compile(r"^tbh$"),         # tbh
    re.compile(r"^o+mg+$"),       # omg, oomg
    re.compile(r"^wo+w+$"),       # wow, woow
    re.compile(r"^we+lp+$"),      # welp
    re.compile(r"^yi+ke+s+$"),    # yikes
    re.compile(r"^she+sh+$"),     # sheesh
    re.compile(r"^be+t+$"),       # bet, beet
```

- [ ] **7.2: Run interjection tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -k "memorable or interjection" -v`
Expected: PASS

- [ ] **7.3: Commit**

```bash
git add bot/core/fact_extractor.py
git commit -m "feat(memory): expand interjection filter with English patterns"
```

---

## Task 8: Budget Token + Trust/Love Separation

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/twitch/handlers.py`
- Modify: `bot/core/prompts.py`

- [ ] **8.1: Add budget token helper function**

Add to `bot/core/prompts.py`:

```python
def assemble_memory_context(
    parts: list[tuple[int, str]],
    max_tokens: int,
) -> str:
    """Assemble memory context respecting token budget.

    Args:
        parts: list of (priority, text) tuples. Lower priority = higher importance.
        max_tokens: token budget (estimated as len(text) / 4).

    Returns:
        Assembled context string, truncated to budget.
    """
    sorted_parts = sorted(parts, key=lambda p: p[0])
    result_parts = []
    used_tokens = 0

    for _priority, text in sorted_parts:
        if not text or not text.strip():
            continue
        estimated_tokens = len(text) / 4
        if used_tokens + estimated_tokens > max_tokens:
            # Try to fit a truncated version
            remaining = int((max_tokens - used_tokens) * 4)
            if remaining > 50:
                result_parts.append(text[:remaining])
            break
        result_parts.append(text)
        used_tokens += estimated_tokens

    return "\n".join(result_parts)
```

- [ ] **8.2: Update `build_system_prompt()` to handle trust/love separately**

Add a `relationship_context` parameter:

```python
def build_system_prompt(self, ..., memory_context="", relationship_context="", global_memory_context="", ...):
    # ... existing logic ...
    if memory_context:
        parts.append(f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}")
        if _MEMORY_RECALL_DIRECTIVE:
            parts.append(_MEMORY_RECALL_DIRECTIVE)
    if relationship_context:
        parts.append(f"\n--- Relation ---\n{relationship_context}")
    # ... rest unchanged ...
```

- [ ] **8.3: Restructure `mem_context` assembly in Discord handler**

In `bot/discord/handlers.py`, in the `_process_response()` function, replace the linear `mem_context +=` assembly with budgeted parts:

```python
from bot.core.prompts import assemble_memory_context

# Gather all parts with priorities
memory_parts = []
max_tokens = bot.config.bot.memory_context_max_tokens

# Priority 1: Semantic memories
semantic_mem = await bot.memory.search(platform, user_id, message.content, context_messages=prelude)
if semantic_mem:
    memory_parts.append((1, semantic_mem))

# Priority 2: Relationships
rel_context = await bot.memory.search_relationships(platform, [user_id])
if rel_context:
    memory_parts.append((2, f"--- Relations ---\n{rel_context}"))

# Priority 3: Global memories
global_context = await bot.memory.search_global(message.content)
if global_context:
    memory_parts.append((3, global_context))

# Priority 4: Pending question
question_directive = await bot.memory.get_pending_question_directive(platform, user_id)
if question_directive:
    memory_parts.append((4, question_directive))

# Priority 5: Recent jokes
# ... existing joke logic ...
if jokes_text:
    memory_parts.append((5, jokes_text))

# Priority 6: Opinions
# ... existing opinion logic ...
if opinions_text:
    memory_parts.append((6, opinions_text))

mem_context = assemble_memory_context(memory_parts, max_tokens)

# Trust/love go in separate relationship_context (no budget)
trust = await bot.db.get_trust_score(platform, user_id)
love = await bot.db.get_love_score(platform, user_id, bot.config.bot.love_decay_lambda)
relationship_context = f"Niveau de confiance : {trust:.2f}/1.0\nNiveau d'affection : {love:.2f}/1.0"

# Temporal activity (absence note) prepended to mem_context if present
# ... existing absence logic — prepend to mem_context ...
```

- [ ] **8.4: Apply same restructure in Twitch handler**

Same pattern as 8.3 in `bot/twitch/handlers.py`.

- [ ] **8.5: Run handler tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -k "handler" -v`
Expected: Some failures from mock changes — addressed in Task 9.

- [ ] **8.6: Commit**

```bash
git add bot/core/prompts.py bot/discord/handlers.py bot/twitch/handlers.py
git commit -m "feat(memory): add token budget for memory context, separate trust/love block"
```

---

## Task 9: Update All Tests

**Files:**
- Modify: `tests/test_memory.py`
- Modify: `tests/test_memory_maintenance.py`
- Modify: `tests/test_memory_set_db.py`
- Modify: `tests/test_memory_tag.py`
- Modify: `tests/test_journal.py`
- Modify: `tests/test_dashboard_memory_routes.py`
- Modify: `tests/test_dashboard_links.py`
- Modify: `tests/test_proactive_recall.py`

The pattern is the same across all files:

- [ ] **9.1: Global mock replacement pattern**

Everywhere tests mock `mem0`, replace with `QdrantMemoryStore` mocks:

```python
# Before:
# mock_mem0 = MagicMock()
# memory._mem0 = mock_mem0
# mock_mem0.get_all.return_value = {"results": [{"memory": "text", "id": "abc"}]}

# After:
# mock_store = AsyncMock()
# memory._store = mock_store
# mock_store.get_all.return_value = [MemoryRecord(id="abc", text="text", user_id="discord:123")]
# mock_store.search.return_value = [MemoryRecord(id="abc", text="text", user_id="discord:123", score=0.8)]
# mock_store.upsert.return_value = "point-uuid"
# mock_store.count.return_value = 5
```

- [ ] **9.2: Update `tests/test_memory.py`**

Replace all `_mem0` references with `_store`. Update response format expectations (dict → MemoryRecord).

- [ ] **9.3: Update `tests/test_memory_maintenance.py`**

Update consolidation and evaluate test mocks.

- [ ] **9.4: Update `tests/test_memory_set_db.py`**

Update mock patterns.

- [ ] **9.5: Update `tests/test_memory_tag.py`**

Update mock patterns.

- [ ] **9.6: Update `tests/test_journal.py`**

Replace `memory._mem0.get_all`, `._mem0.delete`, `._mem0.add` with store mocks.

- [ ] **9.7: Update `tests/test_dashboard_memory_routes.py`**

Replace `_get_mem0` mocks with `_get_store` / `memory.store` mocks.

- [ ] **9.8: Update `tests/test_dashboard_links.py`**

Replace mem0 mocks in merge operations.

- [ ] **9.9: Update `tests/test_proactive_recall.py`**

Replace `search_top_match` mocks if they depend on mem0 internals.

- [ ] **9.10: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **9.11: Commit**

```bash
git add tests/
git commit -m "test(memory): update all test mocks from mem0 to QdrantMemoryStore"
```

---

## Task 10: Database Sync Check

**Files:**
- Modify: `bot/db/database.py` (if needed)

- [ ] **10.1: Verify `sync_memory_users_from_qdrant()` payload field**

Check if the method reads `payload.get("memory")` anywhere. If it only reads `payload.get("user_id")`, no change needed. If it reads `memory`, update to `text`.

Since the migration script (Task 11) will add `text` to all payloads, and `_point_to_record()` already falls back to `payload.get("memory", "")`, this should work with both old and new payloads during transition.

- [ ] **10.2: Commit if changed**

```bash
git add bot/db/database.py
git commit -m "fix(db): update sync_memory_users_from_qdrant for new payload format"
```

---

## Task 11: Migration Script

**Files:**
- Create: `scripts/migrate_mem0_to_qdrant.py`

- [ ] **11.1: Create migration script**

```python
#!/usr/bin/env python3
"""Migrate mem0 payloads to structured format in Qdrant.

Reads existing points, rewrites payloads with structured metadata.
Vectors are NOT changed — only payloads are updated.
Idempotent: safe to run multiple times.
"""

import re
import sys
from datetime import datetime, timezone

from qdrant_client import QdrantClient

COLLECTION = "wally_memory"
DATE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]")


def migrate(qdrant_url: str = "http://localhost:6333", dry_run: bool = False):
    client = QdrantClient(url=qdrant_url)
    offset = None
    migrated = 0
    skipped = 0

    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION,
            limit=100,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )

        if not points:
            break

        for point in points:
            payload = point.payload or {}

            # Already migrated?
            if "text" in payload and "source" in payload:
                skipped += 1
                continue

            # Extract text from mem0 format
            text = payload.get("memory", payload.get("text", ""))
            if not text:
                skipped += 1
                continue

            # Extract user_id
            user_id = payload.get("user_id", "")
            if not user_id:
                skipped += 1
                continue

            # Parse platform from user_id
            parts = user_id.split(":", 1)
            platform = parts[0] if len(parts) == 2 else "unknown"

            # Parse date from text prefix [YYYY-MM-DD]
            date_match = DATE_RE.match(text)
            date_str = date_match.group(1) if date_match else datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Build new payload
            new_payload = {
                "text": text,
                "user_id": user_id,
                "category": payload.get("category", "FAIT"),
                "date": date_str,
                "source": "legacy_mem0",
                "platform": platform,
                "created_at": payload.get("created_at", datetime.now(timezone.utc).isoformat()),
            }

            if not dry_run:
                # overwrite_payload replaces entire payload (removes old mem0 fields)
                client.overwrite_payload(
                    collection_name=COLLECTION,
                    payload=new_payload,
                    points=[point.id],
                )
            migrated += 1

        if next_offset is None:
            break
        offset = next_offset

    print(f"Migration complete: {migrated} migrated, {skipped} skipped")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    url = "http://localhost:6333"
    for arg in sys.argv[1:]:
        if arg.startswith("--url="):
            url = arg.split("=", 1)[1]
    migrate(url, dry_run=dry)
```

- [ ] **11.2: Test with dry run**

Run: `cd /opt/stacks/wally-ai && python scripts/migrate_mem0_to_qdrant.py --dry-run`
Expected: Shows count of points that would be migrated

- [ ] **11.3: Commit**

```bash
git add scripts/migrate_mem0_to_qdrant.py
git commit -m "feat(memory): add migration script from mem0 to structured Qdrant payloads"
```

---

## Task 12: Remove mem0 Dependency

**Files:**
- Modify: `requirements.txt`
- Modify: `bot/core/openai_client.py` (if it imports mem0)

- [ ] **12.1: Remove `mem0ai` from `requirements.txt`**

Delete the line: `mem0ai>=0.1.29`

Keep: `qdrant-client>=1.9.0`

- [ ] **12.2: Search for any remaining mem0 imports**

Run: `grep -r "mem0" bot/ --include="*.py" -l`

Remove any remaining `import mem0` or `from mem0` lines.

- [ ] **12.3: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **12.4: Commit**

```bash
git add requirements.txt bot/
git commit -m "chore: remove mem0ai dependency — fully replaced by direct Qdrant access"
```

---

## Task 13: Final Verification

- [ ] **13.1: Run full test suite one last time**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **13.2: Verify no mem0 references remain**

Run: `grep -r "mem0\|_mem0\|_init_mem0" bot/ tests/ --include="*.py"`
Expected: No matches (except possibly comments)

- [ ] **13.3: Verify config loads correctly**

Run: `cd /opt/stacks/wally-ai && python -c "from bot.config import Config; c = Config.load(); print(c.bot.memory_search_min_score, c.bot.memory_context_max_tokens)"`
Expected: `0.5 800`
