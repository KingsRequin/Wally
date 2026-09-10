# bot/discord/clip_post.py
"""Les clips du live, republiés dans un salon Discord.

La veille (`bot/twitch/clip_announce.py`) interroge Helix toutes les vingt
secondes et joue les clips neufs sur l'overlay. Ce module se branche au MÊME
instant : le clip part à l'écran et dans le salon Discord d'un seul geste, sans
second appel à l'API ni seconde source de vérité sur « quels clips existent ».

⚠️ **Un clip publié deux fois est le défaut à éviter ici.** La mémoire de la
veille (`_vus`) est une `deque` en RAM : elle meurt à chaque rebuild, et il y
en a plusieurs par soirée de live. Comme la fenêtre demandée à Twitch fait cinq
minutes, un redémarrage rejouait donc jusqu'à vingt clips — sans conséquence
sur l'overlay (l'écran est éphémère), mais un salon Discord GARDE ce qu'on y
met. D'où le rangement en base, dans `bot_state`.

Et il n'est PAS borné à la session (`EtatPersistant` l'aurait fait) : un clip
republié le lendemain reste un doublon.

⚠️ Un message en Components V2 n'affiche AUCUN aperçu automatique d'URL — le
lecteur Twitch que Discord déplie sur un lien nu n'existe pas ici. La carte
porte donc la vignette du clip en galerie, et le lien reste un lien : on clique
pour regarder.
"""
from __future__ import annotations

import json
from collections import deque
from typing import Any

import discord
from loguru import logger

from bot.discord.fiches import fiche

#: Le violet de Twitch. Un accent par PROVENANCE : ces cartes ne viennent pas
#: du bot mais de la chaîne.
ACCENT_TWITCH = 0x9146FF

#: La clé de `bot_state` qui porte les ids déjà publiés.
CLE_ETAT = "clips_publies_discord"

#: Combien d'ids on garde. Large : un id fait 40 octets, et oublier un clip
#: coûte un doublon visible par tout le serveur.
MEMOIRE = 500

#: Twitch sert cette image tant que le clip n'est pas transcodé. Postée telle
#: quelle, elle resterait DÉFINITIVEMENT dans le salon — Discord met en cache
#: ce qu'il a proxyfié, il ne repasse jamais voir si la vraie vignette est
#: arrivée.
MARQUEUR_VIGNETTE_ABSENTE = "404_processing"


def _duree(clip: dict) -> str:
    try:
        secondes = int(float(clip.get("duration") or 0))
    except (TypeError, ValueError):
        return ""
    return f"{secondes} s" if secondes > 0 else ""


def carte_de_clip(clip: dict) -> discord.ui.LayoutView:
    """La fiche Components V2 d'un clip.

    Séparée de l'envoi pour être testable sans Discord : c'est la moitié qui
    porte le rendu, et la seule qu'on regarde quand la carte est fausse.
    """
    titre = discord.utils.escape_markdown(str(clip.get("title") or "").strip()) or "Un clip"
    auteur = discord.utils.escape_markdown(str(clip.get("creator_name") or "").strip())
    url = str(clip.get("url") or "").strip()

    entete = f"Clippé par **{auteur}**" if auteur else "Nouveau clip"
    duree = _duree(clip)
    if duree:
        entete += f" · {duree}"
    corps = [entete, url] if url else [entete]

    vignette = str(clip.get("thumbnail_url") or "").strip()
    medias = [vignette] if vignette and MARQUEUR_VIGNETTE_ABSENTE not in vignette else []

    return fiche(f"🎬 {titre}", corps, accent=ACCENT_TWITCH, medias=medias)


