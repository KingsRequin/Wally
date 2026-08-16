"""Remettre un élément — ou une scène — à ses valeurs d'origine.

Ce qui se joue ici tient en une phrase : **les défauts viennent du serveur**
(`GET /api/admin/overlay/layout?defauts=1`), jamais d'une copie écrite dans le
navigateur. Deux tables auraient divergé à la première évolution du modèle, et
« remettre à l'origine » aurait alors rendu une position QUI N'EST PLUS celle
d'origine — le pire des deux mondes, puisqu'on croit revenir à un état connu.
Le côté serveur est vérifié dans `test_overlay_layout_routes.py` ; ici, le
panneau.

Trois propriétés :

  1. Un reset rend TOUS les champs, `hidden` compris — un reset qui laisserait
     la visibilité derrière ne serait pas un reset.
  2. `locked` n'est jamais réécrit, et un élément verrouillé est écarté : une
     garde qu'une opération peut lever n'en est pas une.
  3. Le chiffre annoncé ne compte que ce qui change vraiment.

Ces tests échouent sur le code d'avant : `planReinitialisation`,
`appliquerReinitialisation` et `elementsDefaut` n'existaient pas.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
global.navigator = {};
require(%s);
require(%s);
const OA = window.OverlayAdmin;

function el(o) {
  return Object.assign({x: 50, y: 50, anchor: "center", scale: 1,
                        hidden: false, locked: false, solo: true,
                        wally_visible: false}, o);
}
function scene(slug, nom, elements) {
  const base = {avatar: el({}), bingo: el({}), meme: el({})};
  Object.keys(elements || {}).forEach(function (c) { base[c] = el(elements[c]); });
  return {slug: slug, nom: nom, ordre: ["avatar", "bingo", "meme"],
          groupes: [], elements: base};
}
/** Ce que la route `?defauts=1` rendrait : la LIVRAISON, pas ce qui est rangé. */
function livraison() {
  return {version: 1, defaut: "jeu", scenes: [
    {slug: "jeu", nom: "En jeu",
     ordre: ["bingo", "avatar", "meme"],
     groupes: [{id: "g", nom: "Livré", membres: ["avatar", "meme"]}],
     elements: {avatar: el({x: 97, y: 80, anchor: "bottom-right", scale: 0.55}),
                bingo: el({x: 3, y: 18, anchor: "top-left", scale: 0.9}),
                meme: el({})}},
  ]};
}
""" % (json.dumps(str(_STATIC / "overlay_layout.js")),
       json.dumps(str(_STATIC / "overlay_admin.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def test_un_element_retrouve_exactement_sa_valeur_dorigine():
    """Tous ses champs, visibilité comprise. Pas seulement le placement."""
    out = _node("""
    const s = scene("jeu", "En jeu", {
      bingo: {x: 12.5, y: 71, anchor: "bottom-left", scale: 0.7, hidden: true,
              solo: true, wally_visible: true},
    });
    const origine = OA.elementsDefaut(livraison(), "jeu");
    const plan = OA.planReinitialisation(s, ["bingo"], origine);
    OA.appliquerReinitialisation(s, plan.change, origine);
    console.log(JSON.stringify(s.elements.bingo));
    """)
    assert json.loads(out) == {
        "x": 3, "y": 18, "anchor": "top-left", "scale": 0.9,
        "hidden": False, "locked": False, "solo": True, "wally_visible": False,
    }


def test_les_defauts_sortent_du_serveur_scene_par_scene_ou_a_defaut_la_premiere():
    """Une scène créée à la main n'a pas de scène d'origine à son nom : toutes
    les scènes livrées portent la même copie d'`ELEMENTS`, la première fait
    donc l'affaire — mais elle est prise EXPLICITEMENT, pas par hasard."""
    out = _node("""
    console.log(JSON.stringify({
      connue: OA.elementsDefaut(livraison(), "jeu").bingo.x,
      inconnue: OA.elementsDefaut(livraison(), "ma-scene-a-moi").bingo.x,
      vide: Object.keys(OA.elementsDefaut({scenes: []}, "jeu")).length,
    }));
    """)
    assert json.loads(out) == {"connue": 3, "inconnue": 3, "vide": 0}


def test_un_element_verrouille_est_ecarte_et_son_verrou_nest_jamais_reecrit():
    """Une garde qu'une opération peut lever n'en est pas une."""
    out = _node("""
    const s = scene("jeu", "En jeu", {bingo: {x: 90, locked: true}});
    const origine = OA.elementsDefaut(livraison(), "jeu");
    const plan = OA.planReinitialisation(s, ["bingo", "avatar"], origine);
    OA.appliquerReinitialisation(s, plan.change, origine);
    console.log(JSON.stringify({
      bloques: plan.bloques, change: plan.change,
      bingoX: s.elements.bingo.x, bingoVerrou: s.elements.bingo.locked,
    }));
    """)
    assert json.loads(out) == {
        "bloques": ["bingo"], "change": ["avatar"],
        "bingoX": 90, "bingoVerrou": True,
    }


def test_un_element_deja_dorigine_ne_compte_pas_dans_lannonce():
    """« 3 éléments remis à zéro » sur une scène déjà d'origine serait faux."""
    out = _node("""
    const s = scene("jeu", "En jeu", {
      avatar: {x: 97, y: 80, anchor: "bottom-right", scale: 0.55},
      bingo: {x: 3, y: 18, anchor: "top-left", scale: 0.9},
      meme: {x: 12},
    });
    const plan = OA.planReinitialisation(s, ["avatar", "bingo", "meme"],
                                         OA.elementsDefaut(livraison(), "jeu"));
    console.log(JSON.stringify(plan));
    """)
    assert json.loads(out) == {"change": ["meme"], "bloques": []}


def test_lempilement_et_les_groupes_dorigine_sont_lisibles_a_part():
    """Ils ne repartent que sur « toute la scène » : remettre l'ordre d'origine
    parce qu'on a réinitialisé un dé serait un effet de bord découvert après."""
    out = _node("""
    const s = OA.defautsStructure(livraison(), "jeu");
    console.log(JSON.stringify({ordre: s.ordre, groupes: s.groupes.length}));
    """)
    assert json.loads(out) == {"ordre": ["bingo", "avatar", "meme"], "groupes": 1}
