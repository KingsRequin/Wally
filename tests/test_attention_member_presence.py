import pytest

from bot.intelligence.attention_agent import AttentionAgent


class _FakeFacts:
    async def search_by_category(self, *a, **k):
        return []

    async def get_latest_by_source(self, *a, **k):
        return None

    async def get_by_user(self, *a, **k):
        return []

    async def sample_random(self, *a, **k):
        return []


def _neutralize_io(monkeypatch):
    import bot.core.system_info as si

    monkeypatch.setattr(si, "read_host_metrics", lambda: None, raising=False)

    async def _no_weather():
        return None

    monkeypatch.setattr(si, "fetch_weather_france", _no_weather, raising=False)


@pytest.mark.asyncio
async def test_build_context_fills_member_presence(monkeypatch):
    _neutralize_io(monkeypatch)
    agent = AttentionAgent(
        _FakeFacts(),
        presence_provider=lambda: ["Az est ne pas déranger — joue à Apex."],
    )
    ctx = await agent.build_context({"boredom": 0.1}, [], idle=True)
    assert ctx.member_presence == ["Az est ne pas déranger — joue à Apex."]


@pytest.mark.asyncio
async def test_build_context_no_presence_provider(monkeypatch):
    _neutralize_io(monkeypatch)
    agent = AttentionAgent(_FakeFacts())
    ctx = await agent.build_context({"boredom": 0.1}, [], idle=True)
    assert ctx.member_presence == []


@pytest.mark.asyncio
async def test_build_context_presence_provider_error_is_swallowed(monkeypatch):
    _neutralize_io(monkeypatch)

    def _boom():
        raise RuntimeError("cache miss")

    agent = AttentionAgent(_FakeFacts(), presence_provider=_boom)
    ctx = await agent.build_context({"boredom": 0.1}, [], idle=True)
    assert ctx.member_presence == []
