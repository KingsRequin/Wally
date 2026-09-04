# tests/test_voice_style_impose.py
"""Un ton IMPOSÉ à `speak()` prime sur l'humeur et sur le tag de tête (2026-09-04).

Il existe pour le texte qui n'est PAS de Wally : le TTS acheté aux points de
chaîne porte le ton voulu par le viewer, mais son message est enchâssé dans un
gabarit (« untel dit : … »). Un tag laissé dans le texte ne serait donc plus en
tête, et `parse_style_tag` ne le verrait jamais — le ton voyage en DONNÉE.

Il passe par `adapt_style` comme tous les autres : un `express-as` que la voix
montée ignore fait rendre à Azure un flux VIDE sans lever, et Wally deviendrait
muet sans un mot dans les logs.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _svc(voix="fr-FR-Marc:MAI-Voice-2-Flash", humeur=None):
    from bot.discord.voice.service import VoiceService
    svc = VoiceService.__new__(VoiceService)
    svc._vc = MagicMock()
    svc._bot = MagicMock()
    svc._bot.emotion.get_state.return_value = humeur or {}
    svc._bot.emotion.get_secondary_emotions.return_value = []
    svc.listen_only = False
    svc.is_speaking = False
    svc.quota = MagicMock()
    svc._speak_lock = asyncio.Lock()
    svc._tts = MagicMock()
    svc._tts.style_voice = voix
    svc._tts.synthesize_stream = None
    svc._tts.synthesize = AsyncMock(return_value=b"")
    return svc


async def _style_utilise(svc, texte, **kw):
    """Le style réellement passé à la synthèse, quel que soit le chemin."""
    vu = {}

    async def _faux(text, style=None, **_):
        vu["style"] = style
        return False

    svc._tts.synthesize = AsyncMock(side_effect=_faux)
    await svc.speak(texte, **kw)
    return vu.get("style")


@pytest.mark.asyncio
async def test_le_ton_impose_prime_sur_l_humeur():
    svc = _svc(humeur={"joy": 0.9})
    assert await _style_utilise(svc, "alice dit : bonjour", style="angry") == "angry"


@pytest.mark.asyncio
async def test_sans_ton_impose_l_humeur_decide():
    svc = _svc(humeur={"joy": 0.9})
    assert await _style_utilise(svc, "alice dit : bonjour") == "joyful"


@pytest.mark.asyncio
async def test_un_ton_que_la_voix_ignore_ne_rend_pas_muet():
    """Voix sans aucun style : le ton imposé est abandonné, pas envoyé —
    Azure rendrait un flux vide sans lever."""
    svc = _svc(voix="fr-FR-VivienneNeural")
    assert await _style_utilise(svc, "alice dit : bonjour", style="angry") is None


@pytest.mark.asyncio
async def test_un_ton_impose_est_ramene_aux_capacites_de_la_voix():
    """Henri ne connaît pas `angry` ; `adapt_style` le ramène à `excited`."""
    svc = _svc(voix="fr-FR-HenriNeural")
    assert await _style_utilise(svc, "alice dit : bonjour", style="angry") == "excited"
