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

# ── Les réglages universels ─────────────────────────────────────────────────
#
# Les quatre que TOUS les éléments portent, parce qu'ils passent tous par
# `placer()` (overlay_layout.js), le point d'écriture unique du style d'un
# élément sur la page. Ici et pas dans `CHAMPS_PROPRES` : un champ que les
# trente-sept ont n'est propre à personne, et l'y mettre obligerait à le répéter
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

# Les quatre, rassemblés : `champ → (mini, maxi, auto)`, ou `None` pour un
# booléen, qui n'a ni bornes ni choix.
#
# Une table plutôt que quatre lignes en dur, pour la raison qui gouverne tout ce
# fichier : elle a UN seul lecteur de plus que la fusion — la route qui la sert
# au panneau. Sans elle, le panneau devrait deviner que ces quatre-là existent
# sur les trente-sept, et redire leurs bornes en JavaScript ; deux tables
# divergent au premier ajustement, et le panneau laisserait alors saisir une
# valeur que le serveur ramène en silence.
CHAMPS_UNIVERSELS: dict[str, tuple[float, float, bool] | None] = {
    "opacite": (OPACITE_MIN, OPACITE_MAX, False),
    "rotation": (ROTATION_MIN, ROTATION_MAX, False),
    "largeur_max": (LARGEUR_MIN, LARGEUR_MAX, True),
    "miroir": None,
}

# ── Les réglages de rythme des widgets qui PASSENT ──────────────────────────
#
# `duree` = 0 vaut AUTO : le serveur décide, comme avant ce réglage. C'est la
# valeur LIVRÉE, et c'est elle qui protège le live — livrer 12 s (le repli de
# `showWidget`) ferait disparaître un sondage de 120 s à la douzième seconde,
# sur les trois scènes, dès le premier rebuild et sans que personne ait touché
# à un curseur.
#
# Le plafond de 180 s est celui de `showWidget` (overlay.js), et il n'est pas
# arbitraire : le serveur émet jusqu'à 124 s (sondage de 120 s + 4).
WIDGET_DUREE_MIN, WIDGET_DUREE_MAX, WIDGET_DUREE_DEFAUT = 2.0, 180.0, 0.0
DELAI_MIN, DELAI_MAX, DELAI_DEFAUT = 0.0, 10.0, 0.0
# 0,15 s = `GLITCH_MS` côté page (5 états × 30 ms) : la durée de la rafale
# d'aujourd'hui. La reproduire ici est ce qui fait que rien ne change.
ANIM_DUREE_MIN, ANIM_DUREE_MAX, ANIM_DUREE_DEFAUT = 0.1, 3.0, 0.15

# La bulle a son propre chemin (`say`), avec un repli de 3 s côté page.
BULLE_DUREE_MIN, BULLE_DUREE_MAX, BULLE_DUREE_DEFAUT = 1.0, 60.0, 0.0

# Les quatre éléments qui ont leur PROPRE chemin de rendu et ne passent donc pas
# par `showWidget` : l'avatar et la bulle vivent en permanence, le rotateur porte
# sa propre boucle, la galerie écoute son propre flux SSE. Leur donner `delai` ou
# une animation de carte serait un réglage qu'aucun code ne lit.
HORS_FILE = frozenset({"avatar", "bubble", "rotator", "image"})


# ── Le catalogue d'animations ───────────────────────────────────────────────
#
# `animate.min.css` est déjà servi sur l'overlay et déjà utilisé par la galerie
# (`animation_in`/`animation_out` de `config.yaml`) : on ne charge rien de neuf,
# on ouvre ce qui était réservé à un seul widget.
#
# Écrit ICI et servi au panneau par la route, jamais recopié en JavaScript :
# deux listes divergent à la première mise à jour de la bibliothèque. Même parti
# pris que `LIBELLES` et `_ECHANTILLONS`, déjà servis par ce chemin.
#
# `glitch` est l'option MAISON et le défaut : c'est la rafale
# (`WallyGlitch.rafale`) qui encadre aujourd'hui l'entrée et la sortie de toutes
# les cartes. La garder en tête de menu est ce qui fait que personne ne voit son
# overlay changer.
#
# Entrées et sorties sont deux listes SÉPARÉES et disjointes : `fadeOut` proposé
# en entrée ferait disparaître la carte au moment où elle apparaît.
ANIM_DEFAUT = "glitch"
ANIM_AUCUNE = "aucune"

ANIMATIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "entree": {
        "Maison": (ANIM_DEFAUT, ANIM_AUCUNE),
        "Fondu": ("fadeIn", "fadeInDown", "fadeInDownBig", "fadeInLeft",
                  "fadeInLeftBig", "fadeInRight", "fadeInRightBig", "fadeInUp",
                  "fadeInUpBig", "fadeInTopLeft", "fadeInTopRight",
                  "fadeInBottomLeft", "fadeInBottomRight"),
        "Glissement": ("slideInDown", "slideInLeft", "slideInRight",
                       "slideInUp"),
        "Zoom": ("zoomIn", "zoomInDown", "zoomInLeft", "zoomInRight",
                 "zoomInUp"),
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

# Les réglages qu'un élément porte SEUL, et comment ils se valident.
#
#   `CHAMPS_PROPRES` : élément → {champ → (mini, maxi, auto)}
#   `CHAMPS_CHOIX`   : élément → {champ → noms acceptés}
#
# Indexées par ÉLÉMENT et non plates, parce que le même mot n'a pas partout la
# même grandeur : `duree` vaut la durée d'UN MÉDIA sur le rotateur (1–120 s,
# plafond dicté par son gardien anti-gel) et la durée d'UN PASSAGE à l'écran sur
# un widget qui passe (2–180 s, ou auto). Une table plate aurait fait dépendre
# la borne appliquée de l'ordre d'écriture — un défaut invisible jusqu'à un
# soir de live.
#
# Elles sont remplies plus bas, PAR LA MÊME BOUCLE qui pose les défauts sur
# `ELEMENTS` : c'est ce qui rend impossible le défaut le plus probable ici, un
# champ posé sur un élément sans validation déclarée, donc rangé tel quel.
CHAMPS_PROPRES: dict[str, dict[str, tuple[float, float, bool]]] = {}
CHAMPS_CHOIX: dict[str, dict[str, frozenset[str]]] = {}

# Doit rester égal à la borne de la route `/overlay-{slug}` (`bot/dashboard/app.py`,
# `_SLUG_SCENE_RE`) : un slug plus long que ça y est refusé et sert la scène par
# défaut en silence — data-scene-slug="" sans erreur ni log.
SLUG_MAX_LEN = 64


def _el(x: float, y: float, anchor: str, scale: float = 1.0,
        *, solo: bool = True, hidden: bool = False,
        wally_visible: bool | None = None) -> dict:
    # `wally_visible` non précisé REPRODUIT le comportement d'avant ce réglage,
    # où `solo` décidait à lui seul de l'effacement de l'avatar : un élément
    # exclusif efface Wally, un élément qui cohabite le laisse. Personne ne voit
    # son overlay changer parce qu'on a ajouté le réglage.
    #
    # Les réglages de PORTÉE (durée, animations, cadence du rotateur) ne sont
    # pas posés ici mais par la boucle de distribution, plus bas : elle écrit
    # d'un même geste le défaut ET sa règle de validation, ce qui rend
    # impossible un champ rangé sans être borné.
    return {"x": x, "y": y, "anchor": anchor, "scale": scale,
            "hidden": hidden, "locked": False, "solo": solo,
            "wally_visible": (not solo) if wally_visible is None else wally_visible,
            # Les quatre universels. Tout élément passe par `placer()`, donc
            # tout élément peut les porter — et leurs valeurs livrées ne
            # changent rien à ce que l'overlay rend aujourd'hui.
            "opacite": OPACITE_DEFAUT, "rotation": ROTATION_DEFAUT,
            "miroir": MIROIR_DEFAUT, "largeur_max": LARGEUR_DEFAUT}


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
    # Sa cadence (`duree`, `pause`) lui est posée par la boucle de distribution,
    # plus bas, comme celle de tous les autres : un seul écrivain.
    "rotator": _el(50.0, 45.0, "center", 1.0, solo=False),
    "image":   _el(50.0, 50.0, "center", 1.0),
    # Ceux qui s'installent
    "bingo":   _el(3.0, 18.0, "top-left", 0.9, solo=False),
    "stats":   _el(3.0, 60.0, "top-left", 0.9, solo=False),
    "talkers": _el(3.0, 40.0, "top-left", 0.9, solo=False),
    # Une étiquette de titre n'est pas un spectacle : elle s'installe en bas à
    # gauche et laisse Wally à l'écran.
    "music_now": _el(3.0, 92.0, "bottom-left", 0.9, solo=False),
    # Un bilan chiffré s'installe le temps qu'on le lise, pendant que la partie
    # suivante commence : il ne chasse personne.
    "apex_kills": _el(97.0, 18.0, "top-right", 0.9, solo=False),
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


# ── La distribution des réglages de portée ──────────────────────────────────
#
# `ELEMENTS`, `CHAMPS_PROPRES` et `CHAMPS_CHOIX` se remplissent ENSEMBLE, ici.
# Un seul écrivain pour les trois : un champ ne peut plus exister sans ses
# bornes, ni des bornes désigner un champ que personne ne porte.
#
# Et la liste des porteurs est CALCULÉE (`widgets_qui_passent`), jamais écrite à
# la main : une liste manuelle aurait laissé le prochain widget ajouté hors de
# portée du panneau, en silence et pour toujours — c'est le défaut que le
# commentaire d'`ELEMENTS` décrit déjà pour la liste des clés elle-même.


def widgets_qui_passent() -> frozenset[str]:
    """Les éléments montés par `showWidget` : tout `ELEMENTS` sauf `HORS_FILE`."""
    return frozenset(ELEMENTS) - HORS_FILE


def _poser(cle: str, champ: str, defaut, bornes=None, choix=None) -> None:
    """Pose un réglage sur un élément ET sa règle de validation, d'un seul geste."""
    ELEMENTS[cle][champ] = defaut
    if bornes is not None:
        CHAMPS_PROPRES.setdefault(cle, {})[champ] = bornes
    if choix is not None:
        CHAMPS_CHOIX.setdefault(cle, {})[champ] = choix


# `sorted` : l'itération d'un frozenset n'a pas d'ordre stable d'un boot à
# l'autre, et ces deux tables sont SERVIES en JSON au panneau. Sans lui, deux
# réponses décrivant le même état seraient octet pour octet différentes.
for _cle in sorted(widgets_qui_passent()):
    _poser(_cle, "duree", WIDGET_DUREE_DEFAUT,
           (WIDGET_DUREE_MIN, WIDGET_DUREE_MAX, True))
    _poser(_cle, "delai", DELAI_DEFAUT, (DELAI_MIN, DELAI_MAX, False))
    _poser(_cle, "anim_duree", ANIM_DUREE_DEFAUT,
           (ANIM_DUREE_MIN, ANIM_DUREE_MAX, False))
    _poser(_cle, "anim_entree", ANIM_DEFAUT, choix=ANIMS_ENTREE)
    _poser(_cle, "anim_sortie", ANIM_DEFAUT, choix=ANIMS_SORTIE)
    _poser(_cle, "anim_insistance", ANIM_AUCUNE, choix=ANIMS_INSISTANCE)

# La bulle : une durée de réplique, rien d'autre. Elle n'a ni file d'attente ni
# carte — sa sortie est un éclatement écrit dans le CSS, pas une animation
# choisie.
_poser("bubble", "duree", BULLE_DUREE_DEFAUT,
       (BULLE_DUREE_MIN, BULLE_DUREE_MAX, True))

# La galerie : les quatre réglages qui vivaient dans `config.yaml`
# (`overlay_image`). Elle a son propre flux SSE et son propre minuteur, donc pas
# de `delai` ni d'insistance — mais bien une durée et deux animations, qu'elle
# avait déjà. La graine qui recopie les valeurs du fichier vit dans le store.
_poser("image", "duree", WIDGET_DUREE_DEFAUT,
       (WIDGET_DUREE_MIN, WIDGET_DUREE_MAX, True))
_poser("image", "anim_duree", ANIM_DUREE_DEFAUT,
       (ANIM_DUREE_MIN, ANIM_DUREE_MAX, False))
_poser("image", "anim_entree", ANIM_DEFAUT, choix=ANIMS_ENTREE)
_poser("image", "anim_sortie", ANIM_DEFAUT, choix=ANIMS_SORTIE)

# Le rotateur garde sa cadence, avec le sens et les bornes qu'elle a toujours
# eus. Pas d'« auto » sur sa durée : un rotateur à zéro seconde par média
# n'affiche rien, et il n'y a personne derrière pour décider à sa place.
_poser("rotator", "duree", ROTATEUR_DUREE_DEFAUT,
       (ROTATEUR_DUREE_MIN, ROTATEUR_DUREE_MAX, False))
_poser("rotator", "pause", ROTATEUR_PAUSE_DEFAUT,
       (ROTATEUR_PAUSE_MIN, ROTATEUR_PAUSE_MAX, False))

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
    "virus_popup", "music_now", "apex_kills",
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


def _borner_ou_auto(valeur, mini: float, maxi: float, defaut: float) -> float:
    """Comme `_borner`, mais ZÉRO passe au travers.

    Zéro n'est pas une valeur de la plage : c'est le mot « auto », c'est-à-dire
    « laisse le serveur décider », qui est le comportement d'avant ce réglage.
    Le faire remonter au plancher transformerait la valeur LIVRÉE en une durée
    de deux secondes appliquée à tout l'overlay, sur les trois scènes, dès le
    premier rebuild — et une largeur maximale de 120 px écraserait chaque carte.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return defaut
    if valeur != valeur:            # NaN, avant toute comparaison
        return defaut
    if float(valeur) == 0.0:
        return 0.0
    return _borner(valeur, mini, maxi, defaut)


def _fusionner_element(cle: str, brut, defaut: dict) -> dict:
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
    # Les quatre universels : tout élément passe par `placer()`, donc tout
    # élément les porte. Lus dans `CHAMPS_UNIVERSELS`, qui est aussi ce que la
    # route sert au panneau — une seule autorité sur ce qui existe et sur ses
    # bornes. `largeur_max` garde son zéro, qui rend la main au CSS au lieu
    # d'écraser la carte ; `miroir` est un booléen, d'où l'entrée à `None`.
    for nom, bornes in CHAMPS_UNIVERSELS.items():
        if bornes is None:
            fusionne[nom] = (bool(brut[nom]) if brut.get(nom) is not None
                             else defaut[nom])
            continue
        mini, maxi, auto = bornes
        borne = _borner_ou_auto if auto else _borner
        fusionne[nom] = borne(brut.get(nom), mini, maxi, defaut[nom])
    # Les réglages propres à CET élément-là. La table est indexée par élément :
    # `duree` ne se borne pas pareil sur le rotateur (durée d'un média, 1–120 s)
    # et sur un widget qui passe (durée d'un passage, 2–180 s, ou auto).
    for nom, (mini, maxi, auto) in CHAMPS_PROPRES.get(cle, {}).items():
        borne = _borner_ou_auto if auto else _borner
        fusionne[nom] = borne(brut.get(nom), mini, maxi, defaut[nom])
    # Les réglages à CHOIX : validés par appartenance, pas par bornes. Un nom
    # inconnu — faute de frappe, animation retirée d'animate.css, sortie
    # proposée en entrée — reprend le défaut, comme tout le reste ici.
    for nom, choix in CHAMPS_CHOIX.get(cle, {}).items():
        valeur = brut.get(nom)
        fusionne[nom] = (valeur if isinstance(valeur, str) and valeur in choix
                         else defaut[nom])
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
    # ── Un widget NEUF ne s'invite pas en plein live ──────────────────────
    #
    # Cette boucle parcourt `ELEMENTS`, pas ce que la scène a enregistré : un
    # widget ajouté au code apparaissait donc sur les TROIS scènes, à sa
    # position par défaut et VISIBLE, dès le rebuild. En clair, on ne pouvait
    # pas ajouter un widget sans le montrer aux viewers pour l'essayer.
    #
    # Une scène qui a déjà des éléments enregistrés a été placée par quelqu'un.
    # Ce qu'elle ne connaît pas est donc arrivé APRÈS elle, et n'a été voulu par
    # personne à cet endroit : il naît masqué, et s'active depuis le panneau
    # — sur une scène d'essai, tranquillement, avant de le montrer.
    #
    # `elements_bruts` vide = première écriture du layout : on garde alors les
    # défauts livrés, sinon un tout premier boot rendrait un overlay vide.
    deja_placee = bool(elements_bruts)

    def _defaut_de(cle: str, defaut: dict) -> dict:
        if deja_placee and cle not in elements_bruts:
            return {**defaut, "hidden": True}
        return defaut

    elements = {
        cle: _fusionner_element(cle, elements_bruts.get(cle), _defaut_de(cle, defaut))
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
