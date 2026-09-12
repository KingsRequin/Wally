"""Les cartes ACTION et PASSIF du TCG du Purgatoire — le LECTEUR de leur source.

Pendant de `bot/core/tcg_cartes.py`, qui ne lit que les HÉROS. Même régime : la
donnée vit dans `tcg/cartes_action.yaml`, ce module la lit au boot, la VALIDE
et la sert. Corriger une carte ne demande donc pas de rebuild.

🚨 Deux catalogues et pas un seul, alors que les deux servent la même page.
C'est délibéré : un héros et une carte action n'ont **aucun champ en commun**
au-delà du nom. Le héros porte atk/pv/aura, une rareté, un budget vérifié, et
quatre couches d'illustration cadrées à la main ; la carte action porte un
type, une catégorie, un coût et un pochoir. Les fondre donnerait une dataclass
dont les deux tiers des champs sont vides pour la moitié des lignes, et une
validation qui devrait d'abord deviner à quelle famille elle a affaire.

🚨 Rien ici n'est calculé et rien ne le sera : le moteur de règles vit
ailleurs. Une règle dupliquée est une porte de triche ouverte.
"""

from __future__ import annotations

import hashlib
from dataclasses import MISSING, dataclass, fields
from pathlib import Path

import yaml
from loguru import logger

from bot.core.tcg_cartes import DOSSIER_ASSETS

CHEMIN_CARTES_ACTION = Path("tcg/cartes_action.yaml")

# Ce qui s'écrit sur une carte dont la règle n'est pas arrêtée. Le mot part
# jusqu'à l'écran : 28 des 46 cartes le portent, et aucune valeur de
# remplissage n'est servie « en attendant ». Un placeholder qui ressemble à une
# donnée finit par être lu comme une donnée.
INDEFINI = "INDÉFINI"


def url(visuel: str) -> str:
    """Le chemin d'un pochoir, versionné par l'empreinte de son contenu.

    🚨 Ce n'est PAS `tcg_cartes.url`, et ça ne peut pas l'être : celui des
    héros ajoute `.avif` au nom et APLATIT le chemin (`Path(base).name`), parce
    qu'une illustration de héros vit à plat dans `assets/` en paire AVIF+WebP.
    Les pochoirs d'ici sont des SVG servis tels quels, en sous-dossier
    (`icones/`, `apex/`). Le réutiliser chercherait
    `assets/full-pizza.svg.avif`, ne le trouverait jamais, et journaliserait un
    avertissement à chaque carte de chaque chargement de page.

    ⚠️ Un fichier manquant ne doit pas empêcher le boot — mais ici il ne peut
    pas arriver : `_lire()` refuse déjà le catalogue si le pochoir n'existe
    pas. Le repli est là pour le cas où le fichier disparaît APRÈS le boot.
    """
    chemin = DOSSIER_ASSETS / visuel.removeprefix("/assets/")
    try:
        marque = hashlib.sha256(chemin.read_bytes()).hexdigest()[:8]
    except OSError as exc:
        logger.warning("TCG : pochoir illisible, URL non versionnée "
                       "({p}) : {e!r}", p=chemin, e=exc)
        return visuel
    return f"{visuel}?v={marque}"

# Le TYPE tient le CADRE de la carte, la CATÉGORIE tient le BANDEAU du haut.
# Deux dimensions, jamais mélangées — une carte de soin passive et une carte de
# soin active partagent le vert et rien d'autre.
TYPES = ("action", "passif")

# 🚨 La FORME du pochoir dans la fenêtre d'illustration, telle que le design la
# pose : une `icone` rend un CARRÉ de 7,4em, une `image` rend 82 % × 7,4em.
# Ce n'est pas un détail de cadrage — un pictogramme et un dessin n'ont pas le
# même poids visuel, et le design les traite comme deux choses différentes
# (`icone:` contre `image:` dans son catalogue). Rendre tout en carré, comme je
# l'avais fait, rapetisse les dessins sans que rien ne le signale.
FORMES = ("icone", "image")
CATEGORIES = ("attaque", "soin", "controle", "aura", "ressource")

