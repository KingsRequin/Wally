# Overlay : scènes, placement libre et page de mise en scène

**Date** : 2026-08-15
**État** : conception validée, implémentation à venir
**Origine** : demande owner du 2026-08-15 — « on va mettre l'overlay en plein écran,
mais il faut positionner Wally correctement » puis « je veux pouvoir déplacer chaque
élément de l'overlay avec un simple glisser ».

---

## Le problème

L'overlay est aujourd'hui une source OBS de **560 × 460** posée en bas à droite
(`docs/overlay.md:9`). Tout en découle :

- Les widgets n'ont **pas de place** : ils occupent la source entière, à tour de
  rôle. `renderWidget()` appelle `clearWidgets()` (`overlay.js:1135`) et
  `showWidget()` met en file d'attente ce qui arrive pendant (`overlay.js:966`).
- **L'avatar et la bulle s'effacent** pendant un widget (`widget-on`,
  `overlay.js:1150`). Wally ne peut donc pas commenter ce qu'il montre — c'est
  écrit noir sur blanc dans les limites connues (`docs/overlay.md:331`).
- Les tailles sont **calibrées sur la source** : 534 px pour une bulle au
  maximum, 432 px pour un sondage à quatre options. Ces chiffres n'ont plus de
  sens dès qu'on change la taille de la source.
- Le rotateur de memes et l'image sont **deux sources OBS distinctes**
  (`overlay_rotation.html`, `overlay_image.html`), placées à la main dans OBS.
- Le placement vit **dans OBS**, donc hors de portée de tout réglage — et il n'y
  a qu'un seul placement pour tout le live.

Trois moments de stream, trois habillages différents (démarrage, jeu, fin), et
aucun moyen de les distinguer.

---

## Ce qu'on construit

Une source OBS **par scène**, en 1920 × 1080 non redimensionnée, contenant
**tout** : avatar, bulle, les dix-sept widgets, le rotateur de memes, l'image.
Chaque élément a sa place, sa taille et sa visibilité, **par scène**, réglables
au glisser depuis le panneau admin, sans recharger quoi que ce soit.

### Non-objectifs

- **Wally ne touche pas au layout.** Il choisit *quoi* afficher et *quand*,
  jamais *où*. La mise en scène du stream appartient au streamer. C'est la
  frontière entre son autonomie et l'habillage de la chaîne, et elle est posée
  ici volontairement plutôt que découverte le jour où il déplacerait un bingo.
- **L'aperçu du panneau n'est pas un aperçu du rendu.** Un « aperçu de l'overlay
  dans le panneau admin » a été écarté le 2026-08-07 (`docs/overlay.md`,
  « Écarté volontairement »). Cette décision tient : la surface de placement
  n'affiche que des rectangles nommés, jamais le contenu réel. Pour voir le
  vrai rendu, on ouvre l'URL de la scène — ou on utilise le bouton *Tester*.
- **Pas de profils de disposition** au-delà des scènes. Une scène EST le profil.

---

## Le modèle

Une seule clé `overlay:layout` dans `bot_state` — même patron que
`apex:live_baseline` et le salon vocal retenu.

```json
{
  "version": 1,
  "defaut": "jeu",
  "scenes": [
    {
      "slug": "start",
      "nom": "Stream Starting",
      "ordre": ["meme", "bubble", "avatar", "rotator"],
      "elements": {
        "avatar": {
          "x": 91.4, "y": 64.8,
          "anchor": "bottom-right",
          "scale": 0.55,
          "hidden": false, "locked": false, "solo": false
        }
      }
    }
  ]
}
```

**`x` / `y` en pourcentage**, jamais en pixels : la disposition survit à un
changement de résolution de la source.

**`anchor`** désigne *quel point* de l'élément la position repère, parmi les
neuf combinaisons (`top-left` … `bottom-right`). Sans lui, un élément placé à
droite sortirait du cadre dès que son contenu s'élargit, et une bulle de dix
lignes pousserait vers la droite au lieu de monter. Le CSS actuel fait déjà
cela à sa façon avec `body[data-side="right"]`, qui bascule de `left: 0` à
`right: 0` (`overlay.html:176`) ; on généralise.

