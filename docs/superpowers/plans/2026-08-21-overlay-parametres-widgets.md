# Paramètres par widget dans l'éditeur d'overlay — plan d'implémentation

> **Pour un exécutant :** les étapes sont en cases à cocher (`- [ ]`). Une tâche
> = un cycle test → implémentation → vérification → commit. On ne passe pas à la
> phase suivante sans le feu vert de l'owner.

**But :** donner à chaque widget de l'overlay dix réglages par scène (opacité,
rotation, miroir, largeur max, durée d'affichage, délai, animations d'entrée /
de sortie / d'insistance, durée d'animation), réglables depuis le panneau de
mise en scène.

**Architecture :** le modèle (`bot/core/overlay_layout.py`) décrit, valide et
borne ; il ne connaît ni réseau ni base. Les portées (quel élément porte quel
champ) sont **calculées** depuis `ELEMENTS`, jamais listées à la main. La page
lit ces valeurs à deux endroits seulement : `placer()` pour tout ce qui est
visuel, `showWidget()` pour tout ce qui est temporel. Le panneau les édite via
trois natures de champ (numérique, booléenne, choix).

**Pile :** Python 3 / FastAPI / aiosqlite côté serveur · JavaScript vanilla (pas
de framework, pas de build) côté page et panneau · `animate.min.css` déjà servi ·
pytest (`asyncio_mode = auto`).

**Spec :** `docs/superpowers/specs/2026-08-21-overlay-parametres-widgets-design.md`

## Contraintes globales

- **La valeur livrée reproduit exactement le comportement d'aujourd'hui.** Aucun
  overlay ne doit changer d'aspect ni de rythme au rebuild. C'est le critère
  d'acceptation numéro un de chaque phase.
- **`duree = 0` signifie « auto : le serveur décide »**, et c'est la valeur
  livrée. Idem `largeur_max = 0` (= le `max-width: 92vw` actuel).
- **Fusionner, jamais remplacer** : une clé absente, `null`, d'un type inattendu
  ou hors bornes reprend son défaut. Jamais d'exception, jamais d'overlay vide.
- **Une seule autorité par valeur.** Les listes d'animations et les portées sont
  écrites en Python et **servies** au panneau. Aucune table recopiée en JS.
- **Aucun `except` muet** (`scripts/lint_silences.py` le vérifie), `loguru`
  uniquement, jamais `print()`.
- **Vérification avant de clore une phase :**
  `python3 -m pytest tests/ -q` · `python3 scripts/lint_types.py` ·
  `python3 scripts/lint_silences.py` — puis commit + rebuild + push.
- **Rebuild :** `bot/**/*.py` exige un rebuild ; `bot/dashboard/static/` non
  (bind-mount, un rechargement du navigateur suffit).

---

## Structure des fichiers

| Fichier | Responsabilité | Phase |
|---|---|---|
| `bot/core/overlay_layout.py` | les dix champs, les portées calculées, les bornes, les listes d'animations, la fusion | 1 |
| `bot/dashboard/routes/overlay.py` | servir `animations` et `portees` au panneau | 1 |
| `bot/dashboard/static/overlay_layout.js` | `placer()` : opacité, rotation, miroir, largeur max | 2 |
| `bot/dashboard/static/overlay.html` | la règle CSS `[data-element] > *` étendue | 2 |
| `bot/dashboard/static/overlay.js` | `showWidget()`, `say()`, `IMAGE.montrer()` : durée, délai, animations | 3 |
| `bot/dashboard/static/overlay_admin.js` | trois natures de champ, sélecteur d'animation, journal des différences | 4 |
| `bot/dashboard/static/style.css` | le style du sélecteur d'animation | 4 |
| `bot/dashboard/static/app.js` | retrait des quatre champs `overlay_image` | 5 |
| `bot/core/overlay_layout_store.py` | la graine `overlay_image` → layout, une fois | 5 |

---

# Phase 1 — Le modèle

Rien de visible ne change. À la fin de cette phase, le layout porte dix champs de
plus, tous à leur valeur livrée, et la route les sert au panneau.

### Tâche 1.1 — Les portées, calculées et non listées

**Fichiers :**
- Modifier : `bot/core/overlay_layout.py`
- Test : `tests/test_overlay_zones_portees.py` (existe) et
  `tests/test_overlay_layout.py` (existe)

**Interfaces produites :**
- `HORS_FILE: frozenset[str]` — les 4 éléments hors `showWidget`
- `widgets_qui_passent() -> frozenset[str]` — les 33 autres
- `CHAMPS_PROPRES: dict[str, dict[str, tuple[float, float, bool]]]` —
  `élément → {champ → (mini, maxi, auto)}`. `auto=True` : la valeur `0` est
  acceptée **hors** de `[mini, maxi]` et signifie « le serveur décide ».
- `CHAMPS_CHOIX: dict[str, dict[str, frozenset[str]]]` — `élément → {champ → choix}`

- [ ] **Étape 1 : écrire le test qui échoue**

Dans `tests/test_overlay_layout.py` :

```python
def test_les_quatre_elements_hors_file_sont_ceux_qui_ont_leur_propre_rendu():
    """`avatar`, `bubble`, `rotator` et `image` ne passent pas par
    `showWidget` : ils ne reçoivent ni `delai` ni les animations de carte.
    La liste est écrite ici pour que l'ajout d'un cinquième chemin de rendu
    casse un test au lieu de passer inaperçu."""
    from bot.core.overlay_layout import HORS_FILE, widgets_qui_passent
    assert HORS_FILE == {"avatar", "bubble", "rotator", "image"}
    assert len(widgets_qui_passent()) == len(ELEMENTS) - 4
    assert not (widgets_qui_passent() & HORS_FILE)


def test_chaque_widget_qui_passe_porte_les_champs_de_rythme():
    """Calculé, pas listé : un widget ajouté à `ELEMENTS` sans son entrée dans
    une table écrite à la main resterait hors de portée du panneau à jamais.

    Les trois champs à CHOIX (`anim_entree`, `anim_sortie`, `anim_insistance`)
    arrivent à la tâche 1.2, avec le catalogue d'animations dont ils tirent
    leurs options — ce test-ci les ajoutera alors."""
    from bot.core.overlay_layout import widgets_qui_passent
    for cle in widgets_qui_passent():
        el = ELEMENTS[cle]
        for champ in ("duree", "delai", "anim_duree"):
            assert champ in el, f"{cle} sans {champ}"


def test_chaque_champ_propre_a_ses_bornes_declarees():
    """Une valeur sans bornes serait rangée telle quelle : la table des bornes
    et les défauts doivent se recouvrir exactement, des deux côtés."""
    from bot.core.overlay_layout import CHAMPS_CHOIX, CHAMPS_PROPRES
    for cle, el in ELEMENTS.items():
        bornes = set(CHAMPS_PROPRES.get(cle, {}))
        choix = set(CHAMPS_CHOIX.get(cle, {}))
        assert not (bornes & choix), f"{cle} : champ à la fois borné et à choix"
        for champ in bornes | choix:
            assert champ in el, f"{cle} : {champ} borné mais sans défaut"


def test_les_quatre_champs_universels_sont_sur_les_trente_sept():
    for cle, el in ELEMENTS.items():
        assert el["opacite"] == 1.0, cle
        assert el["rotation"] == 0.0, cle
        assert el["miroir"] is False, cle
        assert el["largeur_max"] == 0.0, cle
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_layout.py -q -k "portee or champ or universel or hors_file"`
Attendu : `ImportError: cannot import name 'HORS_FILE'`

- [ ] **Étape 3 : implémenter**

Dans `bot/core/overlay_layout.py`, après les constantes `ROTATEUR_*` :

```python
# ── Les réglages universels ─────────────────────────────────────────────────
#
# Les quatre que TOUS les éléments portent, parce qu'ils passent tous par
# `placer()` (overlay_layout.js), le point d'écriture unique du style. Ici et
# pas dans `CHAMPS_PROPRES` : un champ que les trente-sept ont n'est pas
# « propre » à quelqu'un, et le mettre dans la table obligerait à l'y répéter
# trente-sept fois.
#
# Le plancher d'opacité est 0,1 et non 0 : à zéro l'élément est invisible mais
# occupe toujours la scène, efface Wally et passe dans la file — un « masqué »
# qui ne dit pas son nom, alors que `hidden` existe et coupe vraiment.
OPACITE_MIN, OPACITE_MAX, OPACITE_DEFAUT = 0.1, 1.0, 1.0
ROTATION_MIN, ROTATION_MAX, ROTATION_DEFAUT = -45.0, 45.0, 0.0
MIROIR_DEFAUT = False
# `largeur_max` : 0 vaut AUTO, c'est-à-dire le `max-width: 92vw` que
# `[data-element]` porte déjà. Le plancher de 120 px évite une carte réduite à
# un trait, le plafond est la largeur du canvas de référence.
LARGEUR_MIN, LARGEUR_MAX, LARGEUR_DEFAUT = 120.0, 1920.0, 0.0

# ── Les réglages de rythme des widgets qui PASSENT ──────────────────────────
#
# `duree` = 0 vaut AUTO : le serveur décide, comme aujourd'hui. C'est la valeur
# LIVRÉE, et c'est ce qui protège le live — livrer 12 s (le repli de
# `showWidget`) ferait disparaître un sondage de 120 s à la douzième seconde,
# sur les trois scènes, dès le premier rebuild et sans que personne ait touché
# à un curseur.
#
# Le plafond de 180 s est celui de `showWidget` (overlay.js), et il n'est pas
# arbitraire : le serveur émet jusqu'à 124 s (sondage de 120 s + 4).
WIDGET_DUREE_MIN, WIDGET_DUREE_MAX, WIDGET_DUREE_DEFAUT = 2.0, 180.0, 0.0
DELAI_MIN, DELAI_MAX, DELAI_DEFAUT = 0.0, 10.0, 0.0
# 0,15 s = `GLITCH_MS` (5 états × 30 ms) : la durée de la rafale d'aujourd'hui.
ANIM_DUREE_MIN, ANIM_DUREE_MAX, ANIM_DUREE_DEFAUT = 0.1, 3.0, 0.15

# La bulle a son propre chemin (`say`), avec un repli de 3 s côté page.
BULLE_DUREE_MIN, BULLE_DUREE_MAX, BULLE_DUREE_DEFAUT = 1.0, 60.0, 0.0

# Les quatre éléments qui ont leur PROPRE chemin de rendu et ne passent donc
# PAS par `showWidget` : l'avatar et la bulle vivent en permanence, le rotateur
# porte sa propre boucle, la galerie écoute son propre flux SSE. Leur donner
# `delai` ou une animation de carte serait un réglage qu'aucun code ne lit.
HORS_FILE = frozenset({"avatar", "bubble", "rotator", "image"})


def widgets_qui_passent() -> frozenset[str]:
    """Les éléments montés par `showWidget` : tout `ELEMENTS` sauf `HORS_FILE`.

    CALCULÉ et non listé. Une liste écrite à la main aurait laissé le prochain
    widget ajouté hors de portée du panneau, en silence et pour toujours —
    c'est exactement le défaut que le commentaire d'`ELEMENTS` décrit déjà.
    """
    return frozenset(ELEMENTS) - HORS_FILE
```

