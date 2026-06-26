"""VoiceService — gère le cycle de vie audio vocal (join/leave/speak/listen)."""
import asyncio
import io
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

import discord
from discord.ext import voice_recv
from loguru import logger

from bot.config import VoiceConfig

POST_SPEAK_MUTE_S = 0.4  # durée de mute post-lecture pour éviter que la queue residu soit transcrite
from bot.discord.voice.brain import handle_transcript
from bot.discord.voice.providers import build_stt, build_tts
from bot.discord.voice.sink import WallyAudioSink
from bot.discord.voice.tools import VOICE_TOOLS, make_voice_tool_executor


class VoiceService:
    """Cycle de vie audio Discord : connexion salon vocal, STT, TTS, anti-larsen, auto-leave."""

    def __init__(self, bot, cfg: VoiceConfig) -> None:
        self._bot = bot
        self._cfg = cfg
        self._stt = build_stt(cfg)
        self._tts = build_tts(cfg)
        self._vc: discord.VoiceClient | None = None
        self._channel = None
        self.history: list[dict] = []
        self._current_speaker_id: str | None = None
        self.voice_tools = VOICE_TOOLS
        self.tool_executor = make_voice_tool_executor(
            bot, self, current_speaker_id=lambda: self._current_speaker_id
        )
        self.is_speaking: bool = False
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

    def members_in_channel(self) -> list[int]:
        """Retourne les IDs des membres non-bot présents dans le salon."""
        if not self._channel:
            return []
        return [m.id for m in self._channel.members if not m.bot]

    # ------------------------------------------------------------------
    # Join / Leave
    # ------------------------------------------------------------------

    async def join(self, channel) -> None:
        """Rejoint un salon vocal, attache le sink d'écoute, démarre le watchdog auto-leave."""
        if self._vc is not None:
            await self.leave()
        self._channel = channel
        self._vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
        loop = asyncio.get_running_loop()
        self._last_speech_ts = loop.time()
        sink = WallyAudioSink(
            service=self,
            aggressiveness=self._cfg.vad_aggressiveness,
            on_segment=self._on_segment,
            loop=loop,
        )
        self._vc.listen(sink)
        self._auto_leave_task = loop.create_task(self._auto_leave_watch())
        logger.info("voice: rejoint le salon {c}", c=channel.id)

    async def leave(self) -> None:
        """Quitte le salon vocal, stoppe l'écoute et le watchdog."""
        if self._auto_leave_task is not None:
            self._auto_leave_task.cancel()
            self._auto_leave_task = None
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
        self.is_speaking = True
        try:
            pcm = await self._tts.synthesize(text)
            if not pcm:
                return
            # AzureTTS → 48 kHz mono 16-bit ; discord.PCMAudio attend du stéréo.
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
            await asyncio.sleep(POST_SPEAK_MUTE_S)
        except Exception as e:  # noqa: BLE001
            logger.warning("voice speak a échoué: {e}", e=e)
        finally:
            self.is_speaking = False

    # ------------------------------------------------------------------
    # Callback interne — segment audio validé par VAD
    # ------------------------------------------------------------------

    async def _on_segment(self, user, pcm16k_mono: bytes) -> None:
        """Transcrit un segment de parole et appelle le cerveau."""
        try:
            self._last_speech_ts = asyncio.get_running_loop().time()
            text = await self._stt.transcribe(pcm16k_mono)
            if not text:
                return
            # Résolution du label utilisateur (best-effort)
            if hasattr(user, "display_name") and hasattr(user, "name"):
                label = (
                    f"{user.display_name} (@{user.name})"
                    if user.display_name != user.name
                    else user.display_name
                )
            else:
                label = str(user)
            self._current_speaker_id = str(user.id)
            await handle_transcript(
                bot=self._bot,
                service=self,
                speaker_user_id=str(user.id),
                speaker_label=label,
                transcript=text,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("voice _on_segment a échoué: {e}", e=e)

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
