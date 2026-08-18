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

from bot.core.memes import enveloppe_images

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
# masquerait. `rotation` reste réservé alors que la page ne rend plus qu'un avis
# de remplacement : tant que la route existe, elle capte le slug.
SLUGS_RESERVES = frozenset({"image", "rotation", "version", "health"})

SCALE_MIN, SCALE_MAX = 0.2, 2.0

# ── La cadence du rotateur de memes ─────────────────────────────────────────
#
# Les défauts REPRODUISENT les constantes de l'ancienne source OBS
# (`overlay_rotation.html`, puis `ROTATEUR` dans `overlay.js`) : personne ne voit
# son overlay changer de rythme parce qu'on a rendu ces deux valeurs réglables.
#
# Les bornes :
#   - une durée sous 1 s n'affiche plus rien de lisible : les deux rafales de
#     glitch qui encadrent un passage coûtent ~0,46 s (mesuré au navigateur,
#     2 × 7 états de 33 ms), soit déjà près de la moitié du plancher ;
#   - une pause de 0 s est LÉGITIME : elle enchaîne les memes sans temps mort,
#     le glitch de sortie de l'un touchant celui d'entrée du suivant ;
#   - le plafond commun de 120 s tient à deux choses. Au-delà, ce n'est plus un
#     rotateur mais une image fixe (`!image` existe pour ça). Et surtout le
#     gardien anti-gel de la boucle attend `3 × (durée + pause) + 10 s` avant de
#     relancer une source figée : à 120/120, il patiente déjà douze minutes.
ROTATEUR_DUREE_MIN, ROTATEUR_DUREE_MAX, ROTATEUR_DUREE_DEFAUT = 1.0, 120.0, 9.0
ROTATEUR_PAUSE_MIN, ROTATEUR_PAUSE_MAX, ROTATEUR_PAUSE_DEFAUT = 0.0, 120.0, 5.0

# Les réglages qui n'existent que sur CERTAINS éléments : nom → (mini, maxi).
#
# Pourquoi pas sur tous les éléments, ce qui serait plus simple : `ELEMENTS`
# compte trente-quatre clés et le layout en garde une copie PAR SCÈNE. Poser
# `duree`/`pause` partout écrirait 34 × 2 × 3 = 204 valeurs qui ne pilotent
# rien, et surtout la barre de réglages du panneau afficherait « durée
# d'affichage » sur un dé ou un sondage — un réglage visible qu'aucun code ne
# lit est une promesse fausse. Le coût de la justesse est cette table et les
# quatre lignes de fusion qui la lisent.
#
# C'est la PRÉSENCE de la clé dans le défaut de l'élément (`ELEMENTS`) qui dit
# qui la porte ; cette table ne dit que ses bornes. Un seul endroit à toucher
# pour donner la cadence à un autre élément un jour.
CHAMPS_PROPRES: dict[str, tuple[float, float]] = {
    "duree": (ROTATEUR_DUREE_MIN, ROTATEUR_DUREE_MAX),
    "pause": (ROTATEUR_PAUSE_MIN, ROTATEUR_PAUSE_MAX),
}

# Doit rester égal à la borne de la route `/overlay-{slug}` (`bot/dashboard/app.py`,
# `_SLUG_SCENE_RE`) : un slug plus long que ça y est refusé et sert la scène par
# défaut en silence — data-scene-slug="" sans erreur ni log.
SLUG_MAX_LEN = 64


def _el(x: float, y: float, anchor: str, scale: float = 1.0,
        *, solo: bool = True, hidden: bool = False,
        wally_visible: bool | None = None,
        propres: dict | None = None) -> dict:
    # `wally_visible` non précisé REPRODUIT le comportement d'avant ce réglage,
    # où `solo` décidait à lui seul de l'effacement de l'avatar : un élément
    # exclusif efface Wally, un élément qui cohabite le laisse. Personne ne voit
    # son overlay changer parce qu'on a ajouté le réglage.
    #
    # `propres` : les réglages que CET élément est seul à porter (cf.
    # `CHAMPS_PROPRES`). Absents partout ailleurs.
    return {"x": x, "y": y, "anchor": anchor, "scale": scale,
            "hidden": hidden, "locked": False, "solo": solo,
            "wally_visible": (not solo) if wally_visible is None else wally_visible,
            **(propres or {})}


