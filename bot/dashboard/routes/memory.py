# bot/dashboard/routes/memory.py
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from bot.core.memory import GLOBAL_USER_ID
from bot.core.memory_store import MemoryMetadata, MemoryRecord

router = APIRouter()


def _get_store(request: Request):
    """Return the QdrantMemoryStore from MemoryService, or raise 503."""
    state = request.app.state.wally
    store = state.memory.store
    if store is None:
        raise HTTPException(503, detail="Memory store not available")
    return store


# ── GET /memory/users ─────────────────────────────────────────────────────────

@router.get("/memory/users")
async def list_users(
    request: Request,
    q: str | None = None,
    show_all: str | None = None,
    sort_by: str = "memories",
):
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

    # Index avatar par user_id (pour résoudre les avatars des alias liés)
    all_avatars: dict[str, str] = {
        u["user_id"]: u.get("avatar_url") or ""
        for u in all_known
        if u.get("avatar_url")
    }

    # Enrichir chaque utilisateur avec trust_score, love_score, defaults
    for user in merged_users:
        user.setdefault("avatar_url", None)
        user.setdefault("memory_count", 0)

        # Pour les comptes liés, privilégier l'avatar Discord
        linked = user.get("linked_accounts", [])
        if linked:
            uid = user["user_id"]
            user_platform = uid.split(":")[0] if ":" in uid else ""
            # Chercher un avatar Discord parmi canonical + alias
            discord_avatar = None
            if user_platform == "discord" and user.get("avatar_url"):
                discord_avatar = user["avatar_url"]
            else:
                for alias in linked:
                    if alias.get("alias_platform") == "discord":
                        discord_avatar = all_avatars.get(alias["alias_id"])
                        if discord_avatar:
                            break
            if discord_avatar:
                user["avatar_url"] = discord_avatar
        # Extraire platform et raw_id depuis user_id (format "platform:raw_id")
        uid = user["user_id"]
        platform = uid.split(":")[0] if ":" in uid else user.get("platform", "")
        raw_id = uid.split(":", 1)[1] if ":" in uid else uid
        try:
            trust = await state.db.get_trust_score(platform, raw_id)
            user["trust_score"] = float(trust) if trust is not None else 0.0
        except Exception:
            user["trust_score"] = 0.0
        try:
            love = await state.db.get_love_score(platform, raw_id)
            user["love_score"] = float(love) if love is not None else 0.0
        except Exception:
            user["love_score"] = 0.0

    # Tri selon le paramètre sort_by
    sort_keys = {
        "trust": lambda u: u.get("trust_score", 0.0),
        "love": lambda u: u.get("love_score", 0.0),
        "memories": lambda u: u.get("memory_count", 0),
        "name": lambda u: (u.get("username") or "").lower(),
    }
    key_fn = sort_keys.get(sort_by, sort_keys["memories"])
    reverse = sort_by != "name"
    merged_users.sort(key=key_fn, reverse=reverse)

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
    store = _get_store(request)

    def _source_platform(source_id: str) -> str:
        return source_id.split(":")[0] if ":" in source_id else ""

    def _record_to_dict(r: MemoryRecord, source: str) -> dict:
        return {
            "id": r.id,
            "memory": r.text,
            "category": r.category,
            "source": source,
            "source_platform": _source_platform(source),
            "created_at": r.created_at,
            "updated_at": r.created_at,
        }

    # Récupérer les mémoires du user principal
    records = await store.get_all(user_id)
    memories = [_record_to_dict(r, user_id) for r in records if r.text]

    # Si cet utilisateur a des alias liés, inclure aussi leurs mémoires
    accepted_links = await state.db.list_link_proposals(status="accepted")
    alias_ids = [
        link["alias_id"] for link in accepted_links
        if link["canonical_id"] == user_id
    ]
    for alias_id in alias_ids:
        try:
            alias_records = await store.get_all(alias_id)
            for r in alias_records:
                if r.text:
                    memories.append(_record_to_dict(r, alias_id))
        except Exception as exc:
            logger.warning("Échec lecture mémoires alias {a}: {e}", a=alias_id, e=exc)

    # Trier par date (created_at), plus récent en premier
    memories.sort(
        key=lambda m: m.get("created_at") or "",
        reverse=True,
    )

    return {"user_id": user_id, "memories": memories}


