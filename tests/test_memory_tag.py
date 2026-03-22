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
    memory._mem0.add = MagicMock(side_effect=lambda content, user_id, **kwargs: stored_content.append(content))

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
    memory._mem0.add = MagicMock(side_effect=lambda content, user_id, **kwargs: stored_content.append(content))

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        await memory.add("discord", "user1", "bonjour !", emotion_context="")

    assert len(stored_content) == 1
    assert stored_content[0] == "bonjour !"


@pytest.mark.asyncio
async def test_discord_handler_updates_context_window(tmp_path):
    """Le handler Discord met à jour la fenêtre de contexte après une réponse.

    memory.add() (mémoire long-terme) est appelé par le FactExtractor après
    analyse du buffer, pas directement dans le handler. Ce test vérifie le comportement
    réel : append_message est appelé pour le message utilisateur et la réponse,
    et l'état émotionnel est utilisé pour construire le prompt.
    """
    from unittest.mock import AsyncMock, MagicMock
    import discord

    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.discord.allowed_channels = []
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10
    bot.config.discord.spam_detection.enabled = False

    emotion_state = {"anger": 0.0, "joy": 0.8, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0}
    bot.emotion.get_state = MagicMock(return_value=emotion_state)
    bot.db.is_muted = AsyncMock(return_value=False)
    bot.db.is_welcomed = AsyncMock(return_value=True)
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.update_trust_score = AsyncMock()
    bot.db.update_love_score = AsyncMock()
    bot.db.get_love_score = AsyncMock(return_value=0.0)
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.config.bot.love_decay_lambda = 0.02
    bot.openai.complete = AsyncMock(return_value="Réponse de Wally")
    bot.memory.search = AsyncMock(return_value="")
    bot.memory.search_global = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.memory.append_message = MagicMock()
    bot.memory.get_pending_question_directive = AsyncMock(return_value="")
    bot.db.get_last_interaction = AsyncMock(return_value=None)
    bot.db.get_recent_jokes = AsyncMock(return_value=[])
    bot.db.get_opinions = AsyncMock(return_value=[])
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.persona.build_prompt_block = MagicMock(return_value="")
    bot.persona.emotion_directives = {}
    bot.emotion.process_message = AsyncMock()
    bot.fact_extractor = MagicMock()
    bot.web_search = None
    bot.apex_api = None

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

    # La fenêtre de contexte est mise à jour pour le message user + la réponse
    assert bot.memory.append_message.call_count >= 2

    # L'état émotionnel est passé à build_system_prompt
    bot.prompts.build_system_prompt.assert_called_once()
    call_kwargs = bot.prompts.build_system_prompt.call_args
    assert call_kwargs.kwargs["emotion_state"] == emotion_state

    # memory.add() ne doit pas être appelé directement depuis le handler
    bot.memory.add.assert_not_called()

    # Le FactExtractor enregistre le message pour l'analyse
    bot.fact_extractor.record_message.assert_called_once()
