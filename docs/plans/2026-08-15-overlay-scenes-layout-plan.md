# Overlay : scènes et placement libre — plan d'implémentation

> **Pour les agents :** SOUS-COMPÉTENCE REQUISE — utiliser
> `superpowers:subagent-driven-development` (recommandé) ou
> `superpowers:executing-plans` pour dérouler ce plan tâche par tâche. Les
> étapes portent des cases à cocher (`- [ ]`) pour le suivi.

**But :** donner à chaque élément de l'overlay une position, une taille et une
visibilité propres, réglables au glisser depuis le panneau admin, différentes
par scène de stream, et appliquées en direct sans rechargement.

**Architecture :** un modèle JSON unique rangé dans `bot_state`, servi par une
route publique que chaque page lit au démarrage, et republié sur le bus
`overlay_feed` existant à chaque modification. La page applique les positions en
absolu depuis un ancrage, et les tailles par `transform: scale()` sur un canvas
de référence de 1920 × 1080.

**Pile :** Python 3.11 / FastAPI / aiosqlite côté serveur ; JavaScript sans
framework côté page et côté panneau ; pytest pour les tests.

**Spec :** `docs/plans/2026-08-15-overlay-scenes-layout-design.md` — à lire
avant de commencer. Le plan argumente depuis elle.

## Contraintes globales

- **Langue.** Identifiants de code et clés de données en anglais ; noms de
  fonctions, commentaires et messages en français. Les clés de widgets sont
  **exactement** les `kind` déjà employés par `BUILDERS` (`overlay.js:958`).
- **Journalisation.** `from loguru import logger` uniquement. Jamais `print()`,
  jamais `import logging`.
- **Asynchrone.** Toute E/S est `async`. Rien de bloquant dans la boucle.
- **Canvas de référence : 1920 × 1080.** Toute taille s'y rapporte.
- **Slugs réservés :** `image`, `rotation`, `version`, `health`.
- **Plage de `scale` :** 0.2 à 2.0. **Plage de `x`/`y` :** 0.0 à 100.0.
- **Les neuf ancrages :** `top-left`, `top-center`, `top-right`, `middle-left`,
  `center`, `middle-right`, `bottom-left`, `bottom-center`, `bottom-right`.
- **Vérification avant de clore une tâche :** `python -m pytest <fichier> -v`
  puis `python -m pytest tests/ -q -x` pour la non-régression.
- **Un test doit échouer sur le code actuel** avant d'être considéré comme
  valable. C'est la méthode des audits précédents de ce projet.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `bot/core/overlay_layout.py` *(nouveau)* | Le modèle : défauts, fusion, validation, accès par slug. Aucun réseau, aucune base — pur, donc testable seul. |
| `bot/core/overlay_layout_store.py` *(nouveau)* | Charger et enregistrer le modèle dans `bot_state`. Séparé du modèle pour que celui-ci reste sans E/S. |
| `bot/dashboard/routes/overlay.py` *(modifié)* | Les routes GET/PUT du layout et la route de prévisualisation. |
| `bot/dashboard/app.py` *(modifié)* | La route `/overlay-<slug>`. |
| `bot/dashboard/static/overlay.html` *(modifié)* | Le CSS de positionnement absolu et le conteneur par élément. |
| `bot/dashboard/static/overlay_layout.js` *(nouveau)* | L'application du layout dans la page : ancrages, échelle, canvas. Sorti d'`overlay.js`, qui fait déjà 1320 lignes. |
| `bot/dashboard/static/overlay.js` *(modifié)* | `case "layout"`, et fin de l'effacement de l'avatar pour les widgets non `solo`. |
| `bot/dashboard/static/overlay_admin.js` *(nouveau)* | Tout le panneau de mise en scène. Sorti d'`app.js`, qui fait déjà 5679 lignes. |
| `bot/dashboard/static/app.js` *(modifié)* | Trois lignes d'accroche dans `_renderSystemeOverlay()`. |
| `bot/intelligence/overlay_narrator.py` *(modifié)* | L'enum filtré et le refus explicite. |

---

## Phase 1 — Le modèle et les routes

Rien de visible. À la fin de la phase, le layout existe, se valide, se range et
se sert ; l'overlay ne le lit pas encore.

### Tâche 1 : le modèle

**Fichiers :**
- Créer : `bot/core/overlay_layout.py`
- Test : `tests/test_overlay_layout.py`

**Interfaces :**
- Consomme : rien.
- Produit :
  - `ANCRAGES: frozenset[str]` — les neuf ancrages
  - `SLUGS_RESERVES: frozenset[str]`
  - `ELEMENTS: dict[str, dict]` — clé → réglages par défaut
  - `layout_par_defaut() -> dict`
  - `fusionner(brut: dict | None) -> dict`
  - `slug_depuis_nom(nom: str) -> str`
  - `scene_par_slug(layout: dict, slug: str) -> dict | None`

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# tests/test_overlay_layout.py
"""Le modèle de mise en scène de l'overlay.

Un layout illisible ne doit JAMAIS donner un overlay vide : ce réglage se
manipule en plein live, et le pire scénario acceptable est « mal placé ».
Tous les tests de fusion tournent autour de ça.
"""
import pytest

from bot.core.overlay_layout import (
    ANCRAGES, ELEMENTS, SLUGS_RESERVES,
    fusionner, layout_par_defaut, scene_par_slug, slug_depuis_nom,
)


def test_defaut_porte_les_trois_scenes():
    layout = layout_par_defaut()
    assert [s["slug"] for s in layout["scenes"]] == ["start", "jeu", "end"]
    assert layout["defaut"] == "jeu"


def test_defaut_place_chaque_element_de_chaque_scene():
    layout = layout_par_defaut()
    for scene in layout["scenes"]:
        assert set(scene["elements"]) == set(ELEMENTS)
        for cle, el in scene["elements"].items():
            assert el["anchor"] in ANCRAGES
            assert 0.0 <= el["x"] <= 100.0
            assert 0.0 <= el["y"] <= 100.0


def test_fusion_dun_layout_absent_rend_les_defauts():
    assert fusionner(None) == layout_par_defaut()


def test_fusion_dun_json_corrompu_rend_les_defauts():
    # Ni dict, ni scenes : provenance inconnue, on ne devine pas.
    assert fusionner({"n'importe": "quoi"}) == layout_par_defaut()
    assert fusionner([]) == layout_par_defaut()


def test_un_element_absent_reprend_son_defaut():
    """Ajouter un dix-huitième widget dans six mois ne doit pas faire exploser
    la disposition existante."""
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [],
         "elements": {"avatar": {"x": 10.0, "y": 20.0, "anchor": "top-left",
                                 "scale": 1.0, "hidden": False,
                                 "locked": False, "solo": False}}},
    ]}
    scene = fusionner(brut)["scenes"][0]
    assert scene["elements"]["avatar"]["x"] == 10.0        # le réglé est gardé
    assert scene["elements"]["bingo"] == ELEMENTS["bingo"] # l'absent revient


def test_un_element_inconnu_est_ignore():
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [],
         "elements": {"licorne": {"x": 5.0, "y": 5.0}}},
    ]}
    assert "licorne" not in fusionner(brut)["scenes"][0]["elements"]


def test_les_valeurs_hors_bornes_sont_ramenees():
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [],
         "elements": {"avatar": {"x": 999.0, "y": -50.0, "scale": 12.0,
                                 "anchor": "nulle-part", "hidden": "oui",
                                 "locked": False, "solo": False}}},
    ]}
    avatar = fusionner(brut)["scenes"][0]["elements"]["avatar"]
    assert avatar["x"] == 100.0
    assert avatar["y"] == 0.0
    assert avatar["scale"] == 2.0
    assert avatar["anchor"] == ELEMENTS["avatar"]["anchor"]   # ancrage inconnu
    assert avatar["hidden"] is True                           # coercition franche


def test_ordre_complete_les_elements_manquants():
    """`ordre` pilote l'empilement : un élément absent de la liste serait
    invisible au rendu, pas seulement mal empilé."""
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": ["avatar"], "elements": {}},
    ]}
    ordre = fusionner(brut)["scenes"][0]["ordre"]
    assert ordre[0] == "avatar"
    assert set(ordre) == set(ELEMENTS)


def test_une_scene_sans_slug_est_jetee_pas_tout_le_layout():
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"nom": "sans slug", "elements": {}},
        {"slug": "jeu", "nom": "En jeu", "ordre": [], "elements": {}},
    ]}
    assert [s["slug"] for s in fusionner(brut)["scenes"]] == ["jeu"]


def test_un_layout_sans_aucune_scene_valable_rend_les_defauts():
    brut = {"version": 1, "defaut": "jeu", "scenes": [{"nom": "sans slug"}]}
    assert fusionner(brut) == layout_par_defaut()


def test_defaut_pointant_une_scene_absente_retombe_sur_la_premiere():
    brut = {"version": 1, "defaut": "fantome", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [], "elements": {}},
    ]}
    assert fusionner(brut)["defaut"] == "jeu"


@pytest.mark.parametrize("nom,attendu", [
    ("Stream Starting", "stream-starting"),
    ("Fin de stream", "fin-de-stream"),
    ("  Écran   d'attente  ", "ecran-d-attente"),
    ("!!!", "scene"),
    ("image", "image-2"),          # slug réservé : suffixé, pas refusé
])
def test_slug_depuis_nom(nom, attendu):
    assert slug_depuis_nom(nom) == attendu


