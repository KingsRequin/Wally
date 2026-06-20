# bot/v2/core/memory/store.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import uuid5, NAMESPACE_URL

from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
)


@dataclass
class SearchHit:
    id: int      # fact_id SQLite
    score: float


def _fact_uuid(fact_id: int) -> str:
    """Génère un UUID stable depuis l'ID SQLite pour Qdrant."""
    return str(uuid5(NAMESPACE_URL, f"fact:{fact_id}"))


class QdrantEmbeddingStore:
    """Stocke uniquement les embeddings dans Qdrant. Les métadonnées sont en SQLite.

    Payload Qdrant : {"fact_id": int, "user_id": str}
    """

    def __init__(
        self,
        url: str,
        collection_name: str,
        embedding_fn: Callable[[str], Awaitable[list[float]]],
        vector_size: int = 384,
    ) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._collection = collection_name
        self._embed = embedding_fn
        self._vector_size = vector_size

    async def ensure_collection(self) -> None:
        """Crée la collection si elle n'existe pas."""
        try:
            await self._client.get_collection(self._collection)
        except Exception:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
            )

    async def upsert(self, fact_id: int, user_id: str, content: str) -> None:
        try:
            vector = await self._embed(content)
            point = PointStruct(
                id=_fact_uuid(fact_id),
                vector=vector,
                payload={"fact_id": fact_id, "user_id": user_id},
            )
            await self._client.upsert(
                collection_name=self._collection,
                points=[point],
            )
        except Exception as e:
            logger.warning("QdrantEmbeddingStore.upsert failed for fact {id}: {e}", id=fact_id, e=e)

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
    ) -> list[SearchHit]:
        try:
            vector = await self._embed(query)
            response = await self._client.query_points(
                collection_name=self._collection,
                query=vector,
                query_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=limit,
                with_payload=True,
            )
            return [SearchHit(id=h.payload["fact_id"], score=h.score) for h in response.points]
        except Exception as e:
            logger.warning("QdrantEmbeddingStore.search failed: {e}", e=e)
            return []
