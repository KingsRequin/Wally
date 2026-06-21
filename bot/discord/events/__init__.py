# bot/discord/events/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

from bot.discord.events import reactions

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register_events(bot: "WallyDiscord") -> None:
    """Enregistre tous les gateway event handlers Discord sur le bot."""
    reactions.register(bot)
