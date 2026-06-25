# tests/test_discord_userfacing_name.py
"""
TDD: vérifie que les titres d'embed et textes affichés au runtime utilisent
bot_name() (dynamique), et que les descriptions de commandes sont génériques
(sans "Wally").
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence import identity
from bot.discord.commands.mood import MoodCog
from bot.discord.commands.memory_cmd import MemoryPaginatedView, MemoryCog


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_bot_named(name: str):
    bot = MagicMock()
    bot.config.bot.name = name
    bot.config.bot.love_decay_lambda = 0.1
    bot.emotion.get_state = MagicMock(
        return_value={
            "anger": 0.0, "joy": 0.5, "sadness": 0.0,
            "curiosity": 0.3, "boredom": 0.0,
        }
    )
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.get_love_score = AsyncMock(return_value=0.3)
    bot.memory.get_all = AsyncMock(return_value="se souvient de quelque chose")
    return bot


def _make_interaction():
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.user.display_name = "Testeur"
    interaction.guild = MagicMock()
    interaction.guild.return_value = True
    interaction.guild.permissions_for = MagicMock()
    interaction.user.guild_permissions = MagicMock(administrator=True)
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ── mood embed titre ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mood_embed_title_uses_bot_name(monkeypatch):
    """Le titre de l'embed /mood reflète le nom du bot configuré, pas 'Wally' en dur."""
    monkeypatch.setattr(identity, "_NAME", "Cindy")

    bot = _make_bot_named("Cindy")
    cog = MoodCog(bot)
    interaction = _make_interaction()

    await cog.mood.callback(cog, interaction)

    embed = interaction.response.send_message.call_args.kwargs["embed"]
    assert embed.title == "Humeur de Cindy", (
        f"Titre attendu 'Humeur de Cindy', obtenu '{embed.title}'"
    )


@pytest.mark.asyncio
async def test_mood_embed_title_default_wally(monkeypatch):
    """Par défaut (identité non changée), le titre est 'Humeur de Wally'."""
    monkeypatch.setattr(identity, "_NAME", "Wally")

    bot = _make_bot_named("Wally")
    cog = MoodCog(bot)
    interaction = _make_interaction()

    await cog.mood.callback(cog, interaction)

    embed = interaction.response.send_message.call_args.kwargs["embed"]
    assert embed.title == "Humeur de Wally"


# ── memory embed titre ────────────────────────────────────────────────────────

def test_memory_paginated_view_title_uses_bot_name(monkeypatch):
    """MemoryPaginatedView._make_embed utilise bot_name() dans le titre."""
    monkeypatch.setattr(identity, "_NAME", "Cindy")

    view = MemoryPaginatedView(["contenu mémoire"], "Alice")
    embed = view._make_embed()

    assert "Cindy" in embed.title, (
        f"Titre attendu contenant 'Cindy', obtenu '{embed.title}'"
    )
    assert "Alice" in embed.title


@pytest.mark.asyncio
async def test_memory_show_embed_title_uses_bot_name(monkeypatch):
    """Le titre de l'embed /memory (cas sans souvenirs) contient le nom du bot."""
    monkeypatch.setattr(identity, "_NAME", "Cindy")

    bot = _make_bot_named("Cindy")
    bot.memory.get_all = AsyncMock(return_value="")  # pas de souvenirs
    cog = MemoryCog(bot)
    interaction = _make_interaction()

    target_user = MagicMock()
    target_user.id = 999
    target_user.display_name = "Bob"

    await cog.memory_show.callback(cog, interaction, target_user)

    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert "Cindy" in embed.title, (
        f"Titre attendu contenant 'Cindy', obtenu '{embed.title}'"
    )


@pytest.mark.asyncio
async def test_memory_show_embed_title_with_memories_uses_bot_name(monkeypatch):
    """Le titre de l'embed /memory (avec souvenirs, paginator) contient le nom du bot."""
    monkeypatch.setattr(identity, "_NAME", "Cindy")

    bot = _make_bot_named("Cindy")
    bot.memory.get_all = AsyncMock(return_value="Bob aime les chats.")
    cog = MemoryCog(bot)
    interaction = _make_interaction()

    target_user = MagicMock()
    target_user.id = 999
    target_user.display_name = "Bob"

    await cog.memory_show.callback(cog, interaction, target_user)

    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert "Cindy" in embed.title, (
        f"Titre attendu contenant 'Cindy', obtenu '{embed.title}'"
    )


# ── descriptions de commandes génériques (pas de "Wally" en dur) ─────────────

def test_mood_command_description_no_wally():
    """La description de /mood ne doit pas contenir 'Wally' (générique)."""
    from discord import app_commands
    # Parcourt les commandes app_commands du cog
    bot = MagicMock()
    bot.emotion.get_state = MagicMock(return_value={})
    cog = MoodCog(bot)

    # La description est sur l'objet Command (pas sur cog.mood directement)
    desc = cog.mood.description
    assert "Wally" not in desc, (
        f"Description contient encore 'Wally': '{desc}'"
    )


def test_memory_command_description_no_wally():
    """La description de /memory ne doit pas contenir 'Wally' (générique)."""
    bot = MagicMock()
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.get_love_score = AsyncMock(return_value=0.3)
    bot.memory.get_all = AsyncMock(return_value="")
    cog = MemoryCog(bot)

    desc = cog.memory_show.description
    assert "Wally" not in desc, (
        f"Description contient encore 'Wally': '{desc}'"
    )
