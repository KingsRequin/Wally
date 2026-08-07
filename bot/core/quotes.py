"""Citations du live — une phrase entendue en vocal, ressortie plus tard.

Tout l'intérêt est dans le décalage : une réplique reprise dix minutes après
fait sourire, la même reprise trois jours plus tard fait rire. D'où la
persistance, et d'où la préférence donnée aux citations qu'on n'a pas déjà
montrées.

Wally ne peut citer que ce qu'il a entendu : le texte vient de sa transcription,
pas de son imagination. Le prompt le lui rappelle, la base ne peut pas le
vérifier.
"""
from __future__ import annotations

import random
import time

from loguru import logger

# Une citation plus longue ne tient pas à l'écran et n'est plus une punchline.
_MAX_CHARS = 160


class QuoteBook:
    """Retient et ressort les répliques marquantes."""

    def __init__(self, db) -> None:
        self._db = db

    async def add(self, author: str, text: str) -> dict | None:
        author = " ".join((author or "").split())[:24]
        text = " ".join((text or "").split())[:_MAX_CHARS]
        if not author or len(text) < 4:
            return None
        now = time.time()
        await self._db.execute(
            "INSERT INTO quotes (author, text, created_at, shown_at) VALUES (?, ?, ?, ?)",
            (author, text, now, now),      # citée à l'instant : déjà montrée
        )
        logger.info("Citation retenue — {a} : {t}", a=author, t=text[:60])
        return {"author": author, "text": text}

    async def recall(self, author: str = "") -> dict | None:
        """Ressort une citation, en privilégiant les moins vues et les plus vieilles.

        Une citation d'il y a trois jours vaut mieux qu'une d'il y a dix minutes :
        le décalage fait tout.
        """
        query = "SELECT * FROM quotes"
        params: tuple = ()
        if author:
            query += " WHERE author = ? COLLATE NOCASE"
            params = (author.strip(),)
        query += " ORDER BY COALESCE(shown_at, 0) ASC LIMIT 12"
        rows = [dict(r) for r in await self._db.fetch_all(query, params)]
        if not rows:
            return None
        chosen = random.choice(rows)
        await self._db.execute(
            "UPDATE quotes SET shown_at = ? WHERE id = ?", (time.time(), chosen["id"])
        )
        return chosen

    async def count(self) -> int:
        rows = await self._db.fetch_all("SELECT COUNT(*) AS n FROM quotes")
        return int(rows[0]["n"]) if rows else 0
