from __future__ import annotations

import asyncio
from collections import deque


class CognitiveFeed:
    """Fan-out broadcaster for the cognitive loop's live events.

    Mirrors the SSE fan-out pattern in bot/dashboard/routes/sse.py: a list of
    per-subscriber asyncio.Queues plus a circular buffer of the last N events
    used to seed a client before the SSE stream takes over.
    """

    def __init__(self, buffer_size: int = 30, queue_maxsize: int = 50) -> None:
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._queues: list[asyncio.Queue] = []
        self._queue_maxsize = queue_maxsize

    def publish(self, event: dict) -> None:
        # Anti-rumination : ignore un événement identique au précédent
        # (même type + même contenu) — évite que le flux répète la même pensée.
        if self._buffer and self._buffer[-1] == event:
            return
        self._buffer.append(event)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def snapshot(self) -> list[dict]:
        return list(self._buffer)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass
