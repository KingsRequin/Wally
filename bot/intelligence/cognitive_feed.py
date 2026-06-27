from __future__ import annotations

import asyncio
from collections import deque


class CognitiveFeed:
    """Fan-out broadcaster for the cognitive loop's live events.

    Mirrors the SSE fan-out pattern in bot/dashboard/routes/sse.py: a list of
    per-subscriber asyncio.Queues plus a circular buffer of the last N events
    used to seed a client before the SSE stream takes over.
    """

    def __init__(
        self, buffer_size: int = 30, queue_maxsize: int = 50, conv_log=None,
        event_store=None,
    ) -> None:
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._queues: list[asyncio.Queue] = []
        self._queue_maxsize = queue_maxsize
        # Logger de conversation : tout le flux cognitif (ATTN/THINK/DECIDE/
        # SPEAK/ACT/EVOLVE) est journalisé dans logs/conversations/cognitive/brain/.
        self._conv_log = conv_log
        # Historique persistant (#observability). None → live seulement.
        self._event_store = event_store
        # Réfs fortes des tâches de persistance fire-and-forget → évite leur GC
        # prématuré et la perte silencieuse d'une exception future.
        self._persist_tasks: set[asyncio.Task] = set()

    def publish(self, event: dict) -> None:
        # Anti-rumination : ignore un événement identique au précédent
        # (même type + même contenu) — évite que le flux répète la même pensée.
        if self._buffer and self._buffer[-1] == event:
            return
        self._buffer.append(event)
        if self._conv_log is not None:
            etype = str(event.get("type", "event")).lower()
            fields = {k: v for k, v in event.items() if k != "type"}
            self._conv_log.log("cognitive", "brain", etype, **fields)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        # Persistance de l'historique (sauf ATTN, trop fréquent/transitoire).
        if self._event_store is not None and event.get("type") != "ATTN":
            try:
                task = asyncio.get_running_loop().create_task(
                    self._event_store.append(dict(event))
                )
                self._persist_tasks.add(task)
                task.add_done_callback(self._persist_tasks.discard)
            except RuntimeError:
                pass   # pas de loop (test sync) → on saute la persistance

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
