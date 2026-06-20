from __future__ import annotations

import asyncio
import time

from loguru import logger

TICK_ACTIVE = 30       # < 10 min depuis dernière activité
TICK_MODERATE = 120    # < 1h
TICK_IDLE = 300        # > 1h


class CognitiveLoop:
    def __init__(
        self,
        attention_agent,
        inner_monologue,
        meta_agent,
        action_dispatcher,
        emotion_engine=None,
    ) -> None:
        self._attention = attention_agent
        self._monologue = inner_monologue
        self._meta = meta_agent
        self._dispatcher = action_dispatcher
        self._emotion = emotion_engine
        self._last_activity_ts: float = 0.0
        self._recent_interactions: list[dict] = []
        self._task: asyncio.Task | None = None
        self._running = False

    def notify_activity(self, channel_id: int, author: str, content: str) -> None:
        self._last_activity_ts = time.time()
        self._recent_interactions.append({
            "channel": str(channel_id),
            "author": author,
            "content": content[:200],
            "ts": self._last_activity_ts,
        })
        if len(self._recent_interactions) > 20:
            self._recent_interactions = self._recent_interactions[-20:]

    def _tick_interval(self) -> int:
        elapsed = time.time() - self._last_activity_ts
        if elapsed < 600:
            return TICK_ACTIVE
        if elapsed < 3600:
            return TICK_MODERATE
        return TICK_IDLE

    async def _tick(self) -> None:
        try:
            emotion_state = self._emotion.get_state() if self._emotion is not None else {}
            context = await self._attention.build_context(emotion_state, self._recent_interactions)
            result = await self._monologue.generate(context)
            decisions = await self._meta.decide(result.text)
            for decision in decisions:
                if decision.action == "SLEEP" and getattr(decision, "sleep_seconds", None):
                    await asyncio.sleep(min(decision.sleep_seconds, 3600))
                    continue
                await self._dispatcher.dispatch(decision)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("CognitiveLoop tick error: {}", e)

    async def _run(self) -> None:
        logger.info("CognitiveLoop démarrée")
        while self._running:
            interval = self._tick_interval()
            await asyncio.sleep(interval)
            if not self._running:
                break
            await self._tick()

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("CognitiveLoop task créée (tick adaptatif 30s/2min/5min)")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CognitiveLoop arrêtée")
