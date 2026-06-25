# tests/test_twitch_commands_mood.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def make_bot(channel_ids=None, bot_name="Wally"):
    bot = MagicMock()
    bot.emotion.get_state.return_value = {
        "anger": 0.2, "joy": 0.5, "sadness": 0.1, "curiosity": 0.3, "boredom": 0.0,
    }
    bot._channel_ids = channel_ids or {}
    bot.twitch_api.send_message = AsyncMock()
    bot.config.bot.name = bot_name
    # IRC channel mock
    irc_channel = MagicMock()
    irc_channel.send = AsyncMock()
    bot.get_channel.return_value = irc_channel
    return bot


@pytest.mark.asyncio
async def test_mood_sends_via_helix_on_home_channel():
    """Sur la chaîne home (pas dans _channel_ids), envoi via Helix API."""
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot(channel_ids={})
    await handle_mood_command(bot, "streamer")
    bot.twitch_api.send_message.assert_awaited_once()
    sent_text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "Wally" in sent_text
    assert "Joie" in sent_text
    assert "50%" in sent_text


@pytest.mark.asyncio
async def test_mood_uses_bot_name_from_config():
    """Le préfixe 'Humeur de X' utilise bot.config.bot.name, pas 'Wally' hardcodé."""
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot(channel_ids={}, bot_name="Cindy")
    await handle_mood_command(bot, "streamer")
    sent_text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert sent_text.startswith("Humeur de Cindy —"), f"Attendu 'Humeur de Cindy —', obtenu: {sent_text}"
    assert "Wally" not in sent_text, f"'Wally' hardcodé trouvé dans: {sent_text}"


@pytest.mark.asyncio
async def test_mood_sends_via_irc_on_guest_channel():
    """Sur une chaîne invitée (dans _channel_ids), envoi via IRC."""
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot(channel_ids={"guestchan": "456"})
    await handle_mood_command(bot, "guestchan")
    bot.get_channel.assert_called_once_with("guestchan")
    bot.get_channel.return_value.send.assert_awaited_once()
    bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_mood_message_contains_all_five_emotions():
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot()
    await handle_mood_command(bot, "streamer")
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    for label in ("Colère", "Joie", "Tristesse", "Curiosité", "Ennui"):
        assert label in text, f"Label '{label}' manquant dans: {text}"


@pytest.mark.asyncio
async def test_mood_irc_channel_none_does_not_crash():
    """Si get_channel retourne None (IRC non connecté), pas de crash."""
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot(channel_ids={"guestchan": "456"})
    bot.get_channel.return_value = None
    await handle_mood_command(bot, "guestchan")
    # Pas d'exception = succès
