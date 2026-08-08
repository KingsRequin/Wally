# bot/twitch/clip_announce.py
"""Annonce d'un clip repéré par la veille, une fois sa vidéo disponible."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger

# Attentes avant de renoncer à la vidéo, en SECONDES. Twitch documente un délai
# entre la création d'un clip pendant un live et la disponibilité de son asset :
# « indéterminé, typiquement de plusieurs minutes ». La veille interroge l'API
# toutes les deux minutes, elle tombait donc systématiquement sur un clip pas
# encore transcodé — l'overlay n'affichait que la carte titre, alors que le même
# clip demandé plus tard partait bien en vidéo.
#
# Plafonné à ~3 min cumulées : au-delà, le clip n'est plus un moment frais et
# mieux vaut l'annoncer en carte que pas du tout.
CLIP_VIDEO_RETRY_DELAYS = (30, 60, 90)


async def announce_clip(
    narrator,
    api,
    clip: dict,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Montre un clip à l'overlay, en laissant à Twitch le temps de le préparer.

    Affiche UNE seule fois : ré-annoncer à chaque tentative ferait clignoter le
    même clip à l'écran. Sans vidéo au bout des reprises, on annonce quand même
    — le clippeur mérite qu'on le signale, et `show_clip` sait retomber sur le
    player puis sur la carte.
    """
    slug = str(clip.get("id") or "")
    title = clip.get("title") or "un clip"
    author = clip.get("creator_name") or "quelqu'un"

    playable = None
    for attempt, delay in enumerate((0, *CLIP_VIDEO_RETRY_DELAYS)):
        if delay:
            await sleep(delay)
        if not narrator.is_active():
            return  # le live s'est arrêté pendant l'attente
        try:
            playable = await api.get_clip_video_url(slug)
        except Exception as exc:  # noqa: BLE001 — une API muette ne casse rien
            logger.debug("Overlay: vidéo du clip {s} indisponible : {e}", s=slug, e=exc)
            playable = None
        if playable:
            if attempt:
                logger.info(
                    "Overlay: vidéo du clip « {t} » prête après {n} reprise(s)",
                    t=title, n=attempt,
                )
            break

    video = (playable or {}).get("url", "")
    narrator.show_clip(
        title,
        author,
        embed_url=clip.get("embed_url") or "",
        video_url=video,
        duration=(playable or {}).get("duration") or clip.get("duration") or 0.0,
    )
    # Le chemin automatique était muet, là où l'appel explicite journalise : on
    # ne pouvait pas savoir si un clip était parti en vidéo ou en carte nue.
    logger.info(
        "Overlay: clip « {t} » de {a} — {m}",
        t=title, a=author,
        m="joué" if video else ("player en attente de clic"
                                if clip.get("embed_url") else "carte seule"),
    )
