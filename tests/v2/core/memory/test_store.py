"""Tests QdrantEmbeddingStore — Qdrant est mocké."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from wally_v2.core.memory.store import QdrantEmbeddingStore, SearchHit


def make_store():
    async def fake_embed(text: str) -> list[float]:
        return [0.1] * 384

    return QdrantEmbeddingStore(
        url="http://localhost:6333",
        collection_name="test_v2",
        embedding_fn=fake_embed,
    )


@pytest.mark.asyncio
async def test_upsert_calls_qdrant_upsert(monkeypatch):
    """upsert() appelle qdrant_client.upsert avec le bon payload."""
    store = make_store()
    mock_upsert = AsyncMock()
    monkeypatch.setattr(store._client, "upsert", mock_upsert)

    await store.upsert(fact_id=42, user_id="discord:123", content="Aime le café")

    mock_upsert.assert_called_once()
    call_kwargs = mock_upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == "test_v2"
    point = call_kwargs["points"][0]
    assert point.payload == {"fact_id": 42, "user_id": "discord:123"}


@pytest.mark.asyncio
async def test_search_returns_search_hits(monkeypatch):
    """search() retourne une liste de SearchHit avec id et score."""
    store = make_store()

    mock_hit = MagicMock()
    mock_hit.id = "some-uuid"
    mock_hit.payload = {"fact_id": 7}
    mock_hit.score = 0.95

    mock_response = MagicMock()
    mock_response.points = [mock_hit]

    async def mock_query_points(**kwargs):
        return mock_response

    monkeypatch.setattr(store._client, "query_points", mock_query_points)

    hits = await store.search(query="café", user_id="discord:123", limit=5)
    assert len(hits) == 1
    assert hits[0].id == 7
    assert hits[0].score == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_search_filters_by_user_id(monkeypatch):
    """search() inclut le filtre user_id dans la requête Qdrant."""
    store = make_store()
    captured = {}

    mock_response = MagicMock()
    mock_response.points = []

    async def mock_query_points(**kwargs):
        captured.update(kwargs)
        return mock_response

    monkeypatch.setattr(store._client, "query_points", mock_query_points)
    await store.search(query="test", user_id="discord:999", limit=3)

    # Vérifier que le filtre est présent
    assert "query_filter" in captured
