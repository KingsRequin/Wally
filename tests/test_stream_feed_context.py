# tests/test_stream_feed_context.py
"""Le flux passif du stream arrive bien dans les contextes de Wally :
prompt système (Discord / web / Twitch) et contexte cognitif (tick)."""
import pytest

import bot.core.stream_feed as sf
from bot.core.stream_feed import StreamFeed
from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.prompts import PromptBuilder
from bot.intelligence.reasoning_agent import ReasoningAgent

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}


@pytest.fixture(autouse=True)
def _reset_active():
    sf._active = None
    yield
    sf._active = None


def _activate_feed():
    feed = StreamFeed("Azrael_TTV")
    feed.activate()
    feed.record("Azrael_TTV change de jeu : Apex Legends → Warhammer: Darktide")
    feed.record_chat("bob", "gg les gars")
    return feed


# ── Prompt système ────────────────────────────────────────────────────────────

def test_feed_injected_in_system_prompt():
    _activate_feed()
    out = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Flux du stream (perception passive)" in out
    assert "Warhammer: Darktide" in out
    assert "[bob] gg les gars" in out


def test_no_feed_block_without_active_feed():
    out = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Flux du stream" not in out


def test_chat_lines_dropped_on_twitch_home_path():
    """Sur la chaîne du stream, le prélude porte déjà le chat — pas de doublon,
    mais les événements du live restent visibles."""
    _activate_feed()
    out = PromptBuilder().build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        situation={"platform": "Twitch", "stream_live": True,
                   "stream_category": "Warhammer: Darktide"},
    )
    assert "Warhammer: Darktide" in out
    assert "[bob]" not in out


# ── Contexte cognitif ─────────────────────────────────────────────────────────

def _ctx(**kw):
    base = dict(
        emotion_state={"boredom": 0.1}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
    )
    base.update(kw)
    return AttentionContext(**base)


def test_reasoning_renders_stream_feed():
    agent = ReasoningAgent.__new__(ReasoningAgent)  # pas d'I/O constructeur
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {}
    feed = _activate_feed()
    text = agent._format_context(_ctx(stream_feed=feed.render()))
    assert "Warhammer: Darktide" in text
    assert "tu ne réagis pas" in text


def test_reasoning_without_stream_feed():
    agent = ReasoningAgent.__new__(ReasoningAgent)
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {}
    assert "Flux du stream" not in agent._format_context(_ctx())


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


async def test_attention_context_carries_stream_feed(monkeypatch):
    """build_context lit le flux actif sans injection de dépendance."""
    from bot.intelligence.attention_agent import AttentionAgent

    _neutralize_io(monkeypatch)
    _activate_feed()
    ctx = await AttentionAgent(_FakeFacts()).build_context({"boredom": 0.1}, [])
    assert ctx.stream_feed is not None
    assert "Warhammer: Darktide" in ctx.stream_feed
    assert "[bob] gg les gars" in ctx.stream_feed


async def test_stream_feed_never_creates_interactions(monkeypatch):
    """Le flux est un contexte, pas un événement : il n'ajoute rien aux
    interactions récentes et ne réveille donc pas la cadence cognitive."""
    from bot.intelligence.attention_agent import AttentionAgent

    _neutralize_io(monkeypatch)
    _activate_feed()
    ctx = await AttentionAgent(_FakeFacts()).build_context({"boredom": 0.1}, [])
    assert ctx.recent_interactions == []


async def test_attention_context_without_feed(monkeypatch):
    from bot.intelligence.attention_agent import AttentionAgent

    _neutralize_io(monkeypatch)
    ctx = await AttentionAgent(_FakeFacts()).build_context({"boredom": 0.1}, [])
    assert ctx.stream_feed is None
