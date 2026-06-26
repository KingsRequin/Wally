import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.voice.tools import VOICE_TOOLS, make_voice_tool_executor


def _names():
    return {t["function"]["name"] for t in VOICE_TOOLS}


def test_tools_declared():
    assert {"join_voice", "leave_voice"} <= _names()


@pytest.mark.asyncio
async def test_leave_voice_speaks_then_leaves():
    bot = MagicMock()
    service = MagicMock()
    service.members_in_channel.return_value = [42]
    service.speak = AsyncMock()
    service.leave = AsyncMock()
    ex = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "42")
    out = await ex("leave_voice", json.dumps({}))
    service.speak.assert_awaited_once()
    service.leave.assert_awaited_once()
    assert json.loads(out)["status"] == "ok"


@pytest.mark.asyncio
async def test_leave_voice_rejected_for_non_member():
    bot = MagicMock()
    service = MagicMock()
    service.members_in_channel.return_value = [99]  # 42 pas dans le salon
    service.leave = AsyncMock()
    ex = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "42")
    out = await ex("leave_voice", json.dumps({}))
    service.leave.assert_not_awaited()
    assert json.loads(out)["status"] == "denied"