# Les clés SONT les `kind` employés par la page — les franciser casserait la
# correspondance et imposerait une table de traduction pour rien.
#
# La liste suit `BUILDERS` **∪ `APEX_BUILDERS`**, PAS l'enum de l'outil
# `show_overlay`. Les deux objets comptent : `overlay.js` les FUSIONNE
# (`Object.assign(BUILDERS, window.APEX_BUILDERS || {})`), et les huit panneaux
# `apex_*` sont publiés pour de vrai (`bot/core/apex/service.py` rend
# `{"kind": f"apex_{panel}"}`). Ne lire que `BUILDERS` les a fait manquer une
# première fois : le commentaire disait vrai en apparence et désignait la
# moitié de l'univers. `tests/test_overlay_layout_css.py` compare désormais
# l'UNION des deux objets à cette liste.
#
# Une clé absente ici n'est pas seulement mal placée : `appliquer()` n'itérant
# que sur `ELEMENTS`, elle reste hors de portée du panneau de mise en scène,
# à jamais. Une clé en trop n'est qu'un réglage inutile — l'asymétrie tranche.
# `goal` et `uptime` sont dans l'enum de l'outil mais ne sont jamais rendus
# sous ce nom : `_publish_goal` (overlay_narrator.py) publie un `gauge`,
# `uptime` est aliasé en `counter` — les lister ici n'aurait aucun effet.
#
# `solo=True` : l'élément chasse les autres et passe par la file d'attente.
# `solo=False` : il s'installe et laisse la place aux autres par-dessus.
#
# `wally_visible` répond à une TOUTE AUTRE question : l'avatar et la bulle
# restent-ils à l'écran pendant l'affichage ? Les deux étaient confondus dans
# `solo`, alors qu'on peut vouloir un meme qui occupe seul la scène mais garde
# Wally à côté pour qu'il le commente. Non précisé, il vaut `not solo`.
#
# L'échelle de l'avatar vaut 0.55 : elle reproduit, sur un canvas de 1920, la
# taille qu'il avait dans son ancienne source de 560 px de large.
ELEMENTS: dict[str, dict] = {
    # Wally et sa bulle
    "avatar": _el(97.0, 80.0, "bottom-right", 0.55, solo=False),
    "bubble": _el(95.0, 62.0, "bottom-right", 0.9, solo=False),
    # Les deux ex-sources OBS
    "rotator": _el(50.0, 45.0, "center", 1.0, solo=False,
                   propres={"duree": ROTATEUR_DUREE_DEFAUT,
                            "pause": ROTATEUR_PAUSE_DEFAUT}),
    "image":   _el(50.0, 50.0, "center", 1.0),
    # Ceux qui s'installent
    "bingo":   _el(3.0, 18.0, "top-left", 0.9, solo=False),
    "stats":   _el(3.0, 60.0, "top-left", 0.9, solo=False),
    "talkers": _el(3.0, 40.0, "top-left", 0.9, solo=False),
    # Une étiquette de titre n'est pas un spectacle : elle s'installe en bas à
    # gauche et laisse Wally à l'écran.
    "music_now": _el(3.0, 92.0, "bottom-left", 0.9, solo=False),
    # Ceux qui passent
    "meme":       _el(50.0, 50.0, "center"),
    "clip":       _el(50.0, 50.0, "center"),
    "clip_top":   _el(50.0, 50.0, "center"),
    "planning":   _el(50.0, 50.0, "center"),
    "prediction": _el(50.0, 50.0, "center"),
    "quote":      _el(50.0, 50.0, "center"),
    "raid":       _el(50.0, 50.0, "center"),
    "wave":       _el(50.0, 50.0, "center"),
    # Le spam de popups occupe TOUT l'écran, donc il s'ancre au COIN et non au
    # centre : centrée, une carte de 100vw part de la moitié de l'écran et se
    # rattrape par un `translate` — mesuré au navigateur, elle finissait décalée
    # de 77 px. Au coin, il n'y a rien à rattraper. Il reste réglable comme le
    # reste (un overlay qui fait exception à sa propre grammaire ne se règle
    # plus), mais son défaut est celui qui couvre l'écran pile.
    "virus_popup": _el(0.0, 0.0, "top-left"),
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
    # Les panneaux Apex (`overlay_apex.js`) : ils passent comme les autres, et
    # partent donc du même endroit. Avant ce chantier, TOUS les widgets
    # occupaient la place de l'avatar ; aucun n'a de position propre à
    # préserver, le streamer les réglera depuis le panneau.
    "apex_rank":     _el(50.0, 50.0, "center"),
    "apex_progress": _el(50.0, 50.0, "center"),
    "apex_status":   _el(50.0, 50.0, "center"),
    "apex_stats":    _el(50.0, 50.0, "center"),
    "apex_map":      _el(50.0, 50.0, "center"),
    "apex_craft":    _el(50.0, 50.0, "center"),
    "apex_predator": _el(50.0, 50.0, "center"),
    "apex_servers":  _el(50.0, 50.0, "center"),
}

