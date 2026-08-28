"""« Depuis quand tu suis la chaîne ? » — la date vient de Twitch, jamais de lui.

Hors des adapters pour que les DEUX plateformes puissent l'offrir : `twitch/
handlers.py` importe déjà `discord/handlers`, donc y loger l'outil ferait un
cycle. Ce module a d'abord atterri dans `bot/core/` pour cette seule raison —
un contournement, pas un choix — avant que `bot/tools/` existe pour l'accueillir.

Le besoin vient des traces : « wally je follow la chaine dpuis quand? » →
« Pas de date de follow dans mon dossier, j'ai pas accès à ça ». C'était faux —
le scope `moderator:read:followers` était déjà sur le token du bot.
"""
from __future__ import annotations

import json
from typing import Any


FOLLOW_TOOL = {
    "type": "function",
    "function": {
        "name": "follow_date",
        "description": (
            "Depuis quand quelqu'un suit la chaîne. Sers-t'en quand on te "
            "demande son ancienneté (« je follow depuis quand ? », « ça fait "
            "combien de temps que je suis là ? »), ou pour situer un habitué "
            "face à un nouveau. La date vient de Twitch : ne l'invente JAMAIS, "
            "et ne devine pas une ancienneté à partir de tes souvenirs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": (
                        "Le pseudo Twitch de la personne. Laisse VIDE pour "
                        "celui qui te parle — c'est le cas courant."
                    ),
                },
            },
        },
    },
}


def _duree_depuis(iso_utc: str) -> str:
    """« 1 an et 4 mois », depuis un `followed_at` Helix (UTC, suffixe Z).

    Le modèle calcule mal les écarts de dates et rendrait « depuis 2023 » pour
    un follow de mars 2025. On lui donne la durée DÉJÀ faite ; il n'a plus qu'à
    la tourner à sa façon.
    """
    from datetime import datetime, timezone

    quand = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    jours = max((datetime.now(timezone.utc) - quand).days, 0)
    if jours < 31:
        return f"{jours} jour(s)"
    mois = jours // 30
    if mois < 12:
        return f"{mois} mois"
    return f"{mois // 12} an(s) et {mois % 12} mois"


def api_twitch(bot: Any) -> Any:
    """L'API Twitch, vue depuis l'une OU l'autre plateforme.

    `WallyTwitch` la porte directement ; `WallyDiscord` ne l'a que via
    `_twitch_bot`, comme le font déjà les podiums de clips (`discord/bot.py`).
    Sans ce double chemin, l'outil sortirait du catalogue Discord au montage et
    n'y reviendrait jamais — un outil offert nulle part, sans rien pour le dire.
    """
    return (getattr(bot, "twitch_api", None)
            or getattr(getattr(bot, "_twitch_bot", None), "twitch_api", None))


async def run_follow_tool(bot: Any, args: dict, *,
                          platform: str, user_id: str, author: str) -> str:
    """Depuis quand une personne suit la chaîne maison.

    Sans `user`, c'est le demandeur — mais seulement si son identité est un id
    TWITCH. Sur le chemin vocal, `user_id` est un snowflake Discord : l'envoyer
    à Helix rendrait une liste vide, donc « tu ne suis pas la chaîne », à
    quelqu'un qui la suit depuis deux ans. Un faux négatif qu'aucun log
    n'aurait signalé — on demande le pseudo à la place.
    """
    api = api_twitch(bot)
    if api is None:
        return json.dumps({"status": "unavailable",
                           "message": "L'API Twitch n'est pas disponible."})

    pseudo = str(args.get("user") or "").strip().lstrip("@")
    if pseudo:
        cible_id = await api.get_broadcaster_id(pseudo.lower())
        if not cible_id:
            return json.dumps({"status": "not_found", "message":
                               f"Aucun compte Twitch nommé « {pseudo} »."})
        nom = pseudo
    elif platform == "twitch":
        cible_id, nom = str(user_id), author
    else:
        return json.dumps({"status": "need_user", "message": (
            "Tu ne parles pas sur Twitch là : je ne sais pas à quel compte "
            "Twitch rattacher la personne. Demande-lui son pseudo Twitch.")})

    infos = await api.get_follow_date(cible_id)
    if infos is None:
        return json.dumps({"status": "error", "message": (
            "Twitch n'a pas répondu — dis que tu n'arrives pas à vérifier, "
            "surtout ne conclus PAS qu'elle ne suit pas la chaîne.")})
    if not infos:
        return json.dumps({"status": "not_following",
                           "message": f"{nom} ne suit pas la chaîne."})
    quand = infos["followed_at"]
    return json.dumps({"status": "ok", "user": nom, "followed_at": quand,
                       "depuis": _duree_depuis(quand)})
