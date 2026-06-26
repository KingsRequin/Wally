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
