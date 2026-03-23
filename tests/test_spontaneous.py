# tests/test_spontaneous.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.discord.handlers import _check_spontaneous_trigger


def test_passion_keyword_bouchon():
    result = _check_spontaneous_trigger("j'ai trouvé un bouchon rare", curiosity=0.0, anger=0.0, boredom=0.0)
    assert result == "passion"


def test_aversion_keyword_ananas():
    result = _check_spontaneous_trigger("qui veut de la pizza ananas ?", curiosity=0.0, anger=0.0, boredom=0.0)
    assert result == "passion"


def test_no_keyword_no_emotion():
    result = _check_spontaneous_trigger("je vais au magasin", curiosity=0.0, anger=0.0, boredom=0.0)
    assert result is None


def test_emotion_curiosity_high():
    result = _check_spontaneous_trigger("je vais au magasin", curiosity=0.6, anger=0.0, boredom=0.0)
    assert result == "emotion"


def test_emotion_boredom_high():
    result = _check_spontaneous_trigger("salut", curiosity=0.0, anger=0.0, boredom=0.7)
    assert result == "emotion"


def test_emotion_anger_high():
    result = _check_spontaneous_trigger("blabla", curiosity=0.0, anger=0.7, boredom=0.0)
    assert result == "emotion"


def test_emotion_below_threshold():
    result = _check_spontaneous_trigger("blabla", curiosity=0.4, anger=0.3, boredom=0.2)
    assert result is None


def test_passion_takes_priority_over_emotion():
    """If both passion keyword and emotion match, return passion."""
    result = _check_spontaneous_trigger("ce bouchon est incroyable", curiosity=0.8, anger=0.0, boredom=0.0)
    assert result == "passion"


# ── Helpers for memory recall tests ──────────────────────────────────────


def _make_msg(content="je vais lancer une partie"):
    """Helper to build a minimal discord.Message-like mock."""
    msg = MagicMock()
    msg.content = content
    msg.author.id = 12345
    msg.author.bot = False
    msg.author.display_name = "TestUser"
    msg.guild = MagicMock()
    msg.guild.id = 99999
    msg.guild.name = "TestServer"
    msg.channel = MagicMock()
    msg.channel.id = 777
    msg.channel.name = "general"
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.reply = AsyncMock()
    msg.add_reaction = AsyncMock()
    return msg


def make_bot_for_spontaneous():
    bot = MagicMock()
    bot.config.bot.spontaneous_memory_probability = 0.2
    bot.config.bot.memory_recall_min_score = 0.75
    bot.config.bot.spontaneous_cooldown_seconds = 300
    bot.config.bot.spontaneous_discord_enabled = True
    bot.config.bot.spontaneous_probability = 0.05
    bot.config.bot.spontaneous_passion_probability = 0.15
    bot.config.discord.allowed_channels = []
    bot.config.discord.emoji_reaction_probability = 0.0
    bot.config.discord.spam_detection.enabled = False
    bot.user = MagicMock()
    bot.memory.search_top_match = AsyncMock(return_value=None)
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.memory.append_message = MagicMock()
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    bot.prompts.build_system_prompt = MagicMock(return_value="system prompt")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.llm.complete = AsyncMock(return_value="Ah oui, ça me rappelle!")
    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="persona")
    return bot


@pytest.mark.asyncio
async def test_spontaneous_memory_trigger_fires():
    """Full handler flow: memory recall triggers _fire when score >= threshold."""
    from bot.discord import handlers
    from bot.discord.handlers import handle_message

    bot = make_bot_for_spontaneous()
    bot.memory.search_top_match = AsyncMock(return_value=("joue à Apex", 0.85))
    msg = _make_msg("je vais lancer une partie")

    handlers._spontaneous_cooldowns.clear()
    handlers._memory_check_cooldowns.clear()
    with patch("bot.discord.handlers.random") as mock_random, \
         patch("bot.discord.handlers._fire") as mock_fire:
        mock_random.random.return_value = 0.1  # < 0.2 probability
        await handle_message(bot, msg)
        assert mock_fire.called


