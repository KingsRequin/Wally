# bot/discord/commands/mood.py
import discord
from discord import app_commands
from discord.ext import commands

from bot.discord.fiches import ACCENT_ALERTE, ACCENTS_EMOTION, fiche
from bot.intelligence.identity import bot_name

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


def accent_dominant(state: dict[str, float]) -> int:
    """L'accent de la fiche suit l'émotion la plus forte — la MÊME couleur que
    sur le dashboard. Sous le seuil des dominantes, aucune ne parle pour les
    autres : la fiche reste sur son orange neutre."""
    if not state:
        return ACCENT_ALERTE
    emotion, valeur = max(state.items(), key=lambda kv: kv[1])
    if valeur < 0.4:
        return ACCENT_ALERTE
    return ACCENTS_EMOTION.get(emotion, ACCENT_ALERTE)


class MoodCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mood", description="État émotionnel actuel du bot")
    async def mood(self, interaction: discord.Interaction):
        state = self.bot.emotion.get_state()
        lignes = []
        for emotion, value in state.items():
            emoji = EMOTION_EMOJIS.get(emotion, "")
            label = EMOTION_LABELS.get(emotion, emotion.capitalize())
            lignes.append(
                f"{emoji}  **{label}**\n`{make_bar(value)}`  `{int(value * 100):3d}%`  "
                f"{intensity_label(value)}"
            )
        await interaction.response.send_message(
            view=fiche(f"Humeur de {bot_name()}", ["\n\n".join(lignes)],
                       accent=accent_dominant(state)),
        )
