# tests/test_memory_alias.py
"""Tests pour l'alias cache dans MemoryService."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_config():
    config = MagicMock()
    config.bot.context_window_size = 20
    config.bot.prelude_window_size = 15
    config.bot.context_token_threshold = 3000
    config.bot.link_min_confidence = 0.75
    return config


@pytest.mark.asyncio
async def test_load_aliases_populates_cache():
    """load_aliases charge le dict d'alias depuis la DB."""
    from bot.intelligence.memory.service import MemoryService
    config = make_config()
    memory = MemoryService(config)

    db = MagicMock()
    db.get_alias_map = AsyncMock(return_value={"twitch:kingsrequin_ttv": "discord:123456789"})

    await memory.load_aliases(db)

    assert memory._alias_cache == {"twitch:kingsrequin_ttv": "discord:123456789"}


def test_user_id_resolves_alias():
    """_user_id retourne le canonical_id quand un alias est connu."""
    from bot.intelligence.memory.service import MemoryService
    config = make_config()
    memory = MemoryService(config)
    memory._alias_cache = {"twitch:kingsrequin_ttv": "discord:123456789"}

    result = memory._user_id("twitch", "kingsrequin_ttv")
    assert result == "discord:123456789"


def test_user_id_passthrough_when_no_alias():
    """_user_id retourne platform:user_id quand pas d'alias."""
    from bot.intelligence.memory.service import MemoryService
    config = make_config()
    memory = MemoryService(config)

    # Use a realistic Discord snowflake (17+ digits)
    result = memory._user_id("discord", "610550333042589752")
    assert result == "discord:610550333042589752"


@pytest.mark.asyncio
async def test_load_aliases_handles_db_error():
    """load_aliases ne crash pas si la DB échoue."""
    from bot.intelligence.memory.service import MemoryService
    config = make_config()
    memory = MemoryService(config)

    db = MagicMock()
    db.get_alias_map = AsyncMock(side_effect=Exception("DB error"))

    # Ne doit pas lever d'exception
    await memory.load_aliases(db)
    assert memory._alias_cache == {}
