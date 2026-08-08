# tests/test_apex_discord_wiring.py
"""Le câblage de l'outil Apex sur le chemin Discord.

Le service peut être irréprochable et la fonctionnalité morte quand même : c'est
le handler qui offre l'outil et qui fournit l'identité du demandeur. On rejoue
donc la SÉQUENCE réelle des appelants, jusqu'à récupérer l'exécuteur d'outil
effectivement donné au LLM.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.core.apex import APEX_LEGENDS_TOOL


def _bot_avec_apex():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.config.bot.love_decay_lambda = 0.02
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.get_love_score = AsyncMock(return_value=0.0)
    bot.db.update_trust_score = AsyncMock()
    bot.db.update_love_score = AsyncMock()
    bot.db.mark_welcomed = AsyncMock()
    bot.db.upsert_memory_user = AsyncMock()
    bot.db.get_last_interaction = AsyncMock(return_value=None)
    bot.db.get_recent_jokes = AsyncMock(return_value=[])
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.add_timeout = AsyncMock()
    bot.memory.search = AsyncMock(return_value="")
    bot.memory.search_global = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.memory.get_pending_question_directive = AsyncMock(return_value="")
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="")
    bot.emotion.get_state = MagicMock(return_value={"anger": 0.0})
    bot.emotion.process_message = AsyncMock()
    bot.web_search = None
    bot.scrape = None

    apex_api = MagicMock()
    apex_api.available = True
    apex_api.get_tool_definition = MagicMock(return_value=APEX_LEGENDS_TOOL)
    apex_api.execute = AsyncMock(return_value="Diamond 2, 8400 RP")
    bot.apex_api = apex_api

    bot.llm.complete_with_tools = AsyncMock(return_value=("Il est Diamond 2", ["apex_legends"]))
    return bot


def _message():
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
    return msg


async def _repondre(bot, msg):
    from bot.discord.handlers import _respond

    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, msg, "12345", "99999", [])


@pytest.mark.asyncio
async def test_l_outil_apex_est_offert_au_llm():
    bot, msg = _bot_avec_apex(), _message()
    await _repondre(bot, msg)

    bot.llm.complete_with_tools.assert_awaited_once()
    outils = [t["function"]["name"] for t in bot.llm.complete_with_tools.call_args.args[2]]
    assert "apex_legends" in outils
    msg.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_l_executeur_transmet_l_identite_du_demandeur():
    """L'identité vient du handler, jamais du modèle — sinon la garde est morte."""
    bot, msg = _bot_avec_apex(), _message()
    await _repondre(bot, msg)

    executeur = bot.llm.complete_with_tools.call_args.args[3]
    await executeur("apex_legends", json.dumps({"action": "player_stats", "remember": True}))

    kwargs = bot.apex_api.execute.call_args.kwargs
    assert kwargs["requester"] == "discord:12345"
    assert kwargs["requester_name"] == "TestUser"
    assert kwargs["remember"] is True
