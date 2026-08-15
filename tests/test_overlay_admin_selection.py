"""L'édition multiple du panneau de mise en scène, vérifiée hors navigateur.

Trois calculs décident de tout ce que la sélection multiple promet, et aucun
n'est lisible à l'œil :

  1. `bornerDelta` — le déplacement COMMUN d'un bloc. Borner chaque élément
     séparément est le réflexe, et il déforme la sélection sans retour.
  2. `positionAlignee` — le piège central. `x` désigne le POINT D'ANCRAGE, pas
     le bord gauche : « coller à droite » n'est PAS `x = 100`, et un élément
     ancré à gauche à qui on pose `x = 100` sort entièrement du cadre.
  3. `repartitionEgale` — l'espacement égal, extrêmes figés.

Le code est chargé dans node avec un `window` nu : ces trois fonctions sont
pures, elles ne touchent ni au DOM ni au réseau.

Ces tests échouent tous sur le code d'avant (les fonctions n'existaient pas).
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
const W = 800, H = 450;          // une surface plausible du panneau
const ANCRAGES = [
  "top-left", "top-center", "top-right",
  "middle-left", "center", "middle-right",
  "bottom-left", "bottom-center", "bottom-right",
];
function el(o) {
  return Object.assign({x: 50, y: 50, anchor: "center", scale: 1,
                        hidden: false, locked: false}, o);
}
function proche(a, b, tol) {
  if (Math.abs(a - b) > (tol === undefined ? 1e-9 : tol)) {
    throw new Error("attendu " + b + ", obtenu " + a);
  }
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


# ── Le déplacement d'un bloc ────────────────────────────────────────────────

def test_un_bloc_libre_recoit_le_deplacement_demande():
    """Sans bord en vue, le décalage passe tel quel."""
    out = _node("""
      const g = [{depart: {x: 20, y: 30}}, {depart: {x: 40, y: 50}}];
      const d = OA.bornerDelta(g, 7.5, -12.25);
      proche(d.x, 7.5); proche(d.y, -12.25);
      console.log("ok");
    """)
    assert out == "ok"


def test_le_bloc_s_arrete_ENTIER_au_premier_bord_touche():
    """Le cœur du glisser à plusieurs.

    Trois éléments, celui de droite à 95 % : demander +20 doit rendre +5 pour
    TOUT LE MONDE. Borné élément par élément, le troisième se serait arrêté à
    100 pendant que les deux autres avançaient de 20 — les écarts perdus, sans
    moyen de les retrouver.
    """
    out = _node("""
      const g = [{depart: {x: 10, y: 20}}, {depart: {x: 30, y: 40}},
                 {depart: {x: 95, y: 60}}];
      const d = OA.bornerDelta(g, 20, 0);
      proche(d.x, 5);
      // et dans l'autre sens, c'est le premier qui commande
      const d2 = OA.bornerDelta(g, -20, 0);
      proche(d2.x, -10);
      console.log("ok");
    """)
    assert out == "ok"


def test_les_ecarts_survivent_exactement_a_un_deplacement_borne():
    """La promesse tenue au streamer : « les écarts sont conservés »."""
    out = _node("""
      const positions = [{x: 3, y: 40}, {x: 90, y: 66.76}, {x: 100, y: 70}];
      const g = positions.map(function (p) { return {depart: {x: p.x, y: p.y}}; });
      const d = OA.bornerDelta(g, -50, -30);   // demande énorme, bornée à -3
      proche(d.x, -3);
      const apres = positions.map(function (p) {
        return {x: Math.round((p.x + d.x) * 100) / 100,
                y: Math.round((p.y + d.y) * 100) / 100};
      });
      for (let i = 1; i < positions.length; i++) {
        proche(apres[i].x - apres[i - 1].x, positions[i].x - positions[i - 1].x);
        proche(apres[i].y - apres[i - 1].y, positions[i].y - positions[i - 1].y);
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_les_six_alignements_collent_la_boite_au_bord_pour_les_NEUF_ancrages():
    """Le piège de la tâche, vérifié là où il se cache.

    Pour chaque ancrage et chaque bord, on aligne puis on RELIT la boîte rendue
    par `geometrie()` : elle doit toucher le bord visé au pixel, et tenir
    entièrement dans le cadre. Un `x = 100` pour « à droite » ferait sortir
    six ancrages sur neuf, ce que ce test attrape en une passe.
    """
    out = _node("""
      const CAS = {
        "gauche":   function (g) { proche(g.gauche, 0, 0.05); },
        "droite":   function (g) { proche(g.droite, W, 0.05); },
        "centre-h": function (g) { proche((g.gauche + g.droite) / 2, W / 2, 0.05); },
        "haut":     function (g) { proche(g.haut, 0, 0.05); },
        "bas":      function (g) { proche(g.bas, H, 0.05); },
        "centre-v": function (g) { proche((g.haut + g.bas) / 2, H / 2, 0.05); },
      };
      const HORIZONTAL = {gauche: 1, droite: 1, "centre-h": 1};
      OA.BORDS.forEach(function (bord) {
        ANCRAGES.forEach(function (a) {
          // `bubble` (460×170) et `avatar` (200×200) : deux formes, et une
          // échelle qui n'est pas 1 — le décalage d'ancrage la porte.
          [["bubble", 0.9], ["avatar", 1], ["stats", 1.4]].forEach(function (d) {
            const e = el({anchor: a, scale: d[1], x: 37, y: 21});
            const p = OA.positionAlignee(d[0], e, bord, W, H);
            e.x = p.x; e.y = p.y;
            const g = OA.geometrie(d[0], e, W, H);
            CAS[bord](g);
            // Sur l'AXE ALIGNÉ seulement : coller à gauche ne peut rien
            // promettre de la hauteur, et l'élément de départ déborde
            // volontairement en y (`stats` à 1,4 fait 39 % de haut, posé à 21).
            const dedans = HORIZONTAL[bord]
              ? (g.gauche >= -0.05 && g.droite <= W + 0.05)
              : (g.haut >= -0.05 && g.bas <= H + 0.05);
            if (!dedans) throw new Error(bord + " / " + a + " / " + d[0] + " : hors cadre");
          });
        });
      });
      console.log("ok");
    """)
    assert out == "ok"


def test_l_alignement_ne_touche_QUE_l_axe_demande():
    """Coller à gauche ne doit pas remonter l'élément d'un pixel : on aligne
    souvent deux fois de suite, et un axe qui bouge tout seul défait le geste
    précédent."""
    out = _node("""
      ANCRAGES.forEach(function (a) {
        const e = el({anchor: a, x: 42.5, y: 63.25, scale: 0.8});
        ["gauche", "droite", "centre-h"].forEach(function (bord) {
          proche(OA.positionAlignee("bingo", e, bord, W, H).y, e.y);
        });
        ["haut", "bas", "centre-v"].forEach(function (bord) {
          proche(OA.positionAlignee("bingo", e, bord, W, H).x, e.x);
        });
      });
      console.log("ok");
    """)
    assert out == "ok"


def test_coller_a_droite_n_est_PAS_x_egale_100():
    """La preuve par l'absurde, écrite noir sur blanc.

    Sur un `top-left`, « à droite » vaut 100 MOINS la largeur de l'élément ;
    sur un `bottom-right`, il vaut bien 100 ; sur un `center`, l'entre-deux.
    Trois valeurs différentes pour un même bouton — c'est exactement ce qu'un
    `x = 100` en dur aurait manqué.
    """
    out = _node("""
      const bubble = OA.geometrie("bubble", el({scale: 1}), W, H);
      const part = bubble.largeur / W * 100;     // la largeur, en % du cadre
      const gauche = OA.positionAlignee("bubble", el({anchor: "top-left"}), "droite", W, H);
      const centre = OA.positionAlignee("bubble", el({anchor: "center"}), "droite", W, H);
      const bas = OA.positionAlignee("bubble", el({anchor: "bottom-right"}), "droite", W, H);
      proche(gauche.x, 100 - part, 0.01);
      proche(centre.x, 100 - part / 2, 0.01);
      proche(bas.x, 100, 0.01);
      if (!(gauche.x < centre.x && centre.x < bas.x)) throw new Error("ordre");
      console.log([gauche.x, centre.x, bas.x].join(" "));
    """)
    # 460 px de large sur un canvas de 1920 : 23,96 % du cadre.
    assert out == "76.04 88.02 100"


def test_le_delta_est_arrondi_une_fois_pour_tous():
    """Arrondir chaque position ferait dériver les écarts d'un centième par
    geste : `depart + delta` doit rester exact quand les deux le sont."""
    out = _node("""
      const g = [{depart: {x: 10, y: 10}}, {depart: {x: 20, y: 20}}];
      const d = OA.bornerDelta(g, 1.23456789, -0.987654321);
      proche(d.x, 1.23); proche(d.y, -0.99);
      console.log("ok");
    """)
    assert out == "ok"
