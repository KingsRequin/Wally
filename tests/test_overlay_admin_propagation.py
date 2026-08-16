"""Propager un placement d'une scène vers les autres, sans toucher aux scènes.

Le geste que le panneau existe pour éviter : trente-quatre éléments × trois
scènes = cent deux réglages, posés un par un. Propager les fait tous d'un coup —
et c'est précisément pour ça qu'une erreur y coûte cher.

Deux propriétés se jouent ici, et aucune ne se lit dans le code :

  1. **La visibilité ne part pas.** `hidden` est ce qui distingue les trois
     habillages (le bingo masqué au démarrage, visible en jeu). Une propagation
     qui l'emporterait effacerait d'un clic le seul réglage qui donne un sens
     aux scènes. Elle ne part que si on le demande.
  2. **Le chiffre annoncé est le VRAI.** La confirmation dit « N réglages
     écrasés » : compté sur ce qui change réellement, pas sur le produit de deux
     longueurs. Un élément déjà identique ne compte pas, un élément verrouillé
     dans la scène de destination non plus — il n'est pas écrit.

Ces tests échouent sur le code d'avant : `planPropagation` n'existait pas.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
// Un `window` nu suffit : rien n'est touché au chargement des deux fichiers.
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
/** Une scène à trois éléments, tous au même endroit sauf indication. */
function scene(slug, nom, elements) {
  const base = {avatar: el({}), bingo: el({}), meme: el({})};
  Object.keys(elements || {}).forEach(function (c) {
    base[c] = el(elements[c]);
  });
  return {slug: slug, nom: nom, ordre: ["avatar", "bingo", "meme"],
          groupes: [], elements: base};
}
function poser(scenes, courante) {
  OA.etat.layout = {version: 1, defaut: scenes[0].slug, scenes: scenes};
  OA.etat.slugCourant = courante;
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


def test_le_placement_part_la_visibilite_reste():
    """Le cœur de la fonction, et le seul défaut impardonnable si on le rate.

    L'élément propagé retrouve x/y/ancrage/échelle à l'identique dans les deux
    autres scènes ; leur `hidden`, réglé à la main, n'a pas bougé d'un poil.
    """
    out = _node("""
    poser([
      scene("jeu", "En jeu", {bingo: {x: 12.5, y: 71, anchor: "bottom-left",
                                      scale: 0.7, hidden: false}}),
      scene("start", "Stream Starting", {bingo: {hidden: true}}),
      scene("fin", "Fin", {bingo: {hidden: false}}),
    ], "jeu");
    const source = OA.sceneCourante();
    const plan = OA.planPropagation(source, ["bingo"], OA.CHAMPS_PROPAGES);
    OA.appliquerPropagation(source, plan, OA.CHAMPS_PROPAGES);
    const out = OA.etat.layout.scenes.map(function (s) {
      const b = s.elements.bingo;
      return [s.slug, b.x, b.y, b.anchor, b.scale, b.hidden].join("|");
    });
    console.log(JSON.stringify(out));
    """)
    assert json.loads(out) == [
        "jeu|12.5|71|bottom-left|0.7|false",
        # La position est IDENTIQUE …
        "start|12.5|71|bottom-left|0.7|true",   # … et `hidden` intact
        "fin|12.5|71|bottom-left|0.7|false",
    ]


def test_la_visibilite_part_quand_on_la_demande():
    """La nuance existe dans l'interface : cochée, `hidden` voyage avec."""
    out = _node("""
    poser([
      scene("jeu", "En jeu", {bingo: {x: 10, hidden: true}}),
      scene("start", "Stream Starting", {bingo: {hidden: false}}),
    ], "jeu");
    const source = OA.sceneCourante();
    const champs = OA.CHAMPS_PROPAGES.concat(["hidden"]);
    const plan = OA.planPropagation(source, ["bingo"], champs);
    OA.appliquerPropagation(source, plan, champs);
    console.log(JSON.stringify(OA.etat.layout.scenes[1].elements.bingo.hidden));
    """)
    assert json.loads(out) is True


def test_le_compte_annonce_ne_retient_que_ce_qui_change_vraiment():
    """« 12 réglages écrasés » sur une scène déjà identique serait faux.

    Une confirmation qui gonfle son chiffre apprend à ne plus le lire.
    """
    out = _node("""
    poser([
      scene("jeu", "En jeu", {bingo: {x: 10}, meme: {x: 10}}),
      // `bingo` y est DÉJÀ à sa place, `meme` non : un seul réglage écrasé.
      scene("start", "Stream Starting", {bingo: {x: 10}, meme: {x: 90}}),
    ], "jeu");
    const plan = OA.planPropagation(OA.sceneCourante(),
                                    ["avatar", "bingo", "meme"],
                                    OA.CHAMPS_PROPAGES);
    console.log(JSON.stringify(plan.map(function (p) {
      return {scene: p.scene.slug, ecrits: p.ecrits, bloques: p.bloques};
    })));
    """)
    assert json.loads(out) == [
        {"scene": "start", "ecrits": ["meme"], "bloques": []},
    ]


def test_un_element_verrouille_a_destination_nest_pas_ecrase():
    """Le cadenas retient ici comme partout : il est mis de côté, et NOMMÉ.

    La propagation est le geste le plus facile à lancer sur trop d'éléments à la
    fois — c'est là que le verrou sert le plus.
    """
    out = _node("""
    poser([
      scene("jeu", "En jeu", {bingo: {x: 10}}),
      scene("start", "Stream Starting", {bingo: {x: 90, locked: true}}),
    ], "jeu");
    const source = OA.sceneCourante();
    const plan = OA.planPropagation(source, ["bingo"], OA.CHAMPS_PROPAGES);
    OA.appliquerPropagation(source, plan, OA.CHAMPS_PROPAGES);
    console.log(JSON.stringify({
      bloques: plan[0].bloques,
      ecrits: plan[0].ecrits,
      x: OA.etat.layout.scenes[1].elements.bingo.x,
    }));
    """)
    assert json.loads(out) == {"bloques": ["bingo"], "ecrits": [], "x": 90}


def test_la_scene_source_ne_figure_jamais_dans_le_plan():
    """Se propager à soi-même n'écrirait rien, mais gonflerait le compte."""
    out = _node("""
    poser([scene("a", "A", {}), scene("b", "B", {}), scene("c", "C", {})], "b");
    console.log(JSON.stringify(OA.autresScenes().map(function (s) {
      return s.slug;
    })));
    """)
    assert json.loads(out) == ["a", "c"]


def test_ni_lordre_ni_les_groupes_ne_partent():
    """Une scène de fin n'a pas le découpage d'une scène de jeu.

    Propager l'empilement et les groupes serait un effet de bord qu'on ne
    demande pas, et qu'on ne verrait qu'après coup.
    """
    out = _node("""
    const a = scene("jeu", "En jeu", {bingo: {x: 10}});
    const b = scene("start", "Stream Starting", {});
    b.ordre = ["meme", "bingo", "avatar"];
    b.groupes = [{id: "g", nom: "Un groupe", membres: ["bingo", "meme"]}];
    poser([a, b], "jeu");
    const source = OA.sceneCourante();
    const plan = OA.planPropagation(source, OA.clesScene(), OA.CHAMPS_PROPAGES);
    OA.appliquerPropagation(source, plan, OA.CHAMPS_PROPAGES);
    console.log(JSON.stringify({
      ordre: OA.etat.layout.scenes[1].ordre,
      groupes: OA.etat.layout.scenes[1].groupes.length,
    }));
    """)
    assert json.loads(out) == {"ordre": ["meme", "bingo", "avatar"], "groupes": 1}
