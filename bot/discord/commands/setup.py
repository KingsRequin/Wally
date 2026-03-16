# bot/discord/commands/setup.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

EXCLUDED_MODEL_KEYWORDS = ["realtime", "preview", "audio", "vision"]
INCLUDED_MODEL_KEYWORDS = ["gpt", "chatgpt", "o1", "o3", "o4"]


def is_valid_model(model_id: str) -> bool:
    mid = model_id.lower()
    if any(ex in mid for ex in EXCLUDED_MODEL_KEYWORDS):
        return False
    return any(inc in mid for inc in INCLUDED_MODEL_KEYWORDS)


# ── Tab: Humeur ───────────────────────────────────────────────────────────────

_EMOTIONS = ["anger", "joy", "sadness", "curiosity", "boredom"]


class EditEmotionModal(discord.ui.Modal, title="Modifier une emotion"):
    value = discord.ui.TextInput(
        label="Nouvelle valeur (0.0 - 1.0)",
        placeholder="0.5",
        max_length=4,
    )

    def __init__(self, bot: "WallyDiscord", emotion: str):
        super().__init__()
        self.bot = bot
        self.emotion = emotion

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = float(self.value.value)
            self.bot.emotion.set_emotion(self.emotion, v)
            await interaction.response.send_message(
                f"{self.emotion} mis à {int(v * 100)}%", ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("Valeur invalide.", ephemeral=True)


class EmotionMinusButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord", emotion: str, row: int):
        super().__init__(
            label=f"- {emotion}", style=discord.ButtonStyle.secondary, row=row
        )
        self.bot = bot
        self.emotion = emotion

    async def callback(self, interaction: discord.Interaction):
        self.bot.emotion.apply_delta(self.emotion, -0.1)
        v = self.bot.emotion.get_state()[self.emotion]
        await interaction.response.send_message(
            f"{self.emotion}: {int(v * 100)}%", ephemeral=True
        )


class EmotionPlusButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord", emotion: str, row: int):
        super().__init__(
            label=f"+ {emotion}", style=discord.ButtonStyle.primary, row=row
        )
        self.bot = bot
        self.emotion = emotion

    async def callback(self, interaction: discord.Interaction):
        self.bot.emotion.apply_delta(self.emotion, 0.1)
        v = self.bot.emotion.get_state()[self.emotion]
        await interaction.response.send_message(
            f"{self.emotion}: {int(v * 100)}%", ephemeral=True
        )


class EmotionEditButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord", emotion: str, row: int):
        super().__init__(
            label=f"Edit {emotion}", style=discord.ButtonStyle.secondary, row=row
        )
        self.bot = bot
        self.emotion = emotion

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditEmotionModal(self.bot, self.emotion))


class ResetMoodButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(label="Reset humeur", style=discord.ButtonStyle.danger, row=4)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        self.bot.emotion.reset()
        await interaction.response.send_message(
            "Toutes les emotions remises à 0.", ephemeral=True
        )


class MoodView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        for i, emotion in enumerate(_EMOTIONS):
            self.add_item(EmotionMinusButton(bot, emotion, row=i))
            self.add_item(EmotionPlusButton(bot, emotion, row=i))
            self.add_item(EmotionEditButton(bot, emotion, row=i))
        self.add_item(ResetMoodButton(bot))


# ── Tab: Twitch Events ────────────────────────────────────────────────────────

