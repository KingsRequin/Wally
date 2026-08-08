# tests/test_apex_twitch_wiring.py
"""Le câblage de l'outil Apex sur le chemin Twitch.

Même exigence que côté Discord : l'identité du demandeur doit venir du handler.
Les doublures sont IMPORTÉES de `test_twitch_handlers` plutôt que recopiées —
une copie divergerait du vrai harnais sans que rien ne le signale.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.core.apex import APEX_LEGENDS_TOOL
from bot.twitch.handlers import handle_message
from tests.test_twitch_handlers import make_bot, make_payload


def _bot_avec_apex():
    bot = make_bot(trigger_names=["wally"])
    apex_api = MagicMock()
    apex_api.available = True
    apex_api.get_tool_definition = MagicMock(return_value=APEX_LEGENDS_TOOL)
    apex_api.execute = AsyncMock(return_value="Gold 3, 6422 RP")
    bot.apex_api = apex_api
    return bot


@pytest.mark.asyncio
async def test_l_executeur_transmet_l_identite_du_demandeur(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = _bot_avec_apex()
    payload = make_payload(content="wally mes stats apex", author_name="xeforce_", author_id="222")

    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)

    executeur = bot.llm.complete_with_tools.call_args.args[3]
    await executeur("apex_legends", json.dumps({"action": "player_stats", "remember": True}))

    kwargs = bot.apex_api.execute.call_args.kwargs
    assert kwargs["requester"] == "twitch:222"
    assert kwargs["requester_name"] == "xeforce_"
    assert kwargs["remember"] is True


@pytest.mark.asyncio
async def test_l_outil_apex_est_offert_au_llm(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = _bot_avec_apex()

    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, make_payload(content="wally le rank de Daltoosh"))

    outils = [t["function"]["name"] for t in bot.llm.complete_with_tools.call_args.args[2]]
    assert "apex_legends" in outils
