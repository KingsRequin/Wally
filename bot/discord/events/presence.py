# bot/discord/events/presence.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_presence_update(before, after) -> None:
        if after.bot or not bot.social or not after.guild:
            return
        before_games = {a.name for a in (before.activities or []) if isinstance(a, discord.Game)}
        after_games = {a.name for a in (after.activities or []) if isinstance(a, discord.Game)}
        for game in after_games - before_games:
            bot.social.on_game_start(after.display_name, game)
        for game in before_games - after_games:
            bot.social.on_game_stop(after.display_name, game)