# ── POST /memory/users/{user_id}/memories ─────────────────────────────────────

class AddMemoryRequest(BaseModel):
    content: str
    category: str = ""


@router.post("/memory/users/{user_id}/memories")
async def add_memory(user_id: str, body: AddMemoryRequest, request: Request):
    """Ajoute manuellement un souvenir à un utilisateur."""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, detail="Contenu requis")

    store = _get_store(request)
    state = request.app.state.wally

    # Extraire plateforme depuis le user_id (format "platform:id")
    platform = user_id.split(":")[0] if ":" in user_id else ""

    meta = MemoryMetadata(
        user_id=user_id,
        category=body.category or "FAIT",
        source=user_id,
        platform=platform,
    )
    await store.upsert(user_id, content, meta)
    logger.info("Souvenir ajouté manuellement pour {uid}: {c}", uid=user_id, c=content[:80])

    # Assurer que l'utilisateur existe dans memory_users
    await state.db.upsert_memory_user(user_id, platform)

    return {"status": "ok", "user_id": user_id}


# ── DELETE /memory/users/{user_id} ────────────────────────────────────────────

@router.delete("/memory/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    state = request.app.state.wally
    store = _get_store(request)
    await store.delete_by_user(user_id)
    await state.db.execute(
        "DELETE FROM memory_users WHERE user_id = ?", (user_id,)
    )
    return {"deleted": True}


# ── PUT /memory/users/{user_id}/memories/{memory_id} ─────────────────────────

class UpdateMemoryRequest(BaseModel):
    content: str
    category: str = ""


@router.put("/memory/users/{user_id}/memories/{memory_id}")
async def update_memory(user_id: str, memory_id: str, body: UpdateMemoryRequest, request: Request):
    """Modifie le contenu d'un souvenir existant."""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, detail="Contenu requis")

    store = _get_store(request)
    platform = user_id.split(":")[0] if ":" in user_id else ""
    meta = MemoryMetadata(
        user_id=user_id,
        category=body.category or "FAIT",
        source=user_id,
        platform=platform,
    )
    await store.update(memory_id, content, meta)
    logger.info("Souvenir modifié pour {uid}: {mid}", uid=user_id, mid=memory_id)
    return {"status": "ok", "memory_id": memory_id}


# ── DELETE /memory/users/{user_id}/memories/{memory_id} ──────────────────────

@router.delete("/memory/users/{user_id}/memories/{memory_id}")
async def delete_memory(user_id: str, memory_id: str, request: Request):
    store = _get_store(request)
    await store.delete(memory_id)
    return {"deleted": True}


# ── Global memory CRUD ────────────────────────────────────────────────────────

@router.get("/memory/global")
async def list_global_memories(request: Request):
    """Liste toutes les mémoires globales (connaissances communauté)."""
    store = _get_store(request)
    records = await store.get_all(GLOBAL_USER_ID)
    memories = [
        {
            "id": r.id,
            "memory": r.text,
            "created_at": r.created_at,
            "updated_at": r.created_at,
        }
        for r in records
        if r.text
    ]
    memories.sort(
        key=lambda m: m.get("created_at") or "",
        reverse=True,
    )
    return {"memories": memories}


@router.post("/memory/global")
async def add_global_memory(body: AddMemoryRequest, request: Request):
    """Ajoute une connaissance globale (communauté)."""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, detail="Contenu requis")
    state = request.app.state.wally
    await state.memory.add_global(content)
    return {"status": "ok"}


@router.put("/memory/global/{memory_id}")
async def update_global_memory(memory_id: str, body: UpdateMemoryRequest, request: Request):
    """Modifie une mémoire globale."""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, detail="Contenu requis")
    store = _get_store(request)
    meta = MemoryMetadata(
        user_id=GLOBAL_USER_ID,
        category=body.category or "FAIT",
        source="dashboard",
        platform="",
    )
    await store.update(memory_id, content, meta)
    logger.info("Global memory updated: {mid}", mid=memory_id)
    return {"status": "ok", "memory_id": memory_id}


