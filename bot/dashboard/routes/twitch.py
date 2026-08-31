# bot/dashboard/routes/twitch.py
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

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


# Les clips de la chaîne, pour la page publique `/clips`. Cache à part de celui
# du live : la fenêtre et la fraîcheur utile n'ont rien à voir.
_clips_cache: dict = {"data": None, "fetched_at": 0.0}

TTL_CLIPS = 120  # secondes — un clip fraîchement créé apparaît en deux minutes
FENETRE_CLIPS_J = 90  # Helix n'a pas de « tous les clips » : il faut une borne


def _clip_public(clip: dict) -> dict:
    """Ne garde du clip Helix que ce que la page affiche.

    Le reste (`broadcaster_id`, `video_id`, `game_id`, `vod_offset`…) n'a aucun
    usage à l'écran : le publier reviendrait à exposer plus que nécessaire pour
    rien. L'`id` est le slug — le front en construit l'URL d'embed, plutôt que
    de recevoir une URL entière à poser dans un `iframe`.
    """
    return {
        "id": str(clip.get("id") or ""),
        "title": str(clip.get("title") or ""),
        "creator": str(clip.get("creator_name") or ""),
        "created_at": str(clip.get("created_at") or ""),
        "duration": float(clip.get("duration") or 0.0),
        "views": int(clip.get("view_count") or 0),
        "thumbnail_url": str(clip.get("thumbnail_url") or ""),
        "url": str(clip.get("url") or ""),
    }


@router.get("/twitch/clips")
async def get_clips(request: Request) -> dict:
    """Les clips de la chaîne des 90 derniers jours, du plus récent au plus vieux.

    ⚠️ Helix trie par nombre de VUES, jamais par date (cf. `get_last_clip`) : le
    tri par date se fait ici, sur les 100 clips que renvoie l'API. Servir la
    liste telle quelle donnerait « les plus vus » sous un titre qui promet
    « les derniers ».
    """
    state = request.app.state.wally
    if state.twitch_api is None:
        return {"clips": []}

    now = time.time()
    if _clips_cache["data"] is not None and (now - _clips_cache["fetched_at"]) < TTL_CLIPS:
        return {"clips": _clips_cache["data"]}

    since = datetime.now(timezone.utc) - timedelta(days=FENETRE_CLIPS_J)
    bruts = await state.twitch_api.get_recent_clips(
        since.strftime("%Y-%m-%dT%H:%M:%SZ"), first=100
    )
    clips = [_clip_public(c) for c in bruts if c.get("id")]
    clips.sort(key=lambda c: c["created_at"], reverse=True)

    # Une liste VIDE n'est pas mise en cache : `get_recent_clips` rend `[]` aussi
    # bien quand la chaîne n'a rien clippé que quand l'appel a échoué (401, 500,
    # réseau). Figer ce vide deux minutes ferait d'une panne d'une seconde une
    # page vide pour tout le monde — le même piège que le statut du live juste
    # au-dessus, payé une fois déjà.
    if clips:
        _clips_cache.update({"data": clips, "fetched_at": now})
    return {"clips": clips}
