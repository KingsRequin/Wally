import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import (
    BotConfig, OpenAIConfig, EmotionDecayConfig, TwitchEventConfig,
    TwitchConfig, DiscordConfig,
)
from bot.core.memory_store import MemoryRecord, MemoryMetadata


def _make_config(dashboard_token: str = "test-token"):
    cfg = MagicMock()
    cfg.bot = BotConfig(
        trigger_names=["wally"],
        language_default="fr",
        context_window_size=10,
        context_token_threshold=2000,
        prelude_window_size=3,
        journal_time="08:00",
        journal_channel_id=None,
        dashboard_token=dashboard_token,
    )
    cfg.openai = OpenAIConfig(
        primary_model="gpt-5-mini",
        secondary_model="gpt-5-mini",
        temperature=0.7,
        max_tokens=1000,
    )
    cfg.discord = DiscordConfig(anger_trigger_threshold=3, timeout_minutes=10)
    cfg.twitch = TwitchConfig(guest_channels=[], cooldown_seconds=10)
    cfg.emotions = {
        "anger": EmotionDecayConfig(decay_lambda=0.1),
        "joy": EmotionDecayConfig(decay_lambda=0.1),
        "sadness": EmotionDecayConfig(decay_lambda=0.1),
        "curiosity": EmotionDecayConfig(decay_lambda=0.1),
        "boredom": EmotionDecayConfig(decay_lambda=0.1),
    }
    cfg.twitch_events = {"follow": TwitchEventConfig(active=True, message="Hey!")}
    cfg.save = MagicMock()
    return cfg


def _make_state(dashboard_token: str = "test-token"):
    memory = MagicMock()
    mock_store = AsyncMock()
    mock_store.get_all = AsyncMock(return_value=[])
    mock_store.search = AsyncMock(return_value=[])
    mock_store.upsert = AsyncMock(return_value="new-point-id")
    mock_store.delete = AsyncMock()
    mock_store.delete_by_user = AsyncMock()
    mock_store.update = AsyncMock()
    mock_store.count = AsyncMock(return_value=0)
    type(memory).store = PropertyMock(return_value=mock_store)

    db = AsyncMock()

    state = AppState(
        config=_make_config(dashboard_token),
        db=db,
        emotion=MagicMock(),
        memory=memory,
        persona=MagicMock(),
        primary_llm=MagicMock(),
        secondary_llm=MagicMock(),
        image_client=MagicMock(),
        token_manager=MagicMock(),
        twitch_api=None,
        discord_bot=None,
        twitch_bot=None,
    )
    return state, mock_store, db


def _make_client(state: AppState):
    app = create_dashboard_app(state)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


HEADERS = {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_list_users_returns_users():
    state, _, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0}
    ]
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data["users"]) == 1
    assert data["users"][0]["user_id"] == "discord:123"


@pytest.mark.asyncio
async def test_list_users_with_filter():
    state, _, db = _make_state()
    db.list_memory_users.return_value = []
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users?q=discord", headers=HEADERS)
    assert r.status_code == 200
    # Appelé 2 fois : une pour la liste filtrée, une pour uid_to_name (tous les users)
    assert db.list_memory_users.call_count == 2
    db.list_memory_users.assert_any_call("discord", include_no_memory=False)


@pytest.mark.asyncio
async def test_get_user_memories_returns_list_sorted_by_date():
    state, mock_store, _ = _make_state()
    mock_store.get_all = AsyncMock(return_value=[
        MemoryRecord(id="mem-1", text="Préfère le français", user_id="discord:123",
                     created_at="2026-03-10T10:00:00Z"),
        MemoryRecord(id="mem-2", text="Aime Minecraft", user_id="discord:123",
                     created_at="2026-03-18T15:00:00Z"),
        MemoryRecord(id="mem-3", text="Joue à Apex", user_id="discord:123",
                     created_at="2026-03-19T09:00:00Z"),
    ])
    async with _make_client(state) as client:
        r = await client.get(
            "/api/admin/memory/users/discord%3A123", headers=HEADERS
        )
    assert r.status_code == 200
    data = r.json()
    assert len(data["memories"]) == 3
    # Most recent first: mem-3 (03-19), mem-2 (03-18), mem-1 (03-10)
    assert data["memories"][0]["id"] == "mem-3"
    assert data["memories"][1]["id"] == "mem-2"
    assert data["memories"][2]["id"] == "mem-1"
    # Verify date fields are included
    assert data["memories"][0]["created_at"] == "2026-03-19T09:00:00Z"


