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
        primary_model="gpt-4o-mini",
        secondary_model="gpt-4o-mini",
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
    db.list_memory_users.assert_called_once_with("discord")


@pytest.mark.asyncio
async def test_get_user_memories_returns_list():
    state, mock_mem0, _ = _make_state()
    mock_mem0.get_all.return_value = [
        {"id": "mem-1", "memory": "Préfère le français"},
        {"id": "mem-2", "memory": "Aime Minecraft"},
    ]
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *args, **kw: f(*args, **kw))):
        async with _make_client(state) as client:
            r = await client.get(
                "/api/admin/memory/users/discord%3A123", headers=HEADERS
            )
    assert r.status_code == 200
    data = r.json()
    assert len(data["memories"]) == 2
    assert data["memories"][0]["id"] == "mem-1"


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
