# tests/test_twitch_events.py
"""Tests for Twitch EventSub event handlers."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.twitch.events import (
    _bits_joy,
    register_events,
    _subscribe_with_retry,
)


# ── _subscribe_with_retry : backoff sur 429 (bug boot : subscription_end/cheer
#    abandonnées définitivement au 1er 429) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_success_first_try():
    """Souscription OK au 1er essai → factory appelée une fois, pas de sleep."""
    factory = MagicMock(return_value=_awaitable_ok())
    sleeps = []
    ok = await _subscribe_with_retry("follow", factory, sleep=_record(sleeps))
    assert ok is True
    assert factory.call_count == 1
    assert sleeps == []  # aucun backoff


@pytest.mark.asyncio
async def test_subscribe_retries_on_429_then_succeeds():
    """429 puis succès : la factory est RECRÉÉE à chaque essai (coroutine non
    réutilisable) et un backoff est appliqué avant le retry."""
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            return _awaitable_raise(Exception("Subscription failed. Status: 429"))
        return _awaitable_ok()

    sleeps = []
    ok = await _subscribe_with_retry("cheer", factory, sleep=_record(sleeps))
    assert ok is True
    assert calls["n"] == 2
    assert len(sleeps) == 1 and sleeps[0] > 0  # un backoff appliqué


@pytest.mark.asyncio
async def test_subscribe_gives_up_after_persistent_429():
    """429 permanent : épuise les tentatives, ne lève jamais, retourne False."""
    factory = MagicMock(side_effect=lambda: _awaitable_raise(Exception("Status: 429")))
    sleeps = []
    ok = await _subscribe_with_retry("cheer", factory, max_attempts=3, sleep=_record(sleeps))
    assert ok is False
    assert factory.call_count == 3        # 3 tentatives
    assert len(sleeps) == 2               # backoff entre chaque, pas après la dernière


@pytest.mark.asyncio
async def test_subscribe_no_retry_on_non_429():
    """Erreur non-429 (ex 4003, scope manquant) : échec définitif immédiat, pas
    de retry — inutile de marteler une erreur non transitoire."""
    factory = MagicMock(side_effect=lambda: _awaitable_raise(Exception("403 Forbidden")))
    sleeps = []
    ok = await _subscribe_with_retry("sub", factory, sleep=_record(sleeps))
    assert ok is False
    assert factory.call_count == 1
    assert sleeps == []


def _awaitable_ok():
    async def _c():
        return None
    return _c()


def _awaitable_raise(exc):
    async def _c():
        raise exc
    return _c()


def _record(store):
    async def _sleep(d):
        store.append(d)
    return _sleep


def make_bot(event_cfg=None):
    bot = MagicMock()
    bot.emotion.apply_delta = MagicMock()
    bot.emotion.get_state = MagicMock(return_value={})
    bot.prompts.build_system_prompt = MagicMock(return_value="sys")
    bot.llm.complete = AsyncMock(return_value="réponse")
    bot.twitch_api.send_message = AsyncMock()

    default_cfg = {
        "follow": MagicMock(active=True, message="follow {username}"),
        "sub": MagicMock(active=True, message="sub {username}"),
        "resub": MagicMock(active=True, message="resub {username} {months}"),
        "gift_sub": MagicMock(active=True, message="gift {username} x{amount}"),
        "bits": MagicMock(active=True, message="bits {username} {amount}"),
        "raid": MagicMock(active=True, message="raid {username} {raiders_count}"),
    }
    if event_cfg:
        default_cfg.update(event_cfg)
    bot.config.twitch_events.get = lambda k, d=None: default_cfg.get(k, d)
    return bot


def make_gift_payload(gifter="alice", total=5, cumulative=20, is_anonymous=False,
                      broadcaster="mychan"):
    payload = MagicMock()
    payload.data.is_anonymous = is_anonymous
    payload.data.user.name = gifter
    payload.data.total = total
    payload.data.cumulative_total = cumulative
    payload.data.broadcaster.name = broadcaster
    return payload


def make_sub_end_payload(username="bob", broadcaster="mychan"):
    payload = MagicMock()
    payload.data.user.name = username
    payload.data.broadcaster.name = broadcaster
    return payload


def make_chat_payload(content="wally salut", author_name="streamer",
                      author_id="111", channel="mychannel"):
    payload = MagicMock()
    payload.message.text = content
    payload.chatter.name = author_name
    payload.chatter.id = author_id
    payload.broadcaster.name = channel
    return payload


# ── gift sub handler ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gift_sub_applies_joy_delta():
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))

    register_events(bot)
    handler = handlers.get("event_eventsub_notification_subscription_gift")
    assert handler is not None

    payload = make_gift_payload(total=5)
    with patch("bot.twitch.events.social._generate_and_send", new_callable=AsyncMock):
        await handler(payload)

    bot.emotion.apply_delta.assert_called_once_with("joy", 0.5)


@pytest.mark.asyncio
async def test_gift_sub_uses_payload_total_not_cumulative():
    """amount in template must use payload.total, not payload.cumulative_total."""
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers["event_eventsub_notification_subscription_gift"]

    payload = make_gift_payload(total=3, cumulative=50)
    captured = {}

    async def fake_send(b, channel, template, **kwargs):
        captured.update(kwargs)

    with patch("bot.twitch.events.social._generate_and_send", side_effect=fake_send):
        await handler(payload)

    assert captured["amount"] == 3   # payload.total
    assert captured["amount"] != 50  # NOT payload.cumulative_total


@pytest.mark.asyncio
async def test_gift_sub_anonymous_uses_anonyme():
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers["event_eventsub_notification_subscription_gift"]

    payload = make_gift_payload(is_anonymous=True, total=1)
    captured = {}

    async def fake_send(b, channel, template, **kwargs):
        captured.update(kwargs)

    with patch("bot.twitch.events.social._generate_and_send", side_effect=fake_send):
        await handler(payload)

    assert captured["username"] == "Anonyme"


@pytest.mark.asyncio
async def test_gift_sub_inactive_skips():
    bot = make_bot(event_cfg={"gift_sub": MagicMock(active=False)})
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers["event_eventsub_notification_subscription_gift"]

    with patch("bot.twitch.events.social._generate_and_send", new_callable=AsyncMock) as mock_send:
        await handler(make_gift_payload())
    mock_send.assert_not_awaited()


# ── subscription end handler ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_end_no_message_sent():
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers.get("event_eventsub_notification_subscription_end")
    assert handler is not None

    payload = make_sub_end_payload()
    with patch("bot.twitch.events.social._generate_and_send", new_callable=AsyncMock) as mock_send:
        await handler(payload)
    mock_send.assert_not_awaited()
    bot.twitch_api.send_message.assert_not_awaited()


# ── channel.chat.message handler ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_message_handler_calls_handle_message():
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers.get("event_eventsub_notification_channel_chat_message")
    assert handler is not None

    payload = make_chat_payload(content="wally salut")
    with patch("bot.twitch.events.social.handle_message", new_callable=AsyncMock) as mock_handle:
        await handler(payload)
    mock_handle.assert_awaited_once_with(bot, payload.data)


# ── _generate_and_send uses TwitchAPI ────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_and_send_uses_twitch_api():
    """_generate_and_send must call bot.twitch_api.send_message, not IRC channel.send."""
    from bot.twitch.events import _generate_and_send

    bot = make_bot()
    bot.llm.complete = AsyncMock(return_value="Bonjour alice, merci pour ton sub!")

    await _generate_and_send(bot, "mychan", "Bonjour {username}!", username="alice",
                              amount=0, months=0, raiders_count=0)

    bot.twitch_api.send_message.assert_awaited_once()
    sent = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "alice" in sent


# ── SubscriptionTypes patch + _subscribe_chat ─────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_chat_patches_subscription_types():
    """start_eventsub_client() must patch SubscriptionTypes before any subscription."""
    from twitchio.ext.eventsub.models import SubscriptionTypes

    # Remove any prior patch to test from clean state
    SubscriptionTypes._name_map.pop("channel.chat.message", None)
    SubscriptionTypes._type_map.pop("channel.chat.message", None)

    bot = make_bot()
    with patch("bot.twitch.events.os.getenv", side_effect=lambda k, d="": {
        "TWITCH_BROADCASTER_ID": "bc123",
        "TWITCH_BOT_ID": "bot456",
    }.get(k, d)):
        bot.token_manager = MagicMock()
        bot.token_manager.bot_token = "bt"
        bot.token_manager.streamer_token = ""
        with patch("twitchio.ext.eventsub.EventSubWSClient") as MockWSClient:
            mock_client = MockWSClient.return_value
            mock_client.subscribe_channel_follows_v2 = AsyncMock()
            mock_client.subscribe_channel_raid = AsyncMock()
            mock_client._assign_subscription = AsyncMock()
            mock_client.subscribe_channel_subscriptions = AsyncMock()
            mock_client.subscribe_channel_subscription_messages = AsyncMock()
            mock_client.subscribe_channel_subscription_gifts = AsyncMock()
            mock_client.subscribe_channel_subscription_end = AsyncMock()
            mock_client.subscribe_channel_cheers = AsyncMock()
            from bot.twitch.events import start_eventsub_client
            await start_eventsub_client(bot)

    assert "channel.chat.message" in SubscriptionTypes._name_map
    assert SubscriptionTypes._name_map["channel.chat.message"] == "channel_chat_message"
    from bot.twitch.events import ChatMessageData
    assert SubscriptionTypes._type_map["channel.chat.message"] is ChatMessageData


@pytest.mark.asyncio
async def test_subscribe_chat_calls_assign_subscription():
    """_subscribe_chat must call client._assign_subscription with correct condition."""
    from bot.twitch.events import _subscribe_chat, ChatMessageData

    mock_client = MagicMock()
    mock_client._assign_subscription = AsyncMock()

    await _subscribe_chat(mock_client, "bc123", "bot456", "bot_token")

    mock_client._assign_subscription.assert_awaited_once()
    sub = mock_client._assign_subscription.call_args.args[0]
    assert sub.condition == {"broadcaster_user_id": "bc123", "user_id": "bot456"}
    assert sub.token == "bot_token"
    assert sub.event[2] is ChatMessageData
