from __future__ import annotations

import time
from typing import TYPE_CHECKING

import aiosqlite
from loguru import logger


class EmotionMixin:
    _conn: aiosqlite.Connection

    # Declared for type checking (implemented in Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Emotion persistence ───────────────────────────────────────────────────

    async def load_emotion_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_state")
        return {row["emotion"]: float(row["value"]) for row in rows}

    async def save_emotion_state(self, state: dict[str, float]) -> None:
        if not state:
            return
        now = time.time()
        query = (
            "INSERT INTO emotion_state (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
        )
        params = [(emotion, value, now) for emotion, value in state.items()]
        await self._conn.executemany(query, params)
        await self._conn.commit()

    async def insert_emotion_snapshot(self, state: dict[str, float]) -> None:
        await self.execute(
            "INSERT INTO emotion_history "
            "(snapshot_at, anger, joy, sadness, curiosity, boredom) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                state.get("anger", 0.0),
                state.get("joy", 0.0),
                state.get("sadness", 0.0),
                state.get("curiosity", 0.0),
                state.get("boredom", 0.0),
            ),
        )

    async def get_emotion_snapshots_since(self, since: float) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT * FROM emotion_history WHERE snapshot_at >= ? ORDER BY snapshot_at ASC",
            (since,),
        )
        return [dict(row) for row in rows]

    async def cleanup_old_emotion_history(self, days: int = 7) -> None:
        cutoff = time.time() - days * 86400
        await self.execute(
            "DELETE FROM emotion_history WHERE snapshot_at < ?",
            (cutoff,),
        )

    # ── Emotional memory & mood/fatigue persistence ──────────────────────────────

    async def upsert_emotional_memory(
        self, user_id: str, platform: str, emotion: str, affinity: float, interaction_count: int,
    ) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        await self.execute(
            "INSERT INTO emotional_memory (user_id, platform, emotion, affinity, interaction_count, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, platform, emotion) DO UPDATE SET "
            "affinity=excluded.affinity, interaction_count=excluded.interaction_count, last_updated=excluded.last_updated",
            (user_id, platform, emotion, affinity, interaction_count, now),
        )

    async def get_emotional_memory(self, user_id: str, platform: str) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT emotion, affinity, interaction_count, last_updated "
            "FROM emotional_memory WHERE user_id = ? AND platform = ?",
            (user_id, platform),
        )
        return [dict(r) for r in rows]

    async def save_mood_state(self, state: dict[str, float]) -> None:
        now = time.time()
        query = (
            "INSERT INTO emotion_mood (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
        )
        params = [(e, v, now) for e, v in state.items()]
        await self._conn.executemany(query, params)
        await self._conn.commit()

    async def load_mood_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_mood")
        return {row["emotion"]: float(row["value"]) for row in rows}

    async def save_fatigue_state(self, state: dict[str, float]) -> None:
        now = time.time()
        query = (
            "INSERT INTO emotion_fatigue (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
        )
        params = [(e, v, now) for e, v in state.items()]
        await self._conn.executemany(query, params)
        await self._conn.commit()

    async def load_fatigue_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_fatigue")
        return {row["emotion"]: float(row["value"]) for row in rows}

    # ── Emotion peaks ──────────────────────────────────────────────────────

    async def insert_emotion_peak(
        self, timestamp: float, emotion: str, value: float,
        trigger_user: str = "", trigger_message: str = "",
        channel_id: str = "", platform: str = "",
    ) -> None:
        await self.execute(
            "INSERT INTO emotion_peaks "
            "(timestamp, emotion, value, trigger_user, trigger_message, channel_id, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp, emotion, value, trigger_user, trigger_message, channel_id, platform),
        )

    async def get_emotion_peaks_since(self, since: float) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT timestamp, emotion, value, trigger_user, trigger_message, channel_id, platform "
            "FROM emotion_peaks WHERE timestamp >= ? ORDER BY timestamp ASC",
            (since,),
        )
        return [
            {
                "timestamp": float(r["timestamp"]),
                "emotion": r["emotion"],
                "value": float(r["value"]),
                "trigger_user": r["trigger_user"],
                "trigger_message": r["trigger_message"],
                "channel_id": r["channel_id"],
                "platform": r["platform"],
            }
            for r in rows
        ]

    # ── Emotion averages ──────────────────────────────────────────────────

    async def get_emotion_averages(self, since: float) -> dict | None:
        row = await self.fetch_one(
            "SELECT AVG(anger) AS anger, AVG(joy) AS joy, AVG(sadness) AS sadness, "
            "AVG(curiosity) AS curiosity, AVG(boredom) AS boredom "
            "FROM emotion_history WHERE snapshot_at >= ?",
            (since,),
        )
        if row is None or row["anger"] is None:
            return None
        return {
            "anger": float(row["anger"]),
            "joy": float(row["joy"]),
            "sadness": float(row["sadness"]),
            "curiosity": float(row["curiosity"]),
            "boredom": float(row["boredom"]),
        }