@router.delete("/memory/global/{memory_id}")
async def delete_global_memory(memory_id: str, request: Request):
    """Supprime une mémoire globale."""
    store = _get_store(request)
    await store.delete(memory_id)
    return {"deleted": True}


# ── GET /memory/aliases ───────────────────────────────────────────────────────

@router.get("/memory/aliases")
async def list_aliases(request: Request):
    state = request.app.state.wally
    aliases = await state.db.list_aliases()
    unresolved = await state.db.list_unresolved_aliases()

    # Count facts for unresolved aliases (try/except — store may be unavailable)
    store = None
    try:
        store = _get_store(request)
    except Exception:
        pass

    unresolved_with_facts = []
    for u in unresolved:
        fact_count = 0
        if store:
            try:
                count = await store.count(u["user_id"])
                fact_count = count
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

    # ── Resolve missing usernames + fetch avatars ──
    users = await state.db.list_memory_users(include_no_memory=True)
    resolved = 0

    # Discord — resolve usernames and avatars
    if state.discord_bot is not None:
        for user in users:
            if user["platform"] != "discord":
                continue
            raw_id = user["user_id"].replace("discord:", "")
            if not raw_id.isdigit():
                continue
            need_name = not user.get("username")
            need_avatar = not user.get("avatar_url")
            if not need_name and not need_avatar:
                continue
            try:
                discord_user = await state.discord_bot.fetch_user(int(raw_id))
                name = discord_user.display_name or discord_user.name
                avatar = str(discord_user.display_avatar.url) if discord_user.display_avatar else ""
                if name or avatar:
                    await state.db.upsert_memory_user(
                        user["user_id"], "discord",
                        username=name if need_name else "",
                        avatar_url=avatar if need_avatar else "",
                    )
                    if need_name and name:
                        resolved += 1
                    logger.info(
                        "Discord résolu: {id} → name={name} avatar={has}",
                        id=raw_id, name=name, has=bool(avatar),
                    )
            except Exception as e:
                logger.warning("Impossible de résoudre discord:{id}: {e}", id=raw_id, e=e)

    # Twitch — resolve usernames and avatars
    # Twitch user IDs are max ~10 digits; skip Discord snowflakes stored by mistake
    if state.twitch_bot is not None:
        twitch_to_resolve = []
        for user in users:
            if user["platform"] != "twitch":
                continue
            raw_id = user["user_id"].replace("twitch:", "")
            if not raw_id.isdigit():
                continue
            if len(raw_id) > 12:
                logger.debug("Skipping likely Discord snowflake in twitch ns: {uid}", uid=user["user_id"])
                continue
            need_name = not user.get("username")
            need_avatar = not user.get("avatar_url")
            if not need_name and not need_avatar:
                continue
            twitch_to_resolve.append((user["user_id"], int(raw_id), need_name))

        logger.info("Twitch users to resolve: {n}", n=len(twitch_to_resolve))
        for i in range(0, len(twitch_to_resolve), 100):
            batch = twitch_to_resolve[i:i + 100]
            ids = [uid for _, uid, _ in batch]
            try:
                twitch_users = await state.twitch_bot.fetch_users(ids=ids)
                id_to_user = {str(tu.id): tu for tu in twitch_users}
                for full_id, numeric_id, need_name in batch:
                    tu = id_to_user.get(str(numeric_id))
                    if tu:
                        name = tu.display_name or tu.name
                        avatar = getattr(tu, "profile_image", "") or ""
                        await state.db.upsert_memory_user(
                            full_id, "twitch",
                            username=name if need_name else "",
                            avatar_url=avatar,
                        )
                        if need_name and name:
                            resolved += 1
                        logger.info(
                            "Twitch résolu: {uid} → name={name} avatar={has}",
                            uid=full_id, name=name, has=bool(avatar),
                        )
                    else:
                        logger.warning("Twitch API n'a pas retourné: {uid}", uid=full_id)
            except Exception as e:
                logger.warning("Impossible de résoudre batch Twitch: {e}", e=e)

    # ── Update memory_count per user ──
    store = state.memory.store
    if store is not None:
        for user in users:
            uid = user["user_id"]
            try:
                count = await store.count(uid)
                await state.db.execute(
                    "UPDATE memory_users SET memory_count=? WHERE user_id=?",
                    (count, uid),
                )
            except Exception as e:
                logger.warning("memory_count update failed for {uid}: {e}", uid=uid, e=e)

    return {"synced": n, "resolved": resolved}


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
            if user["platform"] != "discord":
                continue
            raw_id = user["user_id"].replace("discord:", "")
            if not raw_id.isdigit():
                continue
            need_name = not user.get("username")
            need_avatar = not user.get("avatar_url")
            if not need_name and not need_avatar:
                continue
            try:
                discord_user = await state.discord_bot.fetch_user(int(raw_id))
                name = discord_user.display_name or discord_user.name
                avatar = str(discord_user.display_avatar.url) if discord_user.display_avatar else ""
                if name or avatar:
                    await state.db.upsert_memory_user(
                        user["user_id"], "discord",
                        username=name if need_name else "",
                        avatar_url=avatar if need_avatar else "",
                    )
                    if need_name and name:
                        resolved += 1
            except Exception as e:
                logger.warning("Impossible de résoudre discord:{id}: {e}", id=raw_id, e=e)

    # ── Twitch ──
    if state.twitch_bot is not None:
        twitch_to_resolve = []
        for user in users:
            if user["platform"] != "twitch":
                continue
            raw_id = user["user_id"].replace("twitch:", "")
            if not raw_id.isdigit() or len(raw_id) > 12:
                continue
            need_name = not user.get("username")
            need_avatar = not user.get("avatar_url")
            if not need_name and not need_avatar:
                continue
            twitch_to_resolve.append((user["user_id"], int(raw_id), need_name))

        for i in range(0, len(twitch_to_resolve), 100):
            batch = twitch_to_resolve[i:i + 100]
            ids = [uid for _, uid, _ in batch]
            try:
                twitch_users = await state.twitch_bot.fetch_users(ids=ids)
                id_to_user = {str(tu.id): tu for tu in twitch_users}
                for full_id, numeric_id, need_name in batch:
                    tu = id_to_user.get(str(numeric_id))
                    if tu:
                        name = tu.display_name or tu.name
                        avatar = getattr(tu, "profile_image", "") or ""
                        await state.db.upsert_memory_user(
                            full_id, "twitch",
                            username=name if need_name else "",
                            avatar_url=avatar,
                        )
                        if need_name and name:
                            resolved += 1
            except Exception as e:
                logger.warning("Impossible de résoudre batch Twitch: {e}", e=e)

    return {"resolved": resolved}


