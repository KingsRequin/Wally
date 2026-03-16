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
from bot.discord.commands.persona_cmd import PersonaCog
from bot.discord.commands.setup import is_valid_model, SetupCog, SetupView, BasicTabSelect


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
    bot.memory.get_all = AsyncMock(return_value="")
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
    bot.memory.get_all = AsyncMock(return_value="")
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
    bot.memory.get_all = AsyncMock(return_value="Bob aime les chats.")
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
    assert len(view.children) == 2  # LevelSelect + RestartButton


@pytest.mark.asyncio
async def test_setup_command_sends_ephemeral():
    bot = make_bot()
    cog = SetupCog(bot)
    interaction = make_interaction()
    await cog.setup.callback(cog, interaction)
    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ── /wally reload-persona ──────────────────────────────────────────────────────

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


@pytest.mark.asyncio
async def test_mood_command_displays_percentage():
    """La commande /mood affiche les émotions en % et non en float."""
    from bot.discord.commands.mood import MoodCog
    from unittest.mock import AsyncMock, MagicMock

    bot = MagicMock()
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.73, "sadness": 0.0,
                      "curiosity": 0.0, "boredom": 0.0}
    )

    cog = MoodCog(bot)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.mood.callback(cog, interaction)

    call_kwargs = interaction.response.send_message.call_args
    embed = call_kwargs.kwargs.get("embed") or (call_kwargs.args[0] if call_kwargs.args else None)
    assert embed is not None
    # Chercher "73%" dans les champs de l'embed
    field_values = [f.value for f in embed.fields]
    assert any("73%" in v for v in field_values)
    assert not any("0.73" in v for v in field_values)


@pytest.mark.asyncio
async def test_setup_mood_tab_displays_percentage():
    """L'onglet Humeur du /setup affiche les émotions en %."""
    from bot.discord.commands.setup import BasicTabSelect  # remplace SetupTabSelect
    from unittest.mock import AsyncMock, MagicMock

    bot = MagicMock()
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.65, "sadness": 0.0,
                      "curiosity": 0.0, "boredom": 0.0}
    )
    bot.config.bot.trigger_names = ["wally"]

    select = BasicTabSelect(bot)  # remplace SetupTabSelect(bot)
    select._values = ["mood"]
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await select.callback(interaction)

    call_args = interaction.response.send_message.call_args
    content = call_args.args[0] if call_args.args else call_args.kwargs.get("content", "")
    assert "65%" in content
    assert "0.65" not in content


@pytest.mark.asyncio
async def test_send_env_tab_includes_env_view(monkeypatch):
    """_send_env_tab envoie un message avec une EnvView (pas juste du texte)."""
    from bot.discord.commands.setup import _send_env_tab, EnvView
    import bot.discord.commands.setup as setup_module

    monkeypatch.setattr(setup_module, "is_env_complete",
                        lambda path=".env": ["OPENAI_API_KEY"])

    bot_obj = make_bot()
    interaction = make_interaction()

    await _send_env_tab(bot_obj, interaction)

    call_args = interaction.response.send_message.call_args
    msg = call_args.args[0] if call_args.args else call_args.kwargs.get("content", "")
    assert "OPENAI_API_KEY" in msg
    # La vraie implémentation doit passer une EnvView
    view = call_args.kwargs.get("view")
    assert view is not None
    assert isinstance(view, EnvView)


