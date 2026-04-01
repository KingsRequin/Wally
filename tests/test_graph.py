# tests/test_graph.py
"""Tests for GraphService — Graphiti is mocked entirely."""
import pytest
from unittest.mock import MagicMock
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
