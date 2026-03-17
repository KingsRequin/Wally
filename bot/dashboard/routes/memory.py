# bot/dashboard/routes/memory.py
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

router = APIRouter()


def _get_mem0(request: Request):
    """Initialise mem0 si besoin et retourne l'objet, ou lève 503."""
    state = request.app.state.wally
    state.memory._init_mem0()
    if state.memory._mem0 is None:
        raise HTTPException(503, detail="mem0 not available")
    return state.memory._mem0


def _unwrap(results) -> list:
    """Unwrap mem0 >= 0.1.40 qui retourne {"results": [...]} au lieu d'une liste."""
    if isinstance(results, dict):
        return results.get("results", [])
    return results if results else []


# ── GET /memory/users ─────────────────────────────────────────────────────────

@router.get("/memory/users")
async def list_users(request: Request, q: str | None = None):
    state = request.app.state.wally
    users = await state.db.list_memory_users(q)
    return {"users": users}


# ── GET /memory/users/{user_id} ───────────────────────────────────────────────

@router.get("/memory/users/{user_id}")
async def get_user_memories(user_id: str, request: Request):
    mem0 = _get_mem0(request)
    results = await asyncio.to_thread(mem0.get_all, user_id=user_id)
    memories = [
        {"id": r.get("id"), "memory": r.get("memory", "")}
        for r in _unwrap(results)
        if r.get("memory")
    ]
    return {"user_id": user_id, "memories": memories}


# ── DELETE /memory/users/{user_id} ────────────────────────────────────────────

@router.delete("/memory/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    state = request.app.state.wally
    mem0 = _get_mem0(request)
    await asyncio.to_thread(mem0.delete_all, user_id=user_id)
    await state.db.execute(
        "DELETE FROM memory_users WHERE user_id = ?", (user_id,)
    )
    return {"deleted": True}


# ── DELETE /memory/users/{user_id}/memories/{memory_id} ──────────────────────

@router.delete("/memory/users/{user_id}/memories/{memory_id}")
async def delete_memory(user_id: str, memory_id: str, request: Request):
    mem0 = _get_mem0(request)
    await asyncio.to_thread(mem0.delete, memory_id)
    return {"deleted": True}


# ── POST /memory/sync ─────────────────────────────────────────────────────────

@router.post("/memory/sync")
async def sync_memory_users(request: Request):
    state = request.app.state.wally
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    n = await state.db.sync_memory_users_from_qdrant(qdrant_url)
    return {"synced": n}


# ── GET /memory/search ────────────────────────────────────────────────────────

@router.get("/memory/search")
async def search_memories(request: Request, q: str | None = None):
    if not q or not q.strip():
        raise HTTPException(400, detail="q parameter required")
    state = request.app.state.wally
    mem0 = _get_mem0(request)

    users = await state.db.list_memory_users()
    username_map = {u["user_id"]: u.get("username") for u in users}

    all_results = []
    for user in users:
        uid = user["user_id"]
        platform = user["platform"]
        try:
            raw = await asyncio.to_thread(mem0.search, q, user_id=uid, limit=3)
            for r in _unwrap(raw):
                if r.get("memory"):
                    all_results.append({
                        "user_id": uid,
                        "username": username_map.get(uid),
                        "platform": platform,
                        "memory": r["memory"],
                        "score": r.get("score", 0.0),
                    })
        except Exception as exc:
            logger.warning("mem0 search failed for {uid}: {e}", uid=uid, e=exc)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": all_results}
