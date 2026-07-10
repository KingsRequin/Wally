# tests/test_prompt_stream_awareness.py
import pytest

import bot.core.stream_watcher as sw
from bot.core.stream_watcher import StreamWatcher
from bot.intelligence.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
_LIVE = {
    "live": True, "title": "Ranked grind", "category": "Apex Legends",
    "viewers": 50, "started_at": "2026-07-10T18:00:00Z",
}


@pytest.fixture(autouse=True)
def _reset_active():
    sw._active = None
    yield
    sw._active = None


def _activate_live():
    w = StreamWatcher(twitch_api=None, streamer_name="Azrael_TTV")
    w._status = dict(_LIVE)
    w.activate()
    return w


def test_awareness_injected_when_live():
    _activate_live()
    result = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "EN LIVE" in result
    assert "Azrael_TTV" in result
    assert "Apex Legends" in result


def test_no_awareness_when_no_watcher():
    result = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "EN LIVE" not in result


def test_awareness_skipped_on_twitch_home_situational_block():
    """Sur la chaîne home (situation.stream_live), le bloc situationnel annonce
    déjà le live — l'awareness corporelle ne doit pas doubler."""
    _activate_live()
    result = PromptBuilder().build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        situation={"platform": "Twitch", "stream_live": True,
                   "stream_category": "Apex Legends", "stream_title": "Ranked grind"},
    )
    # une seule occurrence de la catégorie (bloc situationnel), pas deux
    assert result.count("Tu le sais car tu surveilles sa chaîne") == 0
