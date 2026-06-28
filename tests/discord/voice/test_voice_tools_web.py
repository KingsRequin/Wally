import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.discord.voice.tools import build_voice_tools, make_voice_tool_executor


def _names(tools):
    return {t["function"]["name"] for t in tools}


@pytest.mark.asyncio
async def test_web_search_propose_si_dispo():
    bot = MagicMock()
    bot.web_search.available = True
    bot.web_search.is_quota_exceeded = AsyncMock(return_value=False)
    bot.action_service = None
    tools = await build_voice_tools(bot)
    assert "web_search" in _names(tools)


@pytest.mark.asyncio
async def test_web_search_absent_si_quota_depasse():
    bot = MagicMock()
    bot.web_search.available = True
    bot.web_search.is_quota_exceeded = AsyncMock(return_value=True)
    bot.action_service = None
    tools = await build_voice_tools(bot)
    assert "web_search" not in _names(tools)


@pytest.mark.asyncio
async def test_search_aloud_parle_amorce_puis_renvoie_resultat():
    bot = MagicMock()
    bot.web_search.search = AsyncMock(return_value="RESULTAT")
    service = MagicMock()
    service.speak = AsyncMock()
    with patch("bot.discord.voice.tools.generate_search_filler",
               new=AsyncMock(return_value={"amorce": "j'regarde", "bruits": ["mh..."]})):
        executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "1")
        out = await executor("web_search", json.dumps({"query": "prix ps5"}))
    assert out == "RESULTAT"
    # l'amorce a bien été parlée
    spoken = [c.args[0] for c in service.speak.await_args_list]
    assert "j'regarde" in spoken
    bot.web_search.search.assert_awaited_once()
