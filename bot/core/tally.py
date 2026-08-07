"""Compteurs à la demande — « compte combien de fois Azra dit qu'il a pas rechargé ».

Deux contraintes ont dicté la conception :

1. **Le coût.** Wally entend des centaines de phrases par live. Faire juger
   chacune par un LLM serait ruineux et lent. Le modèle ne travaille donc
   qu'UNE fois, à la création : il traduit la demande en formulations
   (« pas rechargé », « j'ai plus de balles »…). La détection qui suit est un
   simple test de sous-chaîne, instantané et gratuit.

2. **La durée.** Un compteur doit survivre au redémarrage et courir d'un live à
   l'autre — d'où la persistance en base plutôt qu'en mémoire.

Le comptage est volontairement naïf : il ne comprend pas, il repère. C'est
assumé — un compteur de gag n'a pas besoin d'être juste, il a besoin d'être
lisible et de ne jamais s'arrêter tout seul.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata

from loguru import logger

# Au-delà, ce n'est plus un compteur de gag mais un filtre : le risque de faux
# positifs explose et le compteur perd tout sens.
_MAX_KEYWORDS = 8

# Une même phrase ne compte qu'une fois, même si plusieurs formulations y
# figurent (« j'ai pas rechargé, j'avais plus de balles » = 1).
_MIN_INTERVAL_S = 3.0


def _normalize(text: str) -> str:
    """Minuscules, sans accents, ponctuation réduite, entourée d'espaces.

    Les transcriptions vocales accentuent au petit bonheur (« recharge » /
    « rechargé ») : sans normalisation, la moitié des occurrences passeraient à
    côté.

    Les espaces de bord ne sont pas cosmétiques : la détection cherche
    « ␣lag␣ », ce qui évite de compter « village ».
    """
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {text.strip()} "


class TallyService:
    """Crée, arrête et alimente les compteurs. Sans état : la base fait foi."""

    def __init__(self, db) -> None:
        self._db = db
        # Dernier déclenchement par compteur : évite de compter deux fois la même
        # phrase, et amortit les répétitions immédiates du STT.
        self._last_hit: dict[int, float] = {}

    async def start(self, label: str, keywords: list[str], target: str = "") -> dict | None:
        """Ouvre un compteur. Retourne None si la demande est inexploitable."""
        label = " ".join((label or "").split())[:60]
        cleaned = [_normalize(k) for k in (keywords or [])]
        cleaned = [k.strip() for k in cleaned if len(k.strip()) >= 3][:_MAX_KEYWORDS]
        if not label or not cleaned:
            return None
        now = time.time()
        # Relancer un compteur existant le REPREND là où il s'était arrêté : on
        # ne remet pas à zéro un gag qui court depuis trois streams.
        await self._db.execute(
            """INSERT INTO tally_counters (label, keywords, target, count, active, created_at)
               VALUES (?, ?, ?, 0, 1, ?)
               ON CONFLICT(label) DO UPDATE SET active = 1, keywords = excluded.keywords""",
            (label, json.dumps(cleaned, ensure_ascii=False), target or None, now),
        )
        logger.info("Tally: compteur « {l} » actif ({n} formulations)", l=label, n=len(cleaned))
        return await self.get(label)

    async def stop(self, label: str) -> dict | None:
        """Arrête un compteur sans l'effacer : son total reste consultable."""
        row = await self.get(label)
        if row is None:
            return None
        await self._db.execute(
            "UPDATE tally_counters SET active = 0 WHERE id = ?", (row["id"],)
        )
        logger.info("Tally: compteur « {l} » arrêté à {n}", l=row["label"], n=row["count"])
        return {**row, "active": 0}

    async def get(self, label: str) -> dict | None:
        row = await self._db.fetch_one(
            "SELECT * FROM tally_counters WHERE label = ?", (label,)
        )
        return dict(row) if row else None

    async def list(self, active_only: bool = False) -> list[dict]:
        query = "SELECT * FROM tally_counters"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY active DESC, count DESC"
        return [dict(r) for r in await self._db.fetch_all(query)]

    async def scan(self, text: str, *, now: float | None = None) -> list[dict]:
        """Confronte une phrase aux compteurs actifs et incrémente ceux qui matchent.

        Retourne les compteurs touchés — l'appelant décide quoi en montrer.
        """
        text = _normalize(text)
        if not text.strip():
            return []
        now = time.time() if now is None else now
        touched: list[dict] = []
        for row in await self.list(active_only=True):
            if now - self._last_hit.get(row["id"], 0.0) < _MIN_INTERVAL_S:
                continue
            try:
                keywords = json.loads(row["keywords"])
            except (json.JSONDecodeError, TypeError):
                continue
            # Bornes explicites : « lag » ne doit pas compter « village ».
            if not any(f" {k} " in text for k in keywords):
                continue
            self._last_hit[row["id"]] = now
            await self._db.execute(
                "UPDATE tally_counters SET count = count + 1, last_hit_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            touched.append({**row, "count": row["count"] + 1})
            logger.info("Tally: « {l} » → {n}", l=row["label"], n=row["count"] + 1)
        return touched
