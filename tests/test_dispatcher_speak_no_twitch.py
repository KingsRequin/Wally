"""La cognition ne parle jamais sur Twitch.

Un SPEAK spontané est calculé pour Discord. Auparavant, si le stream était live,
il était détourné vers le chat Twitch — d'où l'impression que Wally « parlait de
lui / du RSS » pendant le live. On veut qu'il ne s'exprime sur Twitch QUE sur
mention (chemin réactif Twitch), jamais de sa propre initiative.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.action_dispatcher import ActionDispatcher


@pytest.mark.asyncio
async def test_speak_ne_part_pas_sur_twitch_meme_si_live():
    channel = MagicMock()
    channel.send = AsyncMock()
    channel.name = "general"
    channel.guild = MagicMock()
    channel.guild.name = "TestServer"

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=channel)
    bot._wally_recent_speaks = {}

    twitch_bot = MagicMock()
    twitch_bot._stream_info = {"live": True, "user_login": "wally"}
    twitch_bot.twitch_api.send_message = AsyncMock()

    d = ActionDispatcher(bot=bot, twitch_bot=twitch_bot)  # speak_guard=None → passe
    await d._speak("777", "une pensée spontanée")

    twitch_bot.twitch_api.send_message.assert_not_called()
    channel.send.assert_awaited_once()
