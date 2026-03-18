# bot/twitch/events.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# Imported at module level so tests can patch bot.twitch.events.handle_message
from bot.twitch.handlers import handle_message


def _bits_joy(amount: int) -> float:
    """Map bits amount to joy delta per the design spec."""
    if amount >= 1000:
        return 0.6
    if amount >= 100:
        return 0.3
    return 0.1


async def _generate_and_send(
    bot: "WallyTwitch",
    channel_name: str,
    template: str,
    **kwargs,
) -> None:
    """Generate an OpenAI response from an event template and send via Helix API."""
    try:
        from bot.core.prompts import PromptBuilder

        formatted = PromptBuilder.format_event_message(template, **kwargs)
        situation = {"platform": "Twitch", "streamer": channel_name}
        system = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
        )
        event_user_id = f"twitch:{kwargs.get('username', '')}" if kwargs.get('username') else None
        reply = await bot.openai.complete(
            system,
            [{"role": "user", "content": f"Réagis à cet événement Twitch : {formatted}"}],
            purpose="twitch_event",
            user_id=event_user_id,
        )
        if len(reply) > 480:
            reply = reply[:477] + "..."
        await bot.twitch_api.send_message(text=reply)
    except Exception as e:
        logger.error("Twitch event send error: {e}", e=e)


def register_events(bot: "WallyTwitch") -> None:
    """Register EventSub WebSocket event handlers on the bot instance."""

    @bot.event()
    async def event_eventsub_notification_followV2(payload) -> None:
        cfg = bot.config.twitch_events.get("follow")
        if not cfg or not cfg.active:
            return
        bot.emotion.apply_delta("joy", 0.1)
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=payload.data.user.name, amount=0, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription(payload) -> None:
        cfg = bot.config.twitch_events.get("sub")
        if not cfg or not cfg.active:
            return
        if payload.data.is_gift:
            return  # gift subs handled by subscription_gift handler
        bot.emotion.apply_delta("joy", 0.4)
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=payload.data.user.name, amount=0, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription_message(payload) -> None:
        cfg = bot.config.twitch_events.get("resub")
        if not cfg or not cfg.active:
            return
        bot.emotion.apply_delta("joy", 0.3)
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=payload.data.user.name, amount=0,
            months=payload.data.cumulative_months, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription_gift(payload) -> None:
        cfg = bot.config.twitch_events.get("gift_sub")
        if not cfg or not cfg.active:
            return
        bot.emotion.apply_delta("joy", 0.5)
        gifter = "Anonyme" if payload.data.is_anonymous else payload.data.user.name
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=gifter,
            amount=payload.data.total,   # nb de gifts dans cette transaction
            months=0,
            raiders_count=0,
        )
        # payload.data.cumulative_total disponible pour un futur template "X gifts au total"

    @bot.event()
    async def event_eventsub_notification_subscription_end(payload) -> None:
        logger.debug("Sub end: {user}", user=payload.data.user.name)
        # Pas de réaction visible dans le chat

    @bot.event()
    async def event_eventsub_notification_cheer(payload) -> None:
        cfg = bot.config.twitch_events.get("bits")
        if not cfg or not cfg.active:
            return
        delta = _bits_joy(payload.data.bits)
        bot.emotion.apply_delta("joy", delta)
        username = "Anonyme" if payload.data.is_anonymous else payload.data.user.name
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=username, amount=payload.data.bits, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_raid(payload) -> None:
        cfg = bot.config.twitch_events.get("raid")
        if not cfg or not cfg.active:
            return
        joy_spike = min(payload.data.viewer_count / 50, 0.9)
        bot.emotion.apply_delta("joy", joy_spike)
        # Note: twitchio v2 uses .reciever (typo in library — missing second 'e')
        channel_name = payload.data.reciever.name
        await _generate_and_send(
            bot, channel_name, cfg.message,
            username=payload.data.raider.name, amount=0,
            months=0, raiders_count=payload.data.viewer_count,
        )

    @bot.event()
    async def event_eventsub_notification_channel_chat_message(payload) -> None:
        await handle_message(bot, payload.data)


class ChatMessageData:
    """Minimal data model for channel.chat.message EventSub notifications.

    Registered into twitchio v2's SubscriptionTypes at runtime in
    start_eventsub_client() since twitchio v2 does not natively support
    channel.chat.message.

    Attributes match the EventSub payload field names:
      chatter.id    — chatter_user_id
      chatter.name  — chatter_user_login
      message.text  — message.text
      broadcaster.name — broadcaster_user_login
    """

    __slots__ = "chatter", "message", "broadcaster"

    def __init__(self, client, data: dict):
        # Use twitchio's create_user to get PartialUser objects
        self.chatter = client.client.create_user(
            int(data["chatter_user_id"]), data["chatter_user_login"]
        )
        self.message = _ChatMessageText(data["message"])
        self.broadcaster = client.client.create_user(
            int(data["broadcaster_user_id"]), data["broadcaster_user_login"]
        )


class _ChatMessageText:
    __slots__ = ("text",)

    def __init__(self, data: dict):
        self.text: str = data["text"]


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
            await asyncio.sleep(0.5)  # avoid 429 rate-limit on rapid subscription bursts

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
