import time
import hashlib
import pytest
from bot.db.database import Database


@pytest.fixture
async def db(tmp_path):
    d = await Database.create(str(tmp_path / "test.db"))
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_insert_and_load_chat_messages(db):
    now = time.time()
    msg_id = await db.insert_chat_message("discord:123", "Alice", "https://avatar", "Hello", False, now)
    assert isinstance(msg_id, int)
    messages = await db.load_chat_history(limit=10)
    assert len(messages) == 1
    assert messages[0]["sender_id"] == "discord:123"
    assert messages[0]["content"] == "Hello"
    assert messages[0]["is_wally"] == 0


@pytest.mark.asyncio
async def test_load_chat_history_respects_limit(db):
    now = time.time()
    for i in range(5):
        await db.insert_chat_message("discord:123", "Alice", None, f"msg{i}", False, now + i)
    messages = await db.load_chat_history(limit=3)
    assert len(messages) == 3
    assert messages[0]["content"] == "msg2"
    assert messages[2]["content"] == "msg4"


@pytest.mark.asyncio
async def test_insert_wally_message(db):
    now = time.time()
    await db.insert_chat_message("wally", "Wally", None, "Hey!", True, now)
    messages = await db.load_chat_history(limit=10)
    assert messages[0]["is_wally"] == 1
    assert messages[0]["sender_id"] == "wally"


@pytest.mark.asyncio
async def test_cleanup_old_chat_messages(db):
    old = time.time() - 31 * 86400
    recent = time.time()
    await db.insert_chat_message("discord:1", "A", None, "old", False, old)
    await db.insert_chat_message("discord:2", "B", None, "new", False, recent)
    await db.cleanup_old_chat_messages(days=30)
    messages = await db.load_chat_history(limit=100)
    assert len(messages) == 1
    assert messages[0]["content"] == "new"


@pytest.mark.asyncio
async def test_store_and_get_refresh_token(db):
    token = "random-uuid-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = time.time() + 3600
    await db.store_refresh_token(token_hash, "123", "Alice", "https://avatar", expires)
    result = await db.get_refresh_token(token_hash)
    assert result is not None
    assert result["discord_id"] == "123"


@pytest.mark.asyncio
async def test_get_refresh_token_expired_returns_none(db):
    token_hash = hashlib.sha256(b"expired").hexdigest()
    expired = time.time() - 1
    await db.store_refresh_token(token_hash, "123", "Alice", None, expired)
    result = await db.get_refresh_token(token_hash)
    assert result is None


@pytest.mark.asyncio
async def test_delete_refresh_token(db):
    token_hash = hashlib.sha256(b"to-delete").hexdigest()
    await db.store_refresh_token(token_hash, "123", "Alice", None, time.time() + 3600)
    await db.delete_refresh_token(token_hash)
    result = await db.get_refresh_token(token_hash)
    assert result is None
