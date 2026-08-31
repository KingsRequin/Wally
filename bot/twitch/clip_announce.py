# bot/twitch/clip_announce.py
"""Annonce d'un clip repéré par la veille, une fois sa vidéo disponible."""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from bot.intelligence.overlay_narrator import OverlayNarrator

# Attentes avant de renoncer à la vidéo, en SECONDES. Twitch documente un délai
# entre la création d'un clip pendant un live et la disponibilité de son asset :
# « indéterminé, typiquement de plusieurs minutes ». La veille interroge l'API
# toutes les vingt secondes, elle tombe donc sur un clip pas encore transcodé —
# l'overlay n'afficherait que la carte titre, alors que le même clip demandé
# plus tard part bien en vidéo.
#
# Le pas est ce qui compte, pas le plafond : c'est lui qui fixe combien de temps
# la vidéo reste PRÊTE sans qu'on le sache. Les paliers 30/60/90 laissaient
# jusqu'à 90 s de retard sur un asset déjà disponible. Ici 10 s la première
# minute — là où la plupart des clips arrivent — puis 20 s, jusqu'à 4 min
# cumulées. Au-delà, le clip n'est plus un moment frais et mieux vaut
# l'annoncer en carte que pas du tout.
#
# ⚠️ Chaque reprise est un appel à l'API GQL NON OFFICIELLE : resserrer encore
# reviendrait à la marteler pour gagner quelques secondes.
CLIP_VIDEO_RETRY_DELAYS = (10,) * 6 + (20,) * 9


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
            logger.debug("Overlay: vidéo du clip {s} indisponible : {e!r}", s=slug, e=exc)
            playable = None
        if playable:
            if attempt:
                logger.info(
                    "Overlay: vidéo du clip « {t} » prête après {n} reprise(s)",
                    t=title, n=attempt,
                )
            break

    video = (playable or {}).get("url", "")
    affiche = narrator.show_clip(
        title,
        author,
        embed_url=clip.get("embed_url") or "",
        video_url=video,
        duration=(playable or {}).get("duration") or clip.get("duration") or 0.0,
    )
    # Le chemin automatique était muet, là où l'appel explicite journalise : on
    # ne pouvait pas savoir si un clip était parti en vidéo ou en carte nue.
    #
    # Mais le journal doit dire ce qui est RÉELLEMENT parti à l'écran :
    #   — `show_clip` rend False si le live s'est coupé pendant la préparation
    #     (jusqu'à 3 min de reprises) : rien n'a été publié ;
    #   — une URL de vidéo ne suffit pas à la jouer, elle doit passer la liste
    #     blanche d'hôtes de `_is_clip_video`. Le chemin explicite fait déjà ce
    #     test (`played = self._is_clip_video(video)`) ; celui-ci se contentait
    #     de `if video`, et annonçait « joué » un clip tombé en carte nue.
    if not affiche:
        logger.info("Overlay: clip « {t} » non affiché (live terminé)", t=title)
        return
    joue = OverlayNarrator._is_clip_video(video) if video else False
    logger.info(
        "Overlay: clip « {t} » de {a} — {m}",
        t=title, a=author,
        m="joué" if joue else ("player en attente de clic"
                               if clip.get("embed_url") else "carte seule"),
    )


class VeilleDesClips:
    """Interroge Twitch et annonce les clips créés pendant le live.

    Extraite de `main()` le 2026-08-23 : c'était une closure de plus dans une
    fonction de mille lignes, donc du comportement qu'aucun test ne pouvait
    exécuter — alors qu'elle porte deux arbitrages payés en production.

    Twitch n'émet AUCUN événement EventSub à la création d'un clip (vérifié le
    2026-08-31 : aucun type de souscription ne porte ce nom) : la seule voie est
    d'interroger l'API régulièrement. Deux minutes ont longtemps semblé
    suffire — c'est vrai pour SIGNALER un clip, faux pour le REJOUER : le clip
    passe à l'écran pendant qu'on en parle encore, et deux minutes de retard
    tombent après la conversation. À vingt secondes, un GET Helix vaut 1 point
    sur les 800 par minute de la chaîne : trois par minute ne coûtent rien.

    `un_tour()` est séparé de `veiller()` pour la même raison que dans
    `PresenceDeStream` : une boucle `while True` avec un `sleep(20)` ne se
    teste pas, un tour se teste en une ligne.
    """

    #: La fenêtre demandée à Twitch. Plus large que la période, pour ne pas
    #: rater un clip créé pile entre deux tours.
    FENETRE_MIN = 5
    PERIODE_S = 20.0
    #: `deque(maxlen=...)` et PAS un `set` vidé d'un coup : le `clear()`
    #: oubliait TOUT alors que la fenêtre d'interrogation est de 5 min —
    #: jusqu'à 20 clips étaient réannoncés au tour suivant. Ici les plus vieux
    #: sortent un par un.
    MEMOIRE = 200

    def __init__(self, *, discord_bot: Any, twitch_bot: Any) -> None:
        self._discord = discord_bot
        self._twitch = twitch_bot
        self._vus: deque[str] = deque(maxlen=self.MEMOIRE)
        # Référence forte : l'annonce attend que Twitch ait fini de préparer le
        # clip, une tâche détachée serait ramassée par le GC entre-temps.
        self._taches: set[asyncio.Task] = set()

    async def veiller(self, *, periode: float | None = None) -> None:
        while True:
            await asyncio.sleep(self.PERIODE_S if periode is None else periode)
            await self.un_tour()

    async def un_tour(self) -> None:
        """Un passage. Ne lève jamais."""
        try:
            narrateur = getattr(self._discord, "overlay_narrator", None)
            if narrateur is None or not narrateur.is_active():
                return
            depuis = datetime.now(timezone.utc) - timedelta(minutes=self.FENETRE_MIN)
            clips = await self._twitch.twitch_api.get_recent_clips(
                depuis.strftime("%Y-%m-%dT%H:%M:%SZ")
            )
            neufs = []
            for clip in clips or []:
                cid = str(clip.get("id") or "")
                if not cid or cid in self._vus:
                    continue
                neufs.append(cid)
                # Le clip est REJOUÉ, pas seulement annoncé : muet, il occupe
                # l'écran le temps de la vidéo. L'annonce attend que Twitch ait
                # fini de le préparer, donc en tâche de fond — sinon la veille
                # resterait bloquée et les clips suivants passeraient à la
                # trappe.
                t = asyncio.create_task(
                    announce_clip(narrateur, self._twitch.twitch_api, clip)
                )
                self._taches.add(t)
                t.add_done_callback(self._taches.discard)
            self._vus.extend(neufs)
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            logger.warning("veille des clips en erreur: {e!r}", e=e)
