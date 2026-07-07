"""Validation au démarrage des channel ids configurés : prévient si l'un est mort."""
from pathlib import Path

import discord
from loguru import logger


async def _is_dead(bot, channel_id: int) -> bool:
    """Un canal est mort s'il n'est ni dans le cache ni récupérable via l'API."""
    if bot.get_channel(channel_id) is not None:
        return False
    try:
        await bot.fetch_channel(channel_id)
        return False
    except discord.NotFound:
        return True
    except Exception as e:  # noqa: BLE001 — accès refusé / réseau : on signale sans planter
        logger.warning("channel_health: {id} non vérifiable ({e})", id=channel_id, e=e)
        return True


async def find_dead_channels(bot, channels_md_path) -> list[tuple[str, str]]:
    """Retourne [(id, provenance)] pour chaque channel id configuré introuvable."""
    candidates: list[tuple[int, str]] = []
    bot_cfg = bot.config.bot
    for attr in ("notification_channel_id", "bedroom_channel_id", "journal_channel_id"):
        val = getattr(bot_cfg, attr, None)
        if val:
            candidates.append((int(val), f"config.bot.{attr}"))
    try:
        from bot.intelligence.channels import ChannelDirectory
        directory = ChannelDirectory.load(Path(channels_md_path))
        for cid, cname in directory.name_map().items():
            candidates.append((int(cid), f"CHANNELS.md ({cname})"))
    except Exception as e:  # noqa: BLE001 — CHANNELS.md absent/illisible : on continue
        logger.warning("channel_health: CHANNELS.md illisible ({e})", e=e)

    dead: list[tuple[str, str]] = []
    for cid, origin in candidates:
        if await _is_dead(bot, cid):
            dead.append((str(cid), origin))
    return dead


async def report_dead_channels(bot, channels_md_path=None) -> None:
    """Log WARNING + DM au créateur si au moins un channel id configuré est mort."""
    if channels_md_path is None:
        channels_md_path = (
            Path(__file__).parent.parent / "intelligence" / "persona" / "CHANNELS.md"
        )
    try:
        dead = await find_dead_channels(bot, channels_md_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_health: scan a échoué ({e})", e=e)
        return
    if not dead:
        logger.info("channel_health: tous les canaux configurés sont vivants")
        return
    lines = [f"- {cid} ({origin})" for cid, origin in dead]
    logger.warning("channel_health: {n} canal(aux) mort(s):\n{l}", n=len(dead), l="\n".join(lines))
    owner_id = getattr(bot.config.bot, "owner_discord_id", "")
    if not owner_id:
        return
    try:
        owner = await bot.fetch_user(int(owner_id))
        body = "⚠️ Canaux configurés introuvables (supprimés ou accès perdu) :\n" + "\n".join(lines)
        from bot.discord.message_split import send_chunked

        await send_chunked(owner, body)
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_health: DM créateur a échoué ({e})", e=e)
