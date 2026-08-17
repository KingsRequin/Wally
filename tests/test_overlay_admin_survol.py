"""Le survol relie la liste et l'aperçu — dans UN SEUL sens.

Le défaut, dans les mots de l'owner : « corriger le fait que survoler un élément
dans la visualisation le sélectionne dans la liste. Si on survole dans la liste
ça doit mettre en surbrillance sur l'aperçu, mais pas l'inverse. »

Le lien était symétrique, et il faisait plus que marquer : passer le pointeur sur
un repère de l'aperçu éclairait la ligne correspondante ET faisait DÉFILER la
liste jusqu'à elle. Sur trente-quatre éléments dont vingt-six partent au même
endroit, la liste sautait à chaque va-et-vient du pointeur au-dessus de la
scène — ce qui se lit comme une sélection qu'on n'a pas demandée.

Le sens conservé est celui qui répond à une question qu'on se pose vraiment :
« cette ligne, c'est lequel des repères ? ». L'autre sens répondait à une
question que le repère pose déjà lui-même, puisqu'il porte son nom.

Ces tests échouent sur le code d'avant : `cotesDuSurvol` n'existait pas, et
`survoler()` prenait un drapeau de défilement au lieu d'une origine.
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
// Les deux hôtes, réduits à ce que la marque leur demande.
const CALQUE = "calque", LISTE = "liste";
""" % (json.dumps(str(_STATIC / "overlay_layout.js")),
       json.dumps(str(_STATIC / "overlay_admin.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def test_survoler_une_ligne_eclaire_l_apercu():
    """Le sens utile : trente-quatre lignes, et un repère invisible tant que le
    widget n'affiche rien — sans cette marque, on ne sait pas ce qu'on règle."""
    assert _node("""
      console.log(JSON.stringify(OA.cotesDuSurvol("liste", CALQUE, LISTE)));
    """) == '["calque","liste"]'


def test_survoler_l_apercu_ne_touche_pas_la_liste():
    """Le sens retiré. Le repère porte déjà son nom au survol : éclairer la
    ligne n'apprenait rien, et faire défiler la liste jusqu'à elle donnait
    l'impression d'une sélection déclenchée par un simple passage du pointeur."""
    assert _node("""
      console.log(JSON.stringify(OA.cotesDuSurvol("surface", CALQUE, LISTE)));
    """) == '["calque"]'


def test_une_origine_inconnue_se_comporte_comme_la_liste():
    """Un appel sans origine ne doit pas faire DISPARAÎTRE la marque : le repli
    est le comportement complet, jamais le silencieux."""
    assert _node("""
      const cas = [OA.cotesDuSurvol(null, CALQUE, LISTE),
                   OA.cotesDuSurvol(undefined, CALQUE, LISTE),
                   OA.cotesDuSurvol("", CALQUE, LISTE)];
      console.log(JSON.stringify(cas));
    """) == '[["calque","liste"],["calque","liste"],["calque","liste"]]'


def test_le_survol_de_la_surface_ne_fait_plus_defiler_la_liste():
    """La liste sautait sous le pointeur à chaque passage au-dessus de la scène.
    Ce test lit la source parce que le défilement est un effet de bord du DOM :
    ce qu'on vérifie, c'est qu'aucun code ne le rétablit."""
    src = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")
    bloc = src.split("── Le survol", 1)[1].split("── La liste des éléments", 1)[0]
    assert "scrollTop" not in bloc, (
        "le survol refait défiler la liste : c'est le geste qui se lisait "
        "comme une sélection non demandée")


def test_les_deux_cotes_sont_toujours_nettoyes():
    """La marque doit partir des DEUX côtés à chaque passe, quelle que soit
    l'origine : sinon celle posée depuis la liste resterait allumée quand le
    pointeur passe ensuite sur la surface."""
    src = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")
    bloc = src.split("function appliquerSurvol", 1)[1].split("\n  }", 1)[0]
    assert "noeuds.calque" in bloc and "noeuds.listeElements" in bloc, (
        "le nettoyage doit viser les deux hôtes, pas seulement celui qu'on marque")
