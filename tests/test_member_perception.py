# tests/test_member_perception.py
"""Perception cognitive des arrivées de membres Discord (#A2)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _member(uid=42, name="azrael", display="Azrael", is_bot=False, guild=None):
    return SimpleNamespace(
        id=uid, name=name, display_name=display, bot=is_bot, guild=guild,
    )


def _guild(gid=1, name="Le Serveur", system_channel_id=77):
    sysch = SimpleNamespace(id=system_channel_id) if system_channel_id else None
    return SimpleNamespace(id=gid, name=name, system_channel=sysch)


def _make_bot():
    bot = MagicMock()
    bot.config.discord.ignored_guilds = set()
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_event = MagicMock()
    return bot


@pytest.mark.asyncio
async def test_member_join_feeds_cognitive_loop():
    from bot.discord.handlers import _member_join_context
    bot = _make_bot()
    guild = _guild()
    await _member_join_context(bot, _member(guild=guild))

    bot.cognitive_loop.notify_event.assert_called_once()
    _, kwargs = bot.cognitive_loop.notify_event.call_args
    assert kwargs["channel_id"] == 77            # system_channel
    assert "Azrael (@azrael)" in kwargs["description"]
    assert "rejoin" in kwargs["description"].lower()
    assert kwargs["relevant"] is False           # perception passive


@pytest.mark.asyncio
async def test_member_join_bot_ignored():
    from bot.discord.handlers import _member_join_context
    bot = _make_bot()
    await _member_join_context(bot, _member(is_bot=True, guild=_guild()))
    bot.cognitive_loop.notify_event.assert_not_called()


@pytest.mark.asyncio
async def test_member_join_ignored_guild():
    from bot.discord.handlers import _member_join_context
    bot = _make_bot()
    bot.config.discord.ignored_guilds = {1}
    await _member_join_context(bot, _member(guild=_guild(gid=1)))
    bot.cognitive_loop.notify_event.assert_not_called()


@pytest.mark.asyncio
async def test_member_join_no_system_channel_uses_guild_id():
    from bot.discord.handlers import _member_join_context
    bot = _make_bot()
    guild = _guild(gid=5, system_channel_id=None)
    await _member_join_context(bot, _member(guild=guild))
    _, kwargs = bot.cognitive_loop.notify_event.call_args
    assert kwargs["channel_id"] == 5             # fallback : id du serveur


@pytest.mark.asyncio
async def test_member_join_no_cognitive_loop_noop():
    from bot.discord.handlers import _member_join_context
    bot = _make_bot()
    bot.cognitive_loop = None
    # ne doit pas lever
    await _member_join_context(bot, _member(guild=_guild()))
