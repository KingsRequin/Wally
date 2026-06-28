import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.voice.tools import build_voice_tools, make_voice_tool_executor


def _names(tools):
    return {t["function"]["name"] for t in tools}


@pytest.mark.asyncio
async def test_notes_proposees_en_vocal():
    bot = MagicMock()
    bot.web_search = None
    bot.action_service = None
    tools = await build_voice_tools(bot)
    assert {"save_persistent_note", "delete_persistent_note"} <= _names(tools)


@pytest.mark.asyncio
async def test_save_note_execute_en_vocal():
    bot = MagicMock()
    bot.db.upsert_persistent_note = AsyncMock()
    service = MagicMock()
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "1")
    out = await executor("save_persistent_note",
                         json.dumps({"title": "LAN", "content": "samedi 20h"}))
    bot.db.upsert_persistent_note.assert_awaited_once_with("LAN", "samedi 20h")
    assert json.loads(out)["status"] == "ok"


@pytest.mark.asyncio
async def test_delete_note_introuvable():
    bot = MagicMock()
    bot.db.delete_persistent_note = AsyncMock(return_value=False)
    service = MagicMock()
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "1")
    out = await executor("delete_persistent_note", json.dumps({"title": "X"}))
    assert json.loads(out)["status"] == "not_found"
