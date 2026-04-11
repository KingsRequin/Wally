from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import aiosqlite
from loguru import logger

_TZ_COSTS = ZoneInfo("Europe/Paris")


class CostMixin:
    _conn: aiosqlite.Connection

    # Declared for type checking (implemented in Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Cost tracking ────────────────────────────────────────────────────────

    async def log_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        purpose: str = "",
        user_id: str | None = None,
    ):
        await self.execute(
            "INSERT INTO cost_log "
            "(timestamp, model, input_tokens, output_tokens, cost_usd, purpose, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), model, input_tokens, output_tokens, cost_usd, purpose, user_id),
        )

    async def get_cost_since(self, since_timestamp: float) -> float:
        row = await self.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total "
            "FROM cost_log WHERE timestamp >= ?",
            (since_timestamp,),
        )
        return float(row["total"]) if row else 0.0

    async def get_daily_costs(self, since_ts: float, until_ts: float | None = None) -> list[dict]:
        """Couts agreges par jour (date ISO, cost_usd total)."""
        end = until_ts or time.time()
        rows = await self.fetch_all(
            "SELECT DATE(timestamp, 'unixepoch', 'localtime') AS date, "
            "SUM(cost_usd) AS cost "
            "FROM cost_log WHERE timestamp >= ? AND timestamp <= ? "
            "GROUP BY date ORDER BY date ASC",
            (since_ts, end),
        )
        return [{"date": r["date"], "cost": round(float(r["cost"]), 6)} for r in rows]

    async def get_cost_breakdown(self, since_ts: float, group_by: str) -> list[dict]:
        """Agrege les couts par model, purpose, ou user_id."""
        allowed = {"model", "purpose", "user_id"}
        if group_by not in allowed:
            raise ValueError(f"group_by must be one of {allowed}")
        rows = await self.fetch_all(
            f"SELECT {group_by} AS grp, SUM(cost_usd) AS total, COUNT(*) AS count "
            f"FROM cost_log WHERE timestamp >= ? "
            f"GROUP BY {group_by} ORDER BY total DESC",
            (since_ts,),
        )
        return [
            {"key": r["grp"], "total": round(float(r["total"]), 6), "count": int(r["count"])}
            for r in rows
        ]

    async def get_cost_stats(self, since_ts: float, until_ts: float | None = None) -> dict:
        """Total et nombre d'appels entre since_ts et until_ts."""
        if until_ts is not None:
            row = await self.fetch_one(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS count "
                "FROM cost_log WHERE timestamp >= ? AND timestamp < ?",
                (since_ts, until_ts),
            )
        else:
            row = await self.fetch_one(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS count "
                "FROM cost_log WHERE timestamp >= ?",
                (since_ts,),
            )
        total = float(row["total"]) if row else 0.0
        count = int(row["count"]) if row else 0
        return {"total": round(total, 6), "count": count}

    async def get_cost_logs_paginated(
        self,
        since_ts: float,
        page: int = 1,
        limit: int = 50,
    ) -> dict:
        """Journal pagine des appels LLM avec resolution username."""
        offset = (page - 1) * limit
        rows = await self.fetch_all(
            "SELECT cl.timestamp, cl.model, cl.input_tokens, cl.output_tokens, "
            "cl.cost_usd, cl.purpose, cl.user_id, mu.username "
            "FROM cost_log cl "
            "LEFT JOIN memory_users mu ON mu.user_id = cl.user_id "
            "WHERE cl.timestamp >= ? "
            "ORDER BY cl.timestamp DESC "
            "LIMIT ? OFFSET ?",
            (since_ts, limit, offset),
        )
        count_row = await self.fetch_one(
            "SELECT COUNT(*) AS n FROM cost_log WHERE timestamp >= ?",
            (since_ts,),
        )
        total = count_row["n"] if count_row else 0
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "logs": [
                {
                    "datetime": datetime.fromtimestamp(r["timestamp"], tz=_TZ_COSTS).strftime("%Y-%m-%d %H:%M:%S"),
                    "model": r["model"] or "",
                    "input_tokens": r["input_tokens"] or 0,
                    "output_tokens": r["output_tokens"] or 0,
                    "cost_usd": round(float(r["cost_usd"]), 6),
                    "purpose": r["purpose"] or "",
                    "user_id": r["user_id"] or "",
                    "username": r["username"] or "",
                }
                for r in rows
            ],
        }
