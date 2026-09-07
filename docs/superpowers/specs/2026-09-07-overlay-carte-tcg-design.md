# La carte du TCG sur l'overlay — design

**Date** : 2026-09-07 · **État** : validé, non implémenté

Wally affiche la carte d'une personne sur l'overlay OBS, sur demande ou de
lui-même. Elle apparaît à plat, se déplie en 3D, tourne doucement, puis s'en va.

---

## 0. Pour qui

**L'overlay s'adresse aux VIEWERS, jamais au streamer** — il ne le voit pas
pendant qu'il joue (`2026-08-06-compagnon-de-stream-design.md`, §0). Montrer la
carte de quelqu'un, c'est un geste vers le chat : « voilà à quoi tu ressembles
dans son jeu ». La carte occupe donc **seule la scène** (`solo`), Wally masqué :
arbitrage de l'owner du 2026-09-07.

⚠️ **Les chiffres des cartes sont des placeholders.** La page `/tcg` le dit aux
visiteurs ; l'overlay n'a pas la place de le dire. Ce n'est pas un manque : on
montre une carte, on ne publie pas un barème.

---

## 1. Le problème à résoudre d'abord

Les cartes n'existent qu'en **JavaScript**, dans `public-ui/pages/tcg-collection.js`.
Deux conséquences bloquantes :

- Wally ne peut pas nommer une carte : Python ignore qu'elles existent.
- L'overlay ne peut pas la dessiner : il est servi depuis `/static/`, une autre
  surface, et le composant de rendu importe `h()` depuis la coquille du site
  public (`app.js`) — l'importer tirerait Lenis, le routeur et les flux SSE du
  site dans l'overlay.

Tout le reste du chantier découle de la façon dont on répare ça.

---

## 2. Architecture

### 2.1 La source passe en Python

`bot/core/tcg_cartes.py` devient la **source unique** : une dataclass `CarteTcg`
et un registre des cartes terminées. Trois consommateurs, aucune copie :

| Consommateur | Voie |
|---|---|
| `show_overlay` (le LLM) | lecture directe du registre |
| Le widget overlay | les valeurs voyagent **dans l'événement** du bus SSE |
| Le site public (`/tcg`, `/demo/carte-azrael`) | `GET /api/public/tcg/cartes` |

⚠️ **Une carte n'entre au registre que si son illustration existe.** Règle déjà
écrite en tête de `tcg-collection.js`, elle déménage avec les données : une
entrée sans image donne une carte noire annoncée comme terminée.

**Coût assumé** : `/tcg` fait désormais un appel réseau là où elle affichait
sans rien demander. C'est le prix d'une source unique, et les deux autres pages
de données du site (`/galerie`, `/clips`) le paient déjà.

⚠️ **Un fetch qui échoue doit le DIRE.** Une grille vide se lit « il n'y a pas
de cartes », ce qui est faux. La page rend un état d'échec nommé, avec de quoi
réessayer — l'absence ne doit jamais être confondue avec le vide.

⚠️ **Un seul appel pour les deux pages.** `/tcg` et `/demo/carte-azrael` lisent
la même route ; le module de données mémorise la réponse. Deux fetchs pour la
même liste, c'est deux occasions de diverger à l'écran.

### 2.1 bis — Le cache des illustrations (défaut existant)

`SPAStaticFiles` pose `Cache-Control: no-store` sur **tout** `public-ui/`, y
compris `assets/`. Mesuré le 2026-09-07 : chaque visite de `/tcg` retélécharge
**environ 1 Mo** d'illustrations, et l'overlay le ferait à **chaque affichage**
de carte. Le `no-store` est délibéré pour le HTML, le JS et le CSS — c'est ce
qui rend le front modifiable sans rebuild — mais une illustration n'est pas du
code.

Correctif : `no-cache` pour les médias (`.avif`, `.webp`, `.png`, `.jpg`,
`.webm`, `.woff2`), `no-store` pour le reste. `no-cache` **n'est pas** « pas de
cache » : le navigateur revalide par ETag et reçoit un `304` sans corps. Le
contenu ne peut donc jamais être périmé — c'est ce qui permet au script de
régénération de réécrire une illustration sous le même nom — et le coût passe
de 400 ko à quelques centaines d'octets.

