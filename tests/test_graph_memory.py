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
    return cfg


@pytest.mark.asyncio
async def test_add_user_fact_calls_graph_add_episode(mock_graph, mock_config):
    """add_user_fact() calls graph.add_episode with correct content and source."""
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
    # body = "KingsRequin : préfère le café au thé"
    assert call_kwargs["content"] == "KingsRequin : préfère le café au thé"
    assert "KingsRequin" in call_kwargs["source"]
    assert call_kwargs["author"] == "KingsRequin"


@pytest.mark.asyncio
async def test_add_user_fact_includes_aliases_in_source(mock_graph, mock_config):
    """add_user_fact() injects known aliases into source."""
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
    source = call_kwargs["source"]
    # Only aliases belonging to discord:123456 should appear
    assert "requin" in source.lower() or "kings" in source.lower()
    # Alias of another user should NOT appear
    assert "other" not in source.lower()


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
        {"fact": "KingsRequin aime le café", "valid_at": None, "invalid_at": None},
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
async def test_search_user_facts_returns_empty_when_no_results(mock_graph, mock_config):
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
