# tests/discord/voice/test_voice_tools_reminder.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.voice.tools import build_voice_tools, make_voice_tool_executor


def _names(tools):
    return {t["function"]["name"] for t in tools}


def _action_tool(name):
    return {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}


@pytest.mark.asyncio
async def test_outils_action_proposes_si_service_present():
    bot = MagicMock()
    bot.web_search = None
    bot.action_service.get_tool_definitions.return_value = [_action_tool("create_action_task")]
    tools = await build_voice_tools(bot)
    assert "create_action_task" in _names(tools)


@pytest.mark.asyncio
async def test_create_reminder_utilise_la_chambre():
    bot = MagicMock()
    bot.config.bot.bedroom_channel_id = 1485380606224502844
    bot.config.admin_ids = []
    bot.action_service.execute_tool = AsyncMock(return_value={"status": "ok"})
    member = MagicMock(); member.id = 42
    service = MagicMock()
    service._channel.members = [member]
    service._channel.guild.id = 999
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "42")
    out = await executor("create_action_task", json.dumps({"foo": "bar"}))
    assert json.loads(out)["status"] == "ok"
    kwargs = bot.action_service.execute_tool.await_args.kwargs
    assert kwargs["channel_id"] == "1485380606224502844"
    assert kwargs["user_id"] == "42"
    assert kwargs["guild_id"] == "999"


@pytest.mark.asyncio
async def test_create_reminder_refuse_sans_chambre():
    bot = MagicMock()
    bot.config.bot.bedroom_channel_id = None
    bot.action_service.execute_tool = AsyncMock()
    service = MagicMock()
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "42")
    out = await executor("create_action_task", json.dumps({}))
    assert json.loads(out)["status"] == "denied"
    bot.action_service.execute_tool.assert_not_awaited()
