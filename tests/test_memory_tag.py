import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_memory_config():
    config = MagicMock()
    config.bot.context_window_size = 20
    config.bot.prelude_window_size = 15
    config.bot.context_token_threshold = 3000
    return config


@pytest.mark.asyncio
async def test_memory_add_prefixes_emotion_tag():
    """Quand emotion_context est fourni, le contenu stocké est préfixé."""
    from bot.core.memory import MemoryService
    config = make_memory_config()
    memory = MemoryService(config)

    stored_content = []

    memory._init_mem0()
    memory._mem0 = MagicMock()
    memory._mem0.add = MagicMock(side_effect=lambda content, user_id: stored_content.append(content))

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        await memory.add("discord", "user1", "bonjour !", emotion_context="Wally: joy")

    assert len(stored_content) == 1
    assert stored_content[0].startswith("[Wally: joy]")
    assert "bonjour !" in stored_content[0]


@pytest.mark.asyncio
async def test_memory_add_no_tag_when_empty_context():
    """Quand emotion_context est vide, le contenu n'est pas modifié."""
    from bot.core.memory import MemoryService
    config = make_memory_config()
    memory = MemoryService(config)

    stored_content = []
    memory._init_mem0()
    memory._mem0 = MagicMock()
    memory._mem0.add = MagicMock(side_effect=lambda content, user_id: stored_content.append(content))

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        await memory.add("discord", "user1", "bonjour !", emotion_context="")

    assert len(stored_content) == 1
    assert stored_content[0] == "bonjour !"


@pytest.mark.asyncio
async def test_discord_handler_passes_emotion_tag_to_memory(tmp_path):
    """Le handler Discord passe le tag émotionnel à memory.add()."""
    from unittest.mock import AsyncMock, MagicMock, patch, call
    import discord

    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.discord.allowed_channels = []
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.8, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0}
    )
    bot.db.is_muted = AsyncMock(return_value=False)
    bot.db.is_welcomed = AsyncMock(return_value=True)
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.update_trust_score = AsyncMock()
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.openai.complete = AsyncMock(return_value="Réponse de Wally")
    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.memory.append_message = MagicMock()
    bot.memory.add = AsyncMock()
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.persona.build_prompt_block = MagicMock(return_value="")
    bot.persona.emotion_directives = {}
    bot.emotion.process_message = AsyncMock()

    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.author.id = 123
    message.author.display_name = "TestUser"
    message.content = "wally bonjour"
    message.channel.id = 999
    message.channel.typing = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
    )
    message.guild.id = 456
    message.guild.name = "TestServer"
    message.channel.name = "general"
    message.channel.__class__ = discord.TextChannel
    message.mentions = []
    message.add_reaction = AsyncMock()
    message.remove_reaction = AsyncMock()
    message.reply = AsyncMock()
    message.channel.send = AsyncMock()
    message.id = 1

    from bot.discord.handlers import handle_message
    await handle_message(bot, message)

    # Vérifier que memory.add a été appelé avec un emotion_context non vide
    assert bot.memory.add.called
    call_kwargs = bot.memory.add.call_args
    emotion_context = call_kwargs.kwargs.get("emotion_context", "")
    assert "joy" in emotion_context  # joy=0.8 ≥ 0.4 → dans le tag
