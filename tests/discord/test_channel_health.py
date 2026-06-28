# tests/discord/test_channel_health.py
import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.discord.channel_health import find_dead_channels, report_dead_channels


def _bot_with_config(notif=None, bedroom=None, journal=None):
    bot = MagicMock()
    bot.config.bot.notification_channel_id = notif
    bot.config.bot.bedroom_channel_id = bedroom
    bot.config.bot.journal_channel_id = journal
    return bot


@pytest.mark.asyncio
async def test_canal_vivant_non_signale(tmp_path):
    bot = _bot_with_config(notif=111)
    bot.get_channel.return_value = object()        # présent dans le cache → vivant
    dead = await find_dead_channels(bot, tmp_path / "absent.md")
    assert dead == []


@pytest.mark.asyncio
async def test_canal_mort_detecte(tmp_path):
    bot = _bot_with_config(notif=111)
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
    dead = await find_dead_channels(bot, tmp_path / "absent.md")
    assert [d[0] for d in dead] == ["111"]
    assert "notification_channel_id" in dead[0][1]


@pytest.mark.asyncio
async def test_report_dm_createur_si_mort(tmp_path):
    bot = _bot_with_config(notif=111)
    bot.config.bot.owner_discord_id = "610550333042589752"
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
    owner = MagicMock(); owner.send = AsyncMock()
    bot.fetch_user = AsyncMock(return_value=owner)
    await report_dead_channels(bot, tmp_path / "absent.md")
    owner.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_canal_de_channels_md_detecte(tmp_path):
    bot = _bot_with_config()          # all config ids None
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), "gone"))
    md = tmp_path / "CHANNELS.md"
    md.write_text("111 | #test | text | un canal de test\n")
    dead = await find_dead_channels(bot, md)
    assert [d[0] for d in dead] == ["111"]
    assert "CHANNELS.md" in dead[0][1]


@pytest.mark.asyncio
async def test_report_pas_de_dm_si_tout_vivant(tmp_path):
    bot = _bot_with_config(notif=111)
    bot.config.bot.owner_discord_id = "610550333042589752"
    bot.get_channel.return_value = object()
    bot.fetch_user = AsyncMock()
    await report_dead_channels(bot, tmp_path / "absent.md")
    bot.fetch_user.assert_not_awaited()