Puis modifier `_el()` pour porter les quatre universels :

```python
def _el(x: float, y: float, anchor: str, scale: float = 1.0,
        *, solo: bool = True, hidden: bool = False,
        wally_visible: bool | None = None,
        propres: dict | None = None) -> dict:
    # ... commentaire existant conservé ...
    return {"x": x, "y": y, "anchor": anchor, "scale": scale,
            "hidden": hidden, "locked": False, "solo": solo,
            "wally_visible": (not solo) if wally_visible is None else wally_visible,
            # Les quatre universels : tout élément passe par `placer()`, donc
            # tout élément peut les porter. Leurs valeurs livrées ne changent
            # rien à ce que l'overlay rend aujourd'hui.
            "opacite": OPACITE_DEFAUT, "rotation": ROTATION_DEFAUT,
            "miroir": MIROIR_DEFAUT, "largeur_max": LARGEUR_DEFAUT,
            **(propres or {})}
```

Enfin, **après** la définition d'`ELEMENTS`, la passe qui distribue les champs
de portée et remplit les deux tables de validation d'un seul mouvement :

```python
# ── Les réglages de portée, distribués en UN SEUL endroit ───────────────────
#
# `ELEMENTS`, `CHAMPS_PROPRES` et `CHAMPS_CHOIX` se remplissent ensemble, dans
# la boucle ci-dessous. C'est ce qui rend impossible le défaut le plus probable
# ici : un champ posé sur un élément sans bornes déclarées, donc rangé tel quel
# sans validation. Les trois tables ne peuvent plus diverger, elles n'ont qu'un
# seul écrivain.
#
# Le troisième membre du tuple dit si `0` est accepté HORS des bornes, avec le
# sens « auto : le serveur décide ». Sans lui, `_borner(0, 2, 180, 0)` rendrait
# 2 s et la valeur livrée deviendrait une durée de deux secondes.
CHAMPS_PROPRES: dict[str, dict[str, tuple[float, float, bool]]] = {}
CHAMPS_CHOIX: dict[str, dict[str, frozenset[str]]] = {}


def _poser(cle: str, champ: str, defaut, bornes=None, choix=None) -> None:
    ELEMENTS[cle][champ] = defaut
    if bornes is not None:
        CHAMPS_PROPRES.setdefault(cle, {})[champ] = bornes
    if choix is not None:
        CHAMPS_CHOIX.setdefault(cle, {})[champ] = choix


# Les trois champs à CHOIX arrivent à la tâche 1.2, dans cette même boucle :
# ils ont besoin du catalogue d'animations, qui n'existe pas encore ici.
for _cle in widgets_qui_passent():
    _poser(_cle, "duree", WIDGET_DUREE_DEFAUT,
           (WIDGET_DUREE_MIN, WIDGET_DUREE_MAX, True))
    _poser(_cle, "delai", DELAI_DEFAUT, (DELAI_MIN, DELAI_MAX, False))
    _poser(_cle, "anim_duree", ANIM_DUREE_DEFAUT,
           (ANIM_DUREE_MIN, ANIM_DUREE_MAX, False))

# La bulle : une durée de réplique, rien d'autre. Elle n'a ni file d'attente ni
# carte, sa sortie est un éclatement écrit dans le CSS.
_poser("bubble", "duree", BULLE_DUREE_DEFAUT,
       (BULLE_DUREE_MIN, BULLE_DUREE_MAX, True))

# La galerie : les quatre réglages qui vivaient dans `config.yaml`
# (`overlay_image`). Elle a son propre flux SSE et son propre minuteur, donc
# pas de `delai` ni d'insistance — mais bien une durée et deux animations,
# qu'elle avait déjà.
_poser("image", "duree", WIDGET_DUREE_DEFAUT,
       (WIDGET_DUREE_MIN, WIDGET_DUREE_MAX, True))
_poser("image", "anim_duree", ANIM_DUREE_DEFAUT,
       (ANIM_DUREE_MIN, ANIM_DUREE_MAX, False))

# Le rotateur garde sa cadence, avec le sens et les bornes qu'elle a toujours
# eus : `duree` y est la durée d'UN MÉDIA, pas celle d'un passage à l'écran, et
# son plafond de 120 s tient au gardien anti-gel de la boucle. Même mot, autre
# grandeur — c'est pour cela que la table est indexée par ÉLÉMENT.
_poser("rotator", "duree", ROTATEUR_DUREE_DEFAUT,
       (ROTATEUR_DUREE_MIN, ROTATEUR_DUREE_MAX, False))
_poser("rotator", "pause", ROTATEUR_PAUSE_DEFAUT,
       (ROTATEUR_PAUSE_MIN, ROTATEUR_PAUSE_MAX, False))
```

Retirer du même coup le `propres={...}` de la ligne `"rotator"` dans `ELEMENTS`
(la boucle le pose désormais) et l'ancienne table `CHAMPS_PROPRES` plate.

- [ ] **Étape 4 : vérifier que les tests passent**

Run : `python3 -m pytest tests/test_overlay_layout.py tests/test_overlay_zones_portees.py -q`
Attendu : tout vert. Si `test_overlay_layout.py` importait l'ancien
`CHAMPS_PROPRES` plat, adapter l'import — **sans** asserter la nouvelle forme
comme une ligne d'implémentation (asserter une ligne d'implémentation fige le
défaut : vu six fois dans ce dépôt).

- [ ] **Étape 5 : commit**

```bash
git add bot/core/overlay_layout.py tests/test_overlay_layout.py
git commit -m "feat(overlay): les portées des réglages se calculent au lieu de se lister"
```

---

### Tâche 1.2 — Les listes d'animations, écrites une seule fois

**Fichiers :**
- Modifier : `bot/core/overlay_layout.py`
- Test : `tests/test_overlay_animations.py` (existe)

**Interfaces produites :**
- `ANIM_DEFAUT = "glitch"`, `ANIM_AUCUNE = "aucune"`
- `ANIMATIONS: dict[str, dict[str, tuple[str, ...]]]` — `menu → famille → noms`,
  avec `menu ∈ {"entree", "sortie", "insistance"}`
- `ANIMS_ENTREE`, `ANIMS_SORTIE`, `ANIMS_INSISTANCE : frozenset[str]` — dérivés
  d'`ANIMATIONS`, pour la validation

- [ ] **Étape 1 : écrire le test qui échoue**

```python
def test_chaque_animation_annoncee_existe_vraiment_dans_animate_css():
    """La liste est servie au panneau : une entrée qui ne correspond à aucune
    classe donnerait un choix qui ne fait RIEN, sans la moindre erreur — la
    définition même d'un réglage qui ment."""
    from pathlib import Path
    from bot.core.overlay_layout import ANIMATIONS, ANIM_AUCUNE, ANIM_DEFAUT
    css = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
           / "animate.min.css").read_text(encoding="utf-8")
    for menu in ANIMATIONS.values():
        for noms in menu.values():
            for nom in noms:
                if nom in (ANIM_DEFAUT, ANIM_AUCUNE):
                    continue        # les deux options maison
                assert f"animate__{nom}" in css, f"classe absente : {nom}"


def test_les_trois_menus_portent_le_compte_attendu():
    """42 entrées, 42 sorties, 13 effets d'insistance — plus `glitch` et
    `aucune` là où ils ont un sens. Le compte est là pour qu'une mise à jour
    d'animate.css qui retire une animation se voie ici et pas en live."""
    from bot.core.overlay_layout import ANIMS_ENTREE, ANIMS_INSISTANCE, ANIMS_SORTIE
    assert len(ANIMS_ENTREE) == 44
    assert len(ANIMS_SORTIE) == 44
    assert len(ANIMS_INSISTANCE) == 14


def test_une_sortie_ne_peut_pas_etre_choisie_en_entree():
    """`fadeOut` en entrée ferait disparaître le widget au moment où il
    apparaît. Les deux menus ne se recouvrent que sur les options maison."""
    from bot.core.overlay_layout import (
        ANIM_AUCUNE, ANIM_DEFAUT, ANIMS_ENTREE, ANIMS_SORTIE)
    assert ANIMS_ENTREE & ANIMS_SORTIE == {ANIM_DEFAUT, ANIM_AUCUNE}
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_animations.py -q -k anim`
Attendu : `ImportError: cannot import name 'ANIMATIONS'`

- [ ] **Étape 3 : implémenter**

Dans `bot/core/overlay_layout.py`, **avant** la boucle de la tâche 1.1 :

