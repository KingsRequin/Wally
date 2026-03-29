"""Tests for alias CRUD routes."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import (
    BotConfig, OpenAIConfig, DiscordConfig, TwitchConfig,
    EmotionDecayConfig, TwitchEventConfig,
)

HEADERS = {"Authorization": "Bearer testtoken"}


def _make_config():
    cfg = MagicMock()
    cfg.bot = BotConfig(
        trigger_names=["wally"],
        language_default="fr",
        context_window_size=20,
        context_token_threshold=3000,
        journal_time="03:00",
        dashboard_token="testtoken",
        cost_alert_threshold=25.0,
    )
    cfg.openai = OpenAIConfig(
        primary_model="gpt-5", secondary_model="gpt-5-mini",
        temperature=0.8, max_tokens=1000,
    )
    cfg.discord = DiscordConfig(anger_trigger_threshold=3, timeout_minutes=10)
    cfg.twitch = TwitchConfig(guest_channels=[], cooldown_seconds=10)
    cfg.emotions = {
        "anger": EmotionDecayConfig(decay_lambda=0.1),
        "joy": EmotionDecayConfig(decay_lambda=0.05),
        "sadness": EmotionDecayConfig(decay_lambda=0.08),
        "curiosity": EmotionDecayConfig(decay_lambda=0.1),
        "boredom": EmotionDecayConfig(decay_lambda=0.15),
    }
    cfg.twitch_events = {"follow": TwitchEventConfig(active=True, message="Hey {username}!")}
    cfg.save = MagicMock()
    return cfg


def _make_state(**overrides) -> AppState:
    emotion = MagicMock()
    emotion.get_state.return_value = {
        "anger": 0.1, "joy": 0.7, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0
    }
    db = MagicMock()
    db.list_aliases = AsyncMock(return_value=[])
    db.upsert_alias = AsyncMock()
    db.delete_alias = AsyncMock()
    memory = MagicMock()
    memory.load_aliases = AsyncMock()
    state = AppState(
        config=_make_config(),
        db=db,
        emotion=emotion,
        memory=memory,
        persona=MagicMock(),
        primary_llm=MagicMock(),
        secondary_llm=MagicMock(),
        image_client=MagicMock(),
        token_manager=MagicMock(),
        twitch_api=None,
        discord_bot=None,
        twitch_bot=None,
        start_time=time.time() - 100,
        message_count=42,
    )
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


@pytest.fixture
def app():
    return create_dashboard_app(_make_state())


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── GET /aliases ──────────────────────────────────────────────────────────────

async def test_list_aliases_all(client):
    db = client._transport.app.state.wally.db
    db.list_aliases = AsyncMock(return_value=[
        {"nickname": "zeddo", "canonical_uid": "twitch:mkszedd", "source": "manual", "confidence": 1.0}
    ])
    r = await client.get("/api/admin/aliases", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["nickname"] == "zeddo"
    db.list_aliases.assert_called_once_with(canonical_uid=None)


async def test_list_aliases_by_uid(client):
    db = client._transport.app.state.wally.db
    db.list_aliases = AsyncMock(return_value=[])
    r = await client.get("/api/admin/aliases?canonical_uid=twitch:mkszedd", headers=HEADERS)
    assert r.status_code == 200
    db.list_aliases.assert_called_once_with(canonical_uid="twitch:mkszedd")


# ── POST /aliases ─────────────────────────────────────────────────────────────

async def test_create_alias(client):
    state = client._transport.app.state.wally
    state.db.upsert_alias = AsyncMock()
    state.memory.load_aliases = AsyncMock()
    r = await client.post("/api/admin/aliases", headers=HEADERS, json={
        "nickname": "melio",
        "canonical_uid": "discord:123456789",
        "display_name": "Meliodas"
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    state.db.upsert_alias.assert_called_once_with(
        "melio", "discord:123456789", display_name="Meliodas", source="manual", confidence=1.0
    )
    state.memory.load_aliases.assert_called_once_with(state.db)


async def test_create_alias_no_display_name(client):
    state = client._transport.app.state.wally
    state.db.upsert_alias = AsyncMock()
    state.memory.load_aliases = AsyncMock()
    r = await client.post("/api/admin/aliases", headers=HEADERS, json={
        "nickname": "zeddo",
        "canonical_uid": "twitch:mkszedd",
    })
    assert r.status_code == 200
    state.db.upsert_alias.assert_called_once_with(
        "zeddo", "twitch:mkszedd", display_name=None, source="manual", confidence=1.0
    )


async def test_create_alias_missing_nickname(client):
    r = await client.post("/api/admin/aliases", headers=HEADERS, json={"canonical_uid": "discord:123"})
    assert r.status_code == 400


async def test_create_alias_missing_canonical_uid(client):
    r = await client.post("/api/admin/aliases", headers=HEADERS, json={"nickname": "melio"})
    assert r.status_code == 400


async def test_create_alias_missing_both_fields(client):
    r = await client.post("/api/admin/aliases", headers=HEADERS, json={})
    assert r.status_code == 400


# ── DELETE /aliases/{nickname} ────────────────────────────────────────────────

async def test_delete_alias(client):
    state = client._transport.app.state.wally
    state.db.delete_alias = AsyncMock()
    state.memory.load_aliases = AsyncMock()
    r = await client.delete("/api/admin/aliases/melio", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    state.db.delete_alias.assert_called_once_with("melio")
    state.memory.load_aliases.assert_called_once_with(state.db)


async def test_delete_alias_refreshes_cache(client):
    state = client._transport.app.state.wally
    state.db.delete_alias = AsyncMock()
    state.memory.load_aliases = AsyncMock()
    await client.delete("/api/admin/aliases/zeddo", headers=HEADERS)
    state.memory.load_aliases.assert_called_once_with(state.db)


# ── Auth required ─────────────────────────────────────────────────────────────

async def test_aliases_auth_required(client):
    for path, method in [
        ("/api/admin/aliases", "GET"),
        ("/api/admin/aliases", "POST"),
        ("/api/admin/aliases/test", "DELETE"),
    ]:
        if method == "GET":
            r = await client.get(path)
        elif method == "POST":
            r = await client.post(path, json={})
        else:
            r = await client.delete(path)
        assert r.status_code == 401, f"{method} {path} should require auth"
