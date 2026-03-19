# tests/test_reaction_tracker.py
import time
from unittest.mock import MagicMock

import pytest

from bot.core.reaction_tracker import ReactionTracker


def make_emotion():
    engine = MagicMock()
    engine.apply_delta = MagicMock()
    return engine


def test_tier_delta_first_reaction():
    tracker = ReactionTracker(make_emotion())
    new_tier, delta = tracker._apply_tier_delta(1, 0)
    assert new_tier == 1
    assert delta == pytest.approx(0.05)


def test_tier_delta_escalation():
    tracker = ReactionTracker(make_emotion())
    new_tier, delta = tracker._apply_tier_delta(3, 1)
    assert new_tier == 2
    assert delta == pytest.approx(0.05)


def test_tier_delta_max():
    tracker = ReactionTracker(make_emotion())
    new_tier, delta = tracker._apply_tier_delta(6, 2)
    assert new_tier == 3
    assert delta == pytest.approx(0.05)


def test_tier_delta_same_tier_no_delta():
    tracker = ReactionTracker(make_emotion())
    new_tier, delta = tracker._apply_tier_delta(2, 1)
    assert new_tier == 1
    assert delta == 0.0


def test_discord_reaction_increments_and_applies_joy():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reaction(12345, "😂", is_bot=False)
    tracker.record_discord_reaction(12345, "🤣", is_bot=False)
    tracker.record_discord_reaction(12345, "🔥", is_bot=False)
    calls = emotion.apply_delta.call_args_list
    assert len(calls) == 2
    assert all(c[0][0] == "joy" for c in calls)


def test_discord_reaction_ignores_unknown_message():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.record_discord_reaction(99999, "😂", is_bot=False)
    emotion.apply_delta.assert_not_called()


def test_discord_reaction_ignores_negative_emoji():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reaction(12345, "👎", is_bot=False)
    emotion.apply_delta.assert_not_called()


def test_discord_reaction_ignores_bot():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reaction(12345, "😂", is_bot=True)
    emotion.apply_delta.assert_not_called()


def test_discord_reply_positive_keyword():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reply(12345, "mdr trop bien", is_bot=False)
    assert emotion.apply_delta.call_count == 1


def test_discord_reply_no_keyword():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reply(12345, "ok merci", is_bot=False)
    emotion.apply_delta.assert_not_called()


def test_twitch_window_active():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_twitch_response("twitch:channel1")
    tracker.check_twitch_message("twitch:channel1", "lol c'était drôle")
    assert emotion.apply_delta.call_count == 1


def test_twitch_window_expired():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_twitch_response("twitch:channel1")
    tracker._twitch_windows["twitch:channel1"].timestamp = time.time() - 130
    tracker.check_twitch_message("twitch:channel1", "lol")
    emotion.apply_delta.assert_not_called()


def test_twitch_window_reset_on_new_response():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_twitch_response("twitch:ch")
    tracker.check_twitch_message("twitch:ch", "mdr")
    tracker.track_twitch_response("twitch:ch")
    assert tracker._twitch_windows["twitch:ch"].count == 0
    assert tracker._twitch_windows["twitch:ch"].last_applied_tier == 0


def test_cleanup_removes_old_entries():
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(111)
    tracker._discord_messages[111].timestamp = time.time() - 700
    tracker.track_discord_message(222)
    assert 111 not in tracker._discord_messages
    assert 222 in tracker._discord_messages
