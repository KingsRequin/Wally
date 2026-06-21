import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.intelligence.memory.service import MemoryService


def _make_config():
    cfg = MagicMock()
    cfg.bot.context_window_size = 10
    cfg.bot.prelude_window_size = 5
    cfg.bot.context_token_threshold = 2000
    cfg.bot.memory_search_min_score = 0.5
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
async def test_add_skips_upsert_when_no_db():
    svc = MemoryService(_make_config())
    # no set_db() called

    svc._store_init_attempted = True
    svc._store = AsyncMock()
    svc._store.upsert = AsyncMock(return_value="point-uuid")
    svc._store.get_all = AsyncMock(return_value=[])

    await svc.add("discord", "610550333042589752", "content")
    # implicit: no crash


@pytest.mark.asyncio
async def test_add_skips_upsert_when_store_none():
    svc = MemoryService(_make_config())
    db = AsyncMock()
    svc.set_db(db)
    svc._store = None
    svc._store_init_attempted = True

    await svc.add("discord", "610550333042589752", "content")
    db.upsert_memory_user.assert_not_called()


@pytest.mark.asyncio
async def test_append_message_writes_to_daily_log(tmp_path):
    """append_message doit écrire dans daily_log quand un db est injecté."""
    from bot.intelligence.memory.service import MemoryService
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
