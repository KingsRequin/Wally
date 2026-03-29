# tests/test_twitch_handlers.py
"""
Tests for Twitch message handler pipeline.
Payload is an EventSub channel.chat.message object (not a twitchio IRC Message).
"""
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.twitch.handlers import handle_message, _post_process
from bot.twitch.events import _bits_joy


def make_bot(trigger_names=None, cooldown_seconds=10, trust=0.5):
    bot = MagicMock()
    bot.config.bot.trigger_names = trigger_names or ["wally"]
    bot.config.bot.language_default = "fr"
    bot.config.twitch.cooldown_seconds = cooldown_seconds

    bot._cooldowns = {}
    bot.is_on_cooldown = lambda user_id: (
        time.time() - bot._cooldowns.get(user_id, 0.0)
    ) < cooldown_seconds

    def set_cooldown(user_id):
        bot._cooldowns[user_id] = time.time()

    bot.set_cooldown = set_cooldown

    bot.db.get_trust_score = AsyncMock(return_value=trust)
    bot.db.update_trust_score = AsyncMock()
    bot.db.update_love_score = AsyncMock()
    bot.db.get_love_score = AsyncMock(return_value=0.0)
    bot.db.upsert_memory_user = AsyncMock()
    bot.config.bot.love_decay_lambda = 0.02

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.3, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.0}
    )
    bot.emotion.process_message = AsyncMock(return_value=None)

    bot.memory.search = AsyncMock(return_value="")
    bot.memory.search_global = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.memory.get_pending_question_directive = AsyncMock(return_value="")

    bot.db.get_last_interaction = AsyncMock(return_value=None)
    bot.db.get_recent_jokes = AsyncMock(return_value=[])
    bot.db.get_opinions = AsyncMock(return_value=[])
    bot.db.get_persistent_notes = AsyncMock(return_value=[])

    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.llm.complete = AsyncMock(return_value="Salut depuis Twitch!")
    bot.llm.complete_with_tools = AsyncMock(return_value=("Salut depuis Twitch!", []))

    # TwitchAPI replaces IRC channel.send
    bot.twitch_api.send_message = AsyncMock()

    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="persona block")

    bot.web_search = None  # désactivé par défaut dans les tests
    bot.apex_api = None

    bot.config.bot.spontaneous_twitch_enabled = False  # désactivé pour éviter les MagicMock

    return bot


def make_payload(content="wally salut", author_name="streamer",
                 author_id="111", channel="mychannel", badges=None):
    payload = MagicMock()
    payload.message.text = content
    payload.chatter.name = author_name
    payload.chatter.id = author_id
    payload.chatter.badges = badges if badges is not None else []
    payload.broadcaster.name = channel
    return payload


# ── handle_message ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ignores_own_bot_messages(monkeypatch):
    """Les messages de Wally lui-même (echo EventSub) doivent être ignorés."""
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=["wally"])
    bot.twitch_api._bot_id = "999"
    # Payload dont l'auteur est Wally lui-même
    payload = make_payload(content="wally salut", author_id="999")
    await handle_message(bot, payload)
    bot.llm.complete.assert_not_awaited()
    bot.memory.append_prelude.assert_not_called()


@pytest.mark.asyncio
async def test_ignores_known_bot_username(monkeypatch):
    """Les bots Twitch connus (nightbot, streamelements…) doivent être ignorés."""
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=["wally"])
    payload = make_payload(content="wally salut", author_name="nightbot", author_id="42")
    await handle_message(bot, payload)
    bot.llm.complete.assert_not_awaited()
    bot.memory.append_prelude.assert_not_called()


@pytest.mark.asyncio
async def test_ignores_bot_badge(monkeypatch):
    """Un chatter avec le badge 'bot' doit être ignoré."""
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=["wally"])
    badge = MagicMock()
    badge.id = "bot"
    payload = make_payload(content="wally salut", author_name="some_custom_bot", badges=[badge])
    await handle_message(bot, payload)
    bot.llm.complete.assert_not_awaited()
    bot.memory.append_prelude.assert_not_called()


@pytest.mark.asyncio
async def test_ignores_untriggered_messages(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=["wally"])
    payload = make_payload(content="hello friend")
    await handle_message(bot, payload)
    bot.llm.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_by_name_sends_reply(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=["wally"])
    payload = make_payload(content="wally qui es-tu?")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    bot.twitch_api.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_by_mention_sends_reply(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=[])
    payload = make_payload(content="@wallybot réponds!")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    bot.twitch_api.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_cooldown_prevents_second_response(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(cooldown_seconds=60)
    bot._cooldowns["111"] = time.time()
    payload = make_payload(content="wally salut")
    await handle_message(bot, payload)
    bot.llm.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_reply_truncated_at_480(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot()
    bot.llm.complete = AsyncMock(return_value="x" * 600)
    bot.llm.complete_with_tools = AsyncMock(return_value=("x" * 600, []))
    payload = make_payload(content="wally parle")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    sent_text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert len(sent_text) <= 480
    assert sent_text.endswith("...")


@pytest.mark.asyncio
async def test_appends_to_context_window(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot()
    payload = make_payload(content="wally test", author_name="bob", author_id="42")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    assert bot.memory.append_message.call_count == 2
    calls = bot.memory.append_message.call_args_list
    assert calls[0].args[1] == "bob"
    assert calls[1].args[1] == "Wally"


@pytest.mark.asyncio
async def test_sets_cooldown_after_response(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(cooldown_seconds=10)
    payload = make_payload(content="wally bonjour", author_id="789")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    assert "789" in bot._cooldowns


@pytest.mark.asyncio
async def test_handle_message_exception_is_caught(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot()
    bot.llm.complete = AsyncMock(side_effect=RuntimeError("OpenAI down"))
    bot.llm.complete_with_tools = AsyncMock(side_effect=RuntimeError("OpenAI down"))
    payload = make_payload(content="wally erreur")
    # Should not raise — exception is caught and logged
    await handle_message(bot, payload)
    bot.twitch_api.send_message.assert_not_awaited()


# ── _post_process ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_process_calls_emotion_and_trust():
    bot = make_bot()
    await _post_process(bot, "merci wally", "twitch", "111", 0.5)
    bot.emotion.process_message.assert_awaited_once_with(
        "merci wally", trust_score=0.5, context_messages=None,
        trigger_user="111", channel_id="", platform="twitch",
        user_id="111",
    )
    bot.db.update_trust_score.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_process_decreases_trust_on_insult():
    bot = make_bot()
    await _post_process(bot, "tu es un idiot", "twitch", "111", 0.5)
    call = bot.db.update_trust_score.call_args
    assert call.args[2] < 0


# ── _bits_joy ─────────────────────────────────────────────────────────────────

def test_bits_joy_small():
    assert _bits_joy(50) == 0.1


def test_bits_joy_medium():
    assert _bits_joy(100) == 0.3
    assert _bits_joy(500) == 0.3


def test_bits_joy_large():
    assert _bits_joy(1000) == 0.6
    assert _bits_joy(9999) == 0.6


@pytest.mark.asyncio
async def test_handle_message_increments_visit_msg_count(monkeypatch):
    """Un message sur une chaîne invitée active doit incrémenter msg_count."""
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot()
    bot.config.twitch.channel = "homechannel"
    bot._active_visits = {
        "guestchannel": {"visit_id": 1, "msg_count": 3, "joined_at": time.time() - 100}
    }
    payload = make_payload(content="salut !", author_name="viewer1",
                           author_id="200", channel="guestchannel")
    await handle_message(bot, payload)
    assert bot._active_visits["guestchannel"]["msg_count"] == 4
