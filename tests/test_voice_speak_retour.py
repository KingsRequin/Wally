# tests/test_voice_speak_retour.py
"""`speak()` DIT si la parole est sortie (2026-08-20).

Elle rendait `None` sur tous ses chemins : pas de salon, mode écoute seule,
texte vidé par le nettoyage de style, timeout du TTS, panne Azure. `say_in_voice`
répondait donc « c'est dit à voix haute » à un modérateur devant un silence — le
symétrique exact du `is_sent: false` côté chat Twitch, que ce projet a déjà payé
une fois.

La récompense « im out » en dépend pour rembourser : c'est ce qui a rendu le
défaut visible.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _svc(monkeypatch):
    from bot.discord.voice.service import VoiceService
    svc = VoiceService.__new__(VoiceService)
    svc._vc = MagicMock()
    svc._bot = MagicMock()
    svc.listen_only = False
    svc.is_speaking = False
    svc.quota = MagicMock()
    svc._speak_lock = __import__("asyncio").Lock()
    return svc


@pytest.mark.asyncio
async def test_sans_salon_la_parole_n_est_pas_sortie(monkeypatch):
    svc = _svc(monkeypatch)
    svc._vc = None
    assert await svc.speak("bonsoir") is False


@pytest.mark.asyncio
async def test_en_mode_ecoute_la_parole_n_est_pas_sortie(monkeypatch):
    svc = _svc(monkeypatch)
    svc.listen_only = True
    assert await svc.speak("bonsoir") is False


@pytest.mark.asyncio
async def test_un_texte_vide_n_est_pas_une_parole(monkeypatch):
    svc = _svc(monkeypatch)
    assert await svc.speak("") is False


@pytest.mark.asyncio
async def test_une_parole_jouee_rend_vrai(monkeypatch):
    svc = _svc(monkeypatch)
    svc._speak_locked = AsyncMock(return_value=True)
    assert await svc.speak("bonsoir") is True


@pytest.mark.asyncio
async def test_une_synthese_en_panne_rend_faux(monkeypatch):
    svc = _svc(monkeypatch)
    svc._speak_locked = AsyncMock(return_value=False)
    assert await svc.speak("bonsoir") is False
