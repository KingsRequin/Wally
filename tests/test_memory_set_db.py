import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.memory import MemoryService


def _make_config():
    cfg = MagicMock()
    cfg.bot.context_window_size = 10
    cfg.bot.prelude_window_size = 5
    cfg.bot.context_token_threshold = 2000
    cfg.openai.secondary_model = "gpt-4o-mini"
    return cfg


def test_set_db_stores_reference():
    svc = MemoryService(_make_config())
    db = AsyncMock()
    svc.set_db(db)
    assert svc._db is db


def test_db_is_none_by_default():
    svc = MemoryService(_make_config())
    assert svc._db is None


@pytest.mark.asyncio
async def test_add_calls_upsert_when_db_set():
    svc = MemoryService(_make_config())
    db = AsyncMock()
    svc.set_db(db)

    mock_mem0 = MagicMock()
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    with patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
        await svc.add("discord", "123", "test content")

    db.upsert_memory_user.assert_called_once_with("discord:123", "discord")


@pytest.mark.asyncio
async def test_add_skips_upsert_when_no_db():
    svc = MemoryService(_make_config())
    # no set_db() called

    mock_mem0 = MagicMock()
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    with patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
        await svc.add("discord", "123", "content")
    # implicit: no crash


@pytest.mark.asyncio
async def test_add_skips_upsert_when_mem0_none():
    svc = MemoryService(_make_config())
    db = AsyncMock()
    svc.set_db(db)
    svc._mem0 = None
    svc._mem0_init_attempted = True

    await svc.add("discord", "123", "content")
    db.upsert_memory_user.assert_not_called()
