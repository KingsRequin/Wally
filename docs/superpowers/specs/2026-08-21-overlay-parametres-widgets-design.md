# Des paramètres par widget dans l'éditeur d'overlay — conception

*2026-08-21 · branche `feat/site-redesign-arcade`*

## Le problème

Le panneau de mise en scène règle **où** va chaque élément (position, ancrage,
taille, rang, masqué, verrouillé, solo, Wally visible) et **rien d'autre**. Tout
ce qui touche au **comportement** d'un widget — combien de temps il reste, comment
il entre, comment il sort — est soit figé dans `overlay.js`, soit décidé par le
serveur événement par événement, soit rangé globalement dans `config.yaml`.

Le streamer ne peut donc pas dire « ce panneau Apex, je le veux à 40 % d'opacité,
incliné, qui glisse depuis la droite et reste 8 secondes ». Il peut le placer, un
point c'est tout.

## Ce qui existe déjà, et qu'on ne réinvente pas

Quatre briques sont en place et portent ce chantier :

1. **`_el(..., propres={...})`** dans `bot/core/overlay_layout.py` : un élément
   peut déjà porter des réglages que lui seul a. `rotator` s'en sert pour
   `duree` et `pause`. `CHAMPS_PROPRES` en donne les bornes, `_fusionner_element`
   les valide.
2. **`placer()`** dans `bot/dashboard/static/overlay_layout.js` : le point
   d'écriture **unique** du style d'un élément sur la page. Tout réglage visuel
   passe par là, pour les 37 éléments d'un coup.
3. **`reglages[kind]`** dans `overlay.js` : le layout de la scène est déjà en
   mémoire au moment où `showWidget()` monte une carte. `estSolo()` et
   `masqueWally()` le lisent déjà.
4. **`animate.min.css`** est déjà servi sur l'overlay, et le widget `image` s'en
   sert déjà (`animation_in`, `animation_out`, `animation_duration`,
   `display_duration`) — mais depuis `config.yaml`, globalement, hors du layout.

Le point 4 est un **doublon d'autorité** : la même question (« comment ce widget
entre-t-il ? ») a deux réponses à deux endroits. C'est la signature de défaut que
ce dépôt traque. Ce chantier la referme.

## Le principe qui gouverne

Repris du fichier lui-même :

> Un réglage visible qu'aucun code ne lit est une promesse fausse.

Chaque paramètre décrit ci-dessous est branché sur du code qui le lit vraiment.
Rien n'est ajouté « pour plus tard ».

Et son corollaire, qui décide de la valeur livrée :

> Personne ne voit son overlay changer parce qu'on a rendu un réglage réglable.

## Les décisions

### D1 — Trois portées, pas une seule

Un réglage ne vaut pas pour tout le monde. `avatar` n'a pas de durée
d'affichage ; un dé n'a pas de pause.

