# tests/test_reaction_roster.py
"""Relevé nominatif des réactions emoji d'un message Discord.

Wally ne voyait que des compteurs (ReactionTracker) ou l'événement isolé d'une
réaction ; il ne savait pas QUI avait mis quoi sur un message qu'il relit.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _user(uid, name, display=None):
    return SimpleNamespace(id=uid, name=name, display_name=display or name)


class _FakeReaction:
    """Imite ``discord.Reaction`` : ``users()`` renvoie un itérateur asynchrone."""

    def __init__(self, emoji, users, count=None, error=None):
        self.emoji = emoji
        self._users = list(users)
        self.count = len(self._users) if count is None else count
        self._error = error

    def users(self, limit=None):
        error = self._error
        users = self._users[:limit] if limit is not None else self._users

        async def _gen():
            if error is not None:
                raise error
            for u in users:
                yield u

        return _gen()


def _make_bot():
    bot = MagicMock()
    bot.user = _user(999, "wally", "Wally")
    bot.config.bot.name = "Wally"
    return bot


def _msg(reactions):
    return SimpleNamespace(id=1, reactions=reactions, content="hello", author=_user(50, "bob", "Bob"))


# ── _reaction_roster ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_roster_empty_without_reactions():
    from bot.discord.handlers import _reaction_roster
    assert await _reaction_roster(_make_bot(), _msg([])) == ""


@pytest.mark.asyncio
async def test_roster_names_reactors_per_emoji():
    from bot.discord.handlers import _reaction_roster
    alice, bob, carol = _user(1, "alice", "Alice"), _user(2, "bob", "Bob"), _user(3, "carol", "Carol")
    msg = _msg([_FakeReaction("😂", [alice, bob]), _FakeReaction("👍", [carol])])

    out = await _reaction_roster(_make_bot(), msg)

    assert out == "😂 Alice (@alice), Bob (@bob) · 👍 Carol (@carol)"


@pytest.mark.asyncio
async def test_roster_labels_wally_himself_with_his_name():
    from bot.discord.handlers import _reaction_roster
    msg = _msg([_FakeReaction("🔥", [_user(999, "wally", "Wally-bot")])])

    out = await _reaction_roster(_make_bot(), msg)

    assert out == "🔥 Wally"


@pytest.mark.asyncio
async def test_roster_caps_reactors_and_reports_remainder():
    from bot.discord.handlers import MAX_REACTORS_PER_EMOJI, _reaction_roster
    many = [_user(i, f"u{i}") for i in range(MAX_REACTORS_PER_EMOJI + 3)]
    msg = _msg([_FakeReaction("💀", many)])

    out = await _reaction_roster(_make_bot(), msg)

    assert out.count(",") == MAX_REACTORS_PER_EMOJI - 1
    assert out.endswith(" +3")


@pytest.mark.asyncio
async def test_roster_caps_number_of_emojis():
    from bot.discord.handlers import MAX_REACTION_EMOJIS, _reaction_roster
    alice = _user(1, "alice", "Alice")
    reactions = [_FakeReaction(f"e{i}", [alice]) for i in range(MAX_REACTION_EMOJIS + 2)]

    out = await _reaction_roster(_make_bot(), _msg(reactions))

    assert out.count("Alice") == MAX_REACTION_EMOJIS
    assert out.endswith("+2 autre(s) emoji(s)")


@pytest.mark.asyncio
async def test_roster_falls_back_to_count_when_users_unreadable():
    """Identités inaccessibles (permission, API) → on garde au moins le compte."""
    from bot.discord.handlers import _reaction_roster
    msg = _msg([_FakeReaction("👀", [], count=4, error=RuntimeError("403"))])

    assert await _reaction_roster(_make_bot(), msg) == "👀 ×4"


@pytest.mark.asyncio
async def test_roster_never_raises_on_bogus_message():
    from bot.discord.handlers import _reaction_roster
    bogus = SimpleNamespace(reactions=object())  # non itérable
    assert await _reaction_roster(_make_bot(), bogus) == ""


# ── _with_reactions ────────────────────────────────────────────────────────

def test_with_reactions_appends_tag():
    from bot.discord.handlers import _with_reactions
    assert _with_reactions("salut", "😂 Alice") == "salut [réactions : 😂 Alice]"


def test_with_reactions_without_roster_is_identity():
    from bot.discord.handlers import _with_reactions
    assert _with_reactions("salut", "") == "salut"


def test_with_reactions_on_empty_content():
    from bot.discord.handlers import _with_reactions
    assert _with_reactions("", "👍 Bob") == "[réactions : 👍 Bob]"


# ── _fetch_discord_history (cold start) ────────────────────────────────────

class _FakeHistory:
    def __init__(self, messages):
        self._messages = messages

    def __call__(self, limit=None, **kwargs):
        messages = self._messages[:limit] if limit is not None else self._messages

        async def _gen():
            for m in messages:
                yield m

        return _gen()


def _history_msg(mid, author, content, reactions=()):
    return SimpleNamespace(
        id=mid, author=author, content=content, reactions=list(reactions), mentions=[], guild=None,
    )


@pytest.mark.asyncio
async def test_history_annotates_reactions_when_bot_given():
    from bot.discord.handlers import _fetch_discord_history
    alice = _user(1, "alice", "Alice")
    bob = _user(2, "bob", "Bob")
    channel = SimpleNamespace(history=_FakeHistory([
        _history_msg(2, bob, "ma vanne", [_FakeReaction("😂", [alice])]),
        _history_msg(1, alice, "coucou"),
    ]))

    out = await _fetch_discord_history(channel, limit=5, bot=_make_bot())

    assert [m["content"] for m in out] == ["coucou", "ma vanne [réactions : 😂 Alice (@alice)]"]
    assert [m["author"] for m in out] == ["Alice (@alice)", "Bob (@bob)"]


@pytest.mark.asyncio
async def test_history_without_bot_stays_unannotated():
    from bot.discord.handlers import _fetch_discord_history
    alice = _user(1, "alice", "Alice")
    channel = SimpleNamespace(history=_FakeHistory([
        _history_msg(1, alice, "coucou", [_FakeReaction("😂", [alice])]),
    ]))

    out = await _fetch_discord_history(channel, limit=5)

    assert out == [{"author": "Alice (@alice)", "content": "coucou"}]


@pytest.mark.asyncio
async def test_history_excludes_current_message():
    from bot.discord.handlers import _fetch_discord_history
    alice = _user(1, "alice", "Alice")
    channel = SimpleNamespace(history=_FakeHistory([
        _history_msg(9, alice, "le message courant"),
        _history_msg(1, alice, "coucou"),
    ]))

    out = await _fetch_discord_history(channel, limit=5, exclude_id=9, bot=_make_bot())

    assert [m["content"] for m in out] == ["coucou"]


# ── handle_message : message rejoué au rattrapage ──────────────────────────

@pytest.mark.asyncio
async def test_replayed_message_carries_its_reactions_into_context(monkeypatch):
    """Au rattrapage, le message relu porte déjà des réactions : le contexte du
    canal doit dire qui a réagi, la mémoire garder le contenu brut."""
    from bot.discord import handlers
    alice = _user(1, "alice", "Alice")

    bot = _make_bot()
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.spontaneous_discord_enabled = False
    bot.config.discord.channel_filter_mode = "none"
    bot.config.discord.emoji_reaction_probability = 0.0
    bot.config.discord.ignored_guilds = set()
    bot.config.discord.always_trigger_channels = []
    bot.db.is_chat_user_banned = AsyncMock(return_value=False)
    bot.db.is_muted = AsyncMock(return_value=False)
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.fact_extractor = MagicMock()
    bot.fact_extractor.record_message = MagicMock()
    bot.cognitive_loop = MagicMock()
    bot.cognitive_loop.notify_activity = MagicMock()
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )

    msg = MagicMock()
    msg.id = 77
    msg.content = "vieux message"
    msg.author = MagicMock(id=1, name="alice", display_name="Alice", bot=False)
    msg.guild = MagicMock(id=5)
    msg.channel = MagicMock(id=7)
    msg.mentions = []
    msg.attachments = []
    msg.reference = None
    msg.reactions = [_FakeReaction("😂", [alice])]

    monkeypatch.setattr(handlers, "_check_spam", AsyncMock(return_value=True))  # stoppe le pipeline
    await handlers.handle_message(bot, msg)

    prelude_args, _ = bot.memory.append_prelude.call_args
    assert prelude_args[2] == "vieux message [réactions : 😂 Alice (@alice)]"
    # Les faits mémorisés restent sur le contenu brut
    fact_args, _ = bot.fact_extractor.record_message.call_args
    assert fact_args[4] == "vieux message"
