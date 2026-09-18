# bot/core/notifications.py
"""Prévenir le créateur d'une PANNE — en message privé, jamais sur la place publique.

Vécu le 2026-09-18 : la veille du verrou a annoncé « je ne peux plus rien
enregistrer » dans `#chambre-de-wally`, là où les gens PARLENT à Wally. Une
panne s'adresse au seul qui peut y remédier, pas au serveur.

Le repli n'est donc PAS « le salon configuré, quel qu'il soit » : c'est un
salon technique, et un salon où l'on converse est REFUSÉ même s'il est écrit
dans la config. Mieux vaut un silence de plus qu'un log lâché au milieu d'une
conversation — le MP reste le chemin normal, le repli ne sert qu'à ses ratés.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.discord.bot import WallyDiscord


def salons_ou_l_on_parle(config: "Config") -> set[int]:
    """Les salons où des gens s'adressent à Wally — interdits aux logs.

    CALCULÉS depuis la config, jamais listés à la main : un salon ajouté à la
    whitelist demain est couvert sans qu'on y pense. Une whitelist à `None`
    vaut « tous les salons de ce serveur » et n'est pas énumérable — on ne
    couvre que ce qui l'est.

    Écrivain UNIQUE de la règle : `NotificationService` s'en sert pour refuser
    le repli, `canari.py` pour le dire au démarrage plutôt qu'au moment d'une
    panne. Deux copies divergeraient.
    """
    salons: set[int] = set()
    bot_cfg = getattr(config, "bot", None)
    for attr in ("bedroom_channel_id", "partie_privee_channel_id"):
        valeur = getattr(bot_cfg, attr, None)
        if valeur:
            salons.add(int(valeur))
    discord_cfg = getattr(config, "discord", None)
    whitelist = getattr(discord_cfg, "per_guild_channel_whitelist", {}) or {}
    for ids in whitelist.values():
        for cid in ids or ():
            salons.add(int(cid))
    images = getattr(config, "image_generation", None)
    for cid in getattr(images, "autonomous_channel_ids", ()) or ():
        salons.add(int(cid))
    return salons


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
        if int(channel_id) in salons_ou_l_on_parle(self._config):
            logger.error(
                "Salon de repli {cid} REFUSÉ : on y parle avec Wally, un log n'y a "
                "rien à faire. Alerte perdue — corriger le salon technique.",
                cid=channel_id,
            )
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
