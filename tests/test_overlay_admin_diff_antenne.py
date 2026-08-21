"""Ce que le pied de publication annonce avant d'envoyer à l'antenne.

Le panneau comptait des GESTES : « 6 modifications non publiées », sans dire
lesquelles. Déplacer un élément puis le ramener en faisait deux et ne changeait
rien ; à l'inverse, une scène renommée dans un onglet qu'on ne regarde pas
partait sans être annoncée nulle part. `diffAntenne()` compare le modèle affiché
à celui qui est réellement à l'antenne (`etat.publie`).

Ce que ces tests protègent, c'est l'EXHAUSTIVITÉ de la comparaison : un champ
oublié ne se voit pas en relisant le code, mais un soir de live sous la forme
d'un réglage parti sans avoir été annoncé.

Le code est chargé dans node avec un `window` nu — la fonction ne touche ni au
DOM ni au réseau.
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

/** Pose une antenne et un modèle affiché, et rend le diff. */
function diff(antenne, affiche) {
  OA.etat.publie = JSON.stringify(antenne);
  OA.etat.layout = affiche;
  return OA.diffAntenne();
}

/** Un modèle à une scène, deux éléments. */
function modele(o) {
  return Object.assign({
    defaut: "jeu",
    scenes: [{
      slug: "jeu", nom: "En jeu",
      ordre: ["avatar", "bingo"],
      elements: {avatar: el({}), bingo: el({x: 10})},
      groupes: [],
    }],
  }, o || {});
}
function copie(m) { return JSON.parse(JSON.stringify(m)); }
""" % (json.dumps(str(_STATIC / "overlay_layout.js")),
       json.dumps(str(_STATIC / "overlay_admin.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def test_deux_modeles_identiques_ne_donnent_rien():
    """Le cas qui doit rester silencieux : sans lui, le pied s'allume en ambre
    en permanence et ne signale plus rien."""
    out = _node("""
      const m = modele();
      const d = diff(copie(m), m);
      if (d.total !== 0) throw new Error("total " + d.total);
      if (d.liste.length !== 0) throw new Error("liste non vide");
      if (d.parScene.jeu.n !== 0) throw new Error("parScene");
      console.log("ok");
    """)
    assert out == "ok"


def test_un_aller_retour_ne_compte_pas():
    """Le défaut d'origine : deux gestes, zéro changement. Le compteur du
    brouillon dirait « 2 », le pied doit dire « rien ne part »."""
    out = _node("""
      const antenne = modele();
      const affiche = copie(antenne);
      affiche.scenes[0].elements.avatar.x = 80;   // premier geste
      affiche.scenes[0].elements.avatar.x = 50;   // on revient
      const d = diff(antenne, affiche);
      if (d.total !== 0) throw new Error("total " + d.total);
      console.log("ok");
    """)
    assert out == "ok"


def test_chaque_champ_de_placement_est_vu():
    """Un champ oublié ne se voit pas en relisant : il se voit à l'antenne.

    On confronte donc la liste champ par champ, y compris ceux qu'on n'a pas
    envie de décrire (le verrou, l'exclusivité, la garde de Wally).
    """
    out = _node("""
      const cas = [
        ["x", 12.5, "x "], ["y", 12.5, "y "], ["scale", 1.4, "taille "],
        ["anchor", "top-left", "ancrage "], ["hidden", true, "masqué"],
        ["locked", true, "verrouillé"], ["solo", true, "prend la scène seul"],
        ["wally_visible", false, "Wally s'efface"],
      ];
      cas.forEach(function (c) {
        const antenne = modele();
        const affiche = copie(antenne);
        affiche.scenes[0].elements.avatar[c[0]] = c[1];
        const d = diff(antenne, affiche);
        if (d.total !== 1) throw new Error(c[0] + " : total " + d.total);
        if (d.liste[0].cle !== "avatar") throw new Error(c[0] + " : mauvaise clé");
        if (d.liste[0].d.indexOf(c[2]) < 0) {
          throw new Error(c[0] + " : « " + d.liste[0].d + " » ne dit pas « " + c[2] + " »");
        }
      });
      console.log("ok");
    """)
    assert out == "ok"


def test_l_ancrage_est_dit_en_francais():
    """« ancrage bottom-left → top-left » dans un journal de modifications ne se
    lit pas — les clés du modèle restent anglaises, l'affichage non."""
    out = _node("""
      const antenne = modele();
      const affiche = copie(antenne);
      affiche.scenes[0].elements.avatar.anchor = "bottom-left";
      const d = diff(antenne, affiche);
      if (d.liste[0].d !== "ancrage centre → bas-gauche") {
        throw new Error("« " + d.liste[0].d + " »");
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_un_changement_de_rang_est_vu():
    """L'empilement décide qui passe devant : le changer est une modification
    au même titre qu'un déplacement, et il ne touche aucun champ d'élément."""
    out = _node("""
      const antenne = modele();
      const affiche = copie(antenne);
      affiche.scenes[0].ordre = ["bingo", "avatar"];
      const d = diff(antenne, affiche);
      if (d.total !== 2) throw new Error("total " + d.total);
      d.liste.forEach(function (l) {
        if (l.d.indexOf("rang ") !== 0) throw new Error("« " + l.d + " »");
      });
      console.log("ok");
    """)
    assert out == "ok"


def test_une_scene_ajoutee_supprimee_ou_renommee_est_annoncee():
    """`publier()` pousse le MODÈLE ENTIER : ce qui arrive à une scène qu'on ne
    regarde pas part quand même, et doit donc se lire dans le pied."""
    out = _node("""
      // Ajoutée
      let antenne = modele();
      let affiche = copie(antenne);
      affiche.scenes.push({slug: "fin", nom: "Écran de fin", ordre: [],
                           elements: {}, groupes: []});
      let d = diff(antenne, affiche);
      if (d.total !== 1 || d.liste[0].d !== "scène ajoutée") {
        throw new Error("ajout : " + JSON.stringify(d.liste));
      }
      // Supprimée — elle n'a plus d'onglet, sa disparition doit se lire.
      antenne = modele();
      antenne.scenes.push({slug: "fin", nom: "Écran de fin", ordre: [],
                           elements: {}, groupes: []});
      affiche = modele();
      d = diff(antenne, affiche);
      if (d.total !== 1 || d.liste[0].d !== "scène supprimée") {
        throw new Error("suppression : " + JSON.stringify(d.liste));
      }
      // Renommée
      antenne = modele();
      affiche = copie(antenne);
      affiche.scenes[0].nom = "Partie en cours";
      d = diff(antenne, affiche);
      if (d.total !== 1 || d.liste[0].d.indexOf("renommée") !== 0) {
        throw new Error("renommage : " + JSON.stringify(d.liste));
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_le_changement_de_scene_par_defaut_est_annonce():
    """C'est l'adresse que sert `/overlay-` sans slug : la changer sans le dire
    envoie une source OBS ailleurs."""
    out = _node("""
      const antenne = modele();
      antenne.scenes.push({slug: "fin", nom: "Écran de fin", ordre: [],
                           elements: {}, groupes: []});
      const affiche = copie(antenne);
      affiche.defaut = "fin";
      const d = diff(antenne, affiche);
      if (d.total !== 1 || d.liste[0].d !== "devient la scène par défaut") {
        throw new Error(JSON.stringify(d.liste));
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_la_cadence_absente_du_modele_n_invente_pas_de_modification():
    """Un modèle rangé avant l'ajout de `duree`/`pause` ne les porte pas.
    « durée undefined → 9 s » annoncerait un geste que personne n'a fait."""
    out = _node("""
      const antenne = modele();
      const affiche = copie(antenne);
      affiche.scenes[0].elements.avatar.duree = 9;   // le champ apparaît
      const d = diff(antenne, affiche);
      if (d.total !== 0) throw new Error(JSON.stringify(d.liste));
      // Mais un changement de cadence RÉEL se voit.
      const a2 = copie(affiche);
      const b2 = copie(affiche);
      b2.scenes[0].elements.avatar.duree = 12;
      const d2 = diff(a2, b2);
      if (d2.total !== 1 || d2.liste[0].d.indexOf("durée 9 → 12 s") < 0) {
        throw new Error(JSON.stringify(d2.liste));
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_les_onglets_comptent_les_elements_et_pas_les_scenes():
    """La pastille de l'onglet s'allume sur TOUT changement ; le « 5 modifiés »
    qu'il affiche ne compte que les éléments — sans quoi un renommage se lirait
    comme un élément déplacé."""
    out = _node("""
      const antenne = modele();
      const affiche = copie(antenne);
      affiche.scenes[0].nom = "Partie";                     // scène
      affiche.scenes[0].elements.bingo.hidden = true;       // élément
      const d = diff(antenne, affiche);
      if (d.parScene.jeu.n !== 2) throw new Error("n " + d.parScene.jeu.n);
      if (d.parScene.jeu.elements !== 1) {
        throw new Error("elements " + d.parScene.jeu.elements);
      }
      console.log("ok");
    """)
    assert out == "ok"


def test_sans_antenne_connue_le_diff_est_vide_et_ne_leve_pas():
    """Un chargement raté laisse `etat.publie` à null. Le panneau doit rester
    utilisable : pas de détail plutôt qu'une exception qui casse le rendu."""
    out = _node("""
      OA.etat.publie = null;
      OA.etat.layout = modele();
      const d = OA.diffAntenne();
      if (d.total !== 0) throw new Error("total " + d.total);
      console.log("ok");
    """)
    assert out == "ok"
