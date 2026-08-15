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
