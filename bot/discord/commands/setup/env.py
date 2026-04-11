# bot/discord/commands/setup/env.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bot.discord.commands.setup.utils import (
    ConfirmRestartView,
    read_env_values,
    update_env_file,
    is_env_complete,
)

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


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
