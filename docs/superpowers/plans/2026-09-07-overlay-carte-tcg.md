# La carte du TCG sur l'overlay — plan d'implémentation

> **Pour un agent exécutant** : ce plan s'exécute tâche par tâche. Les étapes
> sont des cases à cocher. Le plan ARGUMENTE depuis la spec — les deux se
> lisent ensemble.

**But** : Wally affiche la carte d'une personne sur l'overlay OBS ; elle arrive
à plat, se déplie en 3D, tourne doucement, puis s'en va.

**Approche** : la source des cartes passe en Python (elle n'existe qu'en
JavaScript aujourd'hui, ce qui bloque tout le reste) ; le composant de rendu
devient pilotable par script et déménage dans un dossier partagé par le site
public et l'overlay ; le widget s'ajoute au registre existant et se déclenche
par une valeur d'enum de `show_overlay`, sans nouvel outil.

**Pile** : Python 3.12 · FastAPI · JavaScript vanilla (modules ES, aucun
framework, aucune dépendance ajoutée).

**Spec** : `docs/superpowers/specs/2026-09-07-overlay-carte-tcg-design.md`

## Contraintes globales

- **Ce bot tourne en PRODUCTION.** Publier dans la même foulée : commit, push,
  et rebuild si du Python a bougé (`GIT_HASH=$(git rev-parse --short HEAD)
  BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) docker compose up -d --build wally`).
- **Vérifications avant de déclarer une tâche finie** : `python3 -m pytest
  tests/ -q` · `lint_types` · `lint_silences` · `lint_ruff` · `lint_logs` ·
  `lint_mort`. Si du JS a bougé : `lint_js` **et** `smoke_front.py`.
  Ne JAMAIS abaisser un cliquet (`--maj`) pour faire passer du code neuf.
- **`loguru` uniquement**, jamais `print()` ni `import logging`. Toujours
  `{e!r}` et jamais `{e}` pour journaliser une exception.
- **Aucun `except` muet** : journaliser, relever, ou rendre un repli explicite.
- **Pas de code mort** : avant d'ajouter une fonction publique, un champ de
  config ou un attribut, nommer son appelant. S'il n'y en a pas, ne pas l'écrire.
- **Un réglage s'écrit du CONSOMMATEUR vers l'UI**, jamais l'inverse.
- **Aucune règle de jeu en JavaScript.** Le moteur vit côté serveur.
- Français partout : noms de symboles, commentaires, messages.

## Références de non-régression

`/opt/design-tcg/references-avant-refactor/` — les quatre cartes au repos et en
survol à un angle de curseur **fixe** (28 %, 22 %), plus la matrice 3D relevée
de chacune. Elles datent d'avant la première ligne modifiée.

| Carte | `transform` attendu après refactor (position fixe) |
|---|---|
| Azraël | `matrix3d(1.03311, -0.017462, 0.118252, …)` |
| Claker | `matrix3d(1.03752, -0.00630969, 0.0715447, …)` |
| rhae___ | `matrix3d(1.03559, -0.011199, 0.0950464, …)` |
| Lilith | `matrix3d(1.03612, -0.00984732, 0.0891959, …)` |

Toutes avec `perspective: 1100px`, `transform-style: preserve-3d`,
`.chero-cadres` en `visible`, `.chero-libre` en `opacity: 1`.

---

## Structure des fichiers

**Créés**

| Fichier | Responsabilité |
|---|---|
| `bot/core/tcg_cartes.py` | La source unique des cartes : dataclass + registre + résolution d'un pseudo. Aucun I/O, aucune dépendance au bot. |
| `bot/dashboard/routes/tcg.py` | `public_router` : `GET /api/public/tcg/cartes`. |
| `public-ui/partage/dom.js` | `h()`, déplacé depuis `app.js`. Le seul module que site et overlay importent tous deux. |
| `public-ui/partage/tcg-carte.js` | Le composant, déplacé et rendu pilotable. |
| `public-ui/partage/tcg-carte.css` | Sa feuille, déplacée. |
| `public-ui/pages/tcg-donnees.js` | Le fetch des cartes, **mémorisé** : un seul appel pour les deux pages. |
| `bot/dashboard/static/overlay_tcg.js` | Le rendu de la carte sur l'overlay et sa chorégraphie. |
| `public-ui/vendor/archivo-black.woff2` + une règle `@font-face` | La police, vendorée. |
| `tests/test_tcg_cartes.py` | Le registre et la résolution par pseudo. |
| `tests/dashboard/test_route_tcg.py` | La route publique. |
| `tests/dashboard/test_cache_medias.py` | Le correctif de cache. |

**Modifiés**

| Fichier | Ce qui change |
|---|---|
| `bot/dashboard/app.py:57-70` | `SPAStaticFiles` : `no-cache` sur les médias, `no-store` ailleurs. Montage du router `tcg`. |
| `public-ui/app.js` | `h()` part dans `partage/dom.js` et est **réexporté** (six pages l'importent de là). |
| `public-ui/pages/tcg.js` · `demo-carte-azrael.js` | Lisent `tcg-donnees.js` au lieu de `tcg-collection.js`. |
| `bot/core/overlay_layout.py` · `overlay_elements.py` | La clé `carte` et son libellé. |
| `bot/dashboard/static/overlay.js` · `overlay.html` | Le builder et le chargement de la feuille + police au boot. |
| `bot/intelligence/overlay_narrator.py` | `carte` dans l'enum, paramètre `personne`. |
| `bot/discord/handlers.py` · `bot/twitch/handlers.py` | Le routage de la valeur `carte`. |
| `scripts/smoke_front.py` | Le survol de `.chero` mesuré. |

**Supprimés**

`public-ui/pages/tcg-collection.js` et `public-ui/pages/tcg-carte-hero.{js,css}`
— déplacés, pas dupliqués. Une copie laissée derrière est du code mort qui
diverge.

---

# Phase 1 — le socle

**Critère de sortie de la phase** : `/tcg` et `/demo/carte-azrael` rendent
exactement comme avant — mêmes captures, mêmes matrices 3D — et le smoke test
étendu l'atteste.

---

### Tâche 1 : le cache des médias

Défaut **déjà en production**, indépendant du reste : à traiter en premier, il
se vérifie seul.

**Fichiers**
- Modifier : `bot/dashboard/app.py:57-70` (`SPAStaticFiles.get_response`)
- Test : `tests/dashboard/test_cache_medias.py` (créer)

**Interfaces**
- Produit : rien de nouveau. Le comportement d'un en-tête HTTP change.

- [ ] **Étape 1 — le test qui échoue**

```python
# tests/dashboard/test_cache_medias.py
"""Une illustration n'est pas du code : elle doit pouvoir être revalidée.

`no-store` interdit AU NAVIGATEUR de garder quoi que ce soit. Posé sur tout
`public-ui/`, il fait retélécharger ~1 Mo d'illustrations à chaque visite de
`/tcg` — et le referait à chaque affichage de carte sur l'overlay.
"""
import pytest

from bot.dashboard.app import _entete_cache


@pytest.mark.parametrize("chemin", [
    "assets/tcg-azrael-hero.avif",
    "assets/tcg-claker-fond.webp",
    "vendor/archivo-black.woff2",
    "wally.webm",
])
def test_les_medias_sont_revalidables(chemin):
    """`no-cache` fait REVALIDER, il n'interdit pas de garder : le navigateur
    envoie son ETag et reçoit un 304 sans corps."""
    entete = _entete_cache(chemin)
    assert "no-store" not in entete
    assert "no-cache" in entete


@pytest.mark.parametrize("chemin", [
    "index.html", "app.js", "style.css", "pages/tcg.js", "",
])
def test_le_code_du_front_n_est_jamais_gardé(chemin):
    """C'est ce `no-store` qui rend le front modifiable sans rebuild : le
    retirer ferait servir du JavaScript périmé après une correction."""
    assert "no-store" in _entete_cache(chemin)
```

- [ ] **Étape 2 — vérifier qu'il échoue**

`python3 -m pytest tests/dashboard/test_cache_medias.py -q`
Attendu : `ImportError: cannot import name '_entete_cache'`.

- [ ] **Étape 3 — implémenter**

Dans `bot/dashboard/app.py`, à côté du `mimetypes.add_type` existant :

```python
# Les extensions dont le contenu n'est pas du code. Elles portent un nom
# STABLE (`tcg-azrael-hero.avif`) et sont réécrites en place par
# `scripts/generer_illustrations_tcg.py` : d'où `no-cache` (revalider) et
# jamais `immutable` (ne plus jamais redemander), qui figerait une
# illustration retouchée dans le navigateur de chaque visiteur.
_EXT_MEDIAS = (".avif", ".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg",
               ".webm", ".mp4", ".woff2", ".woff", ".ico")

_CACHE_CODE = "no-store, no-cache, must-revalidate, max-age=0"
_CACHE_MEDIA = "no-cache"


def _entete_cache(chemin: str) -> str:
    """La valeur de `Cache-Control` pour un fichier du site public."""
    return _CACHE_MEDIA if chemin.lower().endswith(_EXT_MEDIAS) else _CACHE_CODE
```

Puis dans `SPAStaticFiles.get_response`, remplacer les deux affectations en dur
par `_entete_cache(path)`. ⚠️ Le repli `index.html` du 404 garde `_CACHE_CODE` :
c'est du HTML, quel que soit le chemin demandé.

- [ ] **Étape 4 — vérifier qu'il passe**

`python3 -m pytest tests/dashboard/test_cache_medias.py -q` → PASS

- [ ] **Étape 5 — vérifier en RÉEL** (un test ne prouve pas l'en-tête servi)

```bash
GIT_HASH=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  docker compose up -d --build wally && sleep 12
curl -s -D- -o /dev/null http://127.0.0.1:8080/assets/tcg-azrael-hero.avif | grep -i cache-control
curl -s -D- -o /dev/null http://127.0.0.1:8080/app.js | grep -i cache-control
# puis la revalidation : un 304, sans corps
ETAG=$(curl -s -D- -o /dev/null http://127.0.0.1:8080/assets/tcg-azrael-hero.avif | grep -i '^etag' | cut -d' ' -f2 | tr -d '\r')
curl -s -o /dev/null -w '%{http_code} %{size_download}o\n' -H "If-None-Match: $ETAG" \
  http://127.0.0.1:8080/assets/tcg-azrael-hero.avif
```
Attendu : `no-cache` sur l'image, `no-store` sur `app.js`, puis `304 0o`.

- [ ] **Étape 6 — la suite complète, les cliquets, commit, push**

---

### Tâche 2 : la source des cartes en Python

**Fichiers**
- Créer : `bot/core/tcg_cartes.py`
- Créer : `bot/dashboard/routes/tcg.py`
- Modifier : `bot/dashboard/app.py` (monter le router)
- Test : `tests/test_tcg_cartes.py`, `tests/dashboard/test_route_tcg.py`

**Interfaces**
- Produit :
  - `CarteTcg` — dataclass gelée : `cle: str`, `nom: str`, `legende: str`,
    `classe: str`, `ultime: str`, `description: str`, `ambiance: str`,
    `cout: int`, `atk: int`, `pv: int`, `aura: int`, `accent: str`,
    `hero: str`, `fond: str`, `avant_plan: str | None`,
    `hero_3d: str | None`, et les six réglages de cadrage
    (`hero_cote`, `hero_haut`, `hero_echelle`, `hero_3d_cote`,
    `hero_3d_haut`, `avant_plan_largeur`, `avant_plan_bas`),
    plus `particules: str`, `parallaxe: float`, `intensite: float`.
    Les champs d'illustration portent un chemin **sans extension**
    (`/assets/tcg-azrael-hero`) : le front y ajoute `.avif` et `.webp`.
  - `empreinte(base: str) -> str` — les 8 premiers caractères du sha256 du
    fichier `.avif`, calculés au premier appel et mémorisés.

⚠️ **Les URL d'illustration sont VERSIONNÉES** (`…-hero.avif?v=a1b2c3d4`).
Mesuré en prod le 2026-09-07 : la zone Cloudflare porte
`browser_cache_ttl = 14400`, qui **écrase le `Cache-Control` de l'origine**
pour tout ce qu'elle juge cacheable — `CDN-Cache-Control` n'y change rien. Une
illustration retouchée resterait donc quatre heures figée chez les visiteurs.
Versionner par le contenu règle le problème sans dépendre d'un réglage de zone,
et le dépôt a déjà ce mécanisme pour le panneau admin (`_ASSET_VERSION_RE`).

⚠️ L'empreinte se calcule sur le fichier `.avif` seul et sert aux DEUX formats :
le script les régénère toujours ensemble, et lire deux fichiers pour une seule
version doublerait les I/O sans rien garantir de plus.

⚠️ Un fichier manquant ne doit pas empêcher le boot : journaliser en
`warning` et rendre une empreinte vide (l'URL reste valide, elle n'est
simplement pas versionnée). Une illustration absente est un défaut de
déploiement, pas une raison de ne pas démarrer.
  - `CARTES: dict[str, CarteTcg]` — le registre, clé = identifiant court.
  - `resoudre(nom: str) -> CarteTcg | None` — insensible à la casse et aux
    accents ; compare à la clé, au nom, et aux **alias déclarés par la carte**
    (`alias: tuple[str, ...]`, un champ de plus sur la dataclass).
    ⚠️ Pas de lecture en base : les alias de `memory` lient un pseudo à un
    `canonical_uid`, donc à une PERSONNE, et une carte n'a pas d'uid. Le lien
    pseudo → carte est éditorial.
  - `noms_disponibles() -> list[str]` — pour le message de refus.
- Consomme : rien.

- [ ] **Étape 1 — le test qui échoue**

```python
# tests/test_tcg_cartes.py
from bot.core import tcg_cartes


def test_les_quatre_cartes_terminées_sont_là():
    assert set(tcg_cartes.CARTES) == {"azrael", "claker", "rhae", "lilith"}


def test_toute_carte_déclare_ses_illustrations_sans_extension():
    """Le front sert l'AVIF avec repli WebP : il ajoute l'extension lui-même.
    Un chemin qui en porte une ici donnerait `/assets/x.webp.avif`."""
    for carte in tcg_cartes.CARTES.values():
        for chemin in (carte.hero, carte.fond, carte.avant_plan, carte.hero_3d):
            if chemin is not None:
                assert not chemin.endswith((".avif", ".webp", ".png")), chemin


def test_résolution_par_pseudo_complet_court_et_casse():
    for saisi in ("claker", "CLAKER", "ClakerNoJutsu", "clakernojutsu"):
        assert tcg_cartes.resoudre(saisi) is tcg_cartes.CARTES["claker"]


def test_résolution_par_alias_déclaré():
    """« clacker » avec deux c est la faute la plus courante sur ce pseudo :
    elle est déclarée en alias, pas devinée par une distance d'édition — une
    correspondance floue finirait par confondre deux personnes."""
    assert tcg_cartes.resoudre("clacker") is tcg_cartes.CARTES["claker"]
    assert tcg_cartes.resoudre("rhae___") is tcg_cartes.CARTES["rhae"]


def test_résolution_ignore_les_accents():
    """« azrael » sans tréma doit tomber sur Azraël : personne ne tape le tréma
    dans un chat, et le modèle non plus."""
    assert tcg_cartes.resoudre("azrael") is tcg_cartes.CARTES["azrael"]
    assert tcg_cartes.resoudre("azraël") is tcg_cartes.CARTES["azrael"]


def test_un_nom_inconnu_rend_None_et_non_une_carte_au_hasard():
    assert tcg_cartes.resoudre("personne") is None
    assert tcg_cartes.resoudre("") is None


def test_les_noms_disponibles_servent_au_message_de_refus():
    noms = tcg_cartes.noms_disponibles()
    assert "Azraël" in noms and len(noms) == len(tcg_cartes.CARTES)
```

- [ ] **Étape 2** — `python3 -m pytest tests/test_tcg_cartes.py -q` → échoue
  (`ModuleNotFoundError`).

- [ ] **Étape 3 — écrire `bot/core/tcg_cartes.py`**

Recopier les valeurs depuis `public-ui/pages/tcg-collection.js`, **sans rien
recalculer**. Reprendre en tête du module l'avertissement qui y figure :
les chiffres sont des PLACEHOLDERS, la source des vraies valeurs est la base
Notion, et **ne jamais justifier une valeur par le barème**.

`resoudre()` normalise avec `unicodedata.normalize("NFD", …)` puis retire les
marques diacritiques, met en minuscules, et compare à la clé, au `nom` et aux
`alias` de chaque carte.

⚠️ **Correspondance EXACTE sur la table normalisée, jamais floue.** Une
distance d'édition finirait par afficher la carte de quelqu'un d'autre — et
c'est un geste public, sur un stream.

- [ ] **Étape 4** — le test passe.

- [ ] **Étape 5 — la route**

```python
# tests/dashboard/test_route_tcg.py
def test_la_route_rend_les_cartes_dans_l_ordre_du_registre(client):
    r = client.get("/api/public/tcg/cartes")
    assert r.status_code == 200
    cartes = r.json()["cartes"]
    assert [c["nom"] for c in cartes] == ["AZRAËL", "CLAKER", "RHAE", "LILITH"]


def test_la_route_ne_fuit_aucune_clé_interne(client):
    """Elle est PUBLIQUE : tout ce qu'elle rend part à n'importe quel visiteur."""
    for carte in client.get("/api/public/tcg/cartes").json()["cartes"]:
        assert set(carte) <= {
            "cle", "nom", "legende", "classe", "ultime", "description",
            "ambiance", "cout", "atk", "pv", "aura", "accent", "hero", "fond",
            "avantPlan", "hero3d", "heroCote", "heroHaut", "heroEchelle",
            "hero3dCote", "hero3dHaut", "avantPlanLargeur", "avantPlanBas",
            "particules", "parallaxe", "intensite",
        }
```

⚠️ Les clés partent en **camelCase** : c'est le vocabulaire que le composant
lit déjà (`heroCote`, `avantPlanBas`). Renommer côté JS ferait toucher le
composant pour rien pendant un refactor dont le critère est « rien ne change ».

`bot/dashboard/routes/tcg.py` expose `public_router` ; le monter dans
`app.py` à côté des autres, `prefix="/api/public"`.

- [ ] **Étape 6** — suite complète, cliquets, rebuild, `curl` de la route,
  commit, push.

---

### Tâche 3 : le composant pilotable, dans `partage/`

⚠️ **Aucun changement de comportement visible.** C'est un déménagement plus un
changement de signature interne. Toute différence à l'écran est un bug.

**Fichiers**
- Créer : `public-ui/partage/dom.js`, `public-ui/partage/tcg-carte.js`,
  `public-ui/partage/tcg-carte.css`
- Supprimer : `public-ui/pages/tcg-carte-hero.{js,css}` (via `git mv`)
- Modifier : `public-ui/app.js`, `public-ui/pages/tcg.js`,
  `public-ui/pages/demo-carte-azrael.js`, `public-ui/pages/tcg-collection.js`

**Interfaces**
- Produit :
  - `public-ui/partage/dom.js` → `export function h(tag, attrs, ...kids)` —
    déplacé **sans une modification**.
  - `public-ui/partage/tcg-carte.js` →
    - `export function image(base)` (inchangé)
    - `export function monterStylesCarte()` (inchangé, chemins mis à jour)
    - `export function carteHero(carte, options = {})` où
      `options.interactif` vaut `true` par défaut.
      Rend `{ boite, detruire, ouvrir, fermer, incliner }`.
    - `incliner(nx, ny)` avec `nx`, `ny` ∈ [−0.5, +0.5] — **0,0 = centre**.
- Consomme : rien de Python.

- [ ] **Étape 1 — `h()` déménage**

`git mv` du corps de `h()` vers `partage/dom.js`, puis dans `app.js` :

```js
// `h()` vit dans `partage/` : l'overlay en a besoin, et il ne peut pas
// importer cette coquille — il tirerait Lenis, le routeur et les flux SSE.
// Réexporté ici parce que SIX pages l'importent depuis `../app.js`.
export { h } from './partage/dom.js';
```

- [ ] **Étape 2 — vérifier que rien n'a bougé**

`node --check` sur les fichiers touchés, puis
`python3 scripts/smoke_front.py --public`. Les six pages doivent monter.
**Commit ici** : ce déplacement se vérifie seul et n'a pas à être mêlé au reste.

- [ ] **Étape 3 — le composant déménage**

`git mv public-ui/pages/tcg-carte-hero.js public-ui/partage/tcg-carte.js`
(idem pour le `.css`). Mettre à jour `FEUILLE` (`/partage/tcg-carte.css`) et
l'import de `h` (`./dom.js`).

- [ ] **Étape 4 — `incliner()` prend des coordonnées normalisées**

Aujourd'hui la fonction interne lit l'événement. Après :

```js
/** Incline la carte. `nx`/`ny` ∈ [−0.5, +0.5], 0,0 au centre.
 *
 * Le calcul depuis un événement de pointeur ne disparaît pas : il déménage
 * chez l'appelant (`surMouvement`). C'est ce qui rend la carte jouable SANS
 * curseur — l'overlay n'en a pas, et sa chorégraphie appelle directement ici.
 */
const incliner = (nx, ny) => {
  const max = 15 * c.intensite;
  const tiltX = nx * max * 2;
  const tiltY = ny * max * 2;
  // … le corps existant, inchangé à partir d'ici
};

const surMouvement = (e) => {
  const r = racine.getBoundingClientRect();
  if (!r.width || !r.height) return;
  dernier = { nx: (e.clientX - r.left) / r.width - .5,
              ny: (e.clientY - r.top) / r.height - .5 };
  if (!attend) { attend = true; requestAnimationFrame(ecrireDernier); }
};
```

⚠️ Le `requestAnimationFrame` de coalescence reste **sur le chemin du
pointeur**, pas dans `incliner()` : la chorégraphie de l'overlay appelle déjà
depuis une boucle, un second rAF y ajouterait une image de retard.

- [ ] **Étape 5 — le drapeau `interactif`**

```js
const { interactif = true } = options;
if (interactif && tactile) {
  racine.addEventListener('click', basculer);
} else if (interactif && !SOBRE()) {
  racine.addEventListener('pointerenter', entrer);
  racine.addEventListener('pointermove', surMouvement, { passive: true });
  racine.addEventListener('pointerleave', sortir);
}
```

Et `return { boite, detruire, ouvrir: () => entrer(null), fermer: sortir,
incliner };`

⚠️ `entrer` prend aujourd'hui un événement pour amorcer la position du
curseur. `ouvrir()` passe `null` : le chemin existe déjà (c'est celui du tap).

- [ ] **Étape 6 — vérifier l'ABSENCE de régression**

```bash
python3 - <<'PY'
# Rejoue EXACTEMENT le relevé de référence : même viewport, même position.
from playwright.sync_api import sync_playwright
POS = (0.28, 0.22)
ATTENDU = {
  0: "matrix3d(1.03311, -0.017462, 0.118252",
  1: "matrix3d(1.03752, -0.00630969, 0.0715447",
  2: "matrix3d(1.03559, -0.011199, 0.0950464",
  3: "matrix3d(1.03612, -0.00984732, 0.0891959",
}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width":1500,"height":1400}, device_scale_factor=2)
    pg.goto("http://127.0.0.1:8080/tcg", wait_until="networkidle")
    pg.wait_for_timeout(3000)
    for i in range(4):
        carte = pg.locator(".chero").nth(i)
        box = carte.bounding_box()
        pg.mouse.move(box["x"] + box["width"]*POS[0], box["y"] + box["height"]*POS[1])
        pg.wait_for_timeout(1600)
        got = pg.evaluate("(n) => getComputedStyle("
                          "document.querySelectorAll('.chero-carte')[n]).transform", i)
        assert got.startswith(ATTENDU[i]), f"carte {i} : {got}"
        pg.mouse.move(10, 10); pg.wait_for_timeout(900)
    print("les quatre matrices sont identiques aux références")
    b.close()
PY
```

Puis comparer les captures à `/opt/design-tcg/references-avant-refactor/`.

- [ ] **Étape 7** — cliquets JS, smoke, commit, push.

---

### Tâche 4 : le front lit la route, et le smoke test voit la 3D

**Fichiers**
- Créer : `public-ui/pages/tcg-donnees.js`
- Supprimer : `public-ui/pages/tcg-collection.js`
- Modifier : `public-ui/pages/tcg.js`, `public-ui/pages/demo-carte-azrael.js`,
  `public-ui/pages/tcg.css`, `scripts/smoke_front.py`

**Interfaces**
- Produit : `export async function cartes()` — rend `CarteTcg[]` en camelCase,
  **mémorisé** : le second appel ne refait pas de requête. Lève en cas d'échec
  réseau, l'appelant décide quoi montrer.
- Consomme : `GET /api/public/tcg/cartes` (tâche 2), `image()` (tâche 3).

- [ ] **Étape 1 — le module de données**

```js
// public-ui/pages/tcg-donnees.js
import { image } from '../partage/tcg-carte.js';

// Un seul appel pour les deux pages qui affichent des cartes. Sans cette
// mémorisation, aller de /tcg à /demo/carte-azrael redemanderait la même
// liste — et deux réponses, c'est deux occasions de diverger à l'écran.
let _promesse = null;

export function cartes() {
  if (!_promesse) {
    _promesse = fetch('/api/public/tcg/cartes')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => d.cartes.map((c) => ({
        ...c,
        // Le serveur envoie un chemin SANS extension ; c'est ici qu'on en
        // fait la paire AVIF + repli WebP.
        hero: image(c.hero),
        fond: image(c.fond),
        avantPlan: c.avantPlan ? image(c.avantPlan) : null,
        hero3d: c.hero3d ? image(c.hero3d) : null,
      })))
      // Un échec ne doit pas être mémorisé : la page suivante doit pouvoir
      // réessayer, sinon une coupure d'une seconde vide le site jusqu'au
      // rechargement.
      .catch((e) => { _promesse = null; throw e; });
  }
  return _promesse;
}
```

- [ ] **Étape 2 — `/tcg` consomme, et DIT quand ça échoue**

`mount()` devient asynchrone : squelette, puis remplissage. En cas d'échec,
rendre un bloc `.tcgal-echec` nommé (« Les cartes n'ont pas pu être chargées. »)
avec un bouton qui rappelle `cartes()`.

⚠️ **Ne pas laisser une grille vide** : elle se lit « il n'y a pas de cartes »,
ce qui est faux. Le compteur (« 4 CARTES TERMINÉES ») se calcule après la
réponse, pas avant.

⚠️ `unmount()` peut être appelé pendant que le fetch est en vol : garder un
drapeau et ne rien insérer dans un `el` qui n'est plus à l'écran.

- [ ] **Étape 3 — le smoke test mesure l'effet 3D**

Dans `verifier_site_public`, après la boucle des pages :

```python
# L'effet 3D des cartes du TCG n'était couvert par RIEN : le test de relief
# existant vise les `[data-tilt]` du site, pas `.chero`. Une carte peut
# monter, s'afficher, et ne plus s'incliner du tout sans qu'un test bronche.
page.goto(f"{BASE}/tcg", wait_until="networkidle", timeout=40000)
page.wait_for_selector(".chero", timeout=_ATTENTE_PANNEAU_MS)
page.wait_for_timeout(1500)
carte = page.locator(".chero").first
boite = carte.bounding_box()
page.mouse.move(boite["x"] + boite["width"] * 0.28,
                boite["y"] + boite["height"] * 0.22)
page.wait_for_timeout(1200)
etat = page.evaluate("""() => {
  const c = document.querySelector('.chero');
  return {
    perspective: getComputedStyle(c).perspective,
    transform: getComputedStyle(c.querySelector('.chero-carte')).transform,
    cadres: getComputedStyle(c.querySelector('.chero-cadres')).visibility,
  };
}""")
rap.dire(etat["perspective"] == "1100px",
         "carte TCG : la 3D est posée au survol", str(etat["perspective"]))
rap.dire(etat["transform"].startswith("matrix3d"),
         "carte TCG : elle s'incline vraiment", etat["transform"][:60])
rap.dire(etat["cadres"] == "visible",
         "carte TCG : les cadres s'allument", etat["cadres"])

page.mouse.move(10, 10)
page.wait_for_timeout(1200)
apres = page.evaluate("""() => {
  const c = document.querySelector('.chero');
  return { perspective: getComputedStyle(c).perspective,
           cadres: getComputedStyle(c.querySelector('.chero-cadres')).visibility };
}""")
# La 3D RETIRÉE au repos est la moitié qui compte : c'est elle qui garde une
# grille de vingt cartes à un calque GPU au lieu de neuf par carte.
rap.dire(apres["perspective"] == "none",
         "carte TCG : et revient à plat en sortant", str(apres["perspective"]))
rap.dire(apres["cadres"] == "hidden",
         "carte TCG : les cadres s'éteignent", apres["cadres"])
```

⚠️ On mesure l'**état rendu**, jamais qu'une fonction a été appelée : un test
qui assère une ligne d'implémentation fige le défaut le jour où elle change.

- [ ] **Étape 4** — suite, cliquets JS, `smoke_front.py --public`, comparaison
  aux captures de référence, commit, push.

- [ ] **Étape 5 — GATE : montrer les captures avant/après à l'owner** et
  attendre son accord avant la phase 2.

---

# Phase 2 — le widget

**Critère de sortie** : la carte jouée sur `overlay.html`, captures des quatre
phases, et le widget réglable depuis le panneau de mise en scène.

---

### Tâche 5 : la clé dans le registre

🚨 **Cette tâche N'EST PAS commitable seule.** Quatre verrous du projet la
tiennent avec le front de l'overlay ; la clé ajoutée sans eux laisse la suite
rouge. Découvert le 2026-09-07 en l'exécutant, et le plan avait tort de les
séparer. À faire d'un seul geste avec la tâche 6.

| Verrou | Ce qu'il réclame | Où |
|---|---|---|
| `_ORDRE_DEFAUT` | la clé DANS cette liste | `overlay_layout.py:826` |
| `test_overlay_wally_visible` | le compte d'éléments (37 → 38) et une phrase disant que `carte` efface Wally | `tests/test_overlay_wally_visible.py:58` |
| `test_overlay_preview` | une entrée dans `_ECHANTILLONS` | `bot/dashboard/routes/overlay.py:468` |
| `test_overlay_layout_css` | `"carte"` en JS **et** `<div data-element="carte">` en HTML | `overlay_layout.js`, `overlay.html` |

🚨 **`_ORDRE_DEFAUT` est le plus coûteux des quatre** : `fusionner()` complète
l'empilement depuis cette liste et non depuis `ELEMENTS`. Une clé qui n'y
figure pas n'entre jamais dans `ordre`, et un élément absent d'`ordre` **n'est
pas rendu du tout**. Le widget aurait été réglable dans le panneau et invisible
en live — le pire des deux mondes, et rien ne l'aurait dit.

Le compte `37` du test `wally_visible` n'est pas un oubli : il est conçu pour
obliger à passer par ce fichier et à se demander si le nouvel élément efface
Wally.

**Fichiers**
- Modifier : `bot/core/overlay_layout.py` (`ELEMENTS` **et** `_ORDRE_DEFAUT`),
  `bot/core/overlay_elements.py` (`LIBELLES`),
  `bot/dashboard/routes/overlay.py` (`_ECHANTILLONS`),
  `tests/test_overlay_wally_visible.py` (le compte)
- Test : `tests/test_overlay_elements.py:12` garde déjà la parité
  (`set(ELEMENTS) - set(LIBELLES)`). Il échouera dès la clé ajoutée sans son
  libellé — c'est le filet, il n'y a rien à écrire.

- [ ] **Étape 1** — ajouter la clé SEULE et lancer
  `python3 -m pytest tests/test_overlay_elements.py -q` : il doit ÉCHOUER.
  Un filet qu'on n'a pas vu se déclencher n'est pas un filet.
- [ ] **Étape 2** — ajouter `"carte": _el(50.0, 50.0, "center")` dans la
  section « Ceux qui passent ». `solo` vaut `True` par défaut : la carte chasse
  Wally, c'est l'arbitrage.
- [ ] **Étape 3** — le libellé :

```python
    "carte": {
        "nom": "Carte du Purgatoire",
        "description": "La carte d'une personne de la communauté, telle qu'elle "
                       "existe sur le site : elle arrive à plat, se déplie en "
                       "3D, tourne doucement, puis s'en va. Les chiffres qu'elle "
                       "porte sont provisoires.",
    },
```

- [ ] **Étape 4** — vérifier que les **dix réglages par scène** sont bien
  distribués sur `carte` (la portée est calculée, elle ne se déclare pas) :

```bash
python3 -c "
from bot.core.overlay_layout import ELEMENTS, widgets_qui_passent
assert 'carte' in widgets_qui_passent()
print(sorted(ELEMENTS['carte']))"
```
Attendu : `duree`, `delai`, `anim_entree`, `anim_sortie`, `anim_insistance`,
`anim_duree`, `opacite`, `rotation`, `miroir`, `largeur_max` présents.

- [ ] **Étape 5** — suite, cliquets, commit.

---

### Tâche 6 : le rendu et la chorégraphie

**Fichiers**
- Créer : `bot/dashboard/static/overlay_tcg.js`
- Modifier : `bot/dashboard/static/overlay.js` (`BUILDERS`),
  `bot/dashboard/static/overlay.html` (feuille + police au boot)
- Créer : `public-ui/vendor/archivo-black.woff2` + la règle `@font-face`

**Interfaces**
- Consomme : `carteHero(carte, { interactif: false })` (tâche 3) et son
  `{ ouvrir, fermer, incliner, detruire }`.
- Produit : `export function carteOverlay(params)` → un nœud DOM, et démarre
  sa propre chorégraphie. `params` porte la carte **entière**, telle qu'envoyée
  par le bus.

- [ ] **Étape 1 — vendorer la police**

Télécharger le woff2 d'Archivo Black, le poser dans `public-ui/vendor/`,
compléter `vendor/PROVENANCE.md` (source, licence OFL, date), et déclarer le
`@font-face` dans `partage/tcg-carte.css`. Retirer le `<link>` Google Fonts
de `monterStylesCarte()`.

⚠️ Le site public en profite aussi : une requête externe de moins sur `/tcg`.

- [ ] **Étape 2 — la chorégraphie**

```js
// Les quatre fenêtres, en fractions de la durée totale. Écrites en SECONDES
// et non en pourcentages : l'entrée et la sortie doivent durer le même temps
// que la carte soit affichée 5 s ou 20 s — seule la rotation s'étire.
const ENTREE_S = 0.6;
const OUVERTURE_S = 0.8;
const SORTIE_S = 0.8;

// La moitié de la course d'un curseur. À pleine amplitude la carte bascule
// comme sous une souris qui balaie : ça se lit comme un bug d'animation, pas
// comme une présentation.
const AMPLITUDE = 0.25;
```

La rotation est une Lissajous 2:1 :
`nx = AMPLITUDE * Math.sin(t)`, `ny = AMPLITUDE * Math.sin(2 * t) * 0.6`,
avec `t` avançant d'environ un tour complet sur la phase.

⚠️ **Passer par la boucle du composant** (celle des particules, 30 images/s,
en pause hors écran) plutôt que d'ouvrir un `requestAnimationFrame` de plus.

- [ ] **Étape 3 — le décodage avant la première image**

```js
// Une carte qui apparaît pendant son propre décodage joue ses phases sur une
// image absente. On attend — mais AVEC un plafond : un `decode()` qui
// n'aboutit jamais (image manquante, réseau coupé) transformerait une
// précaution en panne silencieuse.
const PLAFOND_DECODE_MS = 2000;
await Promise.race([
  Promise.all([...noeud.querySelectorAll('img')].map((i) => i.decode().catch(() => {}))),
  new Promise((r) => setTimeout(r, PLAFOND_DECODE_MS)),
]);
```

⚠️ Journaliser quand le plafond est atteint : `console.warn` est le seul
journal de l'overlay, et une carte qui arrive nue doit laisser une trace.

- [ ] **Étape 4 — l'échelle**

```js
// 340 px CSS × 2 = 680 px sur un canvas de 1920, rendu en DPR 1 : exactement
// la résolution pour laquelle les illustrations sont générées (340 CSS ×
// DPR 2, cf. `scripts/generer_illustrations_tcg.py`). Passer à 3 les rendrait
// toutes floues, sans que rien ne le signale.
boite.style.setProperty('--chero-k', '2');
```

- [ ] **Étape 5 — la durée vient du RÉGLAGE, pas du code**

⚠️ `duree = 0` vaut « auto : le serveur décide », et c'est la valeur livrée sur
les trois scènes. Écrire le repli de `showWidget` (12 s) en dur ferait partir
une carte réglée à 20 s au bout de douze secondes, dès le rebuild. La
chorégraphie lit la durée que `showWidget` lui passe et n'en invente aucune ;
seules `ENTREE_S`, `OUVERTURE_S` et `SORTIE_S` sont fixes, la rotation prend ce
qui reste.

⚠️ Si ce qui reste est négatif (durée réglée sous 2,2 s), la rotation est
sautée et les trois autres phases sont comprimées proportionnellement — pas
d'animation à rebours.

- [ ] **Étape 6 — un seul écrivain sur le `transform` du plateau**

La rotation s'écrit dans le `transform` de `.chero-carte`, là où le survol
l'écrit déjà. Deux `transform` sur un même nœud ne se cumulent pas, ils se
REMPLACENT : la chorégraphie doit passer par `incliner()` et jamais toucher au
style directement. C'est précisément pour ça que `incliner()` est exposé.

- [ ] **Étape 7 — brancher dans `BUILDERS`** et charger feuille + police au
  boot dans `overlay.html`.

- [ ] **Étape 8 — vérifier en RÉEL** sur `overlay.html` : publier un événement
  de test sur le bus, capturer les quatre phases, contrôler qu'aucune erreur JS
  ne sort. `smoke_front.py --overlay`.

- [ ] **Étape 9** — cliquets, commit, push, rebuild.

---

# Phase 3 — le déclenchement

**Critère de sortie** : Wally affiche une carte demandée, en vrai, et sa trace
le dit.

⚠️ **Piège de cette phase** : `widgets_disponibles` retire de l'enum tout
widget qu'AUCUNE scène n'affiche. Tant que `carte` n'est pas posée sur une
scène depuis le panneau, Wally ne voit pas la valeur — sans qu'aucune erreur ne
le dise. **Poser la scène AVANT de chercher un défaut dans l'outil.**

---

### Tâche 7 : l'enum et le paramètre

**Fichiers**
- Modifier : `bot/intelligence/overlay_narrator.py` (`OVERLAY_TOOL_SPEC`)
- Test : `tests/test_overlay_tool_spec.py` (ou le fichier existant)

- [ ] **Étape 1** — ajouter `"carte"` à l'enum `widget` et un paramètre :

```python
"personne": {
    "type": "string",
    "description": (
        "Pour `widget=carte` UNIQUEMENT : le pseudo de la personne dont tu "
        "montres la carte (« claker », « rhae », « azrael », « lilith »). "
        "Un nom que tu ne connais pas te sera refusé avec la liste de ce qui "
        "existe — n'invente pas de carte."
    ),
},
```

- [ ] **Étape 2** — le test : `carte` présent dans l'enum, `personne` décrit,
  et **la spec reste sérialisable en JSON** (les fournisseurs la refusent
  sinon).
- [ ] **Étape 3** — vérifier que le filtrage par scène marche : `carte` absent
  de toute scène ⇒ absent de l'enum.

---

### Tâche 8 : le routage, la trace, le refus

**Fichiers**
- Modifier : `bot/discord/handlers.py`, `bot/twitch/handlers.py`,
  `bot/intelligence/action_dispatcher.py`

- [ ] **Étape 1 — résoudre, refuser proprement**

```python
carte = tcg_cartes.resoudre(args.get("personne", ""))
if carte is None:
    return (f"Aucune carte à ce nom. Celles qui existent : "
            f"{', '.join(tcg_cartes.noms_disponibles())}.")
```

⚠️ Un refus qui NOMME ce qui existe : sans la liste, Wally réessaie au hasard.

- [ ] **Étape 2 — publier**, en passant la carte entière en paramètres.

- [ ] **Étape 3 — la trace**

`overlay_feed.widget()` consigne déjà « tu as affiché le widget « carte » »
— volontairement sans ses paramètres, qui portent ailleurs du texte libre. Un
pseudo n'en est pas : l'appelant ajoute sa ligne.

```python
note_act(f"tu as montré la carte de {carte.nom} aux viewers")
```

Sans elle, Wally fait le geste et ne sait pas qu'il l'a fait —
`self_trace.py` est le point d'entrée unique de « ce que Wally vient de faire ».

- [ ] **Étape 4 — parité Discord / Twitch.** Une capacité branchée d'un seul
  côté est un défaut que les tests de parité du projet attrapent : vérifier
  qu'ils couvrent bien la nouvelle valeur.

- [ ] **Étape 5 — vérifier en RÉEL** : poser `carte` sur une scène, demander à
  Wally d'afficher une carte, contrôler l'overlay ET la trace en base.

- [ ] **Étape 6** — suite complète, six cliquets, smoke, commit, push, rebuild.

---

## Ce que ce plan ne fait pas

- **Le fond animé** (WebM au survol) : se branchera sur cette base, après.
- **Toute autre voie de déclenchement** que Wally : ni commande chat, ni points
  de chaîne.
- **Les vraies valeurs des cartes** : elles viennent de Notion, carte par carte.
