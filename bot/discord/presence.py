# bot/discord/presence.py
"""Perception de la présence Discord — lecture seule.

Wally voit ce qu'un membre normal voit dans la barre latérale du serveur :
le statut (en ligne / inactif / ne pas déranger / hors ligne) et l'activité en
cours (jeu, écoute, stream, statut perso). Rien de plus : aucune donnée vocale,
aucune donnée personnelle, et uniquement sur le **serveur principal**
(``DISCORD_GUILD_ID``).

discord.py maintient déjà ``Member.status`` et ``Member.activities`` à jour dans
son cache dès que les intents ``members`` + ``presences`` sont actifs. On se
contente donc de lire ce cache à la demande — pas de handler d'événement, pas de
stockage.
"""
from __future__ import annotations

import os

import discord
from loguru import logger

_STATUS_FR = {
    "online": "en ligne",
    "idle": "inactif",
    "dnd": "ne pas déranger",
    "offline": "hors ligne",
}

# Activités qui signalent quelqu'un « occupé, à ne pas déranger » (en pleine
# game / en train de streamer / en compétition). L'écoute de musique ou un
# statut perso n'en font pas partie : ça ne dérange personne.
_BUSY_ACTIVITY_TYPES = {
    discord.ActivityType.playing,
    discord.ActivityType.streaming,
    discord.ActivityType.competing,
}


class PresenceService:
    """Lecture seule du statut + activité d'un membre du serveur principal."""

    def __init__(self, client: discord.Client, guild_id: int | None = None):
        self._client = client
        # DISCORD_GUILD_ID peut lister plusieurs serveurs ; la présence suit le 1er (principal).
        from bot.discord.guild_sync import parse_guild_ids
        ids = parse_guild_ids(os.getenv("DISCORD_GUILD_ID"))
        self._guild_id = guild_id or (ids[0] if ids else None)
        if self._guild_id is None:
            logger.warning(
                "PresenceService : DISCORD_GUILD_ID absent — perception de présence désactivée"
            )

    @property
    def enabled(self) -> bool:
        return self._guild_id is not None

    def _member(self, user_id: str | int) -> discord.Member | None:
        if self._guild_id is None:
            return None
        guild = self._client.get_guild(self._guild_id)
        if guild is None:
            return None
        try:
            return guild.get_member(int(user_id))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _describe_activity(act) -> str | None:
        """Une activité → phrase courte FR, ou None si rien d'utile."""
        if isinstance(act, discord.CustomActivity):
            text = (act.name or "").strip()
            return f"statut perso : « {text} »" if text else None
        if isinstance(act, discord.Spotify):
            return f"écoute {act.title} — {act.artist}"
        name = getattr(act, "name", None)
        if not name:
            return None
        verbs = {
            discord.ActivityType.playing: "joue à",
            discord.ActivityType.streaming: "stream",
            discord.ActivityType.listening: "écoute",
            discord.ActivityType.watching: "regarde",
            discord.ActivityType.competing: "participe à",
        }
        verb = verbs.get(getattr(act, "type", None))
        return f"{verb} {name}" if verb else None

    def get(self, user_id: str | int) -> dict | None:
        """Snapshot ``{"status": str, "activities": list[str]}`` ou None.

        None = membre introuvable dans le cache du serveur principal.
        """
        member = self._member(user_id)
        if member is None:
            return None
        activities = [
            desc
            for act in member.activities
            if (desc := self._describe_activity(act))
        ]
        return {"status": str(member.status), "activities": activities}

    @staticmethod
    def _line(status: str, activities: list[str], display_name: str) -> str:
        """« {pseudo} est {statut} — {activités}. » — formatage FR partagé."""
        status_fr = _STATUS_FR.get(status, status)
        line = f"{display_name} est {status_fr}"
        if activities:
            line += " — " + ", ".join(activities)
        return line + "."

    def describe(self, user_id: str | int, display_name: str) -> str | None:
        """Phrase prête pour le prompt, ou None si rien d'intéressant.

        On n'injecte rien si le membre est hors ligne **et** sans activité :
        ce serait du bruit pour le LLM.
        """
        snap = self.get(user_id)
        if snap is None:
            return None
        status = snap["status"]
        acts = snap["activities"]
        if status == "offline" and not acts:
            return None
        return self._line(status, acts, display_name)

    def roster(self, limit: int = 8) -> list[str]:
        """Membres actuellement visibles (non hors-ligne) du serveur principal —
        ce que Wally verrait dans la barre latérale.

        Priorise ceux qu'il vaut mieux ne pas déranger : « ne pas déranger »
        d'abord, puis ceux en pleine activité (game / stream), puis inactifs,
        puis simplement en ligne. Plafonné à ``limit``. Ignore les bots.
        Lecture seule, best-effort : toute erreur renvoie une liste vide.
        """
        if self._guild_id is None:
            return []
        guild = self._client.get_guild(self._guild_id)
        if guild is None:
            return []
        try:
            rows: list[tuple[int, str]] = []
            for member in guild.members:
                if getattr(member, "bot", False):
                    continue
                status = str(member.status)
                if status == "offline":
                    continue
                acts: list[str] = []
                busy = False
                for act in member.activities:
                    if getattr(act, "type", None) in _BUSY_ACTIVITY_TYPES:
                        busy = True
                    if (desc := self._describe_activity(act)):
                        acts.append(desc)
                if status == "dnd":
                    rank = 0
                elif busy:
                    rank = 1
                elif status == "idle":
                    rank = 2
                else:
                    rank = 3
                rows.append((rank, self._line(status, acts, member.display_name)))
            rows.sort(key=lambda r: r[0])
            return [line for _, line in rows[:limit]]
        except Exception as e:  # noqa: BLE001 — perception jamais bloquante
            logger.warning("PresenceService.roster: {}", e)
            return []
