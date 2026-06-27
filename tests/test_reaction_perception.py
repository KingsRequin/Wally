# tests/test_reaction_perception.py
"""Perception LLM des réactions emoji Discord (injection dans le contexte)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── _format_reactions (pur) ───────────────────────────────────────────────

def test_format_reactions_own_message():
    from bot.discord.handlers import _format_reactions
    out = _format_reactions("😂", "Wally", "ma vanne", on_own_message=True)
    assert out == "a réagi 😂 à ton message « ma vanne »"


def test_format_reactions_other_message():
    from bot.discord.handlers import _format_reactions
    out = _format_reactions("🔥", "Bob (@bob)", "son post", on_own_message=False)
    assert out == "a réagi 🔥 au message de Bob (@bob) « son post »"


def test_format_reactions_truncates_long_content():
    from bot.discord.handlers import _format_reactions
    out = _format_reactions("👀", "Wally", "x" * 300, on_own_message=True)
    assert "…" in out
    assert len(out) < 200


def test_format_reactions_empty_content():
    from bot.discord.handlers import _format_reactions
    out = _format_reactions("😂", "Wally", "", on_own_message=True)
    assert out == "a réagi 😂 à ton message"


# ── _reactions_context (async, avec mocks) ────────────────────────────────

def _user(uid, name, display=None, is_bot=False):
    return SimpleNamespace(id=uid, name=name, display_name=display or name, bot=is_bot)


def _make_bot(message_author):
    bot = MagicMock()
    bot.user = _user(999, "Wally")
    bot.config.discord.ignored_guilds = set()
    bot.memory = MagicMock()
    bot.memory.append_message = MagicMock()
    ch = MagicMock()
    ch.fetch_message = AsyncMock(
        return_value=SimpleNamespace(author=message_author, content="le contenu")
    )
    bot.get_channel = MagicMock(return_value=ch)
    bot.get_user = MagicMock(return_value=None)
    return bot


def _payload(user_id=42, emoji="😂", member=None, guild_id=1, channel_id=7, message_id=100):
    return SimpleNamespace(
        user_id=user_id, emoji=emoji, member=member,
        guild_id=guild_id, channel_id=channel_id, message_id=message_id,
    )


@pytest.mark.asyncio
async def test_reaction_on_wally_message_injected():
    from bot.discord.handlers import _reactions_context
    azrael = _user(42, "azrael", "Azrael")
    bot = _make_bot(message_author=_user(999, "Wally"))  # message de Wally
    await _reactions_context(bot, _payload(member=azrael))

    bot.memory.append_message.assert_called_once()
    args, kwargs = bot.memory.append_message.call_args
    assert args[0] == "7"          # channel_id
    assert args[1] == "Azrael (@azrael)"  # auteur de la réaction (label complet)
    assert "à ton message" in args[2]
    assert kwargs["platform"] == "discord"


@pytest.mark.asyncio
async def test_notable_reaction_on_other_message_injected():
    from bot.discord.handlers import _reactions_context
    azrael = _user(42, "azrael", "Azrael")
    bob = _user(50, "bob", "Bob")
    bot = _make_bot(message_author=bob)
    await _reactions_context(bot, _payload(member=azrael, emoji="🔥"))

    bot.memory.append_message.assert_called_once()
    args, _ = bot.memory.append_message.call_args
    assert "au message de Bob" in args[2]


@pytest.mark.asyncio
async def test_non_notable_reaction_on_other_message_ignored():
    from bot.discord.handlers import _reactions_context
    azrael = _user(42, "azrael", "Azrael")
    bob = _user(50, "bob", "Bob")
    bot = _make_bot(message_author=bob)
    await _reactions_context(bot, _payload(member=azrael, emoji="🥖"))  # non marquant

    bot.memory.append_message.assert_not_called()


@pytest.mark.asyncio
async def test_reaction_by_bot_ignored():
    from bot.discord.handlers import _reactions_context
    botmember = _user(42, "rythm", "Rythm", is_bot=True)
    bot = _make_bot(message_author=_user(999, "Wally"))
    await _reactions_context(bot, _payload(member=botmember))

    bot.memory.append_message.assert_not_called()


@pytest.mark.asyncio
async def test_reaction_by_wally_himself_ignored():
    from bot.discord.handlers import _reactions_context
    bot = _make_bot(message_author=_user(50, "bob", "Bob"))
    await _reactions_context(bot, _payload(user_id=999, member=None, emoji="🔥"))

    bot.memory.append_message.assert_not_called()


@pytest.mark.asyncio
async def test_notable_reaction_on_other_bot_message_ignored():
    from bot.discord.handlers import _reactions_context
    azrael = _user(42, "azrael", "Azrael")
    otherbot = _user(60, "musicbot", "MusicBot", is_bot=True)
    bot = _make_bot(message_author=otherbot)
    await _reactions_context(bot, _payload(member=azrael, emoji="🔥"))

    bot.memory.append_message.assert_not_called()


@pytest.mark.asyncio
async def test_self_reaction_on_own_message_ignored():
    from bot.discord.handlers import _reactions_context
    bob = _user(50, "bob", "Bob")
    bot = _make_bot(message_author=bob)
    # bob réagit à son propre message → pas pertinent
    await _reactions_context(bot, _payload(user_id=50, member=bob, emoji="🔥"))

    bot.memory.append_message.assert_not_called()


# ── DM (message privé) ─────────────────────────────────────────────────────
# En MP : payload.guild_id est None, payload.member est None et le canal DM
# n'est pas toujours en cache → bot.get_channel renvoie None. On doit alors
# le récupérer via fetch_channel, et l'auteur de la réaction via fetch_user.

@pytest.mark.asyncio
async def test_dm_reaction_on_wally_message_injected():
    from bot.discord.handlers import _reactions_context
    azrael = _user(42, "azrael", "Azrael")
    bot = _make_bot(message_author=_user(999, "Wally"))  # message de Wally en MP
    ch = bot.get_channel.return_value
    bot.get_channel = MagicMock(return_value=None)  # canal DM non caché
    bot.fetch_channel = AsyncMock(return_value=ch)
    bot.get_user = MagicMock(return_value=None)
    bot.fetch_user = AsyncMock(return_value=azrael)

    await _reactions_context(bot, _payload(member=None, guild_id=None))

    bot.fetch_channel.assert_awaited_once_with(7)
    bot.memory.append_message.assert_called_once()
    args, kwargs = bot.memory.append_message.call_args
    assert args[1] == "Azrael (@azrael)"
    assert "à ton message" in args[2]
    assert kwargs["platform"] == "discord"


# ── #A2 : perception cognitive des réactions (notify_event) ─────────────────

@pytest.mark.asyncio
async def test_reaction_on_wally_message_feeds_cognitive_loop_relevant():
    """Réaction sur un message de Wally → notify_event(relevant=True) : c'est un
    feedback social qui le concerne directement."""
    from bot.discord.handlers import _reactions_context
    azrael = _user(42, "azrael", "Azrael")
    bot = _make_bot(message_author=_user(999, "Wally"))
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_event = MagicMock()
    await _reactions_context(bot, _payload(member=azrael))

    bot.cognitive_loop.notify_event.assert_called_once()
    _, kwargs = bot.cognitive_loop.notify_event.call_args
    assert kwargs["relevant"] is True
    assert "Azrael (@azrael)" in kwargs["description"]
    assert "à ton message" in kwargs["description"]


@pytest.mark.asyncio
async def test_notable_reaction_on_other_message_feeds_cognitive_loop_passive():
    """Réaction notable sur le message d'un AUTRE → notify_event(relevant=False)."""
    from bot.discord.handlers import _reactions_context
    azrael = _user(42, "azrael", "Azrael")
    bob = _user(50, "bob", "Bob")
    bot = _make_bot(message_author=bob)
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_event = MagicMock()
    await _reactions_context(bot, _payload(member=azrael, emoji="🔥"))

    bot.cognitive_loop.notify_event.assert_called_once()
    _, kwargs = bot.cognitive_loop.notify_event.call_args
    assert kwargs["relevant"] is False


@pytest.mark.asyncio
async def test_ignored_reaction_does_not_feed_cognitive_loop():
    """Une réaction filtrée (bot, non marquante…) ne nourrit pas le cerveau."""
    from bot.discord.handlers import _reactions_context
    azrael = _user(42, "azrael", "Azrael")
    bob = _user(50, "bob", "Bob")
    bot = _make_bot(message_author=bob)
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_event = MagicMock()
    await _reactions_context(bot, _payload(member=azrael, emoji="🥖"))  # non marquant

    bot.cognitive_loop.notify_event.assert_not_called()
