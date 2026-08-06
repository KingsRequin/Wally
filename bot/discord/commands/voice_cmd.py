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

    @app_commands.command(
        name="ecoute",
        description="Wally rejoint le vocal du stream en écoute seule (il n'y parle pas)",
    )
    @app_commands.describe(
        salon="Salon à écouter — par défaut celui du stream, sinon le tien",
    )
    async def ecoute(
        self,
        interaction: discord.Interaction,
        salon: discord.VoiceChannel | None = None,
    ) -> None:
        """Rattrapage manuel de l'auto-join.

        Le passage en live ne se produit qu'une fois : après un redémarrage en
        plein stream, plus rien ne déclenche l'arrivée de Wally.
        """
        service = getattr(self.bot, "voice_service", None)
        if service is None:
            await interaction.response.send_message(
                "Le vocal n'est pas actif sur cette instance.", ephemeral=True
            )
            return

        channel = salon
        if channel is None:
            configured = getattr(self.bot.config.bot, "stream_voice_channel_id", None)
            if configured:
                channel = self.bot.get_channel(configured)
            if channel is None:
                voice = getattr(interaction.user, "voice", None)
                channel = voice.channel if voice else None
        if channel is None:
            await interaction.response.send_message(
                "Aucun salon à écouter : aucun n'est configuré pour le stream, "
                "et tu n'es dans aucun vocal.", ephemeral=True
            )
            return

        await interaction.response.defer()
        try:
            await service.join(channel, listen_only=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("/ecoute a échoué: {e}", e=e)
            await interaction.followup.send(
                f"Impossible de rejoindre **{channel.name}**.", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"J'écoute **{channel.name}** 👂 — je ne parlerai pas ici, "
            "je réagis sur l'overlay."
        )

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
