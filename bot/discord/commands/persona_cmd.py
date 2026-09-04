# bot/discord/commands/persona_cmd.py
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.discord.fiches import ACCENT_ALERTE, ACCENT_OK, fiche


class PersonaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="reload-persona",
        description="Recharge les fichiers de persona (SOUL, IDENTITY, VOICE) depuis le disque",
    )
    @app_commands.default_permissions(administrator=True)
    async def reload_persona(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            self.bot.persona.reload()
            statuses = []
            for filename in self.bot.persona._FILES:
                ok = bool(self.bot.persona._blocks.get(filename))
                icon = "✅" if ok else "⚠️"
                statuses.append(f"{icon} `{filename}`")

            complet = all(self.bot.persona._blocks.get(f)
                          for f in self.bot.persona._FILES)
            await interaction.followup.send(
                view=fiche("Persona rechargée", ["\n".join(statuses)],
                           accent=ACCENT_OK if complet else ACCENT_ALERTE),
                ephemeral=True,
            )
        except Exception as e:
            logger.error("reload-persona error: {e!r}", e=e)
            await interaction.followup.send("Erreur lors du rechargement de la persona.", ephemeral=True)
