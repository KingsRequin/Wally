# tests/test_memory.py
"""
Tests for MemoryService — QdrantMemoryStore is mocked entirely.
"""
import time

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from bot.core.memory import MemoryService


def make_config(window_size=5, token_threshold=100):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5
    return config


def test_append_and_get_context():
    svc = MemoryService(make_config())
    svc.append_message("ch1", "Alice", "Hello")
    svc.append_message("ch1", "Bob", "World")
    ctx = svc.get_context("ch1")
    assert len(ctx) == 2
    assert ctx[0]["author"] == "Alice"
    assert ctx[0]["content"] == "Hello"
    assert ctx[1]["author"] == "Bob"
    assert "timestamp" in ctx[0]


def test_context_window_trims_to_max():
    svc = MemoryService(make_config(window_size=3))
    for i in range(5):
        svc.append_message("ch1", "User", f"Message {i}")
    ctx = svc.get_context("ch1")
    assert len(ctx) == 3
    assert ctx[0]["content"] == "Message 2"  # oldest kept


def test_empty_context_returns_empty_list():
    svc = MemoryService(make_config())
    assert svc.get_context("nonexistent") == []


def test_channels_are_independent():
    svc = MemoryService(make_config())
    svc.append_message("ch1", "Alice", "In channel 1")
    svc.append_message("ch2", "Bob", "In channel 2")
    assert len(svc.get_context("ch1")) == 1
    assert len(svc.get_context("ch2")) == 1
    assert svc.get_context("ch1")[0]["author"] == "Alice"


def test_user_id_namespacing():
    svc = MemoryService(make_config())
    # Discord snowflakes are 17-20 digits
    assert svc._user_id("discord", "610550333042589752") == "discord:610550333042589752"
    assert svc._user_id("twitch", "alice") == "twitch:alice"
    # Short numeric IDs on discord get redirected to twitch (cross-platform fix)
    assert svc._user_id("discord", "123") == "twitch:123"
    # Long numeric IDs on twitch get redirected to discord
    assert svc._user_id("twitch", "610550333042589752") == "discord:610550333042589752"


@pytest.mark.asyncio
async def test_get_context_summarized_returns_messages_when_below_threshold():
    svc = MemoryService(make_config(token_threshold=10000))
    svc.append_message("ch1", "Alice", "Short message")
    result = await svc.get_context_summarized_if_needed("ch1")
    assert len(result) == 1
    assert result[0]["author"] == "Alice"


@pytest.mark.asyncio
async def test_get_context_summarized_when_no_openai_returns_as_is():
    # Without openai client set, should return messages unmodified even if over threshold
    svc = MemoryService(make_config(token_threshold=1))
    svc.append_message("ch1", "Alice", "A" * 10)
    result = await svc.get_context_summarized_if_needed("ch1")
    assert len(result) == 1  # no openai, no summarization


@pytest.mark.asyncio
async def test_add_graceful_when_store_unavailable():
    svc = MemoryService(make_config())
    # store is not initialized (no Qdrant in test env) — should not raise
    await svc.add("discord", "user1", "Alice likes cats")


@pytest.mark.asyncio
async def test_search_returns_empty_when_store_unavailable():
    svc = MemoryService(make_config())
    result = await svc.search("discord", "user1", "cats")
    assert result == ""


@pytest.mark.asyncio
async def test_search_returns_empty_when_all_scores_too_low():
    """Si tous les résultats sont sous le seuil, retourner chaîne vide."""
    svc = MemoryService(make_config())
    svc._store_init_attempted = True
    svc._store = AsyncMock()
    # Store returns empty when all below min_score threshold
    svc._store.search = AsyncMock(return_value=[])

    result = await svc.search("discord", "user1", "quelque chose")
    assert result == ""



def test_get_all_contexts_returns_all_sorted():
    svc = MemoryService(make_config())
    svc.append_message("ch1", "Alice", "First")
    svc.append_message("ch2", "Bob", "Second")
    # Force timestamps to ensure deterministic order
    svc._context_windows["ch1"][0]["timestamp"] = 1.0
    svc._context_windows["ch2"][0]["timestamp"] = 2.0
    all_ctx = svc.get_all_contexts()
    assert len(all_ctx) == 2
    assert all_ctx[0]["author"] == "Alice"
    assert all_ctx[1]["author"] == "Bob"


def test_get_all_contexts_empty():
    svc = MemoryService(make_config())
    assert svc.get_all_contexts() == []


@pytest.mark.asyncio
async def test_summarize_messages_multi_pass():
    """When messages span >1 chunk, a final combining call is made."""
    svc = MemoryService(make_config())

    call_count = 0

    async def fake_complete(system, messages, purpose="summary"):
        nonlocal call_count
        call_count += 1
        return f"summary_{call_count}"

    mock_openai = MagicMock()
    mock_openai.complete = fake_complete
    svc.set_openai_client(mock_openai)

    # 15 messages → 2 chunks (10 + 5) → 2 chunk summaries + 1 final = 3 calls
    messages = [
        {"author": "U", "content": f"msg{i}", "timestamp": float(i)}
        for i in range(15)
    ]
    result = await svc._summarize_messages(messages)

    assert call_count == 3
    assert result == "summary_3"  # the final combining call


# ── Prelude buffer ────────────────────────────────────────────────────────────

def make_config_prelude(window_size=5, token_threshold=100, prelude_size=3):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
    config.bot.prelude_window_size = prelude_size
    config.bot.memory_search_min_score = 0.5
    return config


def test_append_prelude_circular():
    svc = MemoryService(make_config_prelude(prelude_size=3))
    for i in range(5):
        svc.append_prelude("ch1", "User", f"msg {i}")
    result = svc.get_prelude("ch1")
    assert len(result) == 3
    assert result[0]["content"] == "msg 2"  # oldest kept


def test_get_prelude_returns_copy():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "hello")
    copy = svc.get_prelude("ch1")
    copy.append({"author": "X", "content": "injected", "timestamp": 0})
    assert len(svc.get_prelude("ch1")) == 1  # original untouched


def test_prelude_independent_from_context_windows():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "prelude msg")
    svc.append_message("ch1", "Alice", "context msg")
    assert len(svc.get_prelude("ch1")) == 1
    assert len(svc.get_context("ch1")) == 1
    assert svc.get_prelude("ch1")[0]["content"] == "prelude msg"
    assert svc.get_context("ch1")[0]["content"] == "context msg"


def test_prelude_reset_clears_buffer():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "hello")
    assert len(svc.get_prelude("ch1")) == 1
    # reset_all() doit aussi purger _prelude_windows
    import asyncio
    asyncio.run(svc.reset_all())
    assert svc.get_prelude("ch1") == []


