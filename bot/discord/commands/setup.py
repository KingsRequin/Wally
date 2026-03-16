# bot/discord/commands/setup.py
from __future__ import annotations

import asyncio
import os
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

EXCLUDED_MODEL_KEYWORDS = ["realtime", "preview", "audio", "vision"]
INCLUDED_MODEL_KEYWORDS = ["gpt", "chatgpt", "o1", "o3", "o4"]

# ── Clés .env éditables ───────────────────────────────────────────────────────

EDITABLE_ENV_KEYS: list[str] = [
    "OPENAI_API_KEY",
    "DISCORD_TOKEN",
    "DISCORD_GUILD_ID",
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "TWITCH_BROADCASTER_ID",
    "TWITCH_BOT_ID",
    "TWITCH_BOT_NICK",
    "BOT_ACCESS_TOKEN",
    "BOT_REFRESH_TOKEN",
    "STREAMER_ACCESS_TOKEN",
    "STREAMER_REFRESH_TOKEN",
]


# ── Utilitaires .env ──────────────────────────────────────────────────────────

def read_env_values(path: str = ".env") -> dict[str, str]:
    """Lit le .env et retourne toutes les paires KEY=value (hors commentaires)."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {}
    result: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def update_env_file(path: str, updates: dict[str, str]) -> None:
    """Met à jour les clés dans .env, ajoute les clés manquantes en fin de fichier."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.partition("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    with open(path, "w") as f:
        f.writelines(new_lines)


def is_env_complete(path: str = ".env") -> list[str]:
    """Retourne les clés éditables manquantes ou vides dans le .env."""
    values = read_env_values(path)
    return [k for k in EDITABLE_ENV_KEYS if not values.get(k)]


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


# ── Restart ───────────────────────────────────────────────────────────────────

class ConfirmRestartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)  # expire en 30s

    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Redémarrage en cours...", ephemeral=True)
        asyncio.get_running_loop().call_later(1.0, os._exit, 0)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Redémarrage annulé.", ephemeral=True)


# ── Navigation niveau Basique ─────────────────────────────────────────────────

class BasicTabSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Modele IA", value="model", emoji="🤖"),
            discord.SelectOption(label="Humeur", value="mood", emoji="😊"),
            discord.SelectOption(label="Evenements Twitch", value="twitch", emoji="🎮"),
            discord.SelectOption(label="Noms declencheurs", value="triggers", emoji="📢"),
            discord.SelectOption(label="Memoire", value="memory", emoji="🧠"),
            discord.SelectOption(label="Variables d'env", value="env", emoji="🔑"),
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
        elif tab == "env":
            await _send_env_tab(self.bot, interaction)


class BasicView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.add_item(BasicTabSelect(bot))


# ── Tab Avancé : Bot Général ──────────────────────────────────────────────────