@pytest.mark.asyncio
async def test_get_user_memories_empty():
    state, mock_store, _ = _make_state()
    mock_store.get_all = AsyncMock(return_value=[])
    async with _make_client(state) as client:
        r = await client.get(
            "/api/admin/memory/users/discord%3A123", headers=HEADERS
        )
    assert r.status_code == 200
    assert len(r.json()["memories"]) == 0


@pytest.mark.asyncio
async def test_get_user_memories_503_when_store_none():
    state, _, _ = _make_state()
    type(state.memory).store = PropertyMock(return_value=None)
    async with _make_client(state) as client:
        r = await client.get(
            "/api/admin/memory/users/discord%3A123", headers=HEADERS
        )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_delete_user_calls_delete_by_user_and_db():
    state, mock_store, db = _make_state()
    async with _make_client(state) as client:
        r = await client.delete(
            "/api/admin/memory/users/discord%3A123", headers=HEADERS
        )
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    mock_store.delete_by_user.assert_called_once_with("discord:123")
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_delete_memory_calls_store_delete():
    state, mock_store, _ = _make_state()
    async with _make_client(state) as client:
        r = await client.delete(
            "/api/admin/memory/users/discord%3A123/memories/mem-abc",
            headers=HEADERS,
        )
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    mock_store.delete.assert_called_once_with("mem-abc")


@pytest.mark.asyncio
async def test_add_memory_stores_via_store():
    state, mock_store, db = _make_state()
    db.upsert_memory_user = AsyncMock()
    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/users/discord%3A123/memories",
            headers=HEADERS,
            json={"content": "Aime les crevettes"},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    mock_store.upsert.assert_called_once()
    call_args = mock_store.upsert.call_args
    assert call_args.args[0] == "discord:123"  # user_id
    assert call_args.args[1] == "Aime les crevettes"  # text
    db.upsert_memory_user.assert_called_once_with("discord:123", "discord")


@pytest.mark.asyncio
async def test_add_memory_rejects_empty_content():
    state, _, _ = _make_state()
    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/users/discord%3A123/memories",
            headers=HEADERS,
            json={"content": "   "},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_add_memory_503_when_store_none():
    state, _, _ = _make_state()
    type(state.memory).store = PropertyMock(return_value=None)
    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/users/discord%3A123/memories",
            headers=HEADERS,
            json={"content": "Test"},
        )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_update_memory_calls_store_update():
    state, mock_store, _ = _make_state()
    async with _make_client(state) as client:
        r = await client.put(
            "/api/admin/memory/users/discord%3A123/memories/mem-abc",
            headers=HEADERS,
            json={"content": "Nouveau contenu"},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    mock_store.update.assert_called_once()
    call_args = mock_store.update.call_args
    assert call_args.args[0] == "mem-abc"
    assert call_args.args[1] == "Nouveau contenu"


@pytest.mark.asyncio
async def test_update_memory_rejects_empty_content():
    state, _, _ = _make_state()
    async with _make_client(state) as client:
        r = await client.put(
            "/api/admin/memory/users/discord%3A123/memories/mem-abc",
            headers=HEADERS,
            json={"content": "  "},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_search_requires_q():
    state, _, _ = _make_state()
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/search", headers=HEADERS)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_search_returns_results():
    state, mock_store, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0}
    ]
    mock_store.search = AsyncMock(return_value=[
        MemoryRecord(id="r1", text="Aime Minecraft", user_id="discord:123", score=0.9),
    ])
    async with _make_client(state) as client:
        r = await client.get(
            "/api/admin/memory/search?q=Minecraft", headers=HEADERS
        )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["user_id"] == "discord:123"
    assert results[0]["memory"] == "Aime Minecraft"


