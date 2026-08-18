"""L'outil qui donne la musique d'Azraël à Wally, depuis le chat Twitch.

Deux droits bien distincts, et c'est voulu :

  · **Dire ce qui passe** est ouvert à tous — c'est de la lecture.
  · **Piloter** est réservé aux modérateurs et au streamer. Un viewer qui
    essaie se fait charrier, et le refus le DIT au modèle : sans consigne, Wally
    répondrait par un « non » plat là où l'owner veut une vanne.

L'autorisation vient des BADGES du message réel, jamais du modèle — sinon il
suffirait d'écrire « je suis modo ». Même vocabulaire que `say_in_voice`, où le
broadcaster porte « admin » et non « moderator ».
"""
from __future__ import annotations

from loguru import logger

from bot.core.music import ACTIONS

# `now` n'est pas une commande du lecteur : c'est une lecture, et elle
# n'appartient donc pas à l'énuméré du service.
_LECTURE = "now"

# Les rôles qui donnent le droit de PILOTER, dans le vocabulaire de
# `_resolve_twitch_roles` — où le broadcaster est « admin ».
_ROLES_AUTORISES = {"moderator", "admin"}

MUSIC_TOOL = {
    "type": "function",
    "function": {
        "name": "music_control",
        "description": (
            "La musique qu'Azraël écoute pendant le live. Sert à DEUX choses. "
            "1) Dire ce qui passe (`now`) : n'importe qui peut le demander "
            "(« c'est quoi la musique ? »). "
            "2) Piloter la lecture (`play`, `pause`, `next`, `prev`, "
            "`play_query`) : seuls un MODÉRATEUR ou le streamer y ont droit — "
            "appelle quand même l'outil si un viewer le demande, tu sauras quoi "
            "répondre. Utilise `play_query` avec le titre demandé pour lancer un "
            "morceau précis (« mets du Linkin Park »)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": sorted(ACTIONS | {_LECTURE}),
                    "description": "Ce qu'il faut faire.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Avec `play_query` seulement : le titre, l'artiste ou "
                        "le lien YouTube demandé."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}


def _dire_ce_qui_passe(etat: dict | None) -> str:
    """La réponse à « c'est quoi la musique ? ».

    « Je ne sais pas » et « rien ne joue » sont deux réponses OPPOSÉES :
    l'extension peut être éteinte ou l'onglet fermé. Le service rend `None` dans
    ce cas, et on ne le traduit pas en silence.
    """
    if not etat:
        return ("Tu ne sais pas ce qui passe en ce moment — le lecteur d'Azraël "
                "ne te dit rien (extension coupée, ou rien d'ouvert). Dis-le "
                "franchement, ne devine pas.")
    titre = etat.get("titre") or ""
    artiste = etat.get("artiste") or ""
    morceau = f"{artiste} — {titre}" if artiste else titre
    if not etat.get("joue"):
        return (f"En pause sur « {morceau} ». Dis-le en une phrase, à ta sauce.")
    return f"Ça joue : « {morceau} ». Dis-le en une phrase, à ta sauce."


async def run_music_tool(bot, args: dict, *, roles=None, maison: bool = True,
                         pilotable: bool = True, narrateur=None) -> str:
    """Lit ou pilote la musique. Rend ce que le modèle lira.

    Ne ment jamais sur le résultat : `commander()` attend l'accusé de
    l'extension, et son échec remonte tel quel jusqu'au chat.

    `pilotable=False` sur les chemins SANS badge Twitch (Discord) : dire ce qui
    passe y reste ouvert — c'est une lecture, et le §10 la veut pour tout le
    monde — mais le pilotage n'y a aucun moyen de vérifier un droit. Le refus
    doit alors ORIENTER plutôt que charrier : un membre du Discord qui demande
    la musique suivante n'a rien tenté de louche, il n'est simplement pas au bon
    endroit.
    """
    action = str((args or {}).get("action") or "").strip()
    service = getattr(bot, "music", None)
    if service is None:
        return ("Impossible : le suivi de la musique n'est pas branché sur ce "
                "bot. Dis-le à la personne.")

    if action == _LECTURE:
        etat = service.etat()
        # « Wally le DIT et l'AFFICHE » (§10). L'écran ne conditionne jamais la
        # réponse : un bus overlay en panne, une chaîne invitée ou un salon
        # Discord n'ont pas d'affichage, et la personne obtient son titre quand
        # même.
        if etat and narrateur is not None:
            try:
                narrateur.show_music(etat.get("titre") or "",
                                     etat.get("artiste") or "",
                                     joue=bool(etat.get("joue")))
            except Exception as exc:  # noqa: BLE001 — l'écran ne doit rien casser
                logger.warning("Musique : affichage impossible : {e}", e=exc)
        return _dire_ce_qui_passe(etat)

    if action not in ACTIONS:
        return (f"Refusé : tu ne connais pas l'action « {action or '(vide)'} ». "
                "Dis à la personne ce que tu sais faire : lecture, pause, "
                "suivante, précédente, ou lancer un titre.")

    if not pilotable:
        return ("Impossible ici : la musique se pilote depuis le chat Twitch "
                "pendant le live, là où les badges de modérateur existent. "
                "Dis-le gentiment, ce n'est pas un refus.")

    # La musique tourne sur le PC d'Azraël, pour SON live : une chaîne invitée
    # ne la commande pas. Même garde que le vocal et l'overlay.
    if not maison:
        return ("Refusé : la musique appartient au live d'Azraël, on ne la "
                "commande pas depuis une chaîne invitée. Dis-le simplement.")

    if not (set(roles or ()) & _ROLES_AUTORISES):
        return ("Refusé : cette personne n'est ni modérateur ni le streamer, "
                "elle n'a pas le droit de toucher à la musique. Moque-toi "
                "gentiment d'elle dans le chat, en une phrase.")

    resultat = await service.commander(action, str((args or {}).get("query") or ""))
    if not resultat.get("ok"):
        raison = resultat.get("raison") or "ça n'a pas marché"
        logger.info("Musique : « {a} » refusée — {r}", a=action, r=raison)
        return (f"Ça n'a PAS marché : {raison}. Dis-le à la personne, sans "
                "prétendre que c'est fait.")

    titre = (resultat.get("titre") or "").strip()
    logger.info("Musique : « {a} » exécutée{t}", a=action,
                t=f" → {titre}" if titre else "")
    if titre:
        return f"C'est fait, ça joue maintenant « {titre} ». Confirme en une phrase."
    return "C'est fait. Confirme en une phrase, à ta sauce."