# ── Les groupes d'éléments ──────────────────────────────────────────────────
#
# POURQUOI PAR SCÈNE, ET NON GLOBAUX AU LAYOUT.
#
# Un groupe global se règle une fois et s'impose aux trois scènes ; un groupe
# par scène est plus souple et se recrée trois fois. Le modèle a tranché avant
# nous : `elements` et `ordre` sont DÉJÀ par scène, et le commentaire de
# `layout_par_defaut()` dit pourquoi — les scènes divergent dès le premier
# réglage. Or TOUT ce qu'un groupe fait agit sur des données par scène : le
# déplacer écrit des `x`/`y` de scène, le masquer et le verrouiller écrivent des
# `hidden`/`locked` de scène, et son en-tête se lit dans une liste dont l'ordre
# est celui de la scène. Un groupe global serait le seul objet transversal d'un
# modèle qui n'en a aucun, et il imposerait le même découpage à une scène de fin
# qui n'affiche que trois éléments.
#
# Le coût — recréer trois fois — est largement payé d'avance : les groupes
# livrés ci-dessous partent dans les trois scènes, et « Dupliquer » recopie déjà
# les éléments en profondeur, donc les groupes avec.
#
# UN ÉLÉMENT N'APPARTIENT QU'À UN SEUL GROUPE.
#
# Le groupe est l'unité qu'on manipule. Si `dice` était à la fois dans « Jeux de
# hasard » et dans « Widgets du bas », déplacer le premier groupe déplacerait
# `dice`, et le cadre englobant du second mentirait aussitôt sur ce qu'il
# entoure ; masquer l'un puis montrer l'autre laisserait deux vérités
# contradictoires sur le même élément ; et la liste, qui rend les membres
# groupés sous leur en-tête, devrait afficher `dice` deux fois ou en choisir une
# au hasard. L'exclusivité fait des groupes une PARTITION d'une partie des
# éléments : le cadre dit vrai, la liste ne se répète pas. Elle est tenue ici,
# au point d'écriture (`_fusionner_groupes` : le premier groupe qui réclame une
# clé la garde), et pas seulement dans le panneau.
#
# Le groupe ne porte NI `hidden` NI `locked` à lui : ces deux-là vivent sur
# l'élément, et le cadenas y bloque déjà tout. Un drapeau de groupe serait une
# seconde autorité qui contredirait la première — un membre verrouillé dans un
# groupe libre ne doit pas bouger, c'est la règle en place. Masquer ou
# verrouiller un groupe, c'est le faire à chacun de ses membres.
#
# Les membres sont livrés dans un ordre qui ÉPOUSE `_ORDRE_DEFAUT` : les rendre
# contigus (`_ordre_avec_groupes`) ne doit rien déplacer sur une disposition
# déjà réglée. Mesuré sur la base de production : seul `rps` remonte de trois
# rangs, devant `gauge` et `countdown` — trois widgets exclusifs (`solo`) qui ne
# cohabitent jamais à l'écran. `avatar` n'est délibérément PAS groupé avec
# `bubble` : il a été descendu à la main derrière tout le reste dans la scène de
# jeu, et un groupe « Wally » l'aurait remonté sans que personne ne le demande.
GROUPES_DEFAUT: list[dict] = [
    {"id": "medias", "nom": "Médias en plein cadre",
     "membres": ["image", "meme", "clip", "clip_top", "planning"]},
    {"id": "hasard", "nom": "Jeux de hasard",
     "membres": ["coinflip", "dice", "wheel", "rps"]},
    {"id": "apex", "nom": "Tableau de bord Apex",
     "membres": ["apex_rank", "apex_progress", "apex_status", "apex_stats",
                 "apex_map", "apex_craft", "apex_predator", "apex_servers"]},
    {"id": "installes", "nom": "Widgets installés",
     "membres": ["talkers", "bingo", "stats"]},
]

