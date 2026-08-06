# bot/dashboard/routes/overlay.py
"""Routes de l'overlay de stream : télémétrie de rendu + déclencheur de test.

La télémétrie vient de l'overlay lui-même (fps, pire frame, GPU) : c'est la
seule mesure possible côté page — l'usage GPU système est illisible depuis un
navigateur, et la vraie validation reste les stats OBS chez le streamer.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

public_router = APIRouter()
admin_router = APIRouter()

# Bornes défensives : la télémétrie vient d'une page publique non authentifiée,
# on ne stocke que des valeurs plausibles et une seule entrée (pas de liste qui
# grossit sous des POST hostiles).
_MAX_GPU_LEN = 120


@public_router.post("/overlay-health")
async def overlay_health(request: Request) -> dict:
    """Reçoit la télémétrie de rendu envoyée toutes les 10 s par l'overlay."""
    state = request.app.state.wally
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")
    fps = data.get("fps")
    worst = data.get("worst_frame_ms")
    if not isinstance(fps, (int, float)) or not isinstance(worst, (int, float)):
        raise HTTPException(400, "fps et worst_frame_ms requis")
    state.overlay_health = {
        "fps": max(0, min(240, int(fps))),
        "worst_frame_ms": max(0, min(10_000, int(worst))),
        "gpu": str(data.get("gpu", ""))[:_MAX_GPU_LEN],
        "at": time.time(),
    }
    return {"ok": True}


@admin_router.get("/overlay/health")
async def get_overlay_health(request: Request) -> dict:
    """Dernière télémétrie reçue — visible depuis le dashboard, sans rien
    demander au streamer pendant qu'il joue."""
    health = getattr(request.app.state.wally, "overlay_health", None)
    if not health:
        return {"connected": False}
    # Au-delà de 30 s sans nouvelle (émission toutes les 10 s), l'overlay est
    # considéré déconnecté.
    return {"connected": time.time() - health["at"] < 30, **health}


@admin_router.post("/overlay/test")
async def overlay_test(request: Request) -> dict:
    """Publie un événement de test sur l'overlay (réglage visuel sans attendre
    un vrai événement de stream)."""
    state = request.app.state.wally
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")
    kind = data.get("type", "bubble")
    if kind == "bubble":
        text = (data.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "text requis")
        state.overlay_feed.say(text, mode=data.get("mode", "speech"))
    elif kind == "thinking":
        state.overlay_feed.thinking(bool(data.get("active", True)))
    elif kind == "react":
        state.overlay_feed.react(str(data.get("kind", "test")))
    elif kind == "widget":
        widget = str(data.get("widget") or "").strip()
        if not widget:
            raise HTTPException(400, "widget requis")
        params = data.get("params")
        state.overlay_feed.widget(widget, **(params if isinstance(params, dict) else {}))
    else:
        raise HTTPException(400, f"type inconnu: {kind}")
    return {"ok": True, "subscribers": state.overlay_feed.subscriber_count}
