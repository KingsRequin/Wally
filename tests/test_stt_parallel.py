"""Parallélisme du STT local.

Mesuré en live à trois locuteurs : le calcul ne coûte que ~2 s par énoncé, mais
l'attente en file en ajoutait jusqu'à 13. Le goulot n'était pas le modèle.
"""
import asyncio

import pytest

from bot.discord.voice.providers import FasterWhisperSTT


def _stt(parallel):
    return FasterWhisperSTT(model_size="small", parallel=parallel)


@pytest.mark.asyncio
async def test_deux_transcriptions_avancent_de_front():
    stt = _stt(2)
    ordre = []

    async def _faux(pcm):
        ordre.append("début")
        await asyncio.sleep(0.05)
        ordre.append("fin")
        return "ok"

    # On remplace le calcul, pas la file : c'est elle qu'on teste.
    async def _transcribe(pcm):
        async with stt._sem:
            return await _faux(pcm)

    await asyncio.gather(_transcribe(b""), _transcribe(b""))
    # De front : les deux démarrent avant qu'aucune ne finisse.
    assert ordre[:2] == ["début", "début"]


@pytest.mark.asyncio
async def test_le_parallelisme_reste_borne():
    """Sans borne, quatre locuteurs sur-souscriraient le CPU et la latence
    repartirait dans l'autre sens."""
    stt = _stt(2)
    actifs, pic = 0, 0

    async def _tache():
        nonlocal actifs, pic
        async with stt._sem:
            actifs += 1
            pic = max(pic, actifs)
            await asyncio.sleep(0.02)
            actifs -= 1

    await asyncio.gather(*(_tache() for _ in range(6)))
    assert pic == 2


def test_un_parallelisme_absurde_est_ramene_a_un():
    assert _stt(0)._parallel == 1
    assert _stt(-3)._parallel == 1


def test_le_chargement_du_modele_reste_serialise():
    """Deux chargements concurrents doubleraient la mémoire occupée."""
    stt = _stt(2)
    assert stt._model_guard is not None
    assert stt._load_lock is not None
