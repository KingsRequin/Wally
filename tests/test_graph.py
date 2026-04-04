# tests/test_graph.py
"""Tests for GraphService — Graphiti is mocked entirely."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.core.graph import GraphService


def _make_config(enabled=False):
    config = MagicMock()
    config.graphiti.enabled = enabled
    config.graphiti.neo4j_uri = "bolt://localhost:7687"
    config.graphiti.neo4j_user = "neo4j"
    config.graphiti.neo4j_password = "test"
    config.graphiti.llm_model = "gpt-5-nano"
    config.graphiti.group_id = "test:default"
    config.graphiti.community_detection = False
    config.graphiti.affinity_weights = {
        "voice": 3.0, "reply": 2.0, "mention": 1.5,
        "reaction": 1.0, "thread": 1.0, "game": 2.5,
    }
    config.graphiti.graph_context_max_tokens = 400
    return config


def test_graph_service_not_ready_by_default():
    svc = GraphService(_make_config())
    assert not svc.ready


@pytest.mark.asyncio
async def test_add_episode_returns_none_when_not_ready():
    svc = GraphService(_make_config())
    result = await svc.add_episode("hello", "Alice")
    assert result is None


@pytest.mark.asyncio
async def test_search_returns_empty_when_not_ready():
    svc = GraphService(_make_config())
    results = await svc.search("hello")
    assert results == []


@pytest.mark.asyncio
async def test_get_affinity_returns_zero_when_not_ready():
    svc = GraphService(_make_config())
    score = await svc.get_affinity("Alice", "Bob")
    assert score == 0.0


@pytest.mark.asyncio
async def test_close_when_not_initialized():
    svc = GraphService(_make_config())
    await svc.close()  # Should not raise


@pytest.mark.asyncio
async def test_initialize_disabled():
    svc = GraphService(_make_config(enabled=False))
    result = await svc.initialize()
    assert result is False
    assert not svc.ready


@pytest.mark.asyncio
async def test_fact_extractor_calls_graph_add_episode():
    """FactExtractor should call graph.add_episode for each flushed message."""
    from bot.core.fact_extractor import FactExtractor

    config = _make_config()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100

    memory = AsyncMock()
    llm = AsyncMock()
    graph = AsyncMock()
    graph.ready = True
    graph.add_episode = AsyncMock(return_value={"entities": [], "edges": []})

    extractor = FactExtractor(config, memory, llm, graph=graph)
    assert extractor._graph is graph


@pytest.mark.asyncio
async def test_get_affinity_cypher_direct():
    """get_affinity() uses Cypher query, not semantic search."""
    svc = GraphService(_make_config())
    svc._ready = True
    svc._graphiti = MagicMock()

    # Mock du driver : retourne 2 arêtes de type "vocal" et 1 "reply"
    mock_record_voice = MagicMock()
    mock_record_voice.__getitem__ = lambda self, k: {"type": "EN_VOCAL_AVEC", "cnt": 2}[k]
    mock_record_reply = MagicMock()
    mock_record_reply.__getitem__ = lambda self, k: {"type": "REPOND_A", "cnt": 1}[k]

    mock_result = MagicMock()
    mock_result.records = [mock_record_voice, mock_record_reply]
    svc._graphiti.driver = AsyncMock()
    svc._graphiti.driver.execute_query = AsyncMock(return_value=mock_result)

    score = await svc.get_affinity("Alice", "Bob")
    # voice × 2 = 6.0, reply × 1 = 2.0 → total 8.0
    assert score == 8.0

    # Vérifier que execute_query a bien été appelé (pas graphiti.search)
    svc._graphiti.driver.execute_query.assert_called_once()
    call_args = svc._graphiti.driver.execute_query.call_args
    assert "RELATES_TO" in call_args[0][0]


@pytest.mark.asyncio
async def test_get_social_context_returns_pairs():
    """get_social_context() returns list of (name_a, name_b, strength) tuples."""
    svc = GraphService(_make_config())
    svc._ready = True
    svc._graphiti = MagicMock()

    # Mock : 2 paires, strength 12 et 4
    def _rec(ua, ub, strength):
        r = MagicMock()
        r.__getitem__ = lambda self, k: {"ua": ua, "ub": ub, "strength": strength}[k]
        return r

    mock_result = MagicMock()
    mock_result.records = [_rec("Keychka", "Azrael", 12), _rec("Saphira", "Keychka", 4)]
    svc._graphiti.driver = AsyncMock()
    svc._graphiti.driver.execute_query = AsyncMock(return_value=mock_result)

    pairs = await svc.get_social_context()
    assert pairs == [("Keychka", "Azrael", 12), ("Saphira", "Keychka", 4)]


@pytest.mark.asyncio
async def test_get_social_context_returns_empty_when_not_ready():
    svc = GraphService(_make_config())
    pairs = await svc.get_social_context()
    assert pairs == []


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
