# Rotateur de memes — conception

**Date** : 2026-08-11 · **Statut** : validé, à implémenter
**Demande** : remplacer le widget « Asset rotator » de StreamElements par une
source OBS maison, qui fait défiler en boucle les médias de `data/memes`.

---

## 1. Pourquoi

L'overlay StreamElements de la chaîne contient **un seul widget**, de type
`se-widget-image-rotator` (800 × 600) : un média à la fois, entrée `fadeInLeft`,
~9 s visible, sortie `fadeOutRight`, puis un temps mort. Les fichiers sont
hébergés sur `cdn.streamelements.com/uploads/…`.

Et c'est là qu'est le défaut : **les médias finissent par ne plus charger**. Sur
la bibliothèque d'assets de la chaîne, cinq sur douze affichent aujourd'hui le
logo d'image cassée. Le contenu dépend d'un CDN et d'un compte que l'owner ne
maîtrise pas.

Servis depuis `data/memes`, les mêmes fichiers ne peuvent plus disparaître : ce
sont ses fichiers, sur son disque, déjà bind-montés dans le conteneur.

---

## 2. Ce qu'on construit

Une **page autonome**, sur le modèle de `/overlay-image`. Elle demande la liste
des médias une fois, puis tourne toute seule.

> **Décision :** la page ne dépend pas du bot une fois chargée. Un rebuild de
> Wally ne fige pas la source — elle continue avec la liste qu'elle a en mémoire.

Les deux autres pistes ont été écartées :

- **Piloter depuis le bot en SSE** (le patron de `/overlay-image`) : un défilé
  n'a besoin d'aucune intelligence, et ça rendrait la source dépendante d'un
  processus qui redémarre. C'est précisément la fragilité qu'on fuit.
- **Ajouter un mode rotation à l'overlay compagnon** : `overlay.js` fait déjà
  1123 lignes, les deux fonctions n'ont rien à voir, et le rotateur ne pourrait
  plus être placé et dimensionné indépendamment dans OBS.

Wally **n'intervient pas** sur cette source. Il garde son overlay compagnon pour
les memes qu'il commente.

---

## 3. Architecture

### 3.1 `bot/core/memes.py` — la bibliothèque (existant, deux ajouts)

Les formats vidéo rejoignent la table des types MIME (`.mp4` → `video/mp4`,
`.webm` → `video/webm`), pour que la route publique sache les servir.

```python
_MEDIA_TYPES = {…, ".mp4": "video/mp4", ".webm": "video/webm"}
_EXTENSIONS       = frozenset(images)            # ce que Wally peut MONTRER
_EXTENSIONS_MEDIA = frozenset(_MEDIA_TYPES)      # ce que la route peut SERVIR
```

- `list()` **ne change pas** : elle ne renvoie que des images. C'est celle que
  lit `OverlayNarrator`, qui affiche dans une balise `<img>`.
- `list_medias()` renvoie images **et** vidéos, chacune avec son genre.
- `resolve()` accepte désormais `_EXTENSIONS_MEDIA` : servir un fichier ne
  demande pas de savoir l'afficher.

> **Décision :** « ce que Wally peut montrer » n'est pas « ce que le rotateur
> peut jouer ». Une seule liste et le `.mp4` finirait dans un `<img>` du
> compagnon, cassé. C'est l'invariant que le test doit protéger.

### 3.2 `GET /api/public/rotation` — la liste

```json
{"medias": [{"nom": "meme1.webp", "genre": "image"},
            {"nom": "meme35.mp4", "genre": "video"}]}
```

Rien d'autre : pas les descriptions (le rotateur ne s'en sert pas), pas d'URL
absolue (la page les compose). Les fichiers passent par
`/api/public/meme/{nom}`, la route qui sert déjà les memes.

### 3.3 `bot/dashboard/static/overlay_rotation.html` — la page

Servie par `GET /overlay-rotation` dans `bot/dashboard/app.py`, exactement comme
`/overlay-image`. Autonome : HTML, CSS et JS dans un seul fichier, aucune
dépendance réseau sortante (`animate.min.css` n'est pas utilisé, les animations
sont écrites sur place).

---

## 4. Le cycle

```
tirer un média (jamais deux fois le même d'affilée)
  → PRÉCHARGER, attendre que les dimensions soient connues
  → rafale de glitch d'entrée
  → affichage franc (durée réglable, 9 s par défaut ;
                     pour une vidéo : jusqu'à la fin de la lecture)
  → rafale de glitch de sortie
  → noir (pause réglable, 5 s par défaut)
  → recommencer
```

Tous les **N affichages**, où N est la taille de la liste, la page redemande
celle-ci : un meme déposé dans le dossier pendant le live entre dans la rotation
sans toucher à OBS. Si l'appel échoue, elle garde la liste précédente. (En ordre
aléatoire, « un tour complet » ne veut rien dire — c'est bien un compteur
d'affichages, pas un parcours.)

### Réglages, passés dans l'URL de la source OBS

| Paramètre | Défaut | Rôle |
|---|---|---|
| `duree` | `9` | secondes d'affichage franc d'une image |
| `pause` | `5` | secondes de noir entre deux médias |
| `ordre` | `hasard` | `hasard` ou `dossier` (ordre alphabétique) |
| `saccade` | `33` | millisecondes par état de glitch |

Exemple : `/overlay-rotation?duree=12&pause=3`

La **taille et la position** ne sont pas des paramètres : elles se règlent en
redimensionnant la source dans OBS.

