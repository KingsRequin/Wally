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


def test_pas_de_biais_nom_en_initial_prompt():
    # Anti-hallucination : on n'injecte PAS le nom en initial_prompt, sinon Whisper
    # ressort « Wally wally » sur le bruit (ventilateur).
    stt = FasterWhisperSTT(model_size="small", language="fr-FR", phrases=["Wally", "wally"])
    assert getattr(stt, "_initial_prompt", None) is None


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
    # Anti-hallucination : VAD interne (Silero) actif, pas de conditionnement sur le passé.
    assert fake.received_kwargs.get("vad_filter") is True
    assert fake.received_kwargs.get("condition_on_previous_text") is False
    assert fake.received_kwargs.get("initial_prompt") is None


async def test_transcribe_renvoie_vide_sur_erreur():
    stt = FasterWhisperSTT(model_size="small", language="fr-FR")

    class _Boom:
        def transcribe(self, *a, **k):
            raise RuntimeError("boom")

    stt._model = _Boom()
    assert await stt.transcribe(b"\x00\x00") == ""


async def test_transcribe_serialise_les_appels_concurrents():
    """Une seule transcription à la fois (évite la sur-souscription CPU / les pics aléatoires)."""
    import asyncio
    import threading

    stt = FasterWhisperSTT(model_size="small", language="fr-FR")
    started = []
    gate = threading.Event()

    class _SlowModel:
        def transcribe(self, audio, **k):
            started.append(1)
            if len(started) == 1:
                gate.wait(timeout=2)  # le 1er bloque le thread
            return ([_FakeSeg("x")], {})

    stt._model = _SlowModel()
    pcm = b"\x00\x00" * 100
    t1 = asyncio.create_task(stt.transcribe(pcm))
    await asyncio.sleep(0.1)
    t2 = asyncio.create_task(stt.transcribe(pcm))
    await asyncio.sleep(0.1)
    assert len(started) == 1  # le 2e attend le lock, n'a pas démarré
    gate.set()
    await t1
    await t2
    assert len(started) == 2


async def test_warmup_precharge_le_modele(monkeypatch):
    stt = FasterWhisperSTT(model_size="small", language="fr-FR")
    loaded = []

    def fake_ensure():
        loaded.append(1)
        stt._model = "X"
        return "X"

    monkeypatch.setattr(stt, "_ensure_model", fake_ensure)
    await stt.warmup()
    assert loaded == [1]


def test_cpu_threads_transmis_au_modele(monkeypatch):
    import sys
    import types
    captured = {}

    class _FakeWhisperModel:
        def __init__(self, size, **kwargs):
            captured["size"] = size
            captured.update(kwargs)

    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)

    stt = FasterWhisperSTT(model_size="base", language="fr-FR", cpu_threads=4)
    stt._ensure_model()
    assert captured["size"] == "base"
    assert captured["cpu_threads"] == 4
