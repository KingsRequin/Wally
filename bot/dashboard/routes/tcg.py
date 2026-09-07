"""Les cartes du TCG, servies au site public.

Une seule route, en lecture. Tout le fond — les cartes ET leur mise en forme
pour le front (`en_json`) — vit dans `bot/core/tcg_cartes.py` : trois
consommateurs en ont besoin (cette route, l'échantillon du panneau de mise en
scène, et l'outil de Wally), et le format d'une carte appartient à la carte,
pas à l'une de ses sorties.
"""

from __future__ import annotations

from fastapi import APIRouter

from bot.core.tcg_cartes import CARTES, en_json

public_router = APIRouter()


@public_router.get("/tcg/cartes")
async def cartes() -> dict:
    """Les cartes terminées, dans l'ordre du registre.

    L'ordre compte : c'est celui de la collection à l'écran, et il dit dans
    quel ordre les cartes ont été finies.
    """
    return {"cartes": [en_json(c) for c in CARTES.values()]}
