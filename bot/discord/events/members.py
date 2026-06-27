# bot/discord/events/members.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_member_join(member: discord.Member) -> None:
        # Perception cognitive (#A2) : un nouveau venu doit atteindre le cerveau.
        from bot.discord.handlers import _member_join_context

        await _member_join_context(bot, member)
