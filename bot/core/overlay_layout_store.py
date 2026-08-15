"""Le layout de l'overlay, rangé dans `bot_state`.

Une seule clé, un seul JSON — même patron que `apex:live_baseline` et le salon
vocal retenu. Séparé de `overlay_layout.py` pour que le modèle reste sans E/S,
donc testable sur des dictionnaires nus.
"""
from __future__ import annotations

import json

from loguru import logger

from bot.core.overlay_layout import fusionner, layout_par_defaut

LAYOUT_KEY = "overlay:layout"


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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Overlay layout : écriture impossible ({e})", e=exc)
    return layout
