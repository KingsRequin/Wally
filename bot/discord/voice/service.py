"""VoiceService — gère le cycle de vie audio vocal (join/leave/speak/listen)."""
import asyncio
import io
import warnings
from collections import OrderedDict

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

import discord
from discord.ext import voice_recv
from loguru import logger

from bot.config import VoiceConfig

POST_SPEAK_MUTE_S = 0.4  # durée de mute post-lecture pour éviter que la queue residu soit transcrite
from bot.discord.voice.brain import (
    _is_stop_request,
    _voice_publish,
    generate_voice_greeting,
    handle_transcript,
)
from bot.discord.voice.providers import build_stt, build_streaming_stt, build_tts
from bot.discord.voice.quota import VoiceQuota
from bot.discord.voice.style import resolve_style
from bot.discord.voice.sink import WallyAudioSink
from bot.discord.voice.tools import VOICE_TOOLS, make_voice_tool_executor


def _member_label(member) -> str:
    """Libellé d'un locuteur : 'pseudo affiché (@username)'.

    `username` (member.name) est le pseudo Discord NON modifiable ; `display_name`
    est le pseudo affiché (nickname serveur / nom global, modifiable).
    """
    name = getattr(member, "name", None)
    display = getattr(member, "display_name", None) or name or str(member)
    if name and name != display:
        return f"{display} (@{name})"
    return display


def _make_cue(freq: int = 620, ms: int = 150, sr: int = 48000, vol: float = 0.12) -> bytes:
    """Génère un bref bip neutre (PCM 48 kHz stéréo 16-bit) pour signaler 'je réfléchis'."""
    import math
    import struct
    n = int(sr * ms / 1000)
    fade = max(1, int(sr * 0.012))  # fondu 12 ms pour éviter les clics
    out = bytearray()
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)
        s = int(vol * env * 32767 * math.sin(2 * math.pi * freq * i / sr))
        out += struct.pack("<h", s)
    return audioop.tostereo(bytes(out), 2, 1, 1)


_THINKING_CUE = _make_cue()


def _ensure_opus() -> None:
    """discord.py ne charge pas toujours libopus automatiquement (image slim).
    Sans Opus, l'audio reçu n'est pas décodé (écoute morte) ni encodé (parole muette)."""
    if discord.opus.is_loaded():
        return
    for name in ("libopus.so.0", "opus", "libopus.so"):
        try:
            discord.opus.load_opus(name)
            logger.info("libopus chargé manuellement ({n})", n=name)
            return
        except Exception:  # noqa: BLE001
            continue
    logger.warning("libopus introuvable — le vocal ne pourra ni écouter ni parler")