class EditEventMessageModal(discord.ui.Modal, title="Modifier le message"):
    message = discord.ui.TextInput(
        label="Message (supports {username}, {amount}, etc.)",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    def __init__(self, bot: "WallyDiscord", event_name: str, current_message: str):
        super().__init__()
        self.bot = bot
        self.event_name = event_name
        self.message.default = current_message

    async def on_submit(self, interaction: discord.Interaction):
        event = self.bot.config.twitch_events.get(self.event_name)
        if event:
            event.message = self.message.value
            self.bot.config.save()
            await interaction.response.send_message(
                f"Message pour {self.event_name} mis à jour.", ephemeral=True
            )


class ToggleEventButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord", event_name: str, active: bool):
        label = f"{'✅' if active else '❌'} {event_name}"
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.bot = bot
        self.event_name = event_name

    async def callback(self, interaction: discord.Interaction):
        event = self.bot.config.twitch_events.get(self.event_name)
        if event:
            event.active = not event.active
            self.bot.config.save()
            status = "actif" if event.active else "inactif"
            await interaction.response.send_message(
                f"{self.event_name} est maintenant {status}.", ephemeral=True
            )


class EditEventButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord", event_name: str):
        super().__init__(
            label=f"Modifier {event_name}", style=discord.ButtonStyle.primary
        )
        self.bot = bot
        self.event_name = event_name

    async def callback(self, interaction: discord.Interaction):
        event = self.bot.config.twitch_events.get(self.event_name)
        current = event.message if event else ""
        await interaction.response.send_modal(
            EditEventMessageModal(self.bot, self.event_name, current)
        )


class TwitchEventsView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        for event_name, event_cfg in bot.config.twitch_events.items():
            self.add_item(ToggleEventButton(bot, event_name, event_cfg.active))
            self.add_item(EditEventButton(bot, event_name))


# ── Tab: Trigger Names ────────────────────────────────────────────────────────

class AddTriggerModal(discord.ui.Modal, title="Ajouter un nom declencheur"):
    name = discord.ui.TextInput(label="Nouveau nom", max_length=50)

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name.value.strip().lower()
        if new_name and new_name not in self.bot.config.bot.trigger_names:
            self.bot.config.bot.trigger_names.append(new_name)
            self.bot.config.save()
            await interaction.response.send_message(
                f'"{new_name}" ajouté aux noms déclencheurs.', ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Nom invalide ou déjà présent.", ephemeral=True
            )


class AddTriggerButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(label="Ajouter un nom", style=discord.ButtonStyle.success)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddTriggerModal(self.bot))


class RemoveTriggerButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord", name: str):
        only_one = len(bot.config.bot.trigger_names) <= 1
        super().__init__(
            label=f"Supprimer '{name}'",
            style=discord.ButtonStyle.danger,
            disabled=only_one,
        )
        self.bot = bot
        self.name = name

    async def callback(self, interaction: discord.Interaction):
        if len(self.bot.config.bot.trigger_names) <= 1:
            await interaction.response.send_message(
                "Impossible de supprimer le dernier nom.", ephemeral=True
            )
            return
        self.bot.config.bot.trigger_names.remove(self.name)
        self.bot.config.save()
        await interaction.response.send_message(
            f'"{self.name}" supprimé.', ephemeral=True
        )


class TriggerNamesView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.add_item(AddTriggerButton(bot))
        for name in bot.config.bot.trigger_names:
            self.add_item(RemoveTriggerButton(bot, name))


# ── Tab: Modele IA ────────────────────────────────────────────────────────────

class PrimaryModelSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord", options: list[discord.SelectOption]):
        super().__init__(placeholder="Modele principal...", options=options)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        self.bot.config.openai.primary_model = self.values[0]
        self.bot.config.save()
        await interaction.response.send_message(
            f"Modele principal : {self.values[0]}", ephemeral=True
        )


class SecondaryModelSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord", options: list[discord.SelectOption]):
        super().__init__(placeholder="Modele secondaire...", options=options)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        self.bot.config.openai.secondary_model = self.values[0]
        self.bot.config.save()
        await interaction.response.send_message(
            f"Modele secondaire : {self.values[0]}", ephemeral=True
        )


class ModelSelectView(discord.ui.View):
    def __init__(
        self,
        bot: "WallyDiscord",
        primary_options: list[discord.SelectOption],
        secondary_options: list[discord.SelectOption],
    ):
        super().__init__(timeout=120)
        self.add_item(PrimaryModelSelect(bot, primary_options))
        self.add_item(SecondaryModelSelect(bot, secondary_options))


