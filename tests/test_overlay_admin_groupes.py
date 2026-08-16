"""Les groupes du panneau de mise en scène, vérifiés hors navigateur.

Trois choses décident de tout ce qu'un groupe promet, et aucune ne se lit à
l'œil :

  1. `ordreGroupe` — les membres rendus contigus dans l'empilement. C'est le
     MIROIR de `_ordre_avec_groupes()` (Python) : deux calculs qui divergent, et
     la liste raconte une histoire pendant que l'antenne en joue une autre. Le
     dernier test confronte les deux sur les mêmes entrées.
  2. `retirerDesGroupes` — l'exclusivité (un élément, un seul groupe), tenue au
     point d'écriture, et la disparition d'un groupe vidé.
  3. `boiteEnglobante` — le cadre qu'on voit sur la surface.

Le code est chargé dans node avec un `window` nu : le panneau n'a alors ni DOM
ni réseau, et tous ses rendus sortent au premier `if`. C'est voulu — on teste le
MODÈLE du panneau, pas son affichage.

Ces tests échouent tous sur le code d'avant : aucune de ces fonctions n'existait.
"""
import json
import subprocess
from pathlib import Path

import pytest

from bot.core.overlay_layout import _ordre_avec_groupes, layout_par_defaut

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
global.navigator = {};
require(%s);
require(%s);
const OA = window.OverlayAdmin;

/** Une scène nue, avec ses éléments et ses groupes. Le panneau n'a pas de DOM
 *  ici : tous ses rendus sortent au premier `if`. */
