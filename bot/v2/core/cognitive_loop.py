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
        feed=None,
    ) -> None:
        self._attention = attention_agent
        self._monologue = inner_monologue
        self._meta = meta_agent
        self._dispatcher = action_dispatcher
        self._emotion = emotion_engine
        self._feed = feed
        self._last_activity_ts: float = 0.0
        self._last_tick_activity_ts: float = 0.0
        self._recent_interactions: list[dict] = []
        # Conscience sociale : par canal, suivi des messages spontanés de Wally
        # restés sans réponse → injecté dans le monologue pour qu'il se régule
        # lui-même (un humain n'insiste pas auprès de qui l'ignore).
        # {channel_id: {"last_ts": monotonic, "unanswered": int}}
        self._spontaneous: dict[str, dict] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    def notify_activity(self, channel_id: int, author: str, content: str) -> None:
        self._last_activity_ts = time.monotonic()
        # Quelqu'un a parlé dans ce canal → ses messages spontanés y ont reçu
        # une suite : on remet le compteur « sans réponse » à zéro.
        st = self._spontaneous.get(str(channel_id))
        if st is not None:
            st["unanswered"] = 0
        self._recent_interactions.append({
            "channel": str(channel_id),
            "author": author,
            "content": content[:200],
            "ts": self._last_activity_ts,
        })
        if len(self._recent_interactions) > 20:
            self._recent_interactions = self._recent_interactions[-20:]

    def _tick_interval(self) -> int:
        elapsed = time.monotonic() - self._last_activity_ts
        if elapsed < 600:
            return TICK_ACTIVE
        if elapsed < 3600:
            return TICK_MODERATE
        return TICK_IDLE

    async def _tick(self) -> None:
        # Pas de nouvelle activité depuis le dernier tick → on ne re-génère pas
        # une pensée sur un contexte identique (évite la rumination en boucle).
        if self._last_activity_ts == self._last_tick_activity_ts:
            return
        self._last_tick_activity_ts = self._last_activity_ts
        try:
            now = time.monotonic()
            emotion_state = self._emotion.get_state() if self._emotion is not None else {}
            spontaneous = [
                {"channel": ch, "unanswered": st["unanswered"], "seconds_since": int(now - st["last_ts"])}
                for ch, st in self._spontaneous.items()
                if st["unanswered"] > 0
            ]
            context = await self._attention.build_context(
                emotion_state, self._recent_interactions, spontaneous=spontaneous
            )
            if self._feed:
                _last = self._recent_interactions[-1] if self._recent_interactions else {}
                self._feed.publish({
                    "type": "ATTN",
                    "target": _last.get("author", "—"),
                    "content_snippet": (_last.get("content") or "")[:160],
                })
            result = await self._monologue.generate(context)
            if self._feed:
                self._feed.publish({"type": "THINK", "text": result.text})
            decisions = await self._meta.decide(result.text)
            if self._feed:
                self._feed.publish({"type": "DECIDE", "actions": [d.action for d in decisions]})
            for decision in decisions:
                if decision.action == "SLEEP" and getattr(decision, "sleep_seconds", None):
                    await asyncio.sleep(min(decision.sleep_seconds, 3600))
                    continue
                await self._dispatcher.dispatch(decision)
                # Mémorise un message spontané pour la conscience sociale : tant
                # que personne n'y répond, le compteur grimpe et le prochain
                # monologue verra qu'il parle dans le vide.
                if decision.action == "SPEAK" and decision.channel_id:
                    st = self._spontaneous.setdefault(
                        str(decision.channel_id), {"last_ts": now, "unanswered": 0}
                    )
                    st["last_ts"] = time.monotonic()
                    st["unanswered"] += 1
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
