# bot/twitch/events/social.py
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# Imported at module level so tests can patch bot.twitch.events.social.handle_message
from bot.twitch.handlers import handle_message, _fire


def _check_peak(bot, emotion: str, old_val: float, delta: float, username: str = "", event_name: str = ""):
    """Fire-and-forget peak check for Twitch events."""
    import inspect
    new_val = min(1.0, old_val + delta)
    if hasattr(bot.emotion, '_maybe_log_peak'):
        coro = bot.emotion._maybe_log_peak(
            emotion, old_val, new_val,
            trigger_user=username,
            trigger_message=f"[Twitch {event_name}]",
            channel_id="", platform="twitch",
        )
        if inspect.iscoroutine(coro):
            _fire(coro)


# Track recent follow timestamps to detect follow bursts → curiosity
_recent_follows: list[float] = []
_FOLLOW_BURST_WINDOW = 60.0  # seconds
_FOLLOW_BURST_THRESHOLD = 5  # follows in window to trigger curiosity


def _check_follow_burst() -> bool:
    """Return True if there's a burst of follows (≥5 in 60s)."""
    import time as _time
    now = _time.time()
    cutoff = now - _FOLLOW_BURST_WINDOW
    _recent_follows[:] = [t for t in _recent_follows if t >= cutoff]
    _recent_follows.append(now)
    return len(_recent_follows) >= _FOLLOW_BURST_THRESHOLD


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
        from bot.intelligence.prompts import PromptBuilder

        formatted = PromptBuilder.format_event_message(template, **kwargs)
        from bot.twitch.handlers import _build_situation
        situation = _build_situation(bot, channel_name)
        system = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
        event_user_id = f"twitch:{kwargs.get('username', '')}" if kwargs.get('username') else None
        reply = await bot.llm.complete(
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
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", 0.1)
        _check_peak(bot, "joy", old_joy, 0.1, username=payload.data.user.name, event_name="follow")
        # Follow burst → curiosity ("il se passe quoi ?")
        if _check_follow_burst():
            old_curiosity = bot.emotion.get_state().get("curiosity", 0.0)
            bot.emotion.apply_delta("curiosity", 0.2)
            _check_peak(bot, "curiosity", old_curiosity, 0.2, username=payload.data.user.name, event_name="follow_burst")
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
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", 0.4)
        _check_peak(bot, "joy", old_joy, 0.4, username=payload.data.user.name, event_name="subscribe")
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=payload.data.user.name, amount=0, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription_message(payload) -> None:
        cfg = bot.config.twitch_events.get("resub")
        if not cfg or not cfg.active:
            return
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", 0.3)
        _check_peak(bot, "joy", old_joy, 0.3, username=payload.data.user.name, event_name="resub")
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
        gifter = "Anonyme" if payload.data.is_anonymous else payload.data.user.name
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", 0.5)
        _check_peak(bot, "joy", old_joy, 0.5, username=gifter, event_name="gift_sub")
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
        username = "Anonyme" if payload.data.is_anonymous else payload.data.user.name
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", delta)
        _check_peak(bot, "joy", old_joy, delta, username=username, event_name="bits")
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=username, amount=payload.data.bits, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_raid(payload) -> None:
        cfg = bot.config.twitch_events.get("raid")
        if not cfg or not cfg.active:
            return
        viewers = payload.data.viewer_count
        joy_spike = min(viewers / 50, 0.9)
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", joy_spike)
        _check_peak(bot, "joy", old_joy, joy_spike, username=payload.data.raider.name, event_name="raid")
        # Massive raid (≥50 viewers) → curiosity spike
        if viewers >= 50:
            curiosity_spike = min(viewers / 100, 0.5)
            old_curiosity = bot.emotion.get_state().get("curiosity", 0.0)
            bot.emotion.apply_delta("curiosity", curiosity_spike)
            _check_peak(bot, "curiosity", old_curiosity, curiosity_spike, username=payload.data.raider.name, event_name="raid_massive")
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
