"""Annuler et refaire les gestes du brouillon — Ctrl+Z, Ctrl+Y.

À ne pas confondre avec « Annuler la publication », qui est un cran unique sur
ce qui est à l'ANTENNE. Celui-ci défait des gestes d'édition, sans toucher au
serveur.

Trois propriétés, et la troisième est celle qui rend l'outil utilisable :

  1. Dix gestes se défont en dix annulations, et Ctrl+Y refait le chemin.
  2. Le compteur de modifications suit : sans lui, dix annulations
     ramèneraient la disposition de départ en affichant « 10 modifications non
     publiées ».
  3. **Un geste = un pas.** Taper « 12.5 » dans un champ produit quatre
     événements `input` ; quatre pas videraient les vingt disponibles sur un
     seul champ. Les événements rapprochés de MÊME SOURCE fusionnent — mais
     seulement ceux-là : un alignement qui suivrait une frappe de près reste un
     pas à lui.

Plus la règle de tous les éditeurs : partir dans une autre direction après une
annulation efface ce qui était refaisable.

Ces tests échouent sur le code d'avant : `histoire`, `pousserHistoire` et
`annulerHistoire` n'existaient pas — il n'y avait qu'un cran, sur la
publication.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
global.navigator = {};
// `rendreTout()` et les notifications touchent au DOM et au réseau : le panneau
// n'est pas monté ici, ils n'ont donc aucun nœud à trouver et sortent d'eux-
// mêmes (`if (!liste || ...) return`). C'est exactement ce qu'on veut mesurer :
// l'état, pas l'affichage.
global.document = {activeElement: null, querySelectorAll: function () { return []; }};
require(%s);
require(%s);
const OA = window.OverlayAdmin;

function el(o) {
  return Object.assign({x: 50, y: 50, anchor: "center", scale: 1,
                        hidden: false, locked: false, solo: true,
                        wally_visible: false}, o);
}
function poser() {
  OA.etat.layout = {version: 1, defaut: "jeu", scenes: [{
    slug: "jeu", nom: "En jeu", ordre: ["bingo"], groupes: [],
    elements: {bingo: el({})},
  }]};
  OA.etat.slugCourant = "jeu";
  OA.etat.brouillon = 0;
  OA.etat.direct = false;
  OA.reinitialiserHistoire();
}
function bingo() { return OA.etat.layout.scenes[0].elements.bingo; }
/** Un geste : on bouge, puis on marque — comme tous les appelants du panneau. */
function geste(x, source) {
  bingo().x = x;
  OA.marquerModifie(source);
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


def test_dix_gestes_puis_dix_annulations_ramenent_au_point_de_depart():
    """Et dix Ctrl+Y refont le chemin, valeur par valeur."""
    out = _node("""
    poser();
    const depart = bingo().x;
    for (let i = 1; i <= 10; i++) geste(i * 3, null);
    const apres10 = bingo().x;
    const remonte = [];
    for (let i = 0; i < 10; i++) { OA.annulerHistoire(); remonte.push(bingo().x); }
    const redescente = [];
    for (let i = 0; i < 10; i++) { OA.refaireHistoire(); redescente.push(bingo().x); }
    console.log(JSON.stringify({depart: depart, apres10: apres10,
                                remonte: remonte, redescente: redescente,
                                brouillon: OA.etat.brouillon}));
    """)
    data = json.loads(out)
    assert data["depart"] == 50
    assert data["apres10"] == 30
    # Dix annulations : on redescend 27, 24 … 3, puis le point de départ.
    assert data["remonte"] == [27, 24, 21, 18, 15, 12, 9, 6, 3, 50]
    assert data["redescente"] == [3, 6, 9, 12, 15, 18, 21, 24, 27, 30]
    assert data["brouillon"] == 10


def test_le_compteur_de_modifications_suit_lhistorique():
    """Sinon on revient à la disposition de départ en lisant « 10 en attente »."""
    out = _node("""
    poser();
    for (let i = 1; i <= 4; i++) geste(i * 3, null);
    const suite = [OA.etat.brouillon];
    for (let i = 0; i < 4; i++) { OA.annulerHistoire(); suite.push(OA.etat.brouillon); }
    OA.refaireHistoire(); suite.push(OA.etat.brouillon);
    console.log(JSON.stringify(suite));
    """)
    assert json.loads(out) == [4, 3, 2, 1, 0, 1]


def test_une_rafale_de_meme_source_ne_compte_que_pour_un_pas():
    """Taper « 12.5 » dans le champ X, c'est UN geste — pas quatre.

    Le test rejoue la séquence exacte du champ : `input` à chaque caractère.
    """
    out = _node("""
    poser();
    // Quatre `input` d'affilée sur le même champ, comme une frappe.
    ["1", "12", "12.", "12.5"].forEach(function (v) {
      bingo().x = Number(v) || 0;
      OA.marquerModifie("champ:x");
    });
    const apresFrappe = {pas: OA.histoire.pile.length, x: bingo().x};
    // Puis un geste d'une AUTRE nature, tout de suite après : un pas à lui.
    bingo().y = 12;
    OA.marquerModifie(null);
    const apresAutre = OA.histoire.pile.length;
    // Une annulation ramène à la frappe entière, pas à « 12. ».
    OA.annulerHistoire();
    OA.annulerHistoire();
    console.log(JSON.stringify({apresFrappe: apresFrappe, apresAutre: apresAutre,
                                x: bingo().x, y: bingo().y}));
    """)
    data = json.loads(out)
    # Point de départ + la frappe entière = 2 entrées.
    assert data["apresFrappe"] == {"pas": 2, "x": 12.5}
    assert data["apresAutre"] == 3
    # Deux annulations : on remonte au-delà de la frappe, jusqu'au départ.
    assert data["x"] == 50 and data["y"] == 50


def test_repartir_dans_une_autre_direction_efface_le_refaisable():
    """La règle de tous les éditeurs. L'ignorer rendrait un Ctrl+Y vers un état
    qui n'a jamais suivi celui-ci."""
    out = _node("""
    poser();
    geste(10, null); geste(20, null); geste(30, null);
    OA.annulerHistoire(); OA.annulerHistoire();   // on est à x = 10
    geste(77, null);                              // autre direction
    const avant = {x: bingo().x, pas: OA.histoire.pile.length,
                   index: OA.histoire.index};
    OA.refaireHistoire();                         // il n'y a plus rien devant
    console.log(JSON.stringify({avant: avant, apres: bingo().x}));
    """)
    data = json.loads(out)
    # Départ, 10, 77 : les instantanés 20 et 30 sont partis.
    assert data["avant"] == {"x": 77, "pas": 3, "index": 2}
    assert data["apres"] == 77


