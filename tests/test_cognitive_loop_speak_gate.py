"""Coupure de la prise de parole spontanée de la boucle cognitive.

`spontaneous_channel_speak_enabled=False` (défaut) : Wally garde sa vie mentale
(THINK/feed) mais n'exprime plus ses pensées de sa propre initiative dans un
canal — fini les monologues « Question qui me trotte… » dans le vide.

Deux exceptions survivent à la coupure :
  - un rappel programmé arrivé à échéance (`forced_seed`) : service demandé, pas
    un monologue → le SPEAK passe ;
  - flag remis à True : comportement historique restauré.
"""

import time
from datetime import datetime
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


class _DueFactStore:
    """fact_store minimal qui remonte un rappel arrivé à échéance."""

    def __init__(self, due):
        self._due = due
        self.cleared = []

    async def get_due_facts(self, _now):
        return self._due

    async def clear_schedule(self, fid):
        self.cleared.append(fid)


def _make_loop(decisions, *, speak_enabled=False, bedroom_channel_id=123,
               speakable=None, fact_store=None):
    loop = CognitiveLoop(
        _FakeAttention(),
        _FakeReasoning(decisions),
        _RecordingDispatcher(),
        bedroom_channel_id=bedroom_channel_id,
        speakable_channels=speakable or set(),
        fact_store=fact_store,
        spontaneous_channel_speak_enabled=speak_enabled,
    )
    loop._last_relevant_activity_ts = time.monotonic()
    loop._last_activity_ts = 0.0
    return loop


@pytest.mark.asyncio
async def test_speak_spontane_supprime_par_defaut():
    """Flag off (défaut) + pas de rappel → le monologue est supprimé."""
    decision = MetaDecision(action="SPEAK", channel_id="123", message="Question qui me trotte…")
    loop = _make_loop([decision], speak_enabled=False)

    await loop._tick()

    assert loop._dispatcher.dispatched == []


@pytest.mark.asyncio
async def test_speak_rappel_du_passe_malgre_coupure():
    """Un rappel programmé arrivé à échéance (forced_seed) reste dit."""
    fact = SimpleNamespace(content="appeler le médecin", id=42)
    store = _DueFactStore([fact])
    decision = MetaDecision(action="SPEAK", channel_id="123", message="rappel : appeler le médecin")
    loop = _make_loop([decision], speak_enabled=False, fact_store=store)

    await loop._tick()

    assert len(loop._dispatcher.dispatched) == 1
    assert loop._dispatcher.dispatched[0].channel_id == "123"
    assert store.cleared == [42]


@pytest.mark.asyncio
async def test_speak_passe_quand_flag_active():
    """Flag on → comportement historique : le SPEAK est dispatché."""
    decision = MetaDecision(action="SPEAK", channel_id="999", message="coucou")
    loop = _make_loop([decision], speak_enabled=True, bedroom_channel_id=123)

    await loop._tick()

    assert len(loop._dispatcher.dispatched) == 1
    # Toujours redirigé vers la chambre quand elle est configurée.
    assert loop._dispatcher.dispatched[0].channel_id == "123"


@pytest.mark.asyncio
async def test_act_dm_non_affecte_par_la_coupure():
    """La coupure ne vise que les SPEAK : un ACT (ex. DM owner) passe."""
    decision = MetaDecision(action="ACT", message="dm owner")
    loop = _make_loop([decision], speak_enabled=False)

    await loop._tick()

    assert len(loop._dispatcher.dispatched) == 1
    assert loop._dispatcher.dispatched[0].action == "ACT"
