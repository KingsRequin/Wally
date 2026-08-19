import asyncio
import threading
import os
from typing import Protocol

import azure.cognitiveservices.speech as speechsdk
from loguru import logger

from bot.config import VoiceConfig
from bot.discord.voice.audio import SAMPLE_RATE


# Namespace du `mstts:express-as`. En **http**, pas https : c'est un identifiant
# XML, pas une URL — Azure compare la chaîne exacte. Avec `https://`, le serveur
# ne reconnaît pas l'élément, l'IGNORE en silence et rend la phrase à plat.
# Mesuré le 2026-08-18 sur `fr-FR-Marc:MAI-Voice-2-Flash`, même texte :
#   https + style joyful → 31 200 octets, soit l'octet près le rendu SANS style
#   http  + style joyful → 29 280 octets ; http + softvoice → 59 040 octets
# Autrement dit, tout le système d'émotion vocal ne changeait rien à ce qui
# sortait, sans une seule ligne de log pour le dire.
_MSTTS_NS = "http://www.w3.org/2001/mstts"


# Voix de repli quand la voix configurée ne rend rien. Neurale standard, donc
# couverte par les 500 k caractères gratuits du F0, et l'une des deux seules
# voix fr-FR hors MAI à porter des styles (`cheerful`, `excited`, `sad`,
# `whispering`) — un repli sans émotion du tout s'entendrait comme une panne.
_SECOURS_NEURAL = "fr-FR-HenriNeural"


class SpeechToText(Protocol):
    async def transcribe(self, pcm16k_mono: bytes) -> str: ...


class TextToSpeech(Protocol):
    async def synthesize(self, text: str, style: str | None = None) -> bytes: ...

    # Voix dont les styles `express-as` s'entendront réellement, ou "" si ce
    # moteur n'en porte aucun. C'est elle, et non `cfg.azure_voice`, qui décide
    # des tons proposés à Wally : avec le TTS 1min monté, la voix Azure figure
    # toujours en config sans que personne ne l'entende jamais.
    style_voice: str


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

    @staticmethod
    def _corps(rep, etape: str) -> dict:
        """Le JSON de la réponse, ou {} — en DISANT ce qui est arrivé à la place.

        Vu en production dès la première soirée : « Expecting value: line 1
        column 1 » remontait par l'attrape-tout, donc on savait qu'un énoncé
        était perdu sans savoir pourquoi. Une passerelle qui répond du HTML, un
        429, un corps vide : ce sont trois pannes différentes et un seul
        message. Le statut et l'extrait du corps les séparent.
        """
        try:
            return rep.json()
        except Exception:  # noqa: BLE001
            logger.warning("OneMinSTT: {e} — réponse non-JSON (HTTP {c}) : {t}",
                           e=etape, c=rep.status_code, t=(rep.text or "")[:160])
            return {}

    async def _televerser(self, client, wav: bytes) -> str:
        """Le chemin de l'asset, ou "". Réessaie une fois — l'échec est ALÉATOIRE.

        Mesuré le 2026-08-18 en rafale, sur un fichier identique et valide :
        environ un upload sur six repart en « The file may be corrupt. Please
        upload another », sans rapport avec la durée ni la taille. C'est un
        défaut de leur côté, et il coûtait un énoncé à chaque fois — sept en une
        soirée. Un second essai suffit à le ramener au négligeable ; au-delà, ce
        ne serait plus un aléa mais une panne, et insister ferait attendre une
        parole que personne n'écoutera plus.
        """
        for essai in (1, 2):
            rep = await client.post(
                f"{self._BASE}/assets", headers={"API-KEY": self._key},
                files={"asset": ("enonce.wav", wav, "audio/wav")},
            )
            chemin = (self._corps(rep, "upload").get("fileContent") or {}).get("path")
            if chemin:
                if essai > 1:
                    logger.info("OneMinSTT: upload repassé au 2e essai")
                return chemin
            if essai == 1:
                logger.info("OneMinSTT: upload refusé (HTTP {c}) — second essai",
                            c=rep.status_code)
        return ""

    async def transcribe(self, pcm16k_mono: bytes) -> str:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                chemin = await self._televerser(client, self._wav(pcm16k_mono))
                if not chemin:
                    return ""
                rep = await client.post(
                    f"{self._BASE}/features",
                    headers={"API-KEY": self._key, "Content-Type": "application/json"},
                    json={"type": "SPEECH_TO_TEXT", "model": self._model,
                          "promptObject": {"audioUrl": chemin, "response_format": "text",
                                           "language": self._lang}},
                )
            corps = self._corps(rep, "transcription")
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


