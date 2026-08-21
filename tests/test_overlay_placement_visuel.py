"""Opacité, inclinaison, miroir et largeur maximale — le rendu visuel réglé.

Les quatre passent par `placer()` / `styleDepuisElement()` (overlay_layout.js),
point d'écriture UNIQUE du style d'un élément sur la page. On exécute vraiment
la fonction sous node : ce qu'elle produit ne se lit pas dans le code — une
chaîne `transform` est juste ou fausse selon l'ORDRE de ses facteurs, et l'ordre
a déjà coûté un widget centré qui atterrissait à 30 % de large.

Le piège central, celui qui a fait renoncer à la solution d'origine : le
conteneur a son `transform-origin` sur un COIN (`right bottom` pour l'avatar).
Une rotation posée là tourne l'élément autour de son point d'ancrage, donc le
DÉPLACE en l'inclinant. Elle doit être encadrée par un aller-retour qui ramène
l'origine au centre — et le SENS de cet aller-retour dépend du coin.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
require(%s);
const L = window.WallyLayout;
""" % json.dumps(str(_STATIC / "overlay_layout.js"))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def _style(el: dict) -> dict:
    """Le style que la page appliquerait vraiment à cet élément."""
    src = _PRELUDE + "console.log(JSON.stringify(L.styleDepuisElement(%s)));" \
        % json.dumps(el)
    r = subprocess.run(["node", "-e", src], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _el(**kw) -> dict:
    base = {"x": 50.0, "y": 50.0, "anchor": "center", "scale": 1.0,
            "opacite": 1.0, "rotation": 0.0, "miroir": False,
            "largeur_max": 0.0}
    base.update(kw)
    return base


def test_sans_reglage_la_chaine_de_transform_est_celle_davant():
    """LE test qui protège le live : tant que personne n'a rien réglé, la page
    doit produire EXACTEMENT ce qu'elle produisait avant ce chantier. Un
    aller-retour de recentrage posé inconditionnellement changerait la chaîne
    sur les trente-sept éléments des trois scènes, pour rien."""
    assert _style(_el())["transform"] == "scale(1) translate(-50%, -50%)"


def test_une_inclinaison_tourne_autour_du_centre_pas_du_coin():
    """`translate(50%, 50%) … translate(-50%, -50%)` autour du `rotate` : sans
    lui, l'élément tourne autour de son point d'ancrage et se DÉPLACE à l'écran
    en même temps qu'il s'incline."""
    t = _style(_el(rotation=15.0))["transform"]
    assert "rotate(15deg)" in t
    avant = t.index("translate(50%, 50%)")
    apres = t.index("translate(-50%, -50%)", t.index("rotate("))
    assert avant < t.index("rotate(") < apres


def test_le_sens_du_recentrage_suit_le_coin_dancrage():
    """L'avatar est ancré en bas à droite : son `transform-origin` est le coin
    `right bottom`. Y ajouter `translate(50%, 50%)` viserait un point HORS de
    l'élément — le recentrage doit partir dans l'autre sens."""
    t = _style(_el(anchor="bottom-right", rotation=10.0))["transform"]
    assert "translate(-50%, -50%) rotate(10deg)" in t
    haut_gauche = _style(_el(anchor="top-left", rotation=10.0))["transform"]
    assert "translate(50%, 50%) rotate(10deg)" in haut_gauche


def test_le_miroir_se_retourne_lui_aussi_sur_place():
    t = _style(_el(miroir=True))["transform"]
    assert "scaleX(-1)" in t
    assert "translate(50%, 50%)" in t and "rotate(0deg)" in t


def test_le_miroir_sapplique_avant_linclinaison():
    """« Je retourne l'image, PUIS je l'incline de 10° ». Dans l'autre ordre, le
    miroir inverserait le sens de l'inclinaison — on tourne le curseur vers la
    droite et l'élément part à gauche."""
    t = _style(_el(rotation=10.0, miroir=True))["transform"]
    assert t.index("rotate(10deg)") < t.index("scaleX(-1)")


def test_lechelle_dancrage_reste_en_tete_de_chaine():
    """`scale` AVANT `translate`, et pas l'inverse : les pourcentages d'un
    `translate` se mesurent sur la taille NON transformée. C'est l'ordre déjà
    payé une fois — le recentrage ne doit pas s'y insérer."""
    t = _style(_el(scale=0.5, rotation=20.0))["transform"]
    assert t.startswith("scale(0.5) translate(-50%, -50%)")


def test_lopacite_est_posee_telle_quelle():
    assert _style(_el(opacite=0.4))["opacity"] == "0.4"


def test_une_opacite_absente_ne_pose_rien():
    """Un layout rangé avant ce chantier n'a pas le champ. Poser `opacity: 0`
    par défaut effacerait tout l'overlay."""
    vieux = {"x": 50.0, "y": 50.0, "anchor": "center", "scale": 1.0}
    assert _style(vieux)["opacity"] == ""


def test_la_largeur_max_est_en_pixels_du_canvas():
    assert _style(_el(largeur_max=600.0))["maxWidth"] == "600px"


def test_une_largeur_max_a_zero_rend_la_main_au_css():
    """Zéro vaut AUTO : le `max-width: 92vw` du conteneur reprend. Poser
    « 0px » écraserait la carte à rien."""
    assert _style(_el(largeur_max=0.0))["maxWidth"] == ""


def test_les_cartes_acceptent_de_retrecir_sous_un_plafond():
    """`largeur_max` ne peut RIEN réduire sans `min-width: 0` sur les items de
    grille : ils valent `min-width: auto` par défaut — « jamais plus étroit que
    mon contenu ». Mesuré au navigateur avant correction : le conteneur passait
    bien à 167 px, la carte restait à 250 et débordait. Et comme le placement se
    calcule sur la boîte du CONTENEUR (`translate(-50%)`), le widget se
    retrouvait décalé par-dessus le marché.

    Un réglage qui ne réduit rien ET déplace l'élément est pire que pas de
    réglage — c'est le trou que ce test ferme."""
    html = (_STATIC / "overlay.html").read_text(encoding="utf-8")
    regle = html[html.index("[data-element] > * {"):]
    assert "min-width: 0" in regle[:120]
