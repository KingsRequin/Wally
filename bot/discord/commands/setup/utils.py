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

# Modèles non conversationnels ou incompatibles Chat Completions. La liste
# n'avait que les quatre premiers : `gpt-image-1.5` (le modèle IMAGE du projet),
# `gpt-4o-transcribe`, `gpt-4o-mini-tts` et `gpt-3.5-turbo-instruct` passaient
# donc le filtre et apparaissaient dans le menu « Modèle principal ». En choisir
# un cassait le LLM en silence, et le choix était persisté par `config.save()`.
EXCLUDED_MODEL_KEYWORDS = [
    "realtime", "preview", "audio", "vision",
    "image", "tts", "transcribe", "instruct", "embedding", "moderation", "search",
    # Modèles de CODE : ils répondent en Chat Completions, donc rien ne les
    # écarterait, mais ils sont entraînés à produire des diffs et des patchs —
    # aux antipodes d'une persona qui tchatte. Ajouté en même temps que `gpt`
    # aux familles acceptées, qui les faisait entrer par la porte ouverte.
    "codex",
]
# Familles conversationnelles acceptées. Elle valait ["gpt", "chatgpt"] plus les
# préfixes o1/o3/o4, héritée de l'époque où le texte passait par OpenAI ; quand
# la factory s'est restreinte à DeepSeek, le menu ne proposait plus QUE des
# modèles que le LLM texte ne savait pas servir. En choisir un écrivait
# `llm.primary.model = "gpt-…"` puis l'envoyait à `api.deepseek.com` — chaque
# appel en échec, sur les deux plateformes, jusqu'à édition du YAML.
#
# `gpt` revient le 2026-08-25 parce que `openai` est de nouveau un fournisseur de
# texte constructible (`SUPPORTED_TEXT_PROVIDERS`). Cette liste doit rester le
# reflet de ce que la factory sait construire : l'élargir avant la factory
# reproduirait exactement la panne ci-dessus, dans l'autre sens.
INCLUDED_MODEL_KEYWORDS = ["deepseek", "gpt"]


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
