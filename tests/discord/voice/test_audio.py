from bot.discord.voice.audio import to_stt_format, VadSegmenter, FRAME_BYTES


def test_to_stt_format_halves_then_downsamples():
    # 48k stéréo 16-bit : 1 frame stéréo = 4 octets. 480 frames = 10ms.
    pcm = b"\x01\x02\x03\x04" * 480
    out = to_stt_format(pcm)
    # mono 16k : ~1/6 de la taille d'origine en octets (stéréo→mono /2, 48k→16k /3)
    assert 0 < len(out) <= len(pcm) // 5
    assert len(out) % 2 == 0


def test_vad_segmenter_emits_on_silence(monkeypatch):
    import bot.discord.voice.audio as audio
    # Mock webrtcvad : 'parole' tant que la frame n'est pas tout-zéro
    class FakeVad:
        def __init__(self, agg): pass
        def is_speech(self, frame, rate): return frame != b"\x00" * len(frame)
    monkeypatch.setattr(audio.webrtcvad, "Vad", FakeVad)
    seg = VadSegmenter(aggressiveness=2)
    speech = b"\x11\x22" * (FRAME_BYTES // 2)
    silence = b"\x00" * FRAME_BYTES
    assert seg.feed(speech) is None       # parole, on accumule
    assert seg.feed(speech) is None
    out = None
    # plusieurs frames de silence clôturent le segment
    for _ in range(20):
        out = seg.feed(silence) or out
    assert out is not None and len(out) >= FRAME_BYTES
