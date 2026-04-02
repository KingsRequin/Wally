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
    """Tracks social interactions and flushes to the knowledge graph."""

    FLUSH_INTERVAL = 300  # 5 minutes

    def __init__(self, graph: "GraphService", group_id: str | None = None):
        self._graph = graph
        self._group_id = group_id
        # Buffers: (user_a, user_b, signal_type) -> {count, last_seen, metadata}
        self._buffer: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "last_seen": 0.0, "metadata": {}}
        )
        # Voice state: channel_id -> {user_id: (join_time, display_name)}
        self._voice_sessions: dict[int, dict[int, tuple[float, str]]] = defaultdict(dict)
        self._flush_task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the periodic flush loop."""
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_loop())
            logger.info("SocialTracker started (flush every {s}s)", s=self.FLUSH_INTERVAL)

    async def _flush_loop(self) -> None:
        """Periodically flush buffered signals to Neo4j."""
        try:
            while True:
                await asyncio.sleep(self.FLUSH_INTERVAL)
                await self.flush()
        except asyncio.CancelledError:
            pass

    async def flush(self) -> int:
        """Write buffered signals to the knowledge graph. Returns count flushed."""
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
                    author="system",
                    source="social_tracker",
                    group_id=self._group_id,
                )
                flushed += 1
            except Exception as exc:
                logger.debug("Social signal flush failed: {e}", e=exc)
        if flushed:
            logger.debug("SocialTracker flushed {n} signals", n=flushed)
        return flushed

    def _format_signal(self, user_a: str, user_b: str, signal_type: str, data: dict) -> str:
        """Format a social signal as natural language for Graphiti ingestion."""
        count = data["count"]
        meta = data.get("metadata", {})
        templates = {
            "voice": f"{user_a} et {user_b} ont passé du temps en vocal ensemble ({count} sessions)",
            "reply": f"{user_a} a répondu à {user_b} ({count} fois)",
            "mention": f"{user_a} a mentionné {user_b} ({count} fois)",
            "reaction": f"{user_a} a réagi aux messages de {user_b} ({count} fois)",
            "thread": f"{user_a} et {user_b} ont participé au même thread ({count} fois)",
            "game": f"{user_a} et {user_b} ont joué à {meta.get('game', 'un jeu')} ensemble ({count} fois)",
        }
        return templates.get(signal_type, f"{user_a} interagit avec {user_b}")

    @staticmethod
    def _key(a: str, b: str) -> tuple[str, str]:
        """Normalize pair order (alphabetical) for consistent keys."""
        return (min(a, b), max(a, b))

    # ── Event handlers ──

    def on_reply(self, author_name: str, replied_to_name: str) -> None:
        a, b = self._key(author_name, replied_to_name)
        self._buffer[(a, b, "reply")]["count"] += 1
        self._buffer[(a, b, "reply")]["last_seen"] = time.time()

    def on_mention(self, author_name: str, mentioned_name: str) -> None:
        a, b = self._key(author_name, mentioned_name)
        self._buffer[(a, b, "mention")]["count"] += 1
        self._buffer[(a, b, "mention")]["last_seen"] = time.time()

    def on_reaction(self, reactor_name: str, message_author_name: str) -> None:
        if reactor_name == message_author_name:
            return
        a, b = self._key(reactor_name, message_author_name)
        self._buffer[(a, b, "reaction")]["count"] += 1
        self._buffer[(a, b, "reaction")]["last_seen"] = time.time()

    def on_thread_message(self, author_name: str, other_participant: str) -> None:
        if author_name == other_participant:
            return
        a, b = self._key(author_name, other_participant)
        self._buffer[(a, b, "thread")]["count"] += 1
        self._buffer[(a, b, "thread")]["last_seen"] = time.time()

    def on_game_together(self, user_a_name: str, user_b_name: str, game: str) -> None:
        a, b = self._key(user_a_name, user_b_name)
        key = (a, b, "game")
        self._buffer[key]["count"] += 1
        self._buffer[key]["last_seen"] = time.time()
        self._buffer[key]["metadata"]["game"] = game

    def on_voice_join(self, channel_id: int, user_id: int, display_name: str) -> None:
        """Track when a user joins a voice channel."""
        self._voice_sessions[channel_id][user_id] = (time.time(), display_name)

    def on_voice_leave(self, channel_id: int, user_id: int, display_name: str) -> None:
        """When a user leaves voice, record co-presence with others still in channel."""
        session = self._voice_sessions.get(channel_id, {}).pop(user_id, None)
        if session is None:
            return
        # Record co-presence with everyone still in the channel
        for other_uid, (_, other_name) in self._voice_sessions.get(channel_id, {}).items():
            a, b = self._key(display_name, other_name)
            self._buffer[(a, b, "voice")]["count"] += 1
            self._buffer[(a, b, "voice")]["last_seen"] = time.time()
        # Clean up empty channels
        if not self._voice_sessions.get(channel_id):
            self._voice_sessions.pop(channel_id, None)

    async def stop(self) -> None:
        """Stop flush loop and final flush."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self.flush()