@pytest.mark.asyncio
async def test_env_openai_modal_saves_key(monkeypatch):
    """EnvOpenAIModal.on_submit appelle update_env_file avec OPENAI_API_KEY."""
    from bot.discord.commands.setup import EnvOpenAIModal
    import bot.discord.commands.setup as setup_module

    saved = {}
    monkeypatch.setattr(setup_module, "update_env_file",
                        lambda path, updates: saved.update(updates))

    modal = EnvOpenAIModal({})
    modal.openai_api_key._value = "sk-new-key"

    interaction = make_interaction()
    await modal.on_submit(interaction)

    assert saved.get("OPENAI_API_KEY") == "sk-new-key"
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_advanced_tab_bot_sends_message():
    """L'onglet Bot Général envoie un message avec BotGeneralView."""
    from bot.discord.commands.setup import AdvancedTabSelect

    bot = make_bot()
    bot.config.bot.language_default = "fr"
    bot.config.bot.context_window_size = 20
    bot.config.bot.context_token_threshold = 3000
    bot.config.bot.journal_time = "21:00"
    bot.config.bot.prelude_window_size = 15
    bot.config.bot.journal_channel_id = None

    select = AdvancedTabSelect(bot)
    select._values = ["bot"]
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await select.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_bot_general_modal_saves_config(tmp_path, monkeypatch):
    """BotGeneralModal met à jour config et appelle config.save()."""
    from bot.discord.commands.setup import BotGeneralModal

    bot = make_bot()
    bot.config.bot.language_default = "fr"
    bot.config.bot.context_window_size = 20
    bot.config.bot.context_token_threshold = 3000
    bot.config.bot.journal_time = "21:00"
    bot.config.bot.prelude_window_size = 15
    bot.config.save = MagicMock()

    modal = BotGeneralModal(bot)
    modal.language_default._value = "en"
    modal.context_window_size._value = "25"
    modal.context_token_threshold._value = "4000"
    modal.journal_time._value = "20:00"
    modal.prelude_window_size._value = "10"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    assert bot.config.bot.language_default == "en"
    assert bot.config.bot.context_window_size == 25
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_bot_general_modal_rejects_invalid_int():
    """BotGeneralModal envoie une erreur si context_window_size n'est pas un int valide."""
    from bot.discord.commands.setup import BotGeneralModal

    bot = make_bot()
    bot.config.bot.language_default = "fr"
    bot.config.bot.context_window_size = 20
    bot.config.bot.context_token_threshold = 3000
    bot.config.bot.journal_time = "21:00"
    bot.config.bot.prelude_window_size = 15
    bot.config.save = MagicMock()

    modal = BotGeneralModal(bot)
    modal.language_default._value = "fr"
    modal.context_window_size._value = "abc"  # invalide
    modal.context_token_threshold._value = "3000"
    modal.journal_time._value = "21:00"
    modal.prelude_window_size._value = "15"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    bot.config.save.assert_not_called()
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_params_modal_saves_config():
    """DiscordParamsModal met à jour anger_trigger_threshold et timeout_minutes."""
    from bot.discord.commands.setup import DiscordParamsModal

    bot = make_bot()
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10
    bot.config.save = MagicMock()

    modal = DiscordParamsModal(bot)
    modal.anger_trigger_threshold._value = "5"
    modal.timeout_minutes._value = "15"

    interaction = make_interaction()
    await modal.on_submit(interaction)

    assert bot.config.discord.anger_trigger_threshold == 5
    assert bot.config.discord.timeout_minutes == 15
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_journal_channel_modal_clears_on_empty():
    """JournalChannelModal avec input vide met journal_channel_id à None."""
    from bot.discord.commands.setup import JournalChannelModal

    bot = make_bot()
    bot.config.bot.journal_channel_id = 12345
    bot.config.save = MagicMock()

    modal = JournalChannelModal(bot)
    modal.channel_id._value = ""

    interaction = make_interaction()
    await modal.on_submit(interaction)

    assert bot.config.bot.journal_channel_id is None
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_edit_channel_list_modal_parses_comma_sep_ints():
    """EditChannelListModal parse les IDs séparés par des virgules."""
    from bot.discord.commands.setup import EditChannelListModal

    bot = make_bot()
    bot.config.discord.channel_blacklist = []
    bot.config.save = MagicMock()

    modal = EditChannelListModal(bot, "blacklist")
    modal.channel_ids._value = "123456, 789012, 345678"

    interaction = make_interaction()
    await modal.on_submit(interaction)

    assert bot.config.discord.channel_blacklist == [123456, 789012, 345678]
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_edit_channel_list_modal_rejects_invalid():
    """EditChannelListModal rejette les IDs non entiers."""
    from bot.discord.commands.setup import EditChannelListModal

    bot = make_bot()
    bot.config.discord.channel_blacklist = []
    bot.config.save = MagicMock()

    modal = EditChannelListModal(bot, "blacklist")
    modal.channel_ids._value = "abc, 123"

    interaction = make_interaction()
    await modal.on_submit(interaction)

    bot.config.save.assert_not_called()