```python
# ── Le catalogue d'animations ───────────────────────────────────────────────
#
# `animate.min.css` est déjà servi sur l'overlay et déjà utilisé par la galerie
# (`animation_in`/`animation_out` de `config.yaml`) : on ne charge rien de
# nouveau, on ouvre ce qui était réservé à un seul widget.
#
# Écrit ICI et servi au panneau par la route, jamais recopié en JavaScript :
# deux listes divergent à la première mise à jour de la bibliothèque. C'est le
# même parti pris que `LIBELLES` et `_ECHANTILLONS`, déjà servis par ce chemin.
#
# `glitch` est l'option MAISON et le défaut : c'est la rafale
# (`WallyGlitch.rafale`) qui encadre aujourd'hui l'entrée et la sortie de toutes
# les cartes. La garder en tête de menu est ce qui fait que personne ne voit son
# overlay changer.
#
# Les entrées et les sorties sont deux listes SÉPARÉES et disjointes : `fadeOut`
# proposé en entrée ferait disparaître la carte au moment où elle apparaît.
ANIM_DEFAUT = "glitch"
ANIM_AUCUNE = "aucune"

ANIMATIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "entree": {
        "Maison": (ANIM_DEFAUT, ANIM_AUCUNE),
        "Fondu": ("fadeIn", "fadeInDown", "fadeInDownBig", "fadeInLeft",
                  "fadeInLeftBig", "fadeInRight", "fadeInRightBig", "fadeInUp",
                  "fadeInUpBig", "fadeInTopLeft", "fadeInTopRight",
                  "fadeInBottomLeft", "fadeInBottomRight"),
        "Glissement": ("slideInDown", "slideInLeft", "slideInRight", "slideInUp"),
        "Zoom": ("zoomIn", "zoomInDown", "zoomInLeft", "zoomInRight", "zoomInUp"),
        "Rebond": ("bounceIn", "bounceInDown", "bounceInLeft", "bounceInRight",
                   "bounceInUp"),
        "Recul": ("backInDown", "backInLeft", "backInRight", "backInUp"),
        "Rotation": ("rotateIn", "rotateInDownLeft", "rotateInDownRight",
                     "rotateInUpLeft", "rotateInUpRight"),
        "Retournement": ("flipInX", "flipInY"),
        "Vitesse": ("lightSpeedInLeft", "lightSpeedInRight"),
        "Spéciales": ("rollIn", "jackInTheBox"),
    },
    "sortie": {
        "Maison": (ANIM_DEFAUT, ANIM_AUCUNE),
        "Fondu": ("fadeOut", "fadeOutDown", "fadeOutDownBig", "fadeOutLeft",
                  "fadeOutLeftBig", "fadeOutRight", "fadeOutRightBig",
                  "fadeOutUp", "fadeOutUpBig", "fadeOutTopLeft",
                  "fadeOutTopRight", "fadeOutBottomLeft", "fadeOutBottomRight"),
        "Glissement": ("slideOutDown", "slideOutLeft", "slideOutRight",
                       "slideOutUp"),
        "Zoom": ("zoomOut", "zoomOutDown", "zoomOutLeft", "zoomOutRight",
                 "zoomOutUp"),
        "Rebond": ("bounceOut", "bounceOutDown", "bounceOutLeft",
                   "bounceOutRight", "bounceOutUp"),
        "Recul": ("backOutDown", "backOutLeft", "backOutRight", "backOutUp"),
        "Rotation": ("rotateOut", "rotateOutDownLeft", "rotateOutDownRight",
                     "rotateOutUpLeft", "rotateOutUpRight"),
        "Retournement": ("flipOutX", "flipOutY"),
        "Vitesse": ("lightSpeedOutLeft", "lightSpeedOutRight"),
        "Spéciales": ("rollOut", "hinge"),
    },
    # Les « attention seekers » d'animate.css : ni entrée ni sortie, elles se
    # rejouent EN BOUCLE pendant que le widget est à l'écran. Sans ce troisième
    # menu, treize des quatre-vingt-dix-sept animations de la bibliothèque
    # resteraient inutilisables.
    "insistance": {
        "Maison": (ANIM_AUCUNE,),
        "Pulsation": ("pulse", "heartBeat", "flash"),
        "Secousse": ("shakeX", "shakeY", "headShake", "wobble", "jello"),
        "Élan": ("bounce", "swing", "tada", "rubberBand", "flip"),
    },
}


def _noms(menu: str) -> frozenset[str]:
    return frozenset(n for famille in ANIMATIONS[menu].values() for n in famille)


ANIMS_ENTREE = _noms("entree")
ANIMS_SORTIE = _noms("sortie")
ANIMS_INSISTANCE = _noms("insistance")
```

Puis compléter la boucle de distribution de la tâche 1.1 avec les trois champs
à choix, qui avaient besoin de ce catalogue :

```python
for _cle in widgets_qui_passent():
    # ... les trois `_poser` numériques de la tâche 1.1 ...
    _poser(_cle, "anim_entree", ANIM_DEFAUT, choix=ANIMS_ENTREE)
    _poser(_cle, "anim_sortie", ANIM_DEFAUT, choix=ANIMS_SORTIE)
    _poser(_cle, "anim_insistance", ANIM_AUCUNE, choix=ANIMS_INSISTANCE)

# La galerie avait déjà deux animations, dans `config.yaml`. Elle les garde,
# mais dans la scène. Pas d'insistance : elle a son propre minuteur et son
# propre flux, elle ne passe pas dans la file des cartes.
_poser("image", "anim_entree", ANIM_DEFAUT, choix=ANIMS_ENTREE)
_poser("image", "anim_sortie", ANIM_DEFAUT, choix=ANIMS_SORTIE)
```

Et compléter le test de la tâche 1.1 (`test_chaque_widget_qui_passe_porte_les_
champs_de_rythme`) avec les trois champs à choix, maintenant qu'ils existent :

```python
        for champ in ("duree", "delai", "anim_duree",
                      "anim_entree", "anim_sortie", "anim_insistance"):
```

- [ ] **Étape 4 : vérifier que les tests passent**

Run : `python3 -m pytest tests/test_overlay_animations.py -q`
Attendu : PASS. Si un compte tombe à côté, c'est la LISTE qu'on corrige en la
confrontant au CSS (`grep -o 'animate__[a-zA-Z]*' animate.min.css | sort -u`),
jamais le chiffre attendu du test.

- [ ] **Étape 5 : commit**

```bash
git add bot/core/overlay_layout.py tests/test_overlay_animations.py
git commit -m "feat(overlay): les 97 animations d'animate.css, écrites une seule fois"
```

---

### Tâche 1.3 — La fusion : borner, et laisser passer l'« auto »

**Fichiers :**
- Modifier : `bot/core/overlay_layout.py` (`_borner`, `_fusionner_element`)
- Test : `tests/test_overlay_layout.py`

**Interfaces consommées :** `CHAMPS_PROPRES`, `CHAMPS_CHOIX` (tâche 1.1),
`ANIMS_*` (tâche 1.2)
**Interfaces produites :** `_borner_ou_auto(valeur, mini, maxi, defaut) -> float`

- [ ] **Étape 1 : écrire le test qui échoue**

```python
def test_une_duree_a_zero_est_gardee_telle_quelle():
    """0 vaut AUTO : le serveur décide. Sans l'exception, `_borner` la
    remonterait au plancher de 2 s et la valeur LIVRÉE deviendrait une durée
    de deux secondes appliquée à tous les widgets, sur les trois scènes."""
    el = _scene_avec({"poll": {"duree": 0}})["poll"]
    assert el["duree"] == 0.0


def test_une_duree_hors_bornes_revient_dans_ses_bornes():
    assert _scene_avec({"poll": {"duree": 9000}})["poll"]["duree"] == 180.0
    assert _scene_avec({"poll": {"duree": 0.4}})["poll"]["duree"] == 2.0


def test_la_duree_du_rotateur_garde_ses_propres_bornes():
    """Même mot, autre grandeur : 120 s pour un média, 180 s pour un passage.
    Une table de bornes globale aurait fait dépendre la borne de l'ordre
    d'écriture."""
    assert _scene_avec({"rotator": {"duree": 150}})["rotator"]["duree"] == 120.0
    assert _scene_avec({"poll": {"duree": 150}})["poll"]["duree"] == 150.0


def test_le_rotateur_na_pas_dauto_sur_sa_duree():
    """Un rotateur à zéro seconde par média n'affiche rien : il n'y a personne
    derrière pour « décider », contrairement à un widget poussé par le bot."""
    assert _scene_avec({"rotator": {"duree": 0}})["rotator"]["duree"] == 1.0


def test_une_animation_inconnue_reprend_le_defaut():
    el = _scene_avec({"poll": {"anim_entree": "nawak"}})["poll"]
    assert el["anim_entree"] == "glitch"


def test_une_sortie_proposee_en_entree_est_refusee():
    """`fadeOut` en entrée ferait disparaître la carte au moment où elle
    apparaît. Les deux menus sont disjoints, la validation aussi."""
    el = _scene_avec({"poll": {"anim_entree": "fadeOut"}})["poll"]
    assert el["anim_entree"] == "glitch"


def test_un_champ_de_rythme_sur_un_element_qui_ne_le_porte_pas_est_ignore():
    """`avatar` n'a pas de durée d'affichage : il vit en permanence. Une clé
    envoyée par un JSON écrit à la main ne doit pas s'installer dans le
    modèle, sinon le panneau finirait par l'afficher."""
    assert "duree" not in _scene_avec({"avatar": {"duree": 30}})["avatar"]


def test_les_quatre_universels_se_bornent_comme_les_autres():
    el = _scene_avec({"meme": {"opacite": 5, "rotation": -900,
                               "miroir": "oui", "largeur_max": 99999}})["meme"]
    assert el["opacite"] == 1.0
    assert el["rotation"] == -45.0
    assert el["miroir"] is True
    assert el["largeur_max"] == 1920.0


def test_une_largeur_max_a_zero_reste_a_zero():
    assert _scene_avec({"meme": {"largeur_max": 0}})["meme"]["largeur_max"] == 0.0


def test_un_champ_present_a_null_reprend_son_defaut():
    """`.get(clé, défaut)` ne couvre PAS `clé: null` : la clé est présente, sa
    valeur `None` est rendue telle quelle. Piège déjà payé dans ce dépôt."""
    el = _scene_avec({"poll": {"duree": None, "anim_entree": None,
                               "miroir": None, "opacite": None}})["poll"]
    assert el["duree"] == 0.0
    assert el["anim_entree"] == "glitch"
    assert el["miroir"] is False
    assert el["opacite"] == 1.0


def test_le_defaut_livre_ne_change_rien_a_ce_qui_est_rendu():
    """LE test qui protège le live : une disposition livrée doit sortir de la
    fusion avec des valeurs qui reproduisent le comportement d'avant ce
    chantier — auto partout, glitch partout, rien d'incliné."""
    for scene in layout_par_defaut()["scenes"]:
        for cle, el in scene["elements"].items():
            assert el["opacite"] == 1.0 and el["rotation"] == 0.0
            assert el["miroir"] is False and el["largeur_max"] == 0.0
            if cle in ("rotator",):
                continue
            if "duree" in el:
                assert el["duree"] == 0.0, cle
            if "anim_entree" in el:
                assert el["anim_entree"] == "glitch", cle
                assert el["anim_sortie"] == "glitch", cle
                assert el["anim_duree"] == 0.15, cle
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_layout.py -q -k "auto or animation or universel or rythme or livre"`
Attendu : plusieurs `KeyError` / `AssertionError`.

