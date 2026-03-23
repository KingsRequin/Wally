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
    ImageGenerationConfig, OverlayImageConfig,
    LLMConfig, LLMRoleConfig,
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
        primary_model="gpt-5",
        secondary_model="gpt-5-mini",
        temperature=0.8,
        max_tokens=1000,
        reasoning_effort="medium",
        text_verbosity="medium",
    )
    cfg.discord = DiscordConfig(
        anger_trigger_threshold=3,
        timeout_minutes=10,
    )
    cfg.twitch = TwitchConfig(
        guest_channels=[],
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
    cfg.llm = LLMConfig(
        primary=LLMRoleConfig(provider="openai", model="gpt-5"),
        secondary=LLMRoleConfig(provider="openai", model="gpt-5-mini"),
    )
    cfg.image_generation = ImageGenerationConfig()
    cfg.overlay_image = OverlayImageConfig()
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
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.insert_emotion_snapshot = AsyncMock()

    cfg = _make_config()

    state = AppState(
        config=cfg,
        db=db,
        emotion=emotion,
        memory=MagicMock(),
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


async def test_get_emotions_history_with_since_param(app):
    """Le param since est transmis à la DB ; la réponse contient toujours 'history'."""
    import time
    state = _make_state()
    # Remplacer le mock pour capturer l'argument reçu
    captured = {}
    async def fake_since(since):
        captured["since"] = since
        return []
    state.db.get_emotion_snapshots_since = fake_since

    app2 = create_dashboard_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app2), base_url="http://test"
    ) as c:
        since_val = time.time() - 7 * 86400
        r = await c.get(f"/api/public/emotions/history?since={since_val}")
    assert r.status_code == 200
    assert "history" in r.json()
    assert abs(captured["since"] - since_val) < 1.0


async def test_get_emotions_history_since_capped_at_30d(app):
    """Un since trop ancien est cappé à 30 jours."""
    import time
    state = _make_state()
    captured = {}
    async def fake_since(since):
        captured["since"] = since
        return []
    state.db.get_emotion_snapshots_since = fake_since

    app2 = create_dashboard_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app2), base_url="http://test"
    ) as c:
        r = await c.get("/api/public/emotions/history?since=0")
    assert r.status_code == 200
    # Le since reçu par la DB doit être >= now - 30j - quelques secondes de marge
    assert captured["since"] >= time.time() - 30 * 86400 - 5


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


async def test_update_spam_detection_config(client, app):
    resp = await client.post(
        "/api/admin/config",
        json={"discord": {"spam_detection": {
            "enabled": False,
            "max_messages": 15,
            "window_seconds": 60,
            "mute_minutes": 3,
            "spam_anger_delta": 0.1,
            "exempt_channels": [111, 222],
        }}},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    cfg = app.state.wally.config
    assert cfg.discord.spam_detection.enabled is False
    assert cfg.discord.spam_detection.max_messages == 15
    assert cfg.discord.spam_detection.window_seconds == 60
    assert cfg.discord.spam_detection.exempt_channels == [111, 222]


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


# ── Memory routes (Phase 2 — no longer stub) ──────────────────────────────────

async def test_memory_users_route_is_implemented():
    db = MagicMock()
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.insert_emotion_snapshot = AsyncMock()
    db.list_memory_users = AsyncMock(return_value=[])
    db.list_link_proposals = AsyncMock(return_value=[])
    state = _make_state(db=db)
    app = create_dashboard_app(state)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/admin/memory/users", headers=ADMIN_HEADERS)
    assert r.status_code != 501
