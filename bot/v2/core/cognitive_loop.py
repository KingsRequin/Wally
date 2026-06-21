from __future__ import annotations

import asyncio
import difflib
import random
import re
import time

from loguru import logger

TICK_ACTIVE = 30       # < 10 min depuis dernière activité : cognition de fond vive
TICK_MODERATE = 120    # < 1h : il se détend, encore engagé
TICK_IDLE = 300        # > 1h : plancher du vagabondage idle (5 min)
TICK_IDLE_MAX = 3600   # plafond du vagabondage idle (1h)

_WS_RE = re.compile(r"\s+")


def _too_similar(a: str, b: str) -> bool:
    """True si deux pensées sont quasi identiques (anti-rumination).

    Normalise (lower, strip, espaces collés) ; True si égales, ou si le ratio de
    similarité SequenceMatcher >= 0.92 sur les 400 premiers caractères.
    """
    if not a or not b:
        return False
    na = _WS_RE.sub(" ", a.strip().lower())
    nb = _WS_RE.sub(" ", b.strip().lower())
    if na == nb:
        return True
    return difflib.SequenceMatcher(None, na[:400], nb[:400]).ratio() >= 0.92


class CognitiveLoop:
    def __init__(
        self,
        attention_agent,
        reasoning_agent,
        action_dispatcher,
        emotion_engine=None,
        feed=None,
    ) -> None:
        self._attention = attention_agent
        self._reasoning = reasoning_agent
        self._dispatcher = action_dispatcher
        self._emotion = emotion_engine
        self._feed = feed
        self._last_activity_ts: float = 0.0
        self._last_tick_activity_ts: float = 0.0
        self._last_thought: str = ""
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
        # Seul/idle : l'esprit vagabonde par à-coups irréguliers (effet naturel),
        # pas sur une horloge fixe. Intervalle aléatoire 5 min – 1 h, mais l'ennui
        # raccourcit le plafond (Phase 1b) : plus Wally s'ennuie, plus vite il
        # vagabonde pour chercher de la stimulation. ennui=0 → plage complète ;
        # ennui=1 → toujours 5 min.
        boredom = 0.0
        if self._emotion is not None:
            try:
                boredom = float(self._emotion.get_state().get("boredom", 0.0))
            except Exception:
                boredom = 0.0
        hi = int(TICK_IDLE + (TICK_IDLE_MAX - TICK_IDLE) * (1.0 - min(1.0, max(0.0, boredom))))
        return random.randint(TICK_IDLE, max(TICK_IDLE, hi))

    async def _tick(self) -> None:
        # Pas de nouvelle activité depuis le dernier tick → cognition « idle » :
        # Wally pense quand même, mais à partir d'une amorce de nouveauté (souvenir,
        # but, désir, émotion, heure) pour vagabonder sans ruminer le même contexte.
        is_idle = (self._last_activity_ts == self._last_tick_activity_ts)
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
                emotion_state, self._recent_interactions, spontaneous=spontaneous, idle=is_idle
            )
            if self._feed:
                if is_idle:
                    self._feed.publish({
                        "type": "ATTN",
                        "target": "—",
                        "content_snippet": (getattr(context, "idle_seed", None) or "(vagabondage)")[:160],
                    })
                else:
                    _last = self._recent_interactions[-1] if self._recent_interactions else {}
                    self._feed.publish({
                        "type": "ATTN",
                        "target": _last.get("author", "—"),
                        "content_snippet": (_last.get("content") or "")[:160],
                    })
            result = await self._reasoning.reason(context)
            # Anti-rumination : si la nouvelle pensée est quasi identique à la
            # précédente, on se repose — pas de feed, pas de dispatch (le thought
            # est déjà stocké par le ReasoningAgent ; les THOUGHT décaient vite).
            if result.thought_text and _too_similar(result.thought_text, self._last_thought):
                logger.debug("CognitiveLoop: pensée quasi identique, repos")
                return
            self._last_thought = result.thought_text
            if self._feed:
                self._feed.publish({"type": "THINK", "text": result.thought_text})
            decisions = result.decisions
            if self._feed:
                self._feed.publish({"type": "DECIDE", "actions": [d.action for d in decisions]})
            # Routage SPEAK spontané : en cognition de fond, le channel_id est
            # souvent halluciné. On le redirige vers le dernier canal réellement
            # actif ; sans aucun canal connu, on n'envoie rien (pas de vide).
            known_channels = {i["channel"] for i in self._recent_interactions}
            last_channel = self._recent_interactions[-1]["channel"] if self._recent_interactions else None
            for decision in decisions:
                if decision.action == "SLEEP" and getattr(decision, "sleep_seconds", None):
                    await asyncio.sleep(min(decision.sleep_seconds, 3600))
                    continue
                if decision.action == "SPEAK" and decision.channel_id not in known_channels:
                    if last_channel:
                        logger.debug(
                            "CognitiveLoop: SPEAK canal {} inconnu → redirigé vers {}",
                            decision.channel_id, last_channel,
                        )
                        decision.channel_id = last_channel
                    else:
                        logger.info("SPEAK abandonné : aucun canal actif où parler")
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
