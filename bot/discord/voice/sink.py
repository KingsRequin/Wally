"""WallyAudioSink — reçoit le PCM par locuteur, segmente via VAD, déclenche un callback."""
import asyncio

from discord.ext import voice_recv
from loguru import logger

from bot.discord.voice.audio import FRAME_BYTES, VadSegmenter, to_stt_format


class WallyAudioSink(voice_recv.AudioSink):
    """Reçoit le PCM par locuteur, segmente par VAD, déclenche un callback async par segment.

    Deux modes :
    - batch (défaut) : `on_segment(user, pcm16k_mono)` est appelé (coroutine) sur chaque
      segment de parole clos par le VAD.
    - streaming : si `on_frame` et `on_speech_end` sont fournis, chaque frame brute de 20 ms
      est émise au fil de l'eau via `on_frame(user, frame)` (pour le STT streaming distant), et
      la fin de parole (segment VAD clos) via `on_speech_end(user, segment)` — au lieu de
      `on_segment`. Ces deux callbacks sont synchrones et planifiés sur la boucle via
      `call_soon_threadsafe` (ordre FIFO préservé), car `write()` tourne dans un thread audio.

    Anti-larsen : l'audio est ignoré pendant que `service.is_speaking` est True.
    Le service est passé directement au sink pour éviter de passer par bot.voice_service.
    """

    def __init__(self, service, aggressiveness: int, on_segment, loop: asyncio.AbstractEventLoop,
                 on_frame=None, on_speech_end=None) -> None:
        super().__init__()
        self._service = service
        self._aggr = aggressiveness
        self._on_segment = on_segment
        self._on_frame = on_frame
        self._on_speech_end = on_speech_end
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
            streaming = self._on_frame is not None
            while len(buf) >= FRAME_BYTES:
                frame = bytes(buf[:FRAME_BYTES])
                del buf[:FRAME_BYTES]
                if streaming:
                    self._loop.call_soon_threadsafe(self._on_frame, user, frame)
                out = seg.feed(frame)
                if out:
                    if streaming:
                        self._loop.call_soon_threadsafe(self._on_speech_end, user, out)
                    else:
                        asyncio.run_coroutine_threadsafe(self._on_segment(user, out), self._loop)
        except Exception as e:  # noqa: BLE001
            logger.warning("WallyAudioSink.write a échoué: {e}", e=e)

    def cleanup(self) -> None:
        self._segmenters.clear()
        self._frame_buf.clear()
