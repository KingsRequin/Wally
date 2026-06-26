"""Tests pour bot/discord/voice/service.py — join/leave/speak + anti-larsen."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.config import VoiceConfig
from bot.discord.voice.service import VoiceService


def _make_service():
    """Crée un VoiceService avec les dépendances (STT/TTS) mockées."""
    bot = MagicMock()
    with patch("bot.discord.voice.service.build_stt"), \
         patch("bot.discord.voice.service.build_tts"):
        svc = VoiceService(bot, VoiceConfig(enabled=True))
    return svc


@pytest.mark.asyncio
async def test_join_connects_and_listens():
    """join() doit se connecter au salon et activer l'écoute."""
    svc = _make_service()
    channel = MagicMock()
    channel.id = 555
    vc = MagicMock()
    vc.listen = MagicMock()
    channel.connect = AsyncMock(return_value=vc)

    with patch("bot.discord.voice.service.voice_recv") as mock_vr:
        mock_vr.VoiceRecvClient = MagicMock()
        await svc.join(channel)

    assert svc.is_connected is True
    assert svc.channel_id == 555
    channel.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_leave_disconnects():
    """leave() doit déconnecter le vc et mettre is_connected à False."""
    svc = _make_service()
    channel = MagicMock()
    channel.id = 555
    vc = MagicMock()
    vc.listen = MagicMock()
    vc.stop_listening = MagicMock()
    vc.disconnect = AsyncMock()
    channel.connect = AsyncMock(return_value=vc)

    with patch("bot.discord.voice.service.voice_recv") as mock_vr:
        mock_vr.VoiceRecvClient = MagicMock()
        await svc.join(channel)

    await svc.leave()
    assert svc.is_connected is False
    vc.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_speak_mutes_listening_during_playback():
    """speak() doit remettre is_speaking à False après la lecture."""
    svc = _make_service()
    svc._tts = MagicMock()
    svc._tts.synthesize = AsyncMock(return_value=b"\x00\x00" * 100)

    vc = MagicMock()

    def play_and_fire(source, after=None):
        # Simule la fin du playback : invoque le after callback immédiatement
        # (passe par loop.call_soon_threadsafe dans le vrai code, mais ici
        #  call_soon_threadsafe appelle done.set depuis le thread courant)
        if after is not None:
            after(None)

    vc.play = play_and_fire
    svc._vc = vc

    with patch("bot.discord.voice.service.audioop") as mock_ao, \
         patch("bot.discord.voice.service.discord") as mock_discord:
        mock_ao.tostereo = MagicMock(return_value=b"\x00\x00" * 200)
        mock_discord.PCMAudio = MagicMock()
        await svc.speak("bonjour")

    assert svc.is_speaking is False  # remis à False après playback
    svc._tts.synthesize.assert_awaited_once_with("bonjour")


@pytest.mark.asyncio
async def test_speak_no_vc_is_noop():
    """speak() sans salon connecté ne doit pas lever d'exception."""
    svc = _make_service()
    svc._tts = MagicMock()
    svc._tts.synthesize = AsyncMock(return_value=b"PCM")
    # _vc est None par défaut
    await svc.speak("test")  # ne doit pas lever
    svc._tts.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_speak_sets_is_speaking_then_resets():
    """is_speaking passe à True pendant le speak et revient False après."""
    svc = _make_service()
    svc._tts = MagicMock()
    svc._tts.synthesize = AsyncMock(return_value=b"\x00\x00" * 100)

    vc = MagicMock()
    speaking_states = []

    def capture_play(source, after=None):
        speaking_states.append(svc.is_speaking)
        # Simule la fin du playback pour débloquer done.wait()
        if after is not None:
            after(None)

    vc.play = capture_play
    svc._vc = vc

    with patch("bot.discord.voice.service.audioop") as mock_ao, \
         patch("bot.discord.voice.service.discord") as mock_discord:
        mock_ao.tostereo = MagicMock(return_value=b"\x00\x00" * 200)
        mock_discord.PCMAudio = MagicMock()
        await svc.speak("test")

    # Pendant play(), is_speaking devait être True
    assert speaking_states == [True]
    # Après, False
    assert svc.is_speaking is False


def test_members_in_channel_excludes_bots():
    """members_in_channel() ne doit retourner que des non-bots."""
    svc = _make_service()
    human = MagicMock(); human.id = 111; human.bot = False
    bot_member = MagicMock(); bot_member.id = 999; bot_member.bot = True
    channel = MagicMock()
    channel.members = [human, bot_member]
    svc._channel = channel

    result = svc.members_in_channel()
    assert result == [111]


def test_members_in_channel_no_channel():
    """members_in_channel() retourne [] si pas de salon connecté."""
    svc = _make_service()
    assert svc.members_in_channel() == []


def test_initial_state():
    """Vérifie l'état initial de VoiceService."""
    svc = _make_service()
    assert svc.is_connected is False
    assert svc.channel_id is None
    assert svc.is_speaking is False
    assert svc.history == []
    assert svc.voice_tools == []
    assert svc.tool_executor is None
