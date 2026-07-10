"""L'id de ping (<@id>) est dérivé du user_key et accolé à la mémoire du participant."""
import pytest

from bot.intelligence.attention_agent import AttentionAgent


class _Fact:
    def __init__(self, content):
        self.content = content


class _FakeFacts:
    async def search_by_category(self, *a, **k):
        return []

    async def get_latest_by_source(self, *a, **k):
        return None

    async def get_by_user(self, key, *a, **k):
        # Faits pour un participant Discord ; rien pour wally:self (relations).
        if key == "discord:973346229138382878":
            return [_Fact("joue à Apex")]
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
async def test_participant_memory_carries_discord_mention(monkeypatch):
    _neutralize_io(monkeypatch)
    agent = AttentionAgent(_FakeFacts())
    interactions = [
        {"author": "Cluth", "content": "gg", "channel": "c",
         "user_key": "discord:973346229138382878"},
    ]
    ctx = await agent.build_context({"boredom": 0.1}, interactions)
    assert len(ctx.participant_memories) == 1
    assert ctx.participant_memories[0]["mention"] == "<@973346229138382878>"
    assert ctx.participant_memories[0]["author"] == "Cluth"


@pytest.mark.asyncio
async def test_participant_memory_twitch_key_has_no_mention(monkeypatch):
    _neutralize_io(monkeypatch)

    class _TwitchFacts(_FakeFacts):
        async def get_by_user(self, key, *a, **k):
            if key == "twitch:keychka":
                return [_Fact("stream le soir")]
            return []

    agent = AttentionAgent(_TwitchFacts())
    interactions = [
        {"author": "keychka", "content": "yo", "channel": "c",
         "user_key": "twitch:keychka"},
    ]
    ctx = await agent.build_context({"boredom": 0.1}, interactions)
    assert ctx.participant_memories[0]["mention"] == ""
