# bot/core/overlay_elements.py
"""À quoi sert chaque élément de l'overlay, en français.

Les clés du modèle sont techniques (`apex_predator`, `clip_top`) et ne disent
rien au streamer qui règle son habillage. Ce module leur donne un nom lisible et
une phrase d'explication, affichés dans le panneau de mise en scène.

Source unique : à compléter en même temps qu'`ELEMENTS`, un test le vérifie.
"""

LIBELLES: dict[str, dict[str, str]] = {
    "apex_craft": {
        "nom": "Replicator Apex",
        "description": "Les lots d'objets actuellement proposés au replicator, "
                       "tels que rendus par l'API Apex, Wally ne recopie aucun "
                       "chiffre à la main.",
    },
    "apex_map": {
        "nom": "Rotation des cartes",
        "description": "La carte en cours et la suivante pour chaque mode "
                       "(Battle Royale, Ranked, mode temporaire, Wildcard), avec "
                       "un décompte qui tourne vraiment jusqu'au changement.",
    },
    "apex_predator": {
        "nom": "Seuil Prédateur",
        "description": "Le nombre de points de classement nécessaires pour "
                       "entrer dans le rang Prédateur, par plateforme (PC, PS4, "
                       "Xbox).",
    },
    "apex_progress": {
        "nom": "Courbe de progression Apex",
        "description": "Un graphique de l'évolution d'une statistique (les "
                       "kills par défaut) du joueur suivi sur une période "
                       "donnée, généré à la demande, absent tant qu'il n'y a "
                       "pas assez de relevés pour tracer une courbe.",
    },
    "apex_rank": {
        "nom": "Rang Apex",
        "description": "Le rang classé du joueur suivi, écusson, division et "
                       "points, avec sa position dans le ladder mondial quand "
                       "elle est connue.",
    },
    "apex_servers": {
        "nom": "État des serveurs Apex",
        "description": "L'état en ligne ou hors ligne des serveurs Apex "
                       "Legends, tel que publié par l'API officielle du jeu.",
    },
    "apex_stats": {
        "nom": "Stats de carrière Apex",
        "description": "Les statistiques de carrière du joueur suivi (kills, "
                       "dégâts, parties jouées…) allées chercher directement "
                       "sur l'API, sans passer par ce que Wally a pu lire.",
    },
    "apex_status": {
        "nom": "État en jeu Apex",
        "description": "Si le joueur suivi est actuellement en partie, sur "
                       "quelle légende et avec quel skin, plus son niveau de "
                       "compte.",
    },
    "avatar": {
        "nom": "Avatar de Wally",
        "description": "Wally lui-même, posé en bas à droite de l'écran ; il "
                       "s'anime davantage une seconde sur les gros moments du "
                       "live (raid, sub…).",
    },
    "bingo": {
        "nom": "Bingo du stream",
        "description": "La grille de pronostics que Wally compose sur ce qu'il "
                       "sait du streamer et coche au fur et à mesure de ce "
                       "qu'il constate en direct.",
    },
    "bubble": {
        "nom": "Bulle de pensée",
        "description": "La bulle de bande dessinée où Wally écrit ses "
                       "commentaires et réactions spontanées au fil du live.",
    },
    "clip": {
        "nom": "Alerte clip",
        "description": "Le clip Twitch demandé ou créé pendant le live, rejoué "
                       "en muet à l'écran avec le nom de son auteur.",
    },
    "clip_top": {
        "nom": "Podium des clips",
        "description": "Le classement des cinq clips les plus vus du mois, "
                       "affiché en tableau, sans lecture vidéo.",
    },
    "coinflip": {
        "nom": "Pile ou face",
        "description": "Une pièce qui tourne et retombe sur le résultat décidé "
                       "par Wally, qui peut le forcer s'il veut tricher.",
    },
    "countdown": {
        "nom": "Compte à rebours",
        "description": "Un anneau de temps qui s'éteint tiret par tiret "
                       "jusqu'à zéro, pour un minuteur (BRB, pause…) demandé à "
                       "Wally.",
    },
    "counter": {
        "nom": "Compteur affiché",
        "description": "Un texte court affiché à l'écran, sert par exemple à "
                       "montrer la durée du live ou le total d'un compteur "
                       "communautaire qui vient de monter.",
    },
    "dice": {
        "nom": "Lancer de dés",
        "description": "Un ou plusieurs dés (jusqu'à quatre) qui roulent et "
                       "s'arrêtent sur le résultat décidé par Wally.",
    },
    "gauge": {
        "nom": "Jauge de progression",
        "description": "Une barre qui se remplit vers un pourcentage, donné "
                       "directement par Wally, ou alimenté tout seul par un "
                       "objectif de follows, d'abonnements ou de bits au fil "
                       "des vrais événements du live.",
    },
    "hangman": {
        "nom": "Le pendu",
        "description": "Une partie de pendu : Wally choisit le mot, le chat "
                       "propose des lettres une par une, et la potence se "
                       "dessine trait par trait à chaque erreur.",
    },
    "image": {
        "nom": "Image de la galerie",
        "description": "Une image générée par IA tirée au hasard dans la "
                       "galerie du bot, affichée avec le nom de son créateur, "
                       "déclenchée par une commande de chat (`!image` par "
                       "défaut). Masquée, elle ne s'affiche pas et n'est pas "
                       "téléchargée.",
    },
    "meme": {
        "nom": "Meme de la communauté",
        "description": "Une image du dossier de memes de la chaîne, choisie "
                       "au hasard ou sur un thème demandé, que Wally peut "
                       "commenter.",
    },
    "apex_kills": {
        "nom": "Kills de la partie",
        "description": "Le bilan affiché à la fin de chaque partie d'Apex : "
                       "les kills de la game qui vient de se terminer, et le "
                       "cumul depuis le début du live. Une partie dont les "
                       "compteurs sont illisibles n'affiche rien.",
    },
    "music_now": {
        "nom": "Musique en cours",
        "description": "Le morceau qu'écoute le streamer, affiché quand "
                       "quelqu'un demande dans le chat ce qui passe. Il "
                       "cohabite : Wally reste à l'écran à côté.",
    },
    "pinned": {
        "nom": "Message épinglé",
        "description": "Un message du chat mis en avant à l'écran, avec le "
                       "nom de son auteur.",
    },
    "planning": {
        "nom": "Planning des streams",
        "description": "L'image fixe des horaires de stream, affichée en "
                       "plein cadre par-dessus l'avatar.",
    },
    "poll": {
        "nom": "Sondage du chat",
        "description": "Un sondage à deux à quatre options où le chat vote en "
                       "tapant un numéro, avec le dépouillement qui monte en "
                       "direct jusqu'au résultat final.",
    },
    "prediction": {
        "nom": "Pari de Wally",
        "description": "Le pronostic que Wally annonce sur l'issue d'une "
                       "partie, qu'il tranche lui-même une fois le résultat "
                       "connu, avec son score cumulé de paris justes et faux.",
    },
    "quote": {
        "nom": "Citation du live",
        "description": "Une réplique entendue en vocal que Wally a retenue et "
                       "ressort à l'écran, parfois bien plus tard, avec son "
                       "auteur.",
    },
    "raid": {
        "nom": "Alerte raid",
        "description": "L'annonce d'un raid Twitch, avec le nom du raideur et "
                       "le nombre de personnes qui débarquent.",
    },
    "rotator": {
        "nom": "Rotateur de memes",
        "description": "Un défilement en boucle, autonome et indépendant de "
                       "Wally, des images et vidéos du dossier de memes de la "
                       "chaîne. Masqué, il ne défile pas et ne télécharge "
                       "rien ; le bouton ▶ le fait passer au média suivant.",
    },
    "rps": {
        "nom": "Duel de chifoumi",
        "description": "Un pierre-feuille-ciseaux entre Wally et le coup "
                       "majoritaire voté par le chat, animé puis tranché "
                       "sur-le-champ.",
    },
    "stats": {
        "nom": "Fiche stats joueur",
        "description": "Une petite fiche de lignes « libellé : valeur » que "
                       "Wally rédige lui-même à propos d'un joueur, à ne pas "
                       "confondre avec les panneaux Apex, dont les chiffres "
                       "sont allés chercher automatiquement.",
    },
    "talkers": {
        "nom": "Top des bavards",
        "description": "Le podium des personnes qui ont le plus parlé dans le "
                       "chat depuis le début du live.",
    },
    "versus": {
        "nom": "Face-à-face chiffré",
        "description": "Deux joueurs (ou deux camps) comparés sur une valeur "
                       "chiffrée avec des barres proportionnelles, sert aussi "
                       "à suivre un duel Apex manche après manche.",
    },
    "virus_popup": {
        "nom": "Spam de popups virus",
        "description": "De fausses fenêtres système et des memes en pièce "
                       "jointe s'ouvrent de plus en plus vite et s'empilent "
                       "jusqu'à saturer l'écran, puis un écran bleu nettoie "
                       "tout. Variante de l'avalanche, il prend l'écran seul.",
    },
    "wave": {
        "nom": "Vague d'emotes",
        "description": "L'emote affichée en grand quand au moins quatre "
                       "personnes différentes le spamment dans le chat en "
                       "quelques secondes.",
    },
    "wheel": {
        "nom": "Roue du hasard",
        "description": "Une roue à deux à huit options qui tourne et "
                       "s'arrête sur le choix décidé par Wally.",
    },
}