| Portée | Éléments concernés | Champs |
|---|---|---|
| **Universelle** | les 37 d'`ELEMENTS` | `opacite`, `rotation`, `miroir`, `largeur_max` |
| **Widgets qui passent** | les 33 de `BUILDERS ∪ APEX_BUILDERS` | `duree`, `delai`, `anim_entree`, `anim_sortie`, `anim_duree`, `anim_insistance` |
| **Boucle** | `rotator` | `duree`, `pause` (existants, inchangés) |
| **Bulle** | `bubble` | `duree` (durée d'une réplique) |
| **Galerie** | `image` | `duree`, `anim_entree`, `anim_sortie`, `anim_duree` (migrés de `config.yaml`) |

Les trois universels rejoignent le corps de `_el()` et de `_fusionner_element()`,
au même titre que `scale` et `hidden`. Les autres passent par `propres=`.

Les quatre éléments hors `BUILDERS` — `avatar`, `bubble`, `rotator`, `image` —
ont chacun leur propre chemin de rendu : ils ne reçoivent **pas** `duree`,
`delai` ni `anim_*` au titre des widgets qui passent, seulement ce que leur ligne
du tableau leur donne.

### D2 — La valeur livrée d'une durée est « auto », pas 12 secondes

**C'est la décision qui protège le live.** Le réglage de scène l'emporte sur
`params.duration` : c'est le choix rendu, et c'est le seul qui rende le curseur
honnête. Mais si la valeur **livrée** valait 12 s (le repli actuel de
`showWidget`), alors dès le premier rebuild un sondage de 120 s disparaîtrait de
l'écran à 12 s, sur les trois scènes, sans que personne n'ait touché à un
curseur. Les viewers perdraient la question sous les yeux à mi-vote — exactement
le défaut déjà corrigé une fois quand le plafond client est passé de 30 à 180 s.

Donc : **`duree = 0` signifie « auto : le serveur décide », et c'est la valeur
livrée.** Le curseur porte un cran « auto » à gauche de sa plage. Rien ne change
tant qu'on n'y touche pas ; dès qu'une valeur est posée, elle écrase.

La même règle vaut pour tous les nouveaux champs : la valeur livrée reproduit le
comportement d'aujourd'hui.

| Champ | Livré | Ce que ça reproduit |
|---|---|---|
| `opacite` | `1.0` | aucun changement |
| `rotation` | `0.0` | aucun changement |
| `miroir` | `false` | aucun changement |
| `duree` | `0` (auto) | le serveur décide, comme aujourd'hui |
| `delai` | `0` | apparition immédiate |
| `anim_entree` | `"glitch"` | la rafale de glitch actuelle |
| `anim_sortie` | `"glitch"` | idem |
| `anim_duree` | `0.15` | `GLITCH_MS` = 5 états × 30 ms |
| `anim_insistance` | `"aucune"` | aucun changement |
| `largeur_max` | `0` (auto) | le `max-width: 92vw` actuel, inchangé |

### D3 — Trois exceptions où la mécanique interne garde la main

Une durée réglée ne doit pas couper ce qui est vivant. Trois cas, documentés dans
le code au point de lecture :

- **`params.sticky === true`** — une partie de pendu en cours, un sondage
  ouvert : `showWidget` sort déjà avant de poser le minuteur. On n'y touche pas.
- **`clip` pendant la lecture vidéo** — il sort sur la fin de la vidéo
  (`video.duration + 5`), pas sur un minuteur. Une durée réglée couperait le clip
  au milieu.
- **`virus_popup`** — sa durée pilote un plan de fenêtres calculé
  (`WallyVirus.rythme(duree)` → `fenetres(...)`). Le réglage de scène **remplace**
  `params.seconds` en entrée de ce calcul, il ne se superpose pas au minuteur :
  sinon l'écran bleu de nettoyage tomberait avant ou après la fin du plan.

### D4 — `CHAMPS_PROPRES` devient indexé par élément

`duree` existe déjà sur `rotator` avec les bornes 1–120 s, plafond justifié par
le gardien anti-gel de la boucle (`3 × (durée + pause) + 10 s` : à 120/120 il
patiente déjà douze minutes). Les widgets qui passent, eux, vont jusqu'à 180 s —
le plafond de `showWidget`, qui existe parce que le serveur émet jusqu'à 124 s.

Le même mot, deux sens, deux plages. La table passe donc de
`nom → (mini, maxi)` à `élément → {nom → (mini, maxi)}` des deux côtés
(`overlay_layout.py` et `overlay_admin.js`). Sans ça, la borne d'un champ
dépendrait de l'ordre d'écriture de la table — un défaut invisible qui ne se
verrait qu'un jour de live.

### D5 — Rotation et miroir se composent dans le `transform` du conteneur, avec correction d'origine

**Cette section a été corrigée le 2026-08-21 en exécutant la phase 2 : la
solution d'origine — une règle CSS `[data-element] > *` — ne peut pas
fonctionner.** Elle est conservée ici sous sa forme corrigée, avec la raison,
parce que c'est le genre d'erreur qu'on refait.

Le conteneur d'un élément porte déjà
`transform: scale(e) translate(tx, ty)`, dans **cet ordre**, pour une raison
payée cher : écrit `translate(-50%) scale(s)`, un widget centré à 50 %
atterrissait à 30 % de large. Et son `transform-origin` est un **coin**
(`left top`, `right bottom`…), pas le centre. Un `rotate()` ajouté en bout de
cette chaîne ferait donc tourner l'élément autour de son point d'ancrage : il se
déplacerait à l'écran en même temps qu'il s'incline.

**Pourquoi la règle CSS sur l'enfant ne marche pas.** `overlay.html` pose déjà
`body.widget-on #bubble { transform: translateY(6px) scale(.97) }` et
`body[data-side="right"] #avatar-slot { transform: scaleX(-1) }`. Ces sélecteurs
pèsent (1,1,1) ; un `[data-element] > *` pèse (0,1,0) et perd. La règle aurait
donc été écrasée sur **exactement les deux éléments les plus visibles de
l'overlay**, et seulement sur eux — un défaut qui ne se voit qu'en live, sur la
bulle et l'avatar. Un wrapper dédié aurait contourné le conflit, au prix d'un
nœud de plus dans les trente-sept conteneurs et d'un CSS à retoucher partout.

**La parade retenue** tient dans `styleDepuisElement()`, la fonction pure : on
amène l'origine au centre, on tourne, on revient.

```js
transform: scale(e) translate(tx, ty)
           translate(dx%, dy%) rotate(a) scaleX(m) translate(-dx%, -dy%)
```

Les pourcentages d'un `translate` se mesurent sur la taille **non transformée** :
l'aller et le retour s'annulent donc exactement, quelle que soit l'échelle. Et
le **sens** du recentrage suit le coin — `dx = -50` quand l'ancrage mesure
depuis la droite, `+50` sinon ; idem pour `dy` et le bas. `translate(50%, 50%)`
depuis un coin bas-droit tomberait hors de l'élément.

Le suffixe n'est ajouté **que** si quelque chose est réglé : sans inclinaison ni
miroir, la chaîne reste celle d'avant ce chantier, à l'octet près, sur les
trente-sept éléments des trois scènes. Un test l'exige.

Trois bénéfices non prévus : l'aperçu du panneau hérite gratuitement (son
`styleApercu()` réutilise déjà `styleDepuisElement`), aucune règle CSS nouvelle
n'entre en conflit de spécificité, et tout reste dans le point d'écriture unique
du style.

