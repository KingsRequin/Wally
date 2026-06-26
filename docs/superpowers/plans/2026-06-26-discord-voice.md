# Wally Vocal (Discord) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à Wally d'écouter et parler dans les salons vocaux Discord, en réutilisant son cerveau existant (gate cognitif + reasoning + persona + émotions + mémoire).

**Architecture:** Deux transducteurs (STT en entrée, TTS en sortie) greffés autour du pipeline cognitif existant. La parole entrante est transcrite → passe par `gate.decide()` → si `RESPOND`, un assembleur de contexte vocal dédié génère la réponse via `llm.complete_with_tools()` → synthétisée en voix. STT/TTS derrière une interface interchangeable (Azure en v1).

**Tech Stack:** discord.py + `discord-ext-voice-recv` (réception audio, non native), `PyNaCl`, `azure-cognitiveservices-speech` (STT+TTS), `webrtcvad` (segmentation), FFmpeg/libopus.

## Global Constraints

- Python 3.12 (Dockerfile `python:3.12-slim` — `audioop` disponible).
- discord.py>=2.3.2 ; ne PAS migrer vers Pycord.
- Logging : `loguru` exclusivement, jamais `print()` ni `logging`.
- Tous les handlers : try/except, log, continue — jamais de crash.
- Secrets dans `.env`, jamais commités (`AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`).
- Format tools LLM : OpenAI Chat Completions (`{"type":"function","function":{...}}`).
- Aucun appel réseau réel dans les tests (mock du SDK Azure et du sink).
- Un seul salon vocal actif à la fois (v1).
- Auto-leave après 2 min sans parole.
- Spec de référence : `docs/superpowers/specs/2026-06-26-discord-voice-design.md`.

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `bot/discord/voice/__init__.py` | Exports du module |
| `bot/discord/voice/providers.py` | Interfaces `SpeechToText`/`TextToSpeech` + `AzureSTT`/`AzureTTS` |
| `bot/discord/voice/audio.py` | Resample 48k stéréo→16k mono + `VadSegmenter` |
| `bot/discord/voice/sink.py` | `WallyAudioSink` (réception PCM par locuteur) |
| `bot/discord/voice/service.py` | `VoiceService` : cycle de vie join/leave, état, mapping ssrc→user, auto-leave |
| `bot/discord/voice/brain.py` | `generate_voice_reply()` + `handle_transcript()` (branchement gate→TTS) |
| `bot/discord/voice/tools.py` | Outils LLM `join_voice`/`leave_voice` + executor |
| `bot/discord/commands/voice_cmd.py` | `VoiceCog` : `/wally join`, `/wally leave` |
| `bot/config.py` (modif) | `VoiceConfig` dataclass + load/save |
| `bot/discord/bot.py` (modif) | `intents.voice_states`, instanciation `VoiceService`, `add_cog(VoiceCog)` |
| `requirements.txt` / `Dockerfile` (modif) | Dépendances Python + système |
| `tests/discord/voice/test_*.py` | Tests unitaires par module |

---

## Task 1: Dépendances, config socle & intents

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`
- Modify: `bot/config.py` (ajout `VoiceConfig`, load ~ligne 396, save ~ligne 460)
- Modify: `bot/discord/bot.py:42-46` (intents)
- Test: `tests/test_config.py` (ou nouveau `tests/discord/voice/test_voice_config.py`)

**Interfaces:**
- Produces: `VoiceConfig` dataclass avec champs `enabled: bool`, `stt_provider: str`, `tts_provider: str`, `language: str`, `azure_voice: str`, `auto_leave_minutes: int`, `vad_aggressiveness: int` ; accessible via `config.voice`.

- [ ] **Step 1: Écrire le test de config échouant**

```python
# tests/discord/voice/test_voice_config.py
import yaml
from bot.config import Config, VoiceConfig

