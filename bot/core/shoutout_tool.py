"""« so @machin » — la carte cliquable de la chaîne, pas une phrase qui la cite.

`POST /helix/chat/shoutouts` déclenche le shoutout NATIF : l'aperçu de la chaîne
s'affiche chez tous les viewers, avec le jeu, cliquable. C'est autre chose qu'un
message qui dit « allez voir untel ».

Rangé ici et non dans `twitch/handlers.py` pour la même raison que
`follow_tool.py` : ce module-là importe déjà `discord/handlers`, et l'inverse
ferait un cycle. On lui emprunte d'ailleurs `api_twitch`.

Deux gardes viennent de Twitch et non de nous, ce qui est rare : un shoutout
toutes les 2 minutes, et 60 minutes avant de refaire le même. Le sur-usage est
donc impossible par construction — il n'y a rien à concevoir pour s'en protéger,
seulement à DIRE quand la cadence mord.
"""
from __future__ import annotations

import json
from typing import Any

from bot.core.follow_tool import api_twitch
from bot.core.self_trace import note_act


SHOUTOUT_TOOL = {
    "type": "function",
    "function": {
        "name": "shoutout",
        "description": (
            "Faire un shoutout Twitch officiel : la carte de la chaîne "
            "s'affiche dans le chat de tout le monde, cliquable, avec le jeu et "
            "l'aperçu. Sers-t'en quand on te demande de mettre quelqu'un en "
            "avant (« so @machin », « faut aller voir untel »), ou après un "
            "raid pour renvoyer l'ascenseur. Twitch n'en accepte qu'un toutes "
            "les 2 minutes, et un seul par heure sur la même chaîne : ce n'est "
            "pas à toi de compter, l'outil te le dira. Ça ne remplace pas ce "
            "que tu as à dire sur la personne — la carte montre, toi tu parles."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": "Le pseudo Twitch de la chaîne à mettre en avant.",
                },
            },
            "required": ["user"],
        },
    },
}


async def run_shoutout_tool(bot: Any, args: dict) -> str:
    """Résout le pseudo puis publie le shoutout. Le refus remonte INTACT.

    Le motif rendu par `send_shoutout` est passé tel quel au modèle : un
    cooldown avalé ferait annoncer un shoutout qui n'a pas eu lieu, exactement
    le défaut que `send_message` a payé en enrichissant mémoire et prélude
    d'une réplique jamais partie.
    """
    api = api_twitch(bot)
    if api is None:
        return json.dumps({"status": "unavailable",
                           "message": "L'API Twitch n'est pas disponible."})

    pseudo = str(args.get("user") or "").strip().lstrip("@").lower()
    if not pseudo:
        return json.dumps({"status": "need_user", "message": (
            "Dis-moi QUI mettre en avant — il me faut un pseudo Twitch.")})

    cible = await api.get_broadcaster_id(pseudo)
    if not cible:
        return json.dumps({"status": "not_found", "message":
                           f"Aucune chaîne Twitch nommée « {pseudo} »."})

    motif = await api.send_shoutout(cible)
    if motif:
        return json.dumps({"status": "refused", "message":
                           f"Le shoutout n'est pas parti : {motif}"})
    # Un geste PUBLIC de plus, donc un geste qu'il doit se rappeler avoir fait :
    # sans ça il redemande deux minutes plus tard et se prend le cooldown sans
    # comprendre d'où il sort.
    note_act(f"tu as fait un shoutout Twitch officiel pour {pseudo}")
    return json.dumps({"status": "ok", "message": (
        f"La carte de {pseudo} est affichée dans le chat de tout le monde. "
        "Dis maintenant pourquoi il faut aller la voir — la carte montre, "
        "toi tu parles.")})
