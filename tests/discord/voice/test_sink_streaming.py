"""Tests du WallyAudioSink en mode streaming : émission des frames brutes + fin de parole VAD."""
import asyncio
import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

from bot.discord.voice import sink as sink_mod
from bot.discord.voice.audio import FRAME_BYTES
from bot.discord.voice.sink import WallyAudioSink


class _User:
    def __init__(self, uid):
        self.id = uid


class _VoiceData:
    def __init__(self, pcm):
        self.pcm = pcm


def _stereo_48k(n_frames_16k: int) -> bytes:
    """Construit du PCM 48 kHz stéréo donnant ~`n_frames_16k` frames de 20 ms après to_stt_format."""
    samples_16k = (FRAME_BYTES // 2) * n_frames_16k       # échantillons mono @16k visés
    samples_48k = samples_16k * 3                          # 48k = 3× 16k
    mono = (b"\x10\x00") * samples_48k                     # valeur non nulle (audio « plein »)
    return audioop.tostereo(mono, 2, 1, 1)


async def test_streaming_emet_chaque_frame_via_on_frame():
    loop = asyncio.get_running_loop()
    frames = []
    sink = WallyAudioSink(
        service=None, aggressiveness=2, on_segment=None, loop=loop,
        on_frame=lambda user, frame: frames.append((user.id, frame)),
        on_speech_end=lambda user, seg: None,
    )
    sink.write(_User(7), _VoiceData(_stereo_48k(3)))
    await asyncio.sleep(0)  # laisse tourner les call_soon_threadsafe

    assert len(frames) == 3
    assert all(uid == 7 and len(f) == FRAME_BYTES for uid, f in frames)


async def test_streaming_route_le_segment_vad_vers_on_speech_end(monkeypatch):
    loop = asyncio.get_running_loop()
    ends = []

    class _FakeSeg:
        def __init__(self, *a):
            self._n = 0

        def feed(self, frame):
            self._n += 1
            return b"SEGMENT" if self._n == 1 else None  # clôt un segment au 1er frame

    monkeypatch.setattr(sink_mod, "VadSegmenter", _FakeSeg)
    sink = WallyAudioSink(
        service=None, aggressiveness=2, on_segment=None, loop=loop,
        on_frame=lambda user, frame: None,
        on_speech_end=lambda user, seg: ends.append((user.id, seg)),
    )
    sink.write(_User(9), _VoiceData(_stereo_48k(1)))
    await asyncio.sleep(0)

    assert ends == [(9, b"SEGMENT")]


async def test_mode_batch_route_le_segment_vers_on_segment(monkeypatch):
    """Sans on_frame/on_speech_end, le segment VAD passe par on_segment (comportement existant)."""
    loop = asyncio.get_running_loop()
    segments = []

    class _FakeSeg:
        def __init__(self, *a):
            pass

        def feed(self, frame):
            return b"BATCHSEG"

    async def on_segment(user, seg):
        segments.append((user.id, seg))

    monkeypatch.setattr(sink_mod, "VadSegmenter", _FakeSeg)
    sink = WallyAudioSink(service=None, aggressiveness=2, on_segment=on_segment, loop=loop)
    sink.write(_User(3), _VoiceData(_stereo_48k(1)))
    await asyncio.sleep(0.05)

    assert (3, b"BATCHSEG") in segments
