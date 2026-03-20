# tests/test_proactive_recall.py
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from bot.core.memory import MemoryService


def make_config():
    config = MagicMock()
    config.bot.context_window_size = 20
    config.bot.context_token_threshold = 3000
    config.bot.prelude_window_size = 15
    config.openai.secondary_model = "gpt-4o-mini"
    return config


def make_mem0_results(memories: list[str], scores: list[float] | None = None):
    """Helper to build mem0-style results."""
    if scores is None:
        scores = [0.8] * len(memories)
    return {"results": [
        {"memory": m, "score": s} for m, s in zip(memories, scores)
    ]}


@pytest.mark.asyncio
async def test_search_with_context_makes_two_queries():
    """Avec context_messages, mem0.search est appelé 2 fois."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["souvenir1"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    context = [
        {"author": "Alice", "content": "je parle de mon chat"},
        {"author": "Bob", "content": "il est mignon"},
    ]
    result = await svc.search("discord", "123", "il fait beau", context_messages=context)

    assert mock_mem0.search.call_count == 2


@pytest.mark.asyncio
async def test_search_with_context_deduplicates():
    """Les deux recherches retournent le même souvenir → dédupliqué."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["Alice a un chat"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    context = [{"author": "Alice", "content": "mon chat dort"}]
    result = await svc.search("discord", "123", "il fait beau", context_messages=context)

    # Le souvenir ne doit apparaître qu'une fois malgré 2 recherches
    assert result.count("Alice a un chat") == 1


@pytest.mark.asyncio
async def test_search_without_context_unchanged():
    """Sans context_messages, une seule recherche (comportement existant)."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["souvenir"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    result = await svc.search("discord", "123", "salut")

    assert mock_mem0.search.call_count == 1
    assert "souvenir" in result


@pytest.mark.asyncio
async def test_search_context_excludes_wally_messages():
    """Les messages de Wally ne sont pas inclus dans la query contextuelle."""
    svc = MemoryService(make_config())
    calls = []

    def capture_search(query, user_id, limit=5):
        calls.append(query)
        return make_mem0_results([])

    mock_mem0 = MagicMock()
    mock_mem0.search = capture_search
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    context = [
        {"author": "Alice", "content": "sujet intéressant"},
        {"author": "Wally", "content": "réponse de wally"},
        {"author": "Bob", "content": "je suis d'accord"},
    ]
    await svc.search("discord", "123", "question", context_messages=context)

    # 2 appels : query directe + query contextuelle
    assert len(calls) == 2
    context_query = calls[1]
    assert "réponse de wally" not in context_query
    assert "sujet intéressant" in context_query
    assert "je suis d'accord" in context_query


@pytest.mark.asyncio
async def test_search_context_empty_prelude_fallback():
    """Prelude vide → une seule recherche."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["souvenir"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    result = await svc.search("discord", "123", "question", context_messages=[])

    assert mock_mem0.search.call_count == 1


@pytest.mark.asyncio
async def test_search_context_only_wally_messages_fallback():
    """Prelude avec uniquement des messages de Wally → une seule recherche."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["souvenir"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    context = [
        {"author": "Wally", "content": "blabla"},
        {"author": "Wally", "content": "encore moi"},
    ]
    result = await svc.search("discord", "123", "question", context_messages=context)

    assert mock_mem0.search.call_count == 1
