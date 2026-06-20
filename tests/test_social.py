# tests/test_social.py
"""Tests for SocialTracker."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from bot.discord.social import SocialTracker


def _make_graph(ready=False):
    graph = MagicMock()
    graph.ready = ready
    graph.add_episode = AsyncMock(return_value=None)
    return graph


def test_reply_tracked():
    tracker = SocialTracker(_make_graph())
    tracker.on_reply("Alice", "Bob")
    tracker.on_reply("Alice", "Bob")
    key = ("Alice", "Bob", "reply")
    assert tracker._buffer[key]["count"] == 2


def test_self_reaction_ignored():
    tracker = SocialTracker(_make_graph())
    tracker.on_reaction("Alice", "Alice")
    assert len(tracker._buffer) == 0


def test_mention_directional():
    """Mentions are directional — Zorro→Alice and Alice→Zorro are separate keys."""
    tracker = SocialTracker(_make_graph())
    tracker.on_mention("Zorro", "Alice")
    tracker.on_mention("Alice", "Zorro")
    assert tracker._buffer[("Zorro", "Alice", "mention")]["count"] == 1
    assert tracker._buffer[("Alice", "Zorro", "mention")]["count"] == 1


def test_voice_join_and_leave():
    tracker = SocialTracker(_make_graph())
    tracker.on_voice_join(100, 1, "Alice")
    tracker.on_voice_join(100, 2, "Bob")
    # Bob leaves — should record co-presence with Alice.
    # Buffer keys are ID-based (str snowflakes), normalized alphabetically.
    tracker.on_voice_leave(100, 2, "Bob")
    key = ("1", "2", "voice")
    assert tracker._buffer[key]["count"] == 1


def test_game_together():
    """Both users start the same game — one co-presence signal recorded."""
    tracker = SocialTracker(_make_graph())
    tracker.on_game_start("Alice", "Apex Legends")
    tracker.on_game_start("Bob", "Apex Legends")
    key = ("Alice", "Bob", "game")
    assert tracker._buffer[key]["count"] == 1
    assert tracker._buffer[key]["metadata"]["game"] == "Apex Legends"


@pytest.mark.asyncio
async def test_flush_sends_to_graph():
    graph = _make_graph(ready=True)
    tracker = SocialTracker(graph)
    tracker.on_reply("Alice", "Bob")
    tracker.on_mention("Alice", "Charlie")
    count = await tracker.flush()
    assert count == 2
    assert graph.add_episode.call_count == 2
    assert len(tracker._buffer) == 0


@pytest.mark.asyncio
async def test_flush_skips_when_not_ready():
    graph = _make_graph(ready=False)
    tracker = SocialTracker(graph)
    tracker.on_reply("Alice", "Bob")
    count = await tracker.flush()
    assert count == 0
    assert len(tracker._buffer) == 1  # Still buffered


def test_format_signal_templates():
    tracker = SocialTracker(_make_graph())
    result = tracker._format_signal("Alice", "Bob", "reply", {"count": 5, "metadata": {}})
    assert "Alice" in result
    assert "Bob" in result
    assert "5 fois" in result

    result = tracker._format_signal("Alice", "Bob", "game", {"count": 3, "metadata": {"game": "Apex"}})
    assert "Apex" in result


def test_self_thread_ignored():
    tracker = SocialTracker(_make_graph())
    tracker.on_thread_message("Alice", "Alice")
    assert len(tracker._buffer) == 0


def test_thread_tracked():
    tracker = SocialTracker(_make_graph())
    tracker.on_thread_message("Alice", "Bob")
    key = ("Alice", "Bob", "thread")
    assert tracker._buffer[key]["count"] == 1


def test_voice_leave_unknown_user():
    """Leaving a channel without joining should be a no-op."""
    tracker = SocialTracker(_make_graph())
    tracker.on_voice_leave(100, 999, "Ghost")
    assert len(tracker._buffer) == 0


@pytest.mark.asyncio
async def test_stop_flushes():
    graph = _make_graph(ready=True)
    tracker = SocialTracker(graph)
    tracker.on_reply("Alice", "Bob")
    await tracker.stop()
    assert graph.add_episode.call_count == 1
    assert len(tracker._buffer) == 0