class OneMinTTS:
    """TTS Qwen3-TTS-Flash via 1min.ai. Sortie : PCM 48 kHz mono 16-bit.

    Choisi pour sa VOIX (« Arthur »), pas pour sa vitesse. Azure streame — le
    premier son sort en 0,3 s et Wally parle pendant que la suite se synthétise.
    Ici l'API rend un fichier complet : mesuré à 3,2 s pour une réplique courte,
    4,0 s pour une longue. Sur un salon vocal, ce délai s'ajoute au STT et au
    LLM avant que quiconque entende quoi que ce soit.

    D'où le découpage par phrases de `synthesize_stream` : on synthétise la
    première, on la joue, et les suivantes se préparent pendant qu'elle passe.
    Le premier son arrive alors au bout de la PREMIÈRE phrase et non de tout le
    texte — c'est le seul levier disponible, l'API n'ayant pas de streaming.

    Deux renoncements assumés par rapport à Azure :
    - Pas de style émotionnel : `resolve_style` module la voix Azure selon
      l'émotion dominante (`mstts:express-as`), Qwen n'a pas d'équivalent. Le
      style reçu est donc IGNORÉ, pas silencieusement mal appliqué.
    - `language_type` est forcé (« French » par défaut) : en « Auto », le modèle
      se trompe de langue sur des répliques courtes ou mêlées d'anglais — c'est
      le constat de l'owner, et le jargon Apex rend le cas fréquent.
    """

    _BASE = "https://api.1min.ai/api"
    _ASSETS = "https://asset.1min.ai"
    _MAX_CHARS = 600  # limite dure de l'API, par appel

    # Aucun `express-as` chez Qwen : rien à proposer comme ton. La chaîne vide
    # (et non `None`) dit « voix inconnue » à `supported_styles()`, qui rend
    # l'ensemble vide — un style inventé rendrait la synthèse muette ailleurs.
    style_voice = ""

    # Langue Discord/persona → valeur attendue par l'API (liste close côté 1min.ai).
    _LANGUES = {
        "fr": "French", "en": "English", "es": "Spanish", "de": "German",
        "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese",
        "ko": "Korean", "zh": "Chinese",
    }

    def __init__(self, api_key: str, voice: str = "Arthur", model: str = "qwen3-tts-flash",
                 language: str = "fr-FR", timeout: float = 60.0, secours=None) -> None:
        self._key = api_key
        self._voice = voice
        self._model = model
        self._langue = self._LANGUES.get((language or "fr").split("-")[0].lower(), "French")
        self._timeout = timeout
        # Filet : si l'API ne rend RIEN, Azure prend la réplique. Muet est le
        # pire symptôme de ce bot — il se croit en train de parler, personne ne
        # l'entend, et on cherche ailleurs pendant une heure. Une voix
        # inattendue, elle, s'entend immédiatement.
        self._secours = secours

    def _decouper(self, texte: str) -> list[str]:
        """Découpe en phrases jouables, sans jamais dépasser la limite de l'API.

        Le découpage sert la LATENCE : chaque morceau rendu est un morceau que
        Wally peut déjà dire. On ne coupe donc pas au milieu d'un mot, et on
        regroupe les phrases courtes — une réplique hachée en cinq appels
        coûterait plus d'attente qu'elle n'en fait gagner.
        """
        import re

        morceaux: list[str] = []
        courant = ""
        for phrase in re.split(r"(?<=[.!?…])\s+", (texte or "").strip()):
            if not phrase:
                continue
            # Une phrase seule plus longue que la limite : on la coupe aux espaces.
            while len(phrase) > self._MAX_CHARS:
                coupe = phrase.rfind(" ", 0, self._MAX_CHARS)
                coupe = coupe if coupe > 0 else self._MAX_CHARS
                morceaux.append(phrase[:coupe].strip())
                phrase = phrase[coupe:].strip()
            if not courant:
                courant = phrase
            elif len(courant) + 1 + len(phrase) <= self._MAX_CHARS and len(courant) < 90:
                courant = f"{courant} {phrase}"   # trop court pour valoir un appel
            else:
                morceaux.append(courant)
                courant = phrase
        if courant:
            morceaux.append(courant)
        return morceaux

    async def _un_morceau(self, client, texte: str) -> bytes:
        """PCM 48 kHz mono d'un morceau, ou b'' — l'appelant continue sans lui."""
        import audioop

        rep = await client.post(
            f"{self._BASE}/features",
            headers={"API-KEY": self._key, "Content-Type": "application/json"},
            json={"type": "TEXT_TO_SPEECH", "model": self._model,
                  "promptObject": {"text": texte, "voice": self._voice,
                                   "language_type": self._langue}},
        )
        corps = rep.json()
        if "errorCode" in corps:
            logger.warning("OneMinTTS: refus {c} — {m}", c=corps.get("errorCode"),
                           m=str(corps.get("message"))[:140])
            return b""
        res = ((corps.get("aiRecord") or {}).get("aiRecordDetail") or {}).get("resultObject")
        chemin = (res[0] if isinstance(res, list) and res else res) or ""
        if not chemin:
            logger.warning("OneMinTTS: réponse sans audio — Wally resterait muet")
            return b""
        audio = await client.get(f"{self._ASSETS}/{chemin}")
        brut = audio.content
        # L'en-tête WAV rendu par l'API MENT sur la taille des données (44 739 s
        # annoncées pour 5 s réelles) : on saute les 44 octets d'en-tête et on
        # lit le reste tel quel, plutôt que de faire confiance au `wave` parsé.
        pcm24k = brut[44:] if brut[:4] == b"RIFF" else brut
        converti, _ = audioop.ratecv(pcm24k, 2, 1, 24000, 48000, None)
        return converti

    async def synthesize(self, text: str, style: str | None = None) -> bytes:
        morceaux = []
        await self.synthesize_stream(text, style, morceaux.append)
        return b"".join(morceaux)

    async def synthesize_stream(self, text: str, style: str | None, on_chunk) -> None:
        import httpx

        produit = 0
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for morceau in self._decouper(text):
                    pcm = await self._un_morceau(client, morceau)
                    if pcm:
                        produit += len(pcm)
                        on_chunk(pcm)
        except Exception as e:  # noqa: BLE001
            logger.warning("OneMinTTS.synthesize_stream a échoué: {e}", e=e)
        if produit or self._secours is None or not (text or "").strip():
            return
        # Rien n'est sorti alors qu'il y avait quelque chose à dire.
        logger.warning("OneMinTTS muet — repli sur la voix de secours")
        await self._secours.synthesize_stream(text, style, on_chunk)


