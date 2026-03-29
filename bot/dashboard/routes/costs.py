# bot/dashboard/routes/costs.py
"""Routes admin pour les coûts OpenAI du dashboard."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Request

router = APIRouter()

# Cache simple TTL pour costs_top_users (évite les fetch Discord API répétitifs)
_top_users_cache: dict[str, tuple[float, list]] = {}  # key → (expires_at, data)
_TOP_USERS_TTL = 300  # 5 minutes

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

PURPOSE_FEATURE_MAP: dict[str, str] = {
    "discord_response": "Réponses",
    "discord_spontaneous": "Réponses",
    "discord_ask": "Réponses",
    "twitch_response": "Réponses",
    "twitch_spontaneous": "Réponses",
    "twitch_event": "Réponses",
    "web_response": "Réponses",
    "daily_journal": "Journal",
    "journal_chunk_summary": "Journal",
    "journal_final_summary": "Journal",
    "opinion_formation": "Journal",
    "image_generation": "Images",
    "image_title": "Images",
    "image_description": "Images",
    "emotion_analysis": "Émotions",
    "fact_extraction": "Mémoire",
    "memory_consolidation": "Mémoire",
    "memory_evaluate": "Mémoire",
    "context_summary": "Mémoire",
    "context_summary_final": "Mémoire",
    "memory_cleanup": "Mémoire",
    "embedding": "Mémoire",
    "spam_warning": "Système",
    "reminder": "Système",
    "twitch_visit_summary": "Système",
    "twitch_overlay_announce": "Système",
}


def _clamp_days(days: int) -> int:
    return max(1, min(days, 365))


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
    prev = await db.get_cost_stats(prev_start, month_start)

    total = current["total"]
    count = current["count"]
    avg = round(total / count, 6) if count > 0 else 0.0
    prev_total = prev["total"]
    pct_change = round((total - prev_total) / prev_total * 100, 2) if prev_total > 0 else 0.0

    # Prévision fin de mois basée sur la moyenne quotidienne
    now = datetime.now()
    days_elapsed = now.day
    days_in_month = (now.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1)).day if now.month < 12 else 31
    daily_avg = total / days_elapsed if days_elapsed > 0 else 0.0
    forecast = round(daily_avg * days_in_month, 4)

    return {
        "total": total,
        "avg_per_msg": avg,
        "msg_count": count,
        "prev_total": prev_total,
        "pct_change": pct_change,
        "forecast": forecast,
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
    }


@router.get("/costs/daily")
async def costs_daily(request: Request, days: int = 30) -> dict:
    days = _clamp_days(days)
    db = request.app.state.wally.db
    current = await db.get_daily_costs(_since_ts(days))
    previous = await db.get_daily_costs(_since_ts(days * 2), _since_ts(days))
    return {"current": current, "previous": previous}


@router.get("/costs/breakdown/model")
async def costs_breakdown_model(request: Request, days: int = 30) -> list:
    days = _clamp_days(days)
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "model")
    return [{"model": r["key"], "total": r["total"], "count": r["count"]} for r in rows]


@router.get("/costs/breakdown/purpose")
async def costs_breakdown_purpose(request: Request, days: int = 30) -> list:
    days = _clamp_days(days)
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


def _friendly_name(uid: str | None, username_map: dict[str, str]) -> str:
    """Résout un user_id en nom lisible pour l'affichage."""
    if uid is None:
        return "Système"
    # Nom résolu depuis memory_users
    if uid in username_map:
        return username_map[uid]
    # Extraire la partie lisible depuis "platform:name_or_id"
    parts = uid.split(":", 1)
    if len(parts) == 2:
        platform, raw = parts
        if not raw.isdigit():
            return raw  # twitch:KingsRequin → KingsRequin
    return uid


@router.get("/costs/top-users")
async def costs_top_users(request: Request, days: int = 30, limit: int = 10) -> list:
    days = _clamp_days(days)
    limit = max(1, min(limit, 100))

    cache_key = f"{days}:{limit}"
    cached = _top_users_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]

    state = request.app.state.wally
    db = state.db
    rows = await db.get_cost_breakdown(_since_ts(days), "user_id")

    all_users = await db.list_memory_users()
    username_map = {u["user_id"]: u["username"] for u in all_users if u.get("username")}

    # Résolution à la volée des Discord IDs sans username via le bot Discord
    discord_bot = getattr(state, "discord_bot", None)
    top_rows = rows[:limit]
    if discord_bot is not None:
        for r in top_rows:
            uid = r["key"]
            if uid and uid.startswith("discord:") and uid not in username_map:
                raw_id = uid.split(":", 1)[1]
                if raw_id.isdigit():
                    try:
                        discord_user = await discord_bot.fetch_user(int(raw_id))
                        name = discord_user.display_name or discord_user.name
                        if name:
                            username_map[uid] = name
                            await db.upsert_memory_user(uid, "discord", username=name)
                    except Exception:
                        pass

    result = []
    for r in top_rows:
        uid = r["key"]
        result.append({
            "user_id": uid,
            "username": _friendly_name(uid, username_map),
            "total": r["total"],
            "count": r["count"],
        })

    _top_users_cache[cache_key] = (time.time() + _TOP_USERS_TTL, result)
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


@router.get("/costs/by-feature")
async def costs_by_feature(request: Request, days: int = 30) -> list:
    days = _clamp_days(days)
    db = request.app.state.wally.db
    rows = await db.get_cost_breakdown(_since_ts(days), "purpose")
    features: dict[str, dict] = {}
    grand_total = sum(r["total"] for r in rows)
    for r in rows:
        feat = PURPOSE_FEATURE_MAP.get(r["key"] or "", "Autre")
        if feat not in features:
            features[feat] = {"feature": feat, "cost": 0.0, "count": 0}
        features[feat]["cost"] = round(features[feat]["cost"] + r["total"], 6)
        features[feat]["count"] += r["count"]
    result = sorted(features.values(), key=lambda x: x["cost"], reverse=True)
    for item in result:
        item["pct"] = round(item["cost"] / grand_total * 100, 1) if grand_total > 0 else 0.0
    return result


@router.get("/costs/prices")
async def costs_prices(request: Request) -> dict:
    from bot.core.llm.openai_client import MODEL_COSTS
    from bot.core.llm.claude_client import CLAUDE_MODEL_COSTS
    result: dict[str, dict] = {}
    for model, (inp, out) in MODEL_COSTS.items():
        result[model] = {"input_per_1k": round(inp / 1000, 8), "output_per_1k": round(out / 1000, 8)}
    for model, (inp, out) in CLAUDE_MODEL_COSTS.items():
        result[model] = {"input_per_1k": round(inp / 1000, 8), "output_per_1k": round(out / 1000, 8)}
    return result


@router.get("/costs/logs")
async def costs_logs(request: Request, days: int = 30, page: int = 1, limit: int = 50) -> dict:
    days = _clamp_days(days)
    limit = max(1, min(limit, 200))
    page = max(1, page)
    db = request.app.state.wally.db
    return await db.get_cost_logs_paginated(_since_ts(days), page=page, limit=limit)
