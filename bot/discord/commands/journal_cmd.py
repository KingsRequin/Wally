# bot/discord/commands/journal_cmd.py
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
    @app_commands.default_permissions(administrator=True)
    async def journal(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.journal.generate_and_send()
            await interaction.followup.send("Journal généré et envoyé.", ephemeral=True)
        except Exception as e:
            logger.error("Error generating journal on demand: {e}", e=e)
            await interaction.followup.send(
                "Erreur lors de la génération du journal.", ephemeral=True
            )
