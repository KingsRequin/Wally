# tests/test_apex_discord_wiring.py
"""L'outil Apex est bien offert au LLM sur le chemin Discord.

Extrait de l'ancien `test_apex_api.py` : ce test ne porte pas sur le service
(qu'il double entièrement) mais sur son câblage dans le handler — la seule
partie que le passage au paquet `bot.core.apex` ne réécrit pas.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.core.apex import APEX_LEGENDS_TOOL

# ── Discord handler integration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discord_handler_adds_gun_reaction_on_apex():
    from bot.discord.handlers import _respond

    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.get_love_score = AsyncMock(return_value=0.0)
    bot.db.update_trust_score = AsyncMock()
    bot.db.update_love_score = AsyncMock()
    bot.db.mark_welcomed = AsyncMock()
    bot.db.upsert_memory_user = AsyncMock()
    bot.config.bot.love_decay_lambda = 0.02
    bot.memory.search = AsyncMock(return_value="")
    bot.memory.search_global = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.memory.get_pending_question_directive = AsyncMock(return_value="")
    bot.db.get_last_interaction = AsyncMock(return_value=None)
    bot.db.get_recent_jokes = AsyncMock(return_value=[])
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="")
    bot.emotion.get_state = MagicMock(return_value={"anger": 0.0})
    bot.emotion.process_message = AsyncMock()
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.add_timeout = AsyncMock()

    # No web search
    bot.web_search = None
    bot.scrape = None

    # Apex API mock
    apex_api = MagicMock()
    apex_api.available = True
    apex_api.get_tool_definition = MagicMock(return_value=APEX_LEGENDS_TOOL)
    apex_api.execute = AsyncMock(return_value="Diamond 2, 8400 RP")
    bot.apex_api = apex_api

    bot.llm.complete_with_tools = AsyncMock(return_value=("Il est Diamond 2", ["apex_legends"]))

    msg = MagicMock()
    msg.content = "wally c'est quoi le rank de Daltoosh"
    msg.author.id = 12345
    msg.author.display_name = "TestUser"
    msg.guild.id = 99999
    msg.channel.id = 777
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.mentions = []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.attachments = []

    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, msg, "12345", "99999", [])

    # complete_with_tools called with apex tool
    bot.llm.complete_with_tools.assert_awaited_once()
    call_args = bot.llm.complete_with_tools.call_args
    tools_passed = call_args.args[2]
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert "apex_legends" in tool_names
    # Response sent
    msg.reply.assert_awaited_once()
