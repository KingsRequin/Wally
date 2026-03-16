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
