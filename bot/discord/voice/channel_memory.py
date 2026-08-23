# bot/discord/voice/channel_memory.py
"""Le dernier salon vocal rejoint, retenu d'un redémarrage à l'autre.

Wally rejoignait toujours le salon écrit en config. Or on le déplace en cours de
soirée, et un simple rebuild d'image le ramenait à son point de départ.
"""
from __future__ import annotations


from loguru import logger

LAST_CHANNEL_KEY = "voice:last_channel"


async def remember_voice_channel(db, channel_id: int) -> None:
    """Retient le salon qu'il vient de rejoindre. N'échoue jamais bruyamment."""
    try:
        await db.set_state(LAST_CHANNEL_KEY, str(int(channel_id)))
    except Exception as exc:  # noqa: BLE001 — mémoriser est un confort, pas une condition
        logger.debug("voice: dernier salon non retenu: {e!r}", e=exc)


async def resolve_voice_channel_id(db, configured: int | None) -> int | None:
    """Le salon à rejoindre : le dernier connu, sinon celui de la config."""
    try:
        stored = await db.get_state(LAST_CHANNEL_KEY)
    except Exception as exc:  # noqa: BLE001 — une base muette ne bloque pas le démarrage
        logger.debug("voice: dernier salon illisible: {e!r}", e=exc)
        stored = None
    if stored:
        try:
            return int(stored)
        except (TypeError, ValueError):
            logger.warning("voice: dernier salon illisible ({v!r}), retour à la config", v=stored)
    return configured


async def forget_voice_channel(db) -> None:
    """Efface le souvenir. Appelé quand le salon retenu a disparu de Discord."""
    try:
        await db.delete_state(LAST_CHANNEL_KEY)
    except Exception as exc:  # noqa: BLE001 — un oubli raté se retentera au tour suivant
        logger.debug("voice: dernier salon non oublié: {e!r}", e=exc)


async def _lookup(bot, channel_id: int):
    """Le salon, ou None s'il n'existe PLUS. Lève si Discord est injoignable.

    `get_channel()` seul ne distingue pas « cache pas encore chaud » de « salon
    supprimé » : les deux rendent None. Seul l'appel API tranche, et il n'a lieu
    que sur cache froid.
    """
    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(channel_id)
    except Exception as exc:          # trié sur le code de statut, puis relevé
        if getattr(exc, "status", None) == 404:
            return None
        raise


async def resolve_voice_channel(bot, db, configured: int | None):
    """Le salon vocal à rejoindre, VÉRIFIÉ présent — ou None.

    Un salon vocal peut être ÉPHÉMÈRE : créé à la volée, supprimé dès qu'il se
    vide. L'identifiant retenu la veille ne désigne alors plus rien, et
    `resolve_voice_channel_id` le rendait quand même. Le veilleur de `main.py`
    voyait `get_channel()` à None, passait son tour en silence, et le repli sur
    le salon de config n'était JAMAIS atteint : trois heures de live sans Wally
    le 2026-08-19, sans une ligne de log pour l'expliquer.

    Un souvenir mort est donc effacé — mais seulement sur un 404 franc. Une
    panne réseau laisse le souvenir intact : elle ne dit rien du salon.
    """
    stored = await resolve_voice_channel_id(db, configured=None)
    if stored is not None:
        channel = await _lookup(bot, stored)
        if channel is not None:
            return channel
        logger.warning(
            "voice: le salon retenu {c} n'existe plus — oublié, retour au salon de config",
            c=stored,
        )
        await forget_voice_channel(db)
    if configured is None:
        return None
    channel = await _lookup(bot, configured)
    if channel is None:
        logger.warning("voice: le salon de config {c} est introuvable", c=configured)
    return channel