**Limite connue, traitée en phase 4 :** `geometrie()` (panneau) recalcule la
boîte d'un élément depuis `x`/`y`/`anchor`/`scale` sans tenir compte de
l'inclinaison. Le point d'ancrage ne bouge pas — la rotation est centrée — donc
le glisser reste juste, mais la boîte **englobante** d'un élément incliné est
plus grande que son rectangle : le détecteur de chevauchement et les poignées
raisonneront un peu court tant que la phase 4 n'aura pas posé
`w' = |w·cos a| + |h·sin a|`.

### D6 — `image` quitte `config.yaml` pour le layout

Les quatre clés `overlay_image.{display_duration, animation_in, animation_out,
animation_duration}` sont recopiées **une fois** dans les trois scènes, à la
première lecture d'un layout qui ne les porte pas encore. Ensuite, le layout
décide seul et les quatre champs disparaissent de l'onglet Paramètres du
dashboard.

Bénéfice au-delà du doublon : le réglage d'`image` devient **par scène**, comme
tout le reste. `overlay_image.enabled`, `.command` et `.random_filter` restent
dans `config.yaml` — ils ne parlent pas de mise en scène.

### D7 — Le sélecteur d'animation : les 97, groupées, avec recherche

`animate.min.css` porte 97 animations utilisables : 42 entrées, 42 sorties,
13 effets d'insistance. Les trois menus les exposent **toutes**, groupées par
famille, avec une barre de recherche en tête et un aperçu au survol qui rejoue
l'animation sur une vignette.

| Menu | Contenu | Entrées |
|---|---|---|
| Entrée | `glitch`, `aucune` + les 42 entrées | 44 |
| Sortie | `glitch`, `aucune` + les 42 sorties | 44 |
| Insistance | `aucune` + les 13 « attention » | 14 |

Familles : Back (4+4), Bounce (5+5), Fade (13+13), Flip (2+2), LightSpeed (2+2),
Roll (1+1), Rotate (5+5), Slide (4+4), Zoom (5+5), Spéciales
(`jackInTheBox` / `hinge`), et pour l'insistance : `bounce`, `flash`, `pulse`,
`rubberBand`, `shakeX`, `shakeY`, `headShake`, `swing`, `tada`, `wobble`,
`jello`, `heartBeat`, `flip`.

La validation côté serveur se fait par **appartenance à la liste**, pas par
bornes : `CHAMPS_CHOIX` vient à côté de `CHAMPS_PROPRES`. Un nom inconnu reprend
le défaut, comme partout ailleurs ici — fusionner, jamais remplacer.

La liste des noms est écrite **une fois**, côté Python, et servie au panneau par
le GET du layout. Deux listes auraient divergé à la première mise à jour
d'`animate.css` — c'est exactement le reproche auquel `WallyLayout.TAILLES`
répond déjà.

## Le catalogue complet

### Apparence — les 37 éléments