@pytest.mark.asyncio
async def test_twitch_config_modal_saves_config():
    """TwitchConfigModal met à jour channels et cooldown_seconds."""
    from bot.discord.commands.setup import TwitchConfigModal

    bot = make_bot()
    bot.config.twitch.channels = ["Azrael_TTV"]
    bot.config.twitch.cooldown_seconds = 10
    bot.config.save = MagicMock()

    modal = TwitchConfigModal(bot)
    modal.channels._value = "Azrael_TTV, OtherStreamer"
    modal.cooldown_seconds._value = "15"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    assert bot.config.twitch.channels == ["Azrael_TTV", "OtherStreamer"]
    assert bot.config.twitch.cooldown_seconds == 15
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_openai_params_modal_rejects_invalid_temperature():
    """OpenAIParamsModal rejette une température hors de [0.0, 2.0]."""
    from bot.discord.commands.setup import OpenAIParamsModal

    bot = make_bot()
    bot.config.openai.temperature = 0.8
    bot.config.openai.max_tokens = 1000
    bot.config.save = MagicMock()

    modal = OpenAIParamsModal(bot)
    modal.temperature._value = "3.5"  # hors plage
    modal.max_tokens._value = "1000"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    bot.config.save.assert_not_called()


@pytest.mark.asyncio
async def test_decay_modal_saves_all_lambdas():
    """DecayModal met à jour decay_lambda pour chaque émotion."""
    from bot.discord.commands.setup import DecayModal
    from bot.config import EmotionDecayConfig

    bot = make_bot()
    bot.config.emotions = {
        "anger": EmotionDecayConfig(decay_lambda=0.01),
        "joy": EmotionDecayConfig(decay_lambda=0.005),
        "sadness": EmotionDecayConfig(decay_lambda=0.008),
        "curiosity": EmotionDecayConfig(decay_lambda=0.01),
        "boredom": EmotionDecayConfig(decay_lambda=0.015),
    }
    bot.config.save = MagicMock()

    modal = DecayModal(bot)
    modal.anger._value = "0.02"
    modal.joy._value = "0.01"
    modal.sadness._value = "0.015"
    modal.curiosity._value = "0.012"
    modal.boredom._value = "0.02"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    assert bot.config.emotions["anger"].decay_lambda == pytest.approx(0.02)
    assert bot.config.emotions["joy"].decay_lambda == pytest.approx(0.01)
    bot.config.save.assert_called_once()


@pytest.mark.asyncio
async def test_decay_modal_rejects_out_of_range():
    """DecayModal rejette decay_lambda hors de (0.0, 1.0)."""
    from bot.discord.commands.setup import DecayModal
    from bot.config import EmotionDecayConfig

    bot = make_bot()
    bot.config.emotions = {
        e: EmotionDecayConfig(decay_lambda=0.01)
        for e in ["anger", "joy", "sadness", "curiosity", "boredom"]
    }
    bot.config.save = MagicMock()

    modal = DecayModal(bot)
    modal.anger._value = "1.5"  # hors plage
    modal.joy._value = "0.01"
    modal.sadness._value = "0.008"
    modal.curiosity._value = "0.01"
    modal.boredom._value = "0.015"

    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)

    bot.config.save.assert_not_called()


@pytest.mark.asyncio
async def test_setup_command_warns_if_env_incomplete(monkeypatch):
    """Le message d'accueil de /setup liste les clés .env manquantes."""
    import bot.discord.commands.setup as setup_module
    monkeypatch.setattr(setup_module, "is_env_complete", lambda path=".env": ["OPENAI_API_KEY"])

    bot_obj = make_bot()
    cog = SetupCog(bot_obj)
    interaction = make_interaction()

    await cog.setup.callback(cog, interaction)

    call_args = interaction.response.send_message.call_args
    content = call_args.args[0] if call_args.args else call_args.kwargs.get("content", "")
    assert "OPENAI_API_KEY" in content