# 🚨 L'or (#e1a947) est RÉSERVÉ à la pastille de coût, sur le recto comme ici :
# aucune catégorie ne le porte. L'Aura était or dans le premier jet du design,
# elle est passée en baie pour ça — deux choses différentes de la même couleur
# au même endroit se lisent comme la même chose.
#
# Les teintes sont SOURDES et non des couleurs de TCG : le fond de la carte est
# #12100c, un rouge vif dessus en ferait un autocollant. Chacune tient 4,5:1
# contre la crème, pour que l'étiquette reste lisible.
COULEUR_CATEGORIE = {
    "attaque": "#b23b2e",
    "soin": "#3d6e46",
    "controle": "#7a5296",
    "aura": "#ad3f63",
    "ressource": "#35707d",
}

# L'icône du bandeau. Elle est celle de la CATÉGORIE et pas celle de la carte :
# identique sur les dix cartes d'attaque, c'est elle qui rend la famille
# lisible d'un coup d'œil. La grande illustration, elle, est propre à la carte.
ICONE_CATEGORIE = {
    "attaque": "/assets/icones/swords-power.svg",
    "soin": "/assets/icones/remedy.svg",
    "controle": "/assets/icones/grab.svg",
    "aura": "/assets/icones/beams-aura.svg",
    "ressource": "/assets/icones/test-tube-rack.svg",
}

LIBELLE_CATEGORIE = {
    "attaque": "ATTAQUE",
    "soin": "SOIN",
    "controle": "CONTRÔLE",
    "aura": "AURA",
    "ressource": "RESSOURCE",
}


@dataclass(frozen=True, slots=True)
class CarteAction:
    """Une carte action ou passive, telle qu'elle s'affiche.

    ⚠️ `visuel` porte son extension, CONTRAIREMENT aux héros : ce sont des SVG
    servis tels quels, il n'y a pas de paire AVIF + repli WebP à composer.

    ⚠️ `cout = 0` ne veut pas dire gratuit, il veut dire **non calibré** — le
    coût se pose une fois l'effet arrêté (arbitrage de l'owner du 2026-09-12).
    Le front l'affiche comme tel plutôt que de servir un chiffre décidé par
    personne.
    """

    cle: str
    nom: str
    court: str
    type: str
    categorie: str
    cout: int = 0
    regle: str = INDEFINI
    # Le pochoir. Absent quand la carte porte un `texte` à la place — ou, en
    # dernier recours, quand rien n'est décidé : elle retombe alors sur l'icône
    # de sa catégorie, ce qui reste honnête (aucune carte ne rend un trou).
    visuel: str | None = None
    forme: str = "icone"
    # Un mot posé à la taille d'une illustration. « FEUR » n'a pas d'objet à
    # dessiner, il a une réplique.
    texte: str | None = None
    # Carte À REGROUPER : elle compte pour UNE carte du deck mais en donne
    # `groupe` à la table. Le rendu en tire autant d'exemplaires numérotés,
    # plus la carte complète.
    groupe: int = 0
    # Le pochoir répété. `arc` le range en courbe au lieu de le semer : le
    # semis dit « en vrac », l'arc dit « ensemble ».
    semis: int = 0
    arc: bool = False
    face_cachee: bool = False


_CHAMPS = {f.name for f in fields(CarteAction)}
_OBLIGATOIRES = {f.name for f in fields(CarteAction) if f.default is MISSING}


def _exiger(condition: bool, cle: str, probleme: str) -> None:
    """Refuse le fichier en NOMMANT la carte et le problème.

    On lève, et le bot ne démarre pas — même choix que pour les héros : une
    carte ignorée en silence, c'est un cadre vide découvert en direct.
    """
    if not condition:
        raise ValueError(f"{CHEMIN_CARTES_ACTION} — carte {cle} : {probleme}")