async def _send_model_tab(
    bot: "WallyDiscord", interaction: discord.Interaction
) -> None:
    try:
        models_resp = await bot.openai._client.models.list()
        valid_models = sorted(
            [m.id for m in models_resp.data if is_valid_model(m.id)]
        )

        if not valid_models:
            await interaction.followup.send(
                "Aucun modele compatible trouvé.", ephemeral=True
            )
            return

        primary_options = [
            discord.SelectOption(
                label=mid,
                value=mid,
                default=(mid == bot.config.openai.primary_model),
            )
            for mid in valid_models[:25]
        ]
        secondary_options = [
            discord.SelectOption(
                label=mid,
                value=mid,
                default=(mid == bot.config.openai.secondary_model),
            )
            for mid in valid_models[:25]
        ]

        view = ModelSelectView(bot, primary_options, secondary_options)
        await interaction.followup.send(
            f"**Modele actuel :** {bot.config.openai.primary_model}\n"
            f"**Modele secondaire :** {bot.config.openai.secondary_model}",
            view=view,
            ephemeral=True,
        )
    except Exception as e:
        logger.error("Model tab error: {e}", e=e)
        await interaction.followup.send(
            "Erreur lors de la récupération des modeles.", ephemeral=True
        )


# ── Tab: Mémoire ─────────────────────────────────────────────────────────────

class ResetMemoryButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(
            label="Réinitialiser la mémoire", style=discord.ButtonStyle.danger
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        await self.bot.memory.reset_all()
        await interaction.response.send_message(
            "Mémoire réinitialisée (contexte + mémoire long terme).", ephemeral=True
        )


class MemoryView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=60)
        self.add_item(ResetMemoryButton(bot))


# ── Tab selector ─────────────────────────────────────────────────────────────

class SetupTabSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Modele IA", value="model", emoji="🤖"),
            discord.SelectOption(label="Humeur", value="mood", emoji="😊"),
            discord.SelectOption(label="Evenements Twitch", value="twitch", emoji="🎮"),
            discord.SelectOption(label="Noms declencheurs", value="triggers", emoji="📢"),
            discord.SelectOption(label="Memoire", value="memory", emoji="🧠"),
        ]
        super().__init__(placeholder="Choisir un onglet...", options=options)

    async def callback(self, interaction: discord.Interaction):
        tab = self.values[0]
        if tab == "mood":
            view = MoodView(self.bot)
            state = self.bot.emotion.get_state()
            lines = [f"**{e}** : {int(v * 100)}%" for e, v in state.items()]
            await interaction.response.send_message(
                "**Humeur actuelle :**\n" + "\n".join(lines),
                view=view,
                ephemeral=True,
            )
        elif tab == "twitch":
            view = TwitchEventsView(self.bot)
            lines = [
                f"{'✅' if cfg.active else '❌'} **{name}** : "
                f"{cfg.message[:50]}{'...' if len(cfg.message) > 50 else ''}"
                for name, cfg in self.bot.config.twitch_events.items()
            ]
            await interaction.response.send_message(
                "**Evenements Twitch :**\n" + "\n".join(lines),
                view=view,
                ephemeral=True,
            )
        elif tab == "triggers":
            view = TriggerNamesView(self.bot)
            names = ", ".join(self.bot.config.bot.trigger_names)
            await interaction.response.send_message(
                f"**Noms déclencheurs :** {names}",
                view=view,
                ephemeral=True,
            )
        elif tab == "memory":
            view = MemoryView(self.bot)
            await interaction.response.send_message(
                "**Mémoire de Wally**\n"
                "⚠️ Cette action efface le contexte de conversation et la mémoire long terme.",
                view=view,
                ephemeral=True,
            )
        elif tab == "model":
            await interaction.response.defer(ephemeral=True, thinking=True)
            await _send_model_tab(self.bot, interaction)


class SetupView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=180)
        self.add_item(SetupTabSelect(bot))


class SetupCog(commands.Cog):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot

    @app_commands.command(
        name="setup", description="Panneau de configuration de Wally (admin)"
    )
    @app_commands.default_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        view = SetupView(self.bot)
        await interaction.response.send_message(
            "**Configuration de Wally** — Sélectionnez un onglet :",
            view=view,
            ephemeral=True,
        )
