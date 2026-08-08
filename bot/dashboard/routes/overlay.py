# bot/dashboard/routes/overlay.py
"""Routes de l'overlay de stream : télémétrie de rendu + déclencheur de test.

La télémétrie vient de l'overlay lui-même (fps, pire frame, GPU) : c'est la
seule mesure possible côté page — l'usage GPU système est illisible depuis un
navigateur, et la vraie validation reste les stats OBS chez le streamer.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

public_router = APIRouter()
admin_router = APIRouter()

# Bornes défensives : la télémétrie vient d'une page publique non authentifiée,
# on ne stocke que des valeurs plausibles et une seule entrée (pas de liste qui
# grossit sous des POST hostiles).
_MAX_GPU_LEN = 120


# Empreinte des fichiers réellement servis. `static/` est bind-monté : une
# modification est visible sans rebuild, mais OBS garde sa page en mémoire des
# heures. L'overlay interroge donc cette version et se recharge tout seul.
_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_OVERLAY_FILES = ("overlay.html", "overlay.js")
_version_cache: dict = {"stamp": None, "value": "0"}


def overlay_version() -> str:
    """Empreinte courte du contenu de l'overlay.

    Basée sur le CONTENU et non sur la date : un `touch`, un redéploiement à
    l'identique ou un simple redémarrage ne doivent pas provoquer de
    rechargement en plein live.
    """
    try:
        stamp = tuple(
            (_STATIC_DIR / name).stat().st_mtime_ns for name in _OVERLAY_FILES
        )
    except OSError:
        return _version_cache["value"]
    if stamp == _version_cache["stamp"]:
        return _version_cache["value"]
    digest = hashlib.sha1()
    for name in _OVERLAY_FILES:
        try:
            digest.update((_STATIC_DIR / name).read_bytes())
        except OSError:
            pass
    _version_cache.update(stamp=stamp, value=digest.hexdigest()[:10])
    return _version_cache["value"]


@public_router.get("/meme/{name}")
async def get_meme(name: str, request: Request):
    """Sert une image du dossier des memes.

    Publique parce que l'overlay tourne dans OBS sans session. `resolve` refuse
    tout nom qui sortirait du dossier — c'est la seule barrière, elle est donc
    stricte.
    """
    library = getattr(request.app.state.wally, "memes", None)
    if library is None:
        raise HTTPException(404, "Aucune bibliothèque de memes")
    path = library.resolve(name)
    if path is None:
        raise HTTPException(404, "Meme introuvable")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})


@public_router.get("/overlay-version")
async def get_overlay_version() -> dict:
    """Version courante — l'overlay la compare à la sienne toutes les 30 s."""
    return {"version": overlay_version()}


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


def _narrator(request: Request):
    """Le narrateur est construit avec le bot Discord : absent avant sa connexion."""
    narrator = getattr(
        getattr(request.app.state.wally, "discord_bot", None), "overlay_narrator", None
    )
    if narrator is None:
        raise HTTPException(503, "Narrateur d'overlay indisponible")
    return narrator


@admin_router.get("/overlay/force-live")
async def get_force_live(request: Request) -> dict:
    """Minutes restantes de mode test — le bouton du panneau reflète l'état réel,
    y compris quand l'échéance est tombée toute seule."""
    narrator = _narrator(request)
    remaining = narrator.force_live_remaining()
    return {"active": remaining > 0, "remaining_minutes": round(remaining, 1)}


@admin_router.post("/overlay/force-live")
async def set_force_live(request: Request) -> dict:
    """Active (ou coupe) le mode test hors live.

    Toujours borné dans le temps : oublié actif, il ferait parler Wally dans le
    vide à un appel LLM la bulle.
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    if data.get("active") is False:
        minutes = 0.0
    else:
        try:
            minutes = float(data.get("minutes", 30))
        except (TypeError, ValueError):
            raise HTTPException(400, "minutes invalide")
    narrator = _narrator(request)
    granted = narrator.force_live(minutes)
    # Rangé tout de suite : un rebuild peut arriver dans la minute, et c'est
    # précisément entre deux déploiements qu'on se sert du mode test.
    await narrator.flush_force_live()
    return {"active": granted > 0, "remaining_minutes": round(granted, 1)}


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