| Champ | Plage | Pas | Effet |
|---|---|---|---|
| `opacite` | 0,1 → 1,0 | 0,05 | `opacity` sur le conteneur |
| `rotation` | −45 → +45° | 1 | `--ovl-rotation` |
| `miroir` | booléen | — | `--ovl-miroir` (`scaleX(-1)`) |

Le plancher d'opacité est 0,1 et non 0 : à zéro l'élément est invisible mais
occupe toujours la scène, efface Wally et passe dans la file — un « masqué » qui
ne dit pas son nom, alors que `hidden` existe et coupe vraiment.

### Rythme — les 33 widgets qui passent

| Champ | Plage | Pas | Effet |
|---|---|---|---|
| `duree` | 0 (auto), puis 2 → 180 s | 0,5 | remplace `params.duration` dans `showWidget` |
| `delai` | 0 → 10 s | 0,5 | attente avant l'insertion dans le DOM |
| `anim_entree` | 44 choix | — | classe `animate__` à l'apparition |
| `anim_sortie` | 44 choix | — | classe `animate__` à la sortie |
| `anim_duree` | 0,1 → 3,0 s | 0,05 | `--animate-duration`, et le délai du relais |
| `anim_insistance` | 14 choix | — | classe `animate__ … animate__infinite` pendant l'affichage |

`anim_duree` pilote **aussi** le minuteur de relais : aujourd'hui `playNext` est
rappelé après `GLITCH_MS` (150 ms) en dur. Avec une sortie d'une seconde, la
carte suivante entrerait pendant que la précédente finit de partir — deux cartes
pleines l'une sur l'autre, illisibles. Le relais suit donc l'animation réelle.

### Largeur — les 37 éléments

| Champ | Plage | Pas | Effet |
|---|---|---|---|
| `largeur_max` | 0 (auto), puis 120 → 1920 px | 10 | remplace le `max-width` du conteneur |

`[data-element]` — le conteneur de **chaque** élément — porte déjà
`width: max-content; max-width: 92vw`. Un widget se dimensionne donc par son
contenu, avec pour seul plafond 92 % de la source : une citation longue traverse
l'écran, un message épinglé bavard aussi. `largeur_max` remplace ce plafond par
une valeur choisie, en pixels du canvas de référence 1920 — elle suit donc
l'échelle comme le reste. À `0`, le `92vw` d'aujourd'hui s'applique, inchangé.

C'est un réglage universel et non réservé aux widgets de texte : la règle CSS
qu'il pilote est universelle, et restreindre à une liste écrite à la main
demanderait de la tenir à jour à chaque widget ajouté — pour interdire un réglage
qui ne fait de mal à personne.

### Inchangés

`rotator` garde `duree` (1–120 s) et `pause` (0–120 s) avec leur sens actuel.

## Le rendu : qui lit quoi

| Champ | Lu par | Fichier |
|---|---|---|
| `opacite`, `rotation`, `miroir` | `placer()` | `overlay_layout.js` + règle CSS d'`overlay.html` |
| `duree`, `delai`, `anim_*` | `showWidget()` / `disposeWidget()` | `overlay.js` |
| `duree` de `bubble` | `say()` | `overlay.js` |
| `duree`, `anim_*` d'`image` | `IMAGE.montrer()` | `overlay.js` |
| `largeur_max` | `placer()` → `maxWidth` sur le conteneur | `overlay_layout.js` |
| `duree`/`pause` de `rotator` | `ROTATEUR.appliquerReglage()` | `overlay.js` (inchangé) |

## Le panneau

- **Trois natures de champ** dans l'inspecteur : numérique (existante),
  booléenne (`miroir`), et **choix** (les trois menus d'animation). Les deux
  nouvelles rejoignent `champNumerique` comme sœurs, avec la même garde au point
  d'écriture (`ecrire()` refuse déjà un élément verrouillé, et vérifie le
  propriétaire du champ).
- **Le sélecteur d'animation** est un panneau volant : bouton → menu, recherche
  en tête, familles repliables, aperçu au survol. Deux pièges déjà payés ici :
  `overflow: hidden` rogne un menu qui monte, et un panneau volant choisit son
  côté à l'**ouverture**. Il réutilise le mécanisme du panneau volant existant
  plutôt que d'en poser un second.
- **Le journal « ce qui a bougé »** (`decrireElement`) énumère aujourd'hui ses
  champs à la main, avec deux `if` de rattrapage pour `duree` et `pause`. Ajouter
  dix `if` de plus le rendrait illisible : il passe sur une **table**
  `champ → (libellé, formateur)`, en gardant la règle qui compte — un champ
  absent des deux côtés ne produit aucune ligne, sinon « durée undefined → 9 s »
  annoncerait une modification que personne n'a faite.
