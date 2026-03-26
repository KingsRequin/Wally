"""Direct Qdrant memory store — replaces mem0 middleware."""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import openai
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client import models

# ── Constants ────────────────────────────────────────────────────────────────
_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536
_EMBEDDING_COST_PER_TOKEN = 0.00000002  # $0.02 per 1M tokens


# ── Dataclasses ──────────────────────────────────────────────────────────────
@dataclass
class MemoryMetadata:
    """Metadata attached to a memory point in Qdrant."""

    user_id: str
    category: str = "FAIT"
    date: str = ""
    source: str = "unknown"
    platform: str = ""
    created_at: str = ""

    def to_payload(self, text: str) -> dict[str, Any]:
        today = date.today().isoformat()
        return {
            "text": text,
            "user_id": self.user_id,
            "category": self.category,
            "date": self.date or today,
            "source": self.source,
            "platform": self.platform,
            "created_at": self.created_at or today,
        }


@dataclass
class MemoryRecord:
    """A memory record returned from Qdrant queries."""

    id: str
    text: str
    user_id: str
    category: str = "FAIT"
    date: str = ""
    source: str = ""
    platform: str = ""
    created_at: str = ""
    score: float = 0.0


# ── Store ────────────────────────────────────────────────────────────────────
class QdrantMemoryStore:
    """Direct Qdrant access for long-term memory storage."""

    _EMBED_CACHE_MAX = 2048

    def __init__(self, qdrant_url: str, collection_name: str, db: Any) -> None:
        self._qdrant_url = qdrant_url
        self._collection_name = collection_name
        self._db = db
        self._client: QdrantClient | None = None
        self._openai: openai.OpenAI | None = None
        self._embed_cache: OrderedDict[str, list[float]] = OrderedDict()

    # ── Internal helpers ─────────────────────────────────────────────────

    def _ensure_client(self) -> None:
        """Lazy-init Qdrant client, OpenAI client, and collection."""
        if self._client is None:
            self._client = QdrantClient(url=self._qdrant_url)
            # Ensure collection exists (no-op if already present)
            if not self._client.collection_exists(self._collection_name):
                self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=models.VectorParams(
                        size=_EMBEDDING_DIM,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection {}", self._collection_name)
            logger.info("QdrantMemoryStore connected to {}", self._qdrant_url)
        if self._openai is None:
            self._openai = openai.OpenAI()

    async def _embed(self, text: str) -> list[float]:
        """Generate embedding via OpenAI with LRU cache and log cost."""
        self._ensure_client()
        assert self._openai is not None

        cache_key = hashlib.sha256(text.encode()).hexdigest()
        if cache_key in self._embed_cache:
            self._embed_cache.move_to_end(cache_key)
            return self._embed_cache[cache_key]

        response = await asyncio.wait_for(
            asyncio.to_thread(
                self._openai.embeddings.create,
                model=_EMBEDDING_MODEL,
                input=text,
            ),
            timeout=30.0,
        )
        embedding = response.data[0].embedding
        tokens = response.usage.total_tokens
        cost = tokens * _EMBEDDING_COST_PER_TOKEN

        await self._db.log_cost(
            model=_EMBEDDING_MODEL,
            input_tokens=tokens,
            output_tokens=0,
            cost_usd=cost,
            purpose="embedding",
        )

        self._embed_cache[cache_key] = embedding
        if len(self._embed_cache) > self._EMBED_CACHE_MAX:
            self._embed_cache.popitem(last=False)

        return embedding

    def _build_filter(
        self, user_id: str | None, filters: dict[str, str] | None = None
    ) -> models.Filter | None:
        """Build a Qdrant filter from user_id and optional extra filters."""
        conditions: list[models.FieldCondition] = []
        if user_id:
            conditions.append(
                models.FieldCondition(
                    key="user_id", match=models.MatchValue(value=user_id)
                )
            )
        if filters:
            for key, value in filters.items():
                conditions.append(
                    models.FieldCondition(
                        key=key, match=models.MatchValue(value=value)
                    )
                )
        if not conditions:
            return None
        return models.Filter(must=conditions)

    def _point_to_record(self, point: Any, score: float = 0.0) -> MemoryRecord:
        """Convert a Qdrant point to a MemoryRecord."""
        payload = point.payload or {}
        return MemoryRecord(
            id=str(point.id),
            text=payload.get("text", payload.get("data", payload.get("memory", ""))),
            user_id=payload.get("user_id", ""),
            category=payload.get("category", "FAIT"),
            date=payload.get("date", ""),
            source=payload.get("source", ""),
            platform=payload.get("platform", ""),
            created_at=payload.get("created_at", ""),
            score=score,
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def upsert(
        self, user_id: str, text: str, metadata: MemoryMetadata
    ) -> str:
        """Embed text and upsert a point into Qdrant. Returns the point ID."""
        self._ensure_client()
        assert self._client is not None

        embedding = await self._embed(text)
        point_id = str(uuid.uuid4())
        payload = metadata.to_payload(text)

        await asyncio.to_thread(
            self._client.upsert,
            collection_name=self._collection_name,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )
        logger.debug("Upserted memory {} for user {}", point_id, user_id)
        return point_id

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 10,
        min_score: float = 0.5,
        filters: dict[str, str] | None = None,
    ) -> list[MemoryRecord]:
        """Semantic search against Qdrant. Returns records above min_score."""
        self._ensure_client()
        assert self._client is not None

        embedding = await self._embed(query)
        query_filter = self._build_filter(user_id, filters)

        result = await asyncio.to_thread(
            self._client.query_points,
            collection_name=self._collection_name,
            query=embedding,
            query_filter=query_filter,
            limit=limit,
            score_threshold=min_score,
        )
        return [self._point_to_record(p, score=p.score) for p in result.points]

    async def get_all(
        self, user_id: str, filters: dict[str, str] | None = None,
        batch_size: int = 500,
    ) -> list[MemoryRecord]:
        """Scroll all points for a user with pagination."""
        self._ensure_client()
        assert self._client is not None

        query_filter = self._build_filter(user_id, filters)
        all_records: list[MemoryRecord] = []
        offset: str | None = None

        while True:
            points, next_offset = await asyncio.to_thread(
                self._client.scroll,
                collection_name=self._collection_name,
                scroll_filter=query_filter,
                limit=batch_size,
                offset=offset,
                with_payload=True,
            )
            all_records.extend(self._point_to_record(p) for p in points)
            if next_offset is None:
                break
            offset = next_offset

        logger.debug("get_all for {}: {} records", user_id, len(all_records))
        return all_records

    async def count(
        self, user_id: str, filters: dict[str, str] | None = None
    ) -> int:
        """Count points for a user."""
        self._ensure_client()
        assert self._client is not None

        query_filter = self._build_filter(user_id, filters)
        result = await asyncio.to_thread(
            self._client.count,
            collection_name=self._collection_name,
            count_filter=query_filter,
            exact=True,
        )
        return result.count

    async def delete(self, point_id: str) -> None:
        """Delete a single point by ID."""
        self._ensure_client()
        assert self._client is not None

        await asyncio.to_thread(
            self._client.delete,
            collection_name=self._collection_name,
            points_selector=models.PointIdsList(points=[point_id]),
        )
        logger.debug("Deleted memory point {}", point_id)

    async def delete_batch(self, point_ids: list[str]) -> int:
        """Delete multiple points in a single Qdrant call. Returns count deleted."""
        if not point_ids:
            return 0
        self._ensure_client()
        assert self._client is not None

        await asyncio.to_thread(
            self._client.delete,
            collection_name=self._collection_name,
            points_selector=models.PointIdsList(points=point_ids),
        )
        logger.debug("Batch-deleted {} memory points", len(point_ids))
        return len(point_ids)

    async def delete_by_user(self, user_id: str) -> None:
        """Delete all points for a user."""
        self._ensure_client()
        assert self._client is not None

        await asyncio.to_thread(
            self._client.delete,
            collection_name=self._collection_name,
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
        logger.debug("Deleted all memories for user {}", user_id)

    async def update(
        self, point_id: str, text: str, metadata: MemoryMetadata
    ) -> None:
        """Re-embed text and replace a point (same ID)."""
        self._ensure_client()
        assert self._client is not None

        embedding = await self._embed(text)
        payload = metadata.to_payload(text)

        await asyncio.to_thread(
            self._client.upsert,
            collection_name=self._collection_name,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )
        logger.debug("Updated memory point {}", point_id)

    async def update_payload(
        self, point_id: str, payload: dict[str, Any]
    ) -> None:
        """Update payload fields without re-embedding."""
        self._ensure_client()
        assert self._client is not None

        await asyncio.to_thread(
            self._client.set_payload,
            collection_name=self._collection_name,
            payload=payload,
            points=[point_id],
        )
        logger.debug("Updated payload for point {}", point_id)

    async def reset(self) -> None:
        """Delete and recreate the collection."""
        self._ensure_client()
        assert self._client is not None

        await asyncio.to_thread(
            self._client.delete_collection,
            collection_name=self._collection_name,
        )
        await asyncio.to_thread(
            self._client.create_collection,
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=_EMBEDDING_DIM,
                distance=models.Distance.COSINE,
            ),
        )
        logger.info("Reset collection {}", self._collection_name)
