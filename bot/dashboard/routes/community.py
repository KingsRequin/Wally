from __future__ import annotations

from fastapi import APIRouter, Request
from loguru import logger

public_router = APIRouter()

_AZRAEL = {"name": "Azrael", "trait": "intouchable", "score": "MAX"}


def _trait(trust: float, love: float) -> str:
    if love >= 0.7:
        return "wholesome"
    if trust >= 0.7:
        return "fiable"
    if trust < 0.3:
        return "sous surveillance"
    return "taquin"


@public_router.get("/community/ranking")
async def community_ranking(request: Request, limit: int = 10):
    """Top viewers par affinité (trust + love). Azrael épinglé MAX."""
    db = request.app.state.wally.db
    try:
        users = await db.list_memory_users()
        pairs, meta = [], []
        for u in users:
            plat = u["platform"]
            raw = str(u["user_id"]).split(":", 1)[-1]
            pairs.append((plat, raw))
            meta.append((u, plat, raw))
        love = await db.get_love_scores_batch(pairs)
        rows = []
        for u, plat, raw in meta:
            name = (u.get("username") or "").strip()
            if not name or name.lower() == "azrael":
                continue
            t = float(u.get("trust_score") or 0.0)
            lv = float(love.get((plat, raw), 0.0))
            rows.append({"name": name, "trait": _trait(t, lv), "score": round((t + lv) * 500)})
        rows.sort(key=lambda r: r["score"], reverse=True)
        rows = rows[:limit]
    except Exception as e:  # never 500 the public page
        logger.warning("community/ranking failed: {}", e)
        rows = []
    return {"ranking": [*rows, _AZRAEL]}
