from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class AttentionContext:
    emotion_state: dict[str, float]
    active_desires: list  # list[AtomicFact]
    active_goals: list    # list[AtomicFact]
    recent_thoughts: list  # list[AtomicFact], 3 dernières
    recent_interactions: list[dict]  # [{channel, author, content, ts}]
    time_of_day: str  # "morning" | "afternoon" | "evening" | "night"


class AttentionAgent:
    def __init__(self, fact_store, emotion_engine=None) -> None:
        self._facts = fact_store
        self._emotion = emotion_engine  # réservé pour usage futur

    async def build_context(
        self,
        emotion_state: dict[str, float],
        recent_interactions: list[dict],
    ) -> AttentionContext:
        from bot.v2.core.memory.facts import FactCategory, FactStatus

        desires = await self._facts.search_by_category(
            FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=5
        )
        goals = await self._facts.search_by_category(
            FactCategory.GOAL, status=FactStatus.ACTIVE, limit=5
        )
        thoughts = await self._facts.search_by_category(
            FactCategory.THOUGHT, status=FactStatus.ACTIVE, limit=3
        )

        hour = datetime.now(timezone.utc).hour
        if 5 <= hour < 12:
            tod = "morning"
        elif 12 <= hour < 17:
            tod = "afternoon"
        elif 17 <= hour < 22:
            tod = "evening"
        else:
            tod = "night"

        return AttentionContext(
            emotion_state=emotion_state,
            active_desires=desires,
            active_goals=goals,
            recent_thoughts=thoughts,
            recent_interactions=recent_interactions[-10:],
            time_of_day=tod,
        )
