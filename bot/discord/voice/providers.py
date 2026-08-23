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
    # des tons proposés à Wally.
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
            logger.warning("AzureSTT.transcribe a échoué: {e!r}", e=e)
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
            logger.warning("FasterWhisperSTT.transcribe a échoué: {e!r}", e=e)
            return ""


class XaiSTT:
    """STT distant Grok, chez xAI. SOUPAPE, pas moteur.

    Le `small` local transcrit un énoncé à la fois : à trois locuteurs sa file
    monte à 5-6 s et il finit par JETER de la parole. Cette voie reprend ce qui
    serait perdu — 141 énoncés en 36 min de live le 2026-08-19, le PC GPU de
    l'owner étant éteint, soit 19,6 % de l'audio entendu. Elle ne sert à rien
    quand ce PC tourne.

    Retenue contre Qwen3-ASR-Flash (1min.ai) et Whisper turbo (Groq), sur trois
    mesures faites le 2026-08-19 avec un énoncé de synthèse de 3,3 s :

    - **le nom passe.** `keyterm` biaise réellement la reconnaissance, jusqu'à
      cent termes. 1min.ai n'expose AUCUN équivalent (14 emplacements essayés,
      sortie identique au caractère près) et écrivait « Wall-E » ou « ou ali ».
    - **812 ms**, contre 3,5 s mesurées chez 1min.ai. Une soupape qui rattrape
      de la parole en retard ne vaut que par sa vitesse.
    - **elle se tait sur le vide.** Un silence et un souffle rendent tous deux
      la chaîne vide. C'est le défaut qui a disqualifié 1min.ai : il rendait du
      chinois et du japonais sur les énoncés courts d'un salon francophone
      (15 lignes en 28 min), `language` envoyé et ignoré.

    Coût : 0,10 $/h d'audio, facturé à la durée réelle — l'API rend `duration`.
    Soit ~0,75 $/mois à soixante heures de vocal, GPU éteint tout du long. Groq
    affichait 0,04 $/h mais facture 10 s minimum par requête, or nos énoncés
    font 1,8 s : 0,23 $/h effectif, pour un service moins bon.
    """

    _URL = "https://api.x.ai/v1/stt"

    # Plafonds de l'API : cent termes de biais, cinquante caractères chacun.
    _MAX_KEYTERMS = 100
    _MAX_KEYTERM_LEN = 50

    def __init__(self, api_key: str, language: str = "fr-FR",
                 timeout: float = 20.0, phrases: list[str] | None = None,
                 extra_terms=None, db=None, usd_per_hour: float = 0.0) -> None:
        self._key = api_key
        self._lang = (language or "fr").split("-")[0]
        # Serré volontairement : cette voie ne sert qu'à rattraper de la parole
        # en retard. Une transcription qui arrive après 20 s ne rattrape plus
        # rien, elle encombre — mieux vaut la lâcher et le dire.
        self._timeout = timeout
        # Le nom de Wally et ses surnoms. Le moteur local les reçoit déjà en
        # `hotwords` ; sans eux ici, un énoncé rattrapé perdait justement le mot
        # qui décide si Wally est interpellé.
        # Dédupliqués sans tenir compte de la casse : `trigger_names` porte
        # « wally » à côté du `name` « Wally », et deux fois le même mot
        # occupait deux des cent places pour rien.
        self.keyterms = self._normaliser(phrases)
        # Les noms des gens présents dans le salon. Une SOURCE et non une liste :
        # le provider est construit une fois au démarrage, alors qu'ils entrent
        # et sortent toute la soirée. Relue à chaque énoncé.
        self._extra_terms = extra_terms
        # Ce qu'on dépense, écrit plutôt qu'estimé. Le tarif vient de la config :
        # celui de DeepSeek a doublé du jour au lendemain, et on ne redéploie pas
        # une image pour un changement de prix.
        self._db = db
        self._usd_per_hour = float(usd_per_hour or 0.0)

    @classmethod
    def _normaliser(cls, termes, deja: set[str] | None = None,
                    place: int | None = None) -> list[str]:
        """Nettoie, tronque et déduplique sans tenir compte de la casse.

        `trigger_names` porte « wally » à côté du `name` « Wally », et un
        pseudo peut valoir l'un des deux : le même mot occuperait deux des cent
        places pour rien.
        """
        vus = deja if deja is not None else set()
        place = cls._MAX_KEYTERMS if place is None else place
        gardes: list[str] = []
        for terme in (termes or []):
            terme = (terme or "").strip()[:cls._MAX_KEYTERM_LEN]
            if not terme or terme.lower() in vus:
                continue
            vus.add(terme.lower())
            gardes.append(terme)
            if len(gardes) >= place:
                break
        return gardes

    def _tous_les_termes(self) -> list[str]:
        """Le nom de Wally d'abord, les présents ensuite.

        L'ordre n'est pas cosmétique : c'est son nom qui décide s'il est
        interpellé, et un salon très peuplé ne doit pas pouvoir l'évincer des
        cent places.
        """
        if self._extra_terms is None:
            return self.keyterms
        try:
            presents = self._extra_terms()
        except Exception as exc:  # noqa: BLE001 — un biais optionnel ne coûte pas un énoncé
            logger.debug("XaiSTT: présents illisibles, biais réduit au nom : {e!r}", e=exc)
            return self.keyterms
        deja = {k.lower() for k in self.keyterms}
        reste = self._MAX_KEYTERMS - len(self.keyterms)
        return self.keyterms + self._normaliser(presents, deja, reste)

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

    def _champs(self) -> list[tuple[str, tuple[None, str]]]:
        """Les champs du multipart, hors fichier.

        Une LISTE et non un dict : `keyterm` se répète autant de fois qu'il y a
        de termes, ce qu'un dict écraserait au dernier.
        """
        champs = [("language", (None, self._lang)), ("format", (None, "true"))]
        champs += [("keyterm", (None, k)) for k in self._tous_les_termes()]
        return champs

    async def _transcrire(self, client, wav: bytes) -> str:
        """Le texte, ou "" — en DISANT toujours ce qui est arrivé à la place.

        Un 5xx est réessayé UNE fois : la passerelle du fournisseur précédent
        rendait cinq 502 en 28 min, chacun coûtant un énoncé faute de seconde
        chance. Un 4xx ne l'est jamais — une clé invalide ou un fichier refusé
        ne se répare pas en insistant, et on paierait une seconde attente pour
        le même refus.
        """
        for essai in (1, 2):
            rep = await client.post(
                self._URL,
                headers={"Authorization": f"Bearer {self._key}"},
                files=[("file", ("enonce.wav", wav, "audio/wav")), *self._champs()],
            )
            statut = getattr(rep, "status_code", 0)
            try:
                corps = rep.json()
            except Exception:  # noqa: BLE001 — une passerelle en vrac répond du HTML
                corps = None
            if corps is None:
                logger.warning("XaiSTT: réponse non-JSON (HTTP {c}) : {t}",
                               c=statut, t=(getattr(rep, "text", "") or "")[:160])
            elif statut < 400:
                await self._facturer(corps.get("duration"))
                return str(corps.get("text") or "").strip()
            else:
                erreur = corps.get("error")
                motif = erreur.get("message") if isinstance(erreur, dict) else erreur
                logger.warning("XaiSTT: refus HTTP {c} — {m}", c=statut, m=str(motif)[:140])
            if statut < 500:
                return ""       # refus franc : insister ne le changera pas
            if essai == 1:
                logger.info("XaiSTT: HTTP {c} — second essai", c=statut)
        return ""

    async def _facturer(self, duree) -> None:
        """Inscrit la dépense de CET appel. Jamais bloquant.

        Appelé sur toute réponse acceptée, y compris quand le texte revient
        vide : le fournisseur a traité l'audio et le facture, et c'est
        précisément la dépense qu'on veut voir grossir si le moteur déraille.
        Sans `duration`, on n'invente pas de montant.
        """
        if self._db is None or not self._usd_per_hour or not duree:
            return
        try:
            await self._db.log_cost(
                model="xai-stt", input_tokens=0, output_tokens=0,
                cost_usd=float(duree) * self._usd_per_hour / 3600,
                purpose="voice_stt_overflow",
            )
        except Exception as exc:  # noqa: BLE001 — écrire la dépense est un confort
            logger.debug("XaiSTT: dépense non enregistrée : {e!r}", e=exc)

    async def transcribe(self, pcm16k_mono: bytes) -> str:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await self._transcrire(client, self._wav(pcm16k_mono))
        except Exception as e:  # noqa: BLE001 — une soupape ne casse jamais l'écoute
            logger.warning("XaiSTT.transcribe a échoué: {e!r}", e=e)
            return ""


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
            logger.warning("AzureTTS.synthesize_stream a échoué: {e!r}", e=e)

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


