# bot/dashboard/routes/memory.py
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel


router = APIRouter()

# Références fortes des tâches détachées : la boucle asyncio n'en garde qu'une
# référence FAIBLE, donc le GC peut annuler une tâche en cours de route — et son
# exception ne remonte alors nulle part. Le motif est appliqué dans `admin.py` et
# `twitch_auth.py` ; ces deux fichiers s'en passaient, alors qu'y transitent la
# réconciliation d'alias et la réponse de Wally au chat web.
_bg_tasks: set[asyncio.Task] = set()


def _fire(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task





async def _resolve_missing_usernames(
    state,
    users_without_name: list[dict],
    uid_to_name: dict[str, str],
) -> None:
    """Resolve missing usernames via Discord/Twitch bot caches and persist them.

    Mutates users_without_name in-place (sets ``username``).
    Discord : cache d'abord (``get_user``), puis ``fetch_user`` en repli —
    un aller-retour réseau, séquentiel, PAR utilisateur. Le docstring
    annonçait « cache-only, no API call » alors que le code appelait l'API :
    l'onglet Mémoire pouvait mettre plusieurs secondes à s'ouvrir et
    consommait le quota Discord. Les comptes introuvables (supprimés) sont
    désormais mémorisés pour ne pas être retentés à chaque affichage.
    Twitch : ``fetch_users`` par lots. Les noms résolus sont persistés via
    ``upsert_memory_user``.
    """
    discord_bot = getattr(state, "discord_bot", None)
    twitch_bot = getattr(state, "twitch_bot", None)

    # Separate by platform
    discord_pending: list[dict] = []
    twitch_pending: list[dict] = []
    for u in users_without_name:
        uid = u["user_id"]
        platform = uid.split(":")[0] if ":" in uid else u.get("platform", "")
        raw_id = uid.split(":", 1)[1] if ":" in uid else uid
        if platform == "discord" and raw_id.isdigit() and discord_bot is not None:
            discord_pending.append(u)
        elif platform == "twitch" and raw_id.isdigit() and len(raw_id) <= 12 and twitch_bot is not None:
            twitch_pending.append(u)

    # Discord — cache d'abord (`get_user`), repli sur `fetch_user`.
    #
    # PARALLÉLISÉ et borné : c'était une boucle séquentielle d'allers-retours
    # HTTP Discord, un par utilisateur sans pseudo. À la première ouverture de
    # l'onglet Mémoire après un import, la requête tenait plusieurs secondes ;
    # et un 429 sur `fetch_user` retardait tout le reste du bot, ces appels
    # partageant le bucket global du client discord.py. Le sémaphore garde la
    # pression basse tout en supprimant l'attente cumulée.
    _semaphore = asyncio.Semaphore(5)

    async def _resoudre_discord(u):
        raw_id = u["user_id"].split(":", 1)[1]
        try:
            discord_user = discord_bot.get_user(int(raw_id))
            if discord_user is None:
                discord_user = await discord_bot.fetch_user(int(raw_id))
            if discord_user:
                name = discord_user.display_name or discord_user.name
                avatar = str(discord_user.display_avatar.url) if discord_user.display_avatar else ""
                if name:
                    u["username"] = name
                    uid_to_name[u["user_id"]] = name
                if avatar and not u.get("avatar_url"):
                    u["avatar_url"] = avatar
                # Persist for future requests
                await state.db.upsert_memory_user(
                    u["user_id"], "discord",
                    username=name or "",
                    avatar_url=avatar or "",
                )
        except Exception as e:
            # Trace NÉGATIVE persistée : sans elle, un compte supprimé ou
            # inaccessible était retenté à CHAQUE ouverture de l'onglet, donc le
            # coût ne décroissait jamais. Le pseudo brut vaut mieux qu'un
            # aller-retour perdu ; il sera écrasé si le compte réapparaît.
            logger.debug("Discord name resolve failed for {uid}: {e!r}", uid=u["user_id"], e=e)
            try:
                await state.db.upsert_memory_user(
                    u["user_id"], "discord", username=f"@{raw_id}",
                )
            except Exception:  # noqa: BLE001 — au pire on retentera
                pass

    async def _resoudre_borne(u):
        async with _semaphore:
            await _resoudre_discord(u)

    await asyncio.gather(*(_resoudre_borne(u) for u in discord_pending))

    # Twitch — batch fetch (max 100 per call)
    if twitch_pending:
        for i in range(0, len(twitch_pending), 100):
            batch = twitch_pending[i:i + 100]
            ids = [int(u["user_id"].split(":", 1)[1]) for u in batch]
            try:
                twitch_users = await twitch_bot.fetch_users(ids=ids)
                id_to_tu = {str(tu.id): tu for tu in twitch_users}
                for u in batch:
                    raw_id = u["user_id"].split(":", 1)[1]
                    tu = id_to_tu.get(raw_id)
                    if tu:
                        name = tu.display_name or tu.name
                        avatar = getattr(tu, "profile_image", "") or ""
                        if name:
                            u["username"] = name
                            uid_to_name[u["user_id"]] = name
                        if avatar and not u.get("avatar_url"):
                            u["avatar_url"] = avatar
                        await state.db.upsert_memory_user(
                            u["user_id"], "twitch",
                            username=name or "",
                            avatar_url=avatar or "",
                        )
            except Exception as e:
                logger.debug("Twitch batch resolve failed: {e!r}", e=e)


# ── GET /memory/users ─────────────────────────────────────────────────────────

@router.get("/memory/users")
async def list_users(
    request: Request,
    q: str | None = None,
    show_all: str | None = None,
    sort_by: str = "memories",
    limit: int = 50,
    offset: int = 0,
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

    # ── Résoudre les noms manquants via le cache Discord / Twitch ──
    # Collecte des utilisateurs sans username pour résolution en arrière-plan
    to_resolve: list[dict] = [u for u in users if not u.get("username")]
    if to_resolve:
        await _resolve_missing_usernames(state, to_resolve, uid_to_name)

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

    # Pré-calculer les paires (platform, raw_id) pour batch queries
    user_pairs: list[tuple[str, str]] = []
    for user in merged_users:
        uid = user["user_id"]
        platform = uid.split(":")[0] if ":" in uid else user.get("platform", "")
        raw_id = uid.split(":", 1)[1] if ":" in uid else uid
        user_pairs.append((platform, raw_id))

    # Batch fetch trust et love scores (2 queries au lieu de 2×N)
    trust_map = await state.db.get_trust_scores_batch(user_pairs)
    love_map = await state.db.get_love_scores_batch(user_pairs)

    # `memory_users.memory_count` n'est plus écrit depuis la migration V2 : la
    # colonne est figée à sa valeur V1 et affichait le même total sur chaque
    # carte. Le compte vient du fact store, seule source de vérité.
    store = getattr(state, "fact_store", None)
    fact_counts = await store.count_all_by_user() if store is not None else {}

    # Enrichir chaque utilisateur avec trust_score, love_score, defaults
    for user, (platform, raw_id) in zip(merged_users, user_pairs):
        user.setdefault("avatar_url", None)
        user["memory_count"] = fact_counts.get(user["user_id"], 0)
        user["trust_score"] = trust_map.get((platform, raw_id), 0.0)
        user["love_score"] = love_map.get((platform, raw_id), 0.0)

        # Pour les comptes liés, privilégier l'avatar Discord
        linked = user.get("linked_accounts", [])
        if linked:
            uid = user["user_id"]
            user_platform = uid.split(":")[0] if ":" in uid else ""
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

    total = len(merged_users)
    # Plafond relevé à 1000 le 2026-08-28 : la page Personnes charge TOUT et
    # filtre dans le navigateur. À 200, les 255 personnes suivantes étaient
    # introuvables — pas seulement longues à trouver, invisibles, y compris à la
    # recherche. Exactement le défaut déjà corrigé sur `/apex/personnes`.
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    paginated = merged_users[offset:offset + limit]

    return {"users": paginated, "total": total, "limit": limit, "offset": offset}


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

@router.get("/memory/self")
async def get_wally_self(request: Request):
    """Mémoire interne de Wally (#observability C2) : buts, désirs, pensées,
    affinités, préoccupation courante."""
    store = getattr(request.app.state.wally, "fact_store", None)
    if store is None:
        return {"goals": [], "desires": [], "thoughts": [], "relationships": [], "focus": None}
    from bot.intelligence.memory.facts import FactCategory, FactStatus

    async def _cat(cat, n):
        rows = await store.search_by_category(cat, status=FactStatus.ACTIVE, limit=n)
        return [r.content for r in rows]

    rels = await store.get_by_user("wally:self", categories=[FactCategory.REL])
    focus = await store.get_latest_by_source("wally:self", "focus")
    return {
        "goals": await _cat(FactCategory.GOAL, 10),
        "desires": await _cat(FactCategory.DESIRE, 10),
        "thoughts": await _cat(FactCategory.THOUGHT, 10),
        "relationships": [r.content for r in rels[:10]],
        "focus": focus.content if focus else None,
    }


@router.get("/memory/users/{user_id}")
async def get_user_memories(user_id: str, request: Request):
    """Faits S-P-O mémorisés sur un utilisateur (#observability C1)."""
    store = getattr(request.app.state.wally, "fact_store", None)
    if store is None:
        return {"user_id": user_id, "facts": []}
    facts = await store.get_by_user(user_id)
    return {"user_id": user_id, "facts": [{
        "id": f.id, "content": f.content, "category": f.category.value,
        "subject": f.subject, "predicate": f.predicate, "object": f.object_,
        "confidence": f.confidence, "origin": f.origin,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in facts]}


# ── POST /memory/users/{user_id}/memories ─────────────────────────────────────

class AddMemoryRequest(BaseModel):
    content: str
    category: str = ""


def _require_store(request: Request):
    """Le fact store, ou un 503. Son absence n'est pas une erreur de l'appelant."""
    store = getattr(request.app.state.wally, "fact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Mémoire indisponible")
    return store


@router.post("/memory/users/{user_id}/memories")
async def add_memory(user_id: str, body: AddMemoryRequest, request: Request):
    """Ajoute manuellement un souvenir à un utilisateur."""
    from bot.intelligence.memory.facts import AtomicFact, FactCategory

    store = _require_store(request)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Contenu requis")
    try:
        category = FactCategory(body.category)
    except ValueError:
        # L'UI envoie parfois une catégorie vide : un fait sans étiquette reste
        # un fait, ça ne vaut pas un refus.
        category = FactCategory.FAIT
    fact_id = await store.add(AtomicFact(
        user_id=user_id, content=content, category=category,
        source="dashboard", origin="Dashboard admin",
    ))
    logger.info("Souvenir ajouté à la main pour {u}", u=user_id)
    return {"status": "ok", "id": fact_id}


# ── DELETE /memory/users/{user_id} ────────────────────────────────────────────

@router.delete("/memory/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    """Efface tout ce que Wally sait d'un utilisateur."""
    store = _require_store(request)
    deleted = await store.delete_by_user(user_id)
    logger.info("Mémoire de {u} effacée : {n} fait(s)", u=user_id, n=deleted)
    return {"status": "ok", "deleted": deleted}


# ── PUT /memory/users/{user_id}/memories/{memory_id} ─────────────────────────

class UpdateMemoryRequest(BaseModel):
    content: str
    category: str = ""


@router.put("/memory/users/{user_id}/memories/{memory_id}")
async def update_memory(user_id: str, memory_id: int, body: UpdateMemoryRequest, request: Request):
    """Modifie le contenu d'un souvenir existant."""
    store = _require_store(request)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Contenu requis")
    if not await store.update_content(memory_id, content):
        raise HTTPException(status_code=404, detail="Souvenir introuvable")
    return {"status": "ok"}


# ── DELETE /memory/users/{user_id}/memories/{memory_id} ──────────────────────

@router.delete("/memory/users/{user_id}/memories/{memory_id}")
async def delete_memory(user_id: str, memory_id: int, request: Request):
    """Retire un souvenir de la vue de Wally.

    ARCHIVÉ, pas effacé : `get_by_user` ne rend que les faits actifs, donc il
    disparaît de l'écran comme du prompt — mais une suppression par erreur reste
    rattrapable, et l'historique du fait n'est pas perdu.
    """
    from bot.intelligence.memory.facts import FactStatus

    store = _require_store(request)
    await store.set_status(memory_id, FactStatus.ARCHIVED)
    return {"status": "ok"}


# ── Global memory CRUD ────────────────────────────────────────────────────────

@router.get("/memory/global")
async def list_global_memories(request: Request):
    """Liste toutes les mémoires globales (connaissances communauté)."""
    return {"memories": [], "detail": "mémoire en refonte"}


@router.post("/memory/global")
async def add_global_memory(body: AddMemoryRequest, request: Request):
    """Ajoute une connaissance globale (communauté)."""
    raise HTTPException(status_code=501, detail="Mémoire en refonte — indisponible")


@router.put("/memory/global/{memory_id}")
async def update_global_memory(memory_id: str, body: UpdateMemoryRequest, request: Request):
    """Modifie une mémoire globale."""
    raise HTTPException(status_code=501, detail="Mémoire en refonte — indisponible")


@router.delete("/memory/global/{memory_id}")
async def delete_global_memory(memory_id: str, request: Request):
    """Supprime une mémoire globale."""
    raise HTTPException(status_code=501, detail="Mémoire en refonte — indisponible")


# ── GET /memory/aliases ───────────────────────────────────────────────────────

@router.get("/memory/aliases")
async def list_aliases(request: Request):
    state = request.app.state.wally
    aliases = await state.db.list_aliases()
    unresolved = await state.db.list_unresolved_aliases()

    # fact_count non disponible (store V1 supprimé — refonte V2 en cours)
    unresolved_with_facts = [{**u, "fact_count": 0} for u in unresolved]

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
        _fire(fe._reconcile_orphan_facts(nickname, body.canonical_uid.strip()))

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
        _fire(fe._reconcile_orphan_facts(nickname, canonical_uid))

    return {"status": "ok", "resolved": f"{nickname} → {canonical_uid}"}


# ── POST /memory/sync ─────────────────────────────────────────────────────────

@router.post("/memory/sync")
async def sync_memory_users(request: Request):
    state = request.app.state.wally

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
                logger.warning("Impossible de résoudre discord:{id}: {e!r}", id=raw_id, e=e)

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
                logger.warning("Impossible de résoudre batch Twitch: {e!r}", e=e)

    # memory_count update omis (store V1 supprimé — refonte V2 en cours)
    return {"synced": 0, "resolved": resolved}


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
                logger.warning("Impossible de résoudre discord:{id}: {e!r}", id=raw_id, e=e)

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
                logger.warning("Impossible de résoudre batch Twitch: {e!r}", e=e)

    return {"resolved": resolved}


# ── GET /memory/search ────────────────────────────────────────────────────────

@router.get("/memory/search")
async def search_memories(request: Request, q: str | None = None):
    if not q or not q.strip():
        raise HTTPException(400, detail="q parameter required")
    # V2 refonte — store supprimé
    return {"results": [], "detail": "mémoire en refonte"}


# ── POST /memory/scan-web-chat ────────────────────────────────────────────────

@router.post("/memory/scan-web-chat")
async def scan_web_chat(request: Request):
    """Scan all web chat messages and extract facts via FactExtractor."""
    state = request.app.state.wally
    fe = getattr(state, "fact_extractor", None)
    if fe is None:
        raise HTTPException(503, detail="FactExtractor non disponible")

    # Load all non-Wally messages from chat_messages
    # `async with` : le curseur restait ouvert jusqu'au passage du GC.
    async with state.db._conn.execute(
        "SELECT sender_id, username, content, created_at "
        "FROM chat_messages WHERE is_wally = 0 ORDER BY created_at ASC"
    ) as cursor:
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
            logger.warning("scan-web-chat batch {i} failed: {e!r}", i=i, e=exc)

    logger.info("scan-web-chat complete: {n} facts from {m} messages", n=total_stored, m=len(msg_dicts))
    return {"status": "ok", "messages_scanned": len(msg_dicts), "facts_stored": total_stored}


# ── GET /memoire-commune — ce que Wally sait du GROUPE ───────────────────────

@router.get("/memoire-commune")
async def memoire_commune(request: Request, limite_sujets: int = 20):
    """Tout ce qui n'appartient à personne en particulier, en une requête.

    L'ancien onglet « Mémoire communautaire » lisait `/memory/global`, qui rend
    une liste VIDE et refuse toute écriture en 501 depuis la refonte V2 : un
    panneau mort, qui invitait à ajouter un souvenir aussitôt rejeté.

    Ce que Wally sait du groupe vit ailleurs, et n'était exposé nulle part :

    · les **sujets** formés par la passe nocturne (`topics`), chacun avec son
      résumé, ses participants et **l'opinion de Wally** — la matière la plus
      intéressante du lot, et la seule qui dise ce qu'il en PENSE ;
    · les **questions** qu'il aimerait poser (`memory_questions`) ;
    · les **notes** persistantes, qui n'appartiennent à personne par
      construction — la table n'a pas de colonne d'utilisateur.

    « Dans sa tête » (buts, désirs, pensées) garde sa route `/memory/self` :
    c'est le fact store qu'elle interroge, pas ces trois tables-ci.
    """
    limite_sujets = max(1, min(int(limite_sujets), 100))
    db = request.app.state.wally.db
    questions = await memory_dashboard(request)
    return {
        "sujets": await db.get_topics(limite_sujets),
        "questions": questions.get("pending_questions", []),
        "stats_questions": questions.get("question_stats", {}),
        "notes": await db.get_persistent_notes(),
    }


# ── GET /memory/dashboard — vue d'ensemble mémoire ───────────────────────────

@router.get("/memory/dashboard")
async def memory_dashboard(request: Request):
    """Dashboard mémoire : questions en attente, stats par utilisateur, consolidation."""
    state = request.app.state.wally
    db = state.db

    # 1. Toutes les questions en attente (non résolues)
    async with db._conn.execute(
        "SELECT mq.*, mu.username FROM memory_questions mq "
        "LEFT JOIN memory_users mu ON mu.user_id = mq.user_id "
        "WHERE mq.resolved = 0 ORDER BY "
        "CASE mq.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        "mq.created_at ASC"
    ) as cursor:
        pending_questions = [dict(row) for row in await cursor.fetchall()]

    # 2. Stats questions (total, résolues, en attente)
    async with db._conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved, "
        "SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END) as pending "
        "FROM memory_questions"
    ) as cursor:
        q_stats = dict(await cursor.fetchone())

    # user_memory_counts non disponible (store V1 supprimé — refonte V2 en cours)
    return {
        "pending_questions": pending_questions,
        "question_stats": q_stats,
        "user_memory_counts": [],
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
