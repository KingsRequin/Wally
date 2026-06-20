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
