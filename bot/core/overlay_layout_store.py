"""Le layout de l'overlay, rangé dans `bot_state`.

Une seule clé, un seul JSON — même patron que `apex:live_baseline` et le salon
vocal retenu. Séparé de `overlay_layout.py` pour que le modèle reste sans E/S,
donc testable sur des dictionnaires nus.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from bot.core.overlay_layout import fusionner, layout_par_defaut

LAYOUT_KEY = "overlay:layout"

# Quand la mise en scène est partie à l'antenne pour la dernière fois, en ISO
# local. Une clé À PART et pas un champ du modèle : `fusionner()` ignore ce
# qu'il ne connaît pas, et un champ que le panneau renverrait au PUT ferait
# dater la publication de la dernière ÉDITION du navigateur — pas de l'écriture.
MAJ_KEY = "overlay:layout:maj"

# L'application raisonne en Europe/Paris ; l'hôte est en UTC. Un horodatage naïf
# afficherait « publié à 19:14 » pour une publication de 21:14.
_FUSEAU = ZoneInfo("Europe/Paris")


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
        logger.warning("Overlay layout : lecture impossible ({e})", e=exc)
        return layout_par_defaut()
    if not brut:
        return layout_par_defaut()
    try:
        return fusionner(json.loads(brut))
    except (ValueError, TypeError) as exc:
        # Une écriture interrompue laisse du JSON tronqué. On le dit — un
        # layout perdu en silence se découvrirait des semaines plus tard.
        logger.warning("Overlay layout : JSON illisible, défauts repris ({e})", e=exc)
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
        logger.warning("Overlay layout : écriture impossible ({e})", e=exc)
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
        logger.warning("Overlay layout : date de publication illisible ({e})", e=exc)
        return None
