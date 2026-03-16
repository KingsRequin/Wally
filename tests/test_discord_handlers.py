# tests/test_discord_handlers.py
"""
Tests for Discord message handler pipeline.
All Discord objects and services are mocked — no real bot connection needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.discord.handlers import handle_message, _respond, _post_process


def make_bot(trigger_names=None, muted=False, welcomed=False, trust=0.5):
    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = trigger_names or ["wally"]
    bot.config.bot.prelude_window_size = 5        # ← nouveau
    bot.config.discord.allowed_channels = []
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10

    bot.db.is_muted = AsyncMock(return_value=muted)
    bot.db.is_welcomed = AsyncMock(return_value=welcomed)
    bot.db.get_trust_score = AsyncMock(return_value=trust)
    bot.db.update_trust_score = AsyncMock()
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.add_timeout = AsyncMock()
    bot.db.mark_welcomed = AsyncMock()

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    bot.emotion.get_dominant = MagicMock(return_value=["joy"])
    bot.emotion.process_message = AsyncMock()

    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.memory.get_prelude = MagicMock(return_value=[])      # ← nouveau
    bot.memory.append_prelude = MagicMock()                  # ← nouveau

    bot.language.detect = MagicMock(return_value="fr")
    bot.prompts.build_system_prompt = MagicMock(return_value="system prompt")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")  # ← nouveau
    bot.openai.complete = AsyncMock(return_value="Bonjour!")

    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="persona block")

    return bot


def make_message(content="wally bonjour", author_bot=False, mentions=None):
    """Build a minimal discord.Message-like mock."""
    msg = MagicMock()
    msg.content = content
    msg.author.bot = author_bot
    msg.author.id = 12345
    msg.author.display_name = "TestUser"
    msg.guild.id = 99999
    msg.channel.id = 777
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.mentions = mentions or []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    # bot.user not in mentions by default
    return msg


# ── handle_message ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ignores_bot_messages():
    bot = make_bot()
    message = make_message(author_bot=True)
    await handle_message(bot, message)
    bot.db.is_muted.assert_not_called()


@pytest.mark.asyncio
async def test_ignores_untriggered_messages():
    bot = make_bot(trigger_names=["wally"])
    message = make_message(content="hello there")
    await handle_message(bot, message)
    bot.db.is_muted.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_by_name_calls_respond():
    bot = make_bot(trigger_names=["wally"])
    message = make_message(content="wally bonjour")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    message.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_by_mention_calls_respond():
    bot = make_bot(trigger_names=["wally"])
    message = make_message(content="hey!", mentions=[bot.user])
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    message.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_muted_user_gets_reaction_not_reply():
    bot = make_bot(muted=True)
    message = make_message(content="wally salut")
    await handle_message(bot, message)
    message.add_reaction.assert_awaited_once()
    message.reply.assert_not_awaited()


# ── _respond ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_respond_adds_and_removes_reaction():
    bot = make_bot()
    message = make_message()
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    message.add_reaction.assert_awaited_once_with("🔍")
    message.remove_reaction.assert_awaited_once_with("🔍", bot.user)


@pytest.mark.asyncio
async def test_respond_appends_to_context_window():
    bot = make_bot()
    message = make_message(content="wally qui es-tu?")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    assert bot.memory.append_message.call_count == 2
    calls = bot.memory.append_message.call_args_list
    assert calls[0].args[1] == "TestUser"
    assert calls[1].args[1] == "Wally"


@pytest.mark.asyncio
async def test_respond_includes_context_block_when_present():
    bot = make_bot()
    bot.prompts.build_context_block = MagicMock(return_value="[ctx block]")
    message = make_message(content="wally continue")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    call_args = bot.openai.complete.call_args
    assert "[ctx block]" in call_args.args[1][0]["content"]


# ── _post_process ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_process_calls_emotion_and_trust():
    bot = make_bot()
    await _post_process(bot, "thank you", "discord", "12345", "99999", 0.5)
    bot.emotion.process_message.assert_awaited_once_with("thank you", trust_score=0.5, context_messages=None)
    bot.db.update_trust_score.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_process_decreases_trust_on_insult():
    bot = make_bot()
    await _post_process(bot, "tu es un idiot", "discord", "12345", "99999", 0.5)
    call = bot.db.update_trust_score.call_args
    assert call.args[2] < 0  # negative delta


@pytest.mark.asyncio
async def test_post_process_mutes_on_high_anger_and_threshold():
    bot = make_bot()
    bot.emotion.get_state = MagicMock(return_value={"anger": 0.9})
    bot.db.count_recent_triggers = AsyncMock(return_value=5)
    await _post_process(bot, "merde", "discord", "12345", "99999", 0.5)
    bot.db.add_timeout.assert_awaited_once()


# ── Premier contact (bienvenue intégrée) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_first_contact_marks_welcomed():
    """Lors du premier contact, mark_welcomed est appelé après la réponse."""
    bot = make_bot(welcomed=False)
    message = make_message(content="wally bonjour")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    bot.db.mark_welcomed.assert_awaited_once_with("12345", "99999")


@pytest.mark.asyncio
async def test_already_welcomed_no_mark():
    """Si déjà accueilli, mark_welcomed n'est pas rappelé."""
    bot = make_bot(welcomed=True)
    message = make_message(content="wally bonjour")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    bot.db.mark_welcomed.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_contact_injects_welcome_context():
    """Lors du premier contact, le contexte bienvenue est injecté dans le prompt."""
    bot = make_bot(welcomed=False)
    message = make_message(content="wally salut")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await handle_message(bot, message)
    call_args = bot.openai.complete.call_args
    user_content = call_args[0][1][0]["content"]
    assert "première fois" in user_content


