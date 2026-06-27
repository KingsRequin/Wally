from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import aiosqlite
from loguru import logger

# Cycle de vie d'une demande d'amélioration (code_fix).
REQUESTED = "requested"   # émise, en attente d'autorisation / d'exécution
DELIVERED = "delivered"   # acceptée, implémentée et déployée
DECLINED = "declined"     # refusée par le créateur
ABANDONED = "abandoned"   # timeout / échec technique / sans changement (re-proposable)

# Statuts qui BLOQUENT une redemande : une demande encore ouverte ou déjà livrée.
# Les ABANDONED restent re-proposables (cf. "à reproposer" dans self_fix).
_BLOCKING = (REQUESTED, DELIVERED)

_STOPWORDS = frozenset(
    {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "que",
     "qui", "est", "sur", "pour", "dans", "par", "pas", "ce", "ça", "il",
     "je", "me", "mon", "ma", "mes", "the", "and", "for", "with"}
)


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return {t for t in cleaned.split() if len(t) >= 3 and t not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class UpgradeRow:
    id: int
    proposal: str
    status: str
    created_at: str
    decided_at: str | None = None


class UpgradeRegistry:
    """Registre durable des demandes d'amélioration de Wally (table
    `pending_upgrades`). Donne à Wally la mémoire de ce qu'il a déjà demandé /
    obtenu, pour ne pas redemander une capacité déjà livrée."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def record_request(self, proposal: str) -> int:
        proposal = (proposal or "").strip()
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """INSERT INTO pending_upgrades (proposal, status, created_at)
                   VALUES (?, ?, ?)""",
                (proposal, REQUESTED, now),
            )
            await db.commit()
            logger.debug("UpgradeRegistry: demande #{} enregistrée — {}", cur.lastrowid, proposal[:60])
            return cur.lastrowid  # type: ignore[return-value]

    async def set_status(self, upgrade_id: int, status: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE pending_upgrades SET status = ?, decided_at = ? WHERE id = ?",
                (status, datetime.utcnow().isoformat(), upgrade_id),
            )
            await db.commit()

    async def recent(self, limit: int = 6) -> list[UpgradeRow]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """SELECT id, proposal, status, created_at, decided_at
                   FROM pending_upgrades ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            )
            rows = await cur.fetchall()
        return [
            UpgradeRow(id=r["id"], proposal=r["proposal"], status=r["status"],
                       created_at=r["created_at"], decided_at=r["decided_at"])
            for r in rows
        ]

    async def find_similar(
        self, proposal: str, threshold: float = 0.3
    ) -> UpgradeRow | None:
        """Retourne une demande BLOQUANTE (requested/delivered) sémantiquement
        proche de `proposal`, ou None. Sert la garde anti-redemande."""
        target = _tokens(proposal)
        if not target:
            return None
        placeholders = ",".join("?" * len(_BLOCKING))
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                f"""SELECT id, proposal, status, created_at, decided_at
                    FROM pending_upgrades WHERE status IN ({placeholders})""",
                _BLOCKING,
            )
            rows = await cur.fetchall()
        best: UpgradeRow | None = None
        best_score = threshold
        for r in rows:
            score = _jaccard(target, _tokens(r["proposal"]))
            if score >= best_score:
                best_score = score
                best = UpgradeRow(id=r["id"], proposal=r["proposal"], status=r["status"],
                                  created_at=r["created_at"], decided_at=r["decided_at"])
        return best
