"""Tests des routes API coûts du dashboard."""
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


@pytest.fixture(autouse=True)
def _clear_costs_cache():
    """Vider le cache top_users entre chaque test."""
    from bot.dashboard.routes.costs import _top_users_cache
    _top_users_cache.clear()
    yield
    _top_users_cache.clear()


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
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.insert_emotion_snapshot = AsyncMock()
    state = AppState(
        config=_make_config(),
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


# ── Auth ──────────────────────────────────────────────────────────────────────

async def test_costs_auth_required(client):
    """Tous les endpoints costs refusent sans token."""
    for path in ["/api/admin/costs/summary", "/api/admin/costs/daily",
                 "/api/admin/costs/breakdown/model", "/api/admin/costs/breakdown/purpose",
                 "/api/admin/costs/top-users", "/api/admin/costs/alert"]:
        r = await client.get(path)
        assert r.status_code == 401, f"{path} should require auth"


# ── Summary ───────────────────────────────────────────────────────────────────

async def test_costs_summary(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(side_effect=[
        {"total": 12.50, "count": 100},   # current period
        {"total": 15.00, "count": 120},   # previous period
    ])
    r = await client.get("/api/admin/costs/summary", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 12.50
    assert data["msg_count"] == 100
    assert data["avg_per_msg"] == 0.125
    assert data["prev_total"] == 15.00
    assert data["pct_change"] == pytest.approx(-16.67, abs=0.01)


async def test_costs_summary_empty_db(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 0.0, "count": 0})
    r = await client.get("/api/admin/costs/summary", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0.0
    assert data["avg_per_msg"] == 0.0
    assert data["pct_change"] == 0.0


# ── Daily ─────────────────────────────────────────────────────────────────────

async def test_costs_daily(client):
    db = client._transport.app.state.wally.db
    db.get_daily_costs = AsyncMock(side_effect=[
        [{"date": "2026-03-17", "cost": 0.5}, {"date": "2026-03-18", "cost": 0.8}],
        [{"date": "2026-02-17", "cost": 0.3}, {"date": "2026-02-18", "cost": 0.6}],
    ])
    r = await client.get("/api/admin/costs/daily?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data["current"]) == 2
    assert len(data["previous"]) == 2


# ── Breakdown model ───────────────────────────────────────────────────────────

async def test_costs_breakdown_model(client):
    db = client._transport.app.state.wally.db
    db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "gpt-4o", "total": 8.20, "count": 50},
        {"key": "gpt-4o-mini", "total": 3.15, "count": 80},
    ])
    r = await client.get("/api/admin/costs/breakdown/model?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["model"] == "gpt-4o"
    assert data[0]["total"] == 8.20


# ── Breakdown purpose ────────────────────────────────────────────────────────

async def test_costs_breakdown_purpose(client):
    db = client._transport.app.state.wally.db
    db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "discord_response", "total": 5.0, "count": 40},
        {"key": "discord_ask", "total": 2.0, "count": 15},
        {"key": "twitch_response", "total": 0.4, "count": 5},
        {"key": "session_analysis", "total": 2.0, "count": 20},
        {"key": "emotion_analysis", "total": 1.2, "count": 30},
        {"key": "daily_journal", "total": 1.0, "count": 1},
        {"key": "memory_consolidation", "total": 0.5, "count": 5},
        {"key": "unknown_purpose", "total": 0.1, "count": 1},
    ])
    r = await client.get("/api/admin/costs/breakdown/purpose?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    categories = {d["category"]: d["total"] for d in data}
    assert "Réponses" in categories
    assert "Analyse" in categories
    assert "Journal" in categories
    assert "Mémoire" in categories
    assert "Autre" in categories
    assert categories["Réponses"] == pytest.approx(7.4)


# ── Top users ─────────────────────────────────────────────────────────────────

async def test_costs_top_users(client):
    db = client._transport.app.state.wally.db
    db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "discord:123", "total": 4.20, "count": 30},
        {"key": "twitch:luna", "total": 3.10, "count": 25},
        {"key": None, "total": 1.50, "count": 15},
    ])
    db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:123", "username": "Azrael", "platform": "discord",
         "last_updated": 0, "trust_score": 0.5},
    ])
    r = await client.get("/api/admin/costs/top-users?days=30&limit=10", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    assert data[0]["username"] == "Azrael"
    assert data[2]["username"] == "Système"


async def test_costs_top_users_resolves_discord_names_via_bot():
    """Discord IDs sans username dans memory_users sont résolus via le bot Discord."""
    discord_bot = MagicMock()
    discord_user = MagicMock()
    discord_user.display_name = "KingsRequin"
    discord_user.name = "kingsrequin"
    discord_bot.fetch_user = AsyncMock(return_value=discord_user)

    state = _make_state(discord_bot=discord_bot)
    state.db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "discord:999888", "total": 5.0, "count": 40},
    ])
    state.db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:999888", "username": None, "platform": "discord",
         "last_updated": 0, "trust_score": 0.5},
    ])
    state.db.upsert_memory_user = AsyncMock()

    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/admin/costs/top-users?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data[0]["username"] == "KingsRequin"
    discord_bot.fetch_user.assert_awaited_once_with(999888)
    state.db.upsert_memory_user.assert_awaited_once()


