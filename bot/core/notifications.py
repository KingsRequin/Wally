# bot/core/notifications.py
"""Service de notifications Discord pour alertes coûts et erreurs."""
from __future__ import annotations

import asyncio
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
        self._last_cost_alert: str | None = None  # évite les doublons

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

    async def notify_cost_alert(self, status: str, pct_used: float, current: float, threshold: float) -> None:
        """Envoie une alerte coût si le statut a changé."""
        if status == self._last_cost_alert:
            return  # pas de doublon
        self._last_cost_alert = status

        if status == "critical":
            msg = (
                f"🚨 **Alerte coûts critique** — {pct_used:.1f}% du seuil atteint\n"
                f"Dépensé : ${current:.2f} / ${threshold:.2f}"
            )
        elif status == "warning":
            msg = (
                f"⚠️ **Alerte coûts** — {pct_used:.1f}% du seuil atteint\n"
                f"Dépensé : ${current:.2f} / ${threshold:.2f}"
            )
        else:
            return  # pas de notification pour "ok"

        await self.send(msg)

    async def notify_error(self, error_msg: str) -> None:
        """Envoie une notification pour une erreur critique."""
        await self.send(f"❌ **Erreur** — {error_msg}")
