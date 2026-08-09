# bot/dashboard/routes/twitch.py
from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()

# Cache module-level pour éviter les appels Twitch API à chaque requête.
_cache: dict = {"data": None, "fetched_at": 0.0, "is_live": False}

TTL_LIVE = 60      # secondes — statut live : refresh fréquent
TTL_OFFLINE = 300  # secondes — statut offline : refresh rare


@router.get("/twitch/stream")
async def get_stream_status(request: Request) -> dict:
    """Retourne le statut du stream Azrael_TTV avec cache TTL.

    TTL asymétrique : 60s si live (données changeantes), 5min si offline.
    Si twitch_api est None (Twitch désactivé), retourne offline immédiatement.
    """
    state = request.app.state.wally

    if state.twitch_api is None:
        return {"live": False, "title": None, "category": None, "viewers": 0, "started_at": None}

    now = time.time()
    ttl = TTL_LIVE if _cache["is_live"] else TTL_OFFLINE

    if _cache["data"] is not None and (now - _cache["fetched_at"]) < ttl:
        return _cache["data"]

    result = await state.twitch_api.get_stream()
    if result.get("unknown"):
        # « Je n'ai pas pu demander » n'est pas « hors ligne ». Mis en cache tel
        # quel, ce résultat portait `live: False`, donc le TTL choisi devenait
        # celui du hors-ligne : une coupure réseau d'une seconde figeait
        # l'affichage « hors ligne » pendant CINQ MINUTES en plein live, là où le
        # watcher, lui, retente au bout de 60 s.
        # On garde le dernier statut connu et on retentera au prochain appel.
        if _cache["data"] is not None:
            return _cache["data"]
        return {k: v for k, v in result.items() if k != "unknown"}

    _cache.update({
        "data": result,
        "fetched_at": now,
        "is_live": result.get("live", False),
    })
    return result
