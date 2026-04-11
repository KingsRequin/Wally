# bot/twitch/commands/mood.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


async def handle_mood_command(bot: "WallyTwitch", channel_name: str) -> None:
    """Envoie l'état émotionnel courant dans le chat Twitch."""
    state = bot.emotion.get_state()
    emojis = {"anger": "😤", "joy": "😄", "sadness": "😢", "curiosity": "🤔", "boredom": "😑"}
    labels = {"anger": "Colère", "joy": "Joie", "sadness": "Tristesse", "curiosity": "Curiosité", "boredom": "Ennui"}
    parts = [
        f"{emojis[e]} {labels[e]} {int(state[e]*100)}%"
        for e in ("anger", "joy", "sadness", "curiosity", "boredom")
    ]
    mood_text = "Humeur de Wally — " + " | ".join(parts)

    if channel_name in bot._channel_ids:
        irc_channel = bot.get_channel(channel_name)
        if irc_channel:
            await irc_channel.send(mood_text)
    else:
        await bot.twitch_api.send_message(text=mood_text)
