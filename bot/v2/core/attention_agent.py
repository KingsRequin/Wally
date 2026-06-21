from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AttentionContext:
    emotion_state: dict[str, float]
    active_desires: list  # list[AtomicFact]
    active_goals: list    # list[AtomicFact]
    recent_thoughts: list  # list[AtomicFact], 3 dernières
    recent_interactions: list[dict]  # [{channel, author, content, ts}]
    time_of_day: str  # "morning" | "afternoon" | "evening" | "night"
    spontaneous_outreach: list[dict] = field(default_factory=list)  # [{channel, unanswered, seconds_since}]
    # Amorce de vagabondage : présente uniquement en cognition idle, sinon None.
    idle_seed: str | None = None
    # Pulsion émotionnelle : directive de comportement quand une émotion domine
    # au-dessus du seuil (Phase 1b). None en état neutre.
    emotional_drive: str | None = None
    # Préoccupation courante : le fil de pensée persistant qui traverse les ticks
    # (Phase 3a). Dernier fait actif de source `focus`. None si aucun.
    preoccupation: str | None = None
    # Récit de soi : le dernier « qui je deviens » écrit par Wally (Phase 3b).
    # Dernier fait actif de source `self_narrative`. None si aucun.
    self_narrative: str | None = None


class AttentionAgent:
    def __init__(self, fact_store, emotion_engine=None) -> None:
        self._facts = fact_store
        self._emotion = emotion_engine  # réservé pour usage futur

    async def build_context(
        self,
        emotion_state: dict[str, float],
        recent_interactions: list[dict],
        spontaneous: list[dict] | None = None,
        idle: bool = False,
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

        idle_seed: str | None = None
        if idle:
            idle_seed = await self._build_idle_seed(
                emotion_state, desires, goals, tod, FactCategory
            )

        # Pulsion émotionnelle : calculée à chaque tick (pas seulement en idle),
        # pour orienter la décision aussi bien en conversation qu'en vagabondage.
        from bot.v2.core.emotional_drive import emotional_drive
        drive = emotional_drive(emotion_state)

        # Préoccupation courante : dernier fait actif de source `focus` (Phase 3a).
        # Requêtée à chaque tick → persiste aussi à travers les redémarrages.
        latest = await self._facts.get_latest_by_source("wally:self", "focus")
        preoccupation = latest.content if latest else None

        # Récit de soi : dernier « qui je deviens » écrit par Wally (Phase 3b).
        sn = await self._facts.get_latest_by_source("wally:self", "self_narrative")
        self_narrative = sn.content if sn else None

        return AttentionContext(
            emotion_state=emotion_state,
            active_desires=desires,
            active_goals=goals,
            recent_thoughts=thoughts,
            recent_interactions=recent_interactions[-10:],
            time_of_day=tod,
            spontaneous_outreach=spontaneous or [],
            idle_seed=idle_seed,
            emotional_drive=drive,
            preoccupation=preoccupation,
            self_narrative=self_narrative,
        )

    async def _build_idle_seed(
        self,
        emotion_state: dict[str, float],
        desires: list,
        goals: list,
        time_of_day: str,
        fact_category,
    ) -> str | None:
        """Construit une amorce de vagabondage variée : choisit ALÉATOIREMENT
        une source de nouveauté parmi celles disponibles, pour éviter de
        ruminer toujours le même contexte.
        """
        seeds: list[str] = []

        memories = await self._facts.sample_random(
            limit=1, exclude_category=fact_category.THOUGHT
        )
        if memories:
            seeds.append(f"Un souvenir qui te revient : {memories[0].content}")

        if goals:
            goal = random.choice(goals)
            seeds.append(f"Ton objectif : {goal.content}")

        if desires:
            desire = random.choice(desires)
            seeds.append(f"Un désir qui te travaille : {desire.content}")

        if emotion_state:
            dominant = max(emotion_state, key=emotion_state.get)
            seeds.append(f"Ce que tu ressens surtout là : {dominant}")

        if time_of_day:
            seeds.append(f"C'est {time_of_day}.")

        if not seeds:
            return None
        return random.choice(seeds)