class AzureTTS:
    """TTS Azure Neural. Sortie : PCM 48 kHz mono 16-bit (prêt pour Discord)."""

    def __init__(self, key: str, region: str, voice: str,
                 secours: "AzureTTS | None" = None) -> None:
        self._key, self._region, self._voice = key, region, voice
        # Voix de repli quand celle-ci ne rend RIEN. Sert au cas MAI : la
        # ressource est en SKU F0, où Azure ne facture pas mais BLOQUE une fois
        # le quota atteint — et les voix MAI, comptées en tokens, ne sont pas
        # couvertes par les 500 k caractères du neural standard. Le 2026-08-07,
        # ce mutisme a coûté une soirée : il entendait, décidait, générait sa
        # réplique, jouait son bip, et aucun son ne sortait.
        self._secours = secours

    @property
    def style_voice(self) -> str:
        """La voix qui parle vraiment — c'est elle qui décide des tons offerts."""
        return self._voice

    async def synthesize(self, text: str, style: str | None = None) -> bytes:
        morceaux: list[bytes] = []
        await self.synthesize_stream(text, style, morceaux.append)
        return b"".join(morceaux)

    async def synthesize_stream(self, text: str, style: str | None, on_chunk) -> None:
        """Synthèse en streaming : `on_chunk(pcm48k_mono)` est appelé au fil de l'audio produit,
        ce qui permet de commencer à jouer dès le premier chunk (latence perçue minimale)."""
        produit = 0

        def compter(pcm: bytes) -> None:
            nonlocal produit
            produit += len(pcm)
            on_chunk(pcm)

        await asyncio.to_thread(self._stream_sync, text, style, compter)
        if produit or self._secours is None or not (text or "").strip():
            return
        # Le style DOIT être ramené aux capacités de la voix de secours : Henri
        # ne connaît ni `softvoice` ni `angry`, et un `express-as` inconnu fait
        # échouer la synthèse — le repli serait muet à son tour, pour la même
        # raison que celle qu'il est censé rattraper.
        from bot.discord.voice.style import adapt_style

        style_repli = adapt_style(style, getattr(self._secours, "_voice", None))
        logger.warning("AzureTTS: {v} n'a rien rendu — repli sur {s} (style {a} → {b})",
                       v=self._voice, s=getattr(self._secours, "_voice", "?"),
                       a=style, b=style_repli)
        await self._secours.synthesize_stream(text, style_repli, on_chunk)

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
            f'xmlns:mstts="{_MSTTS_NS}" '
            f'xml:lang="{lang}"><voice name={quoteattr(self._voice)}>{inner}</voice></speak>'
        )


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
    provider = (cfg.tts_provider or "azure").lower()
    if provider in ("1min", "1min.ai", "onemin", "qwen"):
        cle = os.environ.get("ONEMIN_API_KEY", "")
        if cle:
            logger.info("voice: TTS {m} — voix {v}, langue forcée",
                        m=cfg.onemin_tts_model, v=cfg.onemin_tts_voice)
            secours = None
            try:
                azure_key, azure_region = _azure_creds()
                secours = AzureTTS(key=azure_key, region=azure_region, voice=cfg.azure_voice)
            except Exception as e:  # noqa: BLE001 — sans Azure, on part sans filet, en le disant
                logger.warning("voice: pas de voix de secours ({e})", e=e)
            return OneMinTTS(api_key=cle, voice=cfg.onemin_tts_voice,
                             model=cfg.onemin_tts_model, language=cfg.language,
                             secours=secours)
        # On ne laisse PAS Wally muet pour une clé manquante : Azure reprend, et
        # le dit. Une voix inattendue s'entend ; un silence, on l'attribue à
        # autre chose pendant une heure.
        logger.warning("voice: TTS « {p} » demandé mais ONEMIN_API_KEY manque — repli sur Azure",
                       p=provider)
    key, region = _azure_creds()
    # Les voix MAI ne sont pas couvertes par les 500 k caractères gratuits du
    # SKU F0 (elles se comptent en tokens) : le jour où le quota tombe, Azure
    # bloque et Wally devient muet. On lui adosse donc une voix neurale
    # standard, elle couverte — mieux vaut une voix moins expressive que pas de
    # voix du tout. Rien à adosser si la voix principale EST déjà la standard.
    secours = None
    if ":MAI-Voice-" in (cfg.azure_voice or "") and _SECOURS_NEURAL != cfg.azure_voice:
        secours = AzureTTS(key=key, region=region, voice=_SECOURS_NEURAL)
    # Le chemin 1min annonce sa voix au boot, celui-ci se taisait : au premier
    # doute sur ce qu'on entend, il n'y avait rien à relire dans les logs. Les
    # styles disponibles y figurent parce qu'ils DÉPENDENT de la voix — une
    # voix sans style rendrait le système d'émotion inerte, sans rien casser.
    from bot.discord.voice.style import supported_styles

    logger.info("voice: TTS Azure — voix {v}, {n} styles émotionnels{s}",
                v=cfg.azure_voice, n=len(supported_styles(cfg.azure_voice)),
                s=f", secours {secours._voice}" if secours is not None else "")
    return AzureTTS(key=key, region=region, voice=cfg.azure_voice, secours=secours)
