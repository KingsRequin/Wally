"""Un outil vocal doit s'autoriser contre celui qu'on traite, pas le dernier entendu.

L'exécuteur lisait `service._current_speaker_id`, un champ UNIQUE écrit à chaque
transcription. Deux façons de le rendre faux :

1. **déterministe** — `_maybe_respond` défile la file des paroles en attente et
   appelle `_respond_once(sid, …)` sans jamais réécrire le champ ; la parole
   défilée était donc traitée sous l'identité du dernier locuteur ENTENDU ;
2. **course** — pendant l'attente du LLM pour A, la parole de B arrive dans une
   autre tâche et écrase le champ.

Conséquences : `leave_voice` vérifiait « es-tu dans le salon ? » contre la
mauvaise personne, et `create_action_task` / `cancel_action_task` s'exécutaient
avec les rôles Discord d'un autre membre — escalade de privilèges si ce membre
est admin.

L'identité voyage désormais dans une `ContextVar` posée par `_respond_once` :
chaque `asyncio.Task` a sa propre copie du contexte.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from bot.discord.voice.tools import (
    reset_current_speaker,
    set_current_speaker,
)


@pytest.fixture(autouse=True)
def _contexte_propre():
    jeton = set_current_speaker(None)
    yield
    reset_current_speaker(jeton)


def _service(membres: list[int]):
    service = MagicMock()
    service.members_in_channel.return_value = membres
    service._current_speaker_id = None
    service._channel = None
    return service


def _executeur(service):
    from bot.discord.voice.tools import make_voice_tool_executor

    bot = MagicMock()
    # Le repli d'avant : « le dernier locuteur entendu ».
    return make_voice_tool_executor(
        bot, service, current_speaker_id=lambda: service._current_speaker_id
    )


async def test_le_tour_de_parole_impose_son_locuteur(monkeypatch):
    """Alice est dans le salon, Bob n'y est plus mais a parlé en dernier.

    On traite la parole d'ALICE. Sans la ContextVar, l'exécuteur lisait Bob et
    refusait — ou, dans l'autre sens, acceptait pour quelqu'un d'absent.
    """
    service = _service(membres=[111])          # seule Alice est présente
    service._current_speaker_id = "222"        # …mais Bob a parlé en dernier
    service.speak = MagicMock(return_value=asyncio.sleep(0))
    service.leave = MagicMock(return_value=asyncio.sleep(0))

    jeton = set_current_speaker("111")         # ce que fait `_respond_once`
    try:
        out = await _executeur(service)("leave_voice", "{}")
    finally:
        reset_current_speaker(jeton)

    assert '"ok"' in out                       # autorisé pour Alice, la bonne personne


async def test_un_locuteur_absent_du_salon_est_refuse():
    service = _service(membres=[111])
    service._current_speaker_id = "111"        # un membre présent a parlé en dernier

    jeton = set_current_speaker("999")         # mais c'est CE tour qu'on traite
    try:
        out = await _executeur(service)("leave_voice", "{}")
    finally:
        reset_current_speaker(jeton)

    assert '"denied"' in out                   # AVANT : autorisé, via le repli


async def test_deux_tours_concurrents_ne_se_melangent_pas():
    """Le cœur de la course : deux réponses en vol, chacune garde son locuteur."""
    vus: dict[str, str | None] = {}

    async def tour(sid: str, attente: float):
        jeton = set_current_speaker(sid)
        try:
            await asyncio.sleep(attente)       # l'attente du LLM
            from bot.discord.voice.tools import _CURRENT_SPEAKER
            vus[sid] = _CURRENT_SPEAKER.get()
        finally:
            reset_current_speaker(jeton)

    await asyncio.gather(tour("111", 0.02), tour("222", 0.01))

    assert vus == {"111": "111", "222": "222"}
