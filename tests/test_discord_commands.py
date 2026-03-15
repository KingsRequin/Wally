# tests/test_discord_commands.py
"""
Tests for Discord slash commands.
All discord objects and services are mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.discord.commands.mood import MoodCog, make_bar
from bot.discord.commands.status import StatusCog
from bot.discord.commands.ask import AskCog
from bot.discord.commands.memory_cmd import MemoryCog
from bot.discord.commands.setup import is_valid_model, SetupCog, SetupView


def make_bot(primary_model="gpt-4o", secondary_model="gpt-4o-mini"):
    bot = MagicMock()
    bot.config.openai.primary_model = primary_model
    bot.config.openai.secondary_model = secondary_model
    bot.config.bot.trigger_names = ["wally"]
    bot.config.twitch_events = {}
    bot._start_time = None

    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.update_trust_score = AsyncMock()

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    bot.emotion.get_dominant = MagicMock(return_value=["joy"])

    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()

    bot.language.detect = MagicMock(return_value="fr")
    bot.prompts.build_system_prompt = MagicMock(return_value="sys")
    bot.prompts.build_context_block = MagicMock(return_value="")

    bot.openai.complete = AsyncMock(return_value="Réponse Wally")
    bot.openai.get_daily_cost = AsyncMock(return_value=0.0123)
    bot.openai.get_monthly_cost = AsyncMock(return_value=0.456)

    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="persona block")

    return bot


def make_interaction(user_id=42, channel_id=100, guild_id=200):
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.user.display_name = "Testeur"
    interaction.channel_id = channel_id
    interaction.guild_id = guild_id
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ── make_bar ──────────────────────────────────────────────────────────────────

def test_make_bar_full():
    assert make_bar(1.0) == "██████████"


def test_make_bar_empty():
    assert make_bar(0.0) == "░░░░░░░░░░"


def test_make_bar_half():
    bar = make_bar(0.5)
    assert bar.count("█") == 5
    assert bar.count("░") == 5


# ── is_valid_model ────────────────────────────────────────────────────────────

def test_is_valid_model_accepts_gpt():
    assert is_valid_model("gpt-4o") is True
    assert is_valid_model("gpt-4o-mini") is True
    assert is_valid_model("o3-mini") is True


def test_is_valid_model_rejects_excluded():
    assert is_valid_model("gpt-4o-realtime-preview") is False
    assert is_valid_model("gpt-4o-audio-preview") is False
    assert is_valid_model("gpt-4-vision-preview") is False


def test_is_valid_model_rejects_unknown():
    assert is_valid_model("whisper-1") is False
    assert is_valid_model("dall-e-3") is False


# ── /wally mood ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mood_sends_embed():
    bot = make_bot()
    cog = MoodCog(bot)
    interaction = make_interaction()
    # discord.py wraps methods with @app_commands.command into Command objects;
    # call .callback(cog, ...) to invoke the underlying coroutine directly.
    await cog.mood.callback(cog, interaction)
    interaction.response.send_message.assert_awaited_once()
    embed = interaction.response.send_message.call_args.kwargs["embed"]
    assert embed.title == "Humeur de Wally"
    assert len(embed.fields) == 5  # one per emotion


# ── /wally status ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_sends_embed():
    bot = make_bot()
    cog = StatusCog(bot)
    interaction = make_interaction()
    await cog.status.callback(cog, interaction)
    interaction.response.defer.assert_awaited_once()
    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert embed.title == "Statut de Wally"


@pytest.mark.asyncio
async def test_status_shows_model_name():
    bot = make_bot(primary_model="gpt-4o-mini")
    cog = StatusCog(bot)
    interaction = make_interaction()
    await cog.status.callback(cog, interaction)
    embed = interaction.followup.send.call_args.kwargs["embed"]
    model_field = next(f for f in embed.fields if f.name == "Modele principal")
    assert model_field.value == "gpt-4o-mini"


# ── /wally ask ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_calls_openai_and_replies():
    bot = make_bot()
    cog = AskCog(bot)
    interaction = make_interaction()
    with patch("bot.discord.commands.ask.asyncio.create_task"):
        await cog.ask.callback(cog, interaction, question="C'est quoi Python?")
    bot.openai.complete.assert_awaited_once()
    interaction.followup.send.assert_awaited_once_with("Réponse Wally")


@pytest.mark.asyncio
async def test_ask_appends_to_context():
    bot = make_bot()
    cog = AskCog(bot)
    interaction = make_interaction()
    with patch("bot.discord.commands.ask.asyncio.create_task"):
        await cog.ask.callback(cog, interaction, question="Test")
    assert bot.memory.append_message.call_count == 2


@pytest.mark.asyncio
async def test_ask_error_sends_fallback():
    bot = make_bot()
    bot.openai.complete = AsyncMock(side_effect=Exception("API down"))
    cog = AskCog(bot)
    interaction = make_interaction()
    await cog.ask.callback(cog, interaction, question="Test")
    interaction.followup.send.assert_awaited_once_with("Une erreur s'est produite.")


# ── /wally memory ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_show_no_memory():
    bot = make_bot()
    bot.memory.search = AsyncMock(return_value="")
    cog = MemoryCog(bot)
    interaction = make_interaction()
    target_user = MagicMock()
    target_user.id = 999
    target_user.display_name = "Bob"
    await cog.memory_show.callback(cog, interaction, target_user)
    followup_text = interaction.followup.send.call_args.args[0]
    assert "Aucune memoire" in followup_text


@pytest.mark.asyncio
async def test_memory_show_sends_embed():
    bot = make_bot()
    bot.memory.search = AsyncMock(return_value="Bob aime les chats.")
    cog = MemoryCog(bot)
    interaction = make_interaction()
    target_user = MagicMock()
    target_user.id = 999
    target_user.display_name = "Bob"
    await cog.memory_show.callback(cog, interaction, target_user)
    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert "Bob" in embed.title


# ── /wally setup ──────────────────────────────────────────────────────────────

def test_setup_view_has_select():
    bot = make_bot()
    view = SetupView(bot)
    assert len(view.children) == 1  # one SetupTabSelect


@pytest.mark.asyncio
async def test_setup_command_sends_ephemeral():
    bot = make_bot()
    cog = SetupCog(bot)
    interaction = make_interaction()
    await cog.setup.callback(cog, interaction)
    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ── /wally reload-persona ──────────────────────────────────────────────────────

from bot.discord.commands.persona_cmd import PersonaCog


@pytest.mark.asyncio
async def test_reload_persona_sends_embed():
    """La commande reload-persona appelle persona.reload() et envoie un embed."""
    bot = make_bot()
    bot.persona = MagicMock()
    bot.persona.reload = MagicMock()
    # Simuler les blocs chargés : SOUL ok, IDENTITY ok, VOICE manquant
    bot.persona._blocks = {
        "SOUL.md": "âme",
        "IDENTITY.md": "identité",
        "VOICE.md": "",
    }
    bot.persona._FILES = ["SOUL.md", "IDENTITY.md", "VOICE.md"]

    cog = PersonaCog(bot)
    interaction = make_interaction()

    await cog.reload_persona.callback(cog, interaction)

    bot.persona.reload.assert_called_once()
    interaction.followup.send.assert_called_once()
    call_kwargs = interaction.followup.send.call_args
    # L'embed doit être passé en kwarg 'embed'
    assert "embed" in call_kwargs.kwargs