class BotGeneralModal(discord.ui.Modal, title="Paramètres généraux du bot"):
    language_default = discord.ui.TextInput(
        label="Langue par défaut (ex: fr, en)", max_length=5
    )
    context_window_size = discord.ui.TextInput(
        label="Taille contexte (nb messages, ≥1)", max_length=5
    )
    context_token_threshold = discord.ui.TextInput(
        label="Seuil tokens contexte (≥1)", max_length=6
    )
    journal_time = discord.ui.TextInput(
        label="Heure journal (HH:MM)", max_length=5
    )
    prelude_window_size = discord.ui.TextInput(
        label="Taille prélude (≥1)", max_length=5
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        cfg = bot.config.bot
        self.language_default.default = cfg.language_default
        self.context_window_size.default = str(cfg.context_window_size)
        self.context_token_threshold.default = str(cfg.context_token_threshold)
        self.journal_time.default = cfg.journal_time
        self.prelude_window_size.default = str(cfg.prelude_window_size)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cws = int(self.context_window_size.value)
            ctt = int(self.context_token_threshold.value)
            pws = int(self.prelude_window_size.value)
            if cws < 1 or ctt < 1 or pws < 1:
                raise ValueError("Valeur trop petite")
            jt = self.journal_time.value.strip()
            if not re.match(r"^\d{2}:\d{2}$", jt):
                raise ValueError("Format journal_time invalide")
            h, m = int(jt.split(":")[0]), int(jt.split(":")[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError("Heure hors plage")
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Entiers ≥ 1 pour les tailles, format HH:MM (ex: 21:00) pour l'heure journal.",
                ephemeral=True,
            )
            return
        cfg = self.bot.config.bot
        cfg.language_default = self.language_default.value
        cfg.context_window_size = cws
        cfg.context_token_threshold = ctt
        cfg.journal_time = jt
        cfg.prelude_window_size = pws
        self.bot.config.save()
        await interaction.response.send_message("✅ Paramètres généraux mis à jour.", ephemeral=True)


class JournalChannelModal(discord.ui.Modal, title="Channel du journal"):
    channel_id = discord.ui.TextInput(
        label="ID du channel Discord (vide pour désactiver)",
        required=False,
        max_length=20,
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        current = bot.config.bot.journal_channel_id
        self.channel_id.default = str(current) if current else ""

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.channel_id.value.strip()
        if raw == "":
            self.bot.config.bot.journal_channel_id = None
            self.bot.config.save()
            await interaction.response.send_message("✅ Channel journal désactivé.", ephemeral=True)
            return
        try:
            cid = int(raw)
            if cid <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ ID invalide. Entrez un entier > 0 ou laissez vide.", ephemeral=True
            )
            return
        self.bot.config.bot.journal_channel_id = cid
        self.bot.config.save()
        await interaction.response.send_message(f"✅ Channel journal : {cid}", ephemeral=True)


class BotGeneralView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier paramètres généraux", style=discord.ButtonStyle.primary, row=0)
    async def edit_general(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BotGeneralModal(self.bot))

    @discord.ui.button(label="Définir channel journal", style=discord.ButtonStyle.secondary, row=1)
    async def edit_journal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JournalChannelModal(self.bot))


# ── Tab Avancé : Discord ──────────────────────────────────────────────────────

class DiscordParamsModal(discord.ui.Modal, title="Paramètres Discord"):
    anger_trigger_threshold = discord.ui.TextInput(
        label="Seuil déclencheur colère (≥1)", max_length=3
    )
    timeout_minutes = discord.ui.TextInput(
        label="Durée timeout en minutes (≥1)", max_length=4
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.anger_trigger_threshold.default = str(bot.config.discord.anger_trigger_threshold)
        self.timeout_minutes.default = str(bot.config.discord.timeout_minutes)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            att = int(self.anger_trigger_threshold.value)
            tm = int(self.timeout_minutes.value)
            if att < 1 or tm < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Les deux champs doivent être des entiers ≥ 1.",
                ephemeral=True,
            )
            return
        self.bot.config.discord.anger_trigger_threshold = att
        self.bot.config.discord.timeout_minutes = tm
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Seuil colère : {att}, timeout : {tm} min.", ephemeral=True
        )


class EditChannelListModal(discord.ui.Modal, title="Modifier la liste de channels"):
    channel_ids = discord.ui.TextInput(
        label="IDs des channels (séparés par des virgules)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, bot: "WallyDiscord", list_type: str):
        super().__init__()
        self.bot = bot
        self.list_type = list_type
        current: list[int] = (
            bot.config.discord.channel_blacklist
            if list_type == "blacklist"
            else bot.config.discord.channel_whitelist
        )
        self.channel_ids.default = ", ".join(str(c) for c in current)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.channel_ids.value.strip()
        if not raw:
            ids: list[int] = []
        else:
            try:
                ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
                if any(i <= 0 for i in ids):
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    "❌ IDs invalides. Entrez des entiers > 0 séparés par des virgules.",
                    ephemeral=True,
                )
                return
        if self.list_type == "blacklist":
            self.bot.config.discord.channel_blacklist = ids
        else:
            self.bot.config.discord.channel_whitelist = ids
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ {self.list_type.capitalize()} mise à jour ({len(ids)} channel(s)).",
            ephemeral=True,
        )


