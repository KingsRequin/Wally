from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot.intelligence.attention_agent import AttentionAgent
from bot.intelligence.social_rhythm import SocialRhythm


class _FakeFacts:
    async def search_by_category(self, *a, **k):
        return []

    async def get_latest_by_source(self, *a, **k):
        return None

    async def get_by_user(self, *a, **k):
        return []

    async def sample_random(self, *a, **k):
        return []


@pytest.mark.asyncio
async def test_build_context_fills_receptivity(monkeypatch):
    sr = SocialRhythm(alpha=0.5, n_conf=3)
    PARIS = ZoneInfo("Europe/Paris")
    for day in range(1, 7):
        for _ in range(20):
            sr.record_incoming(datetime(2026, 6, day, 14, tzinfo=PARIS))
        sr.record_spontaneous_outcome(True, datetime(2026, 6, day, 14, tzinfo=PARIS))

    # neutralise les I/O réseau/host de build_context
    import bot.core.system_info as si

    monkeypatch.setattr(si, "read_host_metrics", lambda: None, raising=False)

    async def _no_weather():
        return None

    monkeypatch.setattr(si, "fetch_weather_france", _no_weather, raising=False)

    agent = AttentionAgent(_FakeFacts(), social_rhythm=sr)
    ctx = await agent.build_context({"boredom": 0.1}, [], idle=True)
    assert isinstance(ctx.social_receptivity, str) and ctx.social_receptivity
    assert 0.0 <= ctx.receptivity_score <= 1.0
