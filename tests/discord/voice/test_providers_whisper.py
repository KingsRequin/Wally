"""Tests du provider STT local faster-whisper (lazy load, conversion PCM, routing build_stt)."""
import numpy as np
import pytest

from bot.config import VoiceConfig
from bot.discord.voice import providers
from bot.discord.voice.providers import FasterWhisperSTT, AzureSTT, build_stt


class _FakeSeg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    """Modèle factice : capture l'audio reçu, renvoie deux segments."""
    def __init__(self):
        self.received_audio = None
        self.received_kwargs = None

    def transcribe(self, audio, **kwargs):
        self.received_audio = audio
        self.received_kwargs = kwargs
        return ([_FakeSeg(" Salut"), _FakeSeg(" Wally")], {})


# ----------------------------------------------------------------------
# Routing build_stt
# ----------------------------------------------------------------------

def test_build_stt_route_vers_whisper():
    cfg = VoiceConfig(stt_provider="faster_whisper")
    stt = build_stt(cfg, phrases=["Wally"])
    assert isinstance(stt, FasterWhisperSTT)


def test_build_stt_route_vers_azure_par_defaut(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "westeurope")
    cfg = VoiceConfig(stt_provider="azure")
    assert isinstance(build_stt(cfg), AzureSTT)


# ----------------------------------------------------------------------
# Configuration du provider
# ----------------------------------------------------------------------

def test_langue_reduite_au_code_court():
    stt = FasterWhisperSTT(model_size="small", language="fr-FR")
    assert stt._lang == "fr"


def test_initial_prompt_biaise_vers_le_nom():
    stt = FasterWhisperSTT(model_size="small", language="fr-FR", phrases=["Wally", "wally"])
    assert "Wally" in (stt._initial_prompt or "")


def test_init_ne_charge_pas_le_modele():
    # Lazy : aucune inférence/téléchargement tant qu'on ne transcrit pas.
    stt = FasterWhisperSTT(model_size="small", language="fr-FR")
    assert stt._model is None


# ----------------------------------------------------------------------
# Transcription
# ----------------------------------------------------------------------

async def test_transcribe_convertit_pcm_en_float32_et_joint_les_segments():
    stt = FasterWhisperSTT(model_size="small", language="fr-FR", phrases=["Wally"])
    fake = _FakeModel()
    stt._model = fake  # court-circuite le chargement réel

    pcm = np.array([0, 16384, -16384], dtype=np.int16).tobytes()
    text = await stt.transcribe(pcm)

    assert text == "Salut Wally"  # segments joints + strip
    # PCM 16-bit → float32 normalisé dans [-1, 1]
    assert fake.received_audio.dtype == np.float32
    np.testing.assert_allclose(fake.received_audio, [0.0, 0.5, -0.5], atol=1e-4)
    assert fake.received_kwargs.get("language") == "fr"


async def test_transcribe_renvoie_vide_sur_erreur():
    stt = FasterWhisperSTT(model_size="small", language="fr-FR")

    class _Boom:
        def transcribe(self, *a, **k):
            raise RuntimeError("boom")

    stt._model = _Boom()
    assert await stt.transcribe(b"\x00\x00") == ""
