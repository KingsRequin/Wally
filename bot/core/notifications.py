# bot/core/notifications.py
"""Prévenir le créateur d'une PANNE — en message privé, jamais sur la place publique.

Vécu le 2026-09-18 : la veille du verrou a annoncé « je ne peux plus rien
enregistrer » dans le salon de discussion du serveur, devant tout le monde.
Ce n'est pas un salon de logs, et surtout ce n'est adressé à personne d'autre
qu'au seul qui peut y remédier. Une panne se dit en MP.

Le salon configuré reste le REPLI : MP fermés, créateur inconnu du bot, ou pas
d'`owner_discord_id` — on préfère encore un message mal placé à un silence.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.discord.bot import WallyDiscord


class NotificationService:
    """Envoie les alertes techniques au créateur (MP), à défaut dans un salon."""

    def __init__(self, config: "Config", discord_bot: "WallyDiscord | None"):
        self._config = config
        self._discord_bot = discord_bot

    async def send(self, message: str) -> bool:
        """Prévient le créateur. True dès qu'un des deux chemins a abouti."""
        if await self._en_prive(message):
            return True
        return await self._dans_le_salon(message)

    async def _en_prive(self, message: str) -> bool:
        owner_id = (self._config.bot.owner_discord_id or "").strip()
        if not owner_id or self._discord_bot is None:
            return False
        try:
            owner = await self._discord_bot.fetch_user(int(owner_id))
            dm = await owner.create_dm()
            await dm.send(message)
            return True
        except Exception as exc:
            logger.warning("Notification en MP refusée ({e!r}) — repli sur le salon", e=exc)
            return False

    async def _dans_le_salon(self, message: str) -> bool:
        channel_id = self._config.bot.notification_channel_id
        if not channel_id or self._discord_bot is None:
            return False

        try:
            channel = self._discord_bot.get_channel(channel_id)
            if channel is None:
                channel = await self._discord_bot.fetch_channel(channel_id)
            if channel is None:
                logger.warning("Notification channel {cid} not found", cid=channel_id)
                return False
            await channel.send(message)
            return True
        except Exception as exc:
            logger.warning("Failed to send notification: {e!r}", e=exc)
            return False