- [ ] **Étape 3 : implémenter**

Ajouter à côté de `_borner` :

```python
def _borner_ou_auto(valeur, mini: float, maxi: float, defaut: float) -> float:
    """Comme `_borner`, mais ZÉRO passe au travers.

    Zéro n'est pas une valeur dans la plage : c'est le mot « auto », c'est-à-dire
    « laisse le serveur décider », qui est le comportement d'avant ce réglage.
    Le faire remonter au plancher transformerait la valeur LIVRÉE en une durée
    de deux secondes appliquée à tout l'overlay.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return defaut
    if valeur != valeur:                # NaN : json.loads l'accepte
        return defaut
    if float(valeur) == 0.0:
        return 0.0
    return _borner(valeur, mini, maxi, defaut)
```

Puis, dans `_fusionner_element`, ajouter les quatre universels au dictionnaire
`fusionne` et remplacer la boucle des champs propres :

```python
        "opacite": _borner(brut.get("opacite"), OPACITE_MIN, OPACITE_MAX,
                           defaut["opacite"]),
        "rotation": _borner(brut.get("rotation"), ROTATION_MIN, ROTATION_MAX,
                            defaut["rotation"]),
        "miroir": (bool(brut["miroir"]) if brut.get("miroir") is not None
                   else defaut["miroir"]),
        "largeur_max": _borner_ou_auto(brut.get("largeur_max"), LARGEUR_MIN,
                                       LARGEUR_MAX, defaut["largeur_max"]),
    }
    # Les réglages que cet élément-là est SEUL à porter. La table est indexée
    # par élément : `duree` ne veut pas dire la même chose ni ne se borne pareil
    # sur le rotateur (durée d'un média, 1–120 s) et sur un widget qui passe
    # (durée d'un passage, 2–180 s ou auto).
    #
    # `cle` est le nom de l'élément — il faut le passer à cette fonction, qui ne
    # le recevait pas : le `defaut` seul ne dit plus quelles bornes s'appliquent.
    for nom, (mini, maxi, auto) in CHAMPS_PROPRES.get(cle, {}).items():
        borne = _borner_ou_auto if auto else _borner
        fusionne[nom] = borne(brut.get(nom), mini, maxi, defaut[nom])
    # Les réglages à CHOIX : validés par appartenance, pas par bornes. Un nom
    # inconnu — une faute de frappe, une animation retirée d'animate.css, une
    # sortie proposée en entrée — reprend le défaut, comme partout ici.
    for nom, choix in CHAMPS_CHOIX.get(cle, {}).items():
        valeur = brut.get(nom)
        fusionne[nom] = valeur if isinstance(valeur, str) and valeur in choix \
            else defaut[nom]
    return fusionne
```

Adapter la signature : `def _fusionner_element(cle: str, brut, defaut: dict) -> dict:`
et son unique appelant (chercher `_fusionner_element(` dans le fichier — il est
appelé depuis la boucle sur `ELEMENTS` de `_fusionner_scene`, qui a déjà la clé
sous la main).

- [ ] **Étape 4 : vérifier que les tests passent**

Run : `python3 -m pytest tests/test_overlay_layout.py tests/test_overlay_layout_store.py tests/test_overlay_layout_maj.py -q`
Attendu : tout vert.

- [ ] **Étape 5 : commit**

```bash
git add bot/core/overlay_layout.py tests/test_overlay_layout.py
git commit -m "feat(overlay): borner les dix nouveaux réglages, et laisser passer l'auto"
```

---

### Tâche 1.4 — Servir le catalogue au panneau

**Fichiers :**
- Modifier : `bot/dashboard/routes/overlay.py:379-406` (`get_overlay_layout_admin`)
- Test : `tests/test_overlay_layout_routes.py` (existe)

**Interfaces produites :** le GET `/api/admin/overlay/layout` rend en plus
`animations` (le dict `ANIMATIONS`) et `portees`
(`{"champs_propres": {...}, "champs_choix": {...}}`, les deux tables sérialisées
avec des listes à la place des `frozenset`).

- [ ] **Étape 1 : écrire le test qui échoue**

```python
async def test_le_layout_admin_sert_le_catalogue_danimations(client_admin):
    """Servi et non recopié en JS : deux listes divergent à la première mise à
    jour d'animate.css. Même parti pris que `libelles` et `echantillons`, déjà
    servis par cette route."""
    r = await client_admin.get("/api/admin/overlay/layout")
    data = r.json()
    assert "glitch" in data["animations"]["entree"]["Maison"]
    assert "fadeOut" in data["animations"]["sortie"]["Fondu"]
    assert "pulse" in data["animations"]["insistance"]["Pulsation"]


async def test_le_layout_admin_dit_quel_element_porte_quel_champ(client_admin):
    """Le panneau ne doit pas deviner les portées : « durée d'affichage » sur
    un avatar est un réglage qui ment."""
    r = await client_admin.get("/api/admin/overlay/layout")
    portees = r.json()["portees"]
    assert "duree" in portees["champs_propres"]["poll"]
    assert "duree" not in portees["champs_propres"].get("avatar", {})
    assert "anim_entree" in portees["champs_choix"]["poll"]
```

Le fixture `client_admin` est celui déjà utilisé par
`tests/test_overlay_layout_routes.py` — le reprendre tel quel, ne pas en créer
un second.

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_layout_routes.py -q -k "catalogue or portee"`
Attendu : `KeyError: 'animations'`

- [ ] **Étape 3 : implémenter**

Dans `bot/dashboard/routes/overlay.py`, importer `ANIMATIONS`, `CHAMPS_CHOIX`,
`CHAMPS_PROPRES` depuis `bot.core.overlay_layout`, et compléter le `return` de
`get_overlay_layout_admin` :

```python
    return {**layout, "libelles": LIBELLES, "tailles": _tailles_media(request),
            "echantillons": _ECHANTILLONS, "maj": maj,
            # Le catalogue d'animations et les portées voyagent avec le layout,
            # pour la raison de toujours : deux tables divergent au premier
            # widget ajouté. Le panneau fait déjà cet appel au chargement.
            "animations": ANIMATIONS,
            "portees": {
                # `frozenset` ne se sérialise pas en JSON, et l'ordre d'un set
                # n'est pas stable d'un boot à l'autre : trié, pour que deux
                # réponses identiques le soient vraiment.
                "champs_propres": CHAMPS_PROPRES,
                "champs_choix": {cle: {nom: sorted(choix)
                                       for nom, choix in champs.items()}
                                 for cle, champs in CHAMPS_CHOIX.items()},
            }}
```

Vérifier que le panneau retire bien ces deux clés avant de renvoyer le modèle au
PUT : chercher `HORS_MODELE` dans `overlay_admin.js` et y ajouter `"animations"`
et `"portees"`. Sans ça, le PUT renverrait le catalogue dans le layout et le
store le rangerait en base.

- [ ] **Étape 4 : vérifier que les tests passent**

Run : `python3 -m pytest tests/test_overlay_layout_routes.py tests/test_overlay_admin_import_export.py -q`

- [ ] **Étape 5 : phase 1 close — vérification complète et publication**

```bash
python3 -m pytest tests/ -q
python3 scripts/lint_types.py
python3 scripts/lint_silences.py
git add -A
git commit -m "feat(overlay): dix réglages par widget dans le modèle (phase 1/5)"
GIT_HASH=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  docker compose up -d --build wally
git push public feat/site-redesign-arcade:main
```

Puis vérifier en prod que le GET répond avec le catalogue :
`curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/admin/overlay/layout | python3 -c "import json,sys; d=json.load(sys.stdin); print(sorted(d['animations']), len(d['portees']['champs_propres']))"`
Attendu : `['entree', 'insistance', 'sortie'] 36` — les 33 widgets qui passent,
plus `bubble`, `image` et `rotator`, seuls autres porteurs d'un champ borné.
Si le compte diffère, c'est une portée qui manque ou une qui déborde : le lire
et le comprendre, jamais ajuster le chiffre attendu pour faire passer.

**⛔ Feu vert de l'owner avant la phase 2.**

---

# Phase 2 — Le rendu visuel

`opacite`, `rotation`, `miroir`, `largeur_max` deviennent visibles. Bind-mount :
pas de rebuild, un rechargement du navigateur suffit.

### Tâche 2.1 — `styleDepuisElement()` compose les quatre universels

> **Corrigé à l'exécution (2026-08-21).** Cette tâche prévoyait une règle CSS
> `[data-element] > *` : impossible, `body.widget-on #bubble` et
> `body[data-side="right"] #avatar-slot` la battent en spécificité. Voir §D5 du
> design, corrigé lui aussi. La rotation se compose désormais dans le
> `transform` du conteneur, encadrée d'un aller-retour de recentrage dont le
> sens suit le coin d'ancrage. Aucun fichier CSS n'est touché.

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_layout.js` (`placer`)
- Modifier : `bot/dashboard/static/overlay.html` (la règle `[data-element] > *`)
- Test : `tests/test_overlay_layout_css.py`

- [ ] **Étape 1 : écrire le test qui échoue**

```python
def test_placer_pose_les_quatre_reglages_visuels():
    """Le contrôle est textuel faute de navigateur en test — mais il attrape
    le vrai risque : un champ ajouté au modèle que `placer()` ne lit pas, donc
    un réglage qui ne fait rien."""
    js = (_STATIC / "overlay_layout.js").read_text(encoding="utf-8")
    for marqueur in ("opacite", "--ovl-rotation", "--ovl-miroir", "largeur_max"):
        assert marqueur in js, f"absent de placer() : {marqueur}"