class DiscordView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Colère & timeout", style=discord.ButtonStyle.primary, row=0)
    async def edit_params(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DiscordParamsModal(self.bot))

    @discord.ui.button(label="Mode filtre : ...", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_filter(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = self.bot.config.discord.channel_filter_mode
        new_mode = "whitelist" if current == "blacklist" else "blacklist"
        self.bot.config.discord.channel_filter_mode = new_mode
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Mode filtre : **{new_mode}**", ephemeral=True
        )

    @discord.ui.button(label="Modifier la blacklist", style=discord.ButtonStyle.secondary, row=2)
    async def edit_blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditChannelListModal(self.bot, "blacklist"))

    @discord.ui.button(label="Modifier la whitelist", style=discord.ButtonStyle.secondary, row=3)
    async def edit_whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditChannelListModal(self.bot, "whitelist"))


# ── Tab Avancé : Twitch Config ────────────────────────────────────────────────

class TwitchConfigModal(discord.ui.Modal, title="Configuration Twitch"):
    channels = discord.ui.TextInput(
        label="Channels Twitch (séparés par des virgules)",
        max_length=200,
    )
    cooldown_seconds = discord.ui.TextInput(
        label="Cooldown par utilisateur (secondes, ≥0)",
        max_length=5,
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.channels.default = ", ".join(bot.config.twitch.channels)
        self.cooldown_seconds.default = str(bot.config.twitch.cooldown_seconds)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cs = int(self.cooldown_seconds.value)
            if cs < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Cooldown invalide. Entrez un entier ≥ 0.", ephemeral=True
            )
            return
        self.bot.config.twitch.channels = [
            c.strip() for c in self.channels.value.split(",") if c.strip()
        ]
        self.bot.config.twitch.cooldown_seconds = cs
        self.bot.config.save()
        await interaction.response.send_message("✅ Config Twitch mise à jour.", ephemeral=True)


class TwitchConfigView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier config Twitch", style=discord.ButtonStyle.primary, row=0)
    async def edit_twitch(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TwitchConfigModal(self.bot))


# ── Tab Avancé : OpenAI params ────────────────────────────────────────────────

class OpenAIParamsModal(discord.ui.Modal, title="Paramètres OpenAI"):
    temperature = discord.ui.TextInput(
        label="Temperature (0.0 – 2.0)", max_length=5
    )
    max_tokens = discord.ui.TextInput(
        label="Max tokens (≥1)", max_length=6
    )

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        self.temperature.default = str(bot.config.openai.temperature)
        self.max_tokens.default = str(bot.config.openai.max_tokens)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            temp = float(self.temperature.value)
            mt = int(self.max_tokens.value)
            if not (0.0 <= temp <= 2.0) or mt < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Temperature : 0.0–2.0, max_tokens : entier ≥ 1.",
                ephemeral=True,
            )
            return
        self.bot.config.openai.temperature = temp
        self.bot.config.openai.max_tokens = mt
        self.bot.config.save()
        await interaction.response.send_message(
            f"✅ Temperature : {temp}, max_tokens : {mt}.", ephemeral=True
        )


class OpenAIParamsView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier paramètres OpenAI", style=discord.ButtonStyle.primary, row=0)
    async def edit_openai(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OpenAIParamsModal(self.bot))


# ── Tab Avancé : Decay émotions ───────────────────────────────────────────────

