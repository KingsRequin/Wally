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


@pytest.mark.asyncio
async def test_list_memory_users_includes_trust_score():
    """list_memory_users retourne trust_score issu de trust_scores (JOIN)."""
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord")
    # Pas encore de trust score → défaut 0.5
    users = await db.list_memory_users()
    assert users[0]["trust_score"] == 0.5

    # Enregistrer un trust score pour alice
    await db.update_trust_score("discord", "alice", +0.3)
    users = await db.list_memory_users()
    assert users[0]["trust_score"] == round(0.5 + 0.3, 2)
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_trust_score_platform_isolated():
    """Le trust score n'est pas partagé entre discord et twitch pour un même pseudo."""
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:bob", "discord")
    await db.upsert_memory_user("twitch:bob", "twitch")
    await db.update_trust_score("discord", "bob", +0.2)
    users = {u["user_id"]: u for u in await db.list_memory_users()}
    assert users["discord:bob"]["trust_score"] == round(0.5 + 0.2, 2)
    assert users["twitch:bob"]["trust_score"] == 0.5  # Twitch inchangé
    await db.close()


@pytest.mark.asyncio
async def test_upsert_memory_user_stores_username():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord", username="Alice")
    users = await db.list_memory_users()
    assert users[0]["username"] == "Alice"
    await db.close()


@pytest.mark.asyncio
async def test_upsert_memory_user_preserves_username_when_empty():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:alice", "discord", username="Alice")
    await db.upsert_memory_user("discord:alice", "discord", username="")  # pas d'écrasement
    users = await db.list_memory_users()
    assert users[0]["username"] == "Alice"
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_filter_by_username():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:111", "discord", username="OlafMC")
    await db.upsert_memory_user("twitch:222", "twitch", username="StreamerXYZ")
    users = await db.list_memory_users(q="Olaf")
    assert len(users) == 1
    assert users[0]["username"] == "OlafMC"
    await db.close()


@pytest.mark.asyncio
async def test_list_memory_users_filter_by_user_id_still_works():
    db = await Database.create(":memory:")
    await db.upsert_memory_user("discord:111", "discord", username="OlafMC")
    users = await db.list_memory_users(q="discord:111")
    assert len(users) == 1
    await db.close()
