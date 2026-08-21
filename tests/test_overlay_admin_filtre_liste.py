"""Le filtre du panneau des éléments.

Trente-sept lignes dont vingt-six partent au même endroit : retrouver « celui
qui s'appelle apex quelque chose » se faisait à l'œil, en déroulant.

Deux choses se testent ici, et la seconde est la seule qui compte vraiment :

  1. ce que le filtre laisse passer — vérifiable à l'œil ;
  2. ce que la SIGNATURE de la liste en retient. `rendreElements()` ne
     reconstruit la liste que si la signature a changé. Une signature qui
     oublie le filtre, ou l'état « modifié », fige l'affichage sur son état
     d'avant : on tape dans la recherche et rien ne bouge, la pastille ambre
     n'apparaît jamais. Ça ne se voit pas en relisant le code — c'est
     exactement le défaut que la signature a déjà eu.
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
                        hidden: false, locked: false, solo: false,
                        wally_visible: true}, o);
}

/** Une scène de trois éléments, dont un masqué. */
function poser() {
  const scene = {
    slug: "jeu", nom: "En jeu",
    ordre: ["apex_kills", "bingo", "avatar"],
    elements: {apex_kills: el({}), bingo: el({hidden: true}), avatar: el({})},
    groupes: [],
  };
  OA.etat.layout = {defaut: "jeu", scenes: [scene]};
  OA.etat.slugCourant = "jeu";
  OA.etat.publie = JSON.stringify(OA.etat.layout);
  OA.etat.brouillon = 0;
  OA.etat.libelles = {
    apex_kills: {nom: "Kills de la partie", description: ""},
    bingo: {nom: "Bingo du stream", description: ""},
    avatar: {nom: "Avatar de Wally", description: ""},
  };
  OA.filtre.texte = "";
  OA.filtre.masques = false;
  OA.filtre.modifies = false;
  return scene;
}

/** Les clés que le filtre laisse passer, dans l'ordre de la scène. */
function retenues(scene, modifiees) {
  return scene.ordre.filter(function (c) {
    return OA.passeFiltre(c, scene.elements[c], (modifiees || {})[c]);
  });
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


def test_sans_filtre_tout_passe():
    out = _node("""
      const scene = poser();
      if (retenues(scene).join() !== "apex_kills,bingo,avatar") {
        throw new Error(retenues(scene).join());
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_le_texte_cherche_dans_la_cle_ET_dans_le_nom():
    """On connaît l'un ou l'autre selon qu'on vient du panneau ou d'un log."""
    out = _node("""
      const scene = poser();
      OA.filtre.texte = "apex";                  // la clé
      if (retenues(scene).join() !== "apex_kills") throw new Error(retenues(scene).join());
      OA.filtre.texte = "bingo du";              // le nom lisible
      if (retenues(scene).join() !== "bingo") throw new Error(retenues(scene).join());
      OA.filtre.texte = "kills de la partie";    // le nom, pas la clé
      if (retenues(scene).join() !== "apex_kills") throw new Error(retenues(scene).join());
      console.log("ok");
    """)
    assert out == "ok"


def test_les_deux_pastilles_se_cumulent():
    """« masqué ET modifié » est une question qu'on se pose vraiment avant de
    publier — les deux filtres ne s'excluent donc pas."""
    out = _node("""
      const scene = poser();
      OA.filtre.masques = true;
      if (retenues(scene).join() !== "bingo") throw new Error(retenues(scene).join());
      OA.filtre.modifies = true;
      // « bingo » est masqué mais pas modifié : plus rien ne passe.
      if (retenues(scene, {}).join() !== "") throw new Error(retenues(scene, {}).join());
      // Il devient modifié : il repasse.
      if (retenues(scene, {bingo: true}).join() !== "bingo") {
        throw new Error(retenues(scene, {bingo: true}).join());
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_la_signature_voit_le_filtre():
    """Sans ça, taper dans la recherche ne redessine rien : `rendreElements()`
    compare la signature, la trouve identique et laisse la liste d'avant."""
    out = _node("""
      const scene = poser();
      const nu = OA.signatureListe(scene);
      OA.filtre.texte = "apex";
      if (OA.signatureListe(scene) === nu) throw new Error("le texte est invisible");
      OA.filtre.texte = "";
      OA.filtre.masques = true;
      if (OA.signatureListe(scene) === nu) throw new Error("« masqués » est invisible");
      OA.filtre.masques = false;
      OA.filtre.modifies = true;
      if (OA.signatureListe(scene) === nu) throw new Error("« modifiés » est invisible");
      console.log("ok");
    """)
    assert out == "ok"


def test_la_signature_voit_un_element_modifie():
    """La pastille ambre n'apparaîtrait sinon qu'au prochain changement de nom
    ou de visibilité — c'est-à-dire jamais, puisque déplacer un élément ne
    touche ni l'un ni l'autre."""
    out = _node("""
      const scene = poser();
      const nu = OA.signatureListe(scene);
      scene.elements.avatar.x = 42;             // le modèle affiché s'écarte
      if (OA.signatureListe(scene) === nu) {
        throw new Error("un déplacement ne change pas la signature");
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_le_diff_rend_les_cles_touchees():
    """La liste consulte ces clés une fois par ligne ; elles viennent du MÊME
    parcours que le détail du pied, jamais d'un second calcul."""
    out = _node("""
      const scene = poser();
      scene.elements.avatar.x = 42;
      scene.elements.bingo.scale = 1.4;
      const change = OA.diffAntenne().parScene.jeu;
      if (!change.cles.avatar || !change.cles.bingo) {
        throw new Error(JSON.stringify(change.cles));
      }
      if (change.cles.apex_kills) throw new Error("clé intacte marquée");
      if (change.elements !== 2) throw new Error("elements " + change.elements);
      console.log("ok");
    """)
    assert out == "ok"
