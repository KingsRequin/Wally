"""Shared fixtures for tests/dashboard/."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
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
    cfg.discord = DiscordConfig(anger_trigger_threshold=3, timeout_minutes=10)
    cfg.twitch = TwitchConfig(guest_channels=[], cooldown_seconds=10)
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
        message_count=0,
    )
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


@pytest.fixture
async def async_client():
    state = _make_state()
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.app = app
        yield c
