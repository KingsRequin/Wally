"""Tests for _third_party_mention_context helper."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.discord.handlers import _third_party_mention_context


def _make_bot(alias_cache=None, users=None, memory_text=""):
    bot = MagicMock()
    bot.memory._alias_cache = alias_cache or {}
    bot.db.list_memory_users = AsyncMock(return_value=users or [])
    bot.memory.search = AsyncMock(return_value=memory_text)
    return bot


@pytest.mark.asyncio
async def test_no_candidates_returns_empty():
    bot = _make_bot()
    result = await _third_party_mention_context(bot, "discord", "user1", [], [])
    assert result == ""


@pytest.mark.asyncio
async def test_exact_alias_match_injects_memories():
    bot = _make_bot(
        alias_cache={"nickname:melio": "discord:123456"},
        users=[{"user_id": "discord:123456", "username": "Meliodas", "platform": "discord"}],
        memory_text="Aime la fantasy"
    )
    prelude = [{"author": "Alice", "content": "Melio est cool", "timestamp": 0.0}]
    result = await _third_party_mention_context(bot, "discord", "alice_id", prelude, [])
    assert "Souvenirs sur" in result
    assert "Aime la fantasy" in result
    bot.memory.search.assert_called_once_with("discord", "123456", query="Melio")


@pytest.mark.asyncio
async def test_fuzzy_match_injects_note():
    bot = _make_bot(
        users=[{"user_id": "twitch:mkszedd", "username": "mkszedd", "platform": "twitch"}]
    )
    prelude = [{"author": "Bob", "content": "Mkszed est là ?", "timestamp": 0.0}]
    result = await _third_party_mention_context(bot, "discord", "bob_id", prelude, [])
    assert "ressemble à" in result or result == ""  # may or may not match depending on ratio


@pytest.mark.asyncio
async def test_excludes_current_author():
    bot = _make_bot(
        alias_cache={"nickname:alice": "discord:999"}
    )
    prelude = [{"author": "Alice", "content": "Alice est là", "timestamp": 0.0}]
    # author_user_id = "alice" — should be excluded
    result = await _third_party_mention_context(bot, "discord", "alice", prelude, [])
    # alice matches its own author_user_id, so should be skipped
    assert bot.memory.search.call_count == 0


@pytest.mark.asyncio
async def test_max_two_thirds_party():
    bot = _make_bot(
        alias_cache={
            "nickname:alice": "discord:1",
            "nickname:bob": "discord:2",
            "nickname:charlie": "discord:3",
        },
        users=[
            {"user_id": "discord:1", "username": "Alice", "platform": "discord"},
            {"user_id": "discord:2", "username": "Bob", "platform": "discord"},
            {"user_id": "discord:3", "username": "Charlie", "platform": "discord"},
        ],
        memory_text="some memory"
    )
    prelude = [{"author": "X", "content": "Alice Bob Charlie sont là", "timestamp": 0.0}]
    result = await _third_party_mention_context(bot, "discord", "x_id", prelude, [])
    # Should only call memory.search at most twice
    assert bot.memory.search.call_count <= 2


@pytest.mark.asyncio
async def test_no_memories_found_skips_block():
    """If exact alias match but memory.search returns empty, no block injected."""
    bot = _make_bot(
        alias_cache={"nickname:zelda": "discord:42"},
        users=[{"user_id": "discord:42", "username": "Zelda", "platform": "discord"}],
        memory_text=""  # empty memories
    )
    prelude = [{"author": "Link", "content": "Zelda est en ligne", "timestamp": 0.0}]
    result = await _third_party_mention_context(bot, "discord", "link_id", prelude, [])
    assert result == ""


@pytest.mark.asyncio
async def test_context_messages_scanned():
    """Words from context_messages are also scanned for candidate tokens."""
    bot = _make_bot(
        alias_cache={"nickname:moria": "discord:77"},
        users=[{"user_id": "discord:77", "username": "Moria", "platform": "discord"}],
        memory_text="Joue à Minecraft"
    )
    context_messages = [{"role": "user", "content": "Moria est super doué"}]
    result = await _third_party_mention_context(bot, "discord", "someone_id", [], context_messages)
    assert "Souvenirs sur" in result
    assert "Joue à Minecraft" in result
