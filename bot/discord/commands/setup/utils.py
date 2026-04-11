# bot/discord/commands/setup/utils.py
from __future__ import annotations

import asyncio
import os

import discord

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

EXCLUDED_MODEL_KEYWORDS = ["realtime", "preview", "audio", "vision"]
INCLUDED_MODEL_KEYWORDS = ["gpt", "chatgpt", "o1", "o3", "o4"]


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


# ── Restart confirmation ──────────────────────────────────────────────────────

class ConfirmRestartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔄 Redémarrage en cours...", ephemeral=True)
        asyncio.get_running_loop().call_later(1.0, os._exit, 0)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Redémarrage annulé.", ephemeral=True)
