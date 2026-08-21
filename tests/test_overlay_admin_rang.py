"""Le pas de rang de la bande d'inspection.

L'empilement ne se réglait que par glisser dans la liste : un geste imprécis sur
trente-sept lignes, et invisible pour qui regarde la surface. « Derrière » et
« Devant » font le même travail sur l'élément qu'on a sous les yeux.

Ce que ces tests protègent est une garde INVISIBLE À LA LECTURE : le pas est
appliqué, puis `normaliserOrdre()` le DÉFAIT quand il sortirait l'élément de son
groupe — les membres d'un groupe restent contigus. Sans détection de ce
non-effet, le bouton passe pour cassé : on clique, rien ne bouge, rien ne
s'explique.

Le sens compte aussi, et il ne se devine pas : l'index 0 est DEVANT (c'est lui
qui porte le z-index le plus haut, `rendreSurface`).
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

const dits = [];
window.toast = function (m) { dits.push(String(m)); };

function el(o) {
  return Object.assign({x: 50, y: 50, anchor: "center", scale: 1,
                        hidden: false, locked: false, solo: false,
                        wally_visible: true}, o);
}

/** Pose une scène d'`ordre` donné et rend la scène posée. */
function poser(ordre, groupes) {
  const elements = {};
  ordre.forEach(function (c) { elements[c] = el({}); });
  const scene = {slug: "jeu", nom: "En jeu", ordre: ordre.slice(),
                 elements: elements, groupes: groupes || []};
  OA.etat.layout = {defaut: "jeu", scenes: [scene]};
  OA.etat.slugCourant = "jeu";
  OA.etat.publie = JSON.stringify(OA.etat.layout);
  OA.etat.brouillon = 0;
  dits.length = 0;
  return scene;
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


def test_devant_remonte_vers_l_index_zero():
    """Le sens ne se devine pas : l'index 0 porte le z-index le plus haut."""
    out = _node("""
      const scene = poser(["a", "b", "c"]);
      OA.etat.elementCourant = "c";
      OA.deplacerRang(-1);                       // « Devant »
      if (scene.ordre.join() !== "a,c,b") throw new Error(scene.ordre.join());
      OA.deplacerRang(-1);
      if (scene.ordre.join() !== "c,a,b") throw new Error(scene.ordre.join());
      console.log("ok");
    """)
    assert out == "ok"


def test_derriere_descend():
    out = _node("""
      const scene = poser(["a", "b", "c"]);
      OA.etat.elementCourant = "a";
      OA.deplacerRang(1);
      if (scene.ordre.join() !== "b,a,c") throw new Error(scene.ordre.join());
      console.log("ok");
    """)
    assert out == "ok"


def test_au_bout_le_pas_est_refuse_et_dit():
    """Muet, le bouton passe pour cassé — on reclique, plus fort."""
    out = _node("""
      const scene = poser(["a", "b"]);
      OA.etat.elementCourant = "a";
      OA.deplacerRang(-1);                        // déjà tout devant
      if (scene.ordre.join() !== "a,b") throw new Error(scene.ordre.join());
      if (OA.etat.brouillon !== 0) throw new Error("brouillon " + OA.etat.brouillon);
      if (!dits.some(function (m) { return m.indexOf("Déjà tout devant") >= 0; })) {
        throw new Error("rien dit : " + JSON.stringify(dits));
      }
      OA.etat.elementCourant = "b";
      OA.deplacerRang(1);                         // déjà tout derrière
      if (!dits.some(function (m) { return m.indexOf("Déjà tout derrière") >= 0; })) {
        throw new Error("rien dit : " + JSON.stringify(dits));
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_un_pas_a_l_interieur_du_groupe_passe():
    """Deux membres du même groupe échangent leur rang sans rien casser."""
    out = _node("""
      const scene = poser(["a", "b", "c"],
                          [{id: "g1", nom: "Bloc", membres: ["a", "b"]}]);
      OA.etat.elementCourant = "a";
      OA.deplacerRang(1);
      if (scene.ordre.join() !== "b,a,c") throw new Error(scene.ordre.join());
      if (OA.etat.brouillon !== 1) throw new Error("brouillon " + OA.etat.brouillon);
      console.log("ok");
    """)
    assert out == "ok"


def test_un_pas_qui_sortirait_du_groupe_est_defait_et_dit():
    """LA garde invisible : le pas est appliqué, puis `normaliserOrdre()` le
    défait — les membres d'un groupe restent contigus. Sans le message, on
    clique et rien ne se passe, sans explication."""
    out = _node("""
      const scene = poser(["a", "b", "c"],
                          [{id: "g1", nom: "Bloc", membres: ["a", "b"]}]);
      OA.etat.elementCourant = "b";
      OA.deplacerRang(1);                        // sortirait « b » du bloc
      if (scene.ordre.join() !== "a,b,c") throw new Error(scene.ordre.join());
      // Et surtout : AUCUNE modification comptée pour un geste sans effet.
      if (OA.etat.brouillon !== 0) throw new Error("brouillon " + OA.etat.brouillon);
      if (!dits.some(function (m) { return m.indexOf("groupe") >= 0; })) {
        throw new Error("rien dit : " + JSON.stringify(dits));
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_sans_element_choisi_rien_ne_bouge():
    out = _node("""
      const scene = poser(["a", "b"]);
      OA.etat.elementCourant = null;
      OA.deplacerRang(1);
      if (scene.ordre.join() !== "a,b") throw new Error(scene.ordre.join());
      if (OA.etat.brouillon !== 0) throw new Error("brouillon " + OA.etat.brouillon);
      console.log("ok");
    """)
    assert out == "ok"
