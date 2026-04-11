# bot/discord/commands/setup/__init__.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot.discord.commands.setup.utils import (
    EDITABLE_ENV_KEYS,
    read_env_values,
    update_env_file,
    is_env_complete,
    is_valid_model,
    ConfirmRestartView,
)
from bot.discord.commands.setup.basic import BasicView, BasicTabSelect
from bot.discord.commands.setup.advanced import (
    AdvancedView,
    AdvancedTabSelect,
    BotGeneralModal,
    JournalChannelModal,
    BotGeneralView,
    DiscordParamsModal,
    EditChannelListModal,
    DiscordView,
    TwitchConfigModal,
    TwitchConfigView,
    OpenAIParamsModal,
    OpenAIParamsView,
    DecayModal,
    DecayView,
)
from bot.discord.commands.setup.env import _send_env_tab, EnvView, EnvOpenAIModal

__all__ = [
    "SetupCog",
    "SetupView",
    "LevelSelect",
    "RestartButton",
    "BasicView",
    "BasicTabSelect",
    "AdvancedView",
    "AdvancedTabSelect",
    "BotGeneralModal",
    "JournalChannelModal",
    "BotGeneralView",
    "DiscordParamsModal",
    "EditChannelListModal",
    "DiscordView",
    "TwitchConfigModal",
    "TwitchConfigView",
    "OpenAIParamsModal",
    "OpenAIParamsView",
    "DecayModal",
    "DecayView",
    "EnvView",
    "EnvOpenAIModal",
    "_send_env_tab",
    "is_valid_model",
    "is_env_complete",
    "read_env_values",
    "update_env_file",
    "EDITABLE_ENV_KEYS",
    "ConfirmRestartView",
]

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


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
