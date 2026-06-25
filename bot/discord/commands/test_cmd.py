# bot/discord/commands/test_cmd.py
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class TestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="test",
        description="Teste une fonctionnalité du bot (admin)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        feature="Fonctionnalité à tester",
        channel="Salon où envoyer le résultat",
    )
    @app_commands.choices(feature=[
        app_commands.Choice(name="Journal", value="journal"),
    ])
    async def test_feature(
        self,
        interaction: discord.Interaction,
        feature: app_commands.Choice[str],
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)

        if feature.value == "journal":
            await self._test_journal(interaction, channel)
        else:
            await interaction.followup.send(
                f"Fonctionnalité inconnue : {feature.value}", ephemeral=True
            )

    async def _test_journal(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
    ) -> None:
        try:
            journal = self.bot.journal
            if journal is None:
                await interaction.followup.send(
                    "Journal non initialisé.", ephemeral=True
                )
                return

            # Temporarily override send callback to target chosen channel
            original_cb = journal._send_cb

            async def test_send_cb(text: str, file=None) -> None:
                if file and not text:
                    await channel.send(
                        file=discord.File(file, filename="emotions_jour.png")
                    )
                elif file:
                    await channel.send(
                        text, file=discord.File(file, filename="emotions_jour.png")
                    )
                else:
                    await channel.send(f"[TEST] {text}")

            journal._send_cb = test_send_cb
            try:
                await journal.generate_and_send(archive=False)
            finally:
                journal._send_cb = original_cb

            await interaction.followup.send(
                f"Journal de test envoyé dans {channel.mention}.", ephemeral=True
            )
        except Exception as e:
            logger.error("Error in test journal: {e}", e=e)
            await interaction.followup.send(
                "Erreur lors de la génération du journal de test.", ephemeral=True
            )
