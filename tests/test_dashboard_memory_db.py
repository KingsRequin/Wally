import asyncio

import pytest

from bot.db.database import Database


@pytest.mark.asyncio
async def test_upsert_memory_user_creates_entry():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:123", "discord")
    users = await db.list_memory_users()
    assert len(users) == 1
    assert users[0]["user_id"] == "discord:123"
    assert users[0]["platform"] == "discord"
    assert users[0]["last_updated"] > 0
    await db.close()


@pytest.mark.asyncio
async def test_upsert_memory_user_updates_last_updated():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:123", "discord")
    t1 = (await db.list_memory_users())[0]["last_updated"]
    await asyncio.sleep(0.01)
    await db.upsert_memory_user("discord:123", "discord")
    t2 = (await db.list_memory_users())[0]["last_updated"]
    assert t2 >= t1
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_no_filter():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord")
    await db.upsert_memory_user("twitch:bob", "twitch")
    users = await db.list_memory_users()
    assert len(users) == 2
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_with_filter():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord")
    await db.upsert_memory_user("twitch:bob", "twitch")
    users = await db.list_memory_users(q="discord")
    assert len(users) == 1
    assert users[0]["user_id"] == "discord:alice"
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_empty():
    db = await Database.create(":memory:")
    users = await db.list_memory_users()
    assert users == []
    await db.close()