**`scale`, et non une largeur.** Redimensionner par la largeur laisserait le
texte à 16 px dans un widget réduit de moitié, et casserait la mise en page de
chacun des dix-sept — il faudrait retoucher leur CSS un par un.
`transform: scale()` fait grandir l'élément entier, texte compris, sans qu'on
touche à un seul de leurs styles. Plage 0,2 à 2,0.

**`solo`** porte la cohabitation. `true` : l'élément chasse les autres et passe
par la file d'attente actuelle (les jeux, les memes, le hasard). `false` : il
s'affiche par-dessus sans déranger personne (le bingo, les stats, l'objectif).
Réglable par élément, arbitrage owner du 2026-08-15.

**`ordre`** donne l'empilement, du plus proche au plus lointain. Pas de
`z-index` à régler à la main : on réordonne la liste.

**`hidden` est par scène.** C'est lui qui fait tout le travail des trois
habillages : le bingo masqué sur le Starting, visible en jeu, sans que Wally
ait la moindre décision à prendre.

### Le canvas de référence

Les positions en pourcentage résistent au changement de résolution ; les tailles,
non. Un `scale: 1` rendrait un avatar de 200 px large de 10,4 % sur une source
en 1920, mais de 7,8 % sur une source en 2560 — la disposition se déferait.

La page se rend donc sur un **canvas de référence de 1920 × 1080** et applique
un facteur global `largeurRéelle / 1920` à l'ensemble. Les tailles CSS actuelles
sont conservées telles quelles : elles sont calibrées et il n'y a aucune raison
de les refaire. Le `scale` par défaut de l'avatar vaut ~0,55, ce qui reproduit
la taille qu'il a aujourd'hui dans sa source de 560 px.

### Fusion, jamais remplacement

Un élément absent du JSON prend sa position par défaut ; un élément inconnu est
ignoré. Sans cela, ajouter un dix-huitième widget dans six mois ferait exploser
la disposition existante, et un JSON tronqué laisserait un overlay vide.

---

## Les éléments positionnables

Les clés des widgets sont **exactement** les `kind` que le code emploie déjà
(`BUILDERS[kind]`, `overlay.js:958`) : les inventer en français casserait la
correspondance. Les quatre clés nouvelles suivent la même langue.

| Clé | Ce que c'est | `solo` par défaut |
|---|---|---|
| `avatar` | Wally | non |
| `bubble` | sa bulle de BD | non |
| `rotator` | le rotateur de memes (ex-source OBS) | non |
| `image` | l'image plein cadre (ex-source OBS) | oui |
| `bingo` · `stats` · `goal` · `uptime` · `talkers` | les widgets qui s'installent | non |
| `meme` · `versus` · `poll` · `hangman` · `pinned` · `counter` · `coinflip` · `dice` · `wheel` · `gauge` · `countdown` · `rps` | ceux qui passent | oui |

### La bulle

Placement libre, **pointe conservée** : elle s'oriente automatiquement vers
l'avatar, où qu'il soit (arbitrage owner du 2026-08-15). Si l'avatar est masqué
dans la scène, la pointe disparaît — elle viserait le vide.

`?side=left` (`overlay.html:176`) devient redondant : l'ancrage le remplace. Le
paramètre reste accepté sans effet, le temps que les anciennes URL disparaissent.

---

## Le flux

```
                 ┌──────────────┐
   bot_state ◄───┤ overlay_layout│───► GET /api/public/overlay-layout?scene=…
 overlay:layout  │   (modèle)    │        (l'overlay se sert au démarrage)
                 └───────▲───────┘
                         │ PUT /api/admin/overlay/layout
                 ┌───────┴───────┐
                 │  panneau admin │
                 └───────┬───────┘
                         │ publie sur overlay_feed
                         ▼
              {"type":"layout","scene":…}
                         │
              ┌──────────┴──────────┐
              ▼          ▼          ▼
        /overlay-start  -jeu      -end
```

**Au démarrage**, la page lit son layout par un `GET` — source de vérité, sans
dépendre d'un événement qui pourrait ne jamais venir.

**Aux modifications**, l'admin écrit en base *et* publie sur `overlay_feed`, qui
fait déjà le fan-out par abonné (`sse.py:226`). `overlay.js` gagne un
`case "layout"` dans son dispatch (`overlay.js:1256`) qui réapplique les
positions sur ce qui est déjà à l'écran. Aucun rechargement, aucune
reconstruction de widget.

