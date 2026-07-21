# tests/test_typing_perception.py
"""Perception cognitive des indicateurs de frappe Discord (on_typing → notify_typing)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _user(uid, name, display=None, is_bot=False):
    return SimpleNamespace(id=uid, name=name, display_name=display or name, bot=is_bot)


def _channel(channel_id=7, guild_id=1):
    guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
    return SimpleNamespace(id=channel_id, guild=guild)


def _make_bot():
    """Capture le handler on_typing enregistré via @bot.event."""
    bot = MagicMock()
    bot.user = _user(999, "Wally")
    bot.config.discord.ignored_guilds = set()
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_typing = MagicMock()

    captured = {}

    def _event(fn):
        captured["on_typing"] = fn
        return fn

    bot.event = _event

    from bot.discord.events import typing as typing_events
    typing_events.register(bot)
    return bot, captured["on_typing"]


@pytest.mark.asyncio
async def test_typing_feeds_cognitive_loop():
    bot, on_typing = _make_bot()
    alice = _user(42, "alice", "Alice")
    await on_typing(_channel(), alice, None)

    bot.cognitive_loop.notify_typing.assert_called_once()
    args, _ = bot.cognitive_loop.notify_typing.call_args
    assert args[0] == 7                    # channel_id
    assert args[1] == "Alice (@alice)"     # label complet (display ≠ username)


@pytest.mark.asyncio
async def test_typing_by_bot_ignored():
    bot, on_typing = _make_bot()
    rythm = _user(60, "rythm", "Rythm", is_bot=True)
    await on_typing(_channel(), rythm, None)
    bot.cognitive_loop.notify_typing.assert_not_called()


@pytest.mark.asyncio
async def test_typing_by_wally_himself_ignored():
    bot, on_typing = _make_bot()
    await on_typing(_channel(), _user(999, "Wally"), None)
    bot.cognitive_loop.notify_typing.assert_not_called()


@pytest.mark.asyncio
async def test_typing_in_ignored_guild_skipped():
    bot, on_typing = _make_bot()
    bot.config.discord.ignored_guilds = {1}
    alice = _user(42, "alice", "Alice")
    await on_typing(_channel(guild_id=1), alice, None)
    bot.cognitive_loop.notify_typing.assert_not_called()


@pytest.mark.asyncio
async def test_typing_in_dm_still_perceived():
    """Un DM (channel sans guild) reste une perception passive valide."""
    bot, on_typing = _make_bot()
    alice = _user(42, "alice", "Alice")
    await on_typing(_channel(guild_id=None), alice, None)
    bot.cognitive_loop.notify_typing.assert_called_once()


@pytest.mark.asyncio
async def test_typing_no_cognitive_loop_is_noop():
    bot, on_typing = _make_bot()
    bot.cognitive_loop = None
    alice = _user(42, "alice", "Alice")
    await on_typing(_channel(), alice, None)  # ne lève pas
