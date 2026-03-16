# bot/discord/commands/mood.py
import discord
from discord import app_commands
from discord.ext import commands

EMOTION_EMOJIS = {
    "anger": "😤",
    "joy": "😄",
    "sadness": "😢",
    "curiosity": "🤔",
    "boredom": "😑",
}

EMOTION_LABELS = {
    "anger": "Colère",
    "joy": "Joie",
    "sadness": "Tristesse",
    "curiosity": "Curiosité",
    "boredom": "Ennui",
}


def make_bar(value: float, length: int = 12) -> str:
    filled = int(value * length)
    return "▰" * filled + "▱" * (length - filled)


def intensity_label(value: float) -> str:
    if value >= 0.70:
        return "🔥 Intense"
    if value >= 0.50:
        return "⚡ Élevée"
    if value >= 0.25:
        return "😊 Modérée"
    return "💤 Faible"


class MoodCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mood", description="État émotionnel actuel de Wally")
    async def mood(self, interaction: discord.Interaction):
        state = self.bot.emotion.get_state()
        embed = discord.Embed(title="Humeur de Wally", color=discord.Color.orange())
        for emotion, value in state.items():
            emoji = EMOTION_EMOJIS.get(emotion, "")
            label = EMOTION_LABELS.get(emotion, emotion.capitalize())
            bar = make_bar(value)
            embed.add_field(
                name=f"{emoji}  {label}",
                value=f"`{bar}`  `{int(value * 100):3d}%`  {intensity_label(value)}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)