# Un groupe sans nom lisible n'est pas jeté : c'est l'appartenance qui coûte à
# composer, pas le mot. Même parti pris que `nom` sur une scène, qui retombe sur
# son slug plutôt que de faire disparaître la scène.
GROUPE_NOM_DEFAUT = "Groupe sans nom"

# L'empilement par défaut, du plus proche au plus lointain. Wally passe devant
# ce qu'il montre ; les widgets installés restent au fond.
_ORDRE_DEFAUT = [
    "bubble", "avatar", "image", "meme",
    "clip", "clip_top", "planning", "prediction", "quote", "raid", "wave",
    "virus_popup", "music_now",
    "versus", "poll", "hangman",
    "pinned", "counter", "coinflip", "dice", "wheel", "gauge", "countdown",
    "rps",
    "apex_rank", "apex_progress", "apex_status", "apex_stats",
    "apex_map", "apex_craft", "apex_predator", "apex_servers",
    "rotator", "talkers", "bingo", "stats",
]

# Les trois scènes livrées, par leur NOM seul : le slug en DÉRIVE
# (`slug_depuis_nom`), il n'est pas écrit à côté. Une paire écrite à la main a
# donné « Stream Starting » → `start` : incohérent avec ce que produit la
# création d'une scène depuis le panneau, et surtout indevinable quand on
# cherche l'URL à taper dans OBS. Un seul chemin vers un slug, ici comme
# ailleurs.
_NOMS_DEFAUT = ("Stream Starting", "En jeu", "Fin")
_NOM_DEFAUT = "En jeu"


def groupes_par_defaut() -> list[dict]:
    """Les groupes livrés, en copie profonde.

    Copie et non référence : chaque scène a les siens, et une liste partagée les
    ferait tous bouger ensemble au premier renommage — exactement ce que la
    copie des éléments évite déjà.
    """
    return [{"id": g["id"], "nom": g["nom"], "membres": list(g["membres"])}
            for g in GROUPES_DEFAUT]


def layout_par_defaut() -> dict:
    """Trois scènes, tous les éléments placés, rien de masqué.

    Chaque scène a sa PROPRE copie des éléments : elles divergent dès le premier
    réglage, et un dictionnaire partagé les ferait bouger ensemble.
    """
    ordre = _ordre_avec_groupes(list(_ORDRE_DEFAUT), GROUPES_DEFAUT)
    return {
        "version": 1,
        "defaut": slug_depuis_nom(_NOM_DEFAUT),
        "scenes": [
            {"slug": slug_depuis_nom(nom), "nom": nom,
             "ordre": list(ordre),
             "groupes": groupes_par_defaut(),
             "elements": {k: dict(v) for k, v in ELEMENTS.items()}}
            for nom in _NOMS_DEFAUT
        ],
    }


# ── La boîte des widgets à média ────────────────────────────────────────────
#
# Un widget de TEXTE se dimensionne par son contenu et sa taille ne se connaît
# pas à l'avance ; la table du JS (`WallyLayout.TAILLES`) n'en donne qu'un ordre
# de grandeur. Un widget à MÉDIA, lui, affiche une image de dimensions
# arbitraires : sa boîte est IMPOSÉE, et elle se CALCULE depuis le dossier.
#
# La règle, dans les mots de l'owner : « prends la plus grande image en hauteur
# et la plus grande en largeur, et ça définit la box ». Sur les tailles
# affichées, pas sur les fichiers — le dossier monte à 2100 × 2100, plus grand
# que le canvas.
#
# L'intérêt de la calculer plutôt que de l'écrire : elle ne réserve que ce que
# le dossier peut atteindre. Aujourd'hui il contient un portrait à 0,45 et un
# paysage à 1,89, donc les deux axes saturent et la boîte est carrée. Qu'ils
# disparaissent et elle s'aplatit d'elle-même, sans que personne n'y retouche.

# Ce que le cadre ajoute autour de l'image, en pixels : padding et bordure, des
# deux côtés. Ces valeurs décrivent `overlay.html` — c'est le genre de doublon
# qui a créé le défaut d'origine, donc un test les CONFRONTE au CSS
# (`tests/test_overlay_taille_widgets_media.py`).
PASSE_PARTOUT_MEDIA = {"rotator": 34, "meme": 18, "image": 0}

