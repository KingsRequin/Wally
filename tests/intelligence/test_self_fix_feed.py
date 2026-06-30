from unittest.mock import MagicMock

from bot.intelligence.self_fix import SelfFix, _next_threshold_crossed


def _selffix(feed):
    bot = MagicMock()
    bot.cognitive_feed = feed
    return SelfFix(MagicMock(), bot)


# --- _next_threshold_crossed (fonction pure) ---

def test_threshold_none_below_first():
    assert _next_threshold_crossed(10, 0) is None


def test_threshold_first_crossed():
    assert _next_threshold_crossed(30, 0) == 25


def test_threshold_second_crossed():
    assert _next_threshold_crossed(60, 25) == 50


def test_threshold_third_crossed():
    assert _next_threshold_crossed(80, 50) == 75


def test_threshold_same_palier_not_republished():
    assert _next_threshold_crossed(80, 75) is None


def test_threshold_highest_crossed_returned():
    assert _next_threshold_crossed(100, 0) == 75


# --- _publish_feed (best-effort) ---

def test_publish_feed_emits_codefix():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._publish_feed("test detail", full="le goal")
    feed.publish.assert_called_once()
    evt = feed.publish.call_args.args[0]
    assert evt["type"] == "CODEFIX"
    assert evt["detail"] == "test detail"
    assert evt["full"] == "le goal"


def test_publish_feed_no_full_key_when_absent():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._publish_feed("sans full")
    evt = feed.publish.call_args.args[0]
    assert "full" not in evt


def test_publish_feed_no_feed_is_noop():
    bot = MagicMock()
    bot.cognitive_feed = None
    sf = SelfFix(MagicMock(), bot)
    sf._publish_feed("x")  # ne doit pas lever


def test_publish_feed_swallows_exception():
    feed = MagicMock()
    feed.publish.side_effect = Exception("boom")
    sf = _selffix(feed)
    sf._publish_feed("x")  # ne doit pas lever


# --- _maybe_publish_progress (seuils + état) ---

def test_progress_crosses_first_threshold():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._maybe_publish_progress(30)
    assert sf._last_feed_pct == 25
    feed.publish.assert_called_once()
    assert "25" in feed.publish.call_args.args[0]["detail"]


def test_progress_no_double_publish_same_palier():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._maybe_publish_progress(30)   # franchit 25
    feed.publish.reset_mock()
    sf._maybe_publish_progress(45)   # toujours dans le palier 25 (< 50)
    feed.publish.assert_not_called()
    assert sf._last_feed_pct == 25


def test_progress_below_first_threshold_silent():
    feed = MagicMock()
    sf = _selffix(feed)
    sf._maybe_publish_progress(10)
    feed.publish.assert_not_called()
    assert sf._last_feed_pct == 0
