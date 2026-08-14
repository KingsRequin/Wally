"""Une phrase entendue en vocal n'est PAS un événement du live.

Vécu le 2026-08-08 : « du monde débarque, tenez-vous bien » s'affichait sur
l'overlay sans le moindre raid — 30 fois dans la journée. À chaque occurrence,
la bulle suivait d'une seconde une simple phrase de conversation entendue en
vocal.

Le vocal envoyait chaque phrase à `on_stream_event()`, dont le prompt AFFIRME au
modèle qu'il reçoit « un événement qui vient de se produire sur le live : un
raid, un abonnement, des bits, un changement de jeu ou de titre ». Sommé de
ranger « Euh... je ne sais pas si ce serait » dans ces catégories, le modèle
prenait la plus générique et recopiait l'exemple du raid. Il n'inventait pas :
on lui mentait sur la nature de ce qu'on lui donnait.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_voice_listen_only import _service


@pytest.mark.asyncio
async def test_le_vocal_ne_passe_plus_par_le_prompt_des_evenements():
    svc = _service()
    svc.listen_only = True
    svc._vc = MagicMock()
    narrator = MagicMock()
    narrator.count_spoken_vote.return_value = False
    narrator.on_stream_event = AsyncMock(return_value=None)
    narrator.on_overheard = AsyncMock(return_value=None)
    svc._bot.overlay_narrator = narrator

    with patch("bot.core.stream_feed.active_stream_feed", return_value=MagicMock()), \
         patch("bot.discord.voice.service.handle_transcript", new=AsyncMock()):
        user = SimpleNamespace(id=42, display_name="Azrael", name="azrael")
        await svc._dispatch_transcript(user, "euh je sais pas si ce serait", 120.0)
        await asyncio.sleep(0)

    narrator.on_overheard.assert_awaited()
    narrator.on_stream_event.assert_not_awaited()


def _narrator():
    from bot.intelligence.overlay_narrator import OverlayNarrator

    n = OverlayNarrator.__new__(OverlayNarrator)
    n._feed = MagicMock()
    n._recent_bubbles = __import__("collections").deque(maxlen=8)
    n._may_react = lambda: True
    n._mark_spoken = lambda: None
    n._is_repeat = lambda text: False
    n._remember_bubble = lambda text: None
    return n


@pytest.mark.asyncio
async def test_une_bribe_de_conversation_a_son_propre_cadrage():
    """Le prompt des événements décrit un raid/sub/bits : l'y faire passer
    poussait le modèle à inventer un événement qui n'existait pas."""
    from bot.intelligence.overlay_narrator import _EVENT_SYSTEM

    n = _narrator()
    seen = {}

    async def _condense(text, system=None, **_):
        seen["system"] = system
        return "il raconte n'importe quoi"

    n._condense = _condense
    await n.on_overheard("Azraël (vocal) : euh je sais pas")

    assert seen["system"] is not _EVENT_SYSTEM
    # Le cadrage doit NIER l'événement, pas l'énumérer comme une liste de choix.
    assert "pas un événement" in seen["system"].lower()


@pytest.mark.asyncio
async def test_les_vrais_evenements_gardent_leur_cadrage():
    """La régression à éviter : un vrai raid doit continuer d'être annoncé."""
    from bot.intelligence.overlay_narrator import _EVENT_SYSTEM

    n = _narrator()
    seen = {}

    async def _condense(text, system=None, **_):
        seen["system"] = system
        return "du monde débarque"

    n._condense = _condense
    await n.on_stream_event("Un raid de 42 personnes arrive de chez Untel")

    assert seen["system"] is _EVENT_SYSTEM
    n._feed.say.assert_called_once()


@pytest.mark.asyncio
async def test_la_parole_entendue_nallume_pas_les_trois_points():
    """Le vocal passe ici à chaque phrase : des trois-points à chaque fois
    clignoteraient toute la soirée, la plupart sans bulle derrière."""
    n = _narrator()

    async def _condense(text, system=None, **_):
        return None  # le silence, cas normal sur du vocal

    n._condense = _condense
    await n.on_overheard("Azraël (vocal) : mouais bof")

    n._feed.thinking.assert_not_called()


@pytest.mark.asyncio
async def test_la_parole_entendue_nagite_pas_lavatar():
    """`react('stream_event')` fait s'emballer l'avatar : réservé aux vrais
    moments forts, pas à chaque phrase prononcée pendant une partie."""
    n = _narrator()

    async def _condense(text, system=None, **_):
        return "mouais"

    n._condense = _condense
    await n.on_overheard("Azraël (vocal) : un raid de fou dans ce jeu")

    assert not any(c.args and c.args[0] == "stream_event"
                   for c in n._feed.react.call_args_list)
