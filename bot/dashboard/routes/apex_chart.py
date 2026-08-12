# bot/dashboard/routes/apex_chart.py
"""La courbe de progression Apex, rendue à la demande.

Route publique : c'est un `<img src>` dans l'overlay, chargé par OBS, qui ne
porte ni cookie ni jeton. Elle ne révèle rien de plus que le panneau de stats
déjà affiché à l'écran — des compteurs de jeu publics.

Elle reçoit un INSTANT de départ, pas un mot de période : « ce stream » ne veut
rien dire ici (le dashboard ignore quand le live a commencé), et deux calculs de
fenêtre séparés laisseraient passer une carte que cette route refuserait ensuite
de tracer. Le titre se reconstruit à partir d'une clé de liste blanche : rien de
ce qui arrive par l'URL n'est dessiné tel quel dans l'image.

Rendue à la volée plutôt qu'écrite sur disque : un fichier temporaire par
demande, c'est un cycle de vie à gérer, un répertoire à purger et des images
périmées servies après coup. Le tracé coûte moins d'une seconde.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from loguru import logger

from bot.core.apex.periode import CLES, MAX_DUREE_S, MIN_DUREE_S

public_router = APIRouter()

NOTIONS = ("kills", "wins", "damage", "matches", "headshots")


@public_router.get("/apex/progression.png")
async def progression_png(
    request: Request,
    uid: str = Query(..., min_length=1, max_length=32),
    depuis: float = Query(...),
    notion: str = Query("kills"),
    libelle: str = Query("duree"),
) -> Response:
    """Le PNG de la progression d'un compte, ou 404 si rien à tracer."""
    # Un uid Apex est purement numérique. Valider ici évite qu'un paramètre
    # d'URL arbitraire descende jusqu'à une requête SQL.
    if not uid.isdigit():
        raise HTTPException(status_code=400, detail="uid invalide")
    if notion not in NOTIONS or libelle not in CLES:
        raise HTTPException(status_code=400, detail="compteur ou fenêtre inconnu")
    maintenant = time.time()
    # Une fenêtre hors bornes ne vient pas de nous : elle est refusée plutôt que
    # rabotée en silence, sinon l'image montrerait une autre période que la
    # carte qui la porte.
    age = maintenant - depuis
    if not (MIN_DUREE_S <= age <= MAX_DUREE_S):
        raise HTTPException(status_code=400, detail="fenêtre hors bornes")

    state = request.app.state.wally
    db = getattr(state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="base indisponible")

    import asyncio

    from bot.core.apex.chart import libelle as libelle_notion
    from bot.core.apex.chart import render
    from bot.core.apex.history import ApexHistory
    from bot.core.apex.periode import libelle_de

    # Instance neuve plutôt qu'un service partagé : `ApexHistory` ne garde
    # d'état que pour ÉCRIRE (la dernière valeur vue, pour éviter les doublons).
    # En lecture, elle n'a besoin que de la base — et `AppState` ne porte pas le
    # service Apex, qui vit sur les adaptateurs.
    history = ApexHistory(db)

    try:
        progression = await history.progression(uid, notion, depuis)
    except Exception as exc:  # noqa: BLE001 — l'overlay ne casse pas pour un graphe
        logger.warning("Apex chart: progression illisible: {e}", e=exc)
        raise HTTPException(status_code=503, detail="historique illisible") from exc
    if progression is None:
        logger.info("Apex chart: aucun relevé pour {uid} ({n}, {p})",
                    uid=uid, n=notion, p=libelle)
        raise HTTPException(status_code=404, detail="aucun relevé")

    # Le RP sur la même fenêtre : c'est lui qui distingue les parties classées,
    # le mode d'une partie n'existant nulle part dans l'API. Une panne de cette
    # lecture ne doit pas coûter l'image — la courbe reste simplement monochrome.
    try:
        rp = await history.rp_de_la_fenetre(uid, depuis)
    except Exception as exc:  # noqa: BLE001 — sans RP la courbe se trace quand même
        logger.warning("Apex chart: relevés de RP illisibles: {e}", e=exc)
        rp = []

    fenetre = libelle_de(libelle, depuis, maintenant=maintenant)
    titre = f"{libelle_notion(notion).capitalize()} — {fenetre}"
    # En thread : matplotlib bloque, et cette route partage la boucle avec tout
    # le reste du bot.
    buf = await asyncio.to_thread(render, progression.points, notion, titre, rp=rp)
    if buf is None:
        logger.info("Apex chart: {n} relevé(s) pour {uid} — trop peu pour tracer",
                    n=len(progression.points), uid=uid)
        raise HTTPException(status_code=404, detail="pas assez de relevés")
    # Une ligne par image servie : c'est la seule preuve qu'une carte de courbe
    # est bien arrivée jusqu'à l'écran d'OBS. Sans elle, « il n'a rien affiché »
    # ne se distingue pas de « je n'ai pas regardé au bon moment ».
    logger.info("Apex chart servi: uid={uid} ({n}, {p}, {k} points)",
                uid=uid, n=notion, p=fenetre, k=len(progression.points))
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        # Le live bouge : une image mise en cache par OBS montrerait une
        # progression figée.
        headers={"Cache-Control": "no-store"},
    )
