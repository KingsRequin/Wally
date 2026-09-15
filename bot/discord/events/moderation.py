# bot/discord/events/moderation.py
"""Suppressions de messages → journal de modération.

`on_raw_message_delete` et non `on_message_delete` : le second ne voit que les
messages en cache, et une suppression de vieux message passerait inaperçue.
Le contenu n'est connu que si le message était en cache (`cached_message`).

`on_raw_bulk_message_delete` couvre les purges et les suppressions
d'historique d'un ban : sans lui, un pan entier de messages disparaît sans
laisser de trace dans le journal.

`message_supprime` rend la main tout de suite : la carte d'un message en
cache part en tâche de fond, le temps d'attendre que Discord écrive dans son
journal d'audit. Ce gestionnaire n'attend donc jamais ces deux secondes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bot.discord import journal_moderation

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent) -> None:
        await journal_moderation.message_supprime(bot, payload)

    @bot.event
    async def on_raw_bulk_message_delete(payload: discord.RawBulkMessageDeleteEvent) -> None:
        await journal_moderation.messages_supprimes_en_masse(bot, payload)