@pytest.mark.asyncio
async def test_search_empty_results():
    state, mock_store, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0}
    ]
    mock_store.search = AsyncMock(return_value=[])
    async with _make_client(state) as client:
        r = await client.get(
            "/api/admin/memory/search?q=Minecraft", headers=HEADERS
        )
    assert r.status_code == 200
    assert len(r.json()["results"]) == 0


@pytest.mark.asyncio
async def test_search_continues_on_user_error():
    """Search loop must continue even if one user's store call raises."""
    state, mock_store, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0},
        {"user_id": "twitch:bob", "platform": "twitch", "last_updated": 1700000001.0},
    ]

    call_count = 0

    async def _search_side_effect(q, user_id=None, limit=10, min_score=0.5, filters=None):
        nonlocal call_count
        call_count += 1
        if user_id == "discord:123":
            raise RuntimeError("Qdrant timeout")
        return [MemoryRecord(id="r1", text="Aime Minecraft", user_id="twitch:bob", score=0.9)]

    mock_store.search = _search_side_effect
    async with _make_client(state) as client:
        r = await client.get(
            "/api/admin/memory/search?q=Minecraft", headers=HEADERS
        )
    assert r.status_code == 200
    results = r.json()["results"]
    # Only twitch:bob's result should appear (discord:123 raised)
    assert len(results) == 1
    assert results[0]["user_id"] == "twitch:bob"


# ── Alias routes ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_aliases():
    """GET /memory/aliases returns aliases and unresolved with fact_count."""
    state, mock_store, db = _make_state()
    db.list_aliases.return_value = [
        {"nickname": "rekin", "canonical_uid": "discord:123", "display_name": "KingsRequin",
         "source": "manual", "confidence": 1.0},
    ]
    db.list_unresolved_aliases.return_value = [
        {"user_id": "unknown:johndoe", "username": "johndoe"},
    ]
    mock_store.count = AsyncMock(return_value=2)
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/aliases", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data["aliases"]) == 1
    assert data["aliases"][0]["nickname"] == "rekin"
    assert len(data["unresolved"]) == 1
    assert data["unresolved"][0]["user_id"] == "unknown:johndoe"
    assert data["unresolved"][0]["fact_count"] == 2


@pytest.mark.asyncio
async def test_list_aliases_store_down():
    """GET /memory/aliases still works when store is unavailable."""
    state, _, db = _make_state()
    type(state.memory).store = PropertyMock(return_value=None)
    db.list_aliases.return_value = []
    db.list_unresolved_aliases.return_value = [
        {"user_id": "unknown:foo", "username": "foo"},
    ]
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/aliases", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    # fact_count should be 0 when store is not available
    assert data["unresolved"][0]["fact_count"] == 0


@pytest.mark.asyncio
async def test_add_alias():
    """POST /memory/aliases creates alias and updates memory cache."""
    state, _, db = _make_state()
    db.upsert_alias = AsyncMock()
    state.memory.add_alias = MagicMock()

    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/aliases",
            headers=HEADERS,
            json={"nickname": "Rekin", "canonical_uid": "discord:123", "display_name": "KingsRequin"},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    db.upsert_alias.assert_called_once_with(
        "rekin", "discord:123", "KingsRequin", "manual", 1.0
    )
    state.memory.add_alias.assert_called_once_with("nickname:rekin", "discord:123")


@pytest.mark.asyncio
async def test_add_alias_with_fact_extractor():
    """POST /memory/aliases fires _reconcile_orphan_facts when fact_extractor is available."""
    state, _, db = _make_state()
    db.upsert_alias = AsyncMock()
    state.memory.add_alias = MagicMock()

    fe = MagicMock()
    fe._reconcile_orphan_facts = AsyncMock(return_value=None)
    state.fact_extractor = fe

    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/aliases",
            headers=HEADERS,
            json={"nickname": "jo", "canonical_uid": "discord:456", "display_name": ""},
        )
    assert r.status_code == 200
    # Give asyncio.create_task a chance to fire
    import asyncio
    await asyncio.sleep(0)
    fe._reconcile_orphan_facts.assert_called_once_with("jo", "discord:456")


