"""Deux éléments qui cohabitent et se recouvrent : signalé avant le direct.

Le détecteur ne vaut que par ce qu'il REFUSE de dire. Trois refus, et chacun
correspond à une fausse alerte qui aurait appris à ne plus regarder l'alerte :

  1. **Les exclusifs ne sont pas comparés.** Vingt-six widgets `solo: true`
     partent au centre, exactement superposés, et ils ne sont JAMAIS à l'écran
     ensemble — ils passent par la file d'attente. Les signaler ferait crier la
     moitié du panneau en permanence.
  2. **Les masqués non plus** : ils ne sont pas à l'écran du tout.
  3. **Une taille SUPPOSÉE ne conclut rien.** Un élément dont la taille n'a pas
     pu être lue dans l'aperçu est dit INDÉTERMINÉ — pas « sans
     chevauchement », ce qui serait une affirmation qu'on n'a pas les moyens de
     faire.

Plus le seuil : une intersection de moins de 15 % de la plus petite des deux
boîtes est un coin qui se touche.

Ces tests échouent sur le code d'avant : `analyserChevauchements`, `cohabite`
et `surfaceCommune` n'existaient pas.
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
// Le canvas lui-même : les pixels du test sont ceux du modèle.
const W = 1920, H = 1080;

function el(o) {
  return Object.assign({x: 50, y: 50, anchor: "top-left", scale: 1,
                        hidden: false, locked: false, solo: false,
                        wally_visible: true}, o);
}
/** Une scène dont on MESURE les éléments : sans mesure, tout est indéterminé. */
function scene(elements, mesures) {
  Object.keys(OA.mesures).forEach(function (c) { delete OA.mesures[c]; });
  Object.keys(mesures || {}).forEach(function (c) { OA.mesures[c] = mesures[c]; });
  const els = {};
  Object.keys(elements).forEach(function (c) { els[c] = el(elements[c]); });
  return {slug: "jeu", nom: "En jeu", ordre: Object.keys(elements),
          groupes: [], elements: els};
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


def test_deux_elements_qui_cohabitent_et_se_recouvrent_sont_signales():
    """Deux boîtes de 400 × 400 décalées de 100 px : 75 % de recouvrement."""
    out = _node("""
    // `top-left` : x/y sont le coin haut-gauche, la lecture est directe.
    const s = scene({bingo: {x: 0, y: 0}, stats: {x: 400 / 1920 * 100,
                                                 y: 400 / 1080 * 100}},
                    {bingo: [800, 800], stats: [800, 800]});
    const a = OA.analyserChevauchements(s, W, H);
    console.log(JSON.stringify({paires: a.paires, cles: a.cles.sort(),
                                indetermines: a.indetermines}));
    """)
    assert json.loads(out) == {
        "paires": [["bingo", "stats"]],
        "cles": ["bingo", "stats"],
        "indetermines": [],
    }


def test_deux_exclusifs_superposes_ne_disent_rien():
    """Le refus qui compte le plus : vingt-six widgets `solo` partent au centre.

    Exactement la même superposition que le test précédent — seul `solo` change.
    """
    out = _node("""
    const s = scene({meme: {x: 0, y: 0, solo: true},
                     dice: {x: 0, y: 0, solo: true}},
                    {meme: [800, 800], dice: [800, 800]});
    const a = OA.analyserChevauchements(s, W, H);
    console.log(JSON.stringify(a));
    """)
    assert json.loads(out) == {"paires": [], "cles": [], "indetermines": []}


def test_un_element_masque_nest_pas_a_lecran_donc_pas_compare():
    out = _node("""
    const s = scene({bingo: {x: 0, y: 0}, stats: {x: 0, y: 0, hidden: true}},
                    {bingo: [800, 800], stats: [800, 800]});
    console.log(JSON.stringify(OA.analyserChevauchements(s, W, H)));
    """)
    assert json.loads(out) == {"paires": [], "cles": [], "indetermines": []}


def test_sans_taille_mesuree_on_dit_indetermine_jamais_rien_a_signaler():
    """« Je ne sais pas » ne doit jamais s'écrire comme « tout va bien ».

    `stats` n'a pas de mesure : le couple n'est ni signalé ni déclaré sain.
    """
    out = _node("""
    const s = scene({bingo: {x: 0, y: 0}, stats: {x: 0, y: 0}},
                    {bingo: [800, 800]});          // `stats` non mesuré
    const a = OA.analyserChevauchements(s, W, H);
    console.log(JSON.stringify({a: a, texte: OA.texteChevauchements(a)}));
    """)
    data = json.loads(out)
    assert data["a"] == {"paires": [], "cles": [], "indetermines": ["stats"]}
    assert data["texte"] == "aucun chevauchement · 1 indéterminé"


def test_un_coin_qui_se_touche_nest_pas_un_chevauchement():
    """Sous 15 % de la plus petite boîte, deux cartes se mordent sans devenir
    illisibles. Au-dessus, elles le deviennent."""
    out = _node("""
    function recouvrement(px) {
      // Deux boîtes de 800 × 800, décalées pour se recouvrir de `px` en X et
      // de toute leur hauteur : la part vaut px / 800.
      const s = scene({bingo: {x: 0, y: 0},
                       stats: {x: (800 - px) / 1920 * 100, y: 0}},
                      {bingo: [800, 800], stats: [800, 800]});
      return OA.analyserChevauchements(s, W, H).paires.length;
    }
    console.log(JSON.stringify({
      seuil: OA.CHEVAUCHEMENT_MIN,
      juste_en_dessous: recouvrement(100),   // 12,5 %
      juste_au_dessus: recouvrement(160),    // 20 %
    }));
    """)
    assert json.loads(out) == {
        "seuil": 0.15, "juste_en_dessous": 0, "juste_au_dessus": 1,
    }


def test_la_phrase_de_la_barre_detat_dit_les_trois_cas():
    out = _node("""
    console.log(JSON.stringify([
      OA.texteChevauchements({paires: [], cles: [], indetermines: []}),
      OA.texteChevauchements({paires: [["bingo", "stats"]],
                              cles: ["bingo", "stats"], indetermines: []}),
      OA.texteChevauchements({paires: [], cles: [],
                              indetermines: ["bingo", "stats"]}),
    ]));
    """)
    textes = json.loads(out)
    assert textes[0] == "aucun chevauchement"
    assert textes[1].startswith("⚠ 1 chevauchement : ")
    assert textes[2] == "aucun chevauchement · 2 indéterminés"


def test_lechelle_compte_dans_la_boite_comparee():
    """La géométrie porte déjà l'échelle : un élément réduit de moitié ne
    recouvre plus son voisin. Sans ça, le détecteur signalerait un chevauchement
    qui n'existe qu'à l'échelle 1."""
    out = _node("""
    function avec(echelle) {
      // `bingo` part du coin haut-gauche : réduit, son bord DROIT recule.
      const s = scene({bingo: {x: 0, y: 0, scale: echelle},
                       stats: {x: 600 / 1920 * 100, y: 0}},
                      {bingo: [800, 800], stats: [800, 800]});
      return OA.analyserChevauchements(s, W, H).paires.length;
    }
    console.log(JSON.stringify({pleine: avec(1), reduite: avec(0.5)}));
    """)
    # À l'échelle 1, `bingo` s'étend jusqu'à 800 et mord 200 px sur `stats`
    # (25 % de sa boîte) → signalé. À 0,5 il s'arrête à 400 : plus d'intersection.
    assert json.loads(out) == {"pleine": 1, "reduite": 0}
