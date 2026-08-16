"""Exporter la mise en scène, la réimporter, et refuser ce qui n'en est pas une.

Le piège de l'import est côté SERVEUR, et il ne lève rien : `fusionner()` rend
`layout_par_defaut()` sur toute entrée qui n'a pas de `scenes` exploitable
(bot/core/overlay_layout.py). C'est le bon comportement pour lui — un JSON
tronqué en base ne doit jamais donner un overlay vide en plein live — mais il
veut dire qu'un fichier tordu envoyé par le panneau écraserait TOUTE la mise en
scène par la livraison, en silence et à l'antenne.

D'où `refusImport`, avant l'envoi. Ce n'est pas une revalidation du serveur :
c'est la garde contre son repli. Ce fichier vérifie les deux côtés — que le
refus attrape ce qu'il doit, et que le serveur borne bien ce qui passe.

Ces tests échouent sur le code d'avant : `refusImport` et `nomExport`
n'existaient pas.
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.core.overlay_layout import layout_par_defaut
from bot.dashboard.routes.overlay import admin_router

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
global.navigator = {};
require(%s);
require(%s);
const OA = window.OverlayAdmin;
""" % (json.dumps(str(_STATIC / "overlay_layout.js")),
       json.dumps(str(_STATIC / "overlay_admin.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class _State:
    def __init__(self):
        self.rows = {}

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


def _client(db):
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/admin")
    app.state.wally = MagicMock()
    app.state.wally.db = db
    return TestClient(app)


js = pytest.mark.skipif(_SANS_NODE, reason="node absent")


@js
def test_un_fichier_qui_nest_pas_une_mise_en_scene_est_refuse_avant_lenvoi():
    """Chacun de ces cas, envoyé tel quel, aurait remis la LIVRAISON à l'antenne
    sans un mot — c'est le repli de `fusionner()`, et il ne lève pas."""
    out = _node("""
    const cas = {
      nul: null,
      liste: [1, 2, 3],
      texte: "coucou",
      sansScenes: {version: 1, defaut: "jeu"},
      scenesVides: {scenes: []},
      scenesSansSlug: {scenes: [{nom: "En jeu"}, {slug: "   "}]},
      bon: {version: 1, defaut: "jeu",
            scenes: [{slug: "jeu", nom: "En jeu", elements: {}}]},
    };
    const out = {};
    Object.keys(cas).forEach(function (c) { out[c] = OA.refusImport(cas[c]) === null; });
    console.log(JSON.stringify(out));
    """)
    assert json.loads(out) == {
        "nul": False, "liste": False, "texte": False,
        "sansScenes": False, "scenesVides": False, "scenesSansSlug": False,
        "bon": True,
    }


@js
def test_le_nom_du_fichier_porte_la_date():
    """« Celui d'avant le live de samedi » : sans date, on ne les distingue pas."""
    out = _node("""console.log(OA.nomExport());""")
    assert out.startswith("wally-mise-en-scene-")
    assert out.endswith(".json")
    # AAAA-MM-JJ, deux chiffres partout : un `2026-8-3` ne se trie pas.
    corps = out[len("wally-mise-en-scene-"):-len(".json")]
    annee, mois, jour = corps.split("-")
    assert len(annee) == 4 and len(mois) == 2 and len(jour) == 2


def test_un_fichier_exporte_puis_reimporte_rend_le_meme_modele():
    """Le tour complet : ce qui sort du GET, renvoyé au PUT, revient identique.

    C'est ce qui rend l'export utile — un format d'échange à part aurait dérivé
    du modèle au premier champ ajouté.
    """
    db = _State()
    client = _client(db)

    # On règle trois éléments, on publie, on « exporte ».
    layout = layout_par_defaut()
    layout["scenes"][0]["elements"]["bingo"].update(
        {"x": 12.5, "y": 71.0, "anchor": "bottom-left", "scale": 0.7})
    layout["scenes"][1]["elements"]["avatar"].update({"x": 4.0, "hidden": True})
    layout["scenes"][2]["elements"]["stats"].update({"scale": 1.8})
    exporte = client.put("/api/admin/overlay/layout", json=layout).json()

    # On abîme la mise en scène rangée, comme le ferait un live entier.
    autre = layout_par_defaut()
    autre["scenes"][0]["elements"]["bingo"].update({"x": 99.0, "y": 1.0})
    client.put("/api/admin/overlay/layout", json=autre)

    # On réimporte le fichier : on retrouve l'état exporté, au champ près.
    revenu = client.put("/api/admin/overlay/layout",
                        content=json.dumps(exporte).encode()).json()
    assert revenu == exporte


def test_le_serveur_borne_et_complete_ce_quun_fichier_bricole_apporte():
    """L'import passe par la publication, donc par la même porte que le reste :
    valeurs hors bornes ramenées dedans, élément inconnu ignoré, élément absent
    complété par son défaut. Un fichier édité à la main ne casse rien."""
    bricole = {
        "version": 1, "defaut": "jeu",
        "scenes": [{
            "slug": "jeu", "nom": "En jeu",
            "elements": {
                "bingo": {"x": 900.0, "y": -40.0, "scale": 99.0,
                          "anchor": "n-importe-quoi"},
                "widget_qui_nexiste_pas": {"x": 10.0},
            },
        }],
    }
    rendu = _client(_State()).put("/api/admin/overlay/layout", json=bricole).json()
    elements = rendu["scenes"][0]["elements"]
    assert elements["bingo"]["x"] == 100.0        # borné
    assert elements["bingo"]["y"] == 0.0          # borné
    assert elements["bingo"]["scale"] == 2.0      # borné
    assert elements["bingo"]["anchor"] == "top-left"   # défaut, ancrage inconnu
    assert "widget_qui_nexiste_pas" not in elements
    # Complété : les trente-trois autres éléments sont là, à leur défaut.
    assert elements["avatar"] == layout_par_defaut()["scenes"][0]["elements"]["avatar"]
