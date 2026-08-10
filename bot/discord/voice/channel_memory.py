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
        logger.debug("voice: dernier salon non retenu: {e}", e=exc)


async def resolve_voice_channel_id(db, configured: int | None) -> int | None:
    """Le salon à rejoindre : le dernier connu, sinon celui de la config."""
    try:
        stored = await db.get_state(LAST_CHANNEL_KEY)
    except Exception as exc:  # noqa: BLE001 — une base muette ne bloque pas le démarrage
        logger.debug("voice: dernier salon illisible: {e}", e=exc)
        stored = None
    if stored:
        try:
            return int(stored)
        except (TypeError, ValueError):
            logger.warning("voice: dernier salon illisible ({v!r}), retour à la config", v=stored)
    return configured
