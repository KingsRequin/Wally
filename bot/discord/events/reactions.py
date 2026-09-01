# bot/discord/events/reactions.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == bot.user.id:
            return
        if payload.guild_id and payload.guild_id in bot.config.discord.ignored_guilds:
            return

        # Un VOTE n'est pas une réaction sociale : il ne dit pas « j'aime ton
        # message », il dit « je choisis l'option 2 ». Traité en premier et
        # SANS suite — sinon trente votants sur un sondage de Wally lui
        # feraient un pic de joie et trente lignes de perception pour rien.
        if await _sondage(bot, payload, ajout=True):
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

    @bot.event
    async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
        """Décocher son chiffre retire son vote.

        Seuls les sondages écoutent ce retrait : le tracking émotionnel et la
        perception ne comptent QUE ce qui est posé, pas ce qui est repris.
        """
        if bot.user is not None and payload.user_id == bot.user.id:
            return
        await _sondage(bot, payload, ajout=False)


async def _sondage(bot: "WallyDiscord", payload: discord.RawReactionActionEvent,
                   *, ajout: bool) -> bool:
    """Route la réaction vers le service de sondage.

    Rend True si c'était un vote — auquel cas l'appelant s'arrête là. Ne lève
    jamais : une réaction sur un message ordinaire ne doit pas casser le
    handler.
    """
    service = getattr(bot, "sondages", None)
    if service is None:
        return False
    try:
        return await service.sur_reaction(payload, ajout=ajout)
    except Exception as exc:  # noqa: BLE001 — un vote raté n'arrête pas le bot
        logger.warning("Sondage: réaction non traitée ({e!r})", e=exc)
        return False
