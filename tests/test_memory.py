# tests/test_memory.py
"""
Tests for MemoryService — mem0/Qdrant is mocked entirely.
"""
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from bot.core.memory import MemoryService


def make_config(window_size=5, token_threshold=100):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
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
    assert svc._user_id("discord", "123") == "discord:123"
    assert svc._user_id("twitch", "alice") == "twitch:alice"


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
async def test_add_graceful_when_mem0_unavailable():
    svc = MemoryService(make_config())
    # mem0 is not initialized (no Qdrant in test env) — should not raise
    await svc.add("discord", "user1", "Alice likes cats")


@pytest.mark.asyncio
async def test_search_returns_empty_when_mem0_unavailable():
    svc = MemoryService(make_config())
    result = await svc.search("discord", "user1", "cats")
    assert result == ""
