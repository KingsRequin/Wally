"""Canal de destination des interventions spontanées Discord.

Une intervention spontanée (non sollicitée, sans mention) part dans le canal où
a lieu la discussion — PAS dans la chambre de Wally. Rediriger vers la chambre
donnait l'impression qu'il « parlait tout seul » ailleurs ; on veut qu'il
rejoigne la conversation en cours, comme un humain qui saute dans un échange.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.test_spontaneous import make_bot_for_spontaneous, _make_msg


@pytest.mark.asyncio
async def test_spontaneous_va_dans_le_canal_meme_avec_chambre():
    """Chambre configurée → l'intervention part quand même dans le canal (777)."""
    from bot.discord.handlers import _spontaneous_respond
    bot = make_bot_for_spontaneous()
    bot.config.bot.bedroom_channel_id = 123
    # get_channel renverrait la chambre, mais elle ne doit PAS être utilisée.
    bedroom = MagicMock()
    bedroom.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=bedroom)

    msg = _make_msg("bouchon rare")
    await _spontaneous_respond(bot, msg)

    msg.reply.assert_awaited_once()
    bedroom.send.assert_not_called()
    # La mémoire est écrite pour le canal de la discussion (777), pas la chambre.
    assert bot.memory.append_message.call_args.args[0] == "777"


@pytest.mark.asyncio
async def test_spontaneous_sans_chambre_repond_sur_place():
    """Sans chambre configurée : comportement inchangé, réponse sur place."""
    from bot.discord.handlers import _spontaneous_respond
    bot = make_bot_for_spontaneous()
    bot.config.bot.bedroom_channel_id = None

    msg = _make_msg("bouchon rare")
    await _spontaneous_respond(bot, msg)

    msg.reply.assert_awaited_once()
    assert bot.memory.append_message.call_args.args[0] == "777"
