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
            "jeu, kills et rang mondial, ET ses chiffres PAR LÉGENDE). Demande "
            "'player_name' et 'platform' (PC par défaut) ; laisse 'player_name' "
            "VIDE pour « mes stats », le compte déjà mémorisé de la personne "
            "sera utilisé. Ajoute 'legend' pour le détail d'une légende précise "
            "(« combien de kills avec Fuse ? »). · "
            "map_rotation → cartes en cours et suivantes. · "
            "crafting → lots du replicator. · predator → seuil pour Predator. · "
            "server_status → état des serveurs.\n"
            "CE QUE CETTE API NE DONNE PAS : le classement en tant que TABLEAU "
            "(top 500, palmarès par légende), l'historique des matchs, la "
            "boutique, les nouveautés du jeu — et AUCUN classement par PAYS, "
            "quelle que soit la formulation : cette notion n'existe nulle part "
            "dans les données. Ne la cherche pas ailleurs, dis-le franchement. "
            "En revanche tu as, pour chaque chiffre d'un joueur, sa position "
            "MONDIALE et sa position sur SA PLATEFORME (PC, PS4, Xbox) — c'est "
            "le classement le plus fin dont tu disposes, propose-le à la place. "
            "Les kills d'un joueur AVEC une légende donnée sont eux aussi "
            "disponibles — ne les confonds pas avec un palmarès. Si on te le demande, dis-le "
            "simplement et propose à la place la position et le top % du joueur "
            "via player_stats — ne cherche pas ailleurs, aucun site ne te le "
            "donnera dans un format exploitable.\n"
            "UTILISE : « c'est quoi le rank de Daltoosh ? » → player_stats · "
            "« quelle map en ce moment ? » → map_rotation · "
            "« mon pseudo Apex c'est Xyz » → player_stats avec player_name=Xyz "
            "ET remember=true, pour ne plus jamais le redemander · "
            "« j'ai combien de kills ? » → player_stats avec player_name VIDE, "
            "son compte est déjà connu · "
            "« Azraël il a combien de kills avec Fuse ? » → player_stats avec "
            "player_name=Azraël ET legend=Fuse\n"
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
                "legend": {
                    "type": "string",
                    "description": (
                        "Une légende (« Fuse », « Wraith »…) pour n'avoir que "
                        "SES chiffres avec celle-là. Sans ce paramètre, tu "
                        "reçois son podium et la liste des légendes qu'il suit. "
                        "Une légende absente de cette liste n'a pas zéro kill : "
                        "le joueur n'a simplement pas épinglé le compteur."
                    ),
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


# L'affichage à l'écran est un outil À PART, comme `show_last_clip` : la donnée
# se récupère sur le réseau, ce que le `show_overlay` générique — synchrone — ne
# sait pas faire. Wally nomme un panneau, le serveur va chercher les chiffres :
# c'est ce qui garantit qu'aucune valeur ne transite par le modèle.
APEX_OVERLAY_TOOL = {
    "type": "function",
    "function": {
        "name": "show_apex",
        "description": (
            "Affiche des données Apex RÉELLES sur l'overlay du stream. Ne "
            "fonctionne que pendant un live — l'outil te le dira sinon. Tu n'as "
            "aucun chiffre à fournir : nomme le panneau, le reste est allé le "
            "chercher. ⚠️ L'overlay est vu par les SPECTATEURS : ton `comment` "
            "s'adresse à eux. Ne prétends jamais avoir affiché sans appeler cet "
            "outil."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "panel": {
                    "type": "string",
                    "enum": ["rank", "status", "stats", "map", "craft", "predator", "servers"],
                    "description": (
                        "rank = le rang d'un joueur, avec son écusson · "
                        "status = est-il en partie, sur quelle légende · "
                        "stats = ses chiffres de carrière · "
                        "map = la rotation des cartes, avec le décompte · "
                        "craft = les lots du replicator · "
                        "predator = le seuil Predator · "
                        "servers = l'état des serveurs"
                    ),
                },
                "player": {
                    "type": "string",
                    "description": (
                        "Le pseudo, pour rank/status/stats. Laisse vide pour la "
                        "personne à qui tu réponds si elle a déjà déclaré son compte."
                    ),
                },
                "comment": {
                    "type": "string",
                    "description": "Ta réplique, quelques mots — c'est elle qu'on lit.",
                },
            },
            "required": ["panel"],
        },
    },
}