def test_la_rotation_ne_passe_pas_par_le_transform_du_conteneur():
    """Le conteneur porte `scale() translate()` avec un transform-origin sur un
    COIN : un `rotate()` en bout de chaîne ferait tourner l'élément autour de
    son point d'ancrage, donc le DÉPLACERAIT en l'inclinant."""
    js = (_STATIC / "overlay_layout.js").read_text(encoding="utf-8")
    debut = js.index("function styleDepuisElement")
    fin = js.index("function placer")
    assert "rotate(" not in js[debut:fin]


def test_la_regle_css_de_rotation_tourne_autour_du_centre():
    html = (_STATIC / "overlay.html").read_text(encoding="utf-8")
    assert "--ovl-rotation" in html
    assert "--ovl-miroir" in html
    bloc = html[html.index("[data-element] > *"):]
    assert "transform-origin: center" in bloc[:400]
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_layout_css.py -q -k "visuel or rotation or centre"`

- [ ] **Étape 3 : implémenter**

Dans `overlay_layout.js`, `placer()` — **après** la pose du style de placement,
sans toucher à `styleDepuisElement` :

```js
  /** Applique un élément du modèle à un nœud. */
  function placer(noeud, el) {
    if (!noeud || !el) return;
    // ... corps existant, inchangé ...
    noeud.style.display = el.hidden ? "none" : "";

    // ── Les quatre réglages visuels ──────────────────────────────────────
    //
    // L'opacité en direct sur le conteneur : rien ne s'y oppose, et elle doit
    // emporter la carte ET son ombre.
    noeud.style.opacity = (el.opacite === undefined || el.opacite === null)
      ? "" : String(el.opacite);

    // La rotation et le miroir passent par des VARIABLES, appliquées par le CSS
    // à l'enfant. Pas par le `transform` de ce nœud-ci : il porte
    // `scale() translate()` dans un ordre payé cher, avec un `transform-origin`
    // posé sur un COIN. Un `rotate()` en bout de chaîne ferait tourner
    // l'élément autour de son point d'ancrage — il se déplacerait à l'écran en
    // même temps qu'il s'incline, ce que personne ne demande en réglant une
    // inclinaison.
    noeud.style.setProperty("--ovl-rotation", (el.rotation || 0) + "deg");
    noeud.style.setProperty("--ovl-miroir", el.miroir ? "-1" : "1");

    // La largeur maximale REMPLACE le `max-width: 92vw` du conteneur. À zéro,
    // on rend la main au CSS — et non « 0px », qui écraserait la carte.
    // Exprimée en pixels du canvas de référence, elle suit l'échelle comme le
    // reste : c'est le `transform: scale()` du conteneur qui s'en charge.
    noeud.style.maxWidth = (el.largeur_max > 0) ? el.largeur_max + "px" : "";
  }
```

Dans `overlay.html`, étendre la règle **existante** (chercher
`[data-element] > * { grid-area: pile; }`) :

```css
    /* La rotation et le miroir réglés par scène. Sur l'ENFANT et non sur le
       conteneur : celui-ci porte le placement (`scale() translate()`) avec un
       `transform-origin` sur un coin, et une rotation composée là-dessus
       tournerait l'élément autour de son point d'ancrage.
       Les valeurs par défaut (0deg, 1) rendent la règle inerte tant que
       personne n'a réglé : aucun overlay ne change au rechargement. */
    [data-element] > * {
      grid-area: pile;
      transform: rotate(var(--ovl-rotation, 0deg)) scaleX(var(--ovl-miroir, 1));
      transform-origin: center;
    }
```

- [ ] **Étape 4 : vérifier au navigateur, pas seulement en test**

⚠️ **C'est l'étape qui compte.** `avatar` et `rotator` ont des enfants directs
qui portent déjà un `transform` : la nouvelle règle peut l'écraser. Un test vert
ne prouve pas qu'un overlay rend juste.

```bash
python3 -m pytest tests/test_overlay_layout_css.py -q
```

Puis, sur `https://heywally.fr/overlay` (le navigateur MCP ne joint pas
`127.0.0.1:8080`) :
1. l'avatar est à sa place, à sa taille, et respire comme avant ;
2. le rotateur enchaîne ses memes sans saut ;
3. dans la console : `document.querySelector('[data-element="meme"]').style.setProperty('--ovl-rotation','15deg')`
   → la carte s'incline **sans se déplacer** ;
4. `…style.setProperty('--ovl-miroir','-1')` → elle se retourne sur place.

5. **Dans le panneau de mise en scène**, l'aperçu vivant doit montrer les
   quatre réglages : il rend la page dans une iframe, donc il hérite de la règle
   CSS — mais c'est à confirmer à l'œil, pas à supposer. Régler l'opacité de
   `meme` à 0,3 dans l'inspecteur : le repère ET l'aperçu doivent pâlir.

Si l'avatar ou le rotateur casse : leur donner un wrapper `<div class="ovl-tf">`
et viser `[data-element] > .ovl-tf` — le noter dans le commit, c'est un piège
qui se repaiera sinon.

- [ ] **Étape 5 : commit**

```bash
git add bot/dashboard/static/overlay_layout.js bot/dashboard/static/overlay.html \
        tests/test_overlay_layout_css.py
git commit -m "feat(overlay): opacité, inclinaison, miroir et largeur max sur les 37 éléments"
git push public feat/site-redesign-arcade:main
```

**⛔ Feu vert de l'owner avant la phase 3.**

---

# Phase 3 — Le rendu comportemental

### Tâche 3.1 — La durée réglée, et ses trois exceptions

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay.js` (`showWidget`, autour de la ligne 1836)
- Créer : `tests/test_overlay_duree_reglee.py`

- [ ] **Étape 1 : écrire le test qui échoue**

Créer `tests/test_overlay_duree_reglee.py` :

```python
"""La durée d'affichage réglée par scène, et ce qu'elle ne doit PAS couper.

Le contrôle est textuel : il n'y a pas de navigateur en test ici. Il vise donc
ce qui se vérifie ainsi — que les trois exceptions sont présentes et sortent
AVANT la lecture du réglage. Le comportement, lui, se vérifie à l'écran.
"""
from pathlib import Path

_JS = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
       / "overlay.js").read_text(encoding="utf-8")


def test_la_duree_reglee_lemporte_sur_celle_du_serveur():
    """Le choix rendu : le streamer décide. Un repli sur `params.duration`
    seulement n'aurait quasiment jamais rien fait, tous les événements portant
    déjà une durée."""
    assert "dureeReglee" in _JS


def test_une_partie_en_cours_sort_avant_la_duree_reglee():
    """`sticky` est posé sur un pendu en cours et un sondage ouvert. Une durée
    de 5 s couperait la partie sous les yeux du chat."""
    i_sticky = _JS.index("params.sticky === true")
    i_duree = _JS.index("dureeReglee")
    assert i_sticky < i_duree, "la garde sticky doit précéder la lecture"


def test_le_clip_et_le_spam_de_popups_gardent_leur_mecanique():
    """Le clip sort sur la fin de sa VIDÉO, le spam sur la fin d'un PLAN de
    fenêtres calculé. Une durée posée par-dessus couperait l'un au milieu et
    ferait tomber l'écran bleu de l'autre à côté de son plan."""
    assert "DUREE_INTERNE" in _JS
    for kind in ('"clip"', '"virus_popup"'):
        assert kind in _JS[_JS.index("DUREE_INTERNE"):_JS.index("DUREE_INTERNE") + 400]
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_duree_reglee.py -q`
Attendu : `ValueError: substring not found`

- [ ] **Étape 3 : implémenter**

Dans `overlay.js`, près des constantes du haut :

```js
  // Les widgets dont la sortie est décidée par leur PROPRE mécanique, et que
  // la durée réglée dans la scène ne doit donc pas piloter :
  //   · `clip` sort sur la fin de la vidéo (`video.duration + 5`) — une durée
  //     posée par-dessus couperait le clip au milieu ;
  //   · `virus_popup` reçoit sa durée en ENTRÉE d'un plan de fenêtres calculé
  //     (`WallyVirus.rythme` → `fenetres`) : elle y est déjà remplacée, plus
  //     haut, et un second minuteur ferait tomber l'écran bleu de nettoyage à
  //     côté de son plan.
  const DUREE_INTERNE = new Set(["clip", "virus_popup"]);
```

Puis, dans `showWidget`, remplacer la ligne du minuteur :

```js
    // Une partie en cours ne s'efface pas toute seule : le pendu doit rester
    // sous les yeux du chat tant qu'on y joue. (garde existante, inchangée)
    if (params.sticky === true) return;

    // La durée réglée pour CE widget dans CETTE scène l'emporte sur celle que
    // le serveur envoie : c'est le streamer qui décide de son habillage. Zéro
    // vaut « auto », c'est-à-dire le comportement d'avant ce réglage — et c'est
    // la valeur livrée, pour que rien ne change tant que personne n'y touche.
    const reg = reglages[kind] || {};
    const dureeReglee = DUREE_INTERNE.has(kind) ? 0 : (Number(reg.duree) || 0);
    // Le serveur décide (animation + lecture) ; ce plafond n'est qu'un garde-fou.
    // 180 s et non 30 : le serveur émet jusqu'à 124 s (sondage de 120 s + 4).
    const seconds = dureeReglee > 0
      ? dureeReglee
      : Math.min(180, Math.max(2, Number(params.duration) || 12));
