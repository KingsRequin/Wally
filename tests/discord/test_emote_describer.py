# tests/discord/test_emote_describer.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from bot.discord.emote_describer import (
    EmoteDescriber,
    EmoteInfo,
    AUTO_SOURCE,
    run_emote_description,
    _target_guilds,
    _guild_allowed,
)
from bot.intelligence.memory.facts import AtomicFact, FactCategory


def _note(content: str) -> AtomicFact:
    now = datetime.now(timezone.utc).isoformat()
    return AtomicFact(
        user_id="wally:emotes",
        content=content,
        category=FactCategory.PREF,
        confidence=1.0,
        created_at=now,
        last_seen_at=now,
    )


def _store(existing_notes=None):
    store = MagicMock()
    store.get_by_user = AsyncMock(return_value=list(existing_notes or []))
    store.add = AsyncMock(return_value=1)
    return store


def _vision(result="exprime un GG/bravo", available=True):
    v = MagicMock()
    v.available = available
    v.analyze = AsyncMock(return_value=result)
    return v


@pytest.mark.asyncio
async def test_describes_unknown_emote_and_stores_pref_fact():
    store = _store()
    vision = _vision("exprime un GG, un bravo de la commu")
    describer = EmoteDescriber(store, vision)

    n = await describer.describe_new([
        EmoteInfo(name="chatGG", code="<:chatGG:111>", url="http://x/gg.png"),
    ])

    assert n == 1
    store.add.assert_awaited_once()
    fact = store.add.call_args.args[0]
    assert fact.user_id == "wally:emotes"
    assert fact.category == FactCategory.PREF
    assert fact.source == AUTO_SOURCE
    # Format identique aux notes manuelles : "nom → usage" (clé = nom nu).
    assert fact.content == "chatGG → exprime un GG, un bravo de la commu"
    # L'image ET le nom sont fournis à la vision.
    call = vision.analyze.call_args
    assert call.args[0] == ["http://x/gg.png"]
    assert "chatGG" in call.kwargs["caption"]


@pytest.mark.asyncio
async def test_skips_emote_that_already_has_note():
    # Note manuelle existante pour "chatGG" → on ne la réécrit pas.
    store = _store([_note("chatGG → le GG de la commu")])
    vision = _vision()
    describer = EmoteDescriber(store, vision)

    n = await describer.describe_new([
        EmoteInfo(name="chatGG", code="<:chatGG:111>", url="http://x/gg.png"),
        EmoteInfo(name="chatbonjour", code="<:chatbonjour:222>", url="http://x/b.png"),
    ])

    # Seule l'emote inconnue est décrite ; la vision n'est appelée qu'une fois.
    assert n == 1
    assert vision.analyze.await_count == 1
    fact = store.add.call_args.args[0]
    assert fact.content.startswith("chatbonjour →")


@pytest.mark.asyncio
async def test_skip_matching_is_case_insensitive():
    store = _store([_note("ChatGG → le GG")])
    describer = EmoteDescriber(store, _vision())
    n = await describer.describe_new([
        EmoteInfo(name="chatgg", code="<:chatgg:111>", url="http://x/gg.png"),
    ])
    assert n == 0
    store.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_vision_returns_none_stores_nothing():
    store = _store()
    describer = EmoteDescriber(store, _vision(result=None))
    n = await describer.describe_new([
        EmoteInfo(name="chatGG", code="<:chatGG:111>", url="http://x/gg.png"),
    ])
    assert n == 0
    store.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_vision_unavailable_is_noop():
    store = _store()
    describer = EmoteDescriber(store, _vision(available=False))
    n = await describer.describe_new([
        EmoteInfo(name="chatGG", code="<:chatGG:111>", url="http://x/gg.png"),
    ])
    assert n == 0
    store.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_vision_exception_is_swallowed():
    store = _store()
    vision = _vision()
    vision.analyze = AsyncMock(side_effect=RuntimeError("boom"))
    describer = EmoteDescriber(store, vision)
    n = await describer.describe_new([
        EmoteInfo(name="chatGG", code="<:chatGG:111>", url="http://x/gg.png"),
    ])
    assert n == 0
    store.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_usage_is_truncated_and_cleaned():
    store = _store()
    long = "a" * 500
    describer = EmoteDescriber(store, _vision(result=f'  "{long}"\nsuite  '))
    await describer.describe_new([
        EmoteInfo(name="e", code="<:e:1>", url="http://x/e.png"),
    ])
    fact = store.add.call_args.args[0]
    usage = fact.content.split("→", 1)[1].strip()
    assert len(usage) <= 160
    assert "\n" not in usage


@pytest.mark.asyncio
async def test_within_run_dedup_does_not_describe_twice():
    store = _store()
    vision = _vision()
    describer = EmoteDescriber(store, vision)
    # Même nom deux fois (emote présente sur 2 serveurs) → une seule description.
    n = await describer.describe_new([
        EmoteInfo(name="dup", code="<:dup:1>", url="http://x/1.png"),
        EmoteInfo(name="dup", code="<:dup:2>", url="http://x/2.png"),
    ])
    assert n == 1
    assert vision.analyze.await_count == 1


@pytest.mark.asyncio
async def test_feed_event_published():
    store = _store()
    feed = MagicMock()
    describer = EmoteDescriber(store, _vision(), feed=feed)
    await describer.describe_new([
        EmoteInfo(name="chatGG", code="<:chatGG:1>", url="http://x/gg.png"),
    ])
    feed.publish.assert_called_once()
    assert "chatGG" in feed.publish.call_args.args[0]["detail"]


# ── ciblage des serveurs (tous par défaut, un seul si emote_guild_id) ────────

def _emoji(name, url):
    e = MagicMock()
    e.name = name
    e.url = url
    return e


def _guild(gid, name="g", emojis=()):
    g = MagicMock()
    g.id = gid
    g.name = name
    g.emojis = list(emojis)
    return g


def _bot(guilds, emote_guild_id=None):
    bot = MagicMock()
    bot.guilds = guilds
    bot.config.discord.emote_guild_id = emote_guild_id
    return bot


def test_target_guilds_defaults_to_all():
    g1, g2 = _guild(111), _guild(222)
    assert _target_guilds(_bot([g1, g2])) == [g1, g2]


def test_target_guilds_restricted_when_configured():
    g1, g2 = _guild(111), _guild(222)
    assert _target_guilds(_bot([g1, g2], emote_guild_id=222)) == [g2]


def test_target_guilds_empty_when_configured_absent():
    g1 = _guild(111)
    assert _target_guilds(_bot([g1], emote_guild_id=999)) == []


def test_guild_allowed_all_by_default():
    g1, g2 = _guild(111), _guild(222)
    bot = _bot([g1, g2])
    assert _guild_allowed(bot, g1) and _guild_allowed(bot, g2)


def test_guild_allowed_restricted_when_configured():
    g1, g2 = _guild(111), _guild(222)
    bot = _bot([g1, g2], emote_guild_id=111)
    assert _guild_allowed(bot, g1)
    assert not _guild_allowed(bot, g2)


@pytest.mark.asyncio
async def test_run_describes_emotes_from_all_guilds():
    """Sans emote_guild_id, run_emote_description couvre TOUS les serveurs."""
    g1 = _guild(111, emojis=[_emoji("aaa", "http://x/a.png")])
    g2 = _guild(222, emojis=[_emoji("bbb", "http://x/b.png")])
    bot = _bot([g1, g2])
    bot.vision = _vision()
    bot.fact_store = _store()
    bot.cognitive_feed = None
    n = await run_emote_description(bot)
    assert n == 2
    assert bot.fact_store.add.await_count == 2