class DecayModal(discord.ui.Modal, title="Decay des émotions (λ)"):
    anger = discord.ui.TextInput(label="anger decay_lambda (0 < x < 1)", max_length=6)
    joy = discord.ui.TextInput(label="joy decay_lambda (0 < x < 1)", max_length=6)
    sadness = discord.ui.TextInput(label="sadness decay_lambda (0 < x < 1)", max_length=6)
    curiosity = discord.ui.TextInput(label="curiosity decay_lambda (0 < x < 1)", max_length=6)
    boredom = discord.ui.TextInput(label="boredom decay_lambda (0 < x < 1)", max_length=6)

    def __init__(self, bot: "WallyDiscord"):
        super().__init__()
        self.bot = bot
        emotions = bot.config.emotions
        self.anger.default = str(emotions["anger"].decay_lambda)
        self.joy.default = str(emotions["joy"].decay_lambda)
        self.sadness.default = str(emotions["sadness"].decay_lambda)
        self.curiosity.default = str(emotions["curiosity"].decay_lambda)
        self.boredom.default = str(emotions["boredom"].decay_lambda)

    async def on_submit(self, interaction: discord.Interaction):
        raw = {
            "anger": self.anger.value,
            "joy": self.joy.value,
            "sadness": self.sadness.value,
            "curiosity": self.curiosity.value,
            "boredom": self.boredom.value,
        }
        try:
            parsed = {k: float(v) for k, v in raw.items()}
            if any(not (0.0 < v < 1.0) for v in parsed.values()):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Valeurs invalides. Chaque λ doit être un float entre 0.0 et 1.0 (exclus).",
                ephemeral=True,
            )
            return
        for emotion, value in parsed.items():
            self.bot.config.emotions[emotion].decay_lambda = value
        self.bot.config.save()
        await interaction.response.send_message("✅ Decay des émotions mis à jour.", ephemeral=True)


class DecayView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.bot = bot

    @discord.ui.button(label="Modifier decay", style=discord.ButtonStyle.primary, row=0)
    async def edit_decay(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DecayModal(self.bot))


# ── Tab Avancé : implémentations finales ─────────────────────────────────────

async def _send_twitch_config_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    cfg = bot.config.twitch
    lines = [
        "**Twitch Config**",
        f"Channels : {', '.join(cfg.channels)}",
        f"Cooldown : {cfg.cooldown_seconds}s",
    ]
    view = TwitchConfigView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


async def _send_openai_params_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    cfg = bot.config.openai
    lines = [
        "**Paramètres OpenAI**",
        f"Temperature : {cfg.temperature}",
        f"Max tokens : {cfg.max_tokens}",
    ]
    view = OpenAIParamsView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


async def _send_decay_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    emotions = bot.config.emotions
    lines = ["**Decay des émotions (λ)**"] + [
        f"**{e}** : {cfg.decay_lambda}" for e, cfg in emotions.items()
    ]
    view = DecayView(bot)
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


# ── Navigation niveau Avancé ──────────────────────────────────────────────────

class AdvancedTabSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Bot Général", value="bot", emoji="⚙️"),
            discord.SelectOption(label="Discord", value="discord", emoji="💬"),
            discord.SelectOption(label="Twitch Config", value="twitch_cfg", emoji="🟣"),
            discord.SelectOption(label="OpenAI (params)", value="openai", emoji="🤖"),
            discord.SelectOption(label="Decay émotions", value="decay", emoji="💭"),
        ]
        super().__init__(placeholder="Choisir un onglet avancé...", options=options)

    async def callback(self, interaction: discord.Interaction):
        tab = self.values[0]
        if tab == "bot":
            cfg = self.bot.config.bot
            lines = [
                f"**Bot Général**",
                f"Langue : {cfg.language_default}",
                f"Contexte : {cfg.context_window_size} messages / {cfg.context_token_threshold} tokens",
                f"Journal : {cfg.journal_time} — channel : {cfg.journal_channel_id or 'non défini'}",
                f"Prélude : {cfg.prelude_window_size}",
            ]
            view = BotGeneralView(self.bot)
            await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)
        elif tab == "discord":
            cfg = self.bot.config.discord
            lines = [
                f"**Paramètres Discord**",
                f"Seuil colère : {cfg.anger_trigger_threshold} — Timeout : {cfg.timeout_minutes} min",
                f"Mode filtre : **{cfg.channel_filter_mode}**",
                f"Blacklist : {len(cfg.channel_blacklist)} channel(s)",
                f"Whitelist : {len(cfg.channel_whitelist)} channel(s)",
            ]
            view = DiscordView(self.bot)
            await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)
        elif tab == "twitch_cfg":
            await _send_twitch_config_tab(self.bot, interaction)
        elif tab == "openai":
            await _send_openai_params_tab(self.bot, interaction)
        elif tab == "decay":
            await _send_decay_tab(self.bot, interaction)


class AdvancedView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=120)
        self.add_item(AdvancedTabSelect(bot))


# ── Tab .env ──────────────────────────────────────────────────────────────────

