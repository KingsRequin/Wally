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
# La liste suit `BUILDERS`, PAS l'enum de l'outil `show_overlay` : une clé
# absente ici est un widget qui perd son conteneur (et disparaît de l'overlay
# SANS lever d'erreur) le jour où `#widgets` se scinde par clé ; une clé en
# trop n'est qu'un réglage inutile. `goal` et `uptime` sont dans l'enum de
# l'outil mais ne sont jamais rendus sous ce nom : `_publish_goal`
# (overlay_narrator.py) publie un `gauge`, `uptime` est aliasé en `counter` —
# les lister ici n'aurait donc aucun effet.
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
    "talkers": _el(3.0, 40.0, "top-left", 0.9, solo=False),
    # Ceux qui passent
    "meme":       _el(50.0, 50.0, "center"),
    "clip":       _el(50.0, 50.0, "center"),
    "clip_top":   _el(50.0, 50.0, "center"),
    "planning":   _el(50.0, 50.0, "center"),
    "prediction": _el(50.0, 50.0, "center"),
    "quote":      _el(50.0, 50.0, "center"),
    "raid":       _el(50.0, 50.0, "center"),
    "wave":       _el(50.0, 50.0, "center"),
    "versus":     _el(50.0, 50.0, "center"),
    "poll":       _el(50.0, 50.0, "center"),
    "hangman":    _el(50.0, 50.0, "center"),
    "pinned":     _el(50.0, 50.0, "center"),
    "counter":    _el(50.0, 50.0, "center"),
    "coinflip":   _el(50.0, 50.0, "center"),
    "dice":       _el(50.0, 50.0, "center"),
    "wheel":      _el(50.0, 50.0, "center"),
    "gauge":      _el(50.0, 50.0, "center"),
    "countdown":  _el(50.0, 50.0, "center"),
    "rps":        _el(50.0, 50.0, "center"),
}

# L'empilement par défaut, du plus proche au plus lointain. Wally passe devant
# ce qu'il montre ; les widgets installés restent au fond.
_ORDRE_DEFAUT = [
    "bubble", "avatar", "image", "meme",
    "clip", "clip_top", "planning", "prediction", "quote", "raid", "wave",
    "versus", "poll", "hangman",
    "pinned", "counter", "coinflip", "dice", "wheel", "gauge", "countdown",
    "rps", "rotator", "talkers", "bingo", "stats",
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
    # `isinstance(..., str)` avant le `in` : un `anchor` en `dict`/`list` — un
    # JSON par ailleurs légal — ferait lever `in` sur un type non hashable.
    return {
        "x": _borner(brut.get("x"), 0.0, 100.0, defaut["x"]),
        "y": _borner(brut.get("y"), 0.0, 100.0, defaut["y"]),
        "anchor": anchor if isinstance(anchor, str) and anchor in ANCRAGES else defaut["anchor"],
        "scale": _borner(brut.get("scale"), SCALE_MIN, SCALE_MAX, defaut["scale"]),
        # `bool()` franc : l'admin envoie des booléens, mais un JSON écrit à la
        # main peut porter "oui" ou 1. Une clé présente à `null` reprend le
        # défaut — `.get(clé, défaut)` ne le fait PAS : la clé est présente,
        # sa valeur `None` est retournée telle quelle, et `bool(None)` vaut
        # toujours `False` quel que soit le défaut de l'élément.
        "hidden": bool(brut["hidden"]) if brut.get("hidden") is not None else defaut["hidden"],
        "locked": bool(brut["locked"]) if brut.get("locked") is not None else defaut["locked"],
        "solo": bool(brut["solo"]) if brut.get("solo") is not None else defaut["solo"],
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
    # `isinstance(c, str)` avant le `in` : un élément d'`ordre` en `dict`/
    # `list` — un JSON par ailleurs légal — ferait lever `in ELEMENTS` sur un
    # type non hashable.
    ordre = ([c for c in ordre_brut if isinstance(c, str) and c in ELEMENTS]
              if isinstance(ordre_brut, list) else [])
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
    # `isinstance(defaut, str)` avant le `in` : un `defaut` en `dict`/`list` —
    # un JSON par ailleurs légal — ferait lever `in` sur un `set` de chaînes.
    if not isinstance(defaut, str) or defaut not in vus:
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
