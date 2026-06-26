# tests/discord/voice/test_voice_cmd.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.commands.voice_cmd import VoiceCog


@pytest.mark.asyncio
async def test_join_uses_caller_voice_channel():
    bot = MagicMock()
    bot.voice_service.join = AsyncMock()
    cog = VoiceCog(bot)
    inter = MagicMock()
    inter.user.voice.channel = MagicMock()
    inter.response.send_message = AsyncMock()
    await cog.join.callback(cog, inter)
    bot.voice_service.join.assert_awaited_once_with(inter.user.voice.channel)


@pytest.mark.asyncio
async def test_join_without_channel_warns():
    bot = MagicMock()
    bot.voice_service.join = AsyncMock()
    cog = VoiceCog(bot)
    inter = MagicMock()
    inter.user.voice = None
    inter.response.send_message = AsyncMock()
    await cog.join.callback(cog, inter)
    bot.voice_service.join.assert_not_awaited()
    inter.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_leave_calls_service():
    bot = MagicMock()
    bot.voice_service.leave = AsyncMock()
    bot.voice_service.is_connected = True
    cog = VoiceCog(bot)
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    await cog.leave.callback(cog, inter)
    bot.voice_service.leave.assert_awaited_once()