```

Et, pour `virus_popup`, à l'endroit où sa durée est calculée (autour de la ligne
901) :

```js
        // Le réglage de scène remplace `params.seconds` en ENTRÉE du plan, il
        // ne se superpose pas au minuteur : le rythme, le nombre de fenêtres et
        // l'écran bleu de nettoyage se calculent tous depuis cette valeur.
        const regle = Number((reglages.virus_popup || {}).duree) || 0;
        const duree = Math.max(3, Math.min(300, regle
          || Number(p.seconds) || window.WallyVirus.dureeSelonStock(medias.length)));
```

- [ ] **Étape 4 : vérifier**

Run : `python3 -m pytest tests/test_overlay_duree_reglee.py tests/test_overlay_persistance_sondage.py tests/test_overlay_clip.py tests/test_overlay_hangman_persistance.py -q`

Puis à l'écran, sur `https://heywally.fr/overlay` : régler `poll` à 6 s dans le
panneau, publier, lancer un sondage depuis le ▶ → il sort à 6 s. Régler `hangman`
à 5 s, lancer une partie → **elle reste**.

- [ ] **Étape 5 : commit**

```bash
git add bot/dashboard/static/overlay.js tests/test_overlay_duree_reglee.py
git commit -m "feat(overlay): la durée d'affichage se règle par widget et par scène"
```

---

### Tâche 3.2 — Le délai, les animations d'entrée, de sortie et d'insistance

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay.js` (`renderWidget`, `showWidget`, la
  sortie glitch autour de la ligne 1850)
- Test : `tests/test_overlay_duree_reglee.py` (compléter)

- [ ] **Étape 1 : écrire le test qui échoue**

```python
def test_le_relais_suit_la_duree_danimation_reglee():
    """`playNext` était rappelé après `GLITCH_MS` en dur (150 ms). Avec une
    sortie d'une seconde, la carte suivante entrerait pendant que la précédente
    finit de partir : deux cartes pleines l'une sur l'autre, illisibles."""
    assert "GLITCH_MS," not in _JS.split("relaisTimer = setTimeout(playNext")[1][:40]
    assert "sortieMs" in _JS


def test_glitch_reste_le_defaut():
    """Personne ne doit voir son overlay changer parce qu'on a rendu
    l'animation réglable."""
    assert '"glitch"' in _JS


def test_linsistance_se_rejoue_en_boucle():
    assert "animate__infinite" in _JS
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_duree_reglee.py -q -k "relais or glitch or insistance"`

- [ ] **Étape 3 : implémenter**

Ajouter un utilitaire au-dessus de `showWidget` :

```js
  /** Les réglages d'animation de CE widget dans CETTE scène, avec leurs replis.
   *
   *  Les replis reproduisent le comportement d'avant ce réglage : la rafale de
   *  glitch, et sa durée (`GLITCH_MS`). Un layout rangé avant ce chantier n'a
   *  aucun de ces champs — il doit rendre exactement ce qu'il rendait.
   */
  function animDe(kind) {
    const r = reglages[kind] || {};
    const s = Number(r.anim_duree);
    return {
      entree: r.anim_entree || "glitch",
      sortie: r.anim_sortie || "glitch",
      insistance: r.anim_insistance || "aucune",
      ms: (s > 0 ? s : GLITCH_MS / 1000) * 1000,
    };
  }

  /** Pose une animate.css sur un nœud, et rend la durée à attendre.
   *  `glitch` et `aucune` ne sont pas des classes : le premier est la rafale
   *  maison, le second ne fait rien. */
  function animer(noeud, nom, ms, boucle) {
    if (!noeud || nom === "aucune" || nom === "glitch") return;
    noeud.style.setProperty("--animate-duration", (ms / 1000) + "s");
    noeud.classList.add("animate__animated", "animate__" + nom);
    if (boucle) noeud.classList.add("animate__infinite");
  }
```

Dans `renderWidget`, après `box.classList.add("visible")` :

```js
    // L'entrée réglée pour ce widget. `glitch` — le défaut — laisse en place la
    // transition CSS de `.visible`, qui est ce qui se joue aujourd'hui.
    const anim = animDe(kind);
    if (!refresh) animer(box, anim.entree, anim.ms, false);
    // L'insistance se rejoue en boucle pendant tout l'affichage. Posée sur un
    // enfant et non sur la carte : la carte porte déjà l'animation d'entrée, et
    // deux `animation` sur le même nœud se remplacent au lieu de se cumuler.
    if (anim.insistance !== "aucune") {
      animer(box.firstElementChild, anim.insistance, anim.ms, true);
    }
```

Le **délai** : dans `showWidget`, avant le montage, si `reg.delai > 0`, différer
l'insertion — en enregistrant le minuteur dans `minuteurs` pour qu'un `clearAll`
l'annule (un widget qui apparaît après avoir été effacé est le défaut classique
de ce fichier) :

```js
    // Le délai réglé décale l'apparition, pas la sortie : le minuteur de durée
    // ne part qu'une fois la carte montée. Suivi dans `minuteurs` comme le
    // reste — un widget qui surgit après un `clear` est un fantôme, et ce
    // fichier en a déjà payé plusieurs.
    const delai = Number((reglages[kind] || {}).delai) || 0;
    // `_delai_consomme` est ce qui empêche la boucle : le second passage porte
    // le drapeau et tombe droit dans le montage.
    if (delai > 0 && !refresh && !params._delai_consomme) {
      clearTimeout(minuteurs.get("delai:" + kind));
      minuteurs.set("delai:" + kind, setTimeout(() => {
        minuteurs.delete("delai:" + kind);
        showWidget(kind, { ...params, _delai_consomme: true });
      }, delai * 1000));
      return;
    }
```

Vérifier que `clearAll()` / `clearWidgets()` vident bien `minuteurs` en entier,
clés `delai:` comprises : ils itèrent déjà dessus, mais **relire le code avant
d'écrire**. Un widget qui surgit après un `clear` est un fantôme, et ce fichier
en a déjà payé plusieurs.

La **sortie** : remplacer le bloc `WallyGlitch.rafale(...)` du minuteur par un
aiguillage, et faire suivre le relais :

```js
      box.classList.add("leaving");
      const sortieMs = anim.ms;
      if (anim.sortie === "glitch") {
        WallyGlitch.rafale(box, { ...GLITCH, decalage: 22 }).then(() => {
          WallyGlitch.nettoyer(box);
          box.classList.remove("visible");
        });
      } else {
        box.classList.remove("animate__animated", "animate__" + anim.entree);
        animer(box, anim.sortie, sortieMs, false);
        setTimeout(() => box.classList.remove("visible"), sortieMs);
      }
      // Le relais suit l'animation RÉELLE et non `GLITCH_MS` en dur : avec une
      // sortie d'une seconde, la carte suivante entrait pendant que la
      // précédente finissait de partir — deux cartes pleines l'une sur l'autre.
      relaisTimer = setTimeout(playNext, sortieMs);
      setTimeout(() => disposeWidget(box), sortieMs + 260);
```

- [ ] **Étape 4 : vérifier**

Run : `python3 -m pytest tests/test_overlay_duree_reglee.py tests/test_overlay_cancel.py tests/test_overlay_widget_reload_race.py tests/test_overlay_ecourter.py -q`

Puis à l'écran : régler `meme` sur entrée `zoomInDown`, sortie `hinge`,
`anim_duree` 1 s, insistance `pulse`. Lancer un meme depuis le ▶ → il tombe en
zoom, pulse pendant l'affichage, et part en `hinge`. Enchaîner deux memes → le
second n'entre **pas** avant que le premier ait fini de partir.

- [ ] **Étape 5 : commit**

```bash
git add bot/dashboard/static/overlay.js tests/test_overlay_duree_reglee.py
git commit -m "feat(overlay): délai, animations d'entrée, de sortie et d'insistance par widget"
```

---

### Tâche 3.3 — La bulle et la galerie

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay.js` (`say` ligne ~100, `IMAGE.montrer`
  ligne ~2300)
- Test : `tests/test_overlay_duree_reglee.py`

- [ ] **Étape 1 : écrire le test qui échoue**

```python
def test_la_bulle_lit_la_duree_reglee_dans_la_scene():
    say = _JS[_JS.index("function say("):_JS.index("function say(") + 900]
    assert "reglages.bubble" in say


def test_la_galerie_lit_ses_quatre_reglages_dans_la_scene():
    """Ils vivaient dans config.yaml, globalement. Deux autorités sur la même
    question, c'est la signature de défaut que ce dépôt traque."""
    montrer = _JS[_JS.index("function montrer(data)"):]
    bloc = montrer[:1200]
    for champ in ("duree", "anim_entree", "anim_sortie", "anim_duree"):
        assert champ in bloc, f"la galerie ignore {champ}"
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_duree_reglee.py -q -k "bulle or galerie"`

- [ ] **Étape 3 : implémenter**

Dans `say()` :

```js
      // La durée réglée pour la bulle dans cette scène l'emporte sur celle que
      // le serveur envoie. Zéro vaut « auto » : le repli de 3 s d'avant ce
      // réglage, qui est la valeur livrée.
      const regBulle = Number((reglages.bubble || {}).duree) || 0;
      const secondes = regBulle || Math.max(1, durationSeconds || 3);
      hideTimer = setTimeout(popBubble, secondes * 1000);
```

Dans `IMAGE.montrer(data)`, remplacer les quatre lectures de `data.*` :

```js
      // Les quatre réglages viennent désormais de la SCÈNE et non de
      // `config.yaml` : la galerie se règle comme tous les autres widgets, et
      // par scène. `data.*` reste en repli le temps qu'un layout migré arrive.
      const reg = reglages.image || {};
      const animIn = reg.anim_entree && reg.anim_entree !== "glitch"
        ? reg.anim_entree : (data.animation_in || "fadeIn");
      const animOut = reg.anim_sortie && reg.anim_sortie !== "glitch"
        ? reg.anim_sortie : (data.animation_out || "fadeOut");
      const duree = ((Number(reg.duree) || 0)
        || Number(data.display_duration) || 15) * 1000;
      const animS = Number(reg.anim_duree) > 0
        ? Number(reg.anim_duree) : (Number(data.animation_duration) || 1);
```

