from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

public_router = APIRouter()


@public_router.get("/cognitive/state")
async def cognitive_state(request: Request):
    feed = getattr(request.app.state.wally, "cognitive_feed", None)
    if feed is None:
        return {"events": []}
    return {"events": feed.snapshot()}


@public_router.get("/cognitive/history")
async def cognitive_history(request: Request, limit: int = 50, before: int | None = None):
    """Historique persistant du flux cognitif (#observability A6), paginé.
    `next_before` = plus petit id de la page → à repasser pour la page suivante."""
    store = getattr(request.app.state.wally, "cognitive_event_store", None)
    if store is None:
        return {"events": [], "next_before": None}
    limit = max(1, min(limit, 200))
    events = await store.recent(limit=limit, before_id=before)
    next_before = events[-1]["id"] if events else None
    return {"events": events, "next_before": next_before}


@public_router.get("/cognitive/goal")
async def cognitive_goal(request: Request):
    """But(s) courant(s) de Wally + préoccupation + désirs actifs (#observability A7)."""
    store = getattr(request.app.state.wally, "fact_store", None)
    if store is None:
        return {"goals": [], "preoccupation": None, "desires": []}
    from bot.intelligence.memory.facts import FactCategory, FactStatus
    goals = await store.search_by_category(FactCategory.GOAL, status=FactStatus.ACTIVE, limit=5)
    desires = await store.search_by_category(FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=5)
    focus = await store.get_latest_by_source("wally:self", "focus")
    return {
        "goals": [g.content for g in goals],
        "preoccupation": focus.content if focus else None,
        "desires": [d.content for d in desires],
    }


@public_router.get("/sse/cognitive")
async def cognitive_sse(request: Request):
    feed = getattr(request.app.state.wally, "cognitive_feed", None)

    async def gen():
        if feed is None:
            yield ": no-feed\n\n"
            return
        q = feed.subscribe()
        try:
            for evt in feed.snapshot():
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            feed.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
