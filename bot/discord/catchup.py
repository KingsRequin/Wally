# bot/discord/catchup.py
"""
Rattrapage des interactions manquées pendant une indisponibilité.

Au redémarrage (après un crash ou un arrêt), Wally scanne tous les salons Discord
autorisés depuis la date de son dernier log de conversation. Chaque message trouvé
qui le mentionne (@Wally) ou qui répond directement à l'un de ses messages (fonction
« répondre » de Discord) est réinjecté dans le pipeline normal ``handle_message`` —
comme s'il venait d'arriver en temps réel. Objectif : ne rater aucune interaction
pendant les fenêtres où le bot était hors ligne.

La borne temporelle est déduite du dernier ``ts`` présent dans les fichiers
``logs/conversations/discord/{canal}/{YYYY-MM-DD}.jsonl`` (cf. ConversationLogger).
Un garde-fou empêche de remonter au-delà de ``MAX_LOOKBACK_SECONDS`` afin d'éviter
une avalanche d'appels API si le bot est resté éteint très longtemps.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

# Garde-fous : on ne remonte jamais plus loin que 7 jours, et on plafonne le nombre
# de messages relus par canal (l'historique peut être énorme sur un gros serveur).
MAX_LOOKBACK_SECONDS = 7 * 24 * 3600
MAX_MESSAGES_PER_CHANNEL = 500


def _last_ts(path: Path) -> float | None:
    """Renvoie le ``ts`` de la dernière ligne non vide d'un fichier JSONL, ou None."""
    try:
        last: str | None = None
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = line
        if last is None:
            return None
        return float(json.loads(last)["ts"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def find_last_log_timestamp(root: str | Path) -> float | None:
    """Cherche le timestamp du dernier événement Discord journalisé.

    Les fichiers sont nommés ``{YYYY-MM-DD}.jsonl`` : le tri lexical des noms est donc
    chronologique. Le ``ts`` maximal global se trouve forcément dans un fichier de la
    date la plus récente ; on ne lit donc que ces fichiers-là (une journée par canal).
    Renvoie None si aucun log exploitable n'existe.
    """
    discord_root = Path(root) / "discord"
    if not discord_root.is_dir():
        return None
    files = list(discord_root.glob("*/*.jsonl"))
    if not files:
        return None
    latest_date = max(f.stem for f in files)
    best: float | None = None
    for f in files:
        if f.stem != latest_date:
            continue
        ts = _last_ts(f)
        if ts is not None and (best is None or ts > best):
            best = ts
    return best


async def _replied_to_wally(bot: "WallyDiscord", msg: discord.Message) -> bool:
    """True si ``msg`` répond (fonction « répondre » Discord) à un message de Wally."""
    ref = getattr(msg, "reference", None)
    if ref is None or ref.message_id is None:
        return False
    resolved = getattr(ref, "resolved", None)
    if isinstance(resolved, discord.Message):
        return resolved.author.id == bot.user.id
    cached = getattr(ref, "cached_message", None)
    if cached is not None:
        return cached.author.id == bot.user.id
    # Message référencé non résolu (historique) → on le récupère explicitement.
    try:
        ref_msg = await msg.channel.fetch_message(ref.message_id)
    except Exception:  # noqa: BLE001 — supprimé/inaccessible : on ignore le lien
        return False
    return ref_msg.author.id == bot.user.id


async def run_catchup(bot: "WallyDiscord") -> None:
    """Scanne les salons depuis le dernier log et rejoue les messages visant Wally.

    Ne lève jamais : toute erreur par canal est journalisée puis ignorée, afin de ne
    pas compromettre le démarrage. À appeler une seule fois par process (cf. on_ready).
    """
    from bot.discord.handlers import _is_channel_allowed, handle_message

    root = getattr(getattr(bot, "conv_log", None), "root", "logs/conversations")
    last_ts = await asyncio.to_thread(find_last_log_timestamp, root)
    if last_ts is None:
        logger.info("Rattrapage Discord : aucun log antérieur, rien à rattraper")
        return

    now = time.time()
    cutoff = max(last_ts, now - MAX_LOOKBACK_SECONDS)
    after_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
    logger.info(
        "Rattrapage Discord : scan des messages depuis {dt} (dernier log)",
        dt=after_dt.isoformat(),
    )

    pending: list[tuple[float, discord.Message]] = []
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if not _is_channel_allowed(bot.config, channel.id, guild.id):
                continue
            try:
                async for msg in channel.history(
                    after=after_dt, limit=MAX_MESSAGES_PER_CHANNEL, oldest_first=True
                ):
                    if msg.author.bot:
                        continue
                    mentioned = bot.user in msg.mentions
                    if mentioned or await _replied_to_wally(bot, msg):
                        pending.append((msg.created_at.timestamp(), msg))
            except Exception as exc:  # noqa: BLE001 — un canal illisible n'arrête pas le rattrapage
                logger.debug(
                    "Rattrapage : lecture du canal {ch} impossible : {e}",
                    ch=channel.id, e=exc,
                )

    if not pending:
        logger.info("Rattrapage Discord : aucune interaction manquée")
        return

    # Ordre chronologique global : les réponses de Wally restent cohérentes entre canaux.
    pending.sort(key=lambda item: item[0])
    logger.info(
        "Rattrapage Discord : {n} interaction(s) manquée(s) à traiter", n=len(pending)
    )
    for _, msg in pending:
        try:
            await handle_message(bot, msg)
        except Exception as exc:  # noqa: BLE001 — un message fautif n'arrête pas les suivants
            logger.warning(
                "Rattrapage : échec du traitement du message {mid} : {e}",
                mid=msg.id, e=exc,
            )
    logger.info("Rattrapage Discord terminé")
