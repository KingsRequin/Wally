"""« Wally, clippe les 40 dernières secondes et appelle-le kill au wingman ».

Le déclenchement AUTOMATIQUE a été refusé (fiche « REFUSÉ — Clip automatique
sur vague d'emotes », trop de faux positifs) : ce qui reste, et qui est demandé,
c'est le clip à la DEMANDE. Quelqu'un a vu le moment, il le dit, Wally clippe.

Arbitrages de l'owner, le 2026-09-01 :

  · **tout le monde peut demander** — pas de réserve aux modérateurs, contrairement
    à `say_in_voice`. Le chat repère des moments que le streamer ne voit pas.
  · **deux minutes de cooldown, pour la CHAÎNE** et pas par personne. La fenêtre
    de capture de Twitch fait ~90 s : deux clips plus rapprochés se chevauchent
    et racontent le même moment. Le cooldown n'est donc pas là pour freiner les
    gens, il est là parce que le second clip serait le même que le premier.

Hors des adapters pour la raison habituelle (`twitch/handlers.py` importe déjà
`discord/handlers`, y loger l'outil ferait un cycle) et parce que ce module
n'est QU'un outil : `tests/test_tools_rangement.py` tient la règle.
"""
from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger

from bot.tools.follow_tool import api_twitch

# Deux minutes, pour toute la chaîne. Cf. l'en-tête : c'est la fenêtre de
# capture de Twitch qui fixe ce chiffre, pas une politesse.
COOLDOWN_S = 120.0

# Dernière création réussie, en temps MONOTONE — jamais rangé en base : un
# cooldown de deux minutes ne survit pas utilement à un redémarrage, et le
# `monotonic` relu d'un autre process donnerait une durée absurde (piège déjà
# payé sur l'uptime du bot).
_dernier_clip_a: float = 0.0


CLIP_TOOL = {
    "type": "function",
    "function": {
        "name": "create_clip",
        "description": (
            "Clipper le live EN COURS, quand quelqu'un te le demande (« clippe "
            "ça », « fais un clip », « garde ce moment »). Le clip capture ce "
            "qui VIENT de se passer, pas ce qui va se passer : Twitch remonte "
            "dans le direct. N'invente jamais l'URL du clip — elle est dans le "
            "retour de l'outil, recopie-la telle quelle."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Le titre du clip, 60 caractères max. Reprends celui "
                        "qu'on te donne. Si personne n'en propose, écris-en un "
                        "court qui dit ce qui vient de se passer."
                    ),
                },
                "duration": {
                    "type": "integer",
                    "description": (
                        "Durée en secondes, de 5 à 60. Omets pour 30 s, qui "
                        "est le bon choix par défaut. Une demande plus longue "
                        "est ramenée à 60 s : dis-le si ça arrive."
                    ),
                },
            },
        },
    },
}


def _reste(maintenant: float) -> float:
    """Secondes de cooldown restantes. 0 quand c'est ouvert."""
    return max(0.0, COOLDOWN_S - (maintenant - _dernier_clip_a))


async def run_clip_tool(bot: Any, args: dict, *, author: str = "",
                        vocal: bool = False) -> str:
    """Crée le clip et rend son URL, ou dit pourquoi il n'y en a pas.

    Chaque refus porte un `message` rédigé pour être DIT : un outil qui rend
    `{"status": "error"}` nu laisse le modèle inventer une explication, et il
    invente en général qu'il n'a pas la capacité.

    `vocal=True` retire l'URL du rendu : à voix haute elle serait ÉPELÉE
    (« h-t-t-p-s deux-points barre barre… »), inaudible et inutilisable. On ne
    compte pas sur le modèle pour se retenir de lire un champ qu'on lui donne —
    la description de l'outil lui dit justement de le recopier tel quel.
    """
    global _dernier_clip_a

    api = api_twitch(bot)
    if api is None:
        return json.dumps({"status": "unavailable",
                           "message": "L'API Twitch n'est pas disponible."})

    if (reste := _reste(time.monotonic())) > 0:
        return json.dumps({"status": "cooldown", "reste_s": int(reste), "message": (
            f"Un clip vient d'être pris il y a moins de deux minutes : le "
            f"suivant montrerait le même moment. Encore {int(reste)} s.")})

    duree_demandee = int(args.get("duration") or 0)
    clip = await api.create_clip(str(args.get("title") or ""), duree_demandee)
    if clip is None:
        return json.dumps({"status": "failed", "message": (
            "Le clip n'a pas abouti. Soit le live ne tourne pas, soit Twitch "
            "n'a pas fini de le fabriquer. Ne donne AUCUNE URL.")})

    # Posé seulement maintenant : un échec ne doit pas consommer le cooldown,
    # sinon une panne de deux minutes se transforme en quatre.
    _dernier_clip_a = time.monotonic()
    logger.info("Clip créé à la demande de {a} : {u}",
                a=author or "quelqu'un", u=clip.get("url") or "")

    rendu = {"status": "ok", "url": clip.get("url") or "",
             "title": clip.get("title") or ""}
    # La durée RÉELLE, quand elle n'est pas celle demandée : Twitch borne à 60 s
    # et Wally doit pouvoir le dire au lieu de laisser croire qu'il a eu les
    # deux minutes réclamées.
    if duree_demandee and duree_demandee > api.CLIP_DUREE_MAX_S:
        rendu["duree_reelle_s"] = api.CLIP_DUREE_MAX_S
        rendu["message"] = (
            f"Twitch ne sait pas remonter plus loin que "
            f"{api.CLIP_DUREE_MAX_S} s : le clip fait ça, pas "
            f"{duree_demandee} s. Dis-le.")
    # EN DERNIER, et pas au moment où `rendu` est construit : le bornage de
    # durée ci-dessus pose son propre `message` et effacerait celui-ci.
    if vocal:
        del rendu["url"]
        rendu["message"] = " ".join(filter(None, (
            rendu.get("message"),
            "Ne DIS PAS l'adresse du clip à voix haute, elle est illisible à "
            "l'oral : dis simplement que c'est clippé, on retrouve le lien sur "
            "la chaîne.")))
    return json.dumps(rendu)
