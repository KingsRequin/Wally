# bot/discord/commands/persona_cmd.py
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


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

            embed = discord.Embed(
                title="Persona rechargée",
                description="\n".join(statuses),
                color=discord.Color.green() if all(
                    self.bot.persona._blocks.get(f) for f in self.bot.persona._FILES
                ) else discord.Color.orange(),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error("reload-persona error: {e}", e=e)
            await interaction.followup.send("Erreur lors du rechargement de la persona.", ephemeral=True)
