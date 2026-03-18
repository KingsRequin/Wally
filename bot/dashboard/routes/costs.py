# bot/dashboard/routes/costs.py
"""Routes admin pour les coûts OpenAI du dashboard."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Request

router = APIRouter()

PURPOSE_CATEGORIES = {
    "discord_response": "Réponses",
    "discord_ask": "Réponses",
    "twitch_response": "Réponses",
    "twitch_event": "Réponses",
    "session_analysis": "Analyse",
    "emotion_analysis": "Analyse",
    "memory_consolidation": "Mémoire",
    "context_summary": "Mémoire",
    "context_summary_final": "Mémoire",
    "daily_journal": "Journal",
    "journal_chunk_summary": "Journal",
    "journal_final_summary": "Journal",
}


def _since_ts(days: int) -> float:
    """Timestamp Unix il y a N jours."""
    return time.time() - days * 86400


@router.get("/costs/summary")
async def costs_summary(request: Request) -> dict:
    db = request.app.state.wally.db
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

    current = await db.get_cost_stats(month_start)
    # Mois précédent
    prev_start = (datetime.now().replace(day=1) - timedelta(days=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    prev = await db.get_cost_stats(prev_start)

    total = current["total"]
    count = current["count"]
    avg = round(total / count, 6) if count > 0 else 0.0
    prev_total = prev["total"]
    pct_change = round((total - prev_total) / prev_total * 100, 2) if prev_total > 0 else 0.0

    return {
        "total": total,
        "avg_per_msg": avg,
        "msg_count": count,
        "prev_total": prev_total,
        "pct_change": pct_change,
    }


@router.get("/costs/daily")
async def costs_daily(request: Request, days: int = 30) -> dict:
    db = request.app.state.wally.db
    current = await db.get_daily_costs(_since_ts(days))
    previous = await db.get_daily_costs(_since_ts(days * 2), _since_ts(days))
    return {"current": current, "previous": previous}


@router.get("/costs/breakdown/model")
async def costs_breakdown_model(request: Request, days: int = 30) -> list:
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "model")
    return [{"model": r["key"], "total": r["total"], "count": r["count"]} for r in rows]


@router.get("/costs/breakdown/purpose")
async def costs_breakdown_purpose(request: Request, days: int = 30) -> list:
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "purpose")
    categories: dict[str, dict] = {}
    for r in rows:
        cat = PURPOSE_CATEGORIES.get(r["key"] or "", "Autre")
        if cat not in categories:
            categories[cat] = {"category": cat, "total": 0.0, "count": 0}
        categories[cat]["total"] = round(categories[cat]["total"] + r["total"], 6)
        categories[cat]["count"] += r["count"]
    return sorted(categories.values(), key=lambda x: x["total"], reverse=True)


@router.get("/costs/top-users")
async def costs_top_users(request: Request, days: int = 30, limit: int = 10) -> list:
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "user_id")

    all_users = await db.list_memory_users()
    username_map = {u["user_id"]: u["username"] for u in all_users if u.get("username")}

    result = []
    for r in rows[:limit]:
        uid = r["key"]
        if uid is None:
            username = "Système"
        else:
            username = username_map.get(uid) or uid
        result.append({
            "user_id": uid,
            "username": username,
            "total": r["total"],
            "count": r["count"],
        })
    return result


@router.get("/costs/alert")
async def costs_alert(request: Request) -> dict:
    state = request.app.state.wally
    threshold = state.config.bot.cost_alert_threshold
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    stats = await state.db.get_cost_stats(month_start)

    current = stats["total"]
    pct = round(current / threshold * 100, 1) if threshold > 0 else 0.0
    if pct >= 80:
        status = "critical"
    elif pct >= 60:
        status = "warning"
    else:
        status = "ok"

    return {
        "threshold": threshold,
        "current_total": current,
        "pct_used": pct,
        "status": status,
    }
