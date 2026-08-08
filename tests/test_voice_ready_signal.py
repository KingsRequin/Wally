# tests/test_voice_ready_signal.py
"""Savoir à partir de quand Wally entend vraiment.

Le modèle STT se charge APRÈS l'arrivée dans le salon, en tâche détachée : Wally
est là, la connexion est établie, mais les premières phrases se perdent. Rien ne
le signalait.

Il rejoint donc en sourdine et se démute une fois prêt — visible d'un coup d'œil
dans la liste du vocal, et silencieux : un bip s'entendrait sur le stream.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.voice.readiness import signal_ready_when_warm


def _vc():
    vc = MagicMock()
    vc.guild.change_voice_state = AsyncMock()
    vc.channel = MagicMock()
    return vc


@pytest.mark.asyncio
async def test_il_se_demute_une_fois_le_modele_charge():
    vc = _vc()
    chauffe = asyncio.Event()

    async def _warm():
        await chauffe.wait()

    tache = asyncio.create_task(signal_ready_when_warm(vc, _warm()))
    await asyncio.sleep(0)
    vc.guild.change_voice_state.assert_not_awaited()   # pas encore prêt

    chauffe.set()
    await tache

    vc.guild.change_voice_state.assert_awaited_once()
    assert vc.guild.change_voice_state.await_args.kwargs["self_mute"] is False


@pytest.mark.asyncio
async def test_un_prechauffage_en_echec_le_demute_quand_meme():
    """Mieux vaut l'annoncer prêt à tort que le laisser muet pour toujours."""
    vc = _vc()

    async def _boom():
        raise RuntimeError("modèle introuvable")

    await signal_ready_when_warm(vc, _boom())

    vc.guild.change_voice_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_salon_quitte_entre_temps_ne_fait_pas_planter():
    vc = _vc()
    vc.channel = None

    async def _warm():
        return None

    await signal_ready_when_warm(vc, _warm())      # ne lève pas
    vc.guild.change_voice_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_sans_prechauffage_il_est_pret_tout_de_suite():
    vc = _vc()
    await signal_ready_when_warm(vc, None)
    vc.guild.change_voice_state.assert_awaited_once()


# ── attendre le modèle ne suffit pas ────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_transcription_a_blanc_precede_le_demute():
    """Le modèle se charge en deux exemplaires ; on n'en attendait qu'un.

    Faire passer un silence dans la chaîne complète est le seul signal qui ne
    dépende pas du nombre d'objets à réveiller."""
    vc = _vc()
    stt = MagicMock()
    stt._fallback = None
    stt.transcribe = AsyncMock(return_value="")

    await signal_ready_when_warm(vc, None, stt)

    stt.transcribe.assert_awaited_once()
    vc.guild.change_voice_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_c_est_le_repli_local_qui_est_chauffe():
    """En mode distant, c'est lui qui porte le modèle — et qui met du temps."""
    vc = _vc()
    fallback = MagicMock()
    fallback.transcribe = AsyncMock(return_value="")
    streaming = MagicMock()
    streaming._fallback = fallback

    await signal_ready_when_warm(vc, None, streaming)

    fallback.transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_une_transcription_a_blanc_ratee_demute_quand_meme():
    vc = _vc()
    stt = MagicMock()
    stt._fallback = None
    stt.transcribe = AsyncMock(side_effect=RuntimeError("modèle absent"))

    await signal_ready_when_warm(vc, None, stt)

    vc.guild.change_voice_state.assert_awaited_once()