def test_slug_depuis_nom_evite_les_reserves():
    for reserve in SLUGS_RESERVES:
        assert slug_depuis_nom(reserve) not in SLUGS_RESERVES


def test_scene_par_slug():
    layout = layout_par_defaut()
    assert scene_par_slug(layout, "start")["nom"] == "Stream Starting"
    assert scene_par_slug(layout, "inexistante") is None
```

- [ ] **Étape 2 : lancer les tests, vérifier qu'ils échouent**

Commande : `python -m pytest tests/test_overlay_layout.py -v`
Attendu : `ModuleNotFoundError: No module named 'bot.core.overlay_layout'`

- [ ] **Étape 3 : écrire le modèle**

```python
# bot/core/overlay_layout.py
"""La mise en scène de l'overlay : où va chaque élément, dans chaque scène.

Volontairement SANS réseau et SANS base : ce fichier ne fait que décrire, valider
et fusionner. Le rangement vit dans `overlay_layout_store.py`, ce qui laisse
celui-ci testable sur des dictionnaires nus.

Le principe qui gouverne tout : **fusionner, jamais remplacer**. Un élément
absent reprend son défaut, un élément inconnu est ignoré, une valeur aberrante
est ramenée dans ses bornes. Sans cela, ajouter un widget dans six mois ferait
exploser la disposition réglée, et un JSON tronqué laisserait un overlay vide —
alors que ce réglage se manipule en plein live.
"""
from __future__ import annotations

import re
import unicodedata

# Les neuf points d'ancrage. La position désigne CE point de l'élément, et le
# contenu grandit vers l'intérieur du cadre. Sans ancrage, un élément posé à
# droite sortirait de l'écran dès que son contenu s'élargit, et une bulle de dix
# lignes pousserait vers la droite au lieu de monter.
ANCRAGES = frozenset({
    "top-left", "top-center", "top-right",
    "middle-left", "center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
})

# `/overlay-image` et `/overlay-rotation` existent déjà (app.py) ; `version` et
# `health` sont des routes d'API. Une scène qui prendrait un de ces slugs les
# masquerait.
SLUGS_RESERVES = frozenset({"image", "rotation", "version", "health"})

SCALE_MIN, SCALE_MAX = 0.2, 2.0


def _el(x: float, y: float, anchor: str, scale: float = 1.0,
        *, solo: bool = True, hidden: bool = False) -> dict:
    return {"x": x, "y": y, "anchor": anchor, "scale": scale,
            "hidden": hidden, "locked": False, "solo": solo}


# Les clés SONT les `kind` employés par `BUILDERS` (overlay.js) — les franciser
# casserait la correspondance et imposerait une table de traduction pour rien.
#
# `solo=True` : l'élément chasse les autres et passe par la file d'attente.
# `solo=False` : il s'installe et laisse la place aux autres par-dessus.
#
# L'échelle de l'avatar vaut 0.55 : elle reproduit, sur un canvas de 1920, la
# taille qu'il avait dans son ancienne source de 560 px de large.
ELEMENTS: dict[str, dict] = {
    # Wally et sa bulle
    "avatar": _el(97.0, 80.0, "bottom-right", 0.55, solo=False),
    "bubble": _el(95.0, 62.0, "bottom-right", 0.9, solo=False),
    # Les deux ex-sources OBS
    "rotator": _el(50.0, 45.0, "center", 1.0, solo=False),
    "image":   _el(50.0, 50.0, "center", 1.0),
    # Ceux qui s'installent
    "bingo":   _el(3.0, 18.0, "top-left", 0.9, solo=False),
    "stats":   _el(3.0, 60.0, "top-left", 0.9, solo=False),
    "goal":    _el(50.0, 4.0, "top-center", 0.9, solo=False),
    "uptime":  _el(97.0, 4.0, "top-right", 0.8, solo=False),
    "talkers": _el(3.0, 40.0, "top-left", 0.9, solo=False),
    # Ceux qui passent
    "meme":      _el(50.0, 50.0, "center"),
    "versus":    _el(50.0, 50.0, "center"),
    "poll":      _el(50.0, 50.0, "center"),
    "hangman":   _el(50.0, 50.0, "center"),
    "pinned":    _el(50.0, 50.0, "center"),
    "counter":   _el(50.0, 50.0, "center"),
    "coinflip":  _el(50.0, 50.0, "center"),
    "dice":      _el(50.0, 50.0, "center"),
    "wheel":     _el(50.0, 50.0, "center"),
    "gauge":     _el(50.0, 50.0, "center"),
    "countdown": _el(50.0, 50.0, "center"),
    "rps":       _el(50.0, 50.0, "center"),
}

# L'empilement par défaut, du plus proche au plus lointain. Wally passe devant
# ce qu'il montre ; les widgets installés restent au fond.
_ORDRE_DEFAUT = [
    "bubble", "avatar", "image", "meme", "versus", "poll", "hangman",
    "pinned", "counter", "coinflip", "dice", "wheel", "gauge", "countdown",
    "rps", "rotator", "goal", "uptime", "talkers", "bingo", "stats",
]

_SCENES_DEFAUT = (("start", "Stream Starting"), ("jeu", "En jeu"), ("end", "Fin"))


def layout_par_defaut() -> dict:
    """Trois scènes, tous les éléments placés, rien de masqué.

    Chaque scène a sa PROPRE copie des éléments : elles divergent dès le premier
    réglage, et un dictionnaire partagé les ferait bouger ensemble.
    """
    return {
        "version": 1,
        "defaut": "jeu",
        "scenes": [
            {"slug": slug, "nom": nom, "ordre": list(_ORDRE_DEFAUT),
             "elements": {k: dict(v) for k, v in ELEMENTS.items()}}
            for slug, nom in _SCENES_DEFAUT
        ],
    }


def _borner(valeur, mini: float, maxi: float, defaut: float) -> float:
    """Ramène dans les bornes. Ce qui n'est pas un nombre reprend le défaut —
    `bool` est exclu explicitement : `True` est un `int` en Python et passerait
    pour la valeur 1.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return defaut
    valeur = float(valeur)
    if valeur != valeur:            # NaN : json.loads l'accepte
        return defaut
    return max(mini, min(maxi, valeur))


def _fusionner_element(brut, defaut: dict) -> dict:
    if not isinstance(brut, dict):
        return dict(defaut)
    anchor = brut.get("anchor")
    return {
        "x": _borner(brut.get("x"), 0.0, 100.0, defaut["x"]),
        "y": _borner(brut.get("y"), 0.0, 100.0, defaut["y"]),
        "anchor": anchor if anchor in ANCRAGES else defaut["anchor"],
        "scale": _borner(brut.get("scale"), SCALE_MIN, SCALE_MAX, defaut["scale"]),
        # `bool()` franc : l'admin envoie des booléens, mais un JSON écrit à la
        # main peut porter "oui" ou 1, et un `.get(clé, défaut)` ne couvre pas
        # une clé présente à `null` — piège déjà payé sur ce projet.
        "hidden": bool(brut.get("hidden", defaut["hidden"])),
        "locked": bool(brut.get("locked", defaut["locked"])),
        "solo": bool(brut.get("solo", defaut["solo"])),
    }


def _fusionner_scene(brut: dict) -> dict | None:
    """Une scène valable, ou `None` si elle n'a pas de slug exploitable.

    Une scène jetée ne fait pas tomber les autres : on perd une scène, pas la
    disposition entière.
    """
    slug = brut.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        return None
    slug = slug.strip()
    elements_bruts = brut.get("elements")
    if not isinstance(elements_bruts, dict):
        elements_bruts = {}
    elements = {
        cle: _fusionner_element(elements_bruts.get(cle), defaut)
        for cle, defaut in ELEMENTS.items()
    }
    ordre_brut = brut.get("ordre")
    ordre = [c for c in ordre_brut if c in ELEMENTS] if isinstance(ordre_brut, list) else []
    # Un élément absent de `ordre` ne serait pas seulement mal empilé : il ne
    # serait pas rendu du tout. On complète toujours.
    ordre += [c for c in _ORDRE_DEFAUT if c not in ordre]
    nom = brut.get("nom")
    return {
        "slug": slug,
        "nom": nom.strip() if isinstance(nom, str) and nom.strip() else slug,
        "ordre": ordre,
        "elements": elements,
    }


def fusionner(brut) -> dict:
    """Le layout rangé, complété par les défauts. Jamais d'exception.

    Appelé sur ce que rend la base — donc sur du texte qu'un humain a pu éditer,
    qu'une version antérieure a pu écrire, ou qu'une écriture interrompue a pu
    tronquer. Il en sort toujours quelque chose d'affichable.
    """
    if not isinstance(brut, dict):
        return layout_par_defaut()
    scenes_brutes = brut.get("scenes")
    if not isinstance(scenes_brutes, list):
        return layout_par_defaut()
    scenes, vus = [], set()
    for scene_brute in scenes_brutes:
        if not isinstance(scene_brute, dict):
            continue
        scene = _fusionner_scene(scene_brute)
        if scene is None or scene["slug"] in vus:
            continue
        vus.add(scene["slug"])
        scenes.append(scene)
    if not scenes:
        return layout_par_defaut()
    defaut = brut.get("defaut")
    if defaut not in vus:
        defaut = scenes[0]["slug"]
    return {"version": 1, "defaut": defaut, "scenes": scenes}


def slug_depuis_nom(nom: str) -> str:
    """Un slug d'URL depuis un nom lisible.

    N'est appelé qu'à la CRÉATION d'une scène : un renommage ne doit pas changer
    l'URL, sinon la source OBS pointe dans le vide et on l'apprend en direct,
    écran noir.
    """
    sans_accent = unicodedata.normalize("NFKD", str(nom or ""))
    sans_accent = sans_accent.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", sans_accent.lower()).strip("-")
    if not slug:
        slug = "scene"
    # Réservé : suffixé plutôt que refusé — l'utilisateur a le droit d'appeler
    # une scène « image », il n'a simplement pas le droit d'en prendre l'URL.
    if slug in SLUGS_RESERVES:
        slug = f"{slug}-2"
    return slug


def scene_par_slug(layout: dict, slug: str) -> dict | None:
    for scene in layout.get("scenes", []):
        if scene.get("slug") == slug:
            return scene
    return None
```

- [ ] **Étape 4 : lancer les tests, vérifier qu'ils passent**

Commande : `python -m pytest tests/test_overlay_layout.py -v`
Attendu : 13 tests PASS.

- [ ] **Étape 5 : commiter**

```bash
git add bot/core/overlay_layout.py tests/test_overlay_layout.py
git commit -m "feat(overlay): le modèle de mise en scène, fusionné jamais remplacé

Un élément absent reprend son défaut, un inconnu est ignoré, une valeur
aberrante est ramenée dans ses bornes, une scène sans slug est jetée sans
emporter les autres. Ce réglage se manipule en plein live : le pire scénario
acceptable est « mal placé », jamais « rien à l'écran »."
```

---

### Tâche 2 : le rangement et les routes

**Fichiers :**
- Créer : `bot/core/overlay_layout_store.py`
- Modifier : `bot/dashboard/routes/overlay.py` (ajouts en fin de fichier)
- Test : `tests/test_overlay_layout_store.py`

**Interfaces :**
- Consomme : `fusionner`, `layout_par_defaut`, `scene_par_slug` (tâche 1).
- Produit :
  - `LAYOUT_KEY = "overlay:layout"`
  - `async charger_layout(db) -> dict`
  - `async enregistrer_layout(db, brut) -> dict`
  - Routes `GET /api/public/overlay-layout`, `GET|PUT /api/admin/overlay/layout`

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# tests/test_overlay_layout_store.py
"""Le rangement du layout dans `bot_state`.

