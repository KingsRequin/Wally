"""« Tu coûtes combien ? » — la réponse vient de `cost_log`, jamais de lui.

Wally ne dit plus son prix de lui-même (l'alerte publique a été éteinte le
2026-08-31 à la demande de l'owner : elle n'a rien à faire dans un salon, elle
n'est ni une nouvelle ni une conversation). Mais **la question, elle, se pose** —
elle s'est posée le 2026-08-30 dans sa chambre, « Wsh il coute chère le wally ».
Sans cet outil il n'a que deux issues : inventer un chiffre, ou dire qu'il n'y a
pas accès alors que la table est complète et à jour (98 957 lignes de `cost_log`).

## Le calcul appartient au code

Même règle que `follow_tool._duree_depuis` et `humeur_passee_tool` : le modèle
calcule mal, et un chiffre faux sur ce sujet-là se retient. Il reçoit des
montants déjà arrondis en dollars et déjà nommés — jamais un horodatage, jamais
une somme à faire.

Trois fenêtres, parce qu'elles ne disent pas la même chose : les dernières
24 h (« aujourd'hui »), les 30 derniers jours (ce qui a réellement été dépensé)
et la projection du rythme de la semaine sur un mois. La projection est
l'indicateur qui a servi à voir la dérive de DeepSeek — 8,23 $ sur 7 jours,
soit 35,26 $/mois, quand les 30 jours écoulés n'affichaient que 22,93 $.

⚠️ Base vide → `None` et pas 0,00 $, qui se lirait « ça ne coûte rien » alors
que ça veut dire « on ne sait pas encore ». Repris tel quel de
`cout_veille.projection_mensuelle`, pour la même raison.
"""
from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger

COUT_TOOL = {
    "type": "function",
    "function": {
        "name": "mon_cout",
        "description": (
            "Ce que tu coûtes réellement, en dollars : les dernières 24 h, les "
            "30 derniers jours, et ce que donnerait le rythme de la semaine sur "
            "un mois. Sers-t'en UNIQUEMENT quand on te pose la question (« tu "
            "coûtes combien ? », « ça coûte cher un Wally ? », « t'as coûté "
            "combien ce mois-ci ? »). N'aborde JAMAIS le sujet de toi-même : "
            "personne n'a envie d'entendre une facture au milieu d'une "
            "conversation. Et n'invente aucun montant — s'il n'y a rien en "
            "base, dis simplement que tu ne sais pas."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


async def run_cout_tool(bot: Any, args: dict) -> str:
    """Les trois montants, déjà arrondis et nommés. Ne lève jamais."""
    db = getattr(bot, "db", None)
    if db is None:
        return json.dumps({"erreur": "pas de base, je ne peux pas savoir"},
                          ensure_ascii=False)
    maintenant = time.time()
    try:
        jour = await db.get_cost_since(maintenant - 86_400)
        mois = await db.get_cost_since(maintenant - 30 * 86_400)
    except Exception as exc:  # noqa: BLE001 — un outil ne casse jamais la réponse
        logger.warning("mon_cout : lecture de cost_log impossible : {e!r}", e=exc)
        return json.dumps({"erreur": "je n'arrive pas à lire mes dépenses"},
                          ensure_ascii=False)

    # La même projection que la veille : une seule définition du « rythme »,
    # sinon deux chiffres différents circuleraient pour la même chose.
    from bot.core.cout_veille import projection_mensuelle

    projection = await projection_mensuelle(db)

    if not mois and projection is None:
        return json.dumps(
            {"reponse": "aucune dépense enregistrée, je ne sais pas encore ce "
                        "que je coûte"},
            ensure_ascii=False)
    return json.dumps({
        "dernieres_24h_usd": round(jour, 2),
        "30_derniers_jours_usd": round(mois, 2),
        "projection_mensuelle_usd": round(projection, 2) if projection is not None else None,
        "note": "montants en dollars, tout fournisseur confondu (texte, images, "
                "vision, voix). Dis-les simplement, sans en faire un sujet.",
    }, ensure_ascii=False)
