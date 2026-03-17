# tests/test_dashboard_routes.py
"""Tests d'intégration des routes dashboard avec une app FastAPI de test."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from bot.dashboard.state import AppState
from bot.config import (
    BotConfig, OpenAIConfig, DiscordConfig, TwitchConfig,
    EmotionDecayConfig, TwitchEventConfig,
)


def _make_config():
    """Crée un Config mock avec de vraies instances dataclass pour asdict()."""
    cfg = MagicMock()
    cfg.bot = BotConfig(
        trigger_names=["wally"],
        language_default="fr",
        context_window_size=20,
        context_token_threshold=3000,
        journal_time="03:00",
        journal_channel_id=None,
        dashboard_token="testtoken",
        prelude_window_size=15,
    )
    cfg.openai = OpenAIConfig(
        primary_model="gpt-4o",
        secondary_model="gpt-4o-mini",
        temperature=0.8,
        max_tokens=1000,
    )
    cfg.discord = DiscordConfig(
        anger_trigger_threshold=3,
        timeout_minutes=10,
    )
    cfg.twitch = TwitchConfig(
        channels=[],
        cooldown_seconds=10,
    )
    cfg.emotions = {
        "anger": EmotionDecayConfig(decay_lambda=0.1),
        "joy": EmotionDecayConfig(decay_lambda=0.05),
        "sadness": EmotionDecayConfig(decay_lambda=0.08),
        "curiosity": EmotionDecayConfig(decay_lambda=0.1),
        "boredom": EmotionDecayConfig(decay_lambda=0.15),
    }
    cfg.twitch_events = {
        "follow": TwitchEventConfig(active=True, message="Hey {username}!"),
    }
    cfg.save = MagicMock()
    return cfg


def _make_state(**overrides) -> AppState:
    """Crée un AppState minimal avec des mocks."""
    emotion = MagicMock()
    emotion.get_state.return_value = {
        "anger": 0.1, "joy": 0.7, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0
    }
    emotion.set_emotion = MagicMock()

    db = MagicMock()
    db.get_today_emotion_snapshots = AsyncMock(return_value=[])
    db.insert_emotion_snapshot = AsyncMock()

    cfg = _make_config()

    state = AppState(
        config=cfg,
        db=db,
        emotion=emotion,
        memory=MagicMock(),
        persona=MagicMock(),
        openai_client=MagicMock(),
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


# ── Status ────────────────────────────────────────────────────────────────────

async def test_status_shape(client):
    r = await client.get("/api/public/status")
    assert r.status_code == 200
    data = r.json()
    assert "uptime_seconds" in data
    assert "discord_online" in data
    assert "twitch_online" in data
    assert data["total_messages"] == 42


async def test_status_discord_offline_when_none(client):
    r = await client.get("/api/public/status")
    assert r.json()["discord_online"] is False


# ── Emotions public ───────────────────────────────────────────────────────────

async def test_get_emotions_public(client):
    r = await client.get("/api/public/emotions")
    assert r.status_code == 200
    data = r.json()
    assert data["joy"] == 0.7
    assert "anger" in data


async def test_get_emotions_history(client):
    r = await client.get("/api/public/emotions/history")
    assert r.status_code == 200
    assert "history" in r.json()


# ── Emotions admin ────────────────────────────────────────────────────────────

ADMIN_HEADERS = {"Authorization": "Bearer testtoken"}


async def test_set_emotion_valid(client):
    r = await client.post(
        "/api/admin/emotions/set",
        json={"emotion": "joy", "value": 0.9},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["emotion"] == "joy"


async def test_set_emotion_unknown_returns_400(client):
    r = await client.post(
        "/api/admin/emotions/set",
        json={"emotion": "fear", "value": 0.5},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


async def test_set_emotion_out_of_range_returns_400(client):
    r = await client.post(
        "/api/admin/emotions/set",
        json={"emotion": "joy", "value": 1.5},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


async def test_reset_emotions_calls_set_emotion_05(client, app):
    state = app.state.wally
    state.emotion.set_emotion.reset_mock()
    r = await client.post("/api/admin/emotions/reset", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    calls = {call.args[0]: call.args[1] for call in state.emotion.set_emotion.call_args_list}
    assert calls["joy"] == 0.5
    assert calls["anger"] == 0.5
    assert calls["sadness"] == 0.5


# ── Config ────────────────────────────────────────────────────────────────────

async def test_get_config(client, app):
    app.state.wally.config.bot.dashboard_token = "testtoken"
    r = await client.get("/api/admin/config", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert "bot" in r.json()
    assert "openai" in r.json()


async def test_update_config_invalid_temperature(client):
    r = await client.post(
        "/api/admin/config",
        json={"openai": {"temperature": 5.0}},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


async def test_update_config_invalid_lambda(client, app):
    app.state.wally.config.emotions = {"joy": EmotionDecayConfig(decay_lambda=0.1)}
    r = await client.post(
        "/api/admin/config",
        json={"emotions": {"joy": {"decay_lambda": -0.5}}},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


# ── Twitch stream ─────────────────────────────────────────────────────────────

async def test_stream_offline_when_no_twitch_api(client):
    r = await client.get("/api/public/twitch/stream")
    assert r.status_code == 200
    assert r.json()["live"] is False


async def test_stream_uses_cache(app):
    """Vérifie que get_stream() n'est pas appelé deux fois dans le TTL."""
    mock_api = AsyncMock()
    mock_api.get_stream = AsyncMock(return_value={
        "live": True, "title": "Test", "category": "IRL",
        "viewers": 10, "started_at": "2026-03-16T10:00:00Z",
    })
    state = _make_state(twitch_api=mock_api)
    test_app = create_dashboard_app(state)

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        # Reset cache
        from bot.dashboard.routes import twitch as twitch_mod
        twitch_mod._cache.update({"data": None, "fetched_at": 0.0, "is_live": False})

        await c.get("/api/public/twitch/stream")
        await c.get("/api/public/twitch/stream")

    # get_stream() appelé une seule fois (deuxième requête utilise le cache)
    mock_api.get_stream.assert_called_once()


# ── Memory stub ───────────────────────────────────────────────────────────────

async def test_memory_stub_returns_501(client):
    r = await client.get("/api/admin/memory/users", headers=ADMIN_HEADERS)
    assert r.status_code == 501