---

## 5. Le rendu

### 5.1 Le cadre — passe-partout sombre

Un liseré noir de 14 px entre l'image et une bordure orange braise de 3 px,
coins arrondis à 16 px, double lueur externe.

La raison n'est pas décorative : la plupart des memes sont sur **fond blanc**, et
sur le fond noir de l'overlay ça fait une dalle plus lumineuse que le titre de
l'écran. Un cadre orange collé au blanc n'y change rien — c'est le liseré sombre
qui casse le contact.

```css
padding: 14px;
background: rgba(8, 6, 5, 0.94);
border: 3px solid #ff7a2f;
border-radius: 16px;
box-shadow: 0 0 24px rgba(255,122,47,.6),
            inset 0 0 30px rgba(0,0,0,.9),
            0 18px 45px rgba(0,0,0,.8);
```

### 5.2 Les formats

L'image est **bornée en largeur et en hauteur, et jamais agrandie** ; le cadre
l'épouse. Un portrait 500 × 852 est limité par la hauteur, un panoramique
1024 × 576 par la largeur, un petit meme 322 × 378 garde sa taille au lieu
d'être étiré en flou. Les bornes sont exprimées en pourcentage de la source OBS,
pas en pixels, pour survivre à un redimensionnement.

### 5.3 La transition — datamosh procédural

Le bloc **entier, cadre compris**, est pris dans l'effet : bandes découpées au
`clip-path`, décalages horizontaux, dérives de couleur (`invert`, `hue-rotate`,
dédoublement rouge/cyan), un état toutes les **33 ms**, sept états par rafale.

Deux points qui ne sont pas des détails :

1. **Les états sont tirés au sort à chaque passage.** Un glitch rejoué à
   l'identique toutes les 15 s se lit comme une boucle et devient mécanique.
2. **Le média change pendant le noir, une fois préchargé.** C'est ce qui rend le
   changement de format invisible. Sans préchargement, l'image arriverait après
   l'affichage du cadre et on verrait celui-ci grandir d'un coup ; sans le noir,
   on le verrait sauter d'un format à l'autre.

Le glitch est écrit en JavaScript, pas en `@keyframes` : c'est ce qui permet le
tirage au sort. Le coût est le même — ce sont les mêmes propriétés qui bougent.

---

## 6. Robustesse

Six pannes, six réponses. C'est cette section qui sépare cette source de celle
qu'elle remplace.

| Panne | Réponse |
|---|---|
| **Un fichier ne charge pas** | L'événement `error` fait passer au suivant immédiatement, et le fichier sort de la liste pour la session. Pas de cadre vide. |
| **Une vidéo refuse de démarrer** | `play()` renvoie une promesse rejetée (Chrome bloque la lecture audio automatique) → seconde tentative **en muet**, puis passage au suivant. Sans ça, la boucle attendrait un `ended` qui ne viendrait jamais. |
| **Une vidéo ne se termine pas** | Minuteur de sécurité : durée annoncée + 5 s, ou 60 s si la durée est inconnue. |
| **La source se fige** | Chien de garde : plus aucun signe de vie depuis `3 × (duree + pause)` secondes → la page se recharge. Un « signe de vie » est un affichage de média **ou** l'événement `timeupdate` d'une vidéo en cours : sans cette seconde condition, une vidéo de deux minutes se ferait couper au milieu par son propre gardien. |
| **L'API est injoignable** | La dernière liste connue est conservée. Si aucune n'a jamais été reçue, nouvel essai toutes les 10 s, **sans rien afficher** — c'est une source de live, pas une page web : aucun message d'erreur à l'écran. |
| **Le dossier change** | Relecture de la liste à chaque tour complet du pool. |

---

## 7. Tests

**Python** — ce qui est testable normalement :

- `list_medias()` renvoie images et vidéos avec le bon genre ;
- **le `.mp4` n'apparaît pas dans `list()`** — le test qui protège l'overlay
  compagnon de Wally ;
- `GET /api/public/rotation` renvoie la structure attendue, et une liste vide si
  le dossier manque (pas une erreur) ;
- `.mp4` est servi en `video/mp4`.

**La page** — le projet ne teste pas le JavaScript et on n'invente pas un
harnais pour l'occasion. Vérification au navigateur, en provoquant les pannes
pour de vrai : un nom de fichier inexistant dans la liste, une vidéo cassée,
l'API coupée. Critère unique : **la boucle ne s'arrête jamais**, quoi qu'on lui
envoie.

---

## 8. Installation dans OBS

| Réglage | Valeur |
|---|---|
| Source | Navigateur (`Browser Source`) |
| URL | `https://heywally.fr/overlay-rotation` |
| Largeur × hauteur | au goût — 800 × 600 reproduit le widget actuel |
| Fond | transparent |
| Contrôler l'audio via OBS | **coché** (sinon les vidéos sont muettes) |

---

## 9. Ce qu'on ne fait pas

- **Pas de sous-dossier de sélection** : le pool est `data/memes` en entier.
- **Pas de réglages en base ni dans le panneau admin** : l'URL suffit.
- **Pas de plafond de durée sur les vidéos** : elles jouent jusqu'au bout, seul
  le minuteur de sécurité intervient.
- **Pas de SSE, pas de contrôle par Wally.** Si le besoin apparaît un jour, il
  s'ajoutera par-dessus une page qui tourne déjà.
- **Le `.mp4` reste invisible pour l'overlay compagnon**, qui ne sait pas jouer
  de vidéo.
