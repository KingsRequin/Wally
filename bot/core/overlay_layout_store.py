"""Le layout de l'overlay, rangé dans `bot_state`.

Une seule clé, un seul JSON — même patron que `apex:live_baseline` et le salon
vocal retenu. Séparé de `overlay_layout.py` pour que le modèle reste sans E/S,
donc testable sur des dictionnaires nus.
"""
from __future__ import annotations

import json
from datetime import datetime

from loguru import logger

from bot.core.overlay_layout import fusionner, layout_par_defaut

from bot.core.temps import PARIS

LAYOUT_KEY = "overlay:layout"

# Quand la mise en scène est partie à l'antenne pour la dernière fois, en ISO
# local. Une clé À PART et pas un champ du modèle : `fusionner()` ignore ce
# qu'il ne connaît pas, et un champ que le panneau renverrait au PUT ferait
# dater la publication de la dernière ÉDITION du navigateur — pas de l'écriture.
MAJ_KEY = "overlay:layout:maj"

# La graine des réglages de la galerie a-t-elle été semée ?
#
# Les quatre réglages d'affichage du widget `image` — durée, animations d'entrée
# et de sortie, durée d'animation — vivaient dans `config.yaml`
# (`overlay_image`), GLOBALEMENT, pendant que tous les autres widgets se
# réglaient par scène. Deux autorités sur la même question : c'est la signature
# de défaut que ce dépôt traque, et elle se referme ici.
#
# Un DRAPEAU et pas une comparaison aux défauts : sans lui, chaque boot
# écraserait le choix du streamer avec la valeur d'un fichier qu'il ne regarde
# plus, et il ne pourrait jamais rien régler durablement. Et comparer aux
# défauts ne dirait rien — régler `image` sur exactement la valeur livrée est
# une décision comme une autre.
GRAINE_IMAGE_KEY = "overlay:layout:image_migre"

# L'application raisonne en Europe/Paris ; l'hôte est en UTC. Un horodatage naïf
# afficherait « publié à 19:14 » pour une publication de 21:14.
_FUSEAU = PARIS
async def charger_layout(db) -> dict:
    """Le layout rangé, complété par les défauts. Ne lève jamais.

    `db` peut être `None` : la page est servie avant que le bot soit connecté,
    et elle ne doit pas attendre pour s'afficher.
    """
    if db is None:
        return layout_par_defaut()
    try:
        brut = await db.get_state(LAYOUT_KEY)
    except Exception as exc:  # noqa: BLE001 — une base muette n'efface pas l'overlay
        logger.warning("Overlay layout : lecture impossible ({e!r})", e=exc)
        return layout_par_defaut()
    if not brut:
        return layout_par_defaut()
    try:
        return fusionner(json.loads(brut))
    except (ValueError, TypeError) as exc:
        # Une écriture interrompue laisse du JSON tronqué. On le dit — un
        # layout perdu en silence se découvrirait des semaines plus tard.
        logger.warning("Overlay layout : JSON illisible, défauts repris ({e!r})", e=exc)
        return layout_par_defaut()


async def enregistrer_layout(db, brut) -> dict:
    """Valide, range, et rend ce qui a été rangé.

    La validation passe AVANT l'écriture : une valeur hors bornes rangée telle
    quelle y resterait jusqu'au prochain enregistrement, et serait servie entre
    les deux.
    """
    layout = fusionner(brut)
    if db is None:
        return layout
    try:
        await db.set_state(LAYOUT_KEY, json.dumps(layout, ensure_ascii=False))
        # APRÈS le modèle, dans le même `try` : une date posée sur une écriture
        # qui a échoué ferait dire au panneau « à l'antenne depuis 21:14 » alors
        # que l'antenne diffuse toujours l'ancienne.
        await db.set_state(MAJ_KEY, datetime.now(_FUSEAU).isoformat(timespec="seconds"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Overlay layout : écriture impossible ({e!r})", e=exc)
    return layout


async def date_maj(db) -> str | None:
    """Quand la mise en scène rangée est partie à l'antenne, ou `None`.

    `None` couvre trois cas qui se valent du point de vue du panneau : pas de
    base, jamais publié depuis que la date est suivie, ou lecture impossible.
    Chacun veut dire « on ne sait pas », et le panneau le dit ainsi plutôt que
    d'inventer une heure.
    """
    if db is None:
        return None
    try:
        return await db.get_state(MAJ_KEY) or None
    except Exception as exc:  # noqa: BLE001 — une date manquante n'efface rien
        logger.warning("Overlay layout : date de publication illisible ({e!r})", e=exc)
        return None


async def semer_reglages_image(db, config) -> bool:
    """Recopie UNE FOIS les réglages de `overlay_image` dans les trois scènes.

    Appelée au boot, et pas depuis `charger_layout` : celui-ci est sur le chemin
    public, appelé à chaque ouverture de page et à chaque redimensionnement de
    la source OBS. Y poser une migration coûterait une lecture de plus à chaque
    fois, et deux requêtes simultanées pourraient la jouer deux fois.

    Rend `True` si quelque chose a été semé — pour le dire dans les logs, une
    migration silencieuse se cherchant longtemps le jour où l'on se demande d'où
    vient une valeur.
    """
    if db is None:
        return False
    try:
        if await db.get_state(GRAINE_IMAGE_KEY):
            return False
    except Exception as exc:  # noqa: BLE001 — une base muette ne migre rien
        logger.warning("Overlay layout : graine `image` illisible ({e!r})", e=exc)
        return False

    img = getattr(config, "overlay_image", None)
    if img is None:
        # Pas de section : rien à semer, mais la graine est FAITE — sinon on
        # rouvrirait la question à chaque boot, pour rien.
        await _marquer_graine(db)
        return False

    graine = {
        "duree": getattr(img, "display_duration", 0) or 0,
        "anim_entree": getattr(img, "animation_in", "") or "",
        "anim_sortie": getattr(img, "animation_out", "") or "",
        "anim_duree": getattr(img, "animation_duration", 0) or 0,
    }
    try:
        layout = await charger_layout(db)
        for scene in layout["scenes"]:
            scene["elements"].setdefault("image", {}).update(graine)
        # `fusionner` borne ce qui vient du fichier : il s'édite à la main, et
        # une animation retirée d'animate.css ou une durée absurde doit y
        # reprendre son défaut comme tout ce qui entre dans ce modèle.
        range_ = fusionner(layout)
        # Écrit SANS passer par `enregistrer_layout` : celui-ci pose la date de
        # mise à l'antenne, et une graine n'est pas une publication. Le panneau
        # annoncerait « à l'antenne depuis 17:22 » pour une migration que
        # personne n'a demandée.
        await db.set_state(LAYOUT_KEY, json.dumps(range_, ensure_ascii=False))
        await _marquer_graine(db)
    except Exception as exc:  # noqa: BLE001 — un overlay mal réglé vaut mieux qu'un overlay mort
        logger.warning("Overlay layout : graine `image` impossible ({e!r})", e=exc)
        return False
    logger.info(
        "Overlay : réglages de la galerie repris de config.yaml vers les scènes "
        "({d} s, {i} → {o}) — ils se règlent désormais dans « Mise en scène »",
        d=graine["duree"], i=graine["anim_entree"], o=graine["anim_sortie"])
    return True


async def _marquer_graine(db) -> None:
    try:
        await db.set_state(GRAINE_IMAGE_KEY, "1")
    except Exception as exc:  # noqa: BLE001
        # Le pire cas est de resemer au prochain boot : on le dit, on continue.
        logger.warning("Overlay layout : drapeau de graine non posé ({e!r})", e=exc)
