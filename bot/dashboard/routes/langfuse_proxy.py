"""Langfuse integration — stats aggregation + config endpoint."""
from __future__ import annotations

import os
from asyncio import gather
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from loguru import logger

router = APIRouter()

LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_EXTERNAL_URL = os.getenv("LANGFUSE_EXTERNAL_URL", "").rstrip("/")


@router.get("/langfuse-config", include_in_schema=False)
async def langfuse_config() -> JSONResponse:
    """Retourne l'URL externe Langfuse configurée."""
    return JSONResponse({"url": LANGFUSE_EXTERNAL_URL or None})


@router.get("/langfuse-stats", include_in_schema=False)
async def langfuse_stats(request: Request, days: int = 7) -> JSONResponse:
    """Agrège traces, coûts, métriques depuis l'API Langfuse."""
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return JSONResponse({"error": "Langfuse keys not configured"}, status_code=503)

    base = f"{LANGFUSE_HOST}/api/public"
    auth = (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)

    try:
        async with httpx.AsyncClient(auth=auth, timeout=15.0) as client:
            metrics_resp, tp1, tp2 = await gather(
                client.get(f"{base}/metrics/daily"),
                client.get(f"{base}/traces", params={"limit": 100, "page": 1}),
                client.get(f"{base}/traces", params={"limit": 100, "page": 2}),
            )

            metrics_resp.raise_for_status()
            tp1.raise_for_status()

            daily_raw = metrics_resp.json().get("data", [])
            traces_raw = tp1.json().get("data", [])
            if tp2.status_code == 200:
                traces_raw += tp2.json().get("data", [])
            elif tp2.status_code not in (404, 204):
                logger.debug("Langfuse traces page 2 returned {code}", code=tp2.status_code)

    except Exception as exc:
        logger.warning("Langfuse stats fetch error: {e}", e=exc)
        return JSONResponse({"error": f"Langfuse unavailable: {exc}"}, status_code=502)

    # ── Filter to requested day range ────────────────────────────────────
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    daily = [d for d in daily_raw if d.get("date", "") >= cutoff]

    # ── Summary ──────────────────────────────────────────────────────────
    total_cost = sum(d.get("totalCost", 0) or 0 for d in daily)
    total_traces = sum(d.get("countTraces", 0) or 0 for d in daily)
    total_observations = sum(d.get("countObservations", 0) or 0 for d in daily)

    total_input_tokens = 0
    total_output_tokens = 0
    model_agg: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    )

    for day in daily:
        for u in day.get("usage", []):
            model = u.get("model") or "unknown"
            inp = u.get("inputUsage", 0) or 0
            out = u.get("outputUsage", 0) or 0
            cost = u.get("totalCost", 0) or 0
            count = u.get("countObservations", 0) or 0

            total_input_tokens += inp
            total_output_tokens += out

            model_agg[model]["count"] += count
            model_agg[model]["cost"] += cost
            model_agg[model]["input_tokens"] += inp
            model_agg[model]["output_tokens"] += out

    # ── Average latency from recent traces ───────────────────────────────
    latencies = [t["latency"] for t in traces_raw if t.get("latency")]
    avg_latency_ms = round((sum(latencies) / len(latencies)) * 1000) if latencies else 0

    # ── By model (sorted by cost desc) ───────────────────────────────────
    by_model = sorted(
        [
            {"model": m, **v, "cost": round(v["cost"], 6)}
            for m, v in model_agg.items()
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )

    # ── By day (sorted chronologically) ──────────────────────────────────
    by_day = sorted(
        [
            {
                "date": d["date"],
                "cost": round(d.get("totalCost", 0) or 0, 6),
                "traces": d.get("countTraces", 0) or 0,
            }
            for d in daily
        ],
        key=lambda x: x["date"],
    )

    # ── Top users (from traces, grouped by userId) ───────────────────────
    user_agg: dict[str, dict] = defaultdict(lambda: {"traces": 0, "cost": 0.0})
    for t in traces_raw:
        uid = t.get("userId")
        if not uid:
            continue
        ts = t.get("timestamp", "")
        if ts[:10] >= cutoff:
            user_agg[uid]["traces"] += 1
            user_agg[uid]["cost"] += t.get("totalCost", 0) or 0

    # Resolve display names from DB (memory_users schema: user_id, username)
    db = getattr(request.app.state, "wally", None)
    db_ref = getattr(db, "db", None) if db else None
    user_names: dict[str, str] = {}
    if db_ref:
        try:
            rows = await db_ref.fetch_all(
                "SELECT user_id, username FROM memory_users"
            )
            for row in rows:
                uid = row["user_id"]
                name = row["username"] or uid.split(":")[-1]
                user_names[uid] = name
        except Exception as exc:
            logger.debug("Langfuse stats: failed to resolve user names: {e}", e=exc)

    top_users = sorted(
        [
            {
                "user_id": uid,
                "display_name": user_names.get(uid, uid.split(":")[-1] if ":" in uid else uid),
                "traces": v["traces"],
                "cost": round(v["cost"], 6),
            }
            for uid, v in user_agg.items()
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )[:10]

    # ── Recent traces (last 20) ──────────────────────────────────────────
    recent_traces = []
    for t in traces_raw[:20]:
        recent_traces.append({
            "id": t.get("id"),
            "name": t.get("name", ""),
            "user_id": t.get("userId", ""),
            "cost": round(t.get("totalCost", 0) or 0, 6),
            "latency_ms": round((t.get("latency") or 0) * 1000),
            "timestamp": t.get("timestamp", ""),
            "tags": t.get("tags", []),
        })

    return JSONResponse({
        "summary": {
            "total_cost": round(total_cost, 4),
            "total_traces": total_traces,
            "total_observations": total_observations,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "avg_latency_ms": avg_latency_ms,
        },
        "by_model": by_model,
        "by_day": by_day,
        "top_users": top_users,
        "recent_traces": recent_traces,
        "external_url": LANGFUSE_EXTERNAL_URL or None,
        "days": days,
    })
