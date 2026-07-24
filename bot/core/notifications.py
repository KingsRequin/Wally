# bot/core/notifications.py
"""Service de notifications Discord (envoi dans un salon configurable)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.discord.bot import WallyDiscord


class NotificationService:
    """Envoie des notifications dans un salon Discord configurable."""

    def __init__(self, config: "Config", discord_bot: "WallyDiscord | None"):
        self._config = config
        self._discord_bot = discord_bot

    async def send(self, message: str) -> bool:
        """Envoie un message dans le salon de notification configuré."""
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
            logger.warning("Failed to send notification: {e}", e=exc)
            return False
