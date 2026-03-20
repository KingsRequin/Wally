# bot/dashboard/routes/memory.py
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

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
async def list_users(request: Request, q: str | None = None, show_all: str | None = None):
    state = request.app.state.wally
    include_no_memory = show_all == "1"
    users = await state.db.list_memory_users(q, include_no_memory=include_no_memory)

    # Récupérer les liaisons acceptées pour fusionner l'affichage
    accepted_links = await state.db.list_link_proposals(status="accepted")

    # Construire un index user_id → username depuis tous les users connus
    # (pour résoudre les noms des alias supprimés de memory_users après fusion)
    all_known = await state.db.list_memory_users(include_no_memory=True)
    uid_to_name: dict[str, str] = {
        u["user_id"]: u["username"] for u in all_known if u.get("username")
    }

    # alias_id → info du canonical (pour masquer l'alias de la liste)
    alias_set: set[str] = set()
    # canonical_id → liste des alias liés (pour montrer le badge)
    canonical_aliases: dict[str, list[dict]] = {}
    for link in accepted_links:
        alias_id = link["alias_id"]
        alias_set.add(alias_id)
        # Résoudre le nom : DB link → index users connus → raw ID en fallback
        alias_name = (
            link["alias_username"]
            or uid_to_name.get(alias_id)
            or (alias_id.split(":", 1)[1] if ":" in alias_id else alias_id)
        )
        # Si le fallback est un ID numérique, tenter de trouver via le canonical
        # (le canonical a parfois le même user sous un autre format)
        canonical_aliases.setdefault(link["canonical_id"], []).append({
            "alias_id": alias_id,
            "alias_platform": alias_id.split(":")[0] if ":" in alias_id else "",
            "alias_username": alias_name,
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


# ── POST /memory/users (register manually) ────────────────────────────────────

class RegisterUserRequest(BaseModel):
    platform: str
    user_id: str
    username: str = ""


@router.post("/memory/users")
async def register_user(body: RegisterUserRequest, request: Request):
    """Enregistre manuellement un utilisateur (même sans mémoire) pour pouvoir le lier."""
    state = request.app.state.wally
    platform = body.platform.strip().lower()
    raw_id = body.user_id.strip()
    username = body.username.strip()

    if platform not in ("discord", "twitch"):
        raise HTTPException(400, detail="Plateforme invalide (discord ou twitch)")
    if not raw_id:
        raise HTTPException(400, detail="ID utilisateur requis")
    if platform == "discord" and not raw_id.isdigit():
        raise HTTPException(400, detail="L'ID Discord doit être numérique")

    full_id = f"{platform}:{raw_id}"
    await state.db.upsert_memory_user(full_id, platform, username=username)
    logger.info("Utilisateur enregistré manuellement: {uid}", uid=full_id)
    return {"status": "ok", "user_id": full_id}


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


# ── POST /memory/users/{user_id}/memories ─────────────────────────────────────

class AddMemoryRequest(BaseModel):
    content: str


@router.post("/memory/users/{user_id}/memories")
async def add_memory(user_id: str, body: AddMemoryRequest, request: Request):
    """Ajoute manuellement un souvenir à un utilisateur via mem0."""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, detail="Contenu requis")

    mem0 = _get_mem0(request)
    state = request.app.state.wally

    # Extraire plateforme depuis le user_id (format "platform:id")
    platform = user_id.split(":")[0] if ":" in user_id else ""

    result = await asyncio.to_thread(
        mem0.add, content, user_id=user_id,
        metadata={"origin": user_id},
    )
    logger.info("Souvenir ajouté manuellement pour {uid}: {c}", uid=user_id, c=content[:80])

    # Assurer que l'utilisateur existe dans memory_users
    await state.db.upsert_memory_user(user_id, platform)

    return {"status": "ok", "user_id": user_id}


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


# ── PUT /memory/users/{user_id}/memories/{memory_id} ─────────────────────────

class UpdateMemoryRequest(BaseModel):
    content: str


@router.put("/memory/users/{user_id}/memories/{memory_id}")
async def update_memory(user_id: str, memory_id: str, body: UpdateMemoryRequest, request: Request):
    """Modifie le contenu d'un souvenir existant via mem0."""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, detail="Contenu requis")

    mem0 = _get_mem0(request)
    await asyncio.to_thread(mem0.update, memory_id, content)
    logger.info("Souvenir modifié pour {uid}: {mid}", uid=user_id, mid=memory_id)
    return {"status": "ok", "memory_id": memory_id}


# ── DELETE /memory/users/{user_id}/memories/{memory_id} ──────────────────────

@router.delete("/memory/users/{user_id}/memories/{memory_id}")
async def delete_memory(user_id: str, memory_id: str, request: Request):
    mem0 = _get_mem0(request)
    await asyncio.to_thread(mem0.delete, memory_id)
    return {"deleted": True}