# Le rotateur grossit les petits memes pour qu'ils ne paraissent pas perdus
# (`AGRANDIR` dans overlay.js). La carte `meme` et l'image de galerie, elles, ne
# font que réduire.
AGRANDISSEMENT_MEDIA = {"rotator": 2.0, "meme": 1.0, "image": 1.0}

# Le dossier où chaque widget à média prend ses images. `image` lit la galerie
# et non les memes : ses images sont générées, toutes carrées aujourd'hui
# (1024 × 1024), et lui prêter l'enveloppe des memes annoncerait un cadre que
# rien n'y remplit jamais.
DOSSIER_MEDIA = {"rotator": "memes", "meme": "memes", "image": "gallery"}

# LES seuls réglages de goût de tout ce calcul : la place qu'on accepte de
# laisser prendre à chaque média sur le canvas 1920 × 1080, passe-partout
# compris. Tout le reste se mesure.
#
# Ce sont des PLAFONDS, pas des cadres : le cadre, lui, est l'enveloppe de ce
# que le dossier atteint vraiment, et il peut rester bien en dessous. La galerie
# garde 720 — le `max-height` que le CSS lui applique déjà —, parce que corriger
# son CADRE ne doit pas changer son RENDU : ses images sont réduites à 720 de
# haut depuis toujours, et la table en annonçait 1280 de large.
BOITE_MEDIA_MAX = {"rotator": 400, "meme": 400, "image": 720}


def tailles_media(library, dossiers=None) -> dict[str, list[int]]:
    """Les boîtes des widgets à média, mesurées sur leurs images.

    `dossiers` : la racine de chaque dossier connu (`memes`, `gallery`). La
    bibliothèque de memes sait déjà trier les siens — extensions, poids, vidéos
    écartées ; la galerie n'a pas d'équivalent, on lit son dossier.

    Rend un dictionnaire vide si rien n'est mesurable : la page et le panneau
    gardent alors la table du JS. Un dossier vide ne doit pas donner une boîte
    nulle — ce serait un repère d'un pixel au milieu de la scène.
    """
    dossiers = dossiers or {}
    out: dict[str, list[int]] = {}
    for cle, marge in PASSE_PARTOUT_MEDIA.items():
        media_max = BOITE_MEDIA_MAX[cle] - marge
        try:
            if DOSSIER_MEDIA[cle] == "memes":
                if library is None:
                    continue
                env = library.enveloppe_rendue(media_max,
                                               AGRANDISSEMENT_MEDIA[cle])
            else:
                racine = dossiers.get(DOSSIER_MEDIA[cle])
                if racine is None:
                    continue
                env = enveloppe_images(_images_du_dossier(racine), media_max,
                                       AGRANDISSEMENT_MEDIA[cle])
        # Bibliothèque d'un autre type, dossier illisible, Pillow absent : la
        # boîte calculée est un CONFORT, jamais une condition d'affichage.
        except Exception:
            continue
        if env:
            out[cle] = [env[0] + marge, env[1] + marge]
    return out


def _images_du_dossier(racine) -> list:
    """Les fichiers d'un dossier, à plat. Ce qui n'est pas une image sera écarté
    par la lecture elle-même — inutile de dupliquer ici une liste d'extensions
    qui divergerait de celle des memes."""
    from pathlib import Path
    try:
        return [c for c in Path(racine).iterdir() if c.is_file()]
    except OSError:
        return []


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
    fusionne = {
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
        "wally_visible": (bool(brut["wally_visible"])
                          if brut.get("wally_visible") is not None
                          else defaut["wally_visible"]),
    }
    # Les réglages propres à cet élément-là. Même rigueur que les autres champs
    # numériques : `_borner` ramène dans les bornes, et rend le défaut pour ce
    # qui n'est pas un nombre — une clé absente comme une clé présente à `null`.
    for nom, (mini, maxi) in CHAMPS_PROPRES.items():
        if nom in defaut:
            fusionne[nom] = _borner(brut.get(nom), mini, maxi, defaut[nom])
    return fusionne


