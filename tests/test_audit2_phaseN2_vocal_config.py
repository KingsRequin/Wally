# tests/test_audit2_phaseN2_vocal_config.py
"""Phase N2 du second audit : vocal et configuration.

A2-ready — un timeout sur `ready` n'armait ni le backoff ni le repli : deux
           WebSockets en vol en permanence contre un serveur figé.
A2-vad   — le segment VAD n'avait aucun plafond : 32 Ko/s par locuteur sans fin.
A2-int   — `int(speaker)` sans garde cassait l'appel d'outil `leave_voice`.
A2-cfg   — `POST /config` laissait la config à moitié appliquée quand une
           validation échouait plus loin.
"""
import inspect
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException


# ────────────────────────────── A2-ready ──────────────────────────────
def test_un_timeout_ready_compte_comme_injoignable():
    from bot.discord.voice.streaming import RemoteSTTSession

    src = inspect.getsource(RemoteSTTSession.start)
    i = src.index("asyncio.TimeoutError")
    assert "self.unreachable = True" in src[i:i + 800]


# ────────────────────────────── A2-vad ──────────────────────────────
def test_le_segment_vocal_est_plafonne():
    from bot.discord.voice.audio import _MAX_SEGMENT_BYTES, SAMPLE_RATE

    # 30 s d'audio 16 bits mono : au-delà, ce n'est plus un énoncé.
    assert _MAX_SEGMENT_BYTES == SAMPLE_RATE * 2 * 30


def test_une_parole_continue_finit_par_etre_coupee():
    from bot.discord.voice.audio import FRAME_BYTES, VadSegmenter, _MAX_SEGMENT_BYTES

    seg = VadSegmenter.__new__(VadSegmenter)
    seg._vad = MagicMock()
    seg._vad.is_speech = MagicMock(return_value=True)   # jamais de silence
    seg._rate = 16000
    seg._voiced = bytearray()
    seg._in_speech = False
    seg._silence_run = 0

    emis = None
    frames = _MAX_SEGMENT_BYTES // FRAME_BYTES + 2
    for _ in range(frames):
        out = seg.feed(b"\x00" * FRAME_BYTES)
        if out is not None:
            emis = out
            break
    assert emis is not None, "le tampon grossit sans borne"
    assert len(seg._voiced) == 0, "le tampon n'a pas été vidé"


# ────────────────────────────── A2-int ──────────────────────────────
def test_un_identifiant_de_locuteur_non_numerique_ne_casse_pas_l_outil():
    from bot.discord.voice import tools

    src = inspect.getsource(tools)
    assert "except (TypeError, ValueError):" in src
    assert "if speaker is None or int(speaker) not in" not in src


# ────────────────────────────── A2-cfg ──────────────────────────────
@pytest.mark.asyncio
async def test_une_validation_ratee_ne_laisse_rien_derriere_elle():
    from bot.dashboard.routes.admin import update_config

    class _Role:
        def __init__(self):
            self.temperature = 0.8
            self.model = "m"

    class _Cfg:
        def __init__(self):
            self.openai = SimpleNamespace(temperature=0.8)
            self.llm = SimpleNamespace(primary=_Role(), secondary=_Role())

        def save(self):
            raise AssertionError("save() ne doit pas être atteint")

    requete = MagicMock()
    etat = requete.app.state.wally
    etat.config = _Cfg()
    etat.llm = MagicMock(temperature=0.8)
    etat.llm_secondary = MagicMock(temperature=0.8)

    # `temperature` valide (appliquée), puis `reasoning_effort` invalide (lève).
    with pytest.raises(HTTPException):
        await update_config(requete, {
            "openai": {"temperature": 1.5, "reasoning_effort": "n'importe quoi"},
        })

    assert etat.config.openai.temperature == 0.8, "mutation conservée après un 400"


def test_la_restauration_couvre_aussi_les_clients_vivants():
    from bot.dashboard.routes import admin

    src = inspect.getsource(admin.update_config)
    assert "copy.deepcopy(cfg)" in src
    assert "_restaurer_clients_llm(state, _avant)" in src
