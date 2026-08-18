# Wally — musique du live

Une extension Chrome pour **Azraël**. Elle dit à Wally ce qui passe sur YouTube,
et laisse les modérateurs piloter la lecture depuis le chat Twitch.

## Ce qu'elle fait, et ce qu'elle ne fait pas

- Elle regarde **l'onglet YouTube** : le titre du morceau, son artiste, et si ça
  joue ou non.
- Elle envoie ça à Wally toutes les deux secondes, **et rien d'autre** : pas
  l'historique, pas les autres onglets, pas les recherches.
- Elle applique les ordres que les modos donnent à Wally : lecture, pause,
  suivante, précédente, lancer un titre.
- **Interrupteur éteint = rien ne sort.** Ni titre, ni adresse. C'est le premier
  réglage de la fenêtre, il prend effet immédiatement.
- Elle ne peut emmener le navigateur **que sur YouTube** : un lien vers autre
  chose est refusé.

## Installation

1. Récupérer ce dossier (`extension-musique/`) et le poser où il restera —
   Chrome le relit à chaque démarrage, un dossier supprimé désactive
   l'extension.
2. Ouvrir `chrome://extensions`.
3. Activer **Mode développeur** (en haut à droite).
4. **Charger l'extension non empaquetée**, puis choisir ce dossier.
5. Cliquer sur l'icône de l'extension (épingler la puzzle-pièce aide) :
   - **Adresse du bot** : `https://heywally.fr`
   - **Jeton** : demandé à KingsRequin — il ne se trouve nulle part ailleurs.
   - Cocher **Partager ce que j'écoute**.
6. Cliquer **Enregistrer** : le bouton essaie vraiment la connexion et affiche
   `C'est branché ✓`, ou dit ce qui cloche.

Puis ouvrir une vidéo YouTube. Rien à faire de plus.

## Vérifier que ça marche

Dans le chat Twitch, demander à Wally ce qui passe. S'il répond qu'il ne sait
pas :

- l'interrupteur est-il allumé ?
- l'onglet YouTube est-il **ouvert et en lecture** ? Une vidéo en pause depuis
  plus de 45 secondes n'est plus « ce qui passe » ;
- le bouton **Enregistrer** dit-il `C'est branché ✓` ?

## Ce qui se passe si

- **Le bot redémarre** — l'extension réessaie toutes les deux secondes, il n'y a
  rien à faire.
- **Plusieurs onglets YouTube sont ouverts** — les ordres vont à celui qui
  **joue**. `lecture` et `mets tel titre` peuvent réveiller un onglet à l'arrêt.
- **L'extension est éteinte quand un modo demande quelque chose** — Wally le dit
  dans le chat plutôt que de faire croire que c'est fait.

## Pour les curieux

- `lib.js` — le nettoyage des titres. YouTube annonce
  `Numb (Official Music Video) [4K UPGRADE] – Linkin Park` ; le chat reçoit
  `Linkin Park — Numb`. Couvert par des tests (`tests/test_musique_extension_lib.py`).
- `pont.js` — lit le lecteur et applique les ordres. Il tourne dans le monde de
  la page, seul endroit d'où `navigator.mediaSession` est visible.
- `content.js` — le battement vers le bot. Lui seul a le droit de parler au
  réseau.