def build_overflow_stt(cfg: VoiceConfig, phrases: list[str] | None = None,
                       extra_terms=None, db=None) -> SpeechToText | None:
    """La soupape de débordement, ou None si elle n'est pas configurée.

    Rend None sans bruit quand le provider n'est pas demandé, mais LOGUE quand
    il l'est sans clé : une soupape qu'on croit posée et qui ne l'est pas se
    voit seulement le jour où la parole disparaît, c'est-à-dire trop tard.

    `phrases` porte le nom de Wally et ses surnoms, comme pour le moteur local :
    un énoncé rattrapé sans eux perdrait justement le mot qui décide si Wally
    est interpellé.
    """
    provider = (cfg.overflow_stt_provider or "").lower()
    if not provider:
        return None
    if provider != "xai":
        logger.warning("voice: provider de débordement inconnu « {p} » — ignoré", p=provider)
        return None
    cle = os.environ.get("XAI_API_KEY", "")
    if not cle:
        logger.warning("voice: débordement « {p} » demandé mais XAI_API_KEY manque "
                       "— la parole en trop continuera d'être JETÉE", p=provider)
        return None
    soupape = XaiSTT(api_key=cle, language=cfg.language,
                     timeout=cfg.overflow_stt_timeout_s, phrases=phrases,
                     extra_terms=extra_terms, db=db,
                     usd_per_hour=cfg.overflow_stt_usd_per_hour)
    logger.info("voice: soupape de débordement active (xai, {n} terme(s) de biais)",
                n=len(soupape.keyterms))
    return soupape