class PublicationDesClips:
    """Republie dans Discord les clips que l'overlay vient de jouer.

    `charger()` se fait au boot, `publier()` à chaque clip. Ni l'un ni l'autre
    ne lève : un salon injoignable ne doit pas emporter la veille avec lui.
    """

    def __init__(self, *, discord_bot: Any, db: Any, config: Any) -> None:
        self._discord = discord_bot
        self._db = db
        self._config = config
        self._publies: deque[str] = deque(maxlen=MEMOIRE)

    def _salon_configure(self) -> int | None:
        return self._config.discord.clips_channel_id

    async def _lire(self) -> list[str]:
        """Les ids rangés en base. `[]` si la clé est absente ou illisible."""
        if self._db is None:
            return []
        try:
            brut = await self._db.get_state(CLE_ETAT)
            ids = json.loads(brut) if brut else []
        except Exception as exc:  # noqa: BLE001 — une base muette ne doit pas bloquer le live
            logger.warning("Clips Discord : mémoire illisible ({e!r})", e=exc)
            return []
        if not isinstance(ids, list):
            logger.warning("Clips Discord : mémoire de forme inattendue, ignorée")
            return []
        return [str(i) for i in ids if i]

    async def charger(self) -> None:
        """Relit les ids déjà publiés. Ne lève jamais."""
        self._publies.extend(await self._lire())
        logger.info("Clips Discord : {n} clip(s) déjà publié(s) en mémoire",
                    n=len(self._publies))

    async def _ranger(self) -> None:
        """Range la mémoire en FUSIONNANT avec ce qui est déjà en base.

        Écraser avec la seule `deque` de ce process serait un piège : le script
        de rattrapage (`scripts/rattraper_clips_discord.py`) écrit sur la MÊME
        clé, et le premier clip du live suivant effacerait son travail — les
        clips rattrapés repartiraient en doublon. Deux écrivains sur une clé, ça
        se fusionne ; sinon ça se répare avec un « ne pas oublier de
        redémarrer », et on oublie.
        """
        if self._db is None:
            return
        fusion = await self._lire()
        for cid in self._publies:
            if cid not in fusion:
                fusion.append(cid)
        fusion = fusion[-MEMOIRE:]
        try:
            await self._db.set_state(CLE_ETAT, json.dumps(fusion))
        except Exception as exc:  # noqa: BLE001 — le clip est parti, l'oubli n'annule rien
            logger.warning("Clips Discord : mémoire non rangée ({e!r})", e=exc)
            return
        # Reprendre la fusion : c'est par là que ce process apprend ce qu'un
        # rattrapage a publié dans son dos.
        self._publies = deque(fusion, maxlen=MEMOIRE)

    async def _salon(self, salon_id: int):
        salon = self._discord.get_channel(salon_id)
        if salon is None:
            salon = await self._discord.fetch_channel(salon_id)
        return salon

    async def publier(self, clip: dict) -> bool:
        """Poste le clip. Rend True s'il vient d'être publié. Ne lève jamais."""
        salon_id = self._salon_configure()
        if not salon_id or self._discord is None:
            return False

        cid = str(clip.get("id") or "")
        if not cid:
            logger.warning("Clips Discord : clip sans id, non publié")
            return False
        if cid in self._publies:
            logger.info("Clips Discord : « {t} » déjà publié, ignoré",
                        t=clip.get("title") or cid)
            return False

        try:
            salon = await self._salon(salon_id)
            if salon is None:
                logger.warning("Clips Discord : salon {s} introuvable", s=salon_id)
                return False
            await salon.send(view=carte_de_clip(clip))
        except Exception as exc:  # noqa: BLE001 — un salon muet ne casse pas la veille
            logger.warning("Clips Discord : envoi impossible ({e!r})", e=exc)
            return False

        # Après l'envoi SEULEMENT : marquer avant ferait qu'un échec réseau
        # perde le clip pour de bon, alors qu'il repassera au tour suivant.
        self._publies.append(cid)
        await self._ranger()
        logger.info("Clips Discord : « {t} » publié dans {s}",
                    t=clip.get("title") or cid, s=salon_id)
        return True
