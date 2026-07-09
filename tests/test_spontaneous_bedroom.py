"""Redirection des interventions spontanées Discord vers la chambre de Wally.

Une intervention spontanée (non sollicitée, sans mention) part dans le salon
dédié de Wally, pas dans le canal déclencheur. À défaut de chambre configurée,
on retombe sur la réponse en place (régression couverte par test_spontaneous.py).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.test_spontaneous import make_bot_for_spontaneous, _make_msg


def _make_bedroom_channel(chan_id=123):
    chan = MagicMock()
    chan.id = chan_id
    chan.name = "chambre-de-wally"
    chan.send = AsyncMock()
    chan.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    return chan


@pytest.mark.asyncio
async def test_spontaneous_va_dans_la_chambre():
    """Message spontané → chambre, jamais dans le canal déclencheur."""
    from bot.discord.handlers import _spontaneous_respond
    bot = make_bot_for_spontaneous()
    bot.config.bot.bedroom_channel_id = 123
    bedroom = _make_bedroom_channel(123)
    bot.get_channel = MagicMock(return_value=bedroom)

    msg = _make_msg("bouchon rare")
    await _spontaneous_respond(bot, msg)

    bedroom.send.assert_awaited_once()
    msg.reply.assert_not_called()
    # La mémoire est écrite pour la chambre, pas pour le canal déclencheur (777).
    assert bot.memory.append_message.call_args.args[0] == "123"


@pytest.mark.asyncio
async def test_spontaneous_sans_chambre_repond_sur_place():
    """Chambre non configurée → réponse en place (comportement historique)."""
    from bot.discord.handlers import _spontaneous_respond
    bot = make_bot_for_spontaneous()
    bot.config.bot.bedroom_channel_id = None

    msg = _make_msg("bouchon rare")
    await _spontaneous_respond(bot, msg)

    msg.reply.assert_awaited_once()
    assert bot.memory.append_message.call_args.args[0] == "777"
