import pytest
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
        synth.speak_text_async.return_value.get.return_value = result
        sdk.SpeechSynthesizer.return_value = synth
        tts = AzureTTS(key="k", region="r", voice="fr-FR-DeniseNeural")
        audio = await tts.synthesize("salut")
        assert audio == b"PCMDATA"

def test_build_uses_config():
    cfg = VoiceConfig(language="fr-FR", azure_voice="fr-FR-DeniseNeural")
    with patch("bot.discord.voice.providers.speechsdk"), \
         patch.dict("os.environ", {"AZURE_SPEECH_KEY": "k", "AZURE_SPEECH_REGION": "r"}):
        assert isinstance(build_stt(cfg), AzureSTT)
        assert isinstance(build_tts(cfg), AzureTTS)
