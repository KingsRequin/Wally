# bot/dashboard/routes/apex_chart.py
"""La courbe de progression Apex, rendue à la demande.

Route publique : c'est un `<img src>` dans l'overlay, chargé par OBS, qui ne
porte ni cookie ni jeton. Elle ne révèle rien de plus que le panneau de stats
déjà affiché à l'écran — des compteurs de jeu publics.

Rendue à la volée plutôt qu'écrite sur disque : un fichier temporaire par
demande, c'est un cycle de vie à gérer, un répertoire à purger et des images
périmées servies après coup. Le tracé coûte moins d'une seconde.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from loguru import logger

public_router = APIRouter()

PERIODES = ("live", "jour", "semaine", "mois")
NOTIONS = ("kills", "wins", "damage", "matches", "headshots")


@public_router.get("/apex/progression.png")
async def progression_png(
    request: Request,
    uid: str = Query(..., min_length=1, max_length=32),
    period: str = Query("live"),
    notion: str = Query("kills"),
) -> Response:
    """Le PNG de la progression d'un compte, ou 404 si rien à tracer."""
    # Un uid Apex est purement numérique. Valider ici évite qu'un paramètre
    # d'URL arbitraire descende jusqu'à une requête SQL.
    if not uid.isdigit():
        raise HTTPException(status_code=400, detail="uid invalide")
    if period not in PERIODES or notion not in NOTIONS:
        raise HTTPException(status_code=400, detail="période ou compteur inconnu")

    state = request.app.state.wally
    history = getattr(getattr(state, "apex_api", None), "history", None)
    if history is None:
        raise HTTPException(status_code=503, detail="historique indisponible")

    import asyncio
    import time

    from bot.core.apex.chart import libelle, render
    from bot.core.apex.history import debut_de_periode

    depuis = (time.time() - 12 * 3600) if period == "live" else debut_de_periode(period)
    try:
        progression = await history.progression(uid, notion, depuis)
    except Exception as exc:  # noqa: BLE001 — l'overlay ne casse pas pour un graphe
        logger.warning("Apex chart: progression illisible: {e}", e=exc)
        raise HTTPException(status_code=503, detail="historique illisible") from exc
    if progression is None:
        raise HTTPException(status_code=404, detail="aucun relevé")

    titre = f"{libelle(notion).capitalize()} — {period}"
    # En thread : matplotlib bloque, et cette route partage la boucle avec tout
    # le reste du bot.
    buf = await asyncio.to_thread(render, progression.points, notion, titre)
    if buf is None:
        raise HTTPException(status_code=404, detail="pas assez de relevés")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        # Le live bouge : une image mise en cache par OBS montrerait une
        # progression figée.
        headers={"Cache-Control": "no-store"},
    )
