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

    # Récupérer les liaisons acceptées pour fusionner l'affichage
    accepted_links = await state.db.list_link_proposals(status="accepted")

    # alias_id → info du canonical (pour masquer l'alias de la liste)
    alias_set: set[str] = set()
    # canonical_id → liste des alias liés (pour montrer le badge)
    canonical_aliases: dict[str, list[dict]] = {}
    for link in accepted_links:
        alias_set.add(link["alias_id"])
        canonical_aliases.setdefault(link["canonical_id"], []).append({
            "alias_id": link["alias_id"],
            "alias_platform": link["alias_id"].split(":")[0] if ":" in link["alias_id"] else "",
            "alias_username": link["alias_username"]
                or (link["alias_id"].split(":", 1)[1] if ":" in link["alias_id"] else link["alias_id"]),
        })

    # Filtrer les alias de la liste et enrichir le canonical
    merged_users = []
    for user in users:
        if user["user_id"] in alias_set:
            continue  # masquer l'alias, ses mémoires seront vues via le canonical
        aliases = canonical_aliases.get(user["user_id"])
        if aliases:
            user["linked_accounts"] = aliases
        merged_users.append(user)

    return {"users": merged_users}


# ── GET /memory/users/{user_id} ───────────────────────────────────────────────

@router.get("/memory/users/{user_id}")
async def get_user_memories(user_id: str, request: Request):
    state = request.app.state.wally
    mem0 = _get_mem0(request)

    def _extract_origin(r, fallback_source: str) -> str:
        """Extrait la plateforme d'origine depuis le metadata.origin ou le source."""
        origin = (r.get("metadata") or {}).get("origin", "")
        if origin and ":" in origin:
            return origin.split(":")[0]
        return fallback_source.split(":")[0] if ":" in fallback_source else ""

    # Récupérer les mémoires du user principal
    results = await asyncio.to_thread(mem0.get_all, user_id=user_id)
    memories = [
        {
            "id": r.get("id"),
            "memory": r.get("memory", ""),
            "source": user_id,
            "source_platform": _extract_origin(r, user_id),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        }
        for r in _unwrap(results)
        if r.get("memory")
    ]

    # Si cet utilisateur a des alias liés, inclure aussi leurs mémoires
    accepted_links = await state.db.list_link_proposals(status="accepted")
    alias_ids = [
        link["alias_id"] for link in accepted_links
        if link["canonical_id"] == user_id
    ]
    for alias_id in alias_ids:
        try:
            alias_results = await asyncio.to_thread(mem0.get_all, user_id=alias_id)
            for r in _unwrap(alias_results):
                if r.get("memory"):
                    memories.append({
                        "id": r.get("id"),
                        "memory": r.get("memory", ""),
                        "source": alias_id,
                        "source_platform": _extract_origin(r, alias_id),
                        "created_at": r.get("created_at"),
                        "updated_at": r.get("updated_at"),
                    })
        except Exception as exc:
            logger.warning("Échec lecture mémoires alias {a}: {e}", a=alias_id, e=exc)

    # Trier par date (updated_at ou created_at), plus récent en premier
    memories.sort(
        key=lambda m: m.get("updated_at") or m.get("created_at") or "",
        reverse=True,
    )

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


# ── POST /memory/resolve-usernames ────────────────────────────────────────────

@router.post("/memory/resolve-usernames")
async def resolve_usernames(request: Request):
    """Résout les usernames Discord manquants via l'API Discord.

    Parcourt les memory_users Discord sans username et appelle
    discord_bot.fetch_user(id) pour récupérer le display_name.
    """
    state = request.app.state.wally
    if state.discord_bot is None:
        raise HTTPException(503, detail="Discord bot non disponible")

    users = await state.db.list_memory_users()
    resolved = 0
    for user in users:
        if user["platform"] != "discord" or user.get("username"):
            continue
        # Extraire l'ID numérique depuis "discord:123456789"
        raw_id = user["user_id"].replace("discord:", "")
        if not raw_id.isdigit():
            continue
        try:
            discord_user = await state.discord_bot.fetch_user(int(raw_id))
            name = discord_user.display_name or discord_user.name
            if name:
                await state.db.upsert_memory_user(user["user_id"], "discord", username=name)
                resolved += 1
                logger.info("Username résolu: discord:{id} → {name}", id=raw_id, name=name)
        except Exception as e:
            logger.warning("Impossible de résoudre discord:{id}: {e}", id=raw_id, e=e)

    return {"resolved": resolved}


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