**Le champ `scene` sur les événements** : `null` vaut « toutes les pages » —
c'est le cas des widgets normaux, Wally ignorant quelle scène est à l'antenne.
Un slug vise une seule page : c'est le bouton *Tester*, qui ne doit surtout pas
surgir sur la scène en direct pendant qu'on règle celle de fin.

### Les routes

| Route | Rôle |
|---|---|
| `GET /overlay-<slug>` | la page d'une scène |
| `GET /overlay` | la scène par défaut — l'URL actuelle ne meurt pas |
| `GET /api/public/overlay-layout?scene=<slug>` | le layout d'une scène |
| `GET /api/admin/overlay/layout` | tout le modèle, pour l'admin |
| `PUT /api/admin/overlay/layout` | enregistre et publie |
| `POST /api/admin/overlay/preview` | *Tester* / *Tout afficher*, ciblés sur une scène |

**Slugs réservés** : `image`, `rotation`, `version`, `health`. `/overlay-image`
et `/overlay-rotation` existent déjà (`app.py:202`, `app.py:209`) ; une scène
nommée « image » les écraserait.

**Le renommage ne change pas le slug.** Si « Fin de stream » devenait « Outro »
et que l'URL suivait, la source OBS pointerait dans le vide — et on ne s'en
apercevrait qu'en direct, écran noir. Le slug est fixé à la création. Il reste
modifiable, mais explicitement, avec un avertissement qu'il faut retoucher OBS.

---

## Le panneau admin

Onglet **Système → Overlay**, disposition retenue au 2026-08-15 :

- **Colonne de gauche** : la liste des scènes (créer, dupliquer, renommer,
  supprimer) au-dessus de la liste des éléments. Chaque élément porte trois
  actions : masquer (œil), verrouiller (cadenas), tester (▶). La liste se
  réordonne au glisser, ce qui est en haut passe devant.
- **À droite** : la surface de placement au ratio 16/9, avec grille magnétique,
  poignées de redimensionnement, et les flèches du clavier pour l'ajustement fin.
- **Sous la surface** : les réglages de l'élément choisi — x, y, taille, ancrage.
- **En bas** : la case *Aperçu en direct*, le compteur de modifications en
  attente, **Mettre à jour**, **Abandonner**.

### Le mode brouillon

*Aperçu en direct* **décoché par défaut** : le cas dangereux ne doit pas être
celui qu'on obtient sans rien faire. Décoché, les modifications restent dans le
navigateur et l'overlay ne bouge pas d'un pixel — on peut préparer la scène de
fin pendant que le live tourne. **Mettre à jour** publie tout d'un coup.

Le brouillon **ne va pas en base** : sinon un redémarrage du bot publierait des
changements jamais validés. Il survit à un rafraîchissement de la page admin
(stockage navigateur), et quitter la page avec des modifications en attente
déclenche un avertissement.

Coché, chaque relâchement de glisser publie. Pendant le geste lui-même, la
surface bouge localement à 60 fps sans rien émettre : inonder le SSE pendant un
glisser n'apporte rien.

### Aides au placement

- **Ta capture de stream en fond** de la surface, à téléverser une fois. On
  place par rapport au décor réel — le cadre du chat, la zone de jeu — plutôt
  que dans le vide.
- **Tester** (▶) affiche un élément pour de vrai sur l'overlay, avec un contenu
  bidon, pendant qu'on le place. Sans lui, le chifoumi, le dé ou la jauge se
  régleraient à l'aveugle : ils n'apparaissent presque jamais.
- **Tout afficher** envoie des fantômes nommés de tous les éléments visibles de
  la scène. Tester un widget seul ne dit pas comment il cohabite avec les autres.
- **Chevauchement signalé** : deux éléments `solo: false` qui occupent la même
  zone deviennent illisibles en direct. Bordure orange dans la surface, avant
  que les viewers le voient.
- **Exporter / importer** le JSON : récupérer une disposition cassée, changer de
  machine, revenir à un réglage d'il y a trois semaines.
- **Annuler** la dernière publication (un niveau suffit) et **réinitialiser** un
  élément ou une scène entière.