# ── GET /memory/search ────────────────────────────────────────────────────────

@router.get("/memory/search")
async def search_memories(request: Request, q: str | None = None):
    if not q or not q.strip():
        raise HTTPException(400, detail="q parameter required")
    state = request.app.state.wally
    store = _get_store(request)

    users = await state.db.list_memory_users()
    username_map = {u["user_id"]: u.get("username") for u in users}

    all_results = []
    for user in users:
        uid = user["user_id"]
        platform = user["platform"]
        try:
            records = await store.search(q, user_id=uid, limit=3, min_score=0.3)
            for r in records:
                if r.text:
                    all_results.append({
                        "user_id": uid,
                        "username": username_map.get(uid),
                        "platform": platform,
                        "memory": r.text,
                        "score": r.score,
                    })
        except Exception as exc:
            logger.warning("Memory search failed for {uid}: {e}", uid=uid, e=exc)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": all_results}


# ── POST /memory/scan-web-chat ────────────────────────────────────────────────

@router.post("/memory/scan-web-chat")
async def scan_web_chat(request: Request):
    """Scan all web chat messages and extract facts via FactExtractor."""
    state = request.app.state.wally
    fe = getattr(state, "fact_extractor", None)
    if fe is None:
        raise HTTPException(503, detail="FactExtractor non disponible")

    # Load all non-Wally messages from chat_messages
    cursor = await state.db._conn.execute(
        "SELECT sender_id, username, content, created_at "
        "FROM chat_messages WHERE is_wally = 0 ORDER BY created_at ASC"
    )
    rows = await cursor.fetchall()

    if len(rows) < 2:
        return {"status": "skip", "reason": "Moins de 2 messages humains", "facts_stored": 0}

    # Convert to FactExtractor dict format
    msg_dicts = [
        {
            "user_id": row["sender_id"].split(":", 1)[1] if ":" in row["sender_id"] else row["sender_id"],
            "display_name": row["username"],
            "content": row["content"],
            "timestamp": row["created_at"],
        }
        for row in rows
    ]

    # Process in batches of 50 to avoid oversized LLM calls
    total_stored = 0
    batch_size = 50
    for i in range(0, len(msg_dicts), batch_size):
        batch = msg_dicts[i : i + batch_size]
        try:
            stored = await fe._extract_facts(batch, "discord", "web:chat")
            total_stored += stored
        except Exception as exc:
            logger.warning("scan-web-chat batch {i} failed: {e}", i=i, e=exc)

    logger.info("scan-web-chat complete: {n} facts from {m} messages", n=total_stored, m=len(msg_dicts))
    return {"status": "ok", "messages_scanned": len(msg_dicts), "facts_stored": total_stored}