⚠️ Ne PAS poser `immutable` avec un `max-age` long : nos noms de fichiers sont
stables (`tcg-azrael-hero.avif`), une illustration retouchée ne serait jamais
reprise.

### 2.2 Le composant devient pilotable, et partagé

`carteHero()` est aujourd'hui **entièrement piloté par le curseur** : il lit
`event.clientX` et le rectangle de l'élément. Sur l'overlay il n'y a ni souris
ni survol — la chorégraphie doit être **jouée**. Trois changements :

- `incliner(nx, ny)` prend des coordonnées **normalisées** (−0.5 … +0.5). Le
  calcul `(px − rect.left) / rect.width − 0.5` ne disparaît pas : il déménage du
  composant vers le gestionnaire de souris, qui devient un simple appelant.
  **L'angle produit est identique, à la virgule près.**
- `ouvrir()` / `fermer()` s'exposent (ils existent déjà, en privé).
- Un drapeau `interactif` (vrai par défaut) : l'overlay ne branche **aucun**
  écouteur de pointeur.

**L'échelle sur l'overlay est FIGÉE à 2.** La carte fait 340 px CSS ; sur un
canvas de 1920, elle occuperait 18 % de la largeur — illisible sur un stream.
À `--chero-k: 2` elle fait 680 px, et l'overlay rend en DPR 1 : **680 pixels
physiques, exactement ce pour quoi les illustrations sont générées** (340 CSS
× DPR 2, cf. `generer_illustrations_tcg.py`). La coïncidence n'en est pas une,
mais elle est fragile : passer à 3 rendrait toutes les cartes floues sans que
rien ne le signale. La valeur est écrite une fois, avec ce commentaire.

Le composant et le `h()` qu'il utilise déménagent dans **`public-ui/partage/`**,
servi par le catch-all comme le reste du site. Le site importe
`./partage/…`, l'overlay `/partage/…` — même origine, aucun nouveau mount.
`h()` reste **réexporté depuis `app.js`** : six pages l'importent de là, aucune
ne doit bouger.

---

## 3. La chorégraphie

