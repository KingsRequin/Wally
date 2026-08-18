import asyncio
import threading
import os
from typing import Protocol

import azure.cognitiveservices.speech as speechsdk
from loguru import logger

from bot.config import VoiceConfig
from bot.discord.voice.audio import SAMPLE_RATE


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


class FasterWhisperSTT:
    """STT local (faster-whisper / CTranslate2). Entrée : PCM 16 kHz mono 16-bit. Sortie : texte.

    Le modèle est chargé paresseusement au premier appel (et non au boot) pour ne rien charger
    en RAM tant que le vocal n'est pas utilisé en mode whisper, et pour ne pas dépendre du
    package `faster_whisper` quand un autre provider est configuré.
    """

    def __init__(
        self,
        model_size: str = "small",
        language: str = "fr-FR",
        device: str = "cpu",
        compute_type: str = "int8",
        phrases: list[str] | None = None,
        cpu_threads: int = 0,
        parallel: int = 1,
        hotwords: str | None = None,
    ) -> None:
        self._model_size = model_size
        self._lang = (language or "fr").split("-")[0]  # "fr-FR" → "fr"
        self._device = device
        self._compute_type = compute_type
        self._cpu_threads = cpu_threads  # 0 = auto (CTranslate2 choisit)
        # `initial_prompt` reste ÉTEINT : avec « Wally » dedans, le modèle
        # hallucinait « Wally wally » sur le bruit du ventilateur.
        self._initial_prompt = None
        # `hotwords` emprunte pourtant le MÊME emplacement du prompt (après
        # `sot_prev`, cf. `TranscriptionOptions.get_prompt` de faster-whisper) —
        # ce n'est pas un mécanisme plus sage, et le rallumer sur la foi de son
        # nom aurait ramené le défaut ci-dessus. Il a donc fallu le mesurer.
        #
        # `scripts/bench_stt.py`, sur les phrases d'appel RÉELLEMENT ratées en
        # live : 4/8 entendues sans, **8/8 avec**. Zéro faux déclenchement sur
        # les 8 contrôles (« wall jump », « on my way », « un walk », « Well »),
        # zéro bavardage sur 6 non-paroles franchissant le plancher, débit
        # inchangé (2,1× le temps réel). Le nom SEUL suffit — le jargon en plus
        # n'ajoute rien de mesurable, donc il n'entre pas.
        #
        # Ce qui a changé depuis l'hallucination : `vad_filter` Silero, et le
        # plancher qui écarte le souffle avant le moteur. Si le bavardage
        # revenait, ce paramètre est le premier à éteindre.
        self._hotwords = hotwords or (", ".join(p for p in (phrases or []) if p) or None)
        self._model = None  # chargé à la demande
        # Nombre de transcriptions menées de front. Mesuré en live à trois
        # locuteurs : le calcul ne coûte que ~2 s par énoncé, mais l'attente en
        # file en ajoutait jusqu'à 13. Au-delà de ce parallélisme, on
        # sur-souscrit le CPU et la latence repart dans l'autre sens — d'où le
        # produit `parallel × cpu_threads` à garder sous le nombre de cœurs.
        self._parallel = max(1, int(parallel or 1))
        self._sem = asyncio.Semaphore(self._parallel)
        # Le chargement du modèle, lui, reste strictement sérialisé : deux
        # chargements concurrents doubleraient la mémoire.
        self._load_lock = asyncio.Lock()
        # Verrou de thread (et non asyncio) : le chargement a lieu dans le
        # thread de travail, où le verrou asyncio ne protège rien.
        self._model_guard = threading.Lock()

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            logger.info(
                "FasterWhisperSTT: chargement du modèle '{m}' ({d}/{c}, threads={t})",
                m=self._model_size, d=self._device, c=self._compute_type, t=self._cpu_threads,
            )
            self._model = WhisperModel(
                self._model_size, device=self._device, compute_type=self._compute_type,
                cpu_threads=self._cpu_threads,
                # Sans workers supplémentaires, CTranslate2 sérialise en interne :
                # le parallélisme Python ne servirait à rien.
                num_workers=self._parallel,
            )
        return self._model

    async def warmup(self) -> None:
        """Pré-charge le modèle (évite les ~2,5 s du 1er segment et le double-chargement concurrent)."""
        async with self._load_lock:
            await asyncio.to_thread(self._ensure_model)

    async def transcribe(self, pcm16k_mono: bytes) -> str:
        async with self._sem:  # `parallel` transcriptions au plus
            return await asyncio.to_thread(self._transcribe_sync, pcm16k_mono)

    def _transcribe_sync(self, pcm16k_mono: bytes) -> str:
        try:
            import numpy as np
            # `_ensure_model` peut être atteint par deux transcriptions à la fois
            # depuis que le sémaphore en laisse passer plusieurs.
            with self._model_guard:
                model = self._ensure_model()
            audio = np.frombuffer(pcm16k_mono, dtype=np.int16).astype(np.float32) / 32768.0
            # beam_size=1 (greedy) → priorité latence.
            # vad_filter (Silero) : rejette le non-parole (bruit/ventilateur) → anti-hallucination.
            # condition_on_previous_text=False : segments indépendants, évite la dérive.
            segments, _info = model.transcribe(
                audio, language=self._lang, beam_size=1,
                initial_prompt=self._initial_prompt,
                hotwords=self._hotwords,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            # Chaque segment whisper porte déjà un espace de tête → on strip avant de joindre.
            return " ".join(t for seg in segments if (t := seg.text.strip()))
        except Exception as e:  # noqa: BLE001
            logger.warning("FasterWhisperSTT.transcribe a échoué: {e}", e=e)
            return ""


class OneMinSTT:
    """STT distant Qwen3-ASR-Flash, via l'abonnement 1min.ai de l'owner.

    Sert de SOUPAPE, pas de moteur : le `small` local est plus rapide tant qu'une
    seule personne parle (1,2-2,1 s contre 2,4-3,5 s ici, upload compris). Mais
    il transcrit un énoncé à la fois, donc à trois locuteurs sa file le fait
    passer à 5-6 s et il finit par JETER de la parole. Cette API n'a pas de
    file : mesurée à 3,5 s pour trois énoncés simultanés, contre 6,3 s en local.

    Elle reprend donc ce qui serait perdu. Le quota le permet sans y penser :
    ~3,5 crédits pour un énoncé de 2 s, sur un million par mois.

    Deux limites à connaître, mesurées le 2026-08-18 :
    - Le modèle ignore « Wally » et écrit « Wall-E » (que `address_match`
      rattrape) ou « ou ali » (qu'elle ne rattrape pas). 1min.ai n'expose PAS le
      paramètre de contexte de Qwen — 14 emplacements essayés, sortie identique
      au caractère près. Le biais de vocabulaire n'existe donc que côté local.
    - En revanche il rend un bien meilleur français : « Elle est où la balle »
      là où le local écrit « Elle est tout la balle ».
    """

    _BASE = "https://api.1min.ai/api"

    def __init__(self, api_key: str, model: str = "qwen3-asr-flash",
                 language: str = "fr-FR", timeout: float = 20.0) -> None:
        self._key = api_key
        self._model = model
        self._lang = (language or "fr").split("-")[0]
        # Serré volontairement : cette voie ne sert qu'à rattraper de la parole
        # en retard. Une transcription qui arrive après 20 s ne rattrape plus
        # rien, elle encombre — mieux vaut la lâcher et le dire.
        self._timeout = timeout

    @staticmethod
    def _wav(pcm16k_mono: bytes) -> bytes:
        """L'API veut un fichier audio ; le pipeline ne manipule que du PCM nu."""
        import io
        import wave

        tampon = io.BytesIO()
        with wave.open(tampon, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm16k_mono)
        return tampon.getvalue()

    async def transcribe(self, pcm16k_mono: bytes) -> str:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                envoi = await client.post(
                    f"{self._BASE}/assets", headers={"API-KEY": self._key},
                    files={"asset": ("enonce.wav", self._wav(pcm16k_mono), "audio/wav")},
                )
                chemin = (envoi.json().get("fileContent") or {}).get("path")
                if not chemin:
                    logger.warning("OneMinSTT: upload sans chemin ({c}) — {t}",
                                   c=envoi.status_code, t=envoi.text[:120])
                    return ""
                rep = await client.post(
                    f"{self._BASE}/features",
                    headers={"API-KEY": self._key, "Content-Type": "application/json"},
                    json={"type": "SPEECH_TO_TEXT", "model": self._model,
                          "promptObject": {"audioUrl": chemin, "response_format": "text",
                                           "language": self._lang}},
                )
            corps = rep.json()
            if "errorCode" in corps:
                # Le refus arrive en HTTP 200 avec le motif dans le CORPS : sans
                # cette lecture, un quota épuisé passerait pour un énoncé vide.
                logger.warning("OneMinSTT: refus {c} — {m}", c=corps.get("errorCode"),
                               m=str(corps.get("message"))[:140])
                return ""
            res = ((corps.get("aiRecord") or {}).get("aiRecordDetail") or {}).get("resultObject")
            if isinstance(res, list):
                res = " ".join(str(x) for x in res)
            return (res or "").strip()
        except Exception as e:  # noqa: BLE001 — une soupape ne casse jamais l'écoute
            logger.warning("OneMinSTT.transcribe a échoué: {e}", e=e)
            return ""


class AzureTTS:
    """TTS Azure Neural. Sortie : PCM 48 kHz mono 16-bit (prêt pour Discord)."""

    def __init__(self, key: str, region: str, voice: str) -> None:
        self._key, self._region, self._voice = key, region, voice

    async def synthesize(self, text: str, style: str | None = None) -> bytes:
        return await asyncio.to_thread(self._synthesize_sync, text, style)

    async def synthesize_stream(self, text: str, style: str | None, on_chunk) -> None:
        """Synthèse en streaming : `on_chunk(pcm48k_mono)` est appelé au fil de l'audio produit,
        ce qui permet de commencer à jouer dès le premier chunk (latence perçue minimale)."""
        await asyncio.to_thread(self._stream_sync, text, style, on_chunk)

    def _stream_sync(self, text: str, style: str | None, on_chunk) -> None:
        try:
            speech_cfg = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
            speech_cfg.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm
            )
            synth = speechsdk.SpeechSynthesizer(speech_config=speech_cfg, audio_config=None)
            result = synth.start_speaking_ssml_async(self._build_ssml(text, style)).get()
            stream = speechsdk.AudioDataStream(result)
            chunk = bytes(3840)
            produced = 0
            while True:
                n = stream.read_data(chunk)
                if n == 0:
                    break
                produced += n
                on_chunk(chunk[:n])
            # Azure ne LÈVE PAS quand la synthèse échoue : il rend un flux vide.
            # Sans ce contrôle, une clé invalide donnait zéro octet en silence —
            # Wally jouait son bip, générait sa réplique, l'inscrivait au
            # dashboard, et rien ne sortait, sans une ligne de log. Le chemin
            # batch vérifie `result.reason` depuis toujours ; celui-ci l'oubliait.
            if produced:
                return
            details = getattr(stream, "cancellation_details", None)
            if details is not None:
                logger.error(
                    "AzureTTS: synthèse annulée ({r}) — {d}",
                    r=getattr(details, "reason", "?"),
                    d=getattr(details, "error_details", ""),
                )
            else:
                logger.warning(
                    "AzureTTS: aucun audio produit (statut {s}) — Wally reste muet",
                    s=getattr(stream, "status", "?"),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("AzureTTS.synthesize_stream a échoué: {e}", e=e)

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


def _build_batch_stt(provider: str, cfg: VoiceConfig, phrases: list[str] | None) -> SpeechToText:
    """Construit un STT batch (entrée = segment complet) pour le provider donné."""
    provider = (provider or "azure").lower()
    if provider in ("faster_whisper", "faster-whisper", "whisper"):
        return FasterWhisperSTT(
            model_size=cfg.whisper_model,
            language=cfg.language,
            device=cfg.whisper_device,
            compute_type=cfg.whisper_compute_type,
            phrases=phrases,
            cpu_threads=getattr(cfg, "whisper_cpu_threads", 0),
            parallel=getattr(cfg, "stt_parallel", 1),
        )
    key, region = _azure_creds()
    return AzureSTT(key=key, region=region, language=cfg.language, phrases=phrases)


def build_stt(cfg: VoiceConfig, phrases: list[str] | None = None) -> SpeechToText:
    return _build_batch_stt(cfg.stt_provider, cfg, phrases)


def build_overflow_stt(cfg: VoiceConfig) -> SpeechToText | None:
    """La soupape de débordement, ou None si elle n'est pas configurée.

    Rend None sans bruit quand le provider n'est pas demandé, mais LOGUE quand
    il l'est sans clé : une soupape qu'on croit posée et qui ne l'est pas se
    voit seulement le jour où la parole disparaît, c'est-à-dire trop tard.
    """
    provider = (cfg.overflow_stt_provider or "").lower()
    if not provider:
        return None
    if provider not in ("1min", "1min.ai", "onemin"):
        logger.warning("voice: provider de débordement inconnu « {p} » — ignoré", p=provider)
        return None
    cle = os.environ.get("ONEMIN_API_KEY", "")
    if not cle:
        logger.warning("voice: débordement « {p} » demandé mais ONEMIN_API_KEY manque "
                       "— la parole en trop continuera d'être JETÉE", p=provider)
        return None
    logger.info("voice: soupape de débordement active ({m})", m=cfg.overflow_stt_model)
    return OneMinSTT(api_key=cle, model=cfg.overflow_stt_model,
                     language=cfg.language, timeout=cfg.overflow_stt_timeout_s)


def build_streaming_stt(cfg: VoiceConfig, phrases: list[str] | None = None):
    """Construit le STT streaming distant (RemoteStreamingSTT) + son fallback batch CPU local."""
    from bot.discord.voice.streaming import RemoteStreamingSTT
    fallback = _build_batch_stt(cfg.remote_stt_fallback, cfg, phrases)
    # Les places du serveur distant sont comptées (VRAM) : elles reviennent
    # d'abord à ceux au nom de qui Wally agit. `voice.requesters` porte déjà
    # cette liste — le créateur et le streamer — plutôt qu'un jeu d'ID en dur.
    prioritaires = {
        str((r or {}).get("discord_id") or "").strip()
        for r in (cfg.requesters or [])
    }
    prioritaires.discard("")
    return RemoteStreamingSTT(
        cfg.remote_stt_url,
        fallback=fallback,
        max_connections=cfg.remote_stt_max_connections,
        idle_timeout=cfg.remote_stt_idle_timeout,
        health_cache_s=cfg.remote_stt_health_cache_s,
        priority_speakers=prioritaires,
        overflow=build_overflow_stt(cfg),
        overflow_max_inflight=cfg.overflow_stt_max_inflight,
    )


def build_tts(cfg: VoiceConfig) -> TextToSpeech:
    key, region = _azure_creds()
    return AzureTTS(key=key, region=region, voice=cfg.azure_voice)
