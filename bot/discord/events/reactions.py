# bot/discord/events/reactions.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if not bot.reaction_tracker:
            return
        if payload.user_id == bot.user.id:
            return
        member = payload.member
        is_bot = member.bot if member else False
        bot.reaction_tracker.record_discord_reaction(
            payload.message_id, str(payload.emoji), is_bot,
        )

    @bot.event
    async def on_reaction_add(reaction, user) -> None:
        if user.bot or not bot.social:
            return
        author = reaction.message.author
        if author is None:
            return
        if author != user:
            bot.social.on_reaction(user.display_name, author.display_name)