class EnvOpenAIModal(discord.ui.Modal, title="Variables OpenAI"):
    openai_api_key = discord.ui.TextInput(
        label="OPENAI_API_KEY",
        placeholder="sk-proj-...",
        max_length=200,
    )

    def __init__(self, values: dict[str, str]):
        super().__init__()
        self.openai_api_key.default = values.get("OPENAI_API_KEY", "")

    async def on_submit(self, interaction: discord.Interaction):
        update_env_file(".env", {"OPENAI_API_KEY": self.openai_api_key.value})
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage.",
            view=view,
            ephemeral=True,
        )


class EnvDiscordModal(discord.ui.Modal, title="Variables Discord"):
    discord_token = discord.ui.TextInput(
        label="DISCORD_TOKEN",
        placeholder="MTxx...",
        max_length=200,
    )
    discord_guild_id = discord.ui.TextInput(
        label="DISCORD_GUILD_ID",
        placeholder="1063150486137606256",
        max_length=20,
    )

    def __init__(self, values: dict[str, str]):
        super().__init__()
        self.discord_token.default = values.get("DISCORD_TOKEN", "")
        self.discord_guild_id.default = values.get("DISCORD_GUILD_ID", "")

    async def on_submit(self, interaction: discord.Interaction):
        update_env_file(".env", {
            "DISCORD_TOKEN": self.discord_token.value,
            "DISCORD_GUILD_ID": self.discord_guild_id.value,
        })
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage.",
            view=view,
            ephemeral=True,
        )


class EnvTwitchIdModal(discord.ui.Modal, title="Twitch — Identité"):
    twitch_client_id = discord.ui.TextInput(label="TWITCH_CLIENT_ID", max_length=50)
    twitch_client_secret = discord.ui.TextInput(label="TWITCH_CLIENT_SECRET", max_length=50)
    twitch_broadcaster_id = discord.ui.TextInput(label="TWITCH_BROADCASTER_ID", max_length=20)
    twitch_bot_id = discord.ui.TextInput(label="TWITCH_BOT_ID", max_length=20)
    twitch_bot_nick = discord.ui.TextInput(label="TWITCH_BOT_NICK", max_length=50)

    def __init__(self, values: dict[str, str]):
        super().__init__()
        self.twitch_client_id.default = values.get("TWITCH_CLIENT_ID", "")
        self.twitch_client_secret.default = values.get("TWITCH_CLIENT_SECRET", "")
        self.twitch_broadcaster_id.default = values.get("TWITCH_BROADCASTER_ID", "")
        self.twitch_bot_id.default = values.get("TWITCH_BOT_ID", "")
        self.twitch_bot_nick.default = values.get("TWITCH_BOT_NICK", "")

    async def on_submit(self, interaction: discord.Interaction):
        update_env_file(".env", {
            "TWITCH_CLIENT_ID": self.twitch_client_id.value,
            "TWITCH_CLIENT_SECRET": self.twitch_client_secret.value,
            "TWITCH_BROADCASTER_ID": self.twitch_broadcaster_id.value,
            "TWITCH_BOT_ID": self.twitch_bot_id.value,
            "TWITCH_BOT_NICK": self.twitch_bot_nick.value,
        })
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage.",
            view=view,
            ephemeral=True,
        )


class EnvTwitchTokensModal(discord.ui.Modal, title="Twitch — Tokens"):
    bot_access_token = discord.ui.TextInput(label="BOT_ACCESS_TOKEN", max_length=200)
    bot_refresh_token = discord.ui.TextInput(label="BOT_REFRESH_TOKEN", max_length=200)
    streamer_access_token = discord.ui.TextInput(label="STREAMER_ACCESS_TOKEN", max_length=200)
    streamer_refresh_token = discord.ui.TextInput(label="STREAMER_REFRESH_TOKEN", max_length=200)

    def __init__(self, values: dict[str, str]):
        super().__init__()
        self.bot_access_token.default = values.get("BOT_ACCESS_TOKEN", "")
        self.bot_refresh_token.default = values.get("BOT_REFRESH_TOKEN", "")
        self.streamer_access_token.default = values.get("STREAMER_ACCESS_TOKEN", "")
        self.streamer_refresh_token.default = values.get("STREAMER_REFRESH_TOKEN", "")

    async def on_submit(self, interaction: discord.Interaction):
        update_env_file(".env", {
            "BOT_ACCESS_TOKEN": self.bot_access_token.value,
            "BOT_REFRESH_TOKEN": self.bot_refresh_token.value,
            "STREAMER_ACCESS_TOKEN": self.streamer_access_token.value,
            "STREAMER_REFRESH_TOKEN": self.streamer_refresh_token.value,
        })
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "✅ Sauvegardé. Les changements s'appliqueront au prochain démarrage.",
            view=view,
            ephemeral=True,
        )


class EnvOpenAIButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="OpenAI", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        values = read_env_values()
        await interaction.response.send_modal(EnvOpenAIModal(values))


class EnvDiscordButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Discord", style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction: discord.Interaction):
        values = read_env_values()
        await interaction.response.send_modal(EnvDiscordModal(values))


class EnvTwitchIdButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Twitch — Identité", style=discord.ButtonStyle.primary, row=2)

    async def callback(self, interaction: discord.Interaction):
        values = read_env_values()
        await interaction.response.send_modal(EnvTwitchIdModal(values))


class EnvTwitchTokensButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Twitch — Tokens", style=discord.ButtonStyle.primary, row=3)

    async def callback(self, interaction: discord.Interaction):
        values = read_env_values()
        await interaction.response.send_modal(EnvTwitchTokensModal(values))


class EnvView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(EnvOpenAIButton())
        self.add_item(EnvDiscordButton())
        self.add_item(EnvTwitchIdButton())
        self.add_item(EnvTwitchTokensButton())


async def _send_env_tab(bot: "WallyDiscord", interaction: discord.Interaction) -> None:
    missing = is_env_complete()
    lines = ["**Variables d'environnement** — Sélectionnez un groupe à modifier :"]
    if missing:
        lines.append(f"⚠️ Clés manquantes : {', '.join(missing)}")
    view = EnvView()
    await interaction.response.send_message("\n".join(lines), view=view, ephemeral=True)


# ── Sélecteur de niveau + SetupView ──────────────────────────────────────────

class LevelSelect(discord.ui.Select):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Basique", value="basic", emoji="⚙️",
                                 description="Modèle, humeur, triggers, Twitch events, mémoire, .env"),
            discord.SelectOption(label="Avancé", value="advanced", emoji="🔧",
                                 description="Paramètres bot, Discord, Twitch, OpenAI, decay"),
        ]
        super().__init__(placeholder="Choisir un niveau...", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "basic":
            view = BasicView(self.bot)
            await interaction.response.send_message(
                "**Configuration — Niveau Basique**", view=view, ephemeral=True
            )
        else:
            view = AdvancedView(self.bot)
            await interaction.response.send_message(
                "**Configuration — Niveau Avancé**", view=view, ephemeral=True
            )


class RestartButton(discord.ui.Button):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(
            label="🔄 Redémarrer le bot",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        view = ConfirmRestartView()
        await interaction.response.send_message(
            "⚠️ Confirmer le redémarrage du bot ?",
            view=view,
            ephemeral=True,
        )


class SetupView(discord.ui.View):
    def __init__(self, bot: "WallyDiscord"):
        super().__init__(timeout=180)
        self.add_item(LevelSelect(bot))
        self.add_item(RestartButton(bot))


class SetupCog(commands.Cog):
    def __init__(self, bot: "WallyDiscord"):
        self.bot = bot

    @app_commands.command(
        name="setup", description="Panneau de configuration de Wally (admin)"
    )
    @app_commands.default_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        missing = is_env_complete()
        if missing:
            content = (
                "**Configuration de Wally** — Sélectionnez un niveau :\n"
                f"⚠️ Clés `.env` manquantes : {', '.join(missing)}"
            )
        else:
            content = "**Configuration de Wally** — Sélectionnez un niveau :"
        view = SetupView(self.bot)
        await interaction.response.send_message(content, view=view, ephemeral=True)
