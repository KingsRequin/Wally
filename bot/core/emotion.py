# bot/core/emotion.py
from __future__ import annotations

import asyncio
import math
import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config

EMOTIONS = ["anger", "joy", "sadness", "curiosity", "boredom"]

# NRC Lexicon emotion → our 5 emotions mapping
NRC_MAP: dict[str, list[str]] = {
    "anger": ["anger", "disgust"],
    "joy": ["joy", "trust", "anticipation"],
    "sadness": ["sadness", "fear"],
    "curiosity": ["surprise"],
    "boredom": [],
}

# Max delta applied per message per emotion
MAX_DELTA_PER_MESSAGE = 0.3

# Emotions are zeroed below this floor after decay
DECAY_FLOOR = 0.01


class EmotionEngine:
    def __init__(self, config: "Config"):
        self._config = config
        self._state: dict[str, float] = {e: 0.0 for e in EMOTIONS}
        self._last_decay: float = time.time()
        self._decay_task: asyncio.Task | None = None

    # ── State access ─────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, float]:
        return dict(self._state)

    def apply_delta(self, emotion: str, delta: float) -> None:
        if emotion not in self._state:
            return
        self._state[emotion] = max(0.0, min(1.0, self._state[emotion] + delta))

    def set_emotion(self, emotion: str, value: float) -> None:
        if emotion in self._state:
            self._state[emotion] = max(0.0, min(1.0, value))

    def reset(self) -> None:
        self._state = {e: 0.0 for e in EMOTIONS}
        logger.info("Emotion state reset to zero")

    def get_dominant(self, threshold: float = 0.4) -> list[str]:
        return [e for e in EMOTIONS if self._state.get(e, 0.0) >= threshold]

    # ── Decay ─────────────────────────────────────────────────────────────────

    def _apply_decay(self) -> None:
        now = time.time()
        delta_t = now - self._last_decay
        if delta_t <= 0:
            return
        for emotion in EMOTIONS:
            cfg = self._config.emotions.get(emotion)
            if not cfg or self._state[emotion] <= 0:
                continue
            lam = cfg.decay_lambda
            decayed = self._state[emotion] * math.exp(-lam * delta_t)
            self._state[emotion] = 0.0 if decayed < DECAY_FLOOR else decayed
        self._last_decay = now

    async def _decay_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            self._apply_decay()
            logger.debug("Emotion decay applied: {state}", state=self._state)

    def start_decay_task(self) -> None:
        self._decay_task = asyncio.create_task(self._decay_loop())
        logger.info("Emotion decay task started")

    # ── NRCLex analysis ───────────────────────────────────────────────────────

    async def analyze_message(
        self, text: str, trust_score: float = 0.5
    ) -> dict[str, float]:
        return await asyncio.to_thread(self._analyze_sync, text, trust_score)

    def _analyze_sync(self, text: str, trust_score: float) -> dict[str, float]:
        try:
            from nrclex import NRCLex  # local import — heavy at first call

            scores = NRCLex(text).affect_frequencies
            deltas: dict[str, float] = {}

            for emotion, nrc_keys in NRC_MAP.items():
                if not nrc_keys:
                    continue
                raw = sum(scores.get(k, 0.0) for k in nrc_keys)
                if raw <= 0:
                    continue
                if emotion == "anger":
                    # Low trust amplifies anger response
                    amplifier = 1.0 + max(0.0, 1.0 - trust_score)
                    raw = min(raw * amplifier, MAX_DELTA_PER_MESSAGE)
                else:
                    raw = min(raw * 0.3, MAX_DELTA_PER_MESSAGE)
                deltas[emotion] = raw

            return deltas
        except Exception as exc:
            logger.warning("NRCLex analysis failed: {e}", e=exc)
            return {}

    async def process_message(self, text: str, trust_score: float = 0.5) -> None:
        deltas = await self.analyze_message(text, trust_score)
        for emotion, delta in deltas.items():
            self.apply_delta(emotion, delta)