- **L'aperçu vivant** du panneau doit rendre l'opacité, la rotation, le miroir et
  la largeur maximale : ils passent par `placer()`, donc c'est acquis dès que la
  règle CSS est servie à l'iframe d'aperçu. À confirmer au navigateur.
- **La signature de liste** doit couvrir les nouveaux champs : c'est déjà un
  piège relevé sur ce panneau (le compteur comptait des gestes, pas des
  changements).

## Migration

Une fonction unique, appelée à la lecture d'un layout rangé avant ce chantier :

1. Les éléments sans les nouveaux champs les reçoivent à leur valeur livrée —
   c'est déjà ce que `_fusionner_element` fait, il n'y a rien à écrire.
2. **Sauf `image`** : ses quatre champs sont semés depuis `config.yaml`
   (`overlay_image`), une seule fois, dans les trois scènes. Un drapeau en base
   (`overlay_image_migre`) empêche de resemer par-dessus un réglage fait à la
   main.
3. Les quatre champs disparaissent de l'onglet Paramètres du dashboard
   (`app.js`). `enabled`, `command` et `random_filter` y restent.

## Tests

- **Bornes et fusion** : valeur hors plage, `null`, clé absente, type inattendu,
  nom d'animation inconnu → chacun reprend son défaut sans faire tomber le reste.
- **Le défaut ne change rien** : un layout livré doit produire exactement les
  mêmes durées et les mêmes animations qu'avant ce chantier. C'est le test qui
  protège le live.
- **Parité des tables Python ↔ JS** : `test_overlay_layout_css.py` compare déjà
  `ELEMENTS` à `BUILDERS ∪ APEX_BUILDERS` ; il est étendu aux portées (quels
  éléments portent quels champs) et à la liste des animations.
- **Les trois exceptions** : `sticky`, `clip` en lecture, `virus_popup` — un test
  par cas, qui vérifie que la durée réglée **ne** coupe **pas**.
- **Vérification en prod** : le panneau monte, l'inspecteur affiche les champs,
  un réglage posé se voit sur la page. Un test vert ne prouve pas qu'un panneau
  monte — c'est écrit noir sur blanc dans `CLAUDE.md`, et ça a déjà coûté six
  heures de panneau mort.

## Ce qu'on ne fait pas

- **Un son à l'apparition** — écarté à l'arbitrage. Il aurait fallu servir la
  liste des sons au panneau et un second sélecteur.
- **Une couleur d'accent par widget** — le style de l'overlay pose « un accent
  par INTENTION, pas par widget ». Un réglage par widget contredirait une
  décision déjà rendue.
- **Des réglages globaux au layout** — tout ce qui est ajouté ici est **par
  scène**, comme `elements`, `ordre` et `groupes`. Le modèle a tranché avant
  nous : les scènes divergent dès le premier réglage.
- **Un `delai` sur les widgets installés** — ils ne passent pas par la file, il
  n'y a rien à décaler.
- **Une hauteur maximale** — borner une hauteur sans compter les marges a déjà
  inversé une garde ici (la bulle était rognée par le haut, hors cadre).
  `bornerBulle()` fait déjà ce calcul, correctement, pour le seul élément qui en
  a besoin.

## Découpage en phases

Cinq fichiers au plus par phase, vérification et feu vert entre chacune.

| Phase | Portée | Fichiers |
|---|---|---|
| **1** | Le modèle : les 10 champs, les portées, `CHAMPS_PROPRES` indexé, `CHAMPS_CHOIX`, la liste des animations, la route qui les sert | `bot/core/overlay_layout.py`, `bot/dashboard/routes/overlay.py`, tests |
| **2** | Le rendu visuel : opacité, rotation, miroir, largeur max | `overlay_layout.js`, `overlay.html`, tests |
| **3** | Le rendu comportemental : durée, délai, animations, les trois exceptions, la bulle, la galerie | `overlay.js`, tests |
| **4** | Le panneau : les trois natures de champ, le sélecteur d'animation, le journal des différences | `overlay_admin.js`, `style.css` |
| **5** | La migration `image` et le retrait des quatre champs de l'onglet Paramètres | `app.js`, `bot/dashboard/routes/`, tests |

Chaque phase se clôt par `pytest`, `lint_types.py`, `lint_silences.py`, puis
commit + rebuild + push, comme le veut le dépôt.
