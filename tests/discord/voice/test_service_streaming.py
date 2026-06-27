"""Tests du VoiceService en mode STT streaming distant (remote_stream)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config import VoiceConfig
from bot.discord.voice.service import VoiceService


def _streaming_service():
    bot = MagicMock()
    streaming = MagicMock()
    streaming.feed_sync = MagicMock()
    streaming.speech_end_sync = MagicMock()
    with patch("bot.discord.voice.service.build_streaming_stt", return_value=streaming), \
         patch("bot.discord.voice.service.build_stt"), \
         patch("bot.discord.voice.service.build_tts"):
        svc = VoiceService(bot, VoiceConfig(enabled=True, stt_provider="remote_stream"))
    return svc, streaming


def _user(uid=42):
    u = MagicMock()
    u.id = uid
    u.name = "bob"
    u.display_name = "Bob"
    return u


async def test_mode_streaming_construit_le_provider_et_cable_les_callbacks():
    svc, streaming = _streaming_service()
    assert svc._streaming is streaming
    assert svc._stt is None
    assert streaming.on_partial == svc._on_stream_partial
    assert streaming.on_final == svc._on_stream_final


def test_on_frame_feed_le_provider_et_memorise_le_locuteur():
    svc, streaming = _streaming_service()
    u = _user(42)
    svc._on_frame(u, b"abc")
    streaming.feed_sync.assert_called_once_with("42", b"abc")
    assert svc._stream_users["42"] is u


def test_on_speech_end_delegue_le_segment_au_provider():
    svc, streaming = _streaming_service()
    svc._on_speech_end(_user(42), b"SEG")
    streaming.speech_end_sync.assert_called_once_with("42", b"SEG")


async def test_on_stream_final_dispatche_le_transcript():
    svc, streaming = _streaming_service()
    svc._stream_users["42"] = _user(42)
    with patch("bot.discord.voice.service.handle_transcript", new=AsyncMock()) as ht:
        await svc._on_stream_final("42", "bonjour wally", 12.0)
    ht.assert_awaited_once()
    kwargs = ht.call_args.kwargs
    assert kwargs["transcript"] == "bonjour wally"
    assert kwargs["speaker_user_id"] == "42"
    assert kwargs["stt_ms"] == 12.0
    assert kwargs["speaker_label"] == "Bob (@bob)"


async def test_on_stream_final_locuteur_inconnu_est_noop():
    svc, streaming = _streaming_service()
    with patch("bot.discord.voice.service.handle_transcript", new=AsyncMock()) as ht:
        await svc._on_stream_final("999", "x", 1.0)  # pas de user mémorisé
    ht.assert_not_awaited()


async def test_on_stream_final_pendant_que_wally_parle_ignore_sauf_stop():
    svc, streaming = _streaming_service()
    svc._stream_users["42"] = _user(42)
    svc.is_speaking = True
    svc.stop_speaking = MagicMock()
    with patch("bot.discord.voice.service.handle_transcript", new=AsyncMock()) as ht:
        await svc._on_stream_final("42", "et donc je disais que", 5.0)  # parole normale
        ht.assert_not_awaited()
        svc.stop_speaking.assert_not_called()
        await svc._on_stream_final("42", "stop", 5.0)  # ordre d'arrêt court → barge-in
        svc.stop_speaking.assert_called_once()


def test_on_stream_partial_publie_un_event_partial_non_persistant():
    svc, streaming = _streaming_service()
    svc._stream_users["42"] = _user(42)
    feed = MagicMock()
    svc._bot.voice_feed = feed
    svc._channel = MagicMock()
    svc._channel.id = 5
    svc._channel.name = "vocal"

    svc._on_stream_partial("42", "salu")

    feed.publish.assert_called_once()
    event = feed.publish.call_args.args[0]
    assert event["type"] == "partial"
    assert event["text"] == "salu"
    assert event["speaker"] == "Bob (@bob)"
    assert feed.publish.call_args.kwargs.get("persist") is False
