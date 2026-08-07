import contextlib

import pytest
from loguru import logger
from unittest.mock import MagicMock, patch
from bot.config import VoiceConfig
from bot.discord.voice.providers import AzureSTT, AzureTTS, build_stt, build_tts

@pytest.mark.asyncio
async def test_azure_stt_returns_recognized_text():
    with patch("bot.discord.voice.providers.speechsdk") as sdk:
        recognizer = MagicMock()
        result = MagicMock()
        result.reason = sdk.ResultReason.RecognizedSpeech
        result.text = "bonjour wally"
        recognizer.recognize_once.return_value = result
        sdk.SpeechRecognizer.return_value = recognizer
        stt = AzureSTT(key="k", region="r", language="fr-FR")
        text = await stt.transcribe(b"\x00\x00" * 1600)
        assert text == "bonjour wally"

@pytest.mark.asyncio
async def test_azure_stt_empty_on_nomatch():
    with patch("bot.discord.voice.providers.speechsdk") as sdk:
        recognizer = MagicMock()
        result = MagicMock()
        result.reason = sdk.ResultReason.NoMatch
        recognizer.recognize_once.return_value = result
        sdk.SpeechRecognizer.return_value = recognizer
        stt = AzureSTT(key="k", region="r", language="fr-FR")
        assert await stt.transcribe(b"\x00\x00" * 1600) == ""

@pytest.mark.asyncio
async def test_azure_tts_returns_audio_bytes():
    with patch("bot.discord.voice.providers.speechsdk") as sdk:
        synth = MagicMock()
        result = MagicMock()
        result.reason = sdk.ResultReason.SynthesizingAudioCompleted
        result.audio_data = b"PCMDATA"
        synth.speak_ssml_async.return_value.get.return_value = result
        sdk.SpeechSynthesizer.return_value = synth
        tts = AzureTTS(key="k", region="r", voice="fr-FR-Marc:MAI-Voice-2")
        audio = await tts.synthesize("salut", style="whispering")
        assert audio == b"PCMDATA"
        # le SSML envoyé contient bien la voix et le style
        ssml = synth.speak_ssml_async.call_args.args[0]
        assert "fr-FR-Marc:MAI-Voice-2" in ssml
        assert 'style="whispering"' in ssml

def test_build_uses_config():
    cfg = VoiceConfig(language="fr-FR", azure_voice="fr-FR-DeniseNeural")
    with patch("bot.discord.voice.providers.speechsdk"), \
         patch.dict("os.environ", {"AZURE_SPEECH_KEY": "k", "AZURE_SPEECH_REGION": "r"}):
        assert isinstance(build_stt(cfg), AzureSTT)
        assert isinstance(build_tts(cfg), AzureTTS)


@contextlib.contextmanager
def _capture_logs():
    """Capture loguru — `caplog` ne voit que le `logging` de la stdlib."""
    lines: list[str] = []
    sink_id = logger.add(lambda m: lines.append(m), level="WARNING")
    try:
        yield lines
    finally:
        logger.remove(sink_id)


@pytest.mark.asyncio
async def test_le_streaming_signale_une_synthese_annulee():
    """Un flux annulé par Azure rendait ZÉRO octet, sans exception ni log.

    Vécu le 2026-08-07 : la clé Azure Speech est devenue invalide (401 au
    handshake WebSocket). Le SDK ne lève pas — il rend un flux vide. Wally
    jouait donc son bip, générait sa réplique, l'inscrivait au dashboard… et
    aucun son ne sortait, sans la moindre trace dans les logs. Le chemin batch
    vérifie `result.reason` depuis toujours ; le chemin streaming, non.
    """
    with patch("bot.discord.voice.providers.speechsdk") as sdk:
        synth = MagicMock()
        synth.start_speaking_ssml_async.return_value.get.return_value = MagicMock()
        sdk.SpeechSynthesizer.return_value = synth
        stream = MagicMock()
        stream.read_data.return_value = 0          # aucun octet produit
        stream.status = sdk.StreamStatus.Canceled
        stream.cancellation_details = MagicMock(
            reason="CancellationReason.Error",
            error_details="WebSocket upgrade failed: Authentication error (401).",
        )
        sdk.AudioDataStream.return_value = stream

        chunks: list[bytes] = []
        tts = AzureTTS(key="k", region="r", voice="fr-FR-Marc:MAI-Voice-2")
        with _capture_logs() as lines:
            await tts.synthesize_stream("salut", None, chunks.append)

        assert chunks == []
        assert any("401" in line for line in lines), \
            "le motif d'annulation Azure doit apparaître dans les logs"


@pytest.mark.asyncio
async def test_le_streaming_signale_une_synthese_muette():
    """Zéro octet sans annulation explicite doit quand même se voir."""
    with patch("bot.discord.voice.providers.speechsdk") as sdk:
        synth = MagicMock()
        synth.start_speaking_ssml_async.return_value.get.return_value = MagicMock()
        sdk.SpeechSynthesizer.return_value = synth
        stream = MagicMock()
        stream.read_data.return_value = 0
        stream.status = sdk.StreamStatus.AllData
        stream.cancellation_details = None
        sdk.AudioDataStream.return_value = stream

        tts = AzureTTS(key="k", region="r", voice="fr-FR-Marc:MAI-Voice-2")
        with _capture_logs() as lines:
            await tts.synthesize_stream("salut", None, lambda _b: None)

        assert any("aucun audio" in line.lower() for line in lines)
