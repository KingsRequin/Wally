# tests/test_twitch_commands_code.py
import json
import pytest
from datetime import date
from unittest.mock import MagicMock, AsyncMock, patch


def make_bot(note_value=None):
    bot = MagicMock()
    bot.db.get_persistent_note = AsyncMock(return_value=note_value)
    bot.db.upsert_persistent_note = AsyncMock()
    bot._channel_ids = {}
    bot.twitch_api.send_message = AsyncMock()
    irc_channel = MagicMock()
    irc_channel.send = AsyncMock()
    bot.get_channel.return_value = irc_channel
    return bot


def make_mod_badge():
    b = MagicMock()
    b.id = "moderator"
    return b


def make_broadcaster_badge():
    b = MagicMock()
    b.id = "broadcaster"
    return b


def make_viewer_badge():
    b = MagicMock()
    b.id = "subscriber"
    return b


@pytest.fixture(autouse=True)
def clear_state():
    """Vide _daily_codes entre les tests pour éviter les fuites d'état."""
    from bot.twitch.commands import code as code_mod
    code_mod._daily_codes.clear()
    yield
    code_mod._daily_codes.clear()


@pytest.mark.asyncio
async def test_code_no_code_set_shows_no_code_message():
    """!code sans code défini → message 'Pas de code'."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "Pas de code" in text


@pytest.mark.asyncio
async def test_code_displays_code_with_reminder():
    """!code avec code défini → affiche le code + le RAPPEL."""
    from bot.twitch.commands.code import handle_code_command
    today = str(date.today())
    saved = json.dumps({"code": "ABC123", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "ABC123" in text
    assert "ON DIT BONJOUR" in text
    assert "RAPPEL" in text


@pytest.mark.asyncio
async def test_code_set_by_moderator_saves_and_displays():
    """!code ABC par un modérateur → sauvegarde en DB + affiche le code."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    badges = [make_mod_badge()]
    await handle_code_command(bot, "streamer", "mod1", "NEWCODE", badges)
    # DB sauvegardée
    bot.db.upsert_persistent_note.assert_awaited_once()
    saved_json = bot.db.upsert_persistent_note.call_args.args[1]
    assert "NEWCODE" in saved_json
    # Message affiché
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "NEWCODE" in text
    assert "ON DIT BONJOUR" in text


@pytest.mark.asyncio
async def test_code_set_by_broadcaster_saves():
    """!code par broadcaster → accepté."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "owner", "MYCODE", [make_broadcaster_badge()])
    bot.db.upsert_persistent_note.assert_awaited_once()


@pytest.mark.asyncio
async def test_code_set_rejected_for_viewer():
    """!code par un viewer → refusé, DB non touchée."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "viewer", "HACK", [make_viewer_badge()])
    bot.db.upsert_persistent_note.assert_not_awaited()
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "modérateurs" in text.lower() or "Seuls" in text


@pytest.mark.asyncio
async def test_code_resets_if_date_changed():
    """Si le code sauvegardé vient d'hier, il est reset à None."""
    from bot.twitch.commands.code import handle_code_command
    yesterday_note = json.dumps({"code": "OLDCODE", "date": "2000-01-01"})
    bot = make_bot(note_value=yesterday_note)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "Pas de code" in text
    # DB mise à jour avec date d'aujourd'hui et code None
    bot.db.upsert_persistent_note.assert_awaited_once()
    saved = json.loads(bot.db.upsert_persistent_note.call_args.args[1])
    assert saved["code"] is None
    assert saved["date"] == str(date.today())


@pytest.mark.asyncio
async def test_code_loaded_from_db_on_first_access():
    """Au premier accès, le code est chargé depuis la DB."""
    from bot.twitch.commands.code import handle_code_command
    today = str(date.today())
    saved = json.dumps({"code": "DBCODE", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "newchannel", "viewer1", "", [])
    bot.db.get_persistent_note.assert_awaited_once_with("twitch_code:newchannel")
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "DBCODE" in text


@pytest.mark.asyncio
async def test_code_not_reloaded_from_db_on_second_call():
    """Au deuxième appel, la DB n'est plus consultée (cache mémoire)."""
    from bot.twitch.commands.code import handle_code_command
    today = str(date.today())
    saved = json.dumps({"code": "CACHED", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    assert bot.db.get_persistent_note.await_count == 1  # chargé une seule fois