---

## Ce que ça change pour Wally

**Un widget masqué partout n'est plus proposé.** Il sort de l'enum de
`show_overlay` (`overlay_narrator.py:254`) seulement s'il est masqué dans
**toutes** les scènes — masqué dans une seule, il reste utilisable, c'est la
page qui filtre.

**Et s'il le demande quand même**, l'outil lui répond « ce widget n'est visible
sur aucune scène » au lieu de le laisser annoncer « c'est à l'écran ». L'enum
seul ne suffit pas : une action différée ou un rappel programmé passe à côté.
On se branche sur `_note_overlay_refus()`, qui consigne déjà les refus.

C'est la leçon de « il ne savait pas qu'il affichait les bingos » : ce qu'il
croit avoir fait doit correspondre à ce qui s'est produit.

**La limite « un widget occupe tout l'espace » tombe.** L'avatar et la bulle
n'ont plus à s'effacer : `widget-on` ne s'applique qu'aux widgets `solo`. Wally
peut donc afficher un meme **et** le commenter, ce que `docs/overlay.md:331`
donnait pour impossible.

---

## Garde-fous

**Un layout illisible ne donne jamais un overlay vide.** JSON corrompu, clé
manquante, serveur muet : la page retombe sur les positions par défaut et
affiche quand même. Le pire scénario acceptable est « mal placé », jamais « rien
à l'écran » — ce réglage se manipule en plein live.

**Les positions sont bornées à l'enregistrement** (0 à 100 %), et la surface
signale un élément qui sortirait du cadre. Attention en implémentant : borner
une hauteur sans compter les marges a déjà inversé un garde-fou sur ce projet
(bulles BD, 2026-08-13).

**`locked`** empêche de déplacer un élément par accident — Wally et sa bulle
seront verrouillés une fois réglés.

---

## Ce que ça change dans OBS

Une manipulation, une fois, côté streamer :

1. Supprimer les trois sources actuelles (overlay, rotation, image).
2. Dans chaque scène OBS, ajouter **une** source navigateur en **1920 × 1080**,
   sans redimensionnement, fond transparent, pointant sur
   `https://heywally.fr/overlay-start`, `-jeu`, `-end`.

`https://heywally.fr/overlay` continue de servir la scène par défaut : rien ne
casse pendant la transition.

---

## Découpage

Une dizaine de fichiers — quatre phases, cinq fichiers au plus chacune.

| # | Contenu | Fichiers |
|---|---|---|
| 1 | Le modèle : `overlay_layout.py`, défauts, fusion, validation, persistance, les routes GET/PUT | `bot/core/overlay_layout.py`, `bot/dashboard/routes/overlay.py`, tests |
| 2 | L'overlay applique : ancrages, `scale`, canvas de référence, `case "layout"`, routes par scène, absorption du rotateur et de l'image | `overlay.html`, `overlay.js`, `app.py`, `overlay_rotation.html`, `overlay_image.html` |
| 3 | Le panneau : les deux listes, la surface, le glisser, le brouillon, publier | `app.js`, `style.css` |
| 4 | Finitions : *Tester*, *Tout afficher*, capture en fond, chevauchements, export/import, enum filtré et retour d'exécution | `overlay_narrator.py`, `routes/overlay.py`, `app.js` |

Chaque phase est vérifiée avant la suivante. Rien n'est visible du public avant
la phase 2, et l'ancienne URL reste servie tout du long.

## Tests

- **Le modèle** (phase 1) : fusion avec les défauts, élément inconnu ignoré,
  JSON corrompu, bornes, slug réservé refusé, renommage qui ne touche pas au
  slug, duplication qui copie bien les positions.
- **L'application** (phase 2) : chacun des neuf ancrages, le facteur de canvas à
  trois résolutions, un layout absent qui retombe sur les défauts, `solo: false`
  qui n'efface plus l'avatar.
- **Wally** (phase 4) : un widget masqué dans une seule scène reste dans l'enum ;
  masqué partout, il en sort ; demandé malgré tout, il reçoit un refus explicite
  et ne l'annonce pas comme affiché.

Chaque test doit échouer sur le code actuel avant d'être considéré comme valable
— la méthode des audits précédents.
