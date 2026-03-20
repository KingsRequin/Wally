# tests/test_db_aliases.py
"""Tests for user_aliases table and related DB methods."""
import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_upsert_and_get_alias(tmp_path):
    """Insert and retrieve an alias."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_alias("johnnie", "discord:123", "Johnnie Walker", "manual", 1.0)
    aliases = await db.list_aliases(canonical_uid="discord:123")
    assert len(aliases) == 1
    a = aliases[0]
    assert a["nickname"] == "johnnie"
    assert a["canonical_uid"] == "discord:123"
    assert a["display_name"] == "Johnnie Walker"
    assert a["source"] == "manual"
    assert a["confidence"] == pytest.approx(1.0)
    await db.close()


@pytest.mark.asyncio
async def test_manual_alias_not_overwritten_by_llm(tmp_path):
    """A manual alias is NOT overwritten when source=llm tries to update it."""
    db = await Database.create(str(tmp_path / "test.db"))
    # First insert as manual
    await db.upsert_alias("johnnie", "discord:123", "Johnnie Walker", "manual", 1.0)
    # LLM tries to overwrite with a different canonical_uid and lower confidence
    await db.upsert_alias("johnnie", "discord:999", "Someone Else", "llm", 0.6)
    aliases = await db.list_aliases()
    assert len(aliases) == 1
    a = aliases[0]
    # Should still point to original manual entry
    assert a["canonical_uid"] == "discord:123"
    assert a["source"] == "manual"
    assert a["display_name"] == "Johnnie Walker"
    await db.close()


@pytest.mark.asyncio
async def test_delete_alias(tmp_path):
    """Delete an alias by nickname."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_alias("johnnie", "discord:123", "Johnnie Walker", "manual", 1.0)
    await db.delete_alias("johnnie")
    aliases = await db.list_aliases()
    assert len(aliases) == 0
    await db.close()


@pytest.mark.asyncio
async def test_get_alias_map(tmp_path):
    """get_nickname_alias_map returns {nickname: canonical_uid} dict."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_alias("johnnie", "discord:123", "Johnnie Walker", "manual", 1.0)
    await db.upsert_alias("jo", "discord:123", "Jo", "llm", 0.8)
    await db.upsert_alias("bigbob", "discord:456", "Bob", "llm", 0.7)
    alias_map = await db.get_nickname_alias_map()
    assert alias_map["johnnie"] == "discord:123"
    assert alias_map["jo"] == "discord:123"
    assert alias_map["bigbob"] == "discord:456"
    await db.close()


@pytest.mark.asyncio
async def test_list_unresolved_aliases(tmp_path):
    """list_unresolved_aliases returns memory_users with user_id LIKE 'unknown:%'."""
    db = await Database.create(str(tmp_path / "test.db"))
    # Insert a known user and an unknown user into memory_users
    await db.upsert_memory_user("discord:123", "discord", "Johnnie")
    await db.upsert_memory_user("unknown:some_nickname", "unknown", "someone")
    unresolved = await db.list_unresolved_aliases()
    assert len(unresolved) == 1
    assert unresolved[0]["user_id"] == "unknown:some_nickname"
    await db.close()


@pytest.mark.asyncio
async def test_session_messages_has_is_reply(tmp_path):
    """Verify is_reply column exists in session_messages after migration."""
    db = await Database.create(str(tmp_path / "test.db"))
    # Attempt to insert with is_reply — should not raise
    await db._conn.execute(
        "INSERT INTO session_messages "
        "(channel_id, platform, user_id, display_name, content, timestamp, is_reply) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("chan1", "discord", "discord:123", "Johnnie", "hello", 1700000000.0, 1),
    )
    await db._conn.commit()
    cursor = await db._conn.execute(
        "SELECT is_reply FROM session_messages WHERE channel_id = 'chan1'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["is_reply"] == 1
    await db.close()
