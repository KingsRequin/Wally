# bot/dashboard/routes/links.py
"""Routes admin pour la gestion des liaisons de comptes Discord/Twitch."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from bot.dashboard.routes.sse import broadcast_event

router = APIRouter()

# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()


def _fire(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


@router.get("/links")
async def list_links(request: Request, status: str | None = None):
    """Liste les propositions de liaison, filtrées par status optionnel."""
    state = request.app.state.wally
    proposals = await state.db.list_link_proposals(status=status)
    return {"proposals": proposals}


@router.post("/links/analyze")
async def analyze_links(request: Request):
    """Lance l'analyse de similarité en arrière-plan."""
    state = request.app.state.wally
    from bot.core import account_linker
    threshold = getattr(state.config.bot, "link_min_confidence", 0.75)

    async def _run():
        count = await account_linker.analyze_all(state.db, threshold)
        broadcast_event({"type": "links_analyzed", "count": count})
        logger.info("Analyse liens terminée: {n} propositions", n=count)

    _fire(_run())
    return {"status": "started"}


async def _merge_memories(state, canonical_id: str, alias_id: str) -> None:
    """Fusionne les mémoires mem0 de l'alias vers le canonical, puis nettoie."""
    state.memory.add_alias(alias_id, canonical_id)

    state.memory._init_mem0()
    if state.memory._mem0 is None:
        logger.warning("mem0 non disponible — liaison acceptée sans fusion mémoire")
        return

    try:
        alias_memories = await asyncio.to_thread(
            state.memory._mem0.get_all, user_id=alias_id
        )
        memories_list = (
            alias_memories if isinstance(alias_memories, list)
            else alias_memories.get("results", [])
        )
        total = 0
        copied = 0
        for mem in memories_list:
            content = mem.get("memory", "")
            if content:
                total += 1
                try:
                    await asyncio.to_thread(
                        state.memory._mem0.add, content, user_id=canonical_id
                    )
                    copied += 1
                except Exception as copy_err:
                    logger.warning(
                        "Échec copie mémoire {a} → {c}: {e}",
                        a=alias_id, c=canonical_id, e=copy_err,
                    )
        if total > 0 and copied == total:
            await asyncio.to_thread(
                state.memory._mem0.delete_all, user_id=alias_id
            )
            # Ne pas supprimer de memory_users : l'alias est masqué via
            # user_links dans list_users, et on garde le username pour l'affichage
        elif total > 0:
            logger.warning(
                "Fusion partielle {a} → {c}: {ok}/{n} — mémoires alias conservées",
                a=alias_id, c=canonical_id, ok=copied, n=total,
            )
    except Exception as e:
        logger.error("Erreur fusion mémoire: {e}", e=e)


async def _resolve_user_id(db, entered: str, platform: str) -> str | None:
    """Résout un identifiant entré par l'admin vers le vrai user_id dans memory_users.

    Stratégie : match exact sur user_id, puis recherche par username.
    Retourne None si aucun match trouvé (pour éviter de créer des entrées fantômes).
    """
    all_users = await db.list_memory_users(include_no_memory=True)
    platform_users = [u for u in all_users if u["platform"] == platform]

    # 1. Match exact sur user_id (format complet "platform:id")
    for u in platform_users:
        if u["user_id"] == entered:
            return entered

    # 2. Match sur la partie raw_id (après le ":")
    raw = entered.split(":", 1)[1] if ":" in entered else entered
    for u in platform_users:
        u_raw = u["user_id"].split(":", 1)[1] if ":" in u["user_id"] else u["user_id"]
        if u_raw == raw:
            return u["user_id"]

    # 3. Match par username (case-insensitive)
    raw_lower = raw.lower()
    for u in platform_users:
        if u.get("username") and u["username"].lower() == raw_lower:
            return u["user_id"]

    return None


