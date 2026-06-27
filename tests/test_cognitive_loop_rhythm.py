import pytest

from bot.intelligence.cognitive_loop import CognitiveLoop, _speak_pass_probability


def test_speak_pass_probability_curve():
    # haute réceptivité → toujours passer ; basse → rare
    assert _speak_pass_probability(0.5) == pytest.approx(1.0)
    assert _speak_pass_probability(0.4) == pytest.approx(1.0)
    assert _speak_pass_probability(0.05) < 0.2
    assert _speak_pass_probability(0.0) == pytest.approx(0.0)


class _SR:
    def __init__(self, r):
        self._r = r
        self.incoming = 0
        self.outcomes = []

    def record_incoming(self, when):
        self.incoming += 1

    def record_spontaneous_outcome(self, answered, when):
        self.outcomes.append(answered)

    def receptivity(self, when):
        return self._r


def test_notify_activity_feeds_rhythm():
    sr = _SR(0.5)
    loop = CognitiveLoop(None, None, None, social_rhythm=sr)
    loop.notify_activity(1, "bob", "hello")
    assert sr.incoming == 1


def test_idle_ceiling_grows_when_receptivity_low():
    low = CognitiveLoop(None, None, None, emotion_engine=None, social_rhythm=_SR(0.02))
    high = CognitiveLoop(None, None, None, emotion_engine=None, social_rhythm=_SR(0.9))
    # forcer l'état idle (pas d'activité récente)
    low._last_relevant_activity_ts = 0.0
    high._last_relevant_activity_ts = 0.0
    # max sur plusieurs tirages (intervalle aléatoire) : la borne basse doit être plus haute
    lows = max(low._tick_interval() for _ in range(50))
    highs = max(high._tick_interval() for _ in range(50))
    assert lows >= highs
