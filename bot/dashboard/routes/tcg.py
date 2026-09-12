"""Les cartes du TCG, servies au site public.

Deux routes, en lecture, une par famille. Tout le fond — les cartes ET leur
mise en forme pour le front (`en_json`) — vit dans `bot/core/tcg_cartes.py` et
`bot/core/tcg_cartes_action.py` : plusieurs consommateurs en ont besoin (ces
routes, l'échantillon du panneau de mise en scène, et l'outil de Wally), et le
format d'une carte appartient à la carte, pas à l'une de ses sorties.

🚨 Deux routes et pas une seule avec un filtre. Un héros et une carte action
n'ont aucun champ en commun au-delà du nom : les fondre en une réponse
donnerait des objets dont les deux tiers des clés sont nulles, et un front qui
devrait deviner à quelle famille il a affaire avant de savoir quoi lire.
"""

from __future__ import annotations

from fastapi import APIRouter

from bot.core.tcg_cartes import en_json, par_prestige
from bot.core.tcg_cartes_action import en_json as en_json_action
from bot.core.tcg_cartes_action import par_categorie

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


@public_router.get("/tcg/cartes-action")
async def cartes_action() -> dict:
    """Les cartes ACTION et PASSIF, rangées par catégorie.

    L'ordre est celui de la planche du design : les familles se suivent, et à
    l'intérieur d'une famille l'ordre d'écriture du fichier est gardé. Il est
    posé par `par_categorie()` et pas par la page — le rang d'une carte
    appartient à la carte.
    """
    return {"cartes": [en_json_action(c) for c in par_categorie()]}