Quatre phases, sur la **boucle d'animation déjà partagée** par les cartes — pas
un nouveau `requestAnimationFrame` (le composant en a une, à 30 images/s,
arrêtée quand l'onglet passe derrière).

| Fenêtre | Ce qui se passe | Correspondance |
|---|---|---|
| 0 → 0,6 s | la carte arrive **à plat**, fondu et léger zoom | l'état de repos, zéro 3D |
| 0,6 → 1,4 s | `ouvrir()` : couches séparées, cadres, héros qui déborde, bouffée de braises | l'effet de survol |
| 1,4 s → fin −0,8 s | `incliner()` sur une trajectoire lente en huit (Lissajous 2:1) | la rotation parallaxe |
| dernière 0,8 s | `fermer()`, puis retrait du nœud | |

**Durée par défaut 9 s**, portée par le champ `duree` du widget comme tous les
autres. ⚠️ `duree = 0` vaut « auto : le serveur décide » — c'est la valeur
livrée, et le repli de `showWidget` (12 s) ne doit pas être écrit en dur.

⚠️ **Attendre `img.decode()` avant la phase 1**, et le compte à rebours de la
durée ne démarre qu'après. Sans ça la première carte affichée apparaît pendant
son propre décodage : les phases avancent, l'image non.

⚠️ **Avec un plafond de 2 s.** Un `decode()` qui n'aboutit pas — image manquante,
réseau coupé — ne doit pas empêcher l'affichage indéfiniment : passé le délai on
joue quand même, et on journalise. Une attente sans plafond est une panne
silencieuse, pas une précaution.

**Amplitude de la trajectoire : la moitié de la course** (±0,25 sur les deux
axes normalisés, soit ~7° à intensité 1). L'owner a demandé qu'elle « tourne
légèrement » ; à pleine amplitude la carte bascule comme sous un curseur qui
balaie, ce qui se lit comme un bug d'animation plutôt que comme une présentation.

⚠️ La rotation se compose dans le `transform` du plateau (`.chero-carte`), là où
le survol l'écrit déjà. Une seconde source d'écriture sur ce même transform le
remplacerait — deux `transform` sur un nœud ne se cumulent pas.

---

## 4. Le widget dans le registre

🚨 **Ajouter un widget à cet overlay demande SEPT endroits, et six échouent en
SILENCE si on les oublie.** Relevé le 2026-09-07 en les heurtant un par un ; le
plan n'en connaissait aucun au départ, et la liste qu'il a dressée après cinq
en manquait encore deux. À lire avant d'en ajouter un autre.

| # | Endroit | Ce qui arrive si on l'oublie |
|---|---|---|
| 1 | `ELEMENTS` (`overlay_layout.py`) | le widget n'existe pas |
| 2 | `_ORDRE_DEFAUT` (même fichier) | **réglable dans le panneau, JAMAIS rendu en live** |
| 3 | `LIBELLES` (`overlay_elements.py`) | test rouge — le seul qui parle |
| 4 | `_ECHANTILLONS` (`routes/overlay.py`) | invisible dans le panneau de mise en scène |
| 5 | `_OVERLAY_FILES` (même fichier) | le script reste dans le cache d'OBS **pour toujours** |
| 6 | `OverlayNarrator._WIDGETS` | `show_widget` refuse, et la valeur disparaît de l'enum : **Wally ne la voit jamais** |
| 7 | `_WIDGET_WORDS` (`self_model.py`) | Wally POSSÈDE la capacité sans le savoir |
| — | `<div data-element>` + `overlay_layout.js` | tests rouges |

Les numéros 2 et 6 sont les plus coûteux : tout le reste peut être en place, et
le widget reste introuvable ou invisible sans qu'une seule erreur ne le dise.

Clé `carte`. Quatre points de câblage, tous existants :

1. `ELEMENTS` (`overlay_layout.py`) — `_el(50.0, 50.0, "center")`, donc `solo`
   par défaut : la carte chasse Wally, comme voulu. Les **dix réglages par scène**
   (durée, délai, trois animations, opacité, rotation, miroir, largeur max) se
   distribuent tout seuls, la portée étant **calculée** par `widgets_qui_passent()`.
2. `LIBELLES` (`overlay_elements.py`) — nom et phrase pour le panneau de mise en
   scène. Un test vérifie que les deux tables restent en phase.
3. `BUILDERS` (`overlay.js`) — délègue à un module `overlay_tcg.js` qui importe
   le composant partagé et joue la chorégraphie.
4. `overlay.html` — la feuille de la carte et la police **Archivo Black**
   déclarées **au boot**, pas au moment de l'affichage : une police qui arrive
   après le titre, sur un stream, se voit.

⚠️ **La police est VENDORÉE**, pas chargée depuis Google Fonts. Un overlay OBS
qui dépend d'une requête vers un tiers au démarrage affiche son premier titre
dans la police de repli si le réseau traîne — et sur un stream, ça ne se
rattrape pas. Elle rejoint `public-ui/vendor/` et son `PROVENANCE.md`, comme
Lenis. Le site public en profite : une requête externe de moins sur `/tcg`.

---

## 5. Le déclenchement

**Pas de nouvel outil.** Le modèle n'en voit qu'un pour l'overlay,
`show_overlay`, dont le `widget` est un enum — et cet enum est déjà **filtré par
les widgets qu'une scène affiche réellement** (`widgets_disponibles`). La carte
y ajoute :

- la valeur `carte` dans l'enum ;
- un paramètre `personne` (le pseudo). Inconnu → refus **explicite** qui nomme
  les cartes disponibles, jamais un échec muet.

**La résolution pseudo → carte : chaque carte porte SES alias**, écrits à la
main (`alias: tuple[str, ...]`). « claker », « ClakerNoJutsu » et « clacker »
doivent tomber sur la même carte, sinon Wally aura raison et l'outil tort.

⚠️ Une première version de ce paragraphe disait « par les alias déjà en base
(`memory.load_aliases`) ». C'est faux et c'était plus lourd : ces alias lient un
pseudo à un `canonical_uid`, donc à une PERSONNE. Une carte n'a pas d'uid, et
lui en donner un pour quatre cartes serait un champ de plus, une jointure de
plus, et une lecture SQLite dans une fonction qui n'a aucune raison d'en faire.
Le lien pseudo → carte est **éditorial**, pas une relation de mémoire.

**La trace.** `overlay_feed.widget()` consigne déjà « tu as affiché le widget
« carte » » — volontairement sans ses paramètres, qui portent ailleurs du texte
libre. Un pseudo n'est pas du texte libre : l'appelant ajoute sa propre ligne,
« tu as montré la carte de Claker aux viewers ». Sans elle, Wally fait le geste
et ne sait pas qu'il l'a fait (`self_trace.py` est le point d'entrée unique de
« ce que Wally vient de faire »).

---

## 6. Hors périmètre

- **Le fond animé** (WebM au survol) : se branchera sur cette base, après.
- **Toute autre voie de déclenchement** : ni commande chat, ni points de chaîne.
- **Les vraies valeurs des cartes** : elles viennent de Notion, carte par carte.

---

## 7. Comment on prouve qu'on n'a rien cassé

Le refactor touche le rendu de `/tcg`, qui marche aujourd'hui. Deux filets,
posés **avant** la première ligne modifiée :

1. **Des références figées** — `/opt/design-tcg/references-avant-refactor/` :
   les quatre cartes au repos et en survol à un angle de curseur **fixe**
   (28 %, 22 %), plus la **matrice 3D exacte** de chacune relevée au navigateur.
   Après le refactor, mêmes captures, mêmes matrices. Une position reproductible
   est la seule façon de comparer deux survols.
2. **Le smoke test ne couvrait pas l'effet 3D de la carte** — il vérifie le tilt
   des cartes du *site* (`[data-tilt]`), pas celui de `.chero`. Le trou est
   antérieur au chantier. Phase 1 le comble : survol de `.chero`, `perspective`
   posée, `rotateX`/`rotateY` présents, cadres passés en `visible`, et **retour à
   plat à la sortie**.

⚠️ Ne pas asserter une ligne d'implémentation : on mesure l'ÉTAT rendu
(perspective, transform, visibilité), jamais le fait qu'une fonction ait été
appelée. Un test qui exige le comportement fautif le fige — vu six fois ici.

---

## 8. Les phases

Trois phases, cinq fichiers au plus chacune, vérifiées en réel entre les deux.

**Phase 1 — le socle.** Source Python + route publique + composant rendu
pilotable et déplacé dans `partage/`, front recâblé dessus.
*Critère de sortie* : `/tcg` et `/demo/carte-azrael` **identiques à aujourd'hui**
— mêmes captures, mêmes matrices 3D — et le smoke test étendu qui l'atteste.

**Phase 2 — le widget.** `ELEMENTS`, `LIBELLES`, `overlay_tcg.js`, `overlay.js`,
`overlay.html`.
*Critère de sortie* : la carte jouée sur `overlay.html`, captures des quatre
phases, et le widget réglable depuis le panneau de mise en scène.

**Phase 3 — le déclenchement.** L'enum, le paramètre, la résolution par alias,
la trace, les deux plateformes.
*Critère de sortie* : Wally affiche une carte demandée en vrai, et sa trace le
dit.

⚠️ **Piège de cette phase** : `widgets_disponibles` retire de l'enum tout widget
qu'AUCUNE scène n'affiche. Tant que `carte` n'a pas été posée sur une scène
depuis le panneau de mise en scène, Wally ne voit pas la valeur et ne peut pas
l'appeler — sans qu'aucune erreur ne le dise. Vérifier la scène AVANT de
chercher un défaut dans l'outil.
