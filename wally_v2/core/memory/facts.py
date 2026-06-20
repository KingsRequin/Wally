# wally_v2/core/memory/facts.py
from __future__ import annotations

import aiosqlite
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from loguru import logger


class FactCategory(str, Enum):
    FAIT    = "FAIT"
    PREF    = "PREF"
    REL     = "REL"
    LANG    = "LANG"
    DESIRE  = "DESIRE"
    GOAL    = "GOAL"
    EMOTION = "EMOTION"
    THOUGHT = "THOUGHT"


class FactStatus(str, Enum):
    ACTIVE       = "active"
    SUPERSEDED   = "superseded"
    NEEDS_REVIEW = "needs_review"
    ARCHIVED     = "archived"


DECAY_RATES: dict[FactCategory, float] = {
    FactCategory.FAIT:    0.001,
    FactCategory.PREF:    0.005,
    FactCategory.REL:     0.003,
    FactCategory.LANG:    0.001,
    FactCategory.DESIRE:  0.02,
    FactCategory.GOAL:    0.005,
    FactCategory.EMOTION: 0.01,
    FactCategory.THOUGHT: 0.05,
}


@dataclass
class AtomicFact:
    user_id:           str
    content:           str
    category:          FactCategory
    confidence:        float = 1.0
    status:            FactStatus = FactStatus.ACTIVE
    emotional_context: str | None = None
    source:            str = "conversation"
    created_at:        datetime = field(default_factory=datetime.utcnow)
    last_seen_at:      datetime = field(default_factory=datetime.utcnow)
    id:                int | None = None
    decay_rate:        float = field(init=False)

    def __post_init__(self) -> None:
        self.decay_rate = DECAY_RATES.get(self.category, 0.01)


@dataclass
class FactRelation:
    from_id:       int
    to_id:         int
    relation_type: str   # "supersedes" | "contradicts" | "supports"
    created_at:    datetime = field(default_factory=datetime.utcnow)
    id:            int | None = None


class SQLiteFactStore:
    """Accès SQLite pour les AtomicFacts et FactRelations."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def add(self, fact: AtomicFact) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO atomic_facts
                   (user_id, content, category, confidence, decay_rate, status,
                    emotional_context, source, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fact.user_id, fact.content, fact.category.value,
                    fact.confidence, fact.decay_rate, fact.status.value,
                    fact.emotional_context, fact.source,
                    fact.created_at.isoformat(), fact.last_seen_at.isoformat(),
                ),
            )
            await db.commit()
            fact.id = cursor.lastrowid
            return cursor.lastrowid  # type: ignore[return-value]

    async def get_by_user(
        self,
        user_id:        str,
        min_confidence: float = 0.3,
        categories:     list[FactCategory] | None = None,
        status:         FactStatus = FactStatus.ACTIVE,
    ) -> list[AtomicFact]:
        query = (
            "SELECT * FROM atomic_facts "
            "WHERE user_id = ? AND status = ? AND confidence >= ?"
        )
        params: list = [user_id, status.value, min_confidence]
        if categories:
            placeholders = ",".join("?" * len(categories))
            query += f" AND category IN ({placeholders})"
            params.extend(c.value for c in categories)
        query += " ORDER BY last_seen_at DESC, confidence DESC"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return [self._row_to_fact(r) for r in await cursor.fetchall()]

    async def get_by_ids(
        self,
        ids:            list[int],
        min_confidence: float = 0.3,
    ) -> list[AtomicFact]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        query = (
            f"SELECT * FROM atomic_facts "
            f"WHERE id IN ({placeholders}) AND confidence >= ? AND status = ?"
        )
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, [*ids, min_confidence, FactStatus.ACTIVE.value])
            return [self._row_to_fact(r) for r in await cursor.fetchall()]

    async def mark_seen(self, fact_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE atomic_facts SET last_seen_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), fact_id),
            )
            await db.commit()

    async def delete_by_user(self, user_id: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM atomic_facts WHERE user_id = ?", (user_id,)
            )
            await db.commit()
            return cursor.rowcount

    async def count_by_user(self, user_id: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM atomic_facts WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def apply_decay(self) -> int:
        """Réduit confidence de decay_rate pour tous les faits actifs.
        Archive ceux dont confidence tombe sous 0.1. Retourne le nombre de lignes modifiées.
        """
        async with aiosqlite.connect(self._db_path) as db:
            result = await db.execute(
                """UPDATE atomic_facts
                   SET confidence = MAX(0.0, confidence - decay_rate),
                       status = CASE
                           WHEN MAX(0.0, confidence - decay_rate) < 0.1 THEN 'archived'
                           ELSE status
                       END
                   WHERE status = 'active'"""
            )
            await db.commit()
            return result.rowcount

    async def add_relation(self, relation: FactRelation) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO fact_relations (from_id, to_id, relation_type, created_at)
                   VALUES (?, ?, ?, ?)""",
                (relation.from_id, relation.to_id, relation.relation_type,
                 relation.created_at.isoformat()),
            )
            await db.commit()
            relation.id = cursor.lastrowid
            return cursor.lastrowid  # type: ignore[return-value]

    async def supersede(self, old_id: int, new_id: int) -> None:
        """Marque old_id comme superseded et crée la relation supersedes new_id→old_id.

        Les deux opérations sont atomiques : aiosqlite démarre un BEGIN implicite
        avant le premier DML, et le commit() final valide les deux ensemble.
        """
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE atomic_facts SET status = 'superseded' WHERE id = ?",
                (old_id,),
            )
            await db.execute(
                """INSERT INTO fact_relations (from_id, to_id, relation_type, created_at)
                   VALUES (?, ?, 'supersedes', ?)""",
                (new_id, old_id, datetime.utcnow().isoformat()),
            )
            await db.commit()
            logger.debug("supersede: fact {} superseded by {}", old_id, new_id)

    async def search_by_category(
        self,
        category: "FactCategory",
        status: "FactStatus | None" = None,
        limit: int = 10,
    ) -> "list[AtomicFact]":
        if status is None:
            status = FactStatus.ACTIVE
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT id, user_id, content, category, confidence, decay_rate,
                          status, emotional_context, source, created_at, last_seen_at
                   FROM atomic_facts
                   WHERE category = ? AND status = ?
                   ORDER BY last_seen_at DESC
                   LIMIT ?""",
                (category.value, status.value, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_fact(r) for r in rows]

    @staticmethod
    def _row_to_fact(row: aiosqlite.Row) -> AtomicFact:
        fact = AtomicFact(
            user_id=row["user_id"],
            content=row["content"],
            category=FactCategory(row["category"]),
            confidence=row["confidence"],
            status=FactStatus(row["status"]),
            emotional_context=row["emotional_context"],
            source=row["source"] or "conversation",
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )
        fact.id = row["id"]
        # Restore the persisted decay_rate (overrides __post_init__) so that facts
        # keep the rate they were inserted with, even if DECAY_RATES changes later.
        fact.decay_rate = row["decay_rate"]
        return fact
