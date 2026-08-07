"""Paris de Wally sur l'issue d'une partie (widget 16).

Ce widget est resté bloqué longtemps parce qu'aucune source ne dit si une partie
est gagnée : ni l'API Twitch, ni le chat, ni les événements de stream. La sortie
n'est pas de deviner mieux, c'est de laisser Wally CONSTATER — il entend le
vocal et lit le chat, il tranche lui-même et l'assume.

Le score cumulé fait tout l'intérêt : un pari isolé n'amuse personne, « 7 bons
sur 12 » se défend d'un live à l'autre. D'où la persistance.
"""
from __future__ import annotations

import time

from loguru import logger

# Au-delà, le pari n'a plus de rapport avec la partie en cours : on le classe
# sans suite plutôt que de le trancher au hasard des heures après.
_STALE_AFTER_S = 3600.0


class PredictionService:
    """Ouvre, tranche et totalise les paris. La base fait foi."""

    def __init__(self, db) -> None:
        self._db = db

    async def open(self, bet: str) -> dict | None:
        """Ouvre un pari. Un seul à la fois : le précédent resté ouvert est
        abandonné, sinon on trancherait le mauvais."""
        bet = " ".join((bet or "").split())[:90]
        if not bet:
            return None
        await self._db.execute(
            "UPDATE predictions SET outcome = 'void', resolved_at = ? WHERE outcome IS NULL",
            (time.time(),),
        )
        await self._db.execute(
            "INSERT INTO predictions (bet, created_at) VALUES (?, ?)", (bet, time.time())
        )
        logger.info("Prédiction ouverte : « {b} »", b=bet)
        return await self.current()

    async def current(self) -> dict | None:
        """Le pari en cours, s'il n'est pas périmé."""
        row = await self._db.fetch_one(
            "SELECT * FROM predictions WHERE outcome IS NULL ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            return None
        row = dict(row)
        if time.time() - row["created_at"] > _STALE_AFTER_S:
            return None
        return row

    async def resolve(self, right: bool) -> dict | None:
        """Tranche le pari en cours. None s'il n'y en a pas — Wally ne doit pas
        pouvoir s'attribuer un point sans avoir parié."""
        row = await self.current()
        if row is None:
            return None
        outcome = "right" if right else "wrong"
        await self._db.execute(
            "UPDATE predictions SET outcome = ?, resolved_at = ? WHERE id = ?",
            (outcome, time.time(), row["id"]),
        )
        score = await self.score()
        logger.info("Prédiction « {b} » → {o} ({r}/{t})",
                    b=row["bet"], o=outcome, r=score["right"], t=score["total"])
        return {**row, "outcome": outcome, **score}

    async def score(self) -> dict:
        """Bilan cumulé. Les paris abandonnés ne comptent pas."""
        rows = await self._db.fetch_all(
            "SELECT outcome, COUNT(*) AS n FROM predictions "
            "WHERE outcome IN ('right', 'wrong') GROUP BY outcome"
        )
        counts = {r["outcome"]: r["n"] for r in rows}
        right = int(counts.get("right", 0))
        wrong = int(counts.get("wrong", 0))
        return {"right": right, "wrong": wrong, "total": right + wrong}
