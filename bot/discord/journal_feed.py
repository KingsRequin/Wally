"""Les deux tuyaux Discord du journal quotidien : ce qu'il lit, ce qu'il publie.

`JournalService` ne connaît pas Discord — il reçoit deux callables. Ces deux-là
étaient des closures dans le `main()` de mille lignes de `bot/main.py`, donc du
comportement qu'aucun test ne pouvait exécuter.

Ce qu'il y a à ne pas casser :

  · `lire_la_journee()` ne remonte QUE les salons autorisés par la config, et
    RECHERCHE depuis minuit à l'heure de Paris — pas UTC. L'hôte est en UTC ;
    prendre `datetime.now()` naïvement décalerait la journée de deux heures et
    couperait la soirée en deux, ce qui est précisément le moment où il se
    passe quelque chose.
  · Elle inclut les messages de Wally lui-même : le journal raconte la
    conversation, pas seulement ce qu'on lui a dit.
  · Un salon illisible (permissions, salon supprimé) ne doit pas faire tomber
    la lecture des autres — un seul salon fâché coûterait la journée entière.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from bot.core.temps import PARIS

# L'application raisonne en Europe/Paris alors que l'hôte est en UTC.
_FUSEAU = PARIS
#: Plafond par salon. Une journée très bavarde ne doit pas faire exploser la
#: fenêtre du LLM ni le temps de lecture.
_MAX_PAR_SALON = 2000


class JournalDiscord:
    """Les deux callbacks à injecter dans `JournalService`."""

    def __init__(self, *, discord_bot: Any, config: Any) -> None:
        self._bot = discord_bot
        self._config = config

    def brancher(self, journal: Any) -> None:
        journal.set_send_callback(self.publier)
        journal.set_history_callback(self.lire_la_journee)
        # Une ligne au boot, comme pour le veilleur de stream. Le journal ne
        # tourne qu'à 21 h : sans ça, un branchement raté ne se découvrirait
        # que le soir, sur un journal absent ou muet, et sans rien pour dire
        # si c'est le tuyau ou le contenu qui a manqué.
        logger.info("Journal : tuyaux Discord branchés (lecture + publication vers {c})",
                    c=self._config.bot.journal_channel_id or "aucun salon")

    async def publier(self, text: str, file: Any = None) -> None:
        """Poste le journal dans le salon dédié, avec son graphe s'il y en a un."""
        channel_id = self._config.bot.journal_channel_id
        if not channel_id:
            return
        salon = self._bot.get_channel(channel_id)
        if salon is None:
            # Salon supprimé ou cache froid. On le DIT : muet, le journal du
            # soir disparaissait sans que personne s'en aperçoive.
            logger.warning("Journal : salon {c} introuvable, publication perdue",
                           c=channel_id)
            return

        import discord as _discord

        if file is None:
            await salon.send(text)
        elif not text:
            await salon.send(file=_discord.File(file, filename="emotions_jour.png"))
        else:
            await salon.send(text, file=_discord.File(file, filename="emotions_jour.png"))

    async def lire_la_journee(self) -> list[dict]:
        """Tous les messages des salons autorisés depuis minuit, heure de Paris."""
        from bot.discord.handlers import _author_label, _is_channel_allowed

        minuit = datetime.now(_FUSEAU).replace(hour=0, minute=0, second=0, microsecond=0)
        messages: list[dict] = []
        if not self._bot.guilds:
            logger.warning("Journal : aucun serveur Discord connu, lecture sautée")
            return []

        for guild in self._bot.guilds:
            for salon in guild.text_channels:
                if not _is_channel_allowed(self._config, salon.id):
                    continue
                try:
                    async for msg in salon.history(after=minuit, limit=_MAX_PAR_SALON):
                        if not msg.content.strip():
                            continue
                        # Wally compris : le journal raconte la CONVERSATION,
                        # pas seulement ce qu'on lui a dit.
                        messages.append({
                            "author": _author_label(msg.author),
                            "content": msg.content,
                            "timestamp": msg.created_at.timestamp(),
                        })
                except Exception as exc:
                    # Un salon fâché ne coûte pas la journée entière.
                    logger.debug("Journal : salon {ch} illisible : {e!r}",
                                 ch=salon.id, e=exc)

        messages.sort(key=lambda m: m["timestamp"])
        return messages
