from bot.discord.voice.quota import FREE_STT_SECONDS, FREE_TTS_CHARS, VoiceQuota


def test_add_and_snapshot(tmp_path):
    q = VoiceQuota(path=str(tmp_path / "q.json"))
    q.add_stt_seconds(600)   # 10 min d'écoute
    q.add_tts_chars(10_000)
    snap = q.snapshot()
    assert snap["stt_used_seconds"] == 600
    assert snap["stt_remaining_seconds"] == FREE_STT_SECONDS - 600
    assert snap["tts_used_chars"] == 10_000
    assert snap["tts_remaining_chars"] == FREE_TTS_CHARS - 10_000


def test_persists_across_instances(tmp_path):
    p = str(tmp_path / "q.json")
    VoiceQuota(path=p).add_tts_chars(500)
    assert VoiceQuota(path=p).snapshot()["tts_used_chars"] == 500


def test_remaining_never_negative(tmp_path):
    q = VoiceQuota(path=str(tmp_path / "q.json"))
    q.add_stt_seconds(FREE_STT_SECONDS + 9999)
    assert q.snapshot()["stt_remaining_seconds"] == 0.0