class VoiceService:
    """Cycle de vie audio Discord : connexion salon vocal, STT, TTS, anti-larsen, auto-leave."""

    def __init__(self, bot, cfg: VoiceConfig) -> None:
        self._bot = bot
        self._cfg = cfg
        _ensure_opus()
        # Indices STT : nom de Wally + surnoms, pour mieux reconnaître quand on l'appelle.
        stt_phrases: list[str] = []
        try:
            stt_phrases = [bot.config.bot.name, *(bot.config.bot.trigger_names or [])]
        except Exception:  # noqa: BLE001
            pass
        # STT : streaming distant (remote_stream) ou batch (azure / faster_whisper).
        self._streaming = None
        self._stt = None
        self._stt_phrases = stt_phrases
        self._build_stt_pipeline(cfg, stt_phrases)
        self._tts = build_tts(cfg)
        self._vc: discord.VoiceClient | None = None
        self._channel = None
        self._pending_inviter: str | None = None  # qui a demandé à Wally de venir (pour la salutation)
        self.history: list[dict] = []
        self._current_speaker_id: str | None = None
        self._stream_users: dict[str, object] = {}  # speaker_id → membre (streaming multi-locuteurs)
        self._maintain_task: asyncio.Task | None = None
        self._silence_task: asyncio.Task | None = None  # watchdog fin-de-parole à l'horloge
        self.voice_tools = VOICE_TOOLS
        self.tool_executor = make_voice_tool_executor(
            bot, self, current_speaker_id=lambda: self._current_speaker_id
        )
        self.is_speaking: bool = False
        self.is_responding: bool = False  # une seule réponse à la fois (conversation de groupe)
        # Paroles entendues pendant qu'il répond : une entrée par locuteur (id → (label, texte, ts)),
        # traitées dans l'ordre d'arrivée. Remplace l'ancien slot unique qui jetait les autres.
        self._pending_queue: "OrderedDict[str, tuple[str, str, float]]" = OrderedDict()
        self.quota = VoiceQuota()  # suivi du quota Azure (STT/TTS) du mois
        self._last_speech_ts: float = 0.0
        self._auto_leave_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Propriétés publiques
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._vc is not None

    @property
    def channel_id(self) -> int | None:
        return self._channel.id if self._channel else None

    @property
    def channel_name(self) -> str:
        return getattr(self._channel, "name", "") if self._channel else ""

    def _build_stt_pipeline(self, cfg: VoiceConfig, phrases: list[str]) -> None:
        """Construit le pipeline STT : streaming distant (remote_stream) ou batch."""
        provider = (cfg.stt_provider or "").lower()
        if provider in ("remote_stream", "remote-stream", "remote"):
            self._streaming = build_streaming_stt(cfg, phrases=phrases)
            self._streaming.on_partial = self._on_stream_partial
            self._streaming.on_final = self._on_stream_final
            self._stt = None
        else:
            self._streaming = None
            self._stt = build_stt(cfg, phrases=phrases)

    def reload_config(self, cfg: VoiceConfig) -> None:
        """Recharge la config à chaud (voix, langue, seuils, provider STT) sans redémarrer."""
        self._cfg = cfg
        try:
            phrases = [self._bot.config.bot.name, *(self._bot.config.bot.trigger_names or [])]
        except Exception:  # noqa: BLE001
            phrases = []
        try:
            self._build_stt_pipeline(cfg, phrases)
            self._tts = build_tts(cfg)
            logger.info("VoiceService: config rechargée (voix={v}, stt={s})",
                        v=cfg.azure_voice, s=cfg.stt_provider)
        except Exception as e:  # noqa: BLE001
            logger.warning("VoiceService.reload_config a échoué: {e}", e=e)

    def members_in_channel(self) -> list[int]:
        """Retourne les IDs des membres non-bot présents dans le salon."""
        if not self._channel:
            return []
        return [m.id for m in self._channel.members if not m.bot]

    def members_names(self) -> list[str]:
        """Libellés 'pseudo (@username)' des membres humains présents dans le salon."""
        if not self._channel:
            return []
        return [_member_label(m) for m in self._channel.members if not m.bot]

    def members_activity(self) -> list[str]:
        """Activité Discord (jeu, musique…) des présents, ex 'Alex joue à Valorant'."""
        if not self._channel:
            return []
        presence = getattr(self._bot, "presence", None)
        if presence is None:
            return []
        out: list[str] = []
        for m in self._channel.members:
            if m.bot:
                continue
            try:
                snap = presence.get(m.id)
            except Exception:  # noqa: BLE001
                snap = None
            if snap and snap.get("activities"):
                out.append(f"{m.display_name} {', '.join(snap['activities'])}")
        return out

    # ------------------------------------------------------------------
    # Join / Leave
    # ------------------------------------------------------------------

    async def join(self, channel, inviter: str | None = None) -> None:
        """Rejoint un salon vocal, attache le sink d'écoute, démarre le watchdog auto-leave.

        `inviter` : nom de la personne qui a demandé à Wally de venir (injecté dans la salutation)."""
        if self._vc is not None:
            await self.leave()
        self._pending_inviter = inviter
        self._channel = channel
        self._vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
        loop = asyncio.get_running_loop()
        self._last_speech_ts = loop.time()
        self._stream_users.clear()
        if self._streaming is not None:
            # Streaming distant : audio brut au fil de l'eau + fin de parole VAD locale (flush).
            sink = WallyAudioSink(
                service=self,
                aggressiveness=self._cfg.vad_aggressiveness,
                on_segment=None,
                loop=loop,
                on_frame=self._on_frame,
                on_speech_end=self._on_speech_end,
                silence_timeout_s=self._cfg.vad_silence_timeout_s,
            )
            self._maintain_task = loop.create_task(self._streaming.maintain())
            loop.create_task(self._streaming.warmup())  # pré-charge le fallback CPU local
        else:
            sink = WallyAudioSink(
                service=self,
                aggressiveness=self._cfg.vad_aggressiveness,
                on_segment=self._on_segment,
                loop=loop,
                silence_timeout_s=self._cfg.vad_silence_timeout_s,
            )
            # Pré-charge le modèle STT (faster-whisper) dès l'arrivée → évite ~2,5 s au 1er segment.
            _warmup = getattr(self._stt, "warmup", None)
            if _warmup is not None:
                loop.create_task(_warmup())
        # Watchdog fin-de-parole : Discord coupe le silence, donc le VAD ne voit jamais la fin ;
        # ce tick clôt l'énoncé à l'horloge (envoie le flush distant / émet le segment batch).
        self._silence_task = loop.create_task(self._silence_watch(sink))
        self._vc.listen(sink)
        self._auto_leave_task = loop.create_task(self._auto_leave_watch())
        logger.info("voice: rejoint le salon {c}", c=channel.id)
        # Salutation à l'arrivée, en tâche de fond (ne bloque pas la réponse à /join).
        loop.create_task(self._greet())

    async def _greet(self) -> None:
        """Wally salue brièvement en arrivant dans le salon vocal."""
        try:
            present = ", ".join(self.members_names())
            activity = " ; ".join(self.members_activity())
            text = await generate_voice_greeting(
                self._bot, present_label=present, channel_name=self.channel_name,
                activity_label=activity, inviter=self._pending_inviter,
            )
            if text:
                await self.speak(text)
        except Exception as e:  # noqa: BLE001
            logger.warning("voice _greet a échoué: {e}", e=e)
        finally:
            self._pending_inviter = None

    async def greet_newcomer(self, member) -> None:
        """Salue une personne qui vient de rejoindre le salon (anti-spam : pas si Wally parle déjà)."""
        if self.is_speaking:
            return
        try:
            name = getattr(member, "display_name", str(member))
            present = ", ".join(self.members_names())
            activity = " ; ".join(self.members_activity())
            text = await generate_voice_greeting(
                self._bot, present_label=present, newcomer=name, channel_name=self.channel_name,
                activity_label=activity,
            )
            if text:
                await self.speak(text)
        except Exception as e:  # noqa: BLE001
            logger.warning("voice greet_newcomer a échoué: {e}", e=e)

    async def leave(self) -> None:
        """Quitte le salon vocal, stoppe l'écoute et le watchdog."""
        if self._auto_leave_task is not None:
            self._auto_leave_task.cancel()
            self._auto_leave_task = None
        if self._maintain_task is not None:
            self._maintain_task.cancel()
            self._maintain_task = None
        if self._silence_task is not None:
            self._silence_task.cancel()
            self._silence_task = None
        if self._streaming is not None:
            try:
                await self._streaming.close_all()  # ferme toutes les connexions WS distantes
            except Exception as e:  # noqa: BLE001
                logger.warning("voice: fermeture des sessions streaming a échoué: {e}", e=e)
        self._stream_users.clear()
        if self._vc is not None:
            try:
                self._vc.stop_listening()
            except Exception:  # noqa: BLE001
                pass
            try:
                await self._vc.disconnect()
            except Exception as e:  # noqa: BLE001
                logger.warning("voice: disconnect a échoué: {e}", e=e)
        self._vc = None
        self._channel = None
        self.history.clear()
        logger.info("voice: salon quitté")

    # ------------------------------------------------------------------
    # Parole (TTS → playback)
    # ------------------------------------------------------------------

    async def speak(self, text: str) -> None:
        """Synthétise `text` en TTS puis le joue dans le salon (anti-larsen inclus)."""
        if not text or self._vc is None:
            return
        # Style de voix : tag explicite de Wally ([murmure]…) sinon son humeur du moment.
        try:
            emotion_state = self._bot.emotion.get_state()
        except Exception:  # noqa: BLE001
            emotion_state = None
        style, text = resolve_style(text, emotion_state)
        if not text:
            return
        self.quota.add_tts_chars(len(text))
        self.is_speaking = True
        try:
            # Streaming si le provider TTS le supporte (joue dès le 1er chunk) ; sinon batch.
            stream_fn = getattr(self._tts, "synthesize_stream", None)
            if stream_fn is not None:
                await self._speak_streaming(text, style, stream_fn)
            else:
                await self._speak_batch(text, style)
            await asyncio.sleep(POST_SPEAK_MUTE_S)
        except Exception as e:  # noqa: BLE001
            logger.warning("voice speak a échoué: {e}", e=e)
        finally:
            self.is_speaking = False

    async def _speak_streaming(self, text: str, style: str | None, stream_fn) -> None:
        """Joue le TTS au fil de la synthèse via une source alimentée en continu (latence minimale)."""
        from bot.discord.voice.audio import StreamingPCMSource
        source = StreamingPCMSource()
        done = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _after(err):
            if err:
                logger.warning("voice playback erreur: {e}", e=err)
            loop.call_soon_threadsafe(done.set)

        self._vc.play(source, after=_after)
        try:
            # Les chunks PCM 48 kHz mono arrivent au fil de la synthèse → joués immédiatement.
            await stream_fn(text, style, source.feed)
        finally:
            source.finish()  # garantit la fin de lecture même si la synthèse échoue
        await done.wait()

    async def _speak_batch(self, text: str, style: str | None) -> None:
        """Synthèse complète puis lecture (fallback si le provider TTS ne streame pas)."""
        pcm = await self._tts.synthesize(text, style)
        if not pcm:
            return
        # 48 kHz mono 16-bit → stéréo pour discord.PCMAudio.
        pcm_stereo = audioop.tostereo(pcm, 2, 1, 1)
        source = discord.PCMAudio(io.BytesIO(pcm_stereo))
        done = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _after(err):
            if err:
                logger.warning("voice playback erreur: {e}", e=err)
            loop.call_soon_threadsafe(done.set)

        self._vc.play(source, after=_after)
        await done.wait()

    async def play_cue(self) -> None:
        """Joue un bref bip 'je réfléchis' (feedback de latence) et attend sa fin."""
        if self._vc is None or self.is_speaking:
            return
        try:
            source = discord.PCMAudio(io.BytesIO(_THINKING_CUE))
            done = asyncio.Event()
            loop = asyncio.get_running_loop()
            self._vc.play(source, after=lambda _e: loop.call_soon_threadsafe(done.set))
            await done.wait()
        except Exception as e:  # noqa: BLE001
            logger.warning("voice play_cue a échoué: {e}", e=e)

    def stop_speaking(self) -> None:
        """Coupe la lecture en cours (barge-in)."""
        try:
            if self._vc is not None and self._vc.is_playing():
                self._vc.stop()
        except Exception as e:  # noqa: BLE001
            logger.warning("voice stop_speaking a échoué: {e}", e=e)

    # ------------------------------------------------------------------
    # Callback interne — segment audio validé par VAD (mode batch)
    # ------------------------------------------------------------------

    async def _on_segment(self, user, pcm16k_mono: bytes) -> None:
        """Transcrit un segment de parole (STT batch) et appelle le cerveau."""
        try:
            self.quota.add_stt_seconds(len(pcm16k_mono) / 32000)  # 16 kHz mono 16-bit = 32000 o/s
            _t0 = asyncio.get_running_loop().time()
            text = await self._stt.transcribe(pcm16k_mono)
            stt_ms = (asyncio.get_running_loop().time() - _t0) * 1000  # latence de transcription
            await self._dispatch_transcript(user, text, stt_ms)
        except Exception as e:  # noqa: BLE001
            logger.warning("voice _on_segment a échoué: {e}", e=e)

    async def _dispatch_transcript(self, user, text: str, stt_ms: float) -> None:
        """Aiguille une transcription finale (batch ou streaming) vers le cerveau.

        Pendant que Wally parle, seuls les ordres d'arrêt courts passent (barge-in) ; le
        reste est ignoré (sa propre voix captée par les micros, ou parole hors-sujet)."""
        text = (text or "").strip()
        if not text:
            return
        self._last_speech_ts = asyncio.get_running_loop().time()
        if self.is_speaking:
            # Garde-fou anti-auto-coupure : une vraie commande d'arrêt est brève.
            if len(text) <= 40 and _is_stop_request(text):
                logger.info("voice: interruption '{t}' → stop", t=text)
                self.stop_speaking()
            return
        label = _member_label(user)
        self._current_speaker_id = str(user.id)
        await handle_transcript(
            bot=self._bot,
            service=self,
            speaker_user_id=str(user.id),
            speaker_label=label,
            transcript=text,
            stt_ms=stt_ms,
        )

    # ------------------------------------------------------------------
    # Callbacks internes — STT streaming distant
    # ------------------------------------------------------------------

    def _on_frame(self, user, frame: bytes) -> None:
        """Frame brute de 20 ms (16 kHz mono) → streamée au serveur STT distant. Sync, sur la boucle."""
        self._stream_users[str(user.id)] = user
        try:
            self._last_speech_ts = asyncio.get_running_loop().time()
        except RuntimeError:
            pass
        if self._streaming is not None:
            self._streaming.feed_sync(str(user.id), frame)

    def _on_speech_end(self, user, segment: bytes) -> None:
        """Fin de parole (VAD local) → flush distant (ou batch local en fallback). Sync, sur la boucle."""
        self._stream_users[str(user.id)] = user
        if self._streaming is not None:
            self._streaming.speech_end_sync(str(user.id), segment)

    def _on_stream_partial(self, speaker_id: str, text: str) -> None:
        """Transcription partielle (live) → publiée sur le feed vocal (affichage temps réel, non persistée)."""
        user = self._stream_users.get(speaker_id)
        label = _member_label(user) if user is not None else speaker_id
        _voice_publish(self._bot, self, "partial", persist=False,
                       speaker=label, speaker_id=speaker_id, text=text)

    async def _on_stream_final(self, speaker_id: str, text: str, stt_ms: float) -> None:
        """Transcription finale (précise) → cerveau, comme un segment batch."""
        user = self._stream_users.get(speaker_id)
        if user is None:
            return
        await self._dispatch_transcript(user, text, stt_ms)

    async def _silence_watch(self, sink, interval: float = 0.15) -> None:
        """Clôt à l'horloge l'énoncé d'un locuteur qui s'est tu (Discord coupe le silence →
        le VAD local ne se déclenche jamais). Sans ça, le `final` distant ne part jamais."""
        try:
            while self._vc is not None:
                await asyncio.sleep(interval)
                sink.flush_idle()
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("voice _silence_watch a échoué: {e}", e=e)

    # ------------------------------------------------------------------
    # Watchdog auto-leave
    # ------------------------------------------------------------------

    async def _auto_leave_watch(self) -> None:
        """Quitte automatiquement si le salon est vide ou s'il n'y a plus de parole."""
        timeout = self._cfg.auto_leave_minutes * 60
        try:
            while self._vc is not None:
                await asyncio.sleep(10)
                if not self.members_in_channel():
                    logger.info("voice: salon vide → auto-leave")
                    await self.leave()
                    return
                loop = asyncio.get_running_loop()
                if loop.time() - self._last_speech_ts > timeout:
                    logger.info("voice: inactivité {t}s → auto-leave", t=timeout)
                    await self.leave()
                    return
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("voice _auto_leave_watch a échoué: {e}", e=e)