# ── Prelude context ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_passive_capture_non_triggered_message():
    """append_prelude est appelé même sans trigger, dans les canaux autorisés."""
    bot = make_bot()
    message = make_message(content="juste un message normal")  # pas de trigger
    # bot.user pas dans les mentions, pas de trigger name dans content
    await handle_message(bot, message)
    bot.memory.append_prelude.assert_called_once_with(
        str(message.channel.id),
        message.author.display_name,
        message.content,
    )
    # pas de réponse envoyée
    bot.openai.complete.assert_not_called()


@pytest.mark.asyncio
async def test_prelude_included_in_prompt_on_mention():
    """build_prelude_block est appelé avec le prelude au moment de la mention."""
    bot = make_bot()
    prelude_msgs = [{"author": "Alice", "content": "on parlait de trucs", "timestamp": 1.0}]
    bot.memory.get_prelude = MagicMock(return_value=prelude_msgs)
    bot.prompts.build_prelude_block = MagicMock(return_value="[PRELUDE]")

    message = make_message(content="wally c'est quoi ton avis")
    await handle_message(bot, message)

    bot.prompts.build_prelude_block.assert_called_once_with(prelude_msgs)
    # Le prelude doit apparaître dans user_content envoyé à OpenAI
    call_args = bot.openai.complete.call_args
    user_content = call_args[0][1][0]["content"]  # messages[0]["content"]
    assert "[PRELUDE]" in user_content


@pytest.mark.asyncio
async def test_cold_start_fallback_to_channel_history():
    """Si prelude vide, channel.history() est appelé en fallback."""
    bot = make_bot()
    bot.memory.get_prelude = MagicMock(return_value=[])  # vide = cold start

    # Mock channel.history() — retourne 2 messages dans l'ordre inverse (Discord API)
    history_msg1 = MagicMock()
    history_msg1.author.bot = False
    history_msg1.author.display_name = "Alice"
    history_msg1.content = "premier message"

    history_msg2 = MagicMock()
    history_msg2.author.bot = False
    history_msg2.author.display_name = "Bob"
    history_msg2.content = "deuxième message"

    async def fake_history(limit):
        for m in [history_msg2, history_msg1]:  # Discord retourne du plus récent au plus ancien
            yield m

    message = make_message(content="wally dis moi")
    message.channel.history = fake_history

    await handle_message(bot, message)

    # build_prelude_block doit avoir reçu les messages dans l'ordre chronologique
    call_args = bot.prompts.build_prelude_block.call_args[0][0]
    assert len(call_args) == 2
    assert call_args[0]["author"] == "Alice"   # ordre chronologique : plus ancien d'abord
    assert call_args[1]["author"] == "Bob"


@pytest.mark.asyncio
async def test_channel_history_permission_error_graceful():
    """Une erreur sur channel.history() → log WARNING + réponse sans prelude."""
    bot = make_bot()
    bot.memory.get_prelude = MagicMock(return_value=[])  # vide

    async def broken_history(limit):
        raise Exception("Missing Access")
        return  # pragma: no cover
        yield  # make it a generator

    message = make_message(content="wally aide moi")
    message.channel.history = broken_history

    # Ne doit pas lever d'exception
    await handle_message(bot, message)

    # build_prelude_block appelé avec liste vide (graceful degradation)
    bot.prompts.build_prelude_block.assert_called_once_with([])
    # La réponse est quand même envoyée
    bot.openai.complete.assert_called_once()