def test_la_pile_est_bornee_a_une_vingtaine_de_pas():
    """Chaque instantané est le modèle ENTIER : ce n'est pas un éditeur de
    texte, et une pile sans borne finirait par peser lourd pour rien."""
    out = _node("""
    poser();
    for (let i = 1; i <= 60; i++) geste(i, null);
    let n = 0;
    while (OA.histoire.index > 0) { OA.annulerHistoire(); n++; }
    console.log(JSON.stringify({pas: OA.HISTOIRE_PAS, pile: OA.histoire.pile.length,
                                annulations: n, x: bingo().x}));
    """)
    data = json.loads(out)
    assert data["pas"] == 20
    assert data["pile"] == 21          # vingt pas annulables + l'état courant
    assert data["annulations"] == 20
    # On remonte à l'état 40 : les trente-neuf premiers sont sortis de la pile.
    assert data["x"] == 40


def test_une_reponse_du_serveur_repart_dune_pile_neuve():
    """« Annuler » vers un modèle sans rapport avec ce qui est à l'antenne
    serait pire que de ne pas pouvoir annuler du tout."""
    out = _node("""
    poser();
    geste(10, null); geste(20, null);
    OA.reinitialiserHistoire();      // ce que fait `adopter()`
    const avant = {pile: OA.histoire.pile.length, index: OA.histoire.index};
    OA.annulerHistoire();
    console.log(JSON.stringify({avant: avant, x: bingo().x}));
    """)
    assert json.loads(out) == {"avant": {"pile": 1, "index": 0}, "x": 20}
