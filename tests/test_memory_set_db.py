import asyncio
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

    db.upsert_memory_user.assert_called_once_with("discord:123", "discord", "")


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


@pytest.mark.asyncio
async def test_append_message_writes_to_daily_log(tmp_path):
    """append_message doit écrire dans daily_log quand un db est injecté."""
    from bot.core.memory import MemoryService
    from bot.db.database import Database

    config = MagicMock()
    config.bot.context_window_size = 50
    config.bot.prelude_window_size = 10

    db = await Database.create(str(tmp_path / "test.db"))
    memory = MemoryService(config)
    memory.set_db(db)

    memory.append_message("ch1", "Alice", "Bonjour !")
    memory.append_message("ch1", "Wally", "Salut !")

    # Les tâches fire-and-forget sont planifiées mais pas encore exécutées —
    # on cède le contrôle à la boucle d'événements pour les laisser tourner.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    rows = await db.get_today_messages()
    assert len(rows) == 2
    assert rows[0]["author"] == "Alice"
    assert rows[0]["content"] == "Bonjour !"
    assert rows[1]["author"] == "Wally"
    await db.close()


@pytest.mark.asyncio
async def test_append_message_no_db_does_not_crash():
    """append_message sans db injecté ne doit pas lever d'exception."""
    config = MagicMock()
    config.bot.context_window_size = 50
    config.bot.prelude_window_size = 10

    memory = MemoryService(config)  # pas de set_db()
    memory.append_message("ch1", "Alice", "Test")  # doit fonctionner sans erreur