def build_streaming_stt(cfg: VoiceConfig, phrases: list[str] | None = None,
                        extra_terms=None, db=None):
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
        overflow=build_overflow_stt(cfg, phrases=phrases, extra_terms=extra_terms, db=db),
        overflow_max_inflight=cfg.overflow_stt_max_inflight,
    )


def build_tts(cfg: VoiceConfig) -> TextToSpeech:
    provider = (cfg.tts_provider or "azure").lower()
    if provider != "azure":
        # Azure est le seul moteur de synthèse. On ne laisse PAS Wally muet pour
        # une valeur de config inconnue : une voix inattendue s'entend tout de
        # suite ; un silence, on l'attribue à autre chose pendant une heure.
        logger.warning("voice: TTS « {p} » inconnu — repli sur Azure", p=provider)
    key, region = _azure_creds()
    # Les voix MAI ne sont pas couvertes par les 500 k caractères gratuits du
    # SKU F0 (elles se comptent en tokens) : le jour où le quota tombe, Azure
    # bloque et Wally devient muet. On lui adosse donc une voix neurale
    # standard, elle couverte — mieux vaut une voix moins expressive que pas de
    # voix du tout. Rien à adosser si la voix principale EST déjà la standard.
    secours = None
    if ":MAI-Voice-" in (cfg.azure_voice or "") and _SECOURS_NEURAL != cfg.azure_voice:
        secours = AzureTTS(key=key, region=region, voice=_SECOURS_NEURAL)
    # La voix est annoncée au boot : au premier doute sur ce qu'on entend, il
    # faut pouvoir la relire dans les logs. Les
    # styles disponibles y figurent parce qu'ils DÉPENDENT de la voix — une
    # voix sans style rendrait le système d'émotion inerte, sans rien casser.
    from bot.discord.voice.style import supported_styles

    logger.info("voice: TTS Azure — voix {v}, {n} styles émotionnels{s}",
                v=cfg.azure_voice, n=len(supported_styles(cfg.azure_voice)),
                s=f", secours {secours._voice}" if secours is not None else "")
    return AzureTTS(key=key, region=region, voice=cfg.azure_voice, secours=secours)
