"""Les cartes du TCG, servies au site public.

Une seule route, en lecture. Tout le fond — les cartes ET leur mise en forme
pour le front (`en_json`) — vit dans `bot/core/tcg_cartes.py` : trois
consommateurs en ont besoin (cette route, l'échantillon du panneau de mise en
scène, et l'outil de Wally), et le format d'une carte appartient à la carte,
pas à l'une de ses sorties.
"""

from __future__ import annotations

from fastapi import APIRouter

from bot.core.tcg_cartes import en_json, par_prestige

public_router = APIRouter()


@public_router.get("/tcg/cartes")
async def cartes() -> dict:
    """Les cartes, de la plus haute à la plus basse.

    L'ordre compte : c'est celui de la collection à l'écran. Il n'est PLUS
    celui du fichier depuis le 2026-09-09 — le fichier garde l'ordre de
    finition, et `par_prestige()` le reclasse. Le tri est fait ici et pas dans
    la page : le rang d'une carte appartient à la carte, et une page qui le
    recalculerait finirait par en avoir sa propre idée.
    """
    return {"cartes": [en_json(c) for c in par_prestige()]}
