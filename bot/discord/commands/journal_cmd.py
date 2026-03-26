# bot/discord/commands/journal_cmd.py
from __future__ import annotations

from datetime import date, datetime

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class JournalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="journal",
        description="Génère et envoie le journal de Wally maintenant (admin)",
    )
    @app_commands.describe(
        target_date="Date du journal à générer (YYYY-MM-DD). Vide = aujourd'hui.",
    )
    @app_commands.default_permissions(administrator=True)
    async def journal(
        self, interaction: discord.Interaction, target_date: str | None = None
    ):
        await interaction.response.defer(ephemeral=True)

        parsed_date: date | None = None
        if target_date:
            try:
                parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                await interaction.followup.send(
                    "Format de date invalide. Utilise YYYY-MM-DD.", ephemeral=True
                )
                return

        try:
            await self.bot.journal.generate_and_send(target_date=parsed_date)
            label = parsed_date.isoformat() if parsed_date else "aujourd'hui"
            await interaction.followup.send(
                f"Journal généré et envoyé ({label}).", ephemeral=True
            )
        except Exception as e:
            logger.error("Error generating journal on demand: {e}", e=e)
            await interaction.followup.send(
                "Erreur lors de la génération du journal.", ephemeral=True
            )
