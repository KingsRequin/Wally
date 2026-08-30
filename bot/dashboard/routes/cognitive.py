from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from bot.core.text_clean import retirer_tirets_cadratins

public_router = APIRouter()

# Les champs d'un événement cognitif qui portent de la PROSE. Le reste (type,
# horodatage, liste d'actions, identifiants) n'en est pas et ne se nettoie pas.
_CHAMPS_PROSE = ("text", "detail", "message", "content_snippet", "full", "reason")


def _pour_le_public(evt: dict) -> dict:
    """L'événement tel qu'on le LIT sur le site, tirets cadratins en moins.

    Le flux cognitif est une vitrine, mais ses événements n'ont jamais vu de
    filtre de sortie : `strip_stage_directions` sert les messages ADRESSÉS à
    quelqu'un, et une pensée n'est adressée à personne. Le panneau du site en
    était donc truffé le jour où les messages n'en avaient plus.

    Nettoyé au SERVICE et non à l'écriture, pour deux raisons : le fil que
    Wally se relit garde son texte d'origine, et l'historique déjà en base est
    couvert sans avoir à le réécrire.

    Une COPIE : le tampon du feed est partagé entre tous les abonnés SSE, et le
    nettoyer en place le ferait pour tout le monde, deux fois sur le même objet.
    """
    if not any(evt.get(c) for c in _CHAMPS_PROSE):
        return evt
    sortie = dict(evt)
    for champ in _CHAMPS_PROSE:
        valeur = sortie.get(champ)
        if isinstance(valeur, str):
            sortie[champ] = retirer_tirets_cadratins(valeur)
    return sortie


@public_router.get("/cognitive/state")
async def cognitive_state(request: Request):
    feed = getattr(request.app.state.wally, "cognitive_feed", None)
    if feed is None:
        return {"events": []}
    return {"events": [_pour_le_public(e) for e in feed.snapshot()]}


@public_router.get("/cognitive/history")
async def cognitive_history(request: Request, limit: int = 50, before: int | None = None):
    """Historique persistant du flux cognitif (#observability A6), paginé.
    `next_before` = plus petit id de la page → à repasser pour la page suivante."""
    store = getattr(request.app.state.wally, "cognitive_event_store", None)
    if store is None:
        return {"events": [], "next_before": None}
    limit = max(1, min(limit, 200))
    events = await store.recent(limit=limit, before_id=before)
    next_before = events[-1]["id"] if events else None
    return {"events": [_pour_le_public(e) for e in events], "next_before": next_before}


@public_router.get("/cognitive/goal")
async def cognitive_goal(request: Request):
    """But(s) courant(s) de Wally + préoccupation + désirs actifs (#observability A7)."""
    store = getattr(request.app.state.wally, "fact_store", None)
    if store is None:
        return {"goals": [], "preoccupation": None, "desires": []}
    from bot.intelligence.memory.facts import FactCategory, FactStatus
    goals = await store.search_by_category(FactCategory.GOAL, status=FactStatus.ACTIVE, limit=5)
    desires = await store.search_by_category(FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=5)
    focus = await store.get_latest_by_source("wally:self", "focus")
    return {
        "goals": [retirer_tirets_cadratins(g.content) for g in goals],
        "preoccupation": retirer_tirets_cadratins(focus.content) if focus else None,
        "desires": [retirer_tirets_cadratins(d.content) for d in desires],
    }


@public_router.get("/sse/cognitive")
async def cognitive_sse(request: Request):
    feed = getattr(request.app.state.wally, "cognitive_feed", None)

    async def gen():
        if feed is None:
            yield ": no-feed\n\n"
            return
        q = feed.subscribe()
        try:
            for evt in feed.snapshot():
                yield f"data: {json.dumps(_pour_le_public(evt), ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(_pour_le_public(evt), ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            feed.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
