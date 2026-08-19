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

Puis ouvrir une vidéo YouTube — et **recharger les onglets YouTube déjà
ouverts** (F5) : Chrome n'installe l'extension que dans les pages chargées
ensuite. Un onglet ouvert avant l'installation se tait pour toujours.

## Vérifier que ça marche

Ouvrir la fenêtre de l'extension **depuis l'onglet YouTube** : la dernière ligne
dit ce que fait cet onglet-là.

- `✓ Cet onglet parle à Wally (dernier envoi il y a 2 s)` — c'est bon.
- `⚠️ Cet onglet n'envoie rien` — recharger la page (F5).
- `⚠️ Cet onglet essaie mais n'y arrive pas` — l'adresse ou le jeton.

Attention : `C'est branché ✓` du bouton **Enregistrer** ne dit que la moitié.
Cet essai-là part de l'extension, qui a le droit d'appeler le bot de partout ;
le vrai battement, lui, part de la page YouTube. Les deux chemins sont
distincts, et le premier peut réussir pendant que le second n'existe pas.

Ensuite, dans le chat Twitch, demander à Wally ce qui passe. S'il répond qu'il
ne sait pas, l'onglet YouTube est-il **ouvert avec une vidéo** ? Une page
d'accueil ou une recherche ne dit rien de ce qui passe, et une vidéo en pause
depuis plus de 45 secondes n'est plus « ce qui passe ».

## Mettre à jour

Elle **ne se met pas à jour toute seule** : chargée depuis un dossier, seul le
Chrome Web Store ferait ça, et elle n'y est pas.

Le bot dit quelle version il sert. Quand une plus récente existe :

- une **pastille orange** apparaît sur l'icône de l'extension, dans la barre de
  Chrome — visible sans rien ouvrir ;
- la fenêtre dit laquelle, et quoi faire.

La mise à jour, alors : retélécharger `extension-musique.zip`, remplacer le
contenu du dossier, puis **Actualiser** l'extension dans `chrome://extensions`.
La pastille s'éteint au battement suivant.

## Ce qui se passe si

- **Le bot redémarre** — l'extension réessaie toutes les deux secondes, il n'y a
  rien à faire.
- **Plusieurs onglets YouTube sont ouverts** — les ordres vont à celui qui
  **joue**. `lecture` et `mets tel titre` peuvent réveiller un onglet à l'arrêt.
- **L'extension est éteinte quand un modo demande quelque chose** — Wally le dit
  dans le chat plutôt que de faire croire que c'est fait.

## Pour les curieux

- `lib.js` — d'où vient le titre, dans cet ordre :
  1. **la fiche musicale de YouTube** (sous la vidéo : `Numb` · `Linkin Park` ·
     `Meteora`), sa source de vérité — pas besoin de YouTube Music, elle est là
     sur YouTube ordinaire, et sur un album entier elle suit même le morceau en
     cours pendant que le titre de la vidéo ne bouge pas ;
  2. sinon `mediaSession`, nettoyé : YouTube annonce
     `Numb (Official Music Video) [4K UPGRADE] – Linkin Park`, le chat reçoit
     `Linkin Park — Numb` ;
  3. sinon le titre de l'onglet.
  Couvert par des tests (`tests/test_musique_extension_lib.py`).
- `pont.js` — lit le lecteur et applique les ordres. Il tourne dans le monde de
  la page, seul endroit d'où `navigator.mediaSession` est visible.
- `content.js` — le battement vers le bot. Lui seul a le droit de parler au
  réseau.
- `fond.js` — la pastille sur l'icône, et rien d'autre : `chrome.action` n'est
  joignable ni depuis la page YouTube ni depuis le monde de la page.
