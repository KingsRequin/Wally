"""Routes admin de suivi/debug du pipeline vocal : live SSE + historique persistant."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

admin_router = APIRouter()


@admin_router.get("/voice/history")
async def voice_history(request: Request, limit: int = 100, before: int | None = None):
    """Historique persistant du suivi vocal (entendu / réponse / ignoré), paginé.
    `next_before` = plus petit id de la page → à repasser pour la page suivante."""
    store = getattr(request.app.state.wally, "voice_event_store", None)
    if store is None:
        return {"events": [], "next_before": None}
    limit = max(1, min(limit, 300))
    events = await store.recent(limit=limit, before_id=before)
    next_before = events[-1]["id"] if events else None
    return {"events": events, "next_before": next_before}


@admin_router.get("/sse/voice")
async def voice_sse(request: Request):
    feed = getattr(request.app.state.wally, "voice_feed", None)

    async def gen():
        if feed is None:
            yield ": no-feed\n\n"
            return
        # Pas de snapshot ici : le client charge l'historique persistant via /voice/history
        # (avec id), le SSE ne diffuse que le live → pas de doublon.
        q = feed.subscribe()
        try:
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
