# bot/discord/events/members.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_member_join(member: discord.Member) -> None:
        # Perception cognitive (#A2) : un nouveau venu doit atteindre le cerveau.
        from bot.discord.handlers import _member_join_context

        await _member_join_context(bot, member)

    @bot.event
    async def on_user_update(before: discord.User, after: discord.User) -> None:
        """Quelqu'un a changé de pseudo de compte : on garde l'ancien en alias.

        On écoute `on_user_update` et non `on_member_update` : le premier porte
        le pseudo de COMPTE (`User.name`, stable), le second le surnom de
        serveur, qui change à chaque lubie et remplirait la table d'alias.

        L'événement arrive pour tout utilisateur visible du cache — on ne
        retient que les personnes que Wally connaît déjà.
        """
        if before.name == after.name:
            return  # avatar, bannière… rien qui nous concerne

        uid = f"discord:{after.id}"
        try:
            connu = await bot.db.get_memory_username(uid)
        except Exception as exc:  # noqa: BLE001 — un event Discord ne fait pas tomber le bot
            logger.warning("renommage Discord illisible pour {uid}: {e!r}", uid=uid, e=exc)
            return
        if not connu:
            return  # inconnu de la mémoire : rien à rattacher

        await bot.memory.noter_renommage(bot.db, uid, before.name, after.name)
