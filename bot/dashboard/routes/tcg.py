"""Les cartes du TCG, servies au site public.

Une seule route, en lecture. La source est `bot/core/tcg_cartes.py` ; ce module
ne fait que la mettre en forme pour le front — et décider de ce qui SORT.
"""

from __future__ import annotations

from fastapi import APIRouter

from bot.core import tcg_cartes
from bot.core.tcg_cartes import CarteTcg

public_router = APIRouter()


def _publier(carte: CarteTcg) -> dict:
    """Une carte telle que le front la lit.

    🚨 Les clés partent en **camelCase** : c'est le vocabulaire que le composant
    de rendu lit déjà (`heroCote`, `avantPlanBas`…). Renommer de son côté
    ferait toucher le rendu pendant un refactor dont le critère est « rien ne
    change à l'écran ».

    🚨 Les **alias ne sortent pas**. Cette route est publique : tout ce qu'elle
    rend part à n'importe quel visiteur, et la liste des fautes d'orthographe
    qu'on accepte sur un pseudo n'a rien à y faire.

    Les illustrations sortent **versionnées** par l'empreinte de leur contenu
    (`tcg_cartes.url`) : la zone Cloudflare écrase le `Cache-Control` de
    l'origine, et sans ça une illustration retouchée resterait quatre heures
    figée chez chaque visiteur.
    """
    return {
        "cle": carte.cle,
        "nom": carte.nom,
        "legende": carte.legende,
        "classe": carte.classe,
        "ultime": carte.ultime,
        "description": carte.description,
        "ambiance": carte.ambiance,
        "cout": carte.cout,
        "atk": carte.atk,
        "pv": carte.pv,
        "aura": carte.aura,
        "accent": carte.accent,
        "hero": tcg_cartes.url(carte.hero),
        "fond": tcg_cartes.url(carte.fond),
        # `None` et non `""` : le front teste la présence, et une chaîne vide
        # est fausse en JavaScript sans pour autant dire « absent ».
        "avantPlan": tcg_cartes.url(carte.avant_plan) if carte.avant_plan else None,
        "hero3d": tcg_cartes.url(carte.hero_3d) if carte.hero_3d else None,
        "heroCote": carte.hero_cote,
        "heroHaut": carte.hero_haut,
        "heroEchelle": carte.hero_echelle,
        "hero3dCote": carte.hero_3d_cote,
        "hero3dHaut": carte.hero_3d_haut,
        "avantPlanLargeur": carte.avant_plan_largeur,
        "avantPlanBas": carte.avant_plan_bas,
        "particules": carte.particules,
        "parallaxe": carte.parallaxe,
        "intensite": carte.intensite,
    }


@public_router.get("/tcg/cartes")
async def cartes() -> dict:
    """Les cartes terminées, dans l'ordre du registre.

    L'ordre compte : c'est celui de la collection à l'écran, et il dit dans
    quel ordre les cartes ont été finies.
    """
    return {"cartes": [_publier(c) for c in tcg_cartes.CARTES.values()]}
