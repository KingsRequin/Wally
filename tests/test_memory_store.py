"""Tests for QdrantMemoryStore — Qdrant and OpenAI are fully mocked."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

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
        s = QdrantMemoryStore(
            qdrant_url="http://localhost:6333",
            collection_name="test_collection",
            db=mock_db,
        )
        # Wire up mocks directly
        s._client = MockQdrant.return_value
        s._openai = mock_openai.OpenAI.return_value

        # Default embedding response
        embedding_obj = MagicMock()
        embedding_obj.embedding = [0.1] * 1536
        embed_response = MagicMock()
        embed_response.data = [embedding_obj]
        embed_response.usage.total_tokens = 10
        s._openai.embeddings.create.return_value = embed_response

        yield s


@pytest.mark.asyncio
async def test_upsert_generates_embedding_and_stores(store, mock_db):
    meta = MemoryMetadata(user_id="discord:123", category="FAIT", source="test")
    point_id = await store.upsert("discord:123", "likes cats", meta)

    assert point_id is not None
    store._openai.embeddings.create.assert_called_once()
    store._client.upsert.assert_called_once()

    # Check cost was logged
    mock_db.log_cost.assert_awaited_once()
    call_kwargs = mock_db.log_cost.call_args
    assert call_kwargs[1]["purpose"] == "embedding"


@pytest.mark.asyncio
async def test_search_filters_by_min_score(store):
    from qdrant_client import models

    # Mock search result with one point
    point = MagicMock()
    point.id = "abc-123"
    point.score = 0.8
    point.payload = {
        "text": "likes cats",
        "user_id": "discord:123",
        "category": "FAIT",
        "date": "",
        "source": "test",
        "platform": "",
        "created_at": "2026-01-01",
    }

    scored = MagicMock()
    scored.id = point.id
    scored.score = point.score
    scored.payload = point.payload

    store._client.query_points.return_value = MagicMock(points=[scored])

    results = await store.search("cats", user_id="discord:123", min_score=0.6)

    assert len(results) == 1
    assert results[0].text == "likes cats"
    assert results[0].score == 0.8

    # Verify score_threshold was passed
    call_kwargs = store._client.query_points.call_args
    assert call_kwargs[1]["score_threshold"] == 0.6


@pytest.mark.asyncio
async def test_search_with_category_filter(store):
    store._client.query_points.return_value = MagicMock(points=[])

    await store.search(
        "cats",
        user_id="discord:123",
        filters={"category": "PREFERENCE"},
    )

    call_kwargs = store._client.query_points.call_args
    query_filter = call_kwargs[1]["query_filter"]
    # Should have conditions for both user_id and category
    conditions = query_filter.must
    field_keys = [c.key for c in conditions]
    assert "user_id" in field_keys
    assert "category" in field_keys


@pytest.mark.asyncio
async def test_get_all_returns_all_user_memories(store):
    # First scroll page: 2 points, with offset for next page
    p1 = MagicMock()
    p1.id = "id-1"
    p1.payload = {
        "text": "fact one",
        "user_id": "discord:123",
        "category": "FAIT",
        "date": "",
        "source": "chat",
        "platform": "discord",
        "created_at": "2026-01-01",
    }
    p2 = MagicMock()
    p2.id = "id-2"
    p2.payload = {
        "text": "fact two",
        "user_id": "discord:123",
        "category": "FAIT",
        "date": "",
        "source": "chat",
        "platform": "discord",
        "created_at": "2026-01-02",
    }

    # First call returns points + offset, second returns empty + None
    page1 = MagicMock()
    page1.points = [p1, p2]
    page1.next_page_offset = None

    store._client.scroll.return_value = (page1.points, None)

    results = await store.get_all("discord:123")

    assert len(results) == 2
    assert results[0].text == "fact one"
    assert results[1].text == "fact two"


@pytest.mark.asyncio
async def test_count_returns_point_count(store):
    count_result = MagicMock()
    count_result.count = 42
    store._client.count.return_value = count_result

    result = await store.count("discord:123")

    assert result == 42
    store._client.count.assert_called_once()


@pytest.mark.asyncio
async def test_delete_single_point(store):
    await store.delete("point-abc")

    store._client.delete.assert_called_once()
    call_args = store._client.delete.call_args
    assert call_args[1]["collection_name"] == "test_collection"


@pytest.mark.asyncio
async def test_delete_by_user(store):
    await store.delete_by_user("discord:123")

    store._client.delete.assert_called_once()
    call_args = store._client.delete.call_args
    assert call_args[1]["collection_name"] == "test_collection"


@pytest.mark.asyncio
async def test_update_re_embeds_and_replaces(store):
    meta = MemoryMetadata(user_id="discord:123", category="FAIT", source="test")
    await store.update("existing-id", "updated fact", meta)

    # Should call embedding
    store._openai.embeddings.create.assert_called_once()
    # Should call upsert with the existing id
    store._client.upsert.assert_called_once()
    call_args = store._client.upsert.call_args
    points = call_args[1]["points"]
    assert points[0].id == "existing-id"


@pytest.mark.asyncio
async def test_reset_recreates_collection(store):
    # Mock get_collection to return config
    collection_info = MagicMock()
    collection_info.config.params.vectors = MagicMock()
    store._client.get_collection.return_value = collection_info

    await store.reset()

    store._client.delete_collection.assert_called_once_with(
        collection_name="test_collection"
    )
    store._client.create_collection.assert_called_once()


@pytest.mark.asyncio
async def test_update_payload_without_re_embedding(store):
    await store.update_payload("point-abc", {"category": "PREFERENCE"})

    store._client.set_payload.assert_called_once()
    # Should NOT call embedding
    store._openai.embeddings.create.assert_not_called()


@pytest.mark.asyncio
async def test_point_to_record_mem0_backward_compat(store):
    """Old mem0 payloads use 'memory' key instead of 'text'."""
    point = MagicMock()
    point.id = "old-point"
    point.payload = {
        "memory": "old mem0 fact",
        "user_id": "discord:456",
    }

    record = store._point_to_record(point, score=0.9)

    assert record.text == "old mem0 fact"
    assert record.user_id == "discord:456"
    assert record.score == 0.9


def test_metadata_to_payload():
    meta = MemoryMetadata(user_id="discord:123", category="FAIT", source="chat")
    payload = meta.to_payload("some text")

    assert payload["text"] == "some text"
    assert payload["user_id"] == "discord:123"
    assert payload["category"] == "FAIT"
    assert payload["source"] == "chat"
    # date and created_at should have defaults
    assert payload["date"] != ""
    assert payload["created_at"] != ""