# ── GET /memory/dashboard — vue d'ensemble mémoire ───────────────────────────

@router.get("/memory/dashboard")
async def memory_dashboard(request: Request):
    """Dashboard mémoire : questions en attente, stats par utilisateur, consolidation."""
    state = request.app.state.wally
    db = state.db

    # 1. Toutes les questions en attente (non résolues)
    cursor = await db._conn.execute(
        "SELECT mq.*, mu.username FROM memory_questions mq "
        "LEFT JOIN memory_users mu ON mu.user_id = mq.user_id "
        "WHERE mq.resolved = 0 ORDER BY "
        "CASE mq.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        "mq.created_at ASC"
    )
    pending_questions = [dict(row) for row in await cursor.fetchall()]

    # 2. Stats questions (total, résolues, en attente)
    cursor = await db._conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved, "
        "SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END) as pending "
        "FROM memory_questions"
    )
    q_stats = dict(await cursor.fetchone())

    # 3. Nombre de souvenirs par utilisateur (top 20) via memory store count
    users = await db.list_memory_users()
    user_memory_counts: list[dict] = []
    store = None
    try:
        store = _get_store(request)
    except Exception:
        pass

    if store:
        for u in users[:30]:  # limiter pour perf
            try:
                count = await store.count(u["user_id"])
                user_memory_counts.append({
                    "user_id": u["user_id"],
                    "username": u.get("username") or u["user_id"],
                    "platform": u["platform"],
                    "count": count,
                })
            except Exception:
                pass
        user_memory_counts.sort(key=lambda x: x["count"], reverse=True)

    return {
        "pending_questions": pending_questions,
        "question_stats": q_stats,
        "user_memory_counts": user_memory_counts[:20],
    }


@router.post("/memory/questions/{question_id}/resolve")
async def resolve_question(question_id: int, request: Request):
    """Marque une question mémoire comme résolue."""
    state = request.app.state.wally
    await state.db.resolve_question(question_id)
    return {"status": "ok"}


@router.put("/memory/questions/{question_id}")
async def update_question(question_id: int, request: Request):
    """Met à jour le texte d'une question mémoire."""
    state = request.app.state.wally
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    await state.db.update_question(question_id, question)
    return {"status": "ok"}


@router.delete("/memory/questions/{question_id}")
async def delete_question(question_id: int, request: Request):
    """Supprime une question mémoire."""
    state = request.app.state.wally
    await state.db.delete_question(question_id)
    return {"status": "ok"}
