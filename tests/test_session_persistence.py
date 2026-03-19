# tests/test_session_persistence.py
"""Tests pour la persistence des sessions en SQLite."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.sessions import SessionManager, SESSION_TIMEOUT_SECONDS
from bot.db.database import Database


# ── Helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def db():
    """Crée une DB in-memory pour les tests."""
    database = await Database.create(":memory:")
    yield database
    await database.close()


def make_manager(db=None):
    memory = MagicMock()
    memory.add = AsyncMock()
    openai = MagicMock()
    openai.complete_secondary = AsyncMock(return_value="### Alice\n- aime Python")
    return SessionManager(memory=memory, openai=openai, db=db)


# ── DB methods ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_and_get_session_messages(db):
    """insert_session_message + get_recent_session_messages round-trip."""
    now = time.time()
    await db.insert_session_message("ch1", "discord", "u1", "Alice", "hello", now)
    await db.insert_session_message("ch1", "discord", "u2", "Bob", "hi", now + 1)

    rows = await db.get_recent_session_messages(now - 10)
    assert len(rows) == 2
    assert rows[0]["display_name"] == "Alice"
    assert rows[1]["display_name"] == "Bob"
    assert rows[0]["channel_id"] == "ch1"
    assert rows[0]["platform"] == "discord"


@pytest.mark.asyncio
async def test_get_recent_filters_old_messages(db):
    """Les messages plus anciens que `since` sont exclus."""
    old = time.time() - 3600
    recent = time.time()
    await db.insert_session_message("ch1", "discord", "u1", "Alice", "old", old)
    await db.insert_session_message("ch1", "discord", "u2", "Bob", "new", recent)

    rows = await db.get_recent_session_messages(recent - 10)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Bob"


@pytest.mark.asyncio
async def test_delete_session_messages(db):
    """delete_session_messages supprime uniquement le canal ciblé."""
    now = time.time()
    await db.insert_session_message("ch1", "discord", "u1", "Alice", "hello", now)
    await db.insert_session_message("ch2", "discord", "u2", "Bob", "hi", now)

    await db.delete_session_messages("ch1")

    rows = await db.get_recent_session_messages(now - 10)
    assert len(rows) == 1
    assert rows[0]["channel_id"] == "ch2"


# ── record_message persiste en DB ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_message_persists_to_db(db):
    """record_message écrit en DB via fire-and-forget."""
    mgr = make_manager(db=db)

    mgr.record_message("ch1", "discord", "u1", "Alice", "bonjour")

    # Laisser le fire-and-forget s'exécuter
    await asyncio.sleep(0.05)

    rows = await db.get_recent_session_messages(time.time() - 10)
    assert len(rows) == 1
    assert rows[0]["content"] == "bonjour"
    assert rows[0]["user_id"] == "u1"


@pytest.mark.asyncio
async def test_record_message_works_without_db():
    """record_message fonctionne même sans DB (db=None)."""
    mgr = make_manager(db=None)
    # Ne doit pas lever d'exception
    mgr.record_message("ch1", "discord", "u1", "Alice", "hello")
    assert "ch1" in mgr._sessions


# ── restore_sessions ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_sessions_rebuilds_from_db(db):
    """restore_sessions reconstruit les sessions depuis la DB."""
    now = time.time()
    await db.insert_session_message("ch1", "discord", "u1", "Alice", "msg1", now - 60)
    await db.insert_session_message("ch1", "discord", "u2", "Bob", "msg2", now - 30)
    await db.insert_session_message("ch2", "twitch", "u3", "Charlie", "yo", now - 10)

    mgr = make_manager(db=db)
    count = await mgr.restore_sessions()

    assert count == 2  # 2 canaux restaurés
    assert "ch1" in mgr._sessions
    assert "ch2" in mgr._sessions

    # Vérifier la session ch1
    s1 = mgr._sessions["ch1"]
    assert s1.platform == "discord"
    assert len(s1.messages) == 2
    assert s1.participants["u1"] == "Alice"
    assert s1.participants["u2"] == "Bob"
    assert s1.timeout_task is not None

    # Vérifier la session ch2
    s2 = mgr._sessions["ch2"]
    assert s2.platform == "twitch"
    assert len(s2.messages) == 1


@pytest.mark.asyncio
async def test_restore_sessions_ignores_expired(db):
    """Les messages trop anciens (> SESSION_TIMEOUT_SECONDS) ne sont pas restaurés."""
    old = time.time() - SESSION_TIMEOUT_SECONDS - 60  # expiré
    await db.insert_session_message("ch1", "discord", "u1", "Alice", "old msg", old)

    mgr = make_manager(db=db)
    count = await mgr.restore_sessions()

    assert count == 0
    assert "ch1" not in mgr._sessions


@pytest.mark.asyncio
async def test_restore_sessions_returns_zero_without_db():
    """restore_sessions retourne 0 quand db=None."""
    mgr = make_manager(db=None)
    count = await mgr.restore_sessions()
    assert count == 0


@pytest.mark.asyncio
async def test_restore_sessions_calculates_remaining_timeout(db):
    """Le timer restauré utilise le délai restant, pas le timeout complet."""
    # Message il y a 5 secondes → remaining ≈ SESSION_TIMEOUT_SECONDS - 5
    now = time.time()
    await db.insert_session_message("ch1", "discord", "u1", "Alice", "recent", now - 5)

    mgr = make_manager(db=db)

    with patch("bot.core.sessions.SessionManager._wait_and_close", new_callable=AsyncMock) as mock_wait:
        # Empêcher le vrai sleep
        await mgr.restore_sessions()
        # Vérifier que le délai passé est bien ~SESSION_TIMEOUT_SECONDS - 5
        call_args = mock_wait.call_args
        delay = call_args[0][1]
        assert SESSION_TIMEOUT_SECONDS - 10 < delay < SESSION_TIMEOUT_SECONDS


# ── _wait_and_close nettoie la DB ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wait_and_close_cleans_db_after_analysis(db):
    """Après analyse de session, les messages sont supprimés de la DB."""
    mgr = make_manager(db=db)
    now = time.time()

    # Insérer des messages en DB
    await db.insert_session_message("ch1", "discord", "u1", "Alice", "msg1", now)
    await db.insert_session_message("ch1", "discord", "u2", "Bob", "msg2", now + 1)

    # Enregistrer les messages (crée la session in-memory)
    mgr.record_message("ch1", "discord", "u1", "Alice", "msg1")
    mgr.record_message("ch1", "discord", "u2", "Bob", "msg2")
    await asyncio.sleep(0.05)

    # Simuler le timeout (appeler _wait_and_close avec délai 0)
    await mgr._wait_and_close("ch1", 0)

    # Laisser _analyze_and_cleanup s'exécuter
    await asyncio.sleep(0.1)

    # Les messages doivent être supprimés de la DB
    rows = await db.get_recent_session_messages(now - 10)
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_wait_and_close_cleans_db_for_short_session(db):
    """Même une session < 2 messages nettoie la DB."""
    mgr = make_manager(db=db)
    now = time.time()

    await db.insert_session_message("ch1", "discord", "u1", "Alice", "seul msg", now)
    mgr.record_message("ch1", "discord", "u1", "Alice", "seul msg")
    await asyncio.sleep(0.05)

    await mgr._wait_and_close("ch1", 0)

    rows = await db.get_recent_session_messages(now - 10)
    assert len(rows) == 0