def _fusionner_groupes(brut) -> list[dict]:
    """Les groupes d'une scène, rangés. Jamais d'exception.

    La clé ABSENTE (ou d'un type inattendu) reprend les groupes livrés : c'est
    le cas de toute disposition rangée avant ce chantier, et la même règle que
    partout ailleurs ici — un réglage absent reprend son défaut. Une LISTE VIDE,
    elle, est respectée : dissoudre tous ses groupes est une décision, et les
    voir repousser au rechargement rendrait la dissolution impossible.

    Ce qui est écarté, toujours sans faire tomber le reste :
      - un groupe qui n'est pas un dictionnaire, ou sans `id` exploitable — on
        ne peut ni le renommer ni le dissoudre sans identité ;
      - un `id` déjà pris, comme deux scènes de même slug ;
      - un membre inconnu d'`ELEMENTS` : la clé est ignorée, le groupe garde
        les autres ;
      - un membre DÉJÀ réclamé par un groupe précédent : l'exclusivité se tient
        ici, au point d'écriture ;
      - un groupe qui n'a plus aucun membre au bout de ce tri : il n'y a plus
        rien à manipuler dessous.
    """
    if not isinstance(brut, list):
        return groupes_par_defaut()
    groupes: list[dict] = []
    ids: set[str] = set()
    pris: set[str] = set()
    for groupe_brut in brut:
        if not isinstance(groupe_brut, dict):
            continue
        gid = groupe_brut.get("id")
        if not isinstance(gid, str) or not gid.strip():
            continue
        gid = gid.strip()
        if gid in ids:
            continue
        membres_bruts = groupe_brut.get("membres")
        if not isinstance(membres_bruts, list):
            membres_bruts = []
        membres = []
        for cle in membres_bruts:
            # `isinstance(cle, str)` avant le `in` : une clé en `dict`/`list` —
            # un JSON par ailleurs légal — ferait lever `in` sur un type non
            # hashable.
            if not isinstance(cle, str) or cle not in ELEMENTS or cle in pris:
                continue
            pris.add(cle)
            membres.append(cle)
        if not membres:
            continue
        ids.add(gid)
        nom = groupe_brut.get("nom")
        groupes.append({
            "id": gid,
            "nom": nom.strip() if isinstance(nom, str) and nom.strip()
                   else GROUPE_NOM_DEFAUT,
            "membres": membres,
        })
    return groupes


def _ordre_avec_groupes(ordre: list[str], groupes: list[dict]) -> list[str]:
    """Les membres d'un groupe rendus CONTIGUS, à la place du premier d'entre eux.

    L'ordre de la liste EST l'empilement : c'est écrit dans le panneau et sous
    les yeux du streamer. Une liste qui affiche quatre membres l'un sous l'autre
    pendant que trois autres widgets s'intercalent dans l'empilement réel
    mentirait sur la seule chose que cette liste raconte. Grouper, c'est donc
    aussi rapprocher dans l'empilement — un effet qu'on assume et qu'on annonce.

    Le groupe prend la place de son PREMIER membre, et les membres gardent leur
    ordre relatif : la disposition déjà réglée bouge le moins possible.
    """
    if not groupes:
        return ordre
    par_cle = {cle: g["id"] for g in groupes for cle in g["membres"]}
    sortie: list[str] = []
    faits: set[str] = set()
    for cle in ordre:
        gid = par_cle.get(cle)
        if gid is None:
            sortie.append(cle)
            continue
        if gid in faits:
            continue
        faits.add(gid)
        sortie.extend([c for c in ordre if par_cle.get(c) == gid])
    return sortie


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
    # Les groupes APRÈS le complètement de l'ordre : `_ordre_avec_groupes` lit
    # `ordre` pour ranger les membres, et un membre qui n'y serait pas encore
    # disparaîtrait de la sortie.
    groupes = _fusionner_groupes(brut.get("groupes"))
    ordre = _ordre_avec_groupes(ordre, groupes)
    nom = brut.get("nom")
    return {
        "slug": slug,
        "nom": nom.strip() if isinstance(nom, str) and nom.strip() else slug,
        "ordre": ordre,
        "groupes": groupes,
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
    # Coupé à la borne de la route, puis le trait d'union que la coupe peut
    # laisser en fin de chaîne est retiré — sinon un nom un peu long produirait
    # une scène inaccessible : la route la refuserait en silence.
    slug = slug[:SLUG_MAX_LEN].strip("-") or "scene"
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
