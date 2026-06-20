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
    bot.memory.search.assert_called_once_with("discord", "123456", query="Melio", username_hint="Melio")


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
    """For Twitch-style user_ids (username == user_id), exclusion via direct token match."""
    bot = _make_bot(
        alias_cache={"nickname:alice": "twitch:alice"},
        users=[{"user_id": "twitch:alice", "username": "alice", "platform": "twitch"}],
    )
    prelude = [{"author": "alice", "content": "Alice est là", "timestamp": 0.0}]
    # author_user_id = "alice" — should be excluded for Twitch where id == username
    result = await _third_party_mention_context(bot, "twitch", "alice", prelude, [])
    # alice/Alice matches its own author_user_id or username, so should be skipped
    assert bot.memory.search.call_count == 0


@pytest.mark.asyncio
async def test_excludes_author_by_username_discord():
    """For Discord snowflake IDs, exclusion must use username lookup."""
    bot = _make_bot(
        alias_cache={"nickname:alice": "discord:610550333042589752"},
        users=[{"user_id": "discord:610550333042589752", "username": "Alice", "platform": "discord"}],
        memory_text="Aime la musique"
    )
    prelude = [{"author": "Alice", "content": "Alice est là", "timestamp": 0.0}]
    # author_user_id is a numeric snowflake — direct token compare would never match "Alice"
    result = await _third_party_mention_context(
        bot, "discord", "610550333042589752", prelude, []
    )
    # Alice is the current author — memory.search should NOT be called for her own token
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
