# bot/twitch/events/__init__.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

from bot.twitch.events.models import ChatMessageData
from bot.twitch.events.social import (  # noqa: F401 — re-exports
    register_events,
    _bits_joy,
    _generate_and_send,
)

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


async def start_eventsub_client(bot: "WallyTwitch") -> None:
    """Create an EventSub WebSocket client and subscribe to channel events.

    Patches twitchio v2's SubscriptionTypes at runtime to add
    channel.chat.message support (absent from twitchio v2 natively).

    Token usage:
      Bot token  (BOT_ACCESS_TOKEN):
        channel.follow v2  — moderator:read:followers
        channel.raid       — (no scope)
        channel.chat.message — user:read:chat

      Streamer token (STREAMER_ACCESS_TOKEN):
        channel.subscribe, channel.subscription.message,
        channel.subscription.gift, channel.subscription.end — channel:read:subscriptions
        channel.cheer — bits:read
    """
    broadcaster_id = os.getenv("TWITCH_BROADCASTER_ID", "").strip()
    bot_id = os.getenv("TWITCH_BOT_ID", "").strip() or broadcaster_id
    bot_token = bot.token_manager.bot_token
    streamer_token = bot.token_manager.streamer_token

    if not broadcaster_id or not bot_token:
        logger.warning(
            "EventSub skipped — TWITCH_BROADCASTER_ID and BOT_ACCESS_TOKEN required"
        )
        return

    try:
        from twitchio.ext import eventsub
        from twitchio.ext.eventsub.models import SubscriptionTypes
        from twitchio.ext.eventsub.websocket import _Subscription

        # Patch twitchio v2 to support channel.chat.message
        # (absent from SubscriptionTypes — would cause KeyError in pump() if not patched)
        if "channel.chat.message" not in SubscriptionTypes._name_map:
            SubscriptionTypes._name_map["channel.chat.message"] = "channel_chat_message"
            SubscriptionTypes._type_map["channel.chat.message"] = ChatMessageData

        client = eventsub.EventSubWSClient(bot)

        # Subscriptions are awaited sequentially — see existing code comment re: 4003 errors.
        subscriptions: list[tuple[str, object]] = [
            ("follow", client.subscribe_channel_follows_v2(
                broadcaster=broadcaster_id, moderator=bot_id, token=bot_token
            )),
            ("raid", client.subscribe_channel_raid(
                token=bot_token, to_broadcaster=broadcaster_id
            )),
            ("chat", _subscribe_chat(client, broadcaster_id, bot_id, bot_token)),
        ]

        if streamer_token:
            subscriptions += [
                ("sub", client.subscribe_channel_subscriptions(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("resub", client.subscribe_channel_subscription_messages(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("gift_sub", client.subscribe_channel_subscription_gifts(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("subscription_end", client.subscribe_channel_subscription_end(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("cheer", client.subscribe_channel_cheers(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
            ]
        else:
            logger.warning(
                "EventSub: streamer subscriptions skipped — set STREAMER_ACCESS_TOKEN "
                "(channel:read:subscriptions, bits:read)"
            )

        for name, coro in subscriptions:
            try:
                await coro
                logger.info("EventSub subscribed: {sub}", sub=name)
            except Exception as exc:
                logger.warning(
                    "EventSub subscription failed [{sub}]: {e}", sub=name, e=exc
                )
            await asyncio.sleep(1.5)  # avoid 429 rate-limit on rapid subscription bursts

        # Chaînes invitées : chat seulement
        for guest_name in bot.config.twitch.guest_channels:
            guest_id = await bot.twitch_api.get_broadcaster_id(guest_name)
            if guest_id:
                bot._channel_ids[guest_name] = guest_id
                try:
                    await _subscribe_chat(client, guest_id, bot_id, bot_token)
                    logger.info("EventSub subscribed: chat guest {name}", name=guest_name)
                except Exception as exc:
                    logger.warning(
                        "EventSub guest chat failed [{name}]: {e}", name=guest_name, e=exc
                    )
            else:
                logger.warning(
                    "Chaîne invitée introuvable ou API indisponible: {name}", name=guest_name
                )
            await asyncio.sleep(0.5)

        bot._eventsub_client = client
        logger.info(
            "EventSub WebSocket client active (broadcaster_id={bid})", bid=broadcaster_id
        )

    except Exception as exc:
        logger.error("EventSub client setup failed: {e}", e=exc)


async def _subscribe_chat(client, broadcaster_id: str, bot_id: str, token: str):
    """Subscribe to channel.chat.message via manual _Subscription (not in twitchio v2 API).

    Uses EventSubWSClient._assign_subscription() — the same internal path used by all
    native subscribe_* methods (e.g. subscribe_channel_follows_v2). add_subscription()
    and _wakeup_and_connect() are methods on the inner Websocket class, not on
    EventSubWSClient — using them directly would raise AttributeError.
    """
    from twitchio.ext.eventsub.websocket import _Subscription

    sub = _Subscription(
        ("channel.chat.message", 1, ChatMessageData),
        {"broadcaster_user_id": broadcaster_id, "user_id": bot_id},
        token,
    )
    await client._assign_subscription(sub)
