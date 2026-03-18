# bot/dashboard/routes/links.py
"""Routes admin pour la gestion des liaisons de comptes Discord/Twitch."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from bot.dashboard.routes.sse import broadcast_event

router = APIRouter()


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

    asyncio.create_task(_run())
    return {"status": "started"}


@router.post("/links/{link_id}/accept")
async def accept_link(link_id: int, request: Request):
    """Accepte une liaison : merge mem0 et met à jour le cache d'alias."""
    state = request.app.state.wally
    result = await state.db.accept_link(link_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Liaison introuvable")

    canonical_id = result["canonical_id"]
    alias_id = result["alias_id"]

    # Mettre à jour le cache d'alias dans MemoryService
    state.memory._alias_cache[alias_id] = canonical_id

    # Fusionner les mémoires mem0 : copier les souvenirs de l'alias vers le canonical
    try:
        alias_memories = await asyncio.to_thread(
            state.memory._mem0.get_all, user_id=alias_id
        )
        memories_list = alias_memories if isinstance(alias_memories, list) else alias_memories.get("results", [])
        for mem in memories_list:
            content = mem.get("memory", "")
            if content:
                await asyncio.to_thread(
                    state.memory._mem0.add, content, user_id=canonical_id
                )
        broadcast_event({"type": "link_accepted", "canonical_id": canonical_id, "alias_id": alias_id})
        logger.info("Liaison acceptée: {a} → {c}", a=alias_id, c=canonical_id)
    except Exception as e:
        logger.error("Erreur fusion mémoire: {e}", e=e)

    return {"status": "accepted", "canonical_id": canonical_id, "alias_id": alias_id}


@router.post("/links/{link_id}/reject")
async def reject_link(link_id: int, request: Request):
    """Rejette une liaison."""
    state = request.app.state.wally
    await state.db.reject_link(link_id)
    return {"status": "rejected"}