def _lire(chemin: Path) -> dict[str, CarteAction]:
    """Le fichier des cartes action, validé, dans son ordre d'écriture."""
    entrees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    cartes: dict[str, CarteAction] = {}
    for rang, entree in enumerate(entrees or [], start=1):
        cle = entree.get("cle", f"sans clé, en position {rang}")
        _exiger(not (set(entree) - _CHAMPS), cle,
                f"champ inconnu {sorted(set(entree) - _CHAMPS)}")
        _exiger(not (_OBLIGATOIRES - set(entree)), cle,
                f"champ obligatoire manquant {sorted(_OBLIGATOIRES - set(entree))}")
        _exiger(entree["cle"] not in cartes, cle, "clé en double")
        carte = CarteAction(**entree)
        _exiger(carte.type in TYPES, cle,
                f"type={carte.type!r} hors de {sorted(TYPES)}")
        _exiger(carte.categorie in CATEGORIES, cle,
                f"categorie={carte.categorie!r} hors de {sorted(CATEGORIES)}")
        _exiger(carte.forme in FORMES, cle,
                f"forme={carte.forme!r} hors de {sorted(FORMES)}")
        _exiger(carte.cout >= 0, cle, f"cout={carte.cout!r} négatif")
        _exiger(carte.groupe >= 0, cle, f"groupe={carte.groupe!r} négatif")
        _exiger(carte.semis >= 0, cle, f"semis={carte.semis!r} négatif")
        # Une carte à regrouper ET semée n'a pas de rendu : les deux se
        # disputent la fenêtre d'illustration. Le refuser ici plutôt que de
        # laisser le front en choisir un en silence.
        _exiger(not (carte.groupe and carte.semis), cle,
                "groupe et semis ensemble : les deux occupent la fenêtre")
        _exiger(not (carte.visuel and carte.texte), cle,
                "visuel et texte ensemble : les deux occupent la fenêtre")
        _exiger(not carte.arc or bool(carte.semis), cle,
                "arc sans semis : il n'y a rien à ranger en courbe")
        if carte.visuel is not None:
            # 🚨 Le fichier doit EXISTER. Un pochoir mort rendrait un cadre vide
            # annoncé comme illustré — exactement ce que la règle d'entrée des
            # héros interdit, pour la même raison.
            _exiger(carte.visuel.startswith("/assets/"), cle,
                    f"visuel mal formé : {carte.visuel!r}")
            sur_disque = DOSSIER_ASSETS / carte.visuel.removeprefix("/assets/")
            _exiger(sur_disque.is_file(), cle,
                    f"visuel introuvable sur le disque : {sur_disque}")
        cartes[carte.cle] = carte
    return cartes


CARTES_ACTION: dict[str, CarteAction] = _lire(CHEMIN_CARTES_ACTION)


def par_categorie() -> list[CarteAction]:
    """Les cartes rangées par catégorie, puis dans l'ordre du fichier.

    C'est l'ordre de la planche du design : les familles se suivent, et à
    l'intérieur d'une famille l'ordre d'écriture est gardé. Le tri est fait ici
    et pas dans la page — le rang d'une carte appartient à la carte, et une
    page qui le recalculerait finirait par en avoir sa propre idée.
    """
    rang = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(CARTES_ACTION.values(), key=lambda c: rang[c.categorie])


def en_json(carte: CarteAction) -> dict:
    """Une carte telle que le front la lit.

    Les clés partent en **camelCase**, comme celles des héros : c'est le
    vocabulaire du composant de rendu.

    La couleur, l'icône et le libellé de la catégorie sont SERVIS et non
    recopiés en JS. Une table de correspondance dupliquée dans le front
    diverge le jour où une teinte bouge, et personne ne le voit — le bandeau
    garde alors l'ancienne couleur pendant que le cadre prend la nouvelle.

    Le pochoir sort **versionné** par l'empreinte de son contenu (`url`) : la
    zone Cloudflare écrase le `Cache-Control` de l'origine, et sans ça une
    icône retouchée resterait figée chez chaque visiteur.
    """
    return {
        "cle": carte.cle,
        "nom": carte.nom,
        "court": carte.court,
        "type": carte.type,
        "categorie": carte.categorie,
        "categorieLabel": LIBELLE_CATEGORIE[carte.categorie],
        "categorieCouleur": COULEUR_CATEGORIE[carte.categorie],
        "categorieIcone": url(ICONE_CATEGORIE[carte.categorie]),
        "cout": carte.cout,
        "regle": carte.regle,
        # `None` et non `""` : le front teste la présence, et une chaîne vide
        # est fausse en JavaScript sans pour autant dire « absent ».
        "visuel": url(carte.visuel) if carte.visuel else None,
        "forme": carte.forme,
        "texte": carte.texte,
        "groupe": carte.groupe,
        "semis": carte.semis,
        "arc": carte.arc,
        "faceCachee": carte.face_cachee,
    }
