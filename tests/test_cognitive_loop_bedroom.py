"""Routage « chambre » des prises de parole spontanées de la boucle cognitive.

Tout SPEAK cognitif doit partir dans le salon dédié de Wally (bedroom), jamais
dans le canal courant. Les gardes « anti-vide » (silence idle, messages sans
réponse) ne s'appliquent pas à la chambre — c'est son espace d'expression.
"""

import time
from types import SimpleNamespace

import pytest

from bot.intelligence.cognitive_loop import CognitiveLoop
from bot.intelligence.meta_agent import MetaDecision


class _FakeAttention:
    async def build_context(self, *args, **kwargs):
        return SimpleNamespace()


class _FakeReasoning:
    def __init__(self, decisions):
        self._decisions = decisions

    async def reason(self, context):
        return SimpleNamespace(
            thought_text="une pensée",
            decisions=self._decisions,
            thought_fact_id=None,
        )


class _RecordingDispatcher:
    def __init__(self):
        self.dispatched = []

    async def dispatch(self, decision):
        self.dispatched.append(decision)


def _make_loop(decisions, bedroom_channel_id=None, speakable=None):
    loop = CognitiveLoop(
        _FakeAttention(),
        _FakeReasoning(decisions),
        _RecordingDispatcher(),
        bedroom_channel_id=bedroom_channel_id,
        speakable_channels=speakable or set(),
    )
    # Rester "actif" : aucune garde idle+silence ne doit interférer.
    loop._last_relevant_activity_ts = time.monotonic()
    loop._last_activity_ts = 0.0  # évite la garde idle+silence>2h (branche non-chambre)
    return loop


@pytest.mark.asyncio
async def test_speak_redirige_vers_chambre():
    """Un SPEAK visant un canal quelconque est renvoyé dans la chambre."""
    decision = MetaDecision(action="SPEAK", channel_id="999", message="coucou le monde")
    loop = _make_loop([decision], bedroom_channel_id=123)

    await loop._tick()

    dispatched = loop._dispatcher.dispatched
    assert len(dispatched) == 1
    assert dispatched[0].action == "SPEAK"
    assert dispatched[0].channel_id == "123"


@pytest.mark.asyncio
async def test_speak_chambre_ignore_cooldown_sans_reponse():
    """Dans la chambre, la garde « 3 messages sans réponse » ne bloque jamais."""
    loop = _make_loop([], bedroom_channel_id=123)
    # Simuler une chambre déjà saturée de messages sans réponse.
    loop._spontaneous["123"] = {"last_ts": time.monotonic(), "unanswered": 5}
    loop._reasoning = _FakeReasoning(
        [MetaDecision(action="SPEAK", channel_id="123", message="encore une pensée")]
    )

    await loop._tick()

    assert len(loop._dispatcher.dispatched) == 1
    assert loop._dispatcher.dispatched[0].channel_id == "123"


@pytest.mark.asyncio
async def test_speak_sans_chambre_reste_sur_place():
    """Sans chambre configurée, le routage historique est préservé."""
    decision = MetaDecision(action="SPEAK", channel_id="999", message="dans le canal")
    loop = _make_loop([decision], bedroom_channel_id=None, speakable={"999"})

    await loop._tick()

    dispatched = loop._dispatcher.dispatched
    assert len(dispatched) == 1
    assert dispatched[0].channel_id == "999"


@pytest.mark.asyncio
async def test_speak_sans_chambre_applique_blocage_sans_reponse():
    """Sans chambre, un canal public ignoré (3 sans réponse) reste bloqué."""
    loop = _make_loop([], bedroom_channel_id=None, speakable={"999"})
    loop._spontaneous["999"] = {"last_ts": time.monotonic(), "unanswered": 5}
    loop._reasoning = _FakeReasoning(
        [MetaDecision(action="SPEAK", channel_id="999", message="ignoré")]
    )

    await loop._tick()

    assert loop._dispatcher.dispatched == []
