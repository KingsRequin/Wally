# bot/discord/events/typing.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_typing(
        channel: discord.abc.Messageable,
        user: discord.User | discord.Member,
        when,
    ) -> None:
        """Indicateur de frappe (intent GUILD_MESSAGE_TYPING) : quelqu'un se met à
        écrire dans un salon. On le pousse dans le cerveau comme perception passive
        de VIVACITÉ pour que Wally sache la conversation vivante (cf. notify_typing).
        """
        try:
            if bot.cognitive_loop is None:
                return
            # Ni les bots, ni Wally lui-même.
            if getattr(user, "bot", False):
                return
            if bot.user is not None and user.id == bot.user.id:
                return
            guild = getattr(channel, "guild", None)
            if guild is not None and guild.id in bot.config.discord.ignored_guilds:
                return

            from bot.discord.handlers import _author_label

            bot.cognitive_loop.notify_typing(channel.id, _author_label(user))
        except Exception as e:  # noqa: BLE001 — perception, jamais bloquant
            logger.warning("on_typing a échoué: {e}", e=e)