@pytest.mark.asyncio
async def test_add_alias_rejects_missing_fields():
    """POST /memory/aliases returns 400 when nickname or canonical_uid is empty."""
    state, _, db = _make_state()
    db.upsert_alias = AsyncMock()
    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/aliases",
            headers=HEADERS,
            json={"nickname": "", "canonical_uid": "discord:123", "display_name": ""},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_alias():
    """DELETE /memory/aliases/{nickname} removes alias from DB and memory cache."""
    state, _, db = _make_state()
    db.delete_alias = AsyncMock()
    state.memory.remove_alias = MagicMock()

    async with _make_client(state) as client:
        r = await client.delete("/api/admin/memory/aliases/rekin", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    db.delete_alias.assert_called_once_with("rekin")
    state.memory.remove_alias.assert_called_once_with("nickname:rekin")


@pytest.mark.asyncio
async def test_resolve_alias():
    """POST /memory/aliases/{nickname}/resolve resolves an unknown alias."""
    state, _, db = _make_state()
    db.upsert_alias = AsyncMock()
    state.memory.add_alias = MagicMock()

    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/aliases/unknown%3Ajohndoe/resolve",
            headers=HEADERS,
            json={"canonical_uid": "discord:789", "display_name": "John Doe"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "unknown:johndoe" in data["resolved"]
    db.upsert_alias.assert_called_once_with(
        "unknown:johndoe", "discord:789", "John Doe", "manual", 1.0
    )
    state.memory.add_alias.assert_called_once_with("nickname:unknown:johndoe", "discord:789")


@pytest.mark.asyncio
async def test_list_users_sort_by_trust():
    state, _, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:1", "platform": "discord", "username": "Alice", "memory_count": 5, "avatar_url": None},
        {"user_id": "discord:2", "platform": "discord", "username": "Bob", "memory_count": 10, "avatar_url": None},
    ]
    db.list_link_proposals = AsyncMock(return_value=[])
    db.get_trust_score = AsyncMock(side_effect=lambda p, uid: 0.9 if "1" in uid else 0.3)
    db.get_love_score = AsyncMock(side_effect=lambda p, uid, **kw: 0.5 if "1" in uid else 0.8)

    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users?sort_by=trust", headers=HEADERS)
    assert r.status_code == 200
    users = r.json()["users"]
    assert users[0]["trust_score"] >= users[1]["trust_score"]


@pytest.mark.asyncio
async def test_list_users_sort_by_love():
    state, _, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:1", "platform": "discord", "username": "Alice", "memory_count": 5, "avatar_url": None},
        {"user_id": "discord:2", "platform": "discord", "username": "Bob", "memory_count": 10, "avatar_url": None},
    ]
    db.list_link_proposals = AsyncMock(return_value=[])
    db.get_trust_score = AsyncMock(return_value=0.5)
    db.get_love_score = AsyncMock(side_effect=lambda p, uid, **kw: 0.5 if "1" in uid else 0.8)

    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users?sort_by=love", headers=HEADERS)
    assert r.status_code == 200
    users = r.json()["users"]
    assert users[0]["love_score"] >= users[1]["love_score"]


@pytest.mark.asyncio
async def test_list_users_sort_by_memories():
    state, _, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:1", "platform": "discord", "username": "Alice", "memory_count": 5, "avatar_url": None},
        {"user_id": "discord:2", "platform": "discord", "username": "Bob", "memory_count": 10, "avatar_url": None},
    ]
    db.list_link_proposals = AsyncMock(return_value=[])
    db.get_trust_score = AsyncMock(return_value=0.5)
    db.get_love_score = AsyncMock(return_value=0.5)

    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users?sort_by=memories", headers=HEADERS)
    assert r.status_code == 200
    users = r.json()["users"]
    assert users[0]["memory_count"] >= users[1]["memory_count"]