Patron du `_State` simulé repris de `tests/test_overlay_etat_partie_persist.py`.
"""
import json

import pytest

from bot.core.overlay_layout import ELEMENTS, layout_par_defaut
from bot.core.overlay_layout_store import (
    LAYOUT_KEY, charger_layout, enregistrer_layout,
)


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


@pytest.mark.asyncio
async def test_charger_sans_rien_en_base_rend_les_defauts():
    assert await charger_layout(_State()) == layout_par_defaut()


@pytest.mark.asyncio
async def test_charger_un_json_illisible_rend_les_defauts():
    """Une écriture interrompue laisse du JSON tronqué. L'overlay doit quand
    même s'afficher."""
    db = _State({LAYOUT_KEY: '{"scenes": [{"slug": "jeu"'})
    assert await charger_layout(db) == layout_par_defaut()


@pytest.mark.asyncio
async def test_charger_sans_base_rend_les_defauts():
    """`db=None` arrive avant la connexion du bot : la page ne doit pas
    attendre pour s'afficher."""
    assert await charger_layout(None) == layout_par_defaut()


@pytest.mark.asyncio
async def test_enregistrer_puis_recharger_conserve_les_positions():
    db = _State()
    layout = layout_par_defaut()
    layout["scenes"][0]["elements"]["avatar"]["x"] = 12.5
    await enregistrer_layout(db, layout)
    relu = await charger_layout(db)
    assert relu["scenes"][0]["elements"]["avatar"]["x"] == 12.5


@pytest.mark.asyncio
async def test_enregistrer_valide_avant_de_ranger():
    """Ce qui entre est fusionné : une valeur hors bornes n'atteint pas la
    base, sinon elle y resterait jusqu'au prochain enregistrement."""
    db = _State()
    layout = layout_par_defaut()
    layout["scenes"][0]["elements"]["avatar"]["x"] = 5000.0
    rendu = await enregistrer_layout(db, layout)
    assert rendu["scenes"][0]["elements"]["avatar"]["x"] == 100.0
    assert json.loads(db.rows[LAYOUT_KEY])["scenes"][0]["elements"]["avatar"]["x"] == 100.0


@pytest.mark.asyncio
async def test_enregistrer_sans_base_ne_leve_pas():
    """Le panneau doit répondre même si la base est absente — il rend alors ce
    qu'il a compris, sans prétendre l'avoir rangé."""
    assert await enregistrer_layout(None, layout_par_defaut()) == layout_par_defaut()


@pytest.mark.asyncio
async def test_toutes_les_cles_delements_survivent_a_un_aller_retour():
    db = _State()
    await enregistrer_layout(db, layout_par_defaut())
    relu = await charger_layout(db)
    for scene in relu["scenes"]:
        assert set(scene["elements"]) == set(ELEMENTS)
```

- [ ] **Étape 2 : lancer les tests, vérifier qu'ils échouent**

Commande : `python -m pytest tests/test_overlay_layout_store.py -v`
Attendu : `ModuleNotFoundError: No module named 'bot.core.overlay_layout_store'`

- [ ] **Étape 3 : écrire le rangement**

```python
# bot/core/overlay_layout_store.py
"""Le layout de l'overlay, rangé dans `bot_state`.

Une seule clé, un seul JSON — même patron que `apex:live_baseline` et le salon
vocal retenu. Séparé de `overlay_layout.py` pour que le modèle reste sans E/S,
donc testable sur des dictionnaires nus.
"""
from __future__ import annotations

import json

from loguru import logger

from bot.core.overlay_layout import fusionner, layout_par_defaut

LAYOUT_KEY = "overlay:layout"


async def charger_layout(db) -> dict:
    """Le layout rangé, complété par les défauts. Ne lève jamais.

    `db` peut être `None` : la page est servie avant que le bot soit connecté,
    et elle ne doit pas attendre pour s'afficher.
    """
    if db is None:
        return layout_par_defaut()
    try:
        brut = await db.get_state(LAYOUT_KEY)
    except Exception as exc:  # noqa: BLE001 — une base muette n'efface pas l'overlay
        logger.warning("Overlay layout : lecture impossible ({e})", e=exc)
        return layout_par_defaut()
    if not brut:
        return layout_par_defaut()
    try:
        return fusionner(json.loads(brut))
    except (ValueError, TypeError) as exc:
        # Une écriture interrompue laisse du JSON tronqué. On le dit — un
        # layout perdu en silence se découvrirait des semaines plus tard.
        logger.warning("Overlay layout : JSON illisible, défauts repris ({e})", e=exc)
        return layout_par_defaut()


