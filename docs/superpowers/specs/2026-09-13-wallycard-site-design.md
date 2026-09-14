# Wallycard sur le site : menu, bibliothèque et decks, livre des règles

**Date** : 2026-09-13 · **Statut** : design validé par l'owner, implémentation par morceaux
**Règles du jeu** : page Notion « Wallycard : règles du jeu » (`3dae93ddd54581428c3cd6b054371605`)
**Style** : projet Claude Design « Conception plateau TCG Wally »
(`17ef455a-844b-4b5d-bd20-d2f2f7d8447f`), note `CLAUDE.md` du projet

## 0. Arbitrages rendus

| Question | Réponse de l'owner |
|---|---|
| Nom | Le jeu s'appelle **Wallycard**. ⚠️ La note de style du projet de design dit encore « TCG du Purgatoire » et « Wally n'apparaît nulle part » : c'est périmé sur ce point, le reste du style fait foi. |
| Où vivent les decks | **Sur le compte Discord** du joueur, en base, côté serveur. |
| Taille du deck | **15 cartes tactiques** + **3 héros**. |
| Exemplaires | **1 seul exemplaire** par carte tactique dans un deck. |
| Héros choisissables | **Aucun pour l'instant** : tous grisés, aucun n'a de stats prêtes. |
| Texte des règles | **Export Notion vers le dépôt**, servi par le site. Jamais de lecture Notion en direct. |

## 1. Le menu Wallycard

- La route `/tcg` devient `/wallycard`. `/tcg` redirige : le lien a été partagé.
- Écran titre, trois entrées :
  - **Jouer** : visible, désactivé, marqué « bientôt » ;
  - **Bibliothèque** : la collection et l'éditeur de deck ;
  - **Règles** : le livre des règles.
- Sous-routes : `/wallycard` (menu), `/wallycard/bibliotheque`, `/wallycard/regles`.
- Style repris du dos de carte *purgatoire*, qui est la référence validée :
  - fond encre `#12100c`, accent unique or `#e1a947`, crème `#f7ecd9` ;
  - trame losange posée **depuis le centre**, vignettage radial ;
  - plaque de titre `WALLYCARD` en Archivo Black, losanges or aux quatre angles ;
  - banderoles crème en paire miroir haut/bas, texte JetBrains Mono qui défile ;
  - entrées du menu en plaques, symétrie verticale tenue ;
  - animations coupées sous `prefers-reduced-motion`.
- Aucune couleur écrite en dur dans le JS : les teintes vivent dans la feuille.

## 2. Les decks côté serveur

**Données** : une table `tcg_decks`.

| Colonne | Contenu |
|---|---|
| `id` | identifiant |
| `discord_id` | le compte propriétaire (texte, un snowflake ne survit pas à `Number`) |
| `nom` | nom du deck, borné en longueur |
| `heros` | liste de clés de héros, 3 au plus |
| `cartes` | liste de clés de cartes tactiques, 15 au plus |
| `cree_le`, `modifie_le` | horodatages UTC |

**Routes** (authentifiées par le JWT de connexion Discord du site) : lister ses decks, en
créer, en modifier, en supprimer. Un joueur ne voit et ne touche que les siens.

**Le serveur refuse** : plus de 15 cartes, une carte en double, plus de 3 héros, un héros en
double, une clé de carte ou de héros inconnue, un nom vide ou trop long, un nombre de decks par
compte au-delà d'un plafond. Le front applique les mêmes limites pour l'affichage, mais **seul le
serveur fait foi** : une limite tenue par le client seul se contourne.

**Un deck incomplet s'enregistre.** Tant qu'aucun héros n'est prêt, aucun deck ne peut être
complet ; refuser les brouillons rendrait l'éditeur inutilisable. Le deck porte simplement l'état
« incomplet », déduit (moins de 3 héros ou moins de 15 cartes), jamais stocké.

**Héros prêt** : déduit des données du héros (stats et Ultime écrits), jamais d'un drapeau posé
à la main. Aujourd'hui aucun ne l'est.

## 3. L'éditeur de deck

Dans *Bibliothèque* :

- la galerie actuelle (héros, actions et passifs) reste, avec son relief au survol ;
- un panneau **mon deck** : 3 emplacements de héros, un compteur « n / 15 », la liste des cartes ;
- cliquer une carte l'ajoute ou la retire ; une carte déjà dans le deck est marquée ;
- les héros non prêts sont grisés et ne s'ajoutent pas ;
- enregistrer demande la connexion Discord ; sans connexion, on peut composer mais pas sauvegarder.

## 4. Le livre des règles

- Un export écrit dans le dépôt. Livré le 2026-09-14 comme script À PART,
  `scripts/export_regles_wallycard.py` (le sens inverse de la synchro, qui ne sait que pousser),
  vers `public-ui/donnees/wallycard-regles.json` :
  - la page de règles, chapitre par chapitre ;
  - le corps des 51 fiches détaillées (« Ce qu'elle fait », « Exemple », « À savoir »).
- Prérequis : partager la page Notion « TCG de la commu » avec l'intégration *syncro wallycard*,
  qui ne voit aujourd'hui que la base.
  Tant que ce partage manque, l'export garde les chapitres déjà présents et rafraîchit les fiches.
  Partage fait par l'owner le 2026-09-14 ; l'export par l'API a redonné à l'identique les
  chapitres du premier export, lus par le connecteur.
- L'avertissement en tête de la page Notion n'est pas publié : il renvoie aux sections de travail.
- La page *Règles* affiche les chapitres ; chaque carte citée mène à sa fiche.
- On relance l'export à chaque modification des règles. La page affiche la date du dernier export.
- Les sections « À trancher » et « Propositions » ne sont **pas** publiées : le livre ne dit que
  ce qui est décidé.

## 5. Découpage et vérification

| Morceau | Dépend de | Vérifié par |
|---|---|---|
| 1. Menu | rien | `smoke_front.py --public`, `lint_js.py`, capture en 390 px |
| 2. Decks serveur | rien | tests pytest des refus et du cloisonnement par compte |
| 3. Éditeur | 1 et 2 | smoke du montage, parcours réel ajout / retrait / enregistrement |
| 4. Livre des règles | 1, partage Notion | smoke du montage, export relancé à vide sans erreur |

Chaque morceau touche au plus cinq fichiers, se publie seul et se vérifie dans le navigateur
avant le suivant.

## 6. Hors périmètre

*Jouer* (le moteur de partie), le calibrage des coûts, les variantes de rang S et leur déblocage
par niveau, le bouton de signalement de bug. Ils ont leur place dans les règles, pas dans ce
chantier.
