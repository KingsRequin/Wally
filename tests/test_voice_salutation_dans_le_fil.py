"""En vocal, Wally dit bonjour en arrivant — puis n'écoute plus personne.

Symptôme de l'owner (2026-08-30) : « quand je fais venir Wally en vocal il dit
bonjour, mais ensuite il ne répond pas quand je lui parle. »

Sa salutation partait par `service.speak()` en direct, sans passer par
`_remember_line()` — pourtant décrit comme le point d'écriture UNIQUE du fil.
Elle n'entrait donc NI dans `service.history` (le fil LLM), NI dans le tampon de
contexte écrit.

Or `_should_respond_voice` n'ouvre l'échange que sur trois conditions : on le
nomme, c'est une question, ou il est intervenu dans les deux tours précédents.
La troisième ne pouvait jamais s'amorcer : pour le vocal, Wally n'avait rien
dit. Il fallait le nommer à chaque phrase, alors qu'il venait de saluer.

Même chemin pour `greet_newcomer` (quelqu'un arrive, Wally le salue, sa réponse
tombe dans le vide) et pour `say_in_voice` (un modérateur le fait parler ; on
lui répond, il ne sait pas ce qu'il a dit).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.discord.voice.brain import _remember_line, _should_respond_voice
from bot.discord.voice.service import VoiceService


def _service():
    with patch.object(VoiceService, "_build_stt_pipeline", lambda *a, **k: None), \
         patch("bot.discord.voice.service.build_tts", lambda cfg: MagicMock()), \
         patch("bot.discord.voice.service._ensure_opus", lambda: None), \
         patch("bot.discord.voice.service.make_voice_tool_executor", lambda *a, **k: None):
        bot = MagicMock()
        bot.config.bot.name = "Wally"
        bot.config.bot.trigger_names = ["wally"]
        cfg = SimpleNamespace(vad_aggressiveness=2, vad_silence_timeout_s=1.0,
                              auto_leave_minutes=5)
        svc = VoiceService(bot, cfg)
    svc._vc = MagicMock()
    svc._channel = SimpleNamespace(id=7, name="Général", members=[])
    return svc


def _dit(svc, texte: str):
    """Fait prononcer `texte` par le chemin réel, TTS et Discord coupés."""
    return patch("bot.discord.voice.service.generate_voice_greeting",
                 new=AsyncMock(return_value=texte)), \
        patch.object(VoiceService, "speak", new=AsyncMock(return_value=True))


@pytest.mark.asyncio
async def test_la_salutation_d_arrivee_entre_dans_le_fil():
    svc = _service()
    gen, parle = _dit(svc, "Salut, vous faites quoi ?")
    with gen, parle:
        await svc._greet()
    assert [(m["role"], m["content"]) for m in svc.history] == [
        ("assistant", "Salut, vous faites quoi ?")]


@pytest.mark.asyncio
async def test_apres_son_bonjour_il_repond_sans_qu_on_le_nomme():
    """L'enchaînement RÉEL, celui que l'owner a vécu : il salue, on lui répond.

    Le test isolé de `_should_respond_voice` passait déjà — il reçoit un fil
    qu'on lui fabrique. Ce qui manquait, c'est la séquence : ce fil-là n'était
    jamais celui que produisait une arrivée en vocal.
    """
    svc = _service()
    gen, parle = _dit(svc, "Salut, vous faites quoi ?")
    with gen, parle:
        await svc._greet()

    parole = "ouais je suis là, tranquille"
    _remember_line(svc, role="user", speaker="KingsRequin", text=parole)
    assert _should_respond_voice(parole, svc.history, named=False)


@pytest.mark.asyncio
async def test_la_salutation_d_un_nouveau_venu_entre_aussi_dans_le_fil():
    svc = _service()
    gen, parle = _dit(svc, "Tiens, salut Méliodas.")
    with gen, parle:
        await svc.greet_newcomer(SimpleNamespace(id=9, display_name="Méliodas"))
    assert [m["role"] for m in svc.history] == ["assistant"]


@pytest.mark.asyncio
async def test_en_mode_ecoute_il_ne_salue_pas_et_ne_consigne_rien():
    """Le fil ne doit JAMAIS contenir une réplique qu'il n'a pas prononcée.

    En mode compagnon de stream, `speak()` refuse : la salutation générée était
    jetée. Elle coûtait un appel LLM à CHAQUE arrivée dans le salon, pour rien —
    et la consigner maintenant ferait croire au modèle qu'il a parlé pendant le
    live.
    """
    svc = _service()
    svc.listen_only = True
    with patch("bot.discord.voice.service.generate_voice_greeting",
               new=AsyncMock(return_value="Salut !")) as gen:
        await svc.greet_newcomer(SimpleNamespace(id=9, display_name="Méliodas"))
    gen.assert_not_awaited()
    assert svc.history == []


@pytest.mark.asyncio
async def test_ce_qu_un_moderateur_lui_fait_dire_entre_dans_le_fil():
    """`say_in_voice` : on lui répond, il doit savoir ce qu'il vient de dire."""
    from bot.discord.voice.tools import run_say_in_voice_tool

    svc = _service()   # `_vc` posé par `_service()` → `is_connected` vrai
    svc.speak = AsyncMock(return_value=True)
    bot = SimpleNamespace(voice_service=svc)
    sortie = await run_say_in_voice_tool(
        bot, {"text": "les gars, le stream commence"}, roles=["moderator"], maison=True)
    assert "C'est dit" in sortie
    assert [(m["role"], m["content"]) for m in svc.history] == [
        ("assistant", "les gars, le stream commence")]
