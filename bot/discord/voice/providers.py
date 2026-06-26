import asyncio
import os
from typing import Protocol

import azure.cognitiveservices.speech as speechsdk
from loguru import logger

from bot.config import VoiceConfig


class SpeechToText(Protocol):
    async def transcribe(self, pcm16k_mono: bytes) -> str: ...


class TextToSpeech(Protocol):
    async def synthesize(self, text: str, style: str | None = None) -> bytes: ...


def _azure_creds() -> tuple[str, str]:
    key = os.environ.get("AZURE_SPEECH_KEY", "")
    region = os.environ.get("AZURE_SPEECH_REGION", "")
    if not key or not region:
        raise RuntimeError("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION manquants dans .env")
    return key, region


class AzureSTT:
    """STT Azure. Entrée : PCM 16 kHz mono 16-bit. Sortie : texte (vide si rien)."""

    def __init__(self, key: str, region: str, language: str, phrases: list[str] | None = None) -> None:
        self._key, self._region, self._language = key, region, language
        self._phrases = [p for p in (phrases or []) if p]  # indices (nom du bot, surnoms)

    async def transcribe(self, pcm16k_mono: bytes) -> str:
        return await asyncio.to_thread(self._transcribe_sync, pcm16k_mono)

    def _transcribe_sync(self, pcm16k_mono: bytes) -> str:
        try:
            fmt = speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1
            )
            stream = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
            audio_cfg = speechsdk.audio.AudioConfig(stream=stream)
            speech_cfg = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
            speech_cfg.speech_recognition_language = self._language
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_cfg, audio_config=audio_cfg
            )
            # Indices de phrase : biaise la reconnaissance vers le nom de Wally et ses surnoms.
            if self._phrases:
                grammar = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
                for phrase in self._phrases:
                    grammar.addPhrase(phrase)
            stream.write(pcm16k_mono)
            stream.close()
            result = recognizer.recognize_once()
            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                return result.text or ""
            return ""
        except Exception as e:  # noqa: BLE001
            logger.warning("AzureSTT.transcribe a échoué: {e}", e=e)
            return ""


class AzureTTS:
    """TTS Azure Neural. Sortie : PCM 48 kHz mono 16-bit (prêt pour Discord)."""

    def __init__(self, key: str, region: str, voice: str) -> None:
        self._key, self._region, self._voice = key, region, voice

    async def synthesize(self, text: str, style: str | None = None) -> bytes:
        return await asyncio.to_thread(self._synthesize_sync, text, style)

    def _build_ssml(self, text: str, style: str | None) -> str:
        from xml.sax.saxutils import escape, quoteattr
        lang = "-".join(self._voice.split("-")[:2]) or "fr-FR"
        inner = escape(text)
        if style:
            inner = f'<mstts:express-as style={quoteattr(style)}>{inner}</mstts:express-as>'
        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="https://www.w3.org/2001/mstts" '
            f'xml:lang="{lang}"><voice name={quoteattr(self._voice)}>{inner}</voice></speak>'
        )

    def _synthesize_sync(self, text: str, style: str | None = None) -> bytes:
        try:
            speech_cfg = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
            speech_cfg.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm
            )
            synth = speechsdk.SpeechSynthesizer(speech_config=speech_cfg, audio_config=None)
            result = synth.speak_ssml_async(self._build_ssml(text, style)).get()
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                return result.audio_data
            logger.warning("AzureTTS: synthèse non complétée ({r})", r=result.reason)
            return b""
        except Exception as e:  # noqa: BLE001
            logger.warning("AzureTTS.synthesize a échoué: {e}", e=e)
            return b""


def build_stt(cfg: VoiceConfig, phrases: list[str] | None = None) -> SpeechToText:
    key, region = _azure_creds()
    return AzureSTT(key=key, region=region, language=cfg.language, phrases=phrases)


def build_tts(cfg: VoiceConfig) -> TextToSpeech:
    key, region = _azure_creds()
    return AzureTTS(key=key, region=region, voice=cfg.azure_voice)