- [ ] **Étape 4 : vérifier**

Run : `python3 -m pytest tests/ -q -k overlay`

Puis à l'écran : régler `bubble` à 8 s → une réplique reste 8 s. Lancer `!image`
avec `image` réglé sur `bounceInLeft` → l'image entre par la gauche.

- [ ] **Étape 5 : phase 3 close — vérification complète et publication**

```bash
python3 -m pytest tests/ -q
python3 scripts/lint_types.py
python3 scripts/lint_silences.py
git add -A
git commit -m "feat(overlay): la bulle et la galerie lisent leurs réglages de scène (phase 3/5)"
git push public feat/site-redesign-arcade:main
```

**⛔ Feu vert de l'owner avant la phase 4.**

---

# Phase 4 — Le panneau

### Tâche 4.1 — Deux natures de champ de plus : booléenne et à choix

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_admin.js` (`CHAMPS_PROPRES` ~137,
  `champNumerique` ~4993, la construction de l'inspecteur ~5086)
- Modifier : `bot/dashboard/static/style.css`
- Test : `tests/test_overlay_admin_cadence.py` (existe, couvre déjà les champs
  propres du rotateur)

- [ ] **Étape 1 : écrire le test qui échoue**

```python
def test_le_panneau_ne_recopie_plus_les_bornes_du_serveur():
    """La table locale a été remplacée par ce que sert le GET (`portees`).
    Deux tables divergeaient au premier champ ajouté — c'est le reproche
    auquel ce chantier répond."""
    js = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")
    assert "etat.portees" in js


def test_linspecteur_sait_construire_les_trois_natures_de_champ():
    js = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")
    for fabrique in ("champNumerique", "champBooleen", "champChoix"):
        assert "function " + fabrique in js
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_admin_cadence.py -q -k "bornes or natures"`

- [ ] **Étape 3 : implémenter**

1. Remplacer la constante locale `CHAMPS_PROPRES` (lignes ~135-142) par une
   lecture d'`etat.portees`, posée au chargement à côté d'`etat.libelles`.
   Garder dans le JS **seulement** ce que le serveur ne peut pas dire : le
   libellé français, le pas, et l'infobulle.

```js
  // Ce que le SERVEUR ne peut pas dire : comment un champ se nomme et se
  // manipule à l'écran. Les bornes, les choix et les portées, elles, viennent
  // du GET (`portees`, `animations`) — deux tables divergeaient au premier
  // champ ajouté.
  //
  // `nature` : "nombre" (par défaut), "booleen", "choix". Le troisième nomme
  // le menu d'animations dont il tire ses options.
  const CHAMPS = {
    opacite:   { label: "Opacité", pas: 0.05,
                 aide: "La transparence de l'élément. 1 = opaque." },
    rotation:  { label: "Inclinaison (°)", pas: 1,
                 aide: "L'élément s'incline autour de son centre ; il ne se "
                     + "déplace pas." },
    miroir:    { label: "Miroir", nature: "booleen",
                 aide: "Retourne l'élément de gauche à droite." },
    largeur_max: { label: "Largeur max (px)", pas: 10, auto: "Auto",
                 aide: "En pixels du canvas 1920. Auto = la largeur du "
                     + "contenu, plafonnée à 92 % de l'écran." },
    duree:     { label: "Durée (s)", pas: 0.5, auto: "Auto",
                 aide: "Combien de temps l'élément reste à l'écran. Auto = "
                     + "c'est Wally qui décide, comme avant. Une partie en "
                     + "cours n'est jamais coupée." },
    pause:     { label: "Pause (s)", pas: 0.5,
                 aide: "Combien de temps la zone reste vide entre deux memes. "
                     + "0 les enchaîne." },
    delai:     { label: "Délai (s)", pas: 0.5,
                 aide: "Combien de temps on attend avant de le faire "
                     + "apparaître." },
    anim_duree: { label: "Durée d'anim. (s)", pas: 0.05,
                 aide: "La durée de l'entrée ET de la sortie. La carte "
                     + "suivante attend la fin." },
    anim_entree: { label: "Entrée", nature: "choix", menu: "entree",
                 aide: "Comment l'élément apparaît." },
    anim_sortie: { label: "Sortie", nature: "choix", menu: "sortie",
                 aide: "Comment l'élément s'en va." },
    anim_insistance: { label: "Insistance", nature: "choix", menu: "insistance",
                 aide: "Un effet rejoué en boucle pendant tout l'affichage." },
  };
```

2. `champBooleen(champ, cle)` : une case à cocher qui écrit par le **même**
   `ecrire()` que les autres — la garde du verrouillage est au point d'écriture,
   et elle doit le rester.

3. `champChoix(champ, cle)` : un bouton qui affiche le nom courant et ouvre le
   sélecteur (tâche 4.2). Il écrit lui aussi par `ecrire()`.

4. `ecrire()` accepte désormais des valeurs non numériques : y ajouter
   l'aiguillage sur la nature avant `borner()` — un booléen et une chaîne ne se
   bornent pas.

5. La construction des champs propres (ligne ~5086) itère sur `etat.portees`
   au lieu de la constante locale, et crée la fabrique correspondant à la
   nature. Le mécanisme qui les cache tant que leur élément n'est pas le
   principal de la sélection est **conservé tel quel**.

6. Un champ dont `auto` est renseigné affiche « Auto » à la place de `0` — sans
   ça le streamer lit « durée : 0 » et comprend « ne s'affiche pas ».

- [ ] **Étape 4 : vérifier**

Run : `python3 -m pytest tests/ -q -k overlay_admin`
Puis `node --check bot/dashboard/static/overlay_admin.js`

⚠️ `node --check` ne voit pas les TDZ, et un `throw` dans un `mount()` casse tous
les montages suivants. **Ouvrir le panneau dans le navigateur** et vérifier que
les sept onglets montent encore, pas seulement celui-ci.

- [ ] **Étape 5 : commit**

```bash
git add bot/dashboard/static/overlay_admin.js bot/dashboard/static/style.css \
        tests/test_overlay_admin_cadence.py
git commit -m "feat(overlay): l'inspecteur sait éditer un booléen et un choix"
```

---

### Tâche 4.2 — Le sélecteur d'animation

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_admin.js`
- Modifier : `bot/dashboard/static/style.css`
- Test : `tests/test_overlay_admin_selection.py` (compléter)

- [ ] **Étape 1 : écrire le test qui échoue**

```python
def test_le_selecteur_danimation_cherche_et_previsualise():
    js = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")
    assert "function ouvrirSelecteurAnim" in js
    # La recherche porte sur le nom AFFICHÉ et sur la famille : on connaît
    # l'un ou l'autre selon qu'on cherche « fondu » ou « fadeInUp ».
    assert "animate__" in js, "l'aperçu doit poser la vraie classe"


def test_le_selecteur_choisit_son_cote_a_louverture():
    """Piège déjà payé sur ce panneau : un panneau volant ancré en dur sort de
    l'écran une fois sur deux, la barre passant à la ligne selon la largeur."""
    js = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")
    bloc = js[js.index("function ouvrirSelecteurAnim"):]
    assert "getBoundingClientRect" in bloc[:2500]
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_admin_selection.py -q -k selecteur`

- [ ] **Étape 3 : implémenter**

`ouvrirSelecteurAnim(bouton, menu, valeurCourante, onChoix)` :

- construit un panneau volant depuis `etat.animations[menu]` (servi par le GET) ;
- une barre de recherche en tête, qui filtre sur le nom **et** sur la famille ;
- les familles en en-têtes, l'entrée courante marquée ;
- au survol d'une entrée, une vignette rejoue l'animation : on lui pose
  `animate__animated animate__<nom>`, on retire les classes à `animationend`
  **et** sur un minuteur de secours — `animationcancel` ne déclenche pas
  `animationend`, et si `animate.min.css` n'était pas servi l'événement
  n'arriverait jamais. Ce piège est déjà écrit dans `overlay.js`, ligne ~2330 ;
- le côté (gauche / droite) et le sens (haut / bas) se choisissent à
  l'**ouverture** par `getBoundingClientRect()` ;
- `Échap` et un clic à l'extérieur ferment ; le focus revient au bouton.

⚠️ Vérifier qu'aucun ancêtre du bouton ne porte `overflow: hidden` : il rognerait
le menu. Piège déjà payé sur ce panneau — si c'est le cas, monter le panneau
dans `document.body` avec une position fixe calculée.

- [ ] **Étape 4 : vérifier**

Run : `python3 -m pytest tests/ -q -k overlay_admin` puis
`node --check bot/dashboard/static/overlay_admin.js`

Au navigateur : sélectionner `meme`, ouvrir « Entrée », taper « zoom » → 5
résultats, survoler `zoomInDown` → la vignette tombe. Choisir → le bouton porte
le nom, le compteur de brouillon monte de 1.

- [ ] **Étape 5 : commit**

```bash
git add bot/dashboard/static/overlay_admin.js bot/dashboard/static/style.css \
        tests/test_overlay_admin_selection.py
git commit -m "feat(overlay): choisir une animation parmi 97, avec recherche et aperçu"
```

---

### Tâche 4.3 — Le journal des différences passe sur une table

**Fichiers :**
- Modifier : `bot/dashboard/static/overlay_admin.js` (`decrireElement` ~1694)
- Test : `tests/test_overlay_admin_diff_antenne.py` (existe)

- [ ] **Étape 1 : écrire le test qui échoue**

