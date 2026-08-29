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
    """Le vrai `VoiceData` porte TOUJOURS son paquet (attribut de `__slots__`),
    et sa véracité booléenne est ce qui distingue une frame réelle du
    remplissage inventé par la bibliothèque. Un double sans paquet faisait
    tomber `write()` dans son garde-fou : sourd, mais tests verts."""

    def __init__(self, pcm, packet=None):
        self.pcm = pcm
        self.packet = packet if packet is not None else object()


def _stereo_48k(n_frames_16k: int) -> bytes:
    """Construit du PCM 48 kHz stéréo donnant ~`n_frames_16k` frames de 20 ms après to_stt_format."""
    samples_16k = (FRAME_BYTES // 2) * n_frames_16k       # échantillons mono @16k visés
    samples_48k = samples_16k * 3                          # 48k = 3× 16k
    mono = (b"\x10\x00") * samples_48k                     # valeur non nulle (audio « plein »)
    return audioop.tostereo(mono, 2, 1, 1)


class _SegParlant:
    """Segmenter qui entend de la parole partout — webrtcvad, lui, refuse une
    onde constante, et ces tests portent sur le RELAIS, pas sur le VAD."""

    def __init__(self, *a):
        self.en_parole = True

    def feed(self, frame):
        return None


async def test_streaming_emet_les_frames_parlees_via_on_frame(monkeypatch):
    """Ce test exigeait « CHAQUE frame », y compris le silence — c'était le
    défaut : le sink relayait tout au serveur distant, qui avalait cent quatre
    secondes de silence entre deux prises de parole et saturait. Il porte
    maintenant sur ce qui compte : la parole passe."""
    monkeypatch.setattr(sink_mod, "VadSegmenter", _SegParlant)
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


async def test_le_silence_ne_part_pas_au_serveur_distant():
    """Le vrai VAD sur une onde constante : ce n'est pas de la parole, et rien
    ne doit partir. C'est ce qui noyait le serveur GPU."""
    loop = asyncio.get_running_loop()
    frames = []
    sink = WallyAudioSink(
        service=None, aggressiveness=2, on_segment=None, loop=loop,
        on_frame=lambda user, frame: frames.append((user.id, frame)),
        on_speech_end=lambda user, seg: None,
    )
    sink.write(_User(7), _VoiceData(_stereo_48k(50)))
    await asyncio.sleep(0)

    assert frames == []


async def test_streaming_route_le_segment_vad_vers_on_speech_end(monkeypatch):
    loop = asyncio.get_running_loop()
    ends = []

    class _FakeSeg:
        def __init__(self, *a):
            self._n = 0
            self.en_parole = True

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


class _NeverEndsSeg:
    """Segmenter qui ne clôt JAMAIS via le VAD (simule Discord qui coupe le silence),
    mais dont flush() rend le segment accumulé une seule fois."""

    def __init__(self, *a):
        self.fed = 0
        self._flushed = False

    def feed(self, frame):
        self.fed += 1
        return None  # jamais de fin détectée par le VAD : pas de frames de silence

    def flush(self):
        if self.fed and not self._flushed:
            self._flushed = True
            return b"IDLESEG"
        return None


async def test_flush_idle_emet_le_segment_apres_silence_wallclock(monkeypatch):
    """Streaming : parole puis plus aucune frame → flush_idle clôt l'énoncé à l'horloge."""
    loop = asyncio.get_running_loop()
    ends = []
    clock = {"now": 1000.0}
    monkeypatch.setattr(sink_mod, "VadSegmenter", _NeverEndsSeg)
    sink = WallyAudioSink(
        service=None, aggressiveness=2, on_segment=None, loop=loop,
        on_frame=lambda u, f: None,
        on_speech_end=lambda u, seg: ends.append((u.id, seg)),
        silence_timeout_s=0.6, now_fn=lambda: clock["now"],
    )
    sink.write(_User(5), _VoiceData(_stereo_48k(2)))  # parole en cours
    await asyncio.sleep(0)

    # Silence pas encore écoulé → aucun flush prématuré.
    sink.flush_idle()
    await asyncio.sleep(0)
    assert ends == []

    # Le temps avance au-delà du timeout sans nouvelle frame → l'énoncé est clos.
    clock["now"] += 0.7
    sink.flush_idle()
    await asyncio.sleep(0)
    assert ends == [(5, b"IDLESEG")]

    # Idempotent : pas de double émission aux ticks suivants.
    clock["now"] += 1.0
    sink.flush_idle()
    await asyncio.sleep(0)
    assert ends == [(5, b"IDLESEG")]


async def test_flush_idle_mode_batch_emet_via_on_segment(monkeypatch):
    """Batch : même bug latent → flush_idle clôt l'énoncé via on_segment."""
    loop = asyncio.get_running_loop()
    segments = []
    clock = {"now": 500.0}
    monkeypatch.setattr(sink_mod, "VadSegmenter", _NeverEndsSeg)

    async def on_segment(user, seg):
        segments.append((user.id, seg))

    sink = WallyAudioSink(
        service=None, aggressiveness=2, on_segment=on_segment, loop=loop,
        silence_timeout_s=0.6, now_fn=lambda: clock["now"],
    )
    sink.write(_User(8), _VoiceData(_stereo_48k(2)))
    await asyncio.sleep(0.05)

    clock["now"] += 0.7
    sink.flush_idle()
    await asyncio.sleep(0.05)
    assert segments == [(8, b"IDLESEG")]


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


def test_cleanup_sur_sink_non_initialise_ne_leve_pas():
    """`AudioSink.__del__` appelle `cleanup()` même si `__init__` n'a pas abouti.

    Sans garde, la vraie cause d'un échec d'init disparaissait derrière un
    `AttributeError: '_lock'` levé DANS un `__del__` — donc « Exception ignored »,
    sans traceback exploitable, au moment précis où on aurait besoin de la cause.
    """
    sink = WallyAudioSink.__new__(WallyAudioSink)  # __init__ jamais exécuté
    sink.cleanup()  # ne doit pas lever
