# bot/discord/commands/voice_cmd.py
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class VoiceCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(name="join", description="Wally rejoint ton salon vocal")
    async def join(self, interaction: discord.Interaction) -> None:
        voice = getattr(interaction.user, "voice", None)
        if voice is None or voice.channel is None:
            await interaction.response.send_message(
                "Tu dois être dans un salon vocal pour que je te rejoigne.", ephemeral=True
            )
            return
        try:
            await self.bot.voice_service.join(
                voice.channel, inviter=getattr(interaction.user, "display_name", None)
            )
            await interaction.response.send_message(f"J'arrive dans **{voice.channel.name}** 🎙️")
        except Exception as e:  # noqa: BLE001
            logger.warning("/join a échoué: {e}", e=e)
            await interaction.response.send_message("Impossible de rejoindre le vocal.", ephemeral=True)

    @app_commands.command(name="leave", description="Wally quitte le salon vocal")
    async def leave(self, interaction: discord.Interaction) -> None:
        if not self.bot.voice_service.is_connected:
            await interaction.response.send_message("Je ne suis dans aucun vocal.", ephemeral=True)
            return
        try:
            await self.bot.voice_service.leave()
            await interaction.response.send_message("Je vous laisse 👋")
        except Exception as e:  # noqa: BLE001
            logger.warning("/leave a échoué: {e}", e=e)
            await interaction.response.send_message("Impossible de quitter le vocal.", ephemeral=True)
