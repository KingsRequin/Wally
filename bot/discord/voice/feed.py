"""VoiceFeed — fan-out live des événements du pipeline vocal (mimique CognitiveFeed).

Une Queue par abonné SSE + un buffer circulaire des derniers événements (snapshot initial).
Persistance optionnelle via un VoiceEventStore (historique de debug).
"""
from __future__ import annotations

import asyncio
from collections import deque


class VoiceFeed:
    def __init__(
        self, event_store=None, buffer_size: int = 50, queue_maxsize: int = 100
    ) -> None:
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._queues: list[asyncio.Queue] = []
        self._queue_maxsize = queue_maxsize
        self._event_store = event_store
        # Réfs fortes des tâches de persistance fire-and-forget (évite GC prématuré).
        self._persist_tasks: set[asyncio.Task] = set()

    def publish(self, event: dict) -> None:
        self._buffer.append(event)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        if self._event_store is not None:
            try:
                task = asyncio.get_running_loop().create_task(
                    self._event_store.append(dict(event))
                )
                self._persist_tasks.add(task)
                task.add_done_callback(self._persist_tasks.discard)
            except RuntimeError:
                pass  # pas de loop (test sync) → on saute la persistance

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
