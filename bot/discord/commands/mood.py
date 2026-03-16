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


def make_bar(value: float, length: int = 10) -> str:
    filled = int(value * length)
    return "█" * filled + "░" * (length - filled)


class MoodCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mood", description="Etat emotionnel actuel de Wally")
    async def mood(self, interaction: discord.Interaction):
        state = self.bot.emotion.get_state()
        embed = discord.Embed(title="Humeur de Wally", color=discord.Color.orange())
        for emotion, value in state.items():
            emoji = EMOTION_EMOJIS.get(emotion, "")
            bar = make_bar(value)
            embed.add_field(
                name=f"{emoji} {emotion.capitalize()}",
                value=f"{bar} `{int(value * 100)}%`",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)
