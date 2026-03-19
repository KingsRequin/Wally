# bot/core/reaction_tracker.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.core.emotion import EmotionEngine

TWITCH_WINDOW_SECONDS = 120
CLEANUP_AGE_SECONDS = 600

JOY_TIERS = [(2, 0.05), (5, 0.10), (float("inf"), 0.15)]

POSITIVE_KEYWORDS = {
    "mdr", "lol", "ptdr", "xd", "haha", "😂", "🤣",
    "pog", "gg", "bien joué", "trop bon",
}

POSITIVE_EMOJIS = {
    "😂", "🤣", "❤️", "❤", "👍", "💀", "😭", "🔥", "👏",
}


@dataclass
class _DiscordReactionState:
    count: int = 0
    last_applied_tier: int = 0
    timestamp: float = field(default_factory=time.time)
    reply_text: str = ""
    channel_id: str = ""


@dataclass
class _TwitchWindow:
    timestamp: float = field(default_factory=time.time)
    count: int = 0
    last_applied_tier: int = 0
    reply_text: str = ""


class ReactionTracker:
    def __init__(self, emotion: "EmotionEngine", db=None):
        self._emotion = emotion
        self._db = db
        self._discord_messages: dict[int, _DiscordReactionState] = {}
        self._twitch_windows: dict[str, _TwitchWindow] = {}

    def _apply_tier_delta(self, count: int, last_tier: int) -> tuple[int, float]:
        current_tier = 0
        current_delta = 0.0
        for i, (max_count, cumulative) in enumerate(JOY_TIERS, 1):
            if count <= max_count:
                current_tier = i
                current_delta = cumulative
                break
        if current_tier <= last_tier:
            return last_tier, 0.0
        prev_delta = JOY_TIERS[last_tier - 1][1] if last_tier > 0 else 0.0
        return current_tier, current_delta - prev_delta

    def _maybe_apply(self, count: int, last_tier: int, reply_text: str = "", channel_id: str = "", platform: str = "") -> int:
        new_tier, delta = self._apply_tier_delta(count, last_tier)
        if delta > 0:
            self._emotion.apply_delta("joy", delta)
            logger.debug(
                "Reaction joy boost: count={c} tier={t} delta={d}",
                c=count, t=new_tier, d=delta,
            )
        # Store joke when reaching tier 2 for the first time
        if last_tier < 2 and new_tier >= 2 and reply_text and self._db is not None:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._db.insert_joke(reply_text, channel_id, platform, count))
            except RuntimeError:
                pass  # No running loop (test context)
        return new_tier

    def _cleanup(self) -> None:
        now = time.time()
        cutoff = now - CLEANUP_AGE_SECONDS
        stale = [mid for mid, s in self._discord_messages.items() if s.timestamp < cutoff]
        for mid in stale:
            del self._discord_messages[mid]
        stale_tw = [ch for ch, w in self._twitch_windows.items() if w.timestamp < cutoff]
        for ch in stale_tw:
            del self._twitch_windows[ch]

    def track_discord_message(self, message_id: int, reply_text: str = "", channel_id: str = "") -> None:
        self._cleanup()
        self._discord_messages[message_id] = _DiscordReactionState(reply_text=reply_text, channel_id=channel_id)

    def record_discord_reaction(self, message_id: int, emoji: str, is_bot: bool) -> None:
        if is_bot:
            return
        state = self._discord_messages.get(message_id)
        if state is None:
            return
        if emoji not in POSITIVE_EMOJIS:
            return
        state.count += 1
        state.last_applied_tier = self._maybe_apply(
            state.count, state.last_applied_tier,
            reply_text=state.reply_text, channel_id=state.channel_id, platform="discord",
        )

    def record_discord_reply(self, message_id: int, text: str, is_bot: bool) -> None:
        if is_bot:
            return
        state = self._discord_messages.get(message_id)
        if state is None:
            return
        text_lower = text.lower()
        if not any(kw in text_lower for kw in POSITIVE_KEYWORDS):
            return
        state.count += 1
        state.last_applied_tier = self._maybe_apply(
            state.count, state.last_applied_tier,
            reply_text=state.reply_text, channel_id=state.channel_id, platform="discord",
        )

    def track_twitch_response(self, channel_id: str, reply_text: str = "") -> None:
        self._cleanup()
        self._twitch_windows[channel_id] = _TwitchWindow(reply_text=reply_text)

    def check_twitch_message(self, channel_id: str, text: str) -> None:
        window = self._twitch_windows.get(channel_id)
        if window is None:
            return
        if time.time() - window.timestamp > TWITCH_WINDOW_SECONDS:
            return
        text_lower = text.lower()
        if not any(kw in text_lower for kw in POSITIVE_KEYWORDS):
            return
        window.count += 1
        window.last_applied_tier = self._maybe_apply(
            window.count, window.last_applied_tier,
            reply_text=window.reply_text, channel_id=channel_id, platform="twitch",
        )
