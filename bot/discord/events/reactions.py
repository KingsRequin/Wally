# bot/discord/events/reactions.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == bot.user.id:
            return
        if payload.guild_id and payload.guild_id in bot.config.discord.ignored_guilds:
            return

        # Tracking émotionnel (boost joy sur les messages de Wally) — inchangé.
        if bot.reaction_tracker:
            member = payload.member
            is_bot = member.bot if member else False
            bot.reaction_tracker.record_discord_reaction(
                payload.message_id, str(payload.emoji), is_bot,
            )

        # Perception LLM : injecte la réaction dans le contexte du canal.
        from bot.discord.handlers import _reactions_context

        await _reactions_context(bot, payload)
