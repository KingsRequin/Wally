"""Tests de StreamingPCMSource : AudioSource Discord alimentée en continu (TTS streaming)."""
import threading
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

from bot.discord.voice.audio import StreamingPCMSource


def test_read_rend_un_frame_stereo_de_20ms():
    src = StreamingPCMSource()
    src.feed(b"\x01\x02" * 960)  # 1920 octets = 20 ms @ 48 kHz mono 16-bit
    frame = src.read()
    assert len(frame) == 3840  # 20 ms stéréo 16-bit


def test_read_convertit_mono_en_stereo():
    src = StreamingPCMSource()
    mono = b"\x01\x02" * 960  # 1920 octets
    src.feed(mono)
    frame = src.read()
    assert frame == audioop.tostereo(mono, 2, 1, 1)


def test_read_vide_apres_finish_retourne_fin():
    src = StreamingPCMSource()
    src.finish()
    assert src.read() == b""  # buffer vide + terminé → discord arrête la lecture


def test_dernier_frame_partiel_est_padde_puis_fin():
    src = StreamingPCMSource()
    src.feed(b"\x01\x02" * 100)  # 200 octets < 1920 (frame partiel)
    src.finish()
    frame = src.read()
    assert len(frame) == 3840  # paddé au silence puis converti stéréo
    assert src.read() == b""  # plus rien ensuite


def test_read_bloque_jusqu_au_feed():
    src = StreamingPCMSource()
    out = {}

    def reader():
        out["frame"] = src.read()

    t = threading.Thread(target=reader)
    t.start()
    t.join(timeout=0.2)
    assert t.is_alive()  # pas de données encore → read bloque (ne consomme pas le CPU à vide)

    src.feed(b"\x01\x02" * 960)
    t.join(timeout=1.0)
    assert not t.is_alive()  # le feed a débloqué read
    assert len(out["frame"]) == 3840


def test_cleanup_debloque_read():
    src = StreamingPCMSource()
    out = {}

    def reader():
        out["frame"] = src.read()

    t = threading.Thread(target=reader)
    t.start()
    t.join(timeout=0.2)
    assert t.is_alive()

    src.cleanup()  # discord appelle cleanup() en fin de lecture → ne doit pas hang
    t.join(timeout=1.0)
    assert not t.is_alive()
    assert out["frame"] == b""


async def test_speak_streaming_joue_les_chunks_au_fil_de_la_synthese():
    """_speak_streaming alimente une StreamingPCMSource pendant que discord la draine,
    et n'attend pas toute la synthèse avant de jouer."""
    from bot.discord.voice.service import VoiceService

    played = bytearray()

    class _FakeVC:
        def play(self, source, after):
            def drain():
                while True:
                    frame = source.read()
                    if frame == b"":
                        break
                    played.extend(frame)
                after(None)
            threading.Thread(target=drain).start()

    async def fake_stream(text, style, on_chunk):
        on_chunk(b"\x01\x02" * 960)
        on_chunk(b"\x03\x04" * 960)

    svc = object.__new__(VoiceService)  # contourne __init__ (pas de creds Azure en test)
    svc._vc = _FakeVC()
    await svc._speak_streaming("salut", None, fake_stream)

    expected = audioop.tostereo(b"\x01\x02" * 960, 2, 1, 1) + audioop.tostereo(b"\x03\x04" * 960, 2, 1, 1)
    assert bytes(played) == expected
