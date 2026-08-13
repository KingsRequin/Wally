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
            "ACTIONS : progression → ce qu'un joueur a GAGNÉ sur une période, "
            "avec sa COURBE jointe en image à ta réponse. C'est CETTE action "
            "qu'il faut quand on te demande une courbe, un graphe ou une "
            "progression dans la conversation — elle marche partout, live ou "
            "pas. Là où le canal porte les images (Discord), la courbe voyage "
            "avec ta réponse. Dans le CHAT TWITCH, qui ne porte que du texte, "
            "elle n'a qu'une sortie : l'écran du stream, via `show_apex` "
            "panel=progress — la réponse de cet outil te le dira quand c'est le "
            "cas, et alors tu l'affiches au lieu de t'excuser. "
            "Exemples : « combien de kills depuis le début du stream ? », "
            "« donne-moi la courbe de kills d'azra aujourd'hui », « et ce "
            "mois-ci ? ». Demande 'player_name' — LE JOUEUR VISÉ, à remplir dès "
            "que la question nomme quelqu'un (« la courbe d'azra » → "
            "player_name=azra) ; ne le laisse vide que pour la personne à qui "
            "tu réponds, sinon tu obtiens SA progression à elle et pas celle "
            "dont on parle. Demande aussi 'period' (live/jour/semaine/mois) et "
            "'notion' (kills par défaut). Ce chiffre vient de relevés que je "
            "prends au fil du temps, pas de l'API : il ne remonte pas avant le "
            "premier relevé, et la réponse le dit quand c'est le cas — reprends "
            "cette nuance, ne la gomme pas. · "
            "player_stats → profil d'un joueur (rang, niveau, état en "
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
            "player_name=Azraël ET legend=Fuse · "
            "« mon uid c'est 1002761549602 » → player_stats avec uid=… ET "
            "remember=true\n"
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
                        "progression",
                        "map_rotation",
                        "crafting",
                        "predator",
                        "server_status",
                    ],
                    "description": "La donnée voulue",
                },
                "period": {
                    "type": "string",
                    "description": (
                        "Sur quelle période compter, en clair : « stream » (le "
                        "live en cours, ou le dernier s'il est fini), « jour », "
                        "« semaine », « mois », ou une DURÉE libre — « 5m », "
                        "« 30min », « 2h », « 1h30 », « 3j ». Reprends ce qui "
                        "est demandé : « la courbe des 10 dernières minutes » "
                        "→ period=10m. Défaut « stream »."
                    ),
                },
                "notion": {
                    "type": "string",
                    "enum": ["kills", "wins", "damage", "matches", "headshots"],
                    "description": "Pour progression : quel compteur suivre (kills par défaut).",
                },
                "player_name": {
                    "type": "string",
                    "description": (
                        "Le pseudo du joueur visé — requis pour player_stats, "
                        "et tout aussi utile pour progression : « la courbe "
                        "d'azra » se demande avec player_name=azra. Vide = la "
                        "personne à qui tu réponds."
                    ),
                },
                "platform": {
                    "type": "string",
                    "enum": ["PC", "PS4", "X1"],
                    "description": "La plateforme, PC par défaut",
                },
                "uid": {
                    "type": "string",
                    "description": (
                        "L'identifiant numérique du compte Apex. À utiliser "
                        "quand la recherche par pseudo a échoué : l'API rate "
                        "des comptes bien réels, ce n'est pas une faute de "
                        "frappe. Il se lit sur apexlegendsstatus.com dans "
                        "l'adresse de la forme profile/uid/PC/1234567890 — tu "
                        "peux d'ailleurs me passer ce lien entier, j'en tire "
                        "le numéro. L'autre forme (profile/PC/pseudo) ne "
                        "contient pas d'uid et n'aide en rien. Donne aussi "
                        "player_name avec le pseudo employé : je retiens les "
                        "deux ensemble, et ce pseudo suffira les fois "
                        "suivantes. Combine-le avec remember=true si la "
                        "personne donne le SIEN."
                    ),
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
                    "enum": ["rank", "status", "stats", "progress", "map", "craft",
                             "predator", "servers"],
                    "description": (
                        "rank = le rang d'un joueur, avec son écusson · "
                        "status = est-il en partie, sur quelle légende · "
                        "stats = ses chiffres de carrière · "
                        "progress = sa courbe de progression AFFICHÉE À L'ÉCRAN "
                        "pour les spectateurs (utilise 'period' pour la "
                        "fenêtre). Pour répondre une courbe à quelqu'un DANS LA "
                        "CONVERSATION, ce n'est pas ce panneau : c'est "
                        "`apex_legends` action=progression, qui joint l'image et "
                        "fonctionne même hors live · "
                        "map = la rotation des cartes, avec le décompte · "
                        "craft = les lots du replicator · "
                        "predator = le seuil Predator · "
                        "servers = l'état des serveurs"
                    ),
                },
                "player": {
                    "type": "string",
                    "description": (
                        "Le pseudo du joueur visé, pour rank/status/stats ET "
                        "progress — « affiche la courbe d'azra » se demande "
                        "avec player=azra. Laisse vide UNIQUEMENT pour la "
                        "personne à qui tu réponds : sinon c'est SON compte qui "
                        "part à l'écran, pas celui dont on parle."
                    ),
                },
                "period": {
                    "type": "string",
                    "description": (
                        "Pour le panneau progress : la fenêtre de la courbe, en "
                        "clair — « stream » (défaut), « jour », « semaine », "
                        "« mois », ou une durée libre (« 10m », « 2h », « 3j »). "
                        "Colle à la demande : « la courbe de ce stream » ne doit "
                        "pas rendre une image de quinze heures."
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
