# bot/discord/events/voice.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_voice_state_update(member, before, after) -> None:
        if member.bot or not bot.social:
            return
        if before.channel != after.channel:
            if before.channel:
                bot.social.on_voice_leave(before.channel.id, member.id, member.display_name)
            if after.channel:
                bot.social.on_voice_join(after.channel.id, member.id, member.display_name)