function poser(ordre, groupes) {
  const elements = {};
  ordre.forEach(function (c) {
    elements[c] = {x: 50, y: 50, anchor: "center", scale: 1,
                   hidden: false, locked: false};
  });
  OA.etat.layout = {version: 1, defaut: "jeu", scenes: [
    {slug: "jeu", nom: "En jeu", ordre: ordre.slice(),
     groupes: groupes, elements: elements},
  ]};
  OA.etat.slugCourant = "jeu";
  OA.etat.selection = [];
  OA.etat.elementCourant = null;
  return OA.sceneCourante();
}
function egal(a, b) {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error("attendu " + y + ", obtenu " + x);
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


# ── L'empilement rendu contigu ──────────────────────────────────────────────

def test_les_membres_se_rassemblent_a_la_place_du_PREMIER():
    out = _node("""
      egal(OA.ordreGroupe(["a", "b", "c", "d", "e"],
                          [{id: "g", membres: ["a", "c", "e"]}]),
           ["a", "c", "e", "b", "d"]);
      console.log("ok");
    """)
    assert out == "ok"


def test_un_empilement_deja_contigu_ne_bouge_pas():
    """Le garde-fou qui compte : afficher la liste ne doit pas rebattre une
    disposition réglée à la main."""
    out = _node("""
      const ordre = ["a", "b", "c", "d"];
      egal(OA.ordreGroupe(ordre, [{id: "g", membres: ["b", "c"]}]), ordre);
      console.log("ok");
    """)
    assert out == "ok"


def test_l_ordre_relatif_des_membres_est_conserve():
    out = _node("""
      egal(OA.ordreGroupe(["c", "x", "a"], [{id: "g", membres: ["a", "c"]}]),
           ["c", "a", "x"]);
      console.log("ok");
    """)
    assert out == "ok"


def test_sans_groupe_l_ordre_sort_intact():
    out = _node("""
      egal(OA.ordreGroupe(["a", "b"], []), ["a", "b"]);
      egal(OA.ordreGroupe(["a", "b"], null), ["a", "b"]);
      console.log("ok");
    """)
    assert out == "ok"


def test_normaliserOrdre_ne_signale_un_changement_QUE_s_il_y_en_a_un():
    """L'appelant compte UNE modification par opération : un `true` de complaisance
    ferait grimper le compteur de publication à chaque rendu."""
    out = _node("""
      const scene = poser(["a", "b", "c"], [{id: "g", nom: "G", membres: ["a", "c"]}]);
      if (OA.normaliserOrdre(scene) !== true) throw new Error("attendu un changement");
      egal(scene.ordre, ["a", "c", "b"]);
      if (OA.normaliserOrdre(scene) !== false) throw new Error("second passage inutile");
      console.log("ok");
    """)
    assert out == "ok"


def test_le_JS_et_le_PYTHON_rangent_l_empilement_A_L_IDENTIQUE():
    """Les deux calculs se lisent ensemble et doivent rendre le même ordre.

    Sur des cas tordus exprès : membres éparpillés, groupe en fin de liste,
    groupe d'un seul élément, ordre inversé.
    """
    cas = [
        (["a", "b", "c", "d", "e"], [{"id": "g", "membres": ["a", "c", "e"]}]),
        (["a", "b", "c"], [{"id": "g", "membres": ["c"]}]),
        (["a", "b", "c", "d"], [{"id": "g", "membres": ["c", "d"]}]),
        (["d", "c", "b", "a"], [{"id": "g", "membres": ["a", "b"]},
                                {"id": "h", "membres": ["c", "d"]}]),
        (["a", "b", "c", "d"], [{"id": "g", "membres": ["b", "d"]},
                                {"id": "h", "membres": ["a"]}]),
    ]
    attendu = [_ordre_avec_groupes(list(o), g) for o, g in cas]
    out = _node("""
      const cas = %s;
      console.log(JSON.stringify(cas.map(function (c) {
        return OA.ordreGroupe(c[0], c[1]);
      })));
    """ % json.dumps([[o, g] for o, g in cas]))
    assert json.loads(out) == attendu


def test_le_JS_range_l_empilement_LIVRE_comme_le_serveur():
    """Le cas réel : les quatre groupes livrés, sur les trente-quatre clés."""
    scene = layout_par_defaut()["scenes"][0]
    out = _node("""
      const scene = %s;
      console.log(JSON.stringify(OA.ordreGroupe(scene.ordre, scene.groupes)));
    """ % json.dumps(scene))
    assert json.loads(out) == scene["ordre"]


# ── L'exclusivité, au point d'écriture ──────────────────────────────────────

def test_retirer_sort_les_cles_de_TOUS_les_groupes():
    out = _node("""
      const scene = poser(["a", "b", "c", "d"], [
        {id: "g", nom: "G", membres: ["a", "b"]},
        {id: "h", nom: "H", membres: ["c", "d"]},
      ]);
      const perdus = OA.retirerDesGroupes(scene, ["b", "c"]);
      egal(perdus, []);
      egal(scene.groupes.map(function (g) { return g.membres; }), [["a"], ["d"]]);
      console.log("ok");
    """)
    assert out == "ok"


def test_un_groupe_vide_de_son_dernier_membre_disparait_et_on_le_DIT():
    out = _node("""
      const scene = poser(["a", "b"], [
        {id: "g", nom: "Le mien", membres: ["a"]},
        {id: "h", nom: "L'autre", membres: ["b"]},
      ]);
      const perdus = OA.retirerDesGroupes(scene, ["a"]);
      egal(perdus, ["Le mien"]);
      egal(scene.groupes.map(function (g) { return g.id; }), ["h"]);
      console.log("ok");
    """)
    assert out == "ok"


def test_creer_un_groupe_reprend_les_membres_a_leur_groupe_precedent():
    """Le chemin complet, `window.prompt` compris : un élément n'appartient
    jamais à deux groupes, et c'est vérifié là où l'utilisateur le crée."""
    out = _node("""
      const scene = poser(["a", "b", "c", "d"], [
        {id: "vieux", nom: "Vieux", membres: ["a", "b", "c"]},
      ]);
      window.prompt = function () { return "Nouveau"; };
      OA.etat.selection = ["b", "c"];
      OA.etat.elementCourant = "c";
      OA.creerGroupe();
      egal(scene.groupes.map(function (g) { return [g.id, g.membres]; }),
           [["vieux", ["a"]], ["nouveau", ["b", "c"]]]);
      // et l'empilement suit : les membres du nouveau groupe se touchent
      egal(scene.ordre, ["a", "b", "c", "d"]);
      console.log("ok");
    """)
    assert out == "ok"


def test_creer_un_groupe_refuse_un_seul_element():
    """Un groupe d'un élément est un élément, avec un en-tête en plus."""
    out = _node("""
      const scene = poser(["a", "b"], []);
      let demande = false;
      window.prompt = function () { demande = true; return "X"; };
      OA.etat.selection = ["a"];
      OA.etat.elementCourant = "a";
      OA.creerGroupe();
      egal(scene.groupes, []);
      if (demande) throw new Error("le nom a été demandé pour rien");
      console.log("ok");
    """)
    assert out == "ok"


def test_creer_un_groupe_sans_nom_ne_cree_RIEN():
    out = _node("""
      const scene = poser(["a", "b"], []);
      window.prompt = function () { return "   "; };
      OA.etat.selection = ["a", "b"];
      OA.etat.elementCourant = "b";
      OA.creerGroupe();
      egal(scene.groupes, []);
      // et « Annuler » non plus
      window.prompt = function () { return null; };
      OA.creerGroupe();
      egal(scene.groupes, []);
      console.log("ok");
    """)
    assert out == "ok"


def test_deux_groupes_du_MEME_nom_recoivent_des_identifiants_distincts():
    """Le nom ne peut pas servir de clé : on le renomme, et rien n'interdit de
    l'employer deux fois. Deux `id` identiques, et le serveur en jette un."""
    out = _node("""
      const scene = poser(["a", "b", "c", "d"], []);
      window.prompt = function () { return "Jeux"; };
      OA.etat.selection = ["a", "b"];
      OA.etat.elementCourant = "b";
      OA.creerGroupe();
      OA.etat.selection = ["c", "d"];
      OA.etat.elementCourant = "d";
      OA.creerGroupe();
      egal(scene.groupes.map(function (g) { return g.id; }), ["jeux", "jeux-2"]);
      console.log("ok");
    """)
    assert out == "ok"


def test_dissoudre_ne_touche_ni_aux_places_ni_aux_verrous():
    """« On défait l'en-tête, pas le travail. »"""
    out = _node("""
      const scene = poser(["a", "b"], [{id: "g", nom: "G", membres: ["a", "b"]}]);
      scene.elements.a.x = 12.5;
      scene.elements.b.locked = true;
      scene.elements.b.hidden = true;
      OA.dissoudreGroupe(scene.groupes[0]);
      egal(scene.groupes, []);
      egal([scene.elements.a.x, scene.elements.b.locked, scene.elements.b.hidden],
           [12.5, true, true]);
      egal(scene.ordre, ["a", "b"]);
      console.log("ok");
    """)
    assert out == "ok"


def test_selectionner_un_groupe_selectionne_ses_MEMBRES():
    """La clé de voûte : tout ce qui existait — glisser, flèches, aligner,
    répartir — s'applique alors sans une ligne de plus."""
    out = _node("""
      poser(["a", "b", "c"], [{id: "g", nom: "G", membres: ["c", "a"]}]);
      OA.selectionnerGroupe(OA.groupesScene()[0]);
      // dans l'ordre de la SCÈNE, jamais celui du groupe
      egal(OA.selection(), ["a", "c"]);
      egal(OA.etat.elementCourant, "c");
      console.log("ok");
    """)
    assert out == "ok"


def test_un_membre_fantome_ne_compte_ni_ne_s_affiche():
    """Modèle d'une version d'avant, widget retiré du code : l'en-tête ne doit
    pas annoncer trois membres pour en montrer deux."""
    out = _node("""
      poser(["a", "b"], [{id: "g", nom: "G", membres: ["a", "disparu", "b"]}]);
      // Ce qui s'affiche et ce qui se sélectionne : les membres PRÉSENTS.
      egal(OA.membresPresents(OA.groupesScene()[0]), ["a", "b"]);
      OA.selectionnerGroupe(OA.groupesScene()[0]);
      egal(OA.selection(), ["a", "b"]);
      // La clé fantôme reste RÉCLAMÉE : c'est ce qui empêche un autre groupe de
      // la reprendre, et le serveur la nettoiera au prochain enregistrement.
      egal(OA.groupeDe("disparu").id, "g");
      console.log("ok");
    """)
    assert out == "ok"


def test_retirer_un_element_de_son_groupe_le_laisse_sur_place():
    out = _node("""
      const scene = poser(["a", "b", "c"], [{id: "g", nom: "G", membres: ["a", "b"]}]);
      scene.elements.a.x = 33;
      OA.retirerDuGroupe("a");
      egal(scene.groupes[0].membres, ["b"]);
      egal(scene.elements.a.x, 33);
      egal(OA.groupeDe("a"), null);
      console.log("ok");
    """)
    assert out == "ok"


def test_degrouper_dissout_tous_les_groupes_touches_par_la_selection():
    out = _node("""
      const scene = poser(["a", "b", "c", "d"], [
        {id: "g", nom: "G", membres: ["a", "b"]},
        {id: "h", nom: "H", membres: ["c"]},
      ]);
      OA.etat.selection = ["b", "c", "d"];
      OA.etat.elementCourant = "d";
      OA.degrouperSelection();
      egal(scene.groupes, []);
      egal(scene.ordre, ["a", "b", "c", "d"]);
      console.log("ok");
    """)
    assert out == "ok"


# ── Le cadre englobant ──────────────────────────────────────────────────────

def test_la_boite_englobante_couvre_toutes_les_boites():
    out = _node("""
      egal(OA.boiteEnglobante([
        {gauche: 10, haut: 20, droite: 30, bas: 40},
        {gauche: 5, haut: 25, droite: 25, bas: 60},
      ]), {gauche: 5, haut: 20, droite: 30, bas: 60, largeur: 25, hauteur: 40});
      console.log("ok");
    """)
    assert out == "ok"


def test_la_boite_englobante_d_UNE_seule_boite_est_cette_boite():
    out = _node("""
      const b = OA.boiteEnglobante([{gauche: 1, haut: 2, droite: 3, bas: 4}]);
      egal([b.gauche, b.haut, b.droite, b.bas], [1, 2, 3, 4]);
      console.log("ok");
    """)
    assert out == "ok"


def test_sans_boite_il_n_y_a_pas_de_cadre():
    """`Infinity` posé en `left` sur un `<div>` : le cadre part à l'infini et la
    surface se met à défiler. On ne rend rien."""
    out = _node("""
      egal(OA.boiteEnglobante([]), null);
      egal(OA.boiteEnglobante(null), null);
      console.log("ok");
    """)
    assert out == "ok"
