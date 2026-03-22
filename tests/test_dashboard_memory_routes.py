import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import (
    BotConfig, OpenAIConfig, EmotionDecayConfig, TwitchEventConfig,
    TwitchConfig, DiscordConfig,
)


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
    memory._init_mem0 = MagicMock()
    mock_mem0 = MagicMock()
    memory._mem0 = mock_mem0

    db = AsyncMock()

    state = AppState(
        config=_make_config(dashboard_token),
        db=db,
        emotion=MagicMock(),
        memory=memory,
        persona=MagicMock(),
        openai_client=MagicMock(),
        token_manager=MagicMock(),
        twitch_api=None,
        discord_bot=None,
        twitch_bot=None,
    )
    return state, mock_mem0, db


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
    state, mock_mem0, _ = _make_state()
    mock_mem0.get_all.return_value = [
        {"id": "mem-1", "memory": "Préfère le français", "created_at": "2026-03-10T10:00:00Z", "updated_at": None},
        {"id": "mem-2", "memory": "Aime Minecraft", "created_at": "2026-03-18T15:00:00Z", "updated_at": None},
        {"id": "mem-3", "memory": "Joue à Apex", "created_at": "2026-03-12T08:00:00Z", "updated_at": "2026-03-19T09:00:00Z"},
    ]
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.get(
                "/api/admin/memory/users/discord%3A123", headers=HEADERS
            )
    assert r.status_code == 200
    data = r.json()
    assert len(data["memories"]) == 3
    # Most recent first: mem-3 (updated 03-19), mem-2 (created 03-18), mem-1 (created 03-10)
    assert data["memories"][0]["id"] == "mem-3"
    assert data["memories"][1]["id"] == "mem-2"
    assert data["memories"][2]["id"] == "mem-1"
    # Verify date fields are included
    assert data["memories"][0]["created_at"] == "2026-03-12T08:00:00Z"
    assert data["memories"][0]["updated_at"] == "2026-03-19T09:00:00Z"


@pytest.mark.asyncio
async def test_get_user_memories_unwraps_dict():
    state, mock_mem0, _ = _make_state()
    mock_mem0.get_all.return_value = {
        "results": [{"id": "mem-1", "memory": "Test"}]
    }
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.get(
                "/api/admin/memory/users/discord%3A123", headers=HEADERS
            )
    assert r.status_code == 200
    assert len(r.json()["memories"]) == 1


@pytest.mark.asyncio
async def test_get_user_memories_503_when_mem0_none():
    state, _, _ = _make_state()
    state.memory._mem0 = None
    async with _make_client(state) as client:
        r = await client.get(
            "/api/admin/memory/users/discord%3A123", headers=HEADERS
        )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_delete_user_calls_delete_all_and_db():
    state, mock_mem0, db = _make_state()
    mock_mem0.delete_all = MagicMock()
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.delete(
                "/api/admin/memory/users/discord%3A123", headers=HEADERS
            )
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    mock_mem0.delete_all.assert_called_once_with(user_id="discord:123")
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_delete_memory_calls_mem0_delete():
    state, mock_mem0, _ = _make_state()
    mock_mem0.delete = MagicMock()
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.delete(
                "/api/admin/memory/users/discord%3A123/memories/mem-abc",
                headers=HEADERS,
            )
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    mock_mem0.delete.assert_called_once_with("mem-abc")


@pytest.mark.asyncio
async def test_add_memory_stores_via_mem0():
    state, mock_mem0, db = _make_state()
    mock_mem0.add = MagicMock(return_value={"results": []})
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.post(
                "/api/admin/memory/users/discord%3A123/memories",
                headers=HEADERS,
                json={"content": "Aime les crevettes"},
            )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    mock_mem0.add.assert_called_once_with(
        "Aime les crevettes", user_id="discord:123",
        metadata={"origin": "discord:123"},
    )
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
async def test_add_memory_503_when_mem0_none():
    state, _, _ = _make_state()
    state.memory._mem0 = None
    async with _make_client(state) as client:
        r = await client.post(
            "/api/admin/memory/users/discord%3A123/memories",
            headers=HEADERS,
            json={"content": "Test"},
        )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_update_memory_calls_mem0_update():
    state, mock_mem0, _ = _make_state()
    mock_mem0.update = MagicMock()
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.put(
                "/api/admin/memory/users/discord%3A123/memories/mem-abc",
                headers=HEADERS,
                json={"content": "Nouveau contenu"},
            )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    mock_mem0.update.assert_called_once_with("mem-abc", "Nouveau contenu")


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
    state, mock_mem0, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0}
    ]
    mock_mem0.search.return_value = [
        {"memory": "Aime Minecraft", "score": 0.9}
    ]
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
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
async def test_search_unwraps_dict():
    state, mock_mem0, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0}
    ]
    mock_mem0.search.return_value = {"results": [{"memory": "Test", "score": 0.8}]}
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.get(
                "/api/admin/memory/search?q=test", headers=HEADERS
            )
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1


@pytest.mark.asyncio
async def test_search_continues_on_user_error():
    """Search loop must continue even if one user's mem0 call raises."""
    state, mock_mem0, db = _make_state()
    db.list_memory_users.return_value = [
        {"user_id": "discord:123", "platform": "discord", "last_updated": 1700000000.0},
        {"user_id": "twitch:bob", "platform": "twitch", "last_updated": 1700000001.0},
    ]

    def _search_side_effect(q, user_id, limit):
        if user_id == "discord:123":
            raise RuntimeError("Qdrant timeout")
        return [{"memory": "Aime Minecraft", "score": 0.9}]

    mock_mem0.search.side_effect = _search_side_effect
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
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
    state, mock_mem0, db = _make_state()
    db.list_aliases.return_value = [
        {"nickname": "rekin", "canonical_uid": "discord:123", "display_name": "KingsRequin",
         "source": "manual", "confidence": 1.0},
    ]
    db.list_unresolved_aliases.return_value = [
        {"user_id": "unknown:johndoe", "username": "johndoe"},
    ]
    mock_mem0.get_all.return_value = [
        {"memory": "Aime les jeux FPS"},
        {"memory": "Parle français"},
    ]
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
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
async def test_list_aliases_mem0_down():
    """GET /memory/aliases still works when mem0 is unavailable."""
    state, _, db = _make_state()
    state.memory._mem0 = None
    db.list_aliases.return_value = []
    db.list_unresolved_aliases.return_value = [
        {"user_id": "unknown:foo", "username": "foo"},
    ]
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/aliases", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    # fact_count should be 0 when mem0 is not available
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
    state, mock_mem0, db = _make_state()
    mock_mem0.get_all.return_value = [
        {"id": "mem1", "memory": "Likes Python", "metadata": {"origin": "discord:123", "category": "PREF"}, "created_at": "2026-03-20", "updated_at": "2026-03-20"},
        {"id": "mem2", "memory": "Lives in Lyon", "metadata": {"origin": "discord:123"}, "created_at": "2026-03-19", "updated_at": "2026-03-19"},
    ]
    db.list_link_proposals = AsyncMock(return_value=[])
    async with _make_client(state) as client:
        r = await client.get("/api/admin/memory/users/discord:123", headers=HEADERS)
    assert r.status_code == 200
    memories = r.json()["memories"]
    assert memories[0]["category"] == "PREF"
    assert memories[1]["category"] == ""


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
