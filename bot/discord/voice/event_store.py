"""Historique persistant léger du suivi vocal (table voice_events, rotation par count)."""
from __future__ import annotations

import json
import time

import aiosqlite
from loguru import logger


class VoiceEventStore:
    """Persiste les événements du pipeline vocal (entendu / réponse / ignoré) pour le debug."""

    def __init__(self, db_path: str, cap: int = 1000) -> None:
        self._db_path = db_path
        self._cap = cap

    async def append(self, event: dict) -> None:
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT INTO voice_events (ts, type, payload) VALUES (?, ?, ?)",
                    (time.time(), str(event.get("type", "event")),
                     json.dumps(event, ensure_ascii=False)),
                )
                # Rotation : ne garder que les `cap` derniers ids.
                await db.execute(
                    "DELETE FROM voice_events WHERE id <= "
                    "(SELECT MAX(id) FROM voice_events) - ?",
                    (self._cap,),
                )
                await db.commit()
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            logger.warning("VoiceEventStore.append: {}", e)

    async def recent(self, limit: int = 50, before_id: int | None = None) -> list[dict]:
        sql = "SELECT id, ts, payload FROM voice_events"
        params: list = []
        if before_id is not None:
            sql += " WHERE id < ?"
            params.append(before_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(sql, params)
                rows = await cur.fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("VoiceEventStore.recent: {}", e)
            return []
        out = []
        for r in rows:
            try:
                evt = json.loads(r["payload"])
            except Exception:  # noqa: BLE001
                evt = {"type": "event"}
            evt["id"] = r["id"]
            evt["ts"] = r["ts"]
            out.append(evt)
        return out