@router.post("/links/{link_id}/accept")
async def accept_link(link_id: int, request: Request):
    """Accepte une liaison : merge mem0 et met à jour le cache d'alias."""
    state = request.app.state.wally
    result = await state.db.accept_link(link_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Liaison introuvable")

    canonical_id = result["canonical_id"]
    alias_id = result["alias_id"]

    await _merge_memories(state, canonical_id, alias_id)

    broadcast_event({"type": "link_accepted", "canonical_id": canonical_id, "alias_id": alias_id})
    logger.info("Liaison acceptée: {a} → {c}", a=alias_id, c=canonical_id)
    return {"status": "accepted", "canonical_id": canonical_id, "alias_id": alias_id}


class ManualLinkRequest(BaseModel):
    canonical_id: str
    alias_id: str


@router.post("/links/manual")
async def create_manual_link(body: ManualLinkRequest, request: Request):
    """Crée et accepte immédiatement une liaison manuelle (validation humaine)."""
    state = request.app.state.wally
    canonical = body.canonical_id.strip()
    alias = body.alias_id.strip()

    if not canonical or not alias:
        raise HTTPException(status_code=400, detail="Les deux identifiants sont requis")
    if canonical == alias:
        raise HTTPException(status_code=400, detail="Les deux identifiants doivent être différents")

    # Normaliser le format platform:user_id
    if ":" not in canonical:
        canonical = f"discord:{canonical}"
    if ":" not in alias:
        alias = f"twitch:{alias}"

    # Résoudre vers les vrais user_id dans memory_users
    # (ex: "twitch:noctea_moon" → "twitch:12345678" si le username matche)
    canonical_platform = canonical.split(":")[0]
    alias_platform = alias.split(":")[0]
    resolved_canonical = await _resolve_user_id(state.db, canonical, canonical_platform)
    resolved_alias = await _resolve_user_id(state.db, alias, alias_platform)

    if resolved_canonical is None:
        raise HTTPException(status_code=404, detail=f"Utilisateur introuvable : {canonical}")
    if resolved_alias is None:
        raise HTTPException(status_code=404, detail=f"Utilisateur introuvable : {alias}")
    canonical = resolved_canonical
    alias = resolved_alias

    if canonical == alias:
        raise HTTPException(status_code=400, detail="Les deux identifiants résolvent vers le même utilisateur")

    # Créer la proposition et l'accepter immédiatement (lien humain = confiance 1.0)
    await state.db.upsert_link_proposal(canonical, alias, 1.0)
    # Récupérer l'ID pour marquer comme accepté
    proposals = await state.db.list_link_proposals()
    link_id = None
    for p in proposals:
        if p["canonical_id"] == canonical and p["alias_id"] == alias:
            link_id = p["id"]
            break
    if link_id is not None:
        await state.db.accept_link(link_id)

    await _merge_memories(state, canonical, alias)

    broadcast_event({"type": "link_accepted", "canonical_id": canonical, "alias_id": alias})
    logger.info("Liaison manuelle acceptée: {a} → {c}", a=alias, c=canonical)
    return {"status": "accepted", "canonical_id": canonical, "alias_id": alias}


@router.post("/links/{link_id}/reject")
async def reject_link(link_id: int, request: Request):
    """Rejette une liaison."""
    state = request.app.state.wally
    await state.db.reject_link(link_id)
    broadcast_event({"type": "link_rejected", "link_id": link_id})
    return {"status": "rejected"}


@router.post("/links/{link_id}/unlink")
async def unlink(link_id: int, request: Request):
    """Délie deux comptes précédemment liés.

    Remet le statut à 'rejected', supprime l'alias du cache mémoire,
    et recrée l'entrée memory_users pour l'alias (les mémoires restent
    dans le canonical — pas de "dé-fusion" automatique).
    """
    state = request.app.state.wally

    # Récupérer les infos du lien avant modification
    link = await state.db.get_link_proposal(link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Liaison introuvable")
    if link["status"] != "accepted":
        raise HTTPException(status_code=400, detail="Seule une liaison acceptée peut être déliée")

    canonical_id = link["canonical_id"]
    alias_id = link["alias_id"]

    # Marquer comme rejeté
    await state.db.reject_link(link_id)

    # Retirer du cache d'alias en mémoire
    state.memory.remove_alias(alias_id)

    # Recréer l'entrée memory_users pour l'alias (pour qu'il réapparaisse)
    alias_platform = alias_id.split(":")[0] if ":" in alias_id else ""
    alias_username = link.get("alias_username") or ""
    if alias_platform:
        await state.db.upsert_memory_user(alias_id, alias_platform, username=alias_username)

    broadcast_event({"type": "link_unlinked", "canonical_id": canonical_id, "alias_id": alias_id})
    logger.info("Liaison déliée: {a} ↔ {c}", a=alias_id, c=canonical_id)
    return {"status": "unlinked", "canonical_id": canonical_id, "alias_id": alias_id}