# ── GET /memory/aliases ───────────────────────────────────────────────────────

@router.get("/memory/aliases")
async def list_aliases(request: Request):
    state = request.app.state.wally
    aliases = await state.db.list_aliases()
    unresolved = await state.db.list_unresolved_aliases()

    # Count facts for unresolved aliases (try/except — mem0 may be unavailable)
    mem0 = None
    try:
        mem0 = _get_mem0(request)
    except Exception:
        pass

    unresolved_with_facts = []
    for u in unresolved:
        fact_count = 0
        if mem0:
            try:
                results = await asyncio.to_thread(mem0.get_all, user_id=u["user_id"])
                results = _unwrap(results)
                fact_count = len([r for r in results if r.get("memory")])
            except Exception:
                pass
        unresolved_with_facts.append({**u, "fact_count": fact_count})

    return {"aliases": aliases, "unresolved": unresolved_with_facts}


# ── POST /memory/aliases ──────────────────────────────────────────────────────

class AddAliasRequest(BaseModel):
    nickname: str
    canonical_uid: str
    display_name: str = ""


@router.post("/memory/aliases")
async def add_alias(body: AddAliasRequest, request: Request):
    state = request.app.state.wally
    nickname = body.nickname.strip().lower()
    if not nickname or not body.canonical_uid.strip():
        raise HTTPException(400, detail="nickname et canonical_uid requis")

    await state.db.upsert_alias(
        nickname, body.canonical_uid.strip(),
        body.display_name.strip(), "manual", 1.0,
    )
    state.memory.add_alias(f"nickname:{nickname}", body.canonical_uid.strip())

    # Reconcile orphan facts if applicable
    fe = getattr(state, "fact_extractor", None)
    if fe:
        asyncio.create_task(fe._reconcile_orphan_facts(nickname, body.canonical_uid.strip()))

    return {"status": "ok"}


# ── DELETE /memory/aliases/{nickname} ─────────────────────────────────────────

@router.delete("/memory/aliases/{nickname}")
async def delete_alias(nickname: str, request: Request):
    state = request.app.state.wally
    await state.db.delete_alias(nickname)
    state.memory.remove_alias(f"nickname:{nickname}")
    return {"deleted": True}


# ── POST /memory/aliases/{nickname}/resolve ───────────────────────────────────

class ResolveAliasRequest(BaseModel):
    canonical_uid: str
    display_name: str = ""


@router.post("/memory/aliases/{nickname}/resolve")
async def resolve_alias(nickname: str, body: ResolveAliasRequest, request: Request):
    state = request.app.state.wally
    nickname = nickname.strip().lower()
    canonical_uid = body.canonical_uid.strip()

    if not canonical_uid:
        raise HTTPException(400, detail="canonical_uid requis")

    await state.db.upsert_alias(
        nickname, canonical_uid, body.display_name.strip(), "manual", 1.0,
    )
    state.memory.add_alias(f"nickname:{nickname}", canonical_uid)

    fe = getattr(state, "fact_extractor", None)
    if fe:
        asyncio.create_task(fe._reconcile_orphan_facts(nickname, canonical_uid))

    return {"status": "ok", "resolved": f"{nickname} → {canonical_uid}"}


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
    """Résout les usernames manquants via les APIs Discord et Twitch."""
    state = request.app.state.wally
    users = await state.db.list_memory_users(include_no_memory=True)
    resolved = 0

    # ── Discord ──
    if state.discord_bot is not None:
        for user in users:
            if user["platform"] != "discord" or user.get("username"):
                continue
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

    # ── Twitch ──
    if state.twitch_bot is not None:
        twitch_to_resolve = []
        for user in users:
            if user["platform"] != "twitch" or user.get("username"):
                continue
            raw_id = user["user_id"].replace("twitch:", "")
            if raw_id.isdigit():
                twitch_to_resolve.append((user["user_id"], int(raw_id)))

        # Batch par groupes de 100 (limite API Twitch)
        for i in range(0, len(twitch_to_resolve), 100):
            batch = twitch_to_resolve[i:i + 100]
            ids = [uid for _, uid in batch]
            try:
                twitch_users = await state.twitch_bot.fetch_users(ids=ids)
                id_to_name = {
                    str(tu.id): tu.display_name or tu.name
                    for tu in twitch_users
                }
                for full_id, numeric_id in batch:
                    name = id_to_name.get(str(numeric_id))
                    if name:
                        await state.db.upsert_memory_user(full_id, "twitch", username=name)
                        resolved += 1
                        logger.info("Username résolu: {uid} → {name}", uid=full_id, name=name)
            except Exception as e:
                logger.warning("Impossible de résoudre batch Twitch: {e}", e=e)

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
