import threading
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

import discord
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


class StreamingPCMSource(discord.AudioSource):
    """Source audio Discord alimentée en continu — joue le TTS au fil de la synthèse.

    Le producteur (TTS) appelle `feed()` avec des chunks PCM 48 kHz mono 16-bit à mesure
    qu'ils arrivent, et `finish()` à la fin. Discord appelle `read()` toutes les 20 ms depuis
    son thread de lecture ; on rend des frames stéréo de 20 ms (3840 o). La lecture démarre dès
    le premier chunk au lieu d'attendre toute la synthèse → latence perçue bien moindre.
    """

    _FRAME_MONO = 1920    # 20 ms @ 48 kHz mono 16-bit
    _FRAME_STEREO = 3840  # idem stéréo

    def __init__(self) -> None:
        self._buf = bytearray()
        self._cv = threading.Condition()
        self._finished = False

    def feed(self, pcm48k_mono: bytes) -> None:
        with self._cv:
            self._buf.extend(pcm48k_mono)
            self._cv.notify()

    def finish(self) -> None:
        """Signale la fin du flux : read() videra le reste puis renverra b''."""
        with self._cv:
            self._finished = True
            self._cv.notify_all()

    def is_opus(self) -> bool:
        return False

    def read(self) -> bytes:
        with self._cv:
            # Attend d'avoir un frame complet, sauf si le flux est terminé (évite le CPU à vide).
            while len(self._buf) < self._FRAME_MONO and not self._finished:
                self._cv.wait()
            if len(self._buf) >= self._FRAME_MONO:
                mono = bytes(self._buf[:self._FRAME_MONO])
                del self._buf[:self._FRAME_MONO]
            elif self._buf:  # fin : dernier frame partiel, paddé au silence
                mono = bytes(self._buf).ljust(self._FRAME_MONO, b"\x00")
                self._buf.clear()
            else:
                return b""  # terminé et vide → discord arrête la lecture
        return audioop.tostereo(mono, 2, 1, 1)

    def cleanup(self) -> None:
        # Appelé par discord quand la lecture s'arrête : débloque un read() en attente.
        self.finish()


class VadSegmenter:
    """Découpe un flux PCM 16 kHz mono en segments de parole délimités par les silences."""

    def __init__(self, aggressiveness: int, sample_rate: int = SAMPLE_RATE) -> None:
        self._vad = webrtcvad.Vad(aggressiveness)
        self._rate = sample_rate
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
