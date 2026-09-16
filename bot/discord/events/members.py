# bot/discord/events/members.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from loguru import logger

from bot.discord import bienvenue, journal_membres

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_member_join(member: discord.Member) -> None:
        # Perception cognitive (#A2) : un nouveau venu doit atteindre le cerveau.
        from bot.discord.handlers import _fire, _member_join_context

        # La fiche d'abord : elle est consignée dans self_trace, et la
        # cognition doit la voir quand elle décide si elle accueille à son tour.
        # Défense en profondeur : `accueillir` ne lève jamais en théorie (son
        # propre try/except), mais la perception cognitive ne doit JAMAIS
        # dépendre de cette garantie pour continuer.
        try:
            await bienvenue.accueillir(bot, member)
        except Exception as e:  # noqa: BLE001 — la perception cognitive doit continuer
            logger.warning("bienvenue : accueillir a levé : {e!r}", e=e)
        # Journal des membres (#8) : tâche de fond, un envoi lent sur
        # plusieurs salons de logs ne doit retarder ni l'accueil ni la
        # perception cognitive ci-dessous.
        _fire(journal_membres.membre_rejoint(bot, member))
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