```python
def test_les_dix_nouveaux_reglages_apparaissent_dans_ce_qui_a_bouge():
    """Un réglage qui change sans se dire dans le pied du panneau se publie
    sans avoir été vu. C'est précisément ce que ce journal existe pour
    empêcher."""
    js = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")
    bloc = js[js.index("function decrireElement"):js.index("function diffScene")]
    for champ in ("opacite", "rotation", "miroir", "largeur_max", "delai",
                  "anim_entree", "anim_sortie", "anim_duree", "anim_insistance"):
        assert champ in bloc, f"{champ} ne se dit pas dans le journal"


def test_un_champ_absent_des_deux_cotes_ne_produit_aucune_ligne():
    """« durée undefined → 9 s » annoncerait une modification que personne n'a
    faite. La règle existait pour `duree`/`pause`, elle doit survivre au
    passage sur table."""
    js = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")
    bloc = js[js.index("function decrireElement"):js.index("function diffScene")]
    assert "undefined" in bloc
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_admin_diff_antenne.py -q -k "nouveaux or absent"`

- [ ] **Étape 3 : implémenter**

Remplacer les `if` de `duree` et `pause` par une table, en **gardant** les champs
qui se disent autrement (`hidden`, `locked`, `solo`, `wally_visible`, `anchor`)
en écriture manuelle — c'est la raison d'être du commentaire actuel : un booléen
n'a pas de « avant → après » lisible.

```js
  // Les champs qui se disent tous de la même façon : « libellé avant → après ».
  // Écrits en table et non en `if` empilés — ils sont onze depuis que chaque
  // widget porte ses propres réglages, et la liste continuera de grandir.
  //
  // La règle qui compte est conservée : un champ absent DES DEUX CÔTÉS ne
  // produit aucune ligne. Un modèle rangé avant l'ajout d'un champ ne le porte
  // pas, et « durée undefined → 9 s » annoncerait une modification que personne
  // n'a faite.
  const DITS = [
    ["opacite", "opacité", unNombre],
    ["rotation", "inclinaison", (v) => unNombre(v) + "°"],
    ["largeur_max", "largeur max", (v) => v > 0 ? unNombre(v) + " px" : "auto"],
    ["duree", "durée", (v) => v > 0 ? uneSeconde(v) + " s" : "auto"],
    ["pause", "pause", (v) => uneSeconde(v) + " s"],
    ["delai", "délai", (v) => uneSeconde(v) + " s"],
    ["anim_duree", "durée d'anim.", (v) => uneSeconde(v) + " s"],
    ["anim_entree", "entrée", String],
    ["anim_sortie", "sortie", String],
    ["anim_insistance", "insistance", String],
  ];
```

Et dans `decrireElement`, après les champs qui se disent autrement :

```js
    if (!avant.miroir !== !apres.miroir) {
      d.push(apres.miroir ? "en miroir" : "sens normal");
    }
    DITS.forEach(function (dit) {
      const a = avant[dit[0]], b = apres[dit[0]];
      if (a === undefined || b === undefined || a === b) return;
      d.push(dit[1] + " " + dit[2](a) + " → " + dit[2](b));
    });
```

- [ ] **Étape 4 : vérifier**

Run : `python3 -m pytest tests/ -q -k overlay_admin`

Au navigateur : incliner `meme` de 10°, changer sa sortie → le pied annonce
« Meme de la communauté — inclinaison 0° → 10° · sortie glitch → hinge », et la
pastille ambre apparaît sur sa ligne dans la liste.

⚠️ Vérifier que la **signature de liste** couvre les nouveaux champs : sans ça,
la pastille « modifié » n'apparaît jamais (piège déjà payé sur ce panneau).
Chercher la fonction de signature et la confronter à `DITS`.

- [ ] **Étape 5 : phase 4 close — vérification complète et publication**

```bash
python3 -m pytest tests/ -q
python3 scripts/lint_types.py
python3 scripts/lint_silences.py
git add -A
git commit -m "feat(overlay): régler les dix paramètres depuis le panneau (phase 4/5)"
git push public feat/site-redesign-arcade:main
```

**⛔ Feu vert de l'owner avant la phase 5.**

---

# Phase 5 — La migration de `image`

### Tâche 5.1 — La graine `overlay_image` → layout, une seule fois

**Fichiers :**
- Modifier : `bot/core/overlay_layout_store.py`
- Modifier : `bot/dashboard/static/app.js` (retrait des quatre champs)
- Test : `tests/test_overlay_layout_store.py`

- [ ] **Étape 1 : écrire le test qui échoue**

```python
async def test_les_reglages_de_config_yaml_sont_semes_une_seule_fois(db, config):
    """La graine ne doit pas repousser par-dessus un réglage fait à la main :
    un drapeau en base dit qu'elle a déjà été semée. Sans lui, chaque boot
    écraserait le choix du streamer avec la valeur d'un fichier qu'il ne
    regarde plus."""
    config.overlay_image.display_duration = 7
    config.overlay_image.animation_in = "bounceInLeft"
    layout = await charger_layout(db)
    for scene in layout["scenes"]:
        assert scene["elements"]["image"]["duree"] == 7.0
        assert scene["elements"]["image"]["anim_entree"] == "bounceInLeft"

    # Le streamer règle autrement, puis on recharge : la graine ne repousse pas.
    layout["scenes"][0]["elements"]["image"]["duree"] = 20.0
    await enregistrer_layout(db, layout)
    relu = await charger_layout(db)
    assert relu["scenes"][0]["elements"]["image"]["duree"] == 20.0


async def test_une_valeur_de_config_hors_bornes_ne_casse_pas_la_graine(db, config):
    config.overlay_image.animation_in = "nawak"
    layout = await charger_layout(db)
    assert layout["scenes"][0]["elements"]["image"]["anim_entree"] == "glitch"
```

- [ ] **Étape 2 : vérifier qu'il échoue**

Run : `python3 -m pytest tests/test_overlay_layout_store.py -q -k graine`

- [ ] **Étape 3 : implémenter**

Dans `overlay_layout_store.py`, une fonction appelée depuis `charger_layout` :

```python
_GRAINE_FAITE = "overlay_image_migre"


async def _semer_reglages_image(db, layout: dict, config) -> bool:
    """Recopie une fois les quatre réglages de `overlay_image` dans les scènes.

    Ils vivaient dans `config.yaml`, globalement — deux autorités sur la même
    question. Après cette graine, le layout décide seul et les quatre champs
    disparaissent de l'onglet Paramètres.

    Le drapeau en base est ce qui rend l'opération sûre : sans lui, chaque boot
    écraserait le choix du streamer avec la valeur d'un fichier qu'il ne
    regarde plus. Rend `True` si quelque chose a été semé.
    """
    if await db.get_state(_GRAINE_FAITE):
        return False
    img = getattr(config, "overlay_image", None)
    if img is None:
        # Pas de section : rien à semer, mais la graine est faite — sinon on
        # rouvrirait la question à chaque boot.
        await db.set_state(_GRAINE_FAITE, "1")
        return False
    graine = {"duree": getattr(img, "display_duration", 0) or 0,
              "anim_entree": getattr(img, "animation_in", "") or ANIM_DEFAUT,
              "anim_sortie": getattr(img, "animation_out", "") or ANIM_DEFAUT,
              "anim_duree": getattr(img, "animation_duration", 0) or ANIM_DUREE_DEFAUT}
    for scene in layout["scenes"]:
        scene["elements"].setdefault("image", {}).update(graine)
    # `fusionner` borne ce qui vient du fichier : une animation retirée
    # d'animate.css ou une durée aberrante y reprend son défaut, comme tout ce
    # qui entre dans ce modèle.
    await db.set_state(_GRAINE_FAITE, "1")
    return True
```

L'appeler dans `charger_layout` **avant** le `fusionner` final, et ré-enregistrer
si elle a semé.

Dans `app.js`, retirer les quatre champs de la section « Images » de l'onglet
Paramètres, et **remplacer** par une ligne qui dit où ils sont partis :

```js
  // Les quatre réglages d'affichage (durée, animations) sont partis dans le
  // panneau de mise en scène, où ils se règlent PAR SCÈNE comme ceux de tous
  // les autres widgets. Laisser un champ mort ici aurait rouvert le doublon
  // d'autorité que la migration vient de fermer.
```

`enabled`, `command` et `random_filter` restent : ils ne parlent pas de mise en
scène.

- [ ] **Étape 4 : vérifier**

Run : `python3 -m pytest tests/ -q`

Puis en prod, **après** rebuild, confirmer que la graine a bien pris :

```bash
docker compose exec wally python3 -c "
import asyncio, json
from bot.core.overlay_layout_store import charger_layout
"   # ou plus simplement, lire par la route :
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/admin/overlay/layout \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['scenes'][0]['elements']['image'])"
```

Attendu : `duree` et `anim_entree` reprennent les valeurs de `config.yaml`
(`display_duration: 5`, `animation_in: bounceInLeft` au moment d'écrire ce plan).

- [ ] **Étape 5 : phase 5 close — vérification complète et publication**

```bash
python3 -m pytest tests/ -q
python3 scripts/lint_types.py
python3 scripts/lint_silences.py
git add -A
git commit -m "feat(overlay): les réglages de la galerie quittent config.yaml pour la scène (phase 5/5)"
GIT_HASH=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  docker compose up -d --build wally
git push public feat/site-redesign-arcade:main
```

---

## Vérification finale, à l'écran

À faire sur `https://heywally.fr/overlay` et le panneau de mise en scène, une
fois les cinq phases publiées. Un test vert ne prouve pas qu'un panneau monte.

- [ ] Les sept onglets du dashboard montent (un `throw` dans un `mount()` casse
      tous les suivants).
- [ ] L'inspecteur affiche les bons champs selon l'élément : `avatar` n'a **pas**
      de durée ni d'animation, `poll` les a toutes, `rotator` garde `pause`.
- [ ] Un overlay dont personne n'a touché les réglages rend **exactement** comme
      avant : mêmes durées, glitch à l'entrée et à la sortie, rien d'incliné.
- [ ] Une durée réglée coupe bien un `meme`, et **ne coupe pas** un pendu en
      cours ni un clip en lecture.
- [ ] Une inclinaison incline sans déplacer ; un miroir retourne sur place.
- [ ] Le pied du panneau annonce chaque changement, et la pastille ambre apparaît
      sur la ligne concernée dans la liste.
- [ ] `/api/admin/overlay/layout` ne renvoie pas `animations` ni `portees` dans
      ce que le PUT range (vérifier la taille du blob en base après publication).