# ── Alert ─────────────────────────────────────────────────────────────────────

async def test_costs_alert_ok(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 10.0, "count": 50})
    r = await client.get("/api/admin/costs/alert", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["threshold"] == 25.0
    assert data["current_total"] == 10.0
    assert data["pct_used"] == 40.0
    assert data["status"] == "ok"


async def test_costs_alert_warning(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 18.0, "count": 80})
    r = await client.get("/api/admin/costs/alert", headers=HEADERS)
    data = r.json()
    assert data["status"] == "warning"


async def test_costs_alert_critical(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 22.0, "count": 90})
    r = await client.get("/api/admin/costs/alert", headers=HEADERS)
    data = r.json()
    assert data["status"] == "critical"


async def test_costs_avg_no_division_by_zero(client):
    db = client._transport.app.state.wally.db
    db.get_cost_stats = AsyncMock(return_value={"total": 0.0, "count": 0})
    r = await client.get("/api/admin/costs/summary", headers=HEADERS)
    data = r.json()
    assert data["avg_per_msg"] == 0.0


# ── By Feature ────────────────────────────────────────────────────────────────

async def test_costs_by_feature_grouping(client):
    db = client._transport.app.state.wally.db
    db.get_cost_breakdown = AsyncMock(return_value=[
        {"key": "discord_response", "total": 5.0, "count": 40},
        {"key": "discord_spontaneous", "total": 1.0, "count": 10},
        {"key": "daily_journal", "total": 2.0, "count": 2},
        {"key": "emotion_analysis", "total": 0.5, "count": 50},
        {"key": "image_generation", "total": 3.0, "count": 5},
        {"key": "embedding", "total": 0.2, "count": 100},
        {"key": "reminder", "total": 0.1, "count": 3},
        {"key": "unknown_thing", "total": 0.05, "count": 1},
    ])
    r = await client.get("/api/admin/costs/by-feature?days=30", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    features = {d["feature"]: d for d in data}
    assert features["Réponses"]["cost"] == pytest.approx(6.0)  # 5.0 + 1.0
    assert "Journal" in features
    assert "Images" in features
    assert "Émotions" in features
    assert "Mémoire" in features
    assert "Système" in features
    assert "Autre" in features
    total_pct = sum(d["pct"] for d in data)
    assert total_pct == pytest.approx(100.0, abs=0.5)


# ── Prices ────────────────────────────────────────────────────────────────────

async def test_costs_prices(client):
    r = await client.get("/api/admin/costs/prices", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    for model, prices in data.items():
        assert "input_per_1k" in prices
        assert "output_per_1k" in prices
        assert prices["input_per_1k"] > 0


# ── Logs Paginated ────────────────────────────────────────────────────────────

async def test_costs_logs_paginated(client):
    db = client._transport.app.state.wally.db
    db.get_cost_logs_paginated = AsyncMock(return_value={
        "total": 150, "page": 1, "limit": 50,
        "logs": [{"datetime": "2026-03-29 14:00:00", "model": "gpt-5",
                  "input_tokens": 200, "output_tokens": 80, "cost_usd": 0.00124,
                  "purpose": "discord_response", "user_id": "discord:123", "username": "Azrael"}],
    })
    r = await client.get("/api/admin/costs/logs?days=7&page=1&limit=50", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 150
    assert data["logs"][0]["username"] == "Azrael"


async def test_costs_logs_auth_required(client):
    r = await client.get("/api/admin/costs/logs")
    assert r.status_code == 401