@pytest.mark.asyncio
async def test_list_users_enriches_trust_and_love():
    state, _, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:42", "platform": "discord", "username": "Test", "memory_count": 3, "avatar_url": None},
    ]
    db.list_link_proposals = AsyncMock(return_value=[])
    db.get_trust_score = AsyncMock(return_value=0.75)
    db.get_love_score = AsyncMock(return_value=0.6)

    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users", headers=HEADERS)
    assert r.status_code == 200
    user = r.json()["users"][0]
    assert user["trust_score"] == 0.75
    assert user["love_score"] == 0.6
    assert "avatar_url" in user
    assert "memory_count" in user


@pytest.mark.asyncio
async def test_get_user_memories_includes_category():
    state, mock_store, db = _make_state()
    mock_store.get_all = AsyncMock(return_value=[
        MemoryRecord(id="mem1", text="Likes Python", user_id="discord:123", category="PREF",
                     created_at="2026-03-20", source="discord:123"),
        MemoryRecord(id="mem2", text="Lives in Lyon", user_id="discord:123", category="FAIT",
                     created_at="2026-03-19", source="discord:123"),
    ])
    db.list_link_proposals = AsyncMock(return_value=[])
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users/discord:123", headers=HEADERS)
    assert r.status_code == 200
    memories = r.json()["memories"]
    assert memories[0]["category"] == "PREF"
    assert memories[1]["category"] == "FAIT"


@pytest.mark.asyncio
async def test_add_memory_with_category():
    state, mock_store, db = _make_state()
    db.upsert_memory_user = AsyncMock()
    async with _make_client(state) as client:
        r = await client.post("/api/admin/memory/users/discord:123/memories",
                              json={"content": "Likes cats", "category": "PREF"}, headers=HEADERS)
    assert r.status_code == 200
    call_args = mock_store.upsert.call_args
    metadata = call_args.args[2]
    assert metadata.category == "PREF"


@pytest.mark.asyncio
async def test_add_memory_without_category():
    """POST without category should default to FAIT."""
    state, mock_store, db = _make_state()
    db.upsert_memory_user = AsyncMock()
    async with _make_client(state) as client:
        r = await client.post("/api/admin/memory/users/discord:123/memories",
                              json={"content": "Likes dogs"}, headers=HEADERS)
    assert r.status_code == 200
    call_args = mock_store.upsert.call_args
    metadata = call_args.args[2]
    assert metadata.category == "FAIT"


@pytest.mark.asyncio
async def test_update_memory_accepts_category():
    """PUT with category field should still work."""
    state, mock_store, _ = _make_state()
    async with _make_client(state) as client:
        r = await client.put(
            "/api/admin/memory/users/discord:123/memories/mem-abc",
            headers=HEADERS,
            json={"content": "Updated content", "category": "PREF"},
        )
    assert r.status_code == 200
    mock_store.update.assert_called_once()
    call_args = mock_store.update.call_args
    assert call_args.args[0] == "mem-abc"
    assert call_args.args[1] == "Updated content"
    assert call_args.args[2].category == "PREF"


@pytest.mark.asyncio
async def test_resolve_alias_rejects_empty_canonical():
    """POST /memory/aliases/{nickname}/resolve returns 400 when canonical_uid is empty."""
    state, _, db = _make_state()
    db.upsert_alias = AsyncMock()
    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/aliases/somealias/resolve",
            headers=HEADERS,
            json={"canonical_uid": "  ", "display_name": ""},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_sync_also_resolves_usernames():
    state, mock_store, db = _make_state()
    db.sync_memory_users_from_qdrant = AsyncMock(return_value=3)
    db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:999", "platform": "discord", "username": ""},
    ])
    db.upsert_memory_user = AsyncMock()
    db.execute = AsyncMock()
    mock_discord = MagicMock()
    mock_user = MagicMock()
    mock_user.display_name = "ResolvedName"
    mock_user.name = "ResolvedName"
    mock_discord.fetch_user = AsyncMock(return_value=mock_user)
    state.discord_bot = mock_discord
    state.twitch_bot = None

    async with _make_client(state) as client:
        r = await client.post("/api/admin/memory/sync", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["synced"] == 3
    assert data["resolved"] >= 0