async def enregistrer_layout(db, brut) -> dict:
    """Valide, range, et rend ce qui a été rangé.

    La validation passe AVANT l'écriture : une valeur hors bornes rangée telle
    quelle y resterait jusqu'au prochain enregistrement, et serait servie entre
    les deux.
    """
    layout = fusionner(brut)
    if db is None:
        return layout
    try:
        await db.set_state(LAYOUT_KEY, json.dumps(layout, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Overlay layout : écriture impossible ({e})", e=exc)
    return layout
```

- [ ] **Étape 4 : lancer les tests, vérifier qu'ils passent**

Commande : `python -m pytest tests/test_overlay_layout_store.py -v`
Attendu : 7 tests PASS.

- [ ] **Étape 5 : ajouter les routes**

Ajouter en fin de `bot/dashboard/routes/overlay.py` :

```python
# ── Mise en scène ────────────────────────────────────────────────────────────
from bot.core.overlay_layout import scene_par_slug          # noqa: E402
from bot.core.overlay_layout_store import (                 # noqa: E402
    charger_layout, enregistrer_layout,
)


def _db(request: Request):
    """La base, ou None avant la connexion du bot. `charger_layout` l'accepte."""
    return getattr(request.app.state.wally, "db", None)


@public_router.get("/overlay-layout")
async def get_overlay_layout(request: Request, scene: str = "") -> dict:
    """Le layout d'une scène — ce que la page lit au démarrage.

    Source de vérité, plutôt qu'un événement SSE qui pourrait ne jamais venir :
    une page ouverte alors que le bus est muet doit quand même se placer.
    """
    layout = await charger_layout(_db(request))
    slug = scene or layout["defaut"]
    trouvee = scene_par_slug(layout, slug)
    if trouvee is None:
        # Scène supprimée alors qu'OBS pointe encore dessus : on sert le défaut
        # plutôt qu'un 404 qui laisserait l'écran vide en plein live.
        trouvee = scene_par_slug(layout, layout["defaut"]) or layout["scenes"][0]
    return {"scene": trouvee, "defaut": layout["defaut"]}


@admin_router.get("/overlay/layout")
async def get_overlay_layout_admin(request: Request) -> dict:
    """Tout le modèle — le panneau a besoin de toutes les scènes."""
    return await charger_layout(_db(request))


@admin_router.put("/overlay/layout")
async def put_overlay_layout(request: Request) -> dict:
    """Enregistre et publie. Le retour est ce qui a été RANGÉ, pas ce qui a été
    envoyé : le panneau voit donc immédiatement les valeurs bornées."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")
    layout = await enregistrer_layout(_db(request), data)
    feed = getattr(request.app.state.wally, "overlay_feed", None)
    if feed is not None:
        # Un SIGNAL, pas le layout. `OverlayFeed.recent()` rejoue les dix
        # derniers événements à chaque connexion (overlay_feed.py:105) : y
        # pousser le modèle entier chasserait des bulles utiles du tampon, et
        # une page qui se connecte démarrerait sur un écran vide. La page refait
        # son GET, qui reste la seule source de vérité.
        #
        # `scene: None` — toutes les pages ouvertes se replacent. Chacune ne
        # retient que la scène qui la concerne.
        feed.publish({"type": "layout", "scene": None})
    return layout
```

- [ ] **Étape 6 : vérifier la non-régression et commiter**

```bash
python -m pytest tests/ -q -x
git add bot/core/overlay_layout_store.py bot/dashboard/routes/overlay.py tests/test_overlay_layout_store.py
git commit -m "feat(overlay): le layout se range, se sert et se publie

Une clé dans bot_state, une route publique que la page lit au démarrage, une
route admin qui valide avant d'écrire et republie sur le bus existant. Une
scène supprimée sert le défaut plutôt qu'un 404 : OBS peut pointer dessus en
plein live."
```

---

## Phase 2 — L'overlay applique le layout

À la fin de la phase, `/overlay-jeu` place chaque élément selon le modèle et se
replace en direct sans rechargement.

### Tâche 3 : ancrages, échelle et canvas de référence

**Fichiers :**
- Créer : `bot/dashboard/static/overlay_layout.js`
- Modifier : `bot/dashboard/static/overlay.html` (bloc `<style>` et scripts)
- Test : `tests/test_overlay_layout_css.py`

**Interfaces :**
- Consomme : `GET /api/public/overlay-layout` (tâche 2).
- Produit, sur `window.WallyLayout` :
  - `appliquer(slug: string, scene: object)` — place tous les éléments d'**une
    scène** (l'objet scène, pas le layout entier)
  - `placer(noeud: Element, element: object)` — place un nœud selon un élément
  - `styleDepuisElement(element: object)` — rend
    `{left|right, top|bottom, transform, transformOrigin}` — pur, donc testable
  - `facteurCanvas(): number` — `innerWidth / 1920`
  - `ELEMENTS: string[]`, `ANCRAGES: object`

- [ ] **Étape 1 : écrire le test de correspondance des clés**

Le test Python garantit que le modèle et la page parlent des mêmes éléments —
une clé ajoutée d'un côté et pas de l'autre est invisible autrement.

```python
# tests/test_overlay_layout_css.py
"""Le modèle et la page doivent nommer les mêmes éléments.

Une clé ajoutée dans `ELEMENTS` sans conteneur dans la page ne serait jamais
rendue, et personne ne le verrait avant un live. Le contrôle est mécanique.
"""
from pathlib import Path

from bot.core.overlay_layout import ANCRAGES, ELEMENTS

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"


def test_chaque_element_a_son_ancrage_declare_dans_le_js():
    js = (_STATIC / "overlay_layout.js").read_text(encoding="utf-8")
    for ancrage in ANCRAGES:
        assert f'"{ancrage}"' in js, f"ancrage absent du JS : {ancrage}"


def test_chaque_element_du_modele_est_connu_de_la_page():
    js = (_STATIC / "overlay_layout.js").read_text(encoding="utf-8")
    for cle in ELEMENTS:
        assert f'"{cle}"' in js, f"élément absent du JS : {cle}"


def test_le_canvas_de_reference_est_bien_1920():
    js = (_STATIC / "overlay_layout.js").read_text(encoding="utf-8")
    assert "1920" in js
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Commande : `python -m pytest tests/test_overlay_layout_css.py -v`
Attendu : `FileNotFoundError` sur `overlay_layout.js`.

- [ ] **Étape 3 : écrire `overlay_layout.js`**

```javascript
// bot/dashboard/static/overlay_layout.js
//
// Le placement des éléments de l'overlay.
//
// Sorti d'overlay.js, qui fait déjà 1320 lignes et dont la responsabilité est
// le CONTENU (que montre-t-on, quand) — pas la mise en scène (où).
//
// Deux règles gouvernent tout :
//
//   1. Les positions sont en POURCENTAGE, jamais en pixels : la disposition
//      survit à un changement de résolution de la source OBS.
//   2. Les tailles passent par transform:scale() sur un canvas de référence de
//      1920×1080. Redimensionner par la largeur laisserait le texte à 16px dans
//      un widget réduit de moitié et casserait la mise en page des dix-sept —
//      il faudrait retoucher leur CSS un par un.
window.WallyLayout = (function () {
  "use strict";

  const CANVAS_W = 1920;

  // Chaque ancrage dit DEUX choses : de quel bord on mesure, et dans quel sens
  // le contenu grandit. Le `translate` déplace l'élément de sa propre taille,
  // ce que les pourcentages d'une transformation font nativement.
  const ANCRAGES = {
    "top-left":      { h: "left",  v: "top",    tx: "0",     ty: "0" },
    "top-center":    { h: "left",  v: "top",    tx: "-50%",  ty: "0" },
    "top-right":     { h: "right", v: "top",    tx: "0",     ty: "0" },
    "middle-left":   { h: "left",  v: "top",    tx: "0",     ty: "-50%" },
    "center":        { h: "left",  v: "top",    tx: "-50%",  ty: "-50%" },
    "middle-right":  { h: "right", v: "top",    tx: "0",     ty: "-50%" },
    "bottom-left":   { h: "left",  v: "bottom", tx: "0",     ty: "0" },
    "bottom-center": { h: "left",  v: "bottom", tx: "-50%",  ty: "0" },
    "bottom-right":  { h: "right", v: "bottom", tx: "0",     ty: "0" },
  };

  // Les clés du modèle (bot/core/overlay_layout.py). Un test Python vérifie que
  // les deux listes ne divergent pas.
  const ELEMENTS = [
    "avatar", "bubble", "rotator", "image",
    "bingo", "stats", "goal", "uptime", "talkers",
    "meme", "versus", "poll", "hangman", "pinned", "counter",
    "coinflip", "dice", "wheel", "gauge", "countdown", "rps",
  ];

  /** Le rapport entre la source réelle et le canvas de référence.
   *  Sans lui, un scale de 1 ne rendrait pas la même taille relative sur une
   *  source en 1920 et sur une en 2560 : la disposition se déferait. */
  function facteurCanvas() {
    return (window.innerWidth || CANVAS_W) / CANVAS_W;
  }

  /** Le style de placement d'un élément. Pur : c'est ce qu'on teste. */
  function styleDepuisElement(el) {
    const a = ANCRAGES[el.anchor] || ANCRAGES["center"];
    // Un ancrage à droite ou en bas mesure depuis CE bord : la position est
    // donc le complément. Sans ça, un élément ancré à droite s'éloignerait du
    // bord quand on augmente son x, ce qui est l'inverse de l'attendu.
    const h = a.h === "right" ? 100 - el.x : el.x;
    const v = a.v === "bottom" ? 100 - el.y : el.y;
    const echelle = (el.scale || 1) * facteurCanvas();
    return {
      [a.h]: h + "%",
      [a.v]: v + "%",
      transform: `translate(${a.tx}, ${a.ty}) scale(${echelle})`,
      transformOrigin: `${a.h === "right" ? "right" : "left"} ${a.v === "bottom" ? "bottom" : "top"}`,
    };
  }

  /** Applique un élément du modèle à un nœud. */
  function placer(noeud, el) {
    if (!noeud || !el) return;
    // Les quatre bords sont remis à `auto` avant : changer d'ancrage laissait
    // sinon l'ancien bord posé, et l'élément restait accroché des deux côtés.
    noeud.style.left = noeud.style.right = "auto";
    noeud.style.top = noeud.style.bottom = "auto";
    const style = styleDepuisElement(el);
    Object.keys(style).forEach((k) => { noeud.style[k] = style[k]; });
    noeud.style.display = el.hidden ? "none" : "";
  }

  /** Place tous les éléments d'une scène, et pose l'empilement. */
  function appliquer(slug, scene) {
    if (!scene || !scene.elements) return;
    const ordre = scene.ordre || ELEMENTS;
    ELEMENTS.forEach((cle) => {
      const noeud = document.querySelector(`[data-element="${cle}"]`);
      if (!noeud) return;
      placer(noeud, scene.elements[cle]);
      // L'ordre de la liste EST l'empilement : le premier passe devant.
      const rang = ordre.indexOf(cle);
      noeud.style.zIndex = String(rang < 0 ? 1 : ordre.length - rang);
    });
    document.body.dataset.scene = slug || "";
  }

  return { appliquer, placer, styleDepuisElement, facteurCanvas, ELEMENTS, ANCRAGES };
})();
```

- [ ] **Étape 4 : donner un conteneur à chaque élément dans `overlay.html`**

Dans le bloc `<style>`, remplacer les règles de `#stage` et `#widgets`
(`overlay.html:115-128` et `355-372`) par un positionnement absolu par élément :

```css
    /* ── Placement piloté par le modèle ────────────────────────────────────
       Chaque élément est posé en absolu et reçoit ses bords, sa translation et
       son échelle de `overlay_layout.js`. Aucune position n'est écrite ici :
       ce fichier ne décrit plus QUE l'apparence.

       `#stage` et `#widgets` disparaissent en tant que conteneurs de mise en
       page — ils imposaient un flux commun, ce qui est exactement ce qu'on
       supprime. */
    [data-element] {
      position: absolute;
      /* Sans lui, une largeur en pourcentage se calculerait sur le viewport
         entier ; les widgets ont leur taille propre, ils ne s'étirent pas. */
      width: max-content;
      max-width: 92vw;
    }
```

Puis, dans le corps, envelopper chaque élément :

```html
    <div data-element="avatar"  id="avatar-slot"></div>
    <div data-element="bubble"  id="bubble"><span id="bubble-text"></span></div>
    <div data-element="rotator" id="rotator-slot"></div>
    <div data-element="image"   id="image-slot"></div>
    <!-- Un conteneur par widget : ils ne partagent plus #widgets. -->
    <div data-element="meme"    class="widget-slot"></div>
    <div data-element="bingo"   class="widget-slot"></div>
    <!-- … un par clé de ELEMENTS … -->
```

Et ajouter le script avant `overlay.js` :

```html
    <script src="/static/overlay_layout.js"></script>
```

- [ ] **Étape 5 : orienter la pointe de la bulle**

La bulle est désormais placée librement, mais sa pointe vise l'avatar — c'est le
sens même d'une bulle de BD, et l'arbitrage owner du 2026-08-15 l'a conservée.
Elle est aujourd'hui figée par des règles CSS statiques
(`overlay.html:269-317`, plus leurs miroirs `body[data-side="right"]`).

Ajouter dans `overlay_layout.js` :

```javascript
  /** Oriente la pointe de la bulle vers l'avatar, où qu'il soit.
   *
   *  L'angle est posé en variable CSS plutôt qu'en règles miroir : il y en
   *  avait quatre jeux (gauche/droite × parole/pensée), et une cinquième
   *  position n'aurait pas de règle.
   *
   *  Si l'avatar est masqué dans la scène, la pointe DISPARAÎT — elle viserait
   *  le vide, ce qui se voit immédiatement à l'écran.
   */
  function orienterPointe(scene) {
    const bulle = document.querySelector('[data-element="bubble"]');
    if (!bulle) return;
    const avatar = scene.elements.avatar;
    const el = scene.elements.bubble;
    if (!avatar || avatar.hidden) {
      bulle.classList.add("sans-pointe");
      return;
    }
    bulle.classList.remove("sans-pointe");
    // Repère écran : y croît vers le bas, d'où l'ordre des arguments.
    const angle = Math.atan2(avatar.y - el.y, avatar.x - el.x) * 180 / Math.PI;
    bulle.style.setProperty("--angle-pointe", angle.toFixed(1) + "deg");
  }
```

appelée en fin d'`appliquer()`, et dans `overlay.html` :

```css
    /* La pointe tourne autour de la bulle au lieu d'être fixée à un coin. */
    #bubble.speech::after { transform: rotate(var(--angle-pointe, 90deg)); }
    #bubble.sans-pointe::after,
    #bubble.sans-pointe::before { display: none; }
```

**Attention en implémentant** : ne pas poser `overflow: hidden` sur la bulle.
Les pseudo-éléments qui dessinent la pointe seraient rognés — la pointe n'a
jamais été rendue pendant des semaines pour cette raison (bulles BD,
2026-08-13). Vérifier à l'écran, pas seulement dans le CSS.

- [ ] **Étape 6 : déclarer le nouveau script dans le versionnement**

`bot/dashboard/routes/overlay.py:39` — ajouter `"overlay_layout.js"` à
`_OVERLAY_FILES`. **Sans cela OBS garde indéfiniment la copie du premier
chargement** : le fichier n'aurait pas d'empreinte dans son URL et ne compterait
pas dans la version. Le piège est déjà documenté dans ce fichier.

- [ ] **Étape 7 : lancer les tests et commiter**

```bash
python -m pytest tests/test_overlay_layout_css.py -v
python -m pytest tests/ -q -x
git add bot/dashboard/static/overlay_layout.js bot/dashboard/static/overlay.html bot/dashboard/routes/overlay.py tests/test_overlay_layout_css.py
git commit -m "feat(overlay): chaque élément a sa place, son ancrage et son échelle

Les positions sont en pourcentage et les tailles en transform:scale sur un
canvas de référence de 1920 : la disposition tient à une autre résolution, et
aucun des dix-sept widgets n'a eu besoin qu'on touche à son CSS."
```

---

### Tâche 4 : charger, écouter, et servir les scènes

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay.js` (dispatch, ligne ~1256 ; `widget-on`, ligne ~1150)
- Modifier : `bot/dashboard/app.py` (après la route `/overlay`, ligne ~185)
- Test : `tests/test_overlay_routes_scenes.py`

**Interfaces :**
- Consomme : `window.WallyLayout.appliquer` (tâche 3), `GET /api/public/overlay-layout` (tâche 2).
- Produit : la route `/overlay-<slug>` et le traitement de `{"type": "layout"}`.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# tests/test_overlay_routes_scenes.py
"""Une URL par scène, et l'ancienne qui survit.

`/overlay` reste servie : c'est la source OBS déjà en place chez le streamer,
et la casser pendant la transition mettrait un écran noir en plein live.
"""
import pytest
from fastapi.testclient import TestClient

from bot.core.overlay_layout import SLUGS_RESERVES


@pytest.fixture
def client(app_dashboard):        # fixture existante du projet
    return TestClient(app_dashboard)


def test_overlay_sans_slug_repond_toujours(client):
    assert client.get("/overlay").status_code == 200


def test_chaque_scene_a_son_url(client):
    for slug in ("start", "jeu", "end"):
        r = client.get(f"/overlay-{slug}")
        assert r.status_code == 200
        assert "overlay_layout.js" in r.text


def test_la_page_porte_son_slug(client):
    assert 'data-scene-slug="jeu"' in client.get("/overlay-jeu").text


def test_les_slugs_reserves_ne_sont_pas_captes(client):
    """`/overlay-image` et `/overlay-rotation` existaient AVANT les scènes."""
    for reserve in ("image", "rotation"):
        assert reserve in SLUGS_RESERVES
        assert client.get(f"/overlay-{reserve}").status_code == 200


def test_une_scene_inconnue_sert_quand_meme_une_page(client):
    """OBS peut pointer sur une scène supprimée. Écran noir interdit."""
    assert client.get("/overlay-fantome").status_code == 200
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Commande : `python -m pytest tests/test_overlay_routes_scenes.py -v`
Attendu : 404 sur `/overlay-start`.

- [ ] **Étape 3 : ajouter la route par scène**

Dans `bot/dashboard/app.py`, **après** les routes `/overlay-image` et
`/overlay-rotation` (ligne ~217) — l'ordre de déclaration compte, FastAPI prend
la première qui filtre, et une route paramétrée déclarée avant capterait
`/overlay-image` :

```python
    @app.get("/overlay-{slug}")
    async def overlay_scene(slug: str):
        """La page d'une scène.

        Déclarée APRÈS `/overlay-image` et `/overlay-rotation` : FastAPI retient
        la première route qui filtre, et celle-ci les capterait toutes les deux.

        Un slug inconnu est servi quand même — OBS peut pointer sur une scène
        supprimée, et un 404 mettrait un écran noir en plein live. La page
        demandera son layout et recevra celui de la scène par défaut.
        """
        from bot.dashboard.routes.overlay import (
            overlay_version, version_static_scripts,
        )
        html = (STATIC_DIR / "overlay.html").read_text()
        html = version_static_scripts(html, overlay_version())
        html = html.replace('data-scene-slug=""', f'data-scene-slug="{slug}"')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})
```

Et dans `overlay.html`, poser l'attribut sur `<body>` :
`<body data-side="right" data-scene-slug="">`

- [ ] **Étape 4 : charger le layout et écouter ses mises à jour**

Dans `overlay.js`, ajouter avant la connexion SSE (vers la ligne 1250) :

```javascript
  // Le layout est chargé par un GET, pas attendu du bus : une page ouverte
  // alors que le bus est muet doit quand même se placer.
  const sceneSlug = document.body.dataset.sceneSlug || "";
  async function chargerLayout() {
    try {
      const r = await fetch(
        "/api/public/overlay-layout?scene=" + encodeURIComponent(sceneSlug),
        { cache: "no-store" });
      const data = await r.json();
      WallyLayout.appliquer(data.scene.slug, data.scene);
    } catch (e) {
      // Les défauts du CSS restent en place : mal placé vaut mieux que vide.
      console.warn("layout indisponible", e);
    }
  }
  chargerLayout();
  // La source peut être redimensionnée dans OBS après coup : le facteur de
  // canvas change, les échelles doivent suivre.
  window.addEventListener("resize", chargerLayout);
```

Puis, dans le `switch` du dispatch (`overlay.js:1256`) :

```javascript
      // L'événement est un simple SIGNAL : le layout n'y voyage pas, sans quoi
      // il occuperait le tampon de rejeu au détriment des bulles. On refait le
      // GET, qui reste la seule source de vérité.
      case "layout": chargerLayout(); break;
```

- [ ] **Étape 5 : cesser d'effacer l'avatar pour les widgets qui cohabitent**

`overlay.js:1150` pose `widget-on` sur `<body>`, ce qui efface l'avatar et la
bulle — la limite « un widget occupe tout l'espace » de `docs/overlay.md:331`.
Elle n'a plus lieu d'être quand le widget a sa propre place :

```javascript
    // `widget-on` efface l'avatar et la bulle. Il ne vaut plus que pour les
    // widgets SOLO, qui prennent toute la scène. Un widget qui cohabite a sa
    // place à lui : Wally peut donc l'afficher ET le commenter, ce que la page
    // rendait impossible jusqu'ici.
    document.body.classList.toggle("widget-on", estSolo(kind));
```

avec, près de `chargerLayout` :

```javascript
  // Le modèle est la source : un widget dont on ignore le réglage est traité
  // comme solo, l'ancien comportement — jamais deux widgets superposés par
  // accident.
  let reglages = {};
  function estSolo(kind) {
    const el = reglages[kind];
    return el ? el.solo !== false : true;
  }
```

et `reglages = data.scene.elements;` dans `chargerLayout`, comme dans
`case "layout"`.

- [ ] **Étape 6 : lancer les tests et commiter**

```bash
python -m pytest tests/test_overlay_routes_scenes.py -v
python -m pytest tests/ -q -x
git add bot/dashboard/app.py bot/dashboard/static/overlay.js bot/dashboard/static/overlay.html tests/test_overlay_routes_scenes.py
git commit -m "feat(overlay): une URL par scène, et le layout appliqué en direct

La page charge son layout par un GET et se replace sur événement, sans
rechargement. /overlay reste servie : la source OBS en place ne meurt pas.
Et widget-on ne vaut plus que pour les widgets solo — Wally peut désormais
afficher un meme ET le commenter."
```

---

### Tâche 5 : absorber le rotateur et l'image

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay.js` (montage des deux slots)
- Modifier : `bot/dashboard/static/overlay_rotation.html`, `overlay_image.html` (bandeau d'obsolescence)
- Test : `tests/test_overlay_sources_fusionnees.py`

**Interfaces :**
- Consomme : les conteneurs `data-element="rotator"` et `data-element="image"` (tâche 3).
- Produit : `monterRotateur()` et `monterImage()` dans `overlay.js`.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# tests/test_overlay_sources_fusionnees.py
"""Le rotateur et l'image cessent d'être des sources OBS séparées.

Les deux pages restent servies — elles sont dans OBS chez le streamer — mais
elles portent un avertissement, et leur contenu vit désormais dans la page
principale.
"""
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"


def test_la_page_principale_monte_le_rotateur_et_l_image():
    js = (_STATIC / "overlay.js").read_text(encoding="utf-8")
    assert "monterRotateur" in js
    assert "monterImage" in js
    assert "/api/public/rotation" in js
    assert "/api/public/sse/overlay-image" in js


def test_les_anciennes_pages_avertissent():
    for nom in ("overlay_rotation.html", "overlay_image.html"):
        html = (_STATIC / nom).read_text(encoding="utf-8")
        assert "source-obsolete" in html, f"{nom} n'avertit pas"
```

- [ ] **Étape 2 : lancer, vérifier l'échec**

Commande : `python -m pytest tests/test_overlay_sources_fusionnees.py -v`
Attendu : FAIL sur `assert "monterRotateur" in js`.

- [ ] **Étape 3 : porter les deux boucles dans `overlay.js`**

Reprendre `overlay_rotation.html:106-125` (le `fetch` de `/api/public/rotation`
et la construction de l'URL du média) et `overlay_image.html:106-147` (le
`EventSource` sur `/api/public/sse/overlay-image`), en écrivant dans
`document.querySelector('[data-element="rotator"]')` et `'[data-element="image"]'`
au lieu de leur `<body>`.

Conserver leurs deux garde-fous, tous deux payés en production :
- trois échecs d'affilée du rotateur = serveur absent, on cesse d'insister ;
- `EventSource.onerror` retombe à chaque reconnexion, il ne signale pas une panne.

- [ ] **Étape 4 : marquer les anciennes pages**

En tête de `<body>` des deux fichiers :

```html
  <!-- Ces pages ne sont plus des sources OBS depuis le 2026-08-15 : leur
       contenu vit dans /overlay-<scène>, où il se place comme les autres
       éléments. Conservées le temps que les sources en place disparaissent. -->
  <div class="source-obsolete" style="position:fixed;inset:auto 8px 8px auto;
       padding:6px 10px;border-radius:8px;background:rgba(0,0,0,.6);
       color:#fbbf24;font:12px system-ui">
    Source obsolète — utiliser /overlay-&lt;scène&gt;
  </div>
```

- [ ] **Étape 5 : lancer les tests et commiter**

```bash
python -m pytest tests/test_overlay_sources_fusionnees.py -v
python -m pytest tests/ -q -x
git add bot/dashboard/static/overlay.js bot/dashboard/static/overlay_rotation.html bot/dashboard/static/overlay_image.html tests/test_overlay_sources_fusionnees.py
git commit -m "feat(overlay): le rotateur et l'image rejoignent la page principale

Deux éléments positionnables de plus, deux sources OBS de moins. Les anciennes
pages restent servies avec un avertissement, le temps que les sources en place
chez le streamer disparaissent."
```

---

## Phase 3 — Le panneau de mise en scène

### Tâche 6 : les deux listes

**Fichiers :**
- Créer : `bot/dashboard/static/overlay_admin.js`
- Modifier : `bot/dashboard/static/app.js` (`_renderSystemeOverlay`, ligne 3731)
- Modifier : `bot/dashboard/static/style.css`
- Modifier : `bot/dashboard/static/index.html` (déclaration du script)

**Interfaces :**
- Consomme : `GET|PUT /api/admin/overlay/layout` (tâche 2).
- Produit, sur `window.OverlayAdmin` :
  - `monter(conteneur)` — construit tout le panneau
  - `etat` — `{layout, slugCourant, elementCourant, brouillon, direct}`
  - `marquerModifie()`, `publier()`, `abandonner()`

- [ ] **Étape 1 : construire les listes**

`monter(conteneur)` charge le layout, puis rend deux colonnes conformes à la
disposition retenue le 2026-08-15 (colonne de gauche : scènes puis éléments ;
à droite : la surface). Style glassmorphism obligatoire — fonds
`rgba(255,255,255,.03)`, bordures `rgba(255,255,255,.08)`, rayons 12-16 px,
accent `#06b6d4`.

Chaque scène porte un menu `⋮` : **Renommer** (le slug ne bouge pas — un
avertissement le dit), **Dupliquer**, **Supprimer** (refusée s'il ne reste
qu'une scène), **Définir par défaut**.

Chaque élément porte trois actions : œil (masquer), cadenas (verrouiller),
▶ (tester, tâche 9). La liste se réordonne au glisser et écrit dans
`scene.ordre`.

- [ ] **Étape 2 : accrocher dans `app.js`**

Dans `_renderSystemeOverlay(panel)` (ligne 3731), après les sections existantes :

```javascript
  // La mise en scène vit dans overlay_admin.js : app.js fait déjà 5679 lignes,
  // et ce panneau en pèse plusieurs centaines à lui seul.
  const scene = document.createElement('div');
  scene.className = 'overlay-section';
  panel.appendChild(scene);
  if (window.OverlayAdmin) OverlayAdmin.monter(scene);
```

Déclarer `<script src="/static/overlay_admin.js"></script>` dans `index.html`,
près des autres scripts du panneau.

- [ ] **Étape 3 : vérifier au navigateur**

Ouvrir le panneau, onglet **Système → Overlay**. Les trois scènes et les
vingt-et-un éléments s'affichent. Vérifier dans la console qu'aucune erreur
n'est levée : un `throw` dans un `mount()` casse tous les suivants, et
`node --check` ne voit pas ce genre de faute (incident `buildSections`).

- [ ] **Étape 4 : commiter**

```bash
git add bot/dashboard/static/overlay_admin.js bot/dashboard/static/app.js bot/dashboard/static/style.css bot/dashboard/static/index.html
git commit -m "feat(admin): les scènes et les éléments de l'overlay se listent"
```

---

### Tâche 7 : la surface de placement

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_admin.js`
- Modifier : `bot/dashboard/static/style.css`

**Interfaces :**
- Consomme : `etat` (tâche 6), `WallyLayout.styleDepuisElement` (tâche 3).
- Produit : `rendreSurface()`, `positionDepuisPointeur(evt) -> {x, y}`.

- [ ] **Étape 1 : la surface**

Un conteneur au ratio 16/9 (`aspect-ratio: 16/9`), une grille de 10 % en fond,
un rectangle par élément visible, portant son nom. Un élément masqué est
grisé en pointillés ; un élément verrouillé ne répond pas au pointeur.

- [ ] **Étape 2 : le glisser**

`pointerdown` / `pointermove` / `pointerup` avec `setPointerCapture` — pas
`mousemove` sur `document` : le pointeur sort du cadre pendant un glisser rapide
et le rectangle reste collé. Aimantation sur la grille de 10 %, désactivée en
maintenant `Alt`. Les flèches du clavier déplacent de 0,1 % (2 px sur 1920), avec
`Shift` de 1 %.

La position est calculée depuis l'ancrage de l'élément — le point saisi doit
rester sous le pointeur quel que soit son ancrage :

```javascript
  // L'inverse exact de `styleDepuisElement` : un ancrage à droite mesure
  // depuis ce bord, donc le pourcentage lu est le complément.
  function positionDepuisPointeur(evt, el, cadre) {
    const r = cadre.getBoundingClientRect();
    let x = ((evt.clientX - r.left) / r.width) * 100;
    let y = ((evt.clientY - r.top) / r.height) * 100;
    return { x: Math.max(0, Math.min(100, x)), y: Math.max(0, Math.min(100, y)) };
  }
```

- [ ] **Étape 3 : la barre de réglages**

Sous la surface : le nom de l'élément choisi, `x`, `y`, `taille` en champs
numériques liés au glisser, et une grille de neuf cases pour l'ancrage. Changer
l'ancrage **conserve la position à l'écran** : on recalcule `x`/`y` pour que le
rectangle ne saute pas, sinon chaque changement d'ancrage déplacerait l'élément.

- [ ] **Étape 4 : vérifier au navigateur, puis commiter**

```bash
git add bot/dashboard/static/overlay_admin.js bot/dashboard/static/style.css
git commit -m "feat(admin): la surface de placement, au glisser et au clavier"
```

---

### Tâche 8 : brouillon, publication, garde-fous

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_admin.js`

**Interfaces :**
- Consomme : `etat`, `PUT /api/admin/overlay/layout`.
- Produit : `publier()`, `abandonner()`, `annulerDernierePublication()`.

- [ ] **Étape 1 : la case et le compteur**

*Aperçu en direct* **décoché par défaut** — le cas dangereux ne doit pas être
celui qu'on obtient sans rien faire. Décoché : les modifications restent locales,
le compteur affiche « N modifications non publiées », les boutons **Mettre à
jour** et **Abandonner** apparaissent. Coché : chaque `pointerup` publie ; rien
n'est émis pendant le geste lui-même.

- [ ] **Étape 2 : la survie du brouillon**

`localStorage` sous `wally:overlay:brouillon`, **jamais la base** : un brouillon
rangé en base serait publié au redémarrage du bot, alors qu'il n'a pas été
validé. Au montage, si un brouillon existe, le proposer explicitement plutôt que
de l'appliquer d'office.

`beforeunload` avertit s'il reste des modifications en attente.

- [ ] **Étape 3 : annuler**

Avant chaque publication, garder le layout précédent en mémoire. **Annuler**
republie celui-là. Un seul niveau suffit — c'est le filet pour ne pas rester
coincé en plein live, pas un historique.

- [ ] **Étape 4 : vérifier au navigateur**

Décocher, déplacer trois éléments, vérifier que l'overlay ouvert dans un autre
onglet **ne bouge pas**. Cliquer *Mettre à jour*, vérifier qu'il se replace sans
rechargement. Rafraîchir le panneau, vérifier que le brouillon est proposé.

- [ ] **Étape 5 : commiter**

```bash
git add bot/dashboard/static/overlay_admin.js
git commit -m "feat(admin): mode brouillon — l'overlay ne bouge qu'à la demande

Aperçu en direct décoché par défaut : on peut préparer la scène de fin pendant
que le live tourne sans que rien ne bouge à l'écran. Le brouillon vit dans le
navigateur et jamais en base, sinon un redémarrage publierait des changements
jamais validés."
```

---

## Phase 4 — Finitions

### Tâche 9 : tester un élément, tout afficher

**Fichiers :**
- Modifier : `bot/dashboard/routes/overlay.py`
- Modifier : `bot/dashboard/static/overlay.js`
- Modifier : `bot/dashboard/static/overlay_admin.js`
- Test : `tests/test_overlay_preview.py`

**Interfaces :**
- Produit : `POST /api/admin/overlay/preview` — corps
  `{"scene": "<slug>", "element": "<clé>"}` ou `{"scene": "<slug>", "tous": true}`.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# tests/test_overlay_preview.py
"""Le bouton Tester ne doit JAMAIS surgir sur la scène en direct.

C'est tout l'intérêt du champ `scene` sur les événements : on règle la scène de
fin pendant que le live tourne sur celle du jeu.
"""
import pytest
from fastapi.testclient import TestClient


def test_la_previsualisation_cible_une_seule_scene(app_dashboard, feed_espion):
    client = TestClient(app_dashboard)
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "end", "element": "dice"},
                    headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    evt = feed_espion.publies[-1]
    assert evt["scene"] == "end"       # et surtout pas None
    assert evt["type"] == "widget"
    assert evt["kind"] == "dice"


def test_tout_afficher_envoie_des_fantomes_de_la_scene(app_dashboard, feed_espion):
    client = TestClient(app_dashboard)
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "jeu", "tous": True},
                    headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    evt = feed_espion.publies[-1]
    assert evt["type"] == "ghosts"
    assert evt["scene"] == "jeu"
    assert "avatar" in evt["elements"]


def test_un_element_inconnu_est_refuse(app_dashboard):
    client = TestClient(app_dashboard)
    r = client.post("/api/admin/overlay/preview",
                    json={"scene": "jeu", "element": "licorne"},
                    headers={"Authorization": "Bearer test"})
    assert r.status_code == 400
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — 404 sur la route.

- [ ] **Étape 3 : la route**

```python
# Un jeu de paramètres par widget, calé sur le SCHÉMA de `_WIDGETS`
# (overlay_narrator.py:249-346). Un widget testé sans paramètre se construirait
# vide et ne dirait rien de son encombrement réel — or c'est exactement ce
# qu'on cherche à voir en le plaçant.
#
# Les valeurs sont volontairement LONGUES là où la largeur varie (le sondage à
# quatre options, le versus, le message épinglé) : on règle sur le pire cas,
# pas sur le cas commode.
_ECHANTILLONS: dict[str, dict] = {
    "coinflip":  {"result": "heads"},
    "dice":      {"result": "4", "count": 2},
    "wheel":     {"options": ["Fuse", "Bloodhound", "Rampart", "Mirage"],
                  "result": 0},
    "countdown": {"seconds": 60, "done": "C'est l'heure"},
    "gauge":     {"percent": 62, "label": "Objectif kills"},
    "pinned":    {"text": "Un message du chat, assez long pour occuper "
                          "toute la largeur prévue", "author": "kassandreyunikon"},
    "uptime":    {},
    "counter":   {"text": "12 morts en tombant"},
    "poll":      {"question": "On enchaîne sur du classé ?",
                  "options": ["Oui", "Non", "Une pause d'abord", "Peu importe"],
                  "seconds": 20},
    "stats":     {"player": "Azraël",
                  "lines": ["Rang : Platine 4", "RP : 8 756",
                            "Kills : 102 324", "3ᵉ mondial avec Fuse"]},
    "versus":    {"label": "Kills", "left_name": "Azraël", "left_value": 18,
                  "right_name": "KingsRequin", "right_value": 7},
    "bingo":     {"cells": ["Azra tombe de la map", "Kassandre parle en fight",
                            "Un random qui ping tout", "Zéro dégât sur un fight",
                            "Requin explique Mirage", "Fuse ulti dans le vide"],
                  "check": 0},
    "meme":      {},
    "rps":       {"move": "pierre"},
    "hangman":   {"word": "octane", "hint": "il court vite", "sticky": True},
    "goal":      {"target": 50, "kind": "follow"},
    "talkers":   {},
    # `rotator` et `image` ne passent pas par un builder de widget : ils ont
    # leur propre montage. Le panneau les teste en posant un média d'exemple.
}


@admin_router.post("/overlay/preview")
async def post_overlay_preview(request: Request) -> dict:
    """Affiche un élément — ou tous — sur UNE scène, pour la régler.

    Le champ `scene` est le cœur de la fonction : sans lui, tester un dé
    pendant qu'on prépare la scène de fin le ferait surgir en plein live.
    """
    from bot.core.overlay_layout import ELEMENTS
    data = await request.json()
    slug = str(data.get("scene") or "")
    feed = getattr(request.app.state.wally, "overlay_feed", None)
    if feed is None:
        raise HTTPException(503, "Bus overlay indisponible")
    if data.get("tous"):
        layout = await charger_layout(_db(request))
        scene = scene_par_slug(layout, slug)
        if scene is None:
            raise HTTPException(404, "Scène inconnue")
        feed.publish({"type": "ghosts", "scene": slug,
                      "elements": scene["elements"]})
        return {"ok": True}
    cle = str(data.get("element") or "")
    if cle not in ELEMENTS:
        raise HTTPException(400, f"Élément inconnu : {cle}")
    feed.publish({"type": "widget", "scene": slug, "kind": cle,
                  "params": {**_ECHANTILLONS.get(cle, {}), "duration": 20}})
    return {"ok": True}
```

- [ ] **Étape 4 : le filtre côté page**

Dans le dispatch d'`overlay.js`, **avant** le `switch`, écarter ce qui vise une
autre scène :

```javascript
    // Un événement qui porte un slug ne concerne QUE cette page. Sans ce
    // filtre, régler une scène ferait surgir des widgets sur celle en direct.
    if (event.scene && event.scene !== sceneSlug) return;
```

et le cas des fantômes :

```javascript
      case "ghosts": afficherFantomes(event.elements); break;
```

`afficherFantomes` pose un rectangle nommé, semi-transparent, à la place de
chaque élément non masqué, effacé au bout de 30 s ou à la prochaine annulation.

- [ ] **Étape 5 : lancer les tests et commiter**

```bash
python -m pytest tests/test_overlay_preview.py -v && python -m pytest tests/ -q -x
git add bot/dashboard/routes/overlay.py bot/dashboard/static/overlay.js bot/dashboard/static/overlay_admin.js tests/test_overlay_preview.py
git commit -m "feat(admin): tester un élément sans le faire surgir en direct

Le chifoumi, le dé et la jauge n'apparaissent presque jamais : sans ce bouton
ils se régleraient à l'aveugle. Le champ scene garantit qu'ils ne s'affichent
que sur la page qu'on est en train de régler."
```

---

### Tâche 10 : capture de fond, chevauchements, export

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_admin.js`
- Modifier : `bot/dashboard/static/style.css`

- [ ] **Étape 1 : la capture en fond**

Un `<input type="file" accept="image/*">` qui lit en `dataURL` et pose l'image en
fond de la surface, rangée dans `localStorage` sous `wally:overlay:fond`. Côté
navigateur uniquement : c'est une aide au placement, elle n'a rien à faire en
base et ne doit jamais partir vers l'overlay. Un curseur d'opacité de 20 à 100 %.

- [ ] **Étape 2 : les chevauchements**

Après chaque déplacement, comparer les rectangles des éléments **non masqués et
non solo** deux à deux. Chevauchement de plus de 20 % de la surface du plus
petit → bordure orange et mention dans la barre. Les éléments `solo` ne sont pas
comparés : ils ne sont jamais à l'écran ensemble.

- [ ] **Étape 3 : export et import**

**Exporter** télécharge le JSON complet (`overlay-layout-AAAA-MM-JJ.json`).
**Importer** lit un fichier, le passe par `PUT` — donc par `fusionner`, qui le
valide — et rafraîchit. Un fichier illisible affiche l'erreur sans rien changer.

- [ ] **Étape 4 : réinitialiser**

Deux portées, l'une et l'autre demandant confirmation :

```javascript
  // Les défauts viennent du serveur, pas d'une copie côté navigateur : deux
  // tables de défauts divergeraient à la première évolution du modèle.
  async function reinitialiser(portee, cle) {
    const defauts = await (await fetch("/api/admin/overlay/layout?defauts=1",
      { headers: entetesAdmin() })).json();
    const source = defauts.scenes.find((s) => s.slug === etat.slugCourant)
      || defauts.scenes[0];
    const scene = sceneCourante();
    if (portee === "element") scene.elements[cle] = { ...source.elements[cle] };
    else { scene.elements = structuredClone(source.elements);
           scene.ordre = [...source.ordre]; }
    marquerModifie();
  }
```

Ajouter le paramètre à la route admin de la tâche 2 :

```python
@admin_router.get("/overlay/layout")
async def get_overlay_layout_admin(request: Request, defauts: int = 0) -> dict:
    """Tout le modèle — ou les défauts, pour le bouton Réinitialiser.

    Les défauts sont servis d'ici plutôt que recopiés dans le panneau : deux
    tables divergeraient dès la première évolution du modèle.
    """
    if defauts:
        from bot.core.overlay_layout import layout_par_defaut
        return layout_par_defaut()
    return await charger_layout(_db(request))
```

- [ ] **Étape 5 : vérifier au navigateur et commiter**

```bash
git add bot/dashboard/static/overlay_admin.js bot/dashboard/static/style.css
git commit -m "feat(admin): capture en fond, chevauchements, export/import, réinit"
```

---

### Tâche 11 : Wally sait ce qu'il peut afficher

**Fichiers :**
- Modifier : `bot/intelligence/overlay_narrator.py` (enum ligne ~254, `show_widget`)
- Test : `tests/test_overlay_widgets_masques.py`

**Interfaces :**
- Consomme : `charger_layout` (tâche 2).
- Produit : `async widgets_disponibles(db) -> set[str]`, et un refus explicite
  dans `show_widget`.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# tests/test_overlay_widgets_masques.py
"""Ce qu'il croit avoir affiché doit correspondre à ce qui s'est produit.

C'est la leçon de « il ne savait pas qu'il affichait les bingos » : un widget
masqué partout ne doit ni lui être proposé, ni le laisser annoncer « c'est à
l'écran » s'il le demande quand même.
"""
import json

import pytest

from bot.core.overlay_layout import layout_par_defaut
from bot.core.overlay_layout_store import LAYOUT_KEY
from bot.intelligence.overlay_narrator import widgets_disponibles


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


def _base_avec(masques_par_scene):
    layout = layout_par_defaut()
    for scene in layout["scenes"]:
        for cle in masques_par_scene.get(scene["slug"], []):
            scene["elements"][cle]["hidden"] = True
    return _State({LAYOUT_KEY: json.dumps(layout)})


@pytest.mark.asyncio
async def test_masque_dans_une_seule_scene_reste_disponible():
    """Le bingo masqué sur le Starting sert quand même en jeu — Wally ignore
    quelle scène est à l'antenne, c'est la page qui filtre."""
    db = _base_avec({"start": ["bingo"]})
    assert "bingo" in await widgets_disponibles(db)


@pytest.mark.asyncio
async def test_masque_partout_devient_indisponible():
    db = _base_avec({"start": ["bingo"], "jeu": ["bingo"], "end": ["bingo"]})
    assert "bingo" not in await widgets_disponibles(db)


@pytest.mark.asyncio
async def test_sans_layout_tout_est_disponible():
    """Une base vide ne doit pas priver Wally de ses outils."""
    assert "bingo" in await widgets_disponibles(_State())


@pytest.mark.asyncio
async def test_un_widget_masque_partout_est_refuse_pas_annonce(narrateur_avec_db):
    """Une action différée passe à côté de l'enum : le refus doit venir de
    l'exécution, sinon il annonce « c'est à l'écran » sans que rien ne le soit."""
    narrateur = narrateur_avec_db(_base_avec(
        {"start": ["dice"], "jeu": ["dice"], "end": ["dice"]}))
    rendu = await narrateur.show_widget("dice", "regardez ça")
    assert rendu is False
```

- [ ] **Étape 2 : lancer, vérifier l'échec** — `ImportError` sur
  `widgets_disponibles`.

- [ ] **Étape 3 : implémenter**

```python
async def widgets_disponibles(db) -> set[str]:
    """Les widgets affichables sur AU MOINS une scène.

    Masqué dans une seule scène ne rend pas un widget inutile : Wally ignore
    laquelle est à l'antenne, et c'est la page qui filtre. Seul un masquage
    PARTOUT vaut « tu ne peux pas t'en servir ».
    """
    from bot.core.overlay_layout import ELEMENTS
    from bot.core.overlay_layout_store import charger_layout
    layout = await charger_layout(db)
    return {
        cle for cle in ELEMENTS
        if any(not scene["elements"][cle]["hidden"] for scene in layout["scenes"])
    }
```

L'enum de `_WIDGETS` (ligne ~254) est filtré par cet ensemble au moment de bâtir
les outils. Et dans `show_widget`, avant tout affichage :

```python
        if kind not in await widgets_disponibles(self._db):
            # Le dire, et ne pas l'afficher. `_note_overlay_refus` consigne
            # déjà les refus : le motif rejoint les autres.
            self._note_overlay_refus(kind, {"motif": "masqué sur toutes les scènes"})
            return False
```

- [ ] **Étape 4 : lancer les tests et commiter**

```bash
python -m pytest tests/test_overlay_widgets_masques.py -v && python -m pytest tests/ -q -x
git add bot/intelligence/overlay_narrator.py tests/test_overlay_widgets_masques.py
git commit -m "feat(overlay): il ne propose plus ce qu'aucune scène n'affiche

Masqué dans une seule scène, le widget reste utilisable — c'est la page qui
filtre. Masqué partout, il sort de son enum ET reçoit un refus explicite s'il
le demande via une action différée, au lieu d'annoncer « c'est à l'écran »
devant un écran où rien ne s'affiche."
```

---

### Tâche 12 : la documentation

**Fichiers :**
- Modifier : `docs/overlay.md`
- Modifier : `CLAUDE.md`

- [ ] **Étape 1 : `docs/overlay.md`**

- **Installation dans OBS** : une source par scène, 1920 × 1080 non
  redimensionnée, URL `/overlay-<slug>`. Remplace le tableau 560 × 460.
- **Limites connues** : retirer « Un widget occupe tout l'espace » — c'est faux
  depuis la tâche 4. Ce document est déclaré vivant en tête de fichier ; le
  laisser mentir en ferait une promesse invérifiable.
- **Le rotateur de memes — une seconde source, sans Wally** (ligne 395) :
  réécrire, ce n'est plus une source.
- Nouvelle section **La mise en scène** : les scènes, le panneau, le brouillon.

- [ ] **Étape 2 : `CLAUDE.md`**

Une ligne dans la section overlay : le layout vit dans `bot_state` sous
`overlay:layout`, le modèle dans `bot/core/overlay_layout.py`, et Wally ne
décide jamais **où** s'affiche un élément.

- [ ] **Étape 3 : commiter**

```bash
git add docs/overlay.md CLAUDE.md
git commit -m "docs(overlay): les scènes, et la limite qui tombe"
```

---

## Après la dernière tâche

- [ ] `python -m pytest tests/ -q` — la suite entière.
- [ ] `python scripts/lint_silences.py` et `python scripts/lint_types.py` — les
      deux cliquets du projet ; ils ne doivent pas remonter.
- [ ] Rebuild **avec** `GIT_HASH` et `BUILD_DATE`, faute de quoi
      `BOT_GIT_HASH` vaut `unknown` (piège déjà payé).
- [ ] Vérifier en prod : ouvrir `/overlay-jeu`, déplacer un élément depuis le
      panneau, constater qu'il se replace **sans rechargement**.
- [ ] `git push public feat/site-redesign-arcade:main`.
