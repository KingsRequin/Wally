"""Social signal capture — feeds Discord social interactions into the knowledge graph."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.core.graph import GraphService


class SocialTracker:
    """Tracks social interactions and flushes to the knowledge graph.

    All on_* methods accept Discord user IDs (str snowflakes) as identifiers.
    Display names are registered via register_user() and resolved in _format_signal().
    """

    FLUSH_INTERVAL = 300  # 5 minutes
    _VOICE_SESSION_TTL = 4 * 3600  # 4 hours

    def __init__(self, graph: "GraphService", group_id: str | None = None,
                 bot_id: int | None = None):
        self._graph = graph
        self._group_id = group_id
        self._bot_id: str | None = str(bot_id) if bot_id else None
        # id → display_name resolution cache
        self._id_to_name: dict[str, str] = {}
        # Buffers: (user_a_id, user_b_id, signal_type) -> {count, last_seen, metadata}
        self._buffer: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "last_seen": 0.0, "metadata": {}}
        )
        # Voice state: channel_id -> {user_id (int): join_time}
        self._voice_sessions: dict[int, dict[int, float]] = defaultdict(dict)
        # Active game sessions: game_name -> {user_id (str)}
        self._active_games: dict[str, set[str]] = defaultdict(set)
        self._flush_task: asyncio.Task | None = None

    def register_user(self, user_id: str, display_name: str) -> None:
        """Register a Discord user ID → display name mapping."""
        self._id_to_name[user_id] = display_name

    def set_bot_id(self, bot_id: int) -> None:
        """Set the bot's own Discord ID (called from on_ready)."""
        self._bot_id = str(bot_id)

    def _involves_bot(self, *ids: str) -> bool:
        return self._bot_id is not None and self._bot_id in ids

    def _resolve(self, user_id: str) -> str:
        """Resolve a user ID to display name, falling back to the ID itself."""
        return self._id_to_name.get(user_id, user_id)

    def start(self) -> None:
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_loop())
            logger.info("SocialTracker started (flush every {s}s)", s=self.FLUSH_INTERVAL)

    async def _flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.FLUSH_INTERVAL)
                await self.flush()
        except asyncio.CancelledError:
            pass

    async def flush(self) -> int:
        """Write buffered signals to the knowledge graph. Returns count flushed."""
        self._emit_active_voice_signals()
        self._cleanup_stale_voice_sessions()
        if not self._graph.ready or not self._buffer:
            return 0
        buffer = dict(self._buffer)
        self._buffer.clear()
        flushed = 0
        for (user_a, user_b, signal_type), data in buffer.items():
            try:
                content = self._format_signal(user_a, user_b, signal_type, data)
                await self._graph.add_episode(
                    content=content,
                    author="",
                    source="social_tracker",
                    group_id=self._group_id,
                )
                flushed += 1
            except Exception as exc:
                logger.debug("Social signal flush failed: {e}", e=exc)
        if flushed:
            logger.debug("SocialTracker flushed {n} signals", n=flushed)
        return flushed

    def _format_signal(self, uid_a: str, uid_b: str, signal_type: str, data: dict) -> str:
        """Format a social signal using resolved display names."""
        name_a = self._resolve(uid_a)
        name_b = self._resolve(uid_b)
        count = data["count"]
        meta = data.get("metadata", {})
        templates = {
            "voice":    f"{name_a} et {name_b} ont passé du temps en vocal ensemble ({count} sessions)",
            "reply":    f"{name_a} a répondu à {name_b} ({count} fois)",
            "mention":  f"{name_a} a mentionné {name_b} ({count} fois)",
            "reaction": f"{name_a} a réagi aux messages de {name_b} ({count} fois)",
            "thread":   f"{name_a} et {name_b} ont participé au même thread ({count} fois)",
            "game":     f"{name_a} et {name_b} ont joué à {meta.get('game', 'un jeu')} ensemble ({count} fois)",
        }
        return templates.get(signal_type, f"{name_a} interagit avec {name_b}")

    @staticmethod
    def _key(a: str, b: str) -> tuple[str, str]:
        """Normalize pair order (alphabetical) for consistent keys."""
        return (min(a, b), max(a, b))

    # ── Event handlers — all accept Discord user IDs (str) ──

    def on_reply(self, author_id: str, replied_to_id: str) -> None:
        if self._involves_bot(author_id, replied_to_id):
            return
        key = (author_id, replied_to_id, "reply")
        self._buffer[key]["count"] += 1
        self._buffer[key]["last_seen"] = time.time()

    def on_mention(self, author_id: str, mentioned_id: str) -> None:
        if self._involves_bot(author_id, mentioned_id):
            return
        key = (author_id, mentioned_id, "mention")
        self._buffer[key]["count"] += 1
        self._buffer[key]["last_seen"] = time.time()

    def on_reaction(self, reactor_id: str, message_author_id: str) -> None:
        if self._involves_bot(reactor_id, message_author_id):
            return
        if reactor_id == message_author_id:
            return
        key = (reactor_id, message_author_id, "reaction")
        self._buffer[key]["count"] += 1
        self._buffer[key]["last_seen"] = time.time()

    def on_thread_message(self, author_id: str, owner_id: str) -> None:
        if self._involves_bot(author_id, owner_id):
            return
        if author_id == owner_id:
            return
        a, b = self._key(author_id, owner_id)
        self._buffer[(a, b, "thread")]["count"] += 1
        self._buffer[(a, b, "thread")]["last_seen"] = time.time()

    def on_game_start(self, user_id: str, game: str) -> None:
        if self._involves_bot(user_id):
            return
        now = time.time()
        for other_id in self._active_games[game]:
            a, b = self._key(user_id, other_id)
            key = (a, b, "game")
            self._buffer[key]["count"] += 1
            self._buffer[key]["last_seen"] = now
            self._buffer[key]["metadata"]["game"] = game
        self._active_games[game].add(user_id)

    def on_game_stop(self, user_id: str, game: str) -> None:
        if self._involves_bot(user_id):
            return
        self._active_games[game].discard(user_id)
        if not self._active_games[game]:
            del self._active_games[game]

    def _emit_active_voice_signals(self) -> None:
        now = time.time()
        for users in self._voice_sessions.values():
            uids = list(users.keys())
            for i, uid_a in enumerate(uids):
                for uid_b in uids[i + 1:]:
                    a, b = self._key(str(uid_a), str(uid_b))
                    self._buffer[(a, b, "voice")]["count"] += 1
                    self._buffer[(a, b, "voice")]["last_seen"] = now

    def _cleanup_stale_voice_sessions(self) -> None:
        cutoff = time.time() - self._VOICE_SESSION_TTL
        for ch_id in list(self._voice_sessions):
            stale = [uid for uid, jt in self._voice_sessions[ch_id].items() if jt < cutoff]
            for uid in stale:
                del self._voice_sessions[ch_id][uid]
            if not self._voice_sessions[ch_id]:
                del self._voice_sessions[ch_id]

    def on_voice_join(self, channel_id: int, user_id: int, display_name: str) -> None:
        if self._involves_bot(str(user_id)):
            return
        self.register_user(str(user_id), display_name)
        self._voice_sessions[channel_id][user_id] = time.time()

    def on_voice_leave(self, channel_id: int, user_id: int, display_name: str) -> None:
        if self._involves_bot(str(user_id)):
            return
        self.register_user(str(user_id), display_name)
        join_time = self._voice_sessions.get(channel_id, {}).pop(user_id, None)
        if join_time is None:
            return
        uid_str = str(user_id)
        for other_uid in list(self._voice_sessions.get(channel_id, {}).keys()):
            a, b = self._key(uid_str, str(other_uid))
            self._buffer[(a, b, "voice")]["count"] += 1
            self._buffer[(a, b, "voice")]["last_seen"] = time.time()
        if not self._voice_sessions.get(channel_id):
            self._voice_sessions.pop(channel_id, None)

    async def stop(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self.flush()
