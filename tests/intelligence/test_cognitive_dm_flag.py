from unittest.mock import MagicMock
from bot.intelligence.cognitive_loop import CognitiveLoop


def make_loop():
    return CognitiveLoop(MagicMock(), MagicMock(), MagicMock())


def test_notify_activity_marks_dm():
    loop = make_loop()
    loop.notify_activity(999, "KingsRequin", "coucou en privé", is_dm=True)
    assert loop._recent_interactions[-1]["is_dm"] is True


def test_notify_activity_public_default_not_dm():
    loop = make_loop()
    loop.notify_activity(111, "KingsRequin", "coucou public")
    assert loop._recent_interactions[-1]["is_dm"] is False
