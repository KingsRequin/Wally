# tests/test_discord_descriptions_ui.py
"""
TDD: vérifie que :
  (a) Les titres d'embed et textes UI runtime utilisent bot_name() — dynamiques.
  (b) Les descriptions des commandes ask/status/test/journal/setup sont
      GÉNÉRIQUES (ne contiennent plus "Wally").
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence import identity
from bot.discord.commands.ask import AskCog
from bot.discord.commands.status import StatusCog
from bot.discord.commands.test_cmd import TestCog
from bot.discord.commands.journal_cmd import JournalCog
from bot.discord.commands.setup import SetupCog


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_bot(name: str = "Wally"):
    bot = MagicMock()
    bot.config.bot.name = name
    bot.config.llm.primary.provider = "openai"
    bot.config.llm.primary.model = "gpt-4o"
    bot._start_time = None
    bot.emotion.get_state = MagicMock(
        return_value={
            "anger": 0.0, "joy": 0.5, "sadness": 0.0,
            "curiosity": 0.3, "boredom": 0.0,
        }
    )
    bot.emotion.get_dominant = MagicMock(return_value=["joy"])
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.image_client.get_daily_cost = AsyncMock(return_value=0.01)
    bot.image_client.get_monthly_cost = AsyncMock(return_value=0.1)
    return bot


def _make_interaction():
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.user.display_name = "Testeur"
    interaction.guild_id = 100
    interaction.channel_id = 200
    interaction.guild = MagicMock()
    interaction.channel = MagicMock()
    interaction.channel.name = "general"
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ── (a) titres/textes runtime → bot_name() ────────────────────────────────────

@pytest.mark.asyncio
async def test_status_embed_title_uses_bot_name_cindy(monkeypatch):
    """Avec set_identity(name='Cindy'), le titre embed /status = 'Statut de Cindy'."""
    monkeypatch.setattr(identity, "_NAME", "Cindy")

    bot = _make_bot("Cindy")
    cog = StatusCog(bot)
    interaction = _make_interaction()

    await cog.status.callback(cog, interaction)

    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert embed.title == "Statut de Cindy", (
        f"Titre attendu 'Statut de Cindy', obtenu '{embed.title}'"
    )


@pytest.mark.asyncio
async def test_status_embed_title_default_wally(monkeypatch):
    """Par défaut, le titre est 'Statut de Wally'."""
    monkeypatch.setattr(identity, "_NAME", "Wally")

    bot = _make_bot("Wally")
    cog = StatusCog(bot)
    interaction = _make_interaction()

    await cog.status.callback(cog, interaction)

    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert embed.title == "Statut de Wally"


@pytest.mark.asyncio
async def test_setup_content_uses_bot_name_cindy(monkeypatch):
    """Avec set_identity(name='Cindy'), le message /setup contient 'Cindy'."""
    import bot.discord.commands.setup as setup_module
    monkeypatch.setattr(identity, "_NAME", "Cindy")

    # Patch is_env_complete to return empty (no missing keys)
    monkeypatch.setattr(setup_module, "is_env_complete", lambda: [])

    bot = _make_bot("Cindy")
    cog = SetupCog(bot)
    interaction = _make_interaction()

    await cog.setup.callback(cog, interaction)

    call_kwargs = interaction.response.send_message.call_args
    content = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("content", "")
    assert "Cindy" in content, (
        f"Contenu setup attendu contenant 'Cindy', obtenu: '{content}'"
    )


@pytest.mark.asyncio
async def test_setup_content_with_missing_env_uses_bot_name(monkeypatch):
    """Avec des clés .env manquantes et name='Cindy', le message contient 'Cindy'."""
    import bot.discord.commands.setup as setup_module
    monkeypatch.setattr(identity, "_NAME", "Cindy")

    monkeypatch.setattr(setup_module, "is_env_complete", lambda: ["OPENAI_API_KEY"])

    bot = _make_bot("Cindy")
    cog = SetupCog(bot)
    interaction = _make_interaction()

    await cog.setup.callback(cog, interaction)

    call_kwargs = interaction.response.send_message.call_args
    content = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("content", "")
    assert "Cindy" in content, (
        f"Contenu setup (env manquant) attendu contenant 'Cindy', obtenu: '{content}'"
    )


# ── (b) descriptions commandes génériques — pas de "Wally" ───────────────────

def test_ask_command_description_no_wally():
    """La description de /ask ne doit pas contenir 'Wally'."""
    bot = _make_bot()
    cog = AskCog(bot)
    assert "Wally" not in cog.ask.description, (
        f"Description /ask contient 'Wally': '{cog.ask.description}'"
    )


def test_ask_param_description_no_wally():
    """Le describe de /ask question ne doit pas contenir 'Wally'."""
    bot = _make_bot()
    cog = AskCog(bot)
    # Les describe() sont stockés dans _params en tant que app_commands.Parameter
    # La description peut être un locale_str — on passe par str() pour comparer.
    params = {p.name: p for p in cog.ask._params.values()}
    question_desc = str(params["question"].description)
    assert "Wally" not in question_desc, (
        f"Describe /ask question contient 'Wally': '{question_desc}'"
    )


def test_status_command_description_no_wally():
    """La description de /status ne doit pas contenir 'Wally'."""
    bot = _make_bot()
    cog = StatusCog(bot)
    assert "Wally" not in cog.status.description, (
        f"Description /status contient 'Wally': '{cog.status.description}'"
    )


def test_test_command_description_no_wally():
    """La description de /test ne doit pas contenir 'Wally'."""
    bot = _make_bot()
    cog = TestCog(bot)
    assert "Wally" not in cog.test_feature.description, (
        f"Description /test contient 'Wally': '{cog.test_feature.description}'"
    )


def test_journal_command_description_no_wally():
    """La description de /journal ne doit pas contenir 'Wally'."""
    bot = _make_bot()
    cog = JournalCog(bot)
    assert "Wally" not in cog.journal.description, (
        f"Description /journal contient 'Wally': '{cog.journal.description}'"
    )


def test_setup_command_description_no_wally():
    """La description de /setup ne doit pas contenir 'Wally'."""
    bot = _make_bot()
    cog = SetupCog(bot)
    assert "Wally" not in cog.setup.description, (
        f"Description /setup contient 'Wally': '{cog.setup.description}'"
    )