@pytest.mark.asyncio
async def test_spontaneous_memory_below_threshold():
    """No _fire when memory score is below memory_recall_min_score."""
    from bot.discord import handlers
    from bot.discord.handlers import handle_message

    bot = make_bot_for_spontaneous()
    bot.memory.search_top_match = AsyncMock(return_value=("some memory", 0.5))
    msg = _make_msg("je vais au magasin")

    handlers._spontaneous_cooldowns.clear()
    handlers._memory_check_cooldowns.clear()
    with patch("bot.discord.handlers.random") as mock_random, \
         patch("bot.discord.handlers._fire") as mock_fire:
        mock_random.random.return_value = 0.1
        await handle_message(bot, msg)
        assert not mock_fire.called


@pytest.mark.asyncio
async def test_spontaneous_memory_probability_blocks():
    """No _fire when random exceeds spontaneous_memory_probability."""
    from bot.discord import handlers
    from bot.discord.handlers import handle_message

    bot = make_bot_for_spontaneous()
    bot.memory.search_top_match = AsyncMock(return_value=("joue à Apex", 0.85))
    msg = _make_msg("je vais lancer une partie")

    handlers._spontaneous_cooldowns.clear()
    handlers._memory_check_cooldowns.clear()
    with patch("bot.discord.handlers.random") as mock_random, \
         patch("bot.discord.handlers._fire") as mock_fire:
        mock_random.random.return_value = 0.9  # > 0.2 → blocked
        await handle_message(bot, msg)
        assert not mock_fire.called


@pytest.mark.asyncio
async def test_spontaneous_memory_cooldown():
    """Memory recall respects the spontaneous cooldown."""
    from bot.discord import handlers
    from bot.discord.handlers import handle_message
    import time as _time

    bot = make_bot_for_spontaneous()
    bot.memory.search_top_match = AsyncMock(return_value=("joue à Apex", 0.85))
    msg = _make_msg("je vais lancer une partie")

    handlers._spontaneous_cooldowns["777"] = _time.time()  # cooldown active
    handlers._memory_check_cooldowns.clear()

    with patch("bot.discord.handlers.random") as mock_random, \
         patch("bot.discord.handlers._fire") as mock_fire:
        mock_random.random.return_value = 0.1
        await handle_message(bot, msg)
        assert not mock_fire.called
        bot.memory.search_top_match.assert_not_called()


@pytest.mark.asyncio
async def test_spontaneous_respond_with_memory_injects_recall():
    """_spontaneous_respond injects memory recall into user_content."""
    from bot.discord.handlers import _spontaneous_respond
    bot = make_bot_for_spontaneous()
    msg = _make_msg("je vais lancer une partie")

    await _spontaneous_respond(bot, msg, recall_memory="joue à Apex")

    complete_call = bot.llm.complete.call_args
    user_content = complete_call.args[1][0]["content"]
    assert "Souvenir qui te revient" in user_content
    prompt_kwargs = bot.prompts.build_system_prompt.call_args.kwargs
    assert prompt_kwargs.get("memory_context") == "joue à Apex"


@pytest.mark.asyncio
async def test_spontaneous_respond_without_memory():
    """_spontaneous_respond works normally without recall_memory (regression)."""
    from bot.discord.handlers import _spontaneous_respond
    bot = make_bot_for_spontaneous()
    msg = _make_msg("bouchon")

    await _spontaneous_respond(bot, msg)

    complete_call = bot.llm.complete.call_args
    user_content = complete_call.args[1][0]["content"]
    assert "Souvenir qui te revient" not in user_content


@pytest.mark.asyncio
async def test_spontaneous_memory_twitch():
    """Memory recall works on Twitch handler."""
    from bot.twitch.handlers import _spontaneous_respond_twitch
    bot = make_bot_for_spontaneous()
    bot._channel_ids = {"testchannel": "123"}
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=mock_channel)

    await _spontaneous_respond_twitch(
        bot, "testchannel", "123", "TestUser", "je vais jouer",
        recall_memory="joue à Apex",
    )

    complete_call = bot.llm.complete.call_args
    user_content = complete_call.args[1][0]["content"]
    assert "Souvenir qui te revient" in user_content
