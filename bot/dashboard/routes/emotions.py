# bot/dashboard/routes/emotions.py
from __future__ import annotations

import time as _time

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from bot.core.emotion import EMOTIONS

public_router = APIRouter()
admin_router = APIRouter()


@public_router.get("/emotions")
async def get_emotions_public(request: Request) -> dict:
    return request.app.state.wally.emotion.get_state()


@public_router.get("/emotions/history")
async def get_emotions_history(
    request: Request,
    since: float = Query(default=None),
) -> dict:
    state = request.app.state.wally
    if since is None:
        since = _time.time() - 86400
    # Cap à 30 jours maximum
    since = max(since, _time.time() - 30 * 86400)
    snapshots = await state.db.get_emotion_snapshots_since(since)
    return {"history": snapshots}


@admin_router.get("/emotions")
async def get_emotions_admin(request: Request) -> dict:
    return request.app.state.wally.emotion.get_state()


class SetEmotionBody(BaseModel):
    emotion: str
    value: float


@admin_router.post("/emotions/set")
async def set_emotion(request: Request, body: SetEmotionBody) -> dict:
    state = request.app.state.wally
    if body.emotion not in EMOTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown emotion: {body.emotion}")
    if not 0.0 <= body.value <= 1.0:
        raise HTTPException(status_code=400, detail="value must be 0.0–1.0")
    state.emotion.set_emotion(body.emotion, body.value)
    return {"status": "ok", "emotion": body.emotion, "value": body.value}


@admin_router.post("/emotions/reset")
async def reset_emotions(request: Request) -> dict:
    """Reset toutes les émotions à 0.5 (neutre).
    Appelle set_emotion() pour chaque émotion — NE PAS utiliser emotion.reset()
    qui remet à 0.0.
    """
    state = request.app.state.wally
    for emotion in EMOTIONS:
        state.emotion.set_emotion(emotion, 0.5)
    return {"status": "ok", "message": "All emotions reset to 0.5 (neutral)"}
