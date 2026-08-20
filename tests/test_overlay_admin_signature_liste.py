"""La liste des éléments ne se reconstruit que si elle a VRAIMENT changé.

Le défaut, dans les mots de l'owner : « c'est infernal d'y naviguer, j'ai 1 fps
dessus littéralement ». Une part du prix venait d'ici : `rendreElements()`
repartait d'un `innerHTML = ""` — trente-sept lignes, leurs quatre boutons,
leurs infobulles et leur glisser, soit environ quatre cents nœuds et deux cent
cinquante écouteurs — à CHAQUE clic, alors que dans l'immense majorité des cas
seule la sélection avait bougé, c'est-à-dire deux classes par ligne.

`signatureListe()` départage les deux cas. Tout son danger est là : ce qu'elle
oublierait ne se verrait pas en la lisant, mais des semaines plus tard, sous la
forme d'un œil qui refuse de se fermer ou d'un groupe qui garde son ancien nom.
Ces tests disent donc ce qu'elle doit voir — et le seul cas où elle doit rester
sourde.

Ils n'assertent JAMAIS le format de la signature, seulement des égalités et des
différences : figer la forme reviendrait à interdire d'y ajouter un champ.
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

/** Une scène nue. Le panneau n'a pas de DOM ici : tous ses rendus sortent au
 *  premier `if`, seule la signature nous intéresse. */
function poser(ordre, groupes) {
  const elements = {};
  ordre.forEach(function (c) {
    elements[c] = {x: 50, y: 50, anchor: "center", scale: 1,
                   hidden: false, locked: false};
  });
  OA.etat.layout = {version: 1, defaut: "jeu", scenes: [
    {slug: "jeu", nom: "En jeu", ordre: ordre.slice(),
     groupes: groupes || [], elements: elements},
  ]};
  OA.etat.slugCourant = "jeu";
  OA.etat.selection = [];
  OA.etat.elementCourant = null;
  OA.etat.replies = {};
  OA.etat.libelles = {};
  return OA.etat.layout.scenes[0];
}

function sig(scene) { return OA.signatureListe(scene); }
""" % (json.dumps(str(_STATIC / "overlay_layout.js")),
       json.dumps(str(_STATIC / "overlay_admin.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def test_la_selection_seule_ne_change_pas_la_signature():
    """LE cas qui justifie tout le reste : choisir une ligne ne doit pas
    refaire quatre cents nœuds. La sélection se pose en deux classes."""
    assert _node("""
      const s = poser(["a", "b", "c"]);
      const avant = sig(s);
      OA.etat.selection = ["b"];
      OA.etat.elementCourant = "b";
      console.log(String(sig(s) === avant));
    """) == "true"


def test_masquer_un_element_change_la_signature():
    """Sinon l'œil garderait son icône : la ligne dit « visible » pendant que
    l'élément est masqué."""
    assert _node("""
      const s = poser(["a", "b"]);
      const avant = sig(s);
      s.elements.a.hidden = true;
      console.log(String(sig(s) !== avant));
    """) == "true"


def test_verrouiller_un_element_change_la_signature():
    """Le cadenas grise l'œil et change son titre : deux choses que la ligne
    montre."""
    assert _node("""
      const s = poser(["a", "b"]);
      const avant = sig(s);
      s.elements.b.locked = true;
      console.log(String(sig(s) !== avant));
    """) == "true"


def test_reordonner_change_la_signature():
    """L'ordre de la liste EST l'empilement : une liste figée mentirait sur ce
    qui passe devant."""
    assert _node("""
      const s = poser(["a", "b", "c"]);
      const avant = sig(s);
      s.ordre = ["c", "a", "b"];
      console.log(String(sig(s) !== avant));
    """) == "true"


def test_renommer_un_groupe_change_la_signature():
    assert _node("""
      const s = poser(["a", "b"], [{id: "g1", nom: "Tableau", membres: ["a", "b"]}]);
      const avant = sig(s);
      s.groupes[0].nom = "Tableau de bord";
      console.log(String(sig(s) !== avant));
    """) == "true"


def test_replier_un_groupe_change_la_signature():
    """Le chevron et les membres cachés : le repli se VOIT."""
    assert _node("""
      const s = poser(["a", "b"], [{id: "g1", nom: "G", membres: ["a", "b"]}]);
      const avant = sig(s);
      OA.etat.replies["jeu/g1"] = true;
      console.log(String(sig(s) !== avant));
    """) == "true"


def test_sortir_un_element_d_un_groupe_change_la_signature():
    """Le ⊖ n'apparaît que sur un membre, et la ligne change de place."""
    assert _node("""
      const s = poser(["a", "b"], [{id: "g1", nom: "G", membres: ["a", "b"]}]);
      const avant = sig(s);
      s.groupes[0].membres = ["a"];
      console.log(String(sig(s) !== avant));
    """) == "true"


def test_un_libelle_qui_arrive_change_la_signature():
    """Les libellés arrivent avec le GET, APRÈS le premier rendu : sans ça, la
    liste resterait sur les clés techniques jusqu'au prochain changement."""
    assert _node("""
      const s = poser(["a", "b"]);
      const avant = sig(s);
      OA.etat.libelles = {a: {nom: "Bulle de Wally", description: "ce qu'il dit"}};
      console.log(String(sig(s) !== avant));
    """) == "true"


def test_changer_de_scene_change_la_signature():
    """Deux scènes peuvent porter les mêmes clés dans le même ordre — et des
    visibilités différentes."""
    assert _node("""
      const s = poser(["a", "b"]);
      const avant = sig(s);
      const autre = {slug: "pause", nom: "Pause", ordre: ["a", "b"],
                     groupes: [], elements: s.elements};
      console.log(String(sig(autre) !== avant));
    """) == "true"