def test_voice_config_defaults_when_section_absent(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    base = _minimal_valid_config_dict()  # copie d'un dict config valide existant, sans clé "voice"
    cfg_file.write_text(yaml.dump(base))
    cfg = Config.load(str(cfg_file))
    assert isinstance(cfg.voice, VoiceConfig)
    assert cfg.voice.enabled is False
    assert cfg.voice.auto_leave_minutes == 2

def test_voice_config_roundtrip(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    base = _minimal_valid_config_dict()
    base["voice"] = {"enabled": True, "language": "fr-FR", "auto_leave_minutes": 2}
    cfg_file.write_text(yaml.dump(base))
    cfg = Config.load(str(cfg_file))
    cfg.save()
    reloaded = Config.load(str(cfg_file))
    assert reloaded.voice.enabled is True
    assert reloaded.voice.language == "fr-FR"
```

> `_minimal_valid_config_dict()` : réutiliser le fixture/dict déjà utilisé par les tests config existants (voir `tests/test_config.py`). Si absent, charger `config.example.yaml`.

- [ ] **Step 2: Lancer le test → échec**

Run: `pytest tests/discord/voice/test_voice_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'VoiceConfig'`

- [ ] **Step 3: Ajouter `VoiceConfig` dans `bot/config.py`**

Près des autres dataclasses imbriquées (à côté de `SpamDetectionConfig`, ~ligne 79) :

```python
@dataclass
class VoiceConfig:
    enabled: bool = False
    stt_provider: str = "azure"
    tts_provider: str = "azure"
    language: str = "fr-FR"
    azure_voice: str = "fr-FR-DeniseNeural"  # voix FR à affiner plus tard
    auto_leave_minutes: int = 2
    vad_aggressiveness: int = 2  # webrtcvad 0..3
```

Ajouter le champ sur la classe `Config` (avec les autres champs, default factory) :

```python
    voice: VoiceConfig = field(default_factory=VoiceConfig)
```

Dans `Config.load()` (~ligne 396, à côté du pattern `discord`/`spam_detection`) :

```python
            voice_raw = dict(raw.get("voice", {}))
```

et dans l'appel `cls(...)` ajouter :

```python
                voice=VoiceConfig(**voice_raw),
```

Dans `Config.save()` (~ligne 460), ajouter à `data` :

```python
            "voice": asdict(self.voice),
```

- [ ] **Step 4: Lancer le test → succès**

Run: `pytest tests/discord/voice/test_voice_config.py -v`
Expected: PASS

- [ ] **Step 5: Ajouter les dépendances**

Dans `requirements.txt`, sous `# Discord` :

```txt
# Discord
discord.py>=2.3.2
discord-ext-voice-recv==0.5.2a179  # uniquement des pré-releases publiées ; pinner la version exacte (sinon pip rejette)
PyNaCl>=1.5.0

# Voice (STT/TTS)
azure-cognitiveservices-speech>=1.40.0
webrtcvad>=2.0.10
```

Dans `Dockerfile`, remplacer la ligne `apt-get install` par :

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata docker.io \
    ffmpeg libopus0 libopus-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 6: Activer l'intent voice_states**

Dans `bot/discord/bot.py` (après ligne 45) :

```python
        intents.voice_states = True  # rejoindre/quitter salons vocaux + détecter membres en VC
```

- [ ] **Step 7: Vérifier l'install et committer**

Run: `pip install -r requirements.txt && python -c "import nacl, webrtcvad, azure.cognitiveservices.speech, discord.ext.voice_recv"`
Expected: aucun ImportError

```bash
git add requirements.txt Dockerfile bot/config.py bot/discord/bot.py tests/discord/voice/test_voice_config.py
git commit -m "feat(voice): deps, VoiceConfig et intent voice_states"
```

---

## Task 2: Abstraction provider STT/TTS + implémentation Azure

**Files:**
- Create: `bot/discord/voice/__init__.py`
- Create: `bot/discord/voice/providers.py`
- Test: `tests/discord/voice/test_providers.py`

**Interfaces:**
- Consumes: `VoiceConfig` (Task 1) ; env `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`.
- Produces:
  - `class SpeechToText(Protocol)` : `async def transcribe(self, pcm16k_mono: bytes) -> str`
  - `class TextToSpeech(Protocol)` : `async def synthesize(self, text: str) -> bytes` (PCM 48k mono 16-bit pour le playback Discord)
  - `class AzureSTT(SpeechToText)` ctor `(key: str, region: str, language: str)`
  - `class AzureTTS(TextToSpeech)` ctor `(key: str, region: str, voice: str)`
  - `def build_stt(cfg: VoiceConfig) -> SpeechToText` / `def build_tts(cfg: VoiceConfig) -> TextToSpeech`

- [ ] **Step 1: Écrire le test échouant (mock du SDK Azure)**

```python
# tests/discord/voice/test_providers.py
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
```

- [ ] **Step 2: Lancer → échec**

Run: `pytest tests/discord/voice/test_providers.py -v`
Expected: FAIL — module `bot.discord.voice.providers` introuvable

- [ ] **Step 3: Implémenter `providers.py`**

```python
# bot/discord/voice/__init__.py
"""Module vocal Discord : écoute (STT), parole (TTS), branchement cerveau."""
```

```python
# bot/discord/voice/providers.py
import asyncio
import os
from typing import Protocol

import azure.cognitiveservices.speech as speechsdk
from loguru import logger

from bot.config import VoiceConfig


class SpeechToText(Protocol):
    async def transcribe(self, pcm16k_mono: bytes) -> str: ...


class TextToSpeech(Protocol):
    async def synthesize(self, text: str) -> bytes: ...


def _azure_creds() -> tuple[str, str]:
    key = os.environ.get("AZURE_SPEECH_KEY", "")
    region = os.environ.get("AZURE_SPEECH_REGION", "")
    if not key or not region:
        raise RuntimeError("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION manquants dans .env")
    return key, region


class AzureSTT:
    """STT Azure. Entrée : PCM 16 kHz mono 16-bit. Sortie : texte (vide si rien)."""

    def __init__(self, key: str, region: str, language: str) -> None:
        self._key, self._region, self._language = key, region, language

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

    async def synthesize(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> bytes:
        try:
            speech_cfg = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
            speech_cfg.speech_synthesis_voice_name = self._voice
            speech_cfg.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm
            )
            synth = speechsdk.SpeechSynthesizer(speech_config=speech_cfg, audio_config=None)
            result = synth.speak_text_async(text).get()
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                return result.audio_data
            logger.warning("AzureTTS: synthèse non complétée ({r})", r=result.reason)
            return b""
        except Exception as e:  # noqa: BLE001
            logger.warning("AzureTTS.synthesize a échoué: {e}", e=e)
            return b""


def build_stt(cfg: VoiceConfig) -> SpeechToText:
    key, region = _azure_creds()
    return AzureSTT(key=key, region=region, language=cfg.language)


def build_tts(cfg: VoiceConfig) -> TextToSpeech:
    key, region = _azure_creds()
    return AzureTTS(key=key, region=region, voice=cfg.azure_voice)
```

- [ ] **Step 4: Lancer → succès**

Run: `pytest tests/discord/voice/test_providers.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Committer**

```bash
git add bot/discord/voice/__init__.py bot/discord/voice/providers.py tests/discord/voice/test_providers.py
git commit -m "feat(voice): abstraction STT/TTS + impl Azure"
```

---

## Task 3: Utilitaires audio — resample + VAD segmenter

**Files:**
- Create: `bot/discord/voice/audio.py`
- Test: `tests/discord/voice/test_audio.py`

**Interfaces:**
- Produces:
  - `def to_stt_format(pcm48k_stereo: bytes) -> bytes` — 48k stéréo 16-bit → 16k mono 16-bit (pour `AzureSTT.transcribe`).
  - `class VadSegmenter` ctor `(aggressiveness: int, sample_rate: int = 16000)` ; `feed(pcm16k_mono_frame: bytes) -> bytes | None` (renvoie un segment de parole complet quand un silence le clôt, sinon `None`) ; `flush() -> bytes | None`.
  - Constante `FRAME_MS = 20` et `FRAME_BYTES` (taille d'une frame 20 ms à 16 kHz mono 16-bit = 640 octets).

- [ ] **Step 1: Écrire le test échouant**

```python
# tests/discord/voice/test_audio.py
from bot.discord.voice.audio import to_stt_format, VadSegmenter, FRAME_BYTES

def test_to_stt_format_halves_then_downsamples():
    # 48k stéréo 16-bit : 1 frame stéréo = 4 octets. 480 frames = 10ms.
    pcm = b"\x01\x02\x03\x04" * 480
    out = to_stt_format(pcm)
    # mono 16k : ~1/6 de la taille d'origine en octets (stéréo→mono /2, 48k→16k /3)
    assert 0 < len(out) <= len(pcm) // 5
    assert len(out) % 2 == 0

def test_vad_segmenter_emits_on_silence(monkeypatch):
    import bot.discord.voice.audio as audio
    # Mock webrtcvad : 'parole' tant que la frame n'est pas tout-zéro
    class FakeVad:
        def __init__(self, agg): pass
        def is_speech(self, frame, rate): return frame != b"\x00" * len(frame)
    monkeypatch.setattr(audio.webrtcvad, "Vad", FakeVad)
    seg = VadSegmenter(aggressiveness=2)
    speech = b"\x11\x22" * (FRAME_BYTES // 2)
    silence = b"\x00" * FRAME_BYTES
    assert seg.feed(speech) is None       # parole, on accumule
    assert seg.feed(speech) is None
    out = None
    # plusieurs frames de silence clôturent le segment
    for _ in range(20):
        out = seg.feed(silence) or out
    assert out is not None and len(out) >= FRAME_BYTES
```

- [ ] **Step 2: Lancer → échec**

Run: `pytest tests/discord/voice/test_audio.py -v`
Expected: FAIL — module introuvable

- [ ] **Step 3: Implémenter `audio.py`**

```python
# bot/discord/voice/audio.py
import audioop

import webrtcvad

FRAME_MS = 20
SAMPLE_RATE = 16000
FRAME_BYTES = int(SAMPLE_RATE * (FRAME_MS / 1000)) * 2  # 16-bit mono → 640 octets
_SILENCE_FRAMES_TO_CUT = 15  # ~300 ms de silence clôt un segment


def to_stt_format(pcm48k_stereo: bytes) -> bytes:
    """Discord fournit du PCM 48 kHz stéréo 16-bit ; Azure STT veut 16 kHz mono."""
    mono = audioop.tomono(pcm48k_stereo, 2, 0.5, 0.5)
    converted, _ = audioop.ratecv(mono, 2, 1, 48000, SAMPLE_RATE, None)
    return converted


class VadSegmenter:
    """Découpe un flux PCM 16 kHz mono en segments de parole délimités par les silences."""

    def __init__(self, aggressiveness: int, sample_rate: int = SAMPLE_RATE) -> None:
        self._vad = webrtcvad.Vad(aggressiveness)
        self._rate = sample_rate
        self._buf = bytearray()
        self._voiced = bytearray()
        self._silence_run = 0
        self._in_speech = False

    def feed(self, frame: bytes) -> bytes | None:
        """Alimente une frame de 20 ms (FRAME_BYTES). Retourne un segment clos, sinon None."""
        if len(frame) != FRAME_BYTES:
            return None
        speech = self._vad.is_speech(frame, self._rate)
        if speech:
            self._in_speech = True
            self._silence_run = 0
            self._voiced.extend(frame)
            return None
        if self._in_speech:
            self._silence_run += 1
            self._voiced.extend(frame)
            if self._silence_run >= _SILENCE_FRAMES_TO_CUT:
                return self._emit()
        return None

    def flush(self) -> bytes | None:
        return self._emit() if self._voiced else None

    def _emit(self) -> bytes | None:
        if not self._voiced:
            return None
        seg = bytes(self._voiced)
        self._voiced.clear()
        self._silence_run = 0
        self._in_speech = False
        return seg
```

- [ ] **Step 4: Lancer → succès**

Run: `pytest tests/discord/voice/test_audio.py -v`
Expected: PASS

- [ ] **Step 5: Committer**

```bash
git add bot/discord/voice/audio.py tests/discord/voice/test_audio.py
git commit -m "feat(voice): resample 48k→16k + segmentation VAD"
```

---

## Task 4: Génération de réponse vocale + branchement gate (`brain.py`)

**Files:**
- Create: `bot/discord/voice/brain.py`
- Test: `tests/discord/voice/test_brain.py`

**Interfaces:**
- Consumes: `bot.response_gate` (`gate.decide(...) -> GateDecision`), `bot.llm.complete_with_tools(...)`, `bot.emotion.get_state()`, `bot.memory.search(...)`, `bot.prompts`, `VoiceService` (Task 5, pour `speak()` et l'état) — passé en paramètre, pas importé.
- Produces:
  - `async def generate_voice_reply(bot, speaker_label: str, transcript: str, history: list[dict], tools: list[dict], tool_executor) -> str` — assemble system_prompt (persona+émotions) + messages, appelle `complete_with_tools`, retourne le texte.
  - `async def handle_transcript(bot, service, speaker_user_id: str, speaker_label: str, transcript: str) -> None` — applique le gate ; si `RESPOND`, génère puis fait parler via `service.speak(text)`.

- [ ] **Step 1: Écrire le test échouant**

```python
# tests/discord/voice/test_brain.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.gate import GateDecision
from bot.discord.voice.brain import handle_transcript

def _bot(decision="RESPOND"):
    bot = MagicMock()
    bot.emotion.get_state.return_value = {"anger":0.0,"joy":0.5,"sadness":0.0,"curiosity":0.3,"boredom":0.0}
    bot.memory.search = AsyncMock(return_value="")
    bot.llm.complete_with_tools = AsyncMock(return_value=("salut à tous", []))
    bot.response_gate.decide = AsyncMock(
        return_value=GateDecision(decision=decision, reason="r")
    )
    bot.prompts.build_voice_system = MagicMock(return_value="SYSTEM")
    return bot

@pytest.mark.asyncio
async def test_respond_triggers_speak():
    bot = _bot("RESPOND")
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    await handle_transcript(bot, service, "42", "Alice (@alice)", "wally tu es là ?")
    service.speak.assert_awaited_once()
    assert service.speak.await_args.args[0] == "salut à tous"

@pytest.mark.asyncio
async def test_ignore_does_not_speak():
    bot = _bot("IGNORE")
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    await handle_transcript(bot, service, "42", "Alice (@alice)", "blabla")
    service.speak.assert_not_awaited()
```

- [ ] **Step 2: Lancer → échec**

Run: `pytest tests/discord/voice/test_brain.py -v`
Expected: FAIL — module introuvable

- [ ] **Step 3: Implémenter `brain.py`**

> Note d'intégration : `bot.prompts.build_voice_system(...)` n'existe pas encore. Pour rester DRY sans dupliquer `_respond`, ajouter une petite méthode au `PromptBuilder` qui réutilise les blocs persona+émotions existants mais sans la couche Discord-message. Si le `PromptBuilder` expose déjà une construction de system prompt réutilisable, l'appeler ; sinon ajouter `build_voice_system(emotion_state: dict, memory_context: str, speaker_label: str) -> str` qui concatène persona + directive émotion + `target_notice` + contexte mémoire. Le test mocke cette méthode, donc l'implémentation exacte de `build_voice_system` est traitée comme une sous-étape de cette task (voir Step 3b).

```python
# bot/discord/voice/brain.py
from loguru import logger

_VOICE_TARGET_NOTICE = (
    "Tu participes à une conversation VOCALE. Réponds en une à deux phrases courtes, "
    "naturelles à l'oral, sans formatage ni emoji. Réponds UNIQUEMENT avec ton propre texte."
)


async def generate_voice_reply(bot, speaker_label, transcript, history, tools, tool_executor):
    emotion_state = bot.emotion.get_state()
    try:
        memory_context = await bot.memory.search(
            platform="discord", user_id=None, query=transcript, limit=3
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("voice memory.search a échoué: {e}", e=e)
        memory_context = ""

    system_prompt = bot.prompts.build_voice_system(
        emotion_state=emotion_state,
        memory_context=memory_context or "",
        speaker_label=speaker_label,
    )
    system_prompt = f"{system_prompt}\n\n{_VOICE_TARGET_NOTICE}"

    messages = list(history)
    messages.append({"role": "user", "content": f"{speaker_label}: {transcript}"})

    reply, _tools_called = await bot.llm.complete_with_tools(
        system_prompt, messages, tools, tool_executor,
        purpose="discord_voice",
    )
    return reply or ""


async def handle_transcript(bot, service, speaker_user_id, speaker_label, transcript):
    """Transcrit → gate → (si RESPOND) génère et fait parler Wally."""
    transcript = (transcript or "").strip()
    if not transcript:
        return
    try:
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_activity(
                channel_id=service.channel_id, author=speaker_label, content=transcript
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("voice notify_activity a échoué: {e}", e=e)

    gate = getattr(bot, "response_gate", None)
    decision = "RESPOND"
    if gate is not None:
        try:
            gd = await gate.decide(
                message_content=transcript,
                author_user_id=speaker_user_id,
                emotion_state=bot.emotion.get_state(),
                relationship_facts=[],
                active_desires=[],
                is_triggered=True,
            )
            decision = gd.decision
        except Exception as e:  # noqa: BLE001
            logger.warning("voice gate.decide a échoué, fallback RESPOND: {e}", e=e)

    if decision != "RESPOND":
        logger.info("voice: gate={d}, Wally ne parle pas", d=decision)
        return

    tools = service.voice_tools  # défini en Task 6 (join/leave); peut être [] tant que Task 6 absente
    text = await generate_voice_reply(
        bot, speaker_label, transcript, service.history, tools, service.tool_executor
    )
    if not text:
        return
    service.history.append({"role": "user", "content": f"{speaker_label}: {transcript}"})
    service.history.append({"role": "assistant", "content": text})
    service.history[:] = service.history[-12:]  # borne courte
    await service.speak(text)
    try:
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(service.channel_id, content=text)
    except Exception as e:  # noqa: BLE001
        logger.warning("voice notify_reply a échoué: {e}", e=e)
```

- [ ] **Step 3b: Ajouter `build_voice_system` au PromptBuilder**

Dans `bot/intelligence/prompts.py`, ajouter une méthode qui réutilise les blocs persona + la directive d'émotion dominante déjà utilisés par le chemin Discord (chercher la méthode existante qui construit le system prompt — réutiliser ses helpers, ne pas dupliquer la logique d'émotion) :

```python
    def build_voice_system(self, emotion_state: dict, memory_context: str, speaker_label: str) -> str:
        persona_block = self._persona.full_block()  # même source que le chemin écrit
        emotion_directive = self._emotion_directive(emotion_state)  # helper existant
        parts = [persona_block, emotion_directive]
        if memory_context:
            parts.append(f"--- Mémoire ---\n{memory_context}")
        return "\n\n".join(p for p in parts if p)
```

> Adapter les noms exacts (`self._persona.full_block()`, `self._emotion_directive`) à ce qui existe réellement dans `prompts.py`/`persona.py`. L'objectif : zéro duplication de la logique d'émotion.

- [ ] **Step 4: Lancer → succès**

Run: `pytest tests/discord/voice/test_brain.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Committer**

```bash
git add bot/discord/voice/brain.py bot/intelligence/prompts.py tests/discord/voice/test_brain.py
git commit -m "feat(voice): génération réponse vocale + branchement gate"
```

---

## Task 5: VoiceService + sink d'écoute

**Files:**
- Create: `bot/discord/voice/sink.py`
- Create: `bot/discord/voice/service.py`
- Test: `tests/discord/voice/test_service.py`

**Interfaces:**
- Consumes: `build_stt`/`build_tts` (Task 2), `to_stt_format`/`VadSegmenter`/`FRAME_BYTES` (Task 3), `handle_transcript` (Task 4), `discord-ext-voice-recv`.
- Produces:
  - `class VoiceService` ctor `(bot, cfg: VoiceConfig)`.
  - `async def join(self, channel) -> None` ; `async def leave(self) -> None` ; propriété `channel_id: int | None` ; `is_connected: bool`.
  - `async def speak(self, text: str) -> None` (TTS + playback ; coupe l'écoute pendant le playback — anti-larsen).
  - attributs `history: list[dict]`, `voice_tools: list`, `tool_executor`, `is_speaking: bool`.
  - `def members_in_channel() -> list[int]` (pour garde-fou Task 6).

- [ ] **Step 1: Écrire le test échouant**

```python
# tests/discord/voice/test_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.config import VoiceConfig
from bot.discord.voice.service import VoiceService

def _make_service():
    bot = MagicMock()
    with patch("bot.discord.voice.service.build_stt"), \
         patch("bot.discord.voice.service.build_tts"):
        svc = VoiceService(bot, VoiceConfig(enabled=True))
    return svc

@pytest.mark.asyncio
async def test_join_connects_and_listens():
    svc = _make_service()
    channel = MagicMock()
    channel.id = 555
    channel.connect = AsyncMock(return_value=MagicMock())
    await svc.join(channel)
    assert svc.is_connected is True
    assert svc.channel_id == 555
    channel.connect.assert_awaited_once()

@pytest.mark.asyncio
async def test_leave_disconnects():
    svc = _make_service()
    channel = MagicMock(); channel.id = 555
    vc = MagicMock(); vc.disconnect = AsyncMock(); vc.stop_listening = MagicMock()
    channel.connect = AsyncMock(return_value=vc)
    await svc.join(channel)
    await svc.leave()
    assert svc.is_connected is False
    vc.disconnect.assert_awaited_once()

@pytest.mark.asyncio
async def test_speak_mutes_listening_during_playback():
    svc = _make_service()
    svc._tts.synthesize = AsyncMock(return_value=b"PCM")
    vc = MagicMock(); vc.play = MagicMock(); vc.is_playing = MagicMock(return_value=False)
    svc._vc = vc
    await svc.speak("bonjour")
    assert svc.is_speaking is False  # remis à False après playback
    svc._tts.synthesize.assert_awaited_once_with("bonjour")
```

- [ ] **Step 2: Lancer → échec**

Run: `pytest tests/discord/voice/test_service.py -v`
Expected: FAIL — module introuvable

- [ ] **Step 3: Implémenter `sink.py`**

```python
# bot/discord/voice/sink.py
from discord.ext import voice_recv
from loguru import logger

from bot.discord.voice.audio import FRAME_BYTES, VadSegmenter, to_stt_format


class WallyAudioSink(voice_recv.AudioSink):
    """Reçoit le PCM par locuteur, segmente par VAD, déclenche un callback async par segment.

    callback signature: async def on_segment(user, pcm16k_mono: bytes)
    """

    def __init__(self, bot, aggressiveness: int, on_segment, loop) -> None:
        super().__init__()
        self._bot = bot
        self._aggr = aggressiveness
        self._on_segment = on_segment
        self._loop = loop
        self._segmenters: dict[int, VadSegmenter] = {}
        self._frame_buf: dict[int, bytearray] = {}

    def wants_opus(self) -> bool:
        return False  # on veut du PCM décodé

    def write(self, user, data) -> None:
        if user is None or self._bot.voice_service.is_speaking:
            return  # anti-larsen : on ignore l'audio pendant que Wally parle
        try:
            pcm16 = to_stt_format(data.pcm)  # 48k stéréo -> 16k mono
            buf = self._frame_buf.setdefault(user.id, bytearray())
            buf.extend(pcm16)
            seg = self._segmenters.setdefault(user.id, VadSegmenter(self._aggr))
            while len(buf) >= FRAME_BYTES:
                frame = bytes(buf[:FRAME_BYTES]); del buf[:FRAME_BYTES]
                out = seg.feed(frame)
                if out:
                    self._loop.create_task(self._on_segment(user, out))
        except Exception as e:  # noqa: BLE001
            logger.warning("WallyAudioSink.write a échoué: {e}", e=e)

    def cleanup(self) -> None:
        self._segmenters.clear()
        self._frame_buf.clear()
```

- [ ] **Step 3b: Implémenter `service.py`**

```python
# bot/discord/voice/service.py
import asyncio
import io

import discord
from discord.ext import voice_recv
from loguru import logger

from bot.config import VoiceConfig
from bot.discord.voice.brain import handle_transcript
from bot.discord.voice.providers import build_stt, build_tts
from bot.discord.voice.sink import WallyAudioSink


class VoiceService:
    def __init__(self, bot, cfg: VoiceConfig) -> None:
        self._bot = bot
        self._cfg = cfg
        self._stt = build_stt(cfg)
        self._tts = build_tts(cfg)
        self._vc = None
        self._channel = None
        self.history: list[dict] = []
        self.voice_tools: list = []     # rempli en Task 6
        self.tool_executor = None       # rempli en Task 6
        self.is_speaking = False
        self._last_speech_ts = 0.0
        self._auto_leave_task = None

    @property
    def is_connected(self) -> bool:
        return self._vc is not None

    @property
    def channel_id(self):
        return self._channel.id if self._channel else None

    def members_in_channel(self) -> list[int]:
        if not self._channel:
            return []
        return [m.id for m in self._channel.members if not m.bot]

    async def join(self, channel) -> None:
        if self._vc is not None:
            await self.leave()
        self._channel = channel
        self._vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
        loop = asyncio.get_running_loop()
        self._last_speech_ts = loop.time()
        sink = WallyAudioSink(self._bot, self._cfg.vad_aggressiveness, self._on_segment, loop)
        self._vc.listen(sink)
        self._auto_leave_task = loop.create_task(self._auto_leave_watch())
        logger.info("voice: rejoint le salon {c}", c=channel.id)

    async def leave(self) -> None:
        if self._auto_leave_task:
            self._auto_leave_task.cancel()
            self._auto_leave_task = None
        if self._vc is not None:
            try:
                self._vc.stop_listening()
            except Exception:  # noqa: BLE001
                pass
            await self._vc.disconnect()
        self._vc = None
        self._channel = None
        self.history.clear()
        logger.info("voice: salon quitté")

    async def _on_segment(self, user, pcm16k_mono: bytes) -> None:
        try:
            self._last_speech_ts = asyncio.get_running_loop().time()
            text = await self._stt.transcribe(pcm16k_mono)
            if not text:
                return
            from bot.discord.handlers import _author_label
            label = _author_label(user) if hasattr(user, "display_name") else str(user)
            await handle_transcript(self._bot, self, str(user.id), label, text)
        except Exception as e:  # noqa: BLE001
            logger.warning("voice _on_segment a échoué: {e}", e=e)

    async def speak(self, text: str) -> None:
        if not text or self._vc is None:
            return
        self.is_speaking = True
        try:
            pcm = await self._tts.synthesize(text)
            if not pcm:
                return
            source = discord.PCMAudio(io.BytesIO(pcm))
            done = asyncio.Event()
            self._vc.play(source, after=lambda _e: done.set())
            await done.wait()
        except Exception as e:  # noqa: BLE001
            logger.warning("voice speak a échoué: {e}", e=e)
        finally:
            self.is_speaking = False

    async def _auto_leave_watch(self) -> None:
        timeout = self._cfg.auto_leave_minutes * 60
        try:
            while self._vc is not None:
                await asyncio.sleep(10)
                loop = asyncio.get_running_loop()
                if not self.members_in_channel():
                    logger.info("voice: salon vide → auto-leave")
                    await self.leave(); return
                if loop.time() - self._last_speech_ts > timeout:
                    logger.info("voice: inactivité {t}s → auto-leave", t=timeout)
                    await self.leave(); return
        except asyncio.CancelledError:
            pass
```

> Note : `discord.PCMAudio` attend du PCM 48 kHz **stéréo** 16-bit. L'`AzureTTS` produit du 48 kHz **mono** → ajouter une conversion mono→stéréo dans `speak()` via `audioop.tostereo(pcm, 2, 1, 1)` avant `PCMAudio`. (Ajouter `import audioop` et appliquer : `pcm = audioop.tostereo(pcm, 2, 1, 1)`.)

- [ ] **Step 4: Lancer → succès**

Run: `pytest tests/discord/voice/test_service.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Committer**

```bash
git add bot/discord/voice/sink.py bot/discord/voice/service.py tests/discord/voice/test_service.py
git commit -m "feat(voice): VoiceService (join/leave/speak) + sink écoute + auto-leave"
```

---

## Task 6: Outils LLM join_voice / leave_voice + garde-fous

**Files:**
- Create: `bot/discord/voice/tools.py`
- Modify: `bot/discord/voice/service.py` (câbler `voice_tools` + `tool_executor`)
- Test: `tests/discord/voice/test_voice_tools.py`

**Interfaces:**
- Produces:
  - `VOICE_TOOLS: list[dict]` — définitions `join_voice` / `leave_voice` (format OpenAI).
  - `def make_voice_tool_executor(bot, service, allowed_user_ids_getter)` → `async def executor(name, arguments) -> str`.
  - Garde-fou : `leave_voice` n'est honoré que si l'appel provient d'un membre présent dans le salon (vérif via `service.members_in_channel()`), et `service.speak("ok, je vous laisse")` avant `service.leave()`.

- [ ] **Step 1: Écrire le test échouant**

```python
# tests/discord/voice/test_voice_tools.py
import json, pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.voice.tools import VOICE_TOOLS, make_voice_tool_executor

def _names():
    return {t["function"]["name"] for t in VOICE_TOOLS}

def test_tools_declared():
    assert {"join_voice", "leave_voice"} <= _names()

@pytest.mark.asyncio
async def test_leave_voice_speaks_then_leaves():
    bot = MagicMock()
    service = MagicMock()
    service.members_in_channel.return_value = [42]
    service.speak = AsyncMock()
    service.leave = AsyncMock()
    ex = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "42")
    out = await ex("leave_voice", json.dumps({}))
    service.speak.assert_awaited_once()
    service.leave.assert_awaited_once()
    assert json.loads(out)["status"] == "ok"

@pytest.mark.asyncio
async def test_leave_voice_rejected_for_non_member():
    bot = MagicMock()
    service = MagicMock()
    service.members_in_channel.return_value = [99]  # 42 pas dans le salon
    service.leave = AsyncMock()
    ex = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "42")
    out = await ex("leave_voice", json.dumps({}))
    service.leave.assert_not_awaited()
    assert json.loads(out)["status"] == "denied"
```

- [ ] **Step 2: Lancer → échec**

Run: `pytest tests/discord/voice/test_voice_tools.py -v`
Expected: FAIL — module introuvable

- [ ] **Step 3: Implémenter `tools.py`**

```python
# bot/discord/voice/tools.py
import json

from loguru import logger

VOICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "join_voice",
            "description": (
                "Quand quelqu'un te demande de venir/rejoindre le salon vocal "
                "(ex: 'viens en vocal', 'rejoins-nous'). Tu rejoins le salon vocal de la personne."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leave_voice",
            "description": (
                "Quand on te demande de quitter/partir du salon vocal "
                "(ex: 'quitte le vocal', 'tu peux partir', 'dégage du vocal')."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def make_voice_tool_executor(bot, service, current_speaker_id):
    """current_speaker_id: callable -> str (id Discord du locuteur courant)."""

    async def executor(name: str, arguments: str) -> str:
        try:
            _ = json.loads(arguments or "{}")
        except Exception:  # noqa: BLE001
            pass
        if name == "leave_voice":
            speaker = current_speaker_id()
            if speaker is None or int(speaker) not in service.members_in_channel():
                return json.dumps({"status": "denied", "message": "Seul un membre du salon peut me faire partir."})
            await service.speak("ok, je vous laisse")
            await service.leave()
            return json.dumps({"status": "ok", "message": "Quitté le salon vocal."})
        if name == "join_voice":
            # En contexte vocal Wally est déjà connecté ; le join réel se fait côté texte (handlers).
            return json.dumps({"status": "ok", "message": "Déjà en vocal."})
        return json.dumps({"status": "error", "message": f"Outil inconnu: {name}"})

    return executor
```

- [ ] **Step 3b: Câbler les tools dans `VoiceService`**

Dans `service.py`, `_on_segment` connaît le locuteur courant. Avant d'appeler `handle_transcript`, fixer le contexte des tools :

```python
# dans service.py, ajouter en tête :
from bot.discord.voice.tools import VOICE_TOOLS, make_voice_tool_executor

# dans __init__ :
        self.voice_tools = VOICE_TOOLS
        self._current_speaker_id = None
        self.tool_executor = make_voice_tool_executor(
            bot, self, current_speaker_id=lambda: self._current_speaker_id
        )

# dans _on_segment, avant handle_transcript :
            self._current_speaker_id = str(user.id)
```

- [ ] **Step 4: Lancer → succès**

Run: `pytest tests/discord/voice/test_voice_tools.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Committer**

```bash
git add bot/discord/voice/tools.py bot/discord/voice/service.py tests/discord/voice/test_voice_tools.py
git commit -m "feat(voice): outils LLM join/leave + garde-fou membre + confirmation orale"
```

---

## Task 7: Slash commands /wally join · /wally leave + câblage bot + join_voice côté texte

**Files:**
- Create: `bot/discord/commands/voice_cmd.py`
- Modify: `bot/discord/bot.py` (instancier `VoiceService`, `add_cog(VoiceCog)`)
- Modify: `bot/discord/handlers.py` (exposer `join_voice`/`leave_voice` au chemin texte + executor texte)
- Test: `tests/discord/voice/test_voice_cmd.py`

**Interfaces:**
- Consumes: `VoiceService` (`bot.voice_service`), `VOICE_TOOLS`.
- Produces: `class VoiceCog(commands.Cog)` avec `/wally join` (rejoint le salon de l'appelant) et `/wally leave`.

- [ ] **Step 1: Écrire le test échouant**

```python
# tests/discord/voice/test_voice_cmd.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.commands.voice_cmd import VoiceCog

@pytest.mark.asyncio
async def test_join_uses_caller_voice_channel():
    bot = MagicMock()
    bot.voice_service.join = AsyncMock()
    cog = VoiceCog(bot)
    inter = MagicMock()
    inter.user.voice.channel = MagicMock()
    inter.response.send_message = AsyncMock()
    await cog.join.callback(cog, inter)
    bot.voice_service.join.assert_awaited_once_with(inter.user.voice.channel)

@pytest.mark.asyncio
async def test_join_without_channel_warns():
    bot = MagicMock()
    bot.voice_service.join = AsyncMock()
    cog = VoiceCog(bot)
    inter = MagicMock()
    inter.user.voice = None
    inter.response.send_message = AsyncMock()
    await cog.join.callback(cog, inter)
    bot.voice_service.join.assert_not_awaited()
    inter.response.send_message.assert_awaited_once()

@pytest.mark.asyncio
async def test_leave_calls_service():
    bot = MagicMock()
    bot.voice_service.leave = AsyncMock()
    bot.voice_service.is_connected = True
    cog = VoiceCog(bot)
    inter = MagicMock(); inter.response.send_message = AsyncMock()
    await cog.leave.callback(cog, inter)
    bot.voice_service.leave.assert_awaited_once()
```

- [ ] **Step 2: Lancer → échec**

Run: `pytest tests/discord/voice/test_voice_cmd.py -v`
Expected: FAIL — module introuvable

- [ ] **Step 3: Implémenter `voice_cmd.py`**

```python
# bot/discord/commands/voice_cmd.py
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class VoiceCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(name="join", description="Wally rejoint ton salon vocal")
    async def join(self, interaction: discord.Interaction) -> None:
        voice = getattr(interaction.user, "voice", None)
        if voice is None or voice.channel is None:
            await interaction.response.send_message(
                "Tu dois être dans un salon vocal pour que je te rejoigne.", ephemeral=True
            )
            return
        try:
            await self.bot.voice_service.join(voice.channel)
            await interaction.response.send_message(f"J'arrive dans **{voice.channel.name}** 🎙️")
        except Exception as e:  # noqa: BLE001
            logger.warning("/wally join a échoué: {e}", e=e)
            await interaction.response.send_message("Impossible de rejoindre le vocal.", ephemeral=True)

    @app_commands.command(name="leave", description="Wally quitte le salon vocal")
    async def leave(self, interaction: discord.Interaction) -> None:
        if not self.bot.voice_service.is_connected:
            await interaction.response.send_message("Je ne suis dans aucun vocal.", ephemeral=True)
            return
        await self.bot.voice_service.leave()
        await interaction.response.send_message("Je vous laisse 👋")
```

> Si les commandes existantes utilisent un groupe `/wally <sub>` (app_commands.Group), enregistrer `join`/`leave` comme sous-commandes du même groupe pour cohérence (`/wally join`). Suivre exactement le pattern du fichier de groupe existant (voir comment `mood`/`status` sont rattachés).

- [ ] **Step 3b: Câbler dans `bot/discord/bot.py`**

Dans `setup_hook`, après la création du gate/cognitive_loop et avant le sync de l'arbre :

```python
        from bot.discord.voice.service import VoiceService
        from bot.discord.commands.voice_cmd import VoiceCog

        if self.config.voice.enabled:
            self.voice_service = VoiceService(self, self.config.voice)
            await self.add_cog(VoiceCog(self))
            logger.info("VoiceService activé")
        else:
            self.voice_service = None
```

Ajouter `self.voice_service = None` dans `__init__` (à côté de `self.cognitive_loop = None`).

- [ ] **Step 3c: Exposer join_voice/leave_voice au chemin TEXTE**

Dans `handlers.py`, là où les `tools` sont assemblés pour `_respond` (autour de la construction passée à `complete_with_tools`, ~ligne 1474), ajouter les `VOICE_TOOLS` quand le vocal est activé, et gérer `join_voice` dans `_tool_executor_impl` :

```python
# imports en tête de handlers.py
from bot.discord.voice.tools import VOICE_TOOLS

# dans l'assemblage des tools (là où _NOTE_TOOLS est utilisé) :
    tools = list(_NOTE_TOOLS)
    if getattr(bot, "voice_service", None) is not None:
        tools += VOICE_TOOLS

# dans _tool_executor_impl(name, arguments), ajouter :
    if name == "join_voice":
        voice = getattr(message.author, "voice", None)
        if voice is None or voice.channel is None:
            return json.dumps({"status": "denied", "message": "Tu n'es dans aucun salon vocal."})
        await bot.voice_service.join(voice.channel)
        return json.dumps({"status": "ok", "message": f"Rejoint {voice.channel.name}."})
    if name == "leave_voice":
        if getattr(bot, "voice_service", None) and bot.voice_service.is_connected:
            await bot.voice_service.leave()
            return json.dumps({"status": "ok", "message": "Quitté le vocal."})
        return json.dumps({"status": "ok", "message": "Pas en vocal."})
```

- [ ] **Step 4: Lancer → succès**

Run: `pytest tests/discord/voice/test_voice_cmd.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Vérification globale + commit**

Run: `pytest tests/discord/voice/ -v && python -m pyflakes bot/discord/voice/ bot/discord/commands/voice_cmd.py`
Expected: tous les tests vocaux PASS, aucun import/var orphelin

Run (non-régression) : `pytest -q`
Expected: pas de nouvelle régression (baseline connue : quelques échecs préexistants spam/cost non liés)

```bash
git add bot/discord/commands/voice_cmd.py bot/discord/bot.py bot/discord/handlers.py tests/discord/voice/test_voice_cmd.py
git commit -m "feat(voice): commandes /wally join|leave + join_voice/leave_voice côté texte"
```

---

## Task 8: Vérification manuelle & documentation

**Files:**
- Modify: `config.example.yaml` (section `voice:` documentée)
- Modify: `.env.example` (clés Azure)
- Modify: `README` ou `docs/` (mention de la capacité vocale, si pertinent)

- [ ] **Step 1: Documenter la config exemple**

Ajouter à `config.example.yaml` :

```yaml
voice:
  enabled: false          # passer à true après avoir renseigné les clés Azure
  stt_provider: azure
  tts_provider: azure
  language: fr-FR
  azure_voice: fr-FR-DeniseNeural
  auto_leave_minutes: 2
  vad_aggressiveness: 2
```

Ajouter à `.env.example` :

```
AZURE_SPEECH_KEY=
AZURE_SPEECH_REGION=
```

- [ ] **Step 2: Checklist de vérification manuelle (à faire après déploiement/rebuild image)**

Créer une ressource Azure Speech (F0), renseigner `.env`, `voice.enabled: true`, rebuild image. Puis vérifier :
- [ ] `/wally join` depuis un salon vocal → Wally rejoint.
- [ ] Parler « Wally tu es là ? » → il répond à voix haute en français.
- [ ] Dire quelque chose hors-sujet → le gate peut le faire rester silencieux.
- [ ] Wally ne réagit pas à sa propre voix (anti-larsen).
- [ ] « Wally tu peux partir » à l'oral → il confirme et quitte.
- [ ] `/wally leave` → il quitte.
- [ ] En texte « Wally viens en vocal » (depuis un salon vocal) → il rejoint.
- [ ] Laisser le salon silencieux 2 min → auto-leave.
- [ ] Couper la clé Azure → aucun crash, Wally reste muet en vocal.

- [ ] **Step 3: Committer**

```bash
git add config.example.yaml .env.example
git commit -m "docs(voice): config exemple + clés Azure + checklist de vérif"
```

---

## Self-Review (auteur du plan)

- **Couverture spec :** §3 flux → Tasks 3/4/5 ; §4 déclenchement (3 portes ×2) → Tasks 6 (oral+texte leave), 7 (slash + texte join) ; §5 composants → Tasks 2-7 ; §6 abstraction → Task 2 ; §7 config → Task 1 ; §8 erreurs → try/except dans chaque module ; §9 deps → Task 1 ; §11 tests → chaque task ; §12 limites (1 salon, pas de wake-word) respectées. ✅
- **Anti-larsen** (§5.6) : flag `is_speaking` lu dans `sink.write` + remis à False dans `speak()`. ✅
- **Auto-leave 2 min** (§4) : `_auto_leave_watch` + salon vide. ✅
- **Points à valider à l'exécution** (signalés inline) : noms réels dans `PromptBuilder`/`PersonaService` pour `build_voice_system` (Task 4 Step 3b) ; existence d'un groupe `app_commands` `/wally` pour rattacher join/leave (Task 7 Step 3) ; API exacte `discord-ext-voice-recv` (`VoiceRecvClient`, `listen`, `AudioSink.write(user, data)`, `data.pcm`) et format `discord.PCMAudio` (mono→stéréo). Ce sont des conformités d'API externes, pas des trous de conception.
- **Pas de placeholder de logique** : tout le code est fourni. ✅
```
