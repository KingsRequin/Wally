"""WallyAudioSink — reçoit le PCM par locuteur, segmente via VAD, déclenche un callback."""
import asyncio

from discord.ext import voice_recv
from loguru import logger

from bot.discord.voice.audio import FRAME_BYTES, VadSegmenter, to_stt_format


class WallyAudioSink(voice_recv.AudioSink):
    """Reçoit le PCM par locuteur, segmente par VAD, déclenche un callback async par segment.

    callback signature: async def on_segment(user, pcm16k_mono: bytes)

    Anti-larsen : l'audio est ignoré pendant que `service.is_speaking` est True.
    Le service est passé directement au sink pour éviter de passer par bot.voice_service.
    """

    def __init__(self, service, aggressiveness: int, on_segment, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._service = service
        self._aggr = aggressiveness
        self._on_segment = on_segment
        self._loop = loop
        self._segmenters: dict[int, VadSegmenter] = {}
        self._frame_buf: dict[int, bytearray] = {}

    def wants_opus(self) -> bool:
        """Retourne False : on veut du PCM décodé (pas Opus)."""
        return False

    def write(self, user, data: voice_recv.VoiceData) -> None:
        """Appelé pour chaque paquet audio reçu. user peut être None.

        On NE coupe PAS l'écoute pendant que Wally parle : `_on_segment` filtre alors
        pour ne garder que les ordres d'arrêt (barge-in). Cela transcrit aussi la voix
        de Wally renvoyée par les micros (larsen), mais elle est ignorée côté brain.
        """
        if user is None:
            return
        try:
            if not data.pcm:
                return
            pcm16 = to_stt_format(data.pcm)  # 48k stéréo → 16k mono
            buf = self._frame_buf.setdefault(user.id, bytearray())
            buf.extend(pcm16)
            seg = self._segmenters.setdefault(user.id, VadSegmenter(self._aggr))
            while len(buf) >= FRAME_BYTES:
                frame = bytes(buf[:FRAME_BYTES])
                del buf[:FRAME_BYTES]
                out = seg.feed(frame)
                if out:
                    asyncio.run_coroutine_threadsafe(self._on_segment(user, out), self._loop)
        except Exception as e:  # noqa: BLE001
            logger.warning("WallyAudioSink.write a échoué: {e}", e=e)

    def cleanup(self) -> None:
        self._segmenters.clear()
        self._frame_buf.clear()
