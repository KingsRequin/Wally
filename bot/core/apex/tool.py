# bot/core/apex/tool.py
"""Le schéma de l'outil Apex présenté au LLM.

La description dit aussi ce que l'API NE donne PAS. Le 2026-08-07, faute de
cette phrase, une question sur le top 3 mondial a envoyé le modèle sur trois
`web_search` et un `scrape_url` avant de saturer la boucle d'outils.
"""

APEX_LEGENDS_TOOL = {
    "type": "function",
    "function": {
        "name": "apex_legends",
        "description": (
            "Données Apex Legends. À n'utiliser que pour une question précise sur "
            "le jeu ou sur un joueur.\n"
            "ACTIONS : player_stats → profil d'un joueur (rang, niveau, état en "
            "jeu, kills et rang mondial). Demande 'player_name' et 'platform' "
            "(PC par défaut) ; laisse 'player_name' VIDE pour « mes stats », le "
            "compte déjà mémorisé de la personne sera utilisé. · "
            "map_rotation → cartes en cours et suivantes. · "
            "crafting → lots du replicator. · predator → seuil pour Predator. · "
            "server_status → état des serveurs.\n"
            "CE QUE CETTE API NE DONNE PAS : le classement mondial (top 500, "
            "classement par légende ou par pays), l'historique des matchs, la "
            "boutique, les nouveautés du jeu. Si on te le demande, dis-le "
            "simplement et propose à la place la position et le top % du joueur "
            "via player_stats — ne cherche pas ailleurs, aucun site ne te le "
            "donnera dans un format exploitable.\n"
            "UTILISE : « c'est quoi le rank de Daltoosh ? » → player_stats · "
            "« quelle map en ce moment ? » → map_rotation\n"
            "N'UTILISE PAS : « Apex c'est nul » → une opinion, pas une demande de "
            "données."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "player_stats",
                        "map_rotation",
                        "crafting",
                        "predator",
                        "server_status",
                    ],
                    "description": "La donnée voulue",
                },
                "player_name": {
                    "type": "string",
                    "description": "Le pseudo Apex, requis pour player_stats",
                },
                "platform": {
                    "type": "string",
                    "enum": ["PC", "PS4", "X1"],
                    "description": "La plateforme, PC par défaut",
                },
                "remember": {
                    "type": "boolean",
                    "description": (
                        "true UNIQUEMENT quand la personne déclare SON PROPRE "
                        "pseudo Apex (« mon pseudo c'est X », « je joue sur "
                        "PS4 sous Y »). Son compte est alors retenu et tu ne "
                        "lui redemanderas plus jamais. Jamais true pour le "
                        "pseudo de quelqu'un d'autre."
                    ),
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}
