# tests/test_spam_detection.py
"""
Tests for spam detection in Discord message handler.
"""
import time
from collections import deque

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.discord.handlers import _check_spam, _spam_tracker, handle_message


def _make_spam_bot(enabled=True, max_messages=3, window_seconds=10, mute_minutes=5,
                   spam_anger_delta=0.05, exempt_channels=None):
    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.config.bot.spontaneous_discord_enabled = False
    bot.config.discord.channel_filter_mode = "none"
    bot.config.discord.channel_whitelist = []
    bot.config.discord.channel_blacklist = []
    bot.config.discord.emoji_reaction_probability = 0.0
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10

    bot.config.discord.spam_detection.enabled = enabled
    bot.config.discord.spam_detection.max_messages = max_messages
    bot.config.discord.spam_detection.window_seconds = window_seconds
    bot.config.discord.spam_detection.mute_minutes = mute_minutes
    bot.config.discord.spam_detection.spam_anger_delta = spam_anger_delta
    bot.config.discord.spam_detection.exempt_channels = exempt_channels or []

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    bot.emotion.apply_delta = MagicMock()

    bot.llm_secondary = MagicMock()
    bot.llm_secondary.complete = AsyncMock(return_value="Calme-toi un peu.")

    bot.db = MagicMock()
    bot.db.add_timeout = AsyncMock()
    bot.db.is_muted = AsyncMock(return_value=False)
    bot.db.is_welcomed = AsyncMock(return_value=True)

    bot.memory = MagicMock()
    bot.memory.add = AsyncMock()
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()

    bot.persona = MagicMock()
    bot.persona.is_beloved = MagicMock(return_value=False)

    return bot


def _make_msg(content="spam", author_id=12345, channel_id=777, guild_id=99999):
    msg = MagicMock()
    msg.content = content
    msg.author.bot = False
    msg.author.id = author_id
    msg.author.display_name = "Spammer"
    msg.guild.id = guild_id
    msg.channel.id = channel_id
    msg.mentions = []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.reference = None
    msg.attachments = []
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    return msg


@pytest.fixture(autouse=True)
def clear_spam_tracker():
    _spam_tracker.clear()
    yield
    _spam_tracker.clear()


@pytest.mark.asyncio
async def test_spam_triggers_after_threshold():
    """3 messages in window triggers mute + warning + memory."""
    bot = _make_spam_bot(max_messages=3, window_seconds=10)
    msg = _make_msg()

    # First two messages — no spam
    assert await _check_spam(bot, msg) is False
    assert await _check_spam(bot, msg) is False
    # Third message — spam detected
    assert await _check_spam(bot, msg) is True

    # Warning sent
    msg.channel.send.assert_awaited_once()
    # Mute applied
    bot.db.add_timeout.assert_awaited_once()
    # Memory stored
    bot.memory.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_spam_disabled_does_not_trigger():
    """Disabled config = no mute."""
    bot = _make_spam_bot(enabled=False, max_messages=1)
    msg = _make_msg()

    assert await _check_spam(bot, msg) is False
    bot.db.add_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_exempt_channel_skips_spam_check():
    """Exempt channels ignored."""
    bot = _make_spam_bot(max_messages=1, exempt_channels=[777])
    msg = _make_msg(channel_id=777)

    assert await _check_spam(bot, msg) is False
    bot.db.add_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_muted_user_anger_increases():
    """Muted user messages increase anger when spam detection enabled."""
    bot = _make_spam_bot(enabled=True, spam_anger_delta=0.05)
    bot.db.is_muted = AsyncMock(return_value=True)
    msg = _make_msg(content="wally hey")  # triggered message

    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, msg)

    # Reaction added (muted user gets emoji)
    msg.add_reaction.assert_awaited_once()
    # Anger delta applied
    bot.emotion.apply_delta.assert_called_once_with("anger", 0.05)


@pytest.mark.asyncio
async def test_spam_tracker_cleans_old_entries():
    """Old timestamps purged from tracker."""
    bot = _make_spam_bot(max_messages=5, window_seconds=10)
    msg = _make_msg()

    key = (str(msg.author.id), str(msg.channel.id))

    # Pre-fill tracker with old timestamps
    old_time = time.time() - 20  # 20 seconds ago, outside 10s window
    _spam_tracker[key] = deque([old_time, old_time + 1])

    # Send a new message — old entries should be purged
    result = await _check_spam(bot, msg)
    assert result is False

    # Only the new timestamp should remain
    assert len(_spam_tracker[key]) == 1


@pytest.mark.asyncio
async def test_spam_does_not_trigger_in_dms():
    """DMs should be excluded from spam detection."""
    bot = _make_spam_bot(max_messages=1)
    msg = _make_msg()
    msg.guild = None  # DM

    assert await _check_spam(bot, msg) is False
    bot.db.add_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_different_channels_have_separate_trackers():
    """Spam tracking is per-channel, not global per-user."""
    bot = _make_spam_bot(max_messages=3, window_seconds=60)

    # 2 messages in channel 100
    msg1 = _make_msg(channel_id=100)
    assert await _check_spam(bot, msg1) is False
    assert await _check_spam(bot, msg1) is False

    # 2 messages in channel 200 (same user)
    msg2 = _make_msg(channel_id=200)
    assert await _check_spam(bot, msg2) is False
    assert await _check_spam(bot, msg2) is False

    # Neither should have triggered (threshold is 3)
    bot.db.add_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_tracker_resets_after_spam_trigger():
    """After spam is triggered, the tracker is cleared for that user/channel."""
    bot = _make_spam_bot(max_messages=2, window_seconds=60)
    msg = _make_msg()

    # Trigger spam
    assert await _check_spam(bot, msg) is False
    assert await _check_spam(bot, msg) is True

    key = (str(msg.author.id), str(msg.channel.id))
    # Tracker should be cleared
    assert key not in _spam_tracker
