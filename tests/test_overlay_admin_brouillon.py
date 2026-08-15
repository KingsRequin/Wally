"""Le brouillon du panneau de mise en scène : où il vit, et ce qu'il refuse.

Ce qui se joue ici tient en une phrase : un placement non publié doit survivre à
un F5 **sans jamais partir à l'antenne tout seul**. D'où deux exigences que ces
tests figent :

  1. Le brouillon vit dans le NAVIGATEUR. Rangé côté serveur, il serait servi
     aux pages d'overlay au prochain redémarrage du bot — donc publié sans avoir
     été validé.
  2. Un stockage muet, plein ou tordu ne casse rien. Le panneau se règle en
     plein live ; une préférence d'affichage ne doit jamais l'empêcher de
     s'ouvrir.

Comme `test_overlay_admin_glisser.py`, le fichier est chargé dans node avec un
`window` nu : ces trois fonctions ne touchent ni au DOM ni au réseau.

Sur le code d'avant, elles n'existaient pas — `OverlayAdmin.rangerBrouillon` y
est `undefined` et tous ces tests échouent.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
global.navigator = {};
// Un `localStorage` de poche : c'est le contrat du navigateur qu'on rejoue,
// pas une implémentation à tester.
function stockage() {
  const boite = {};
  return {
    boite: boite,
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(boite, k) ? boite[k] : null; },
    setItem: function (k, v) { boite[k] = String(v); },
    removeItem: function (k) { delete boite[k]; },
  };
}
global.window.localStorage = stockage();
require(%s);
require(%s);
const OA = window.OverlayAdmin;
const CLE = "wally.overlay.brouillon";
function layout() {
  return {defaut: "jeu", scenes: [
    {slug: "jeu", nom: "Jeu", ordre: ["avatar"],
     elements: {avatar: {x: 97, y: 80, anchor: "bottom-right", scale: 0.55}}},
  ]};
}
function egal(a, b) {
  if (a !== b) throw new Error("attendu " + JSON.stringify(b) + ", obtenu " + JSON.stringify(a));
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


def test_le_brouillon_survit_et_porte_son_compte():
    """Ce qu'on range est ce qu'on relit : le modèle, le compte, et la scène."""
    assert _node("""
      OA.etat.layout = layout();
      OA.etat.brouillon = 4;
      OA.etat.slugCourant = "jeu";
      OA.etat.publie = JSON.stringify(layout());
      OA.rangerBrouillon();
      const d = OA.lireBrouillon();
      egal(d.n, 4);
      egal(d.scene, "jeu");
      egal(d.layout.scenes[0].elements.avatar.x, 97);
      egal(d.base, OA.etat.publie);
      console.log("ok");
    """) == "ok"


def test_le_brouillon_ne_va_QUE_dans_le_navigateur():
    """Une seule clé de stockage local, et aucun appel réseau au passage.

    `apiFetch` absent : s'il était touché, `appeler()` rejetterait et le test
    verrait une promesse non gérée. Le rangement doit être purement local.
    """
    assert _node("""
      let reseau = 0;
      window.apiFetch = function () { reseau += 1; return Promise.reject(new Error("interdit")); };
      OA.etat.layout = layout();
      OA.etat.brouillon = 2;
      OA.rangerBrouillon();
      egal(reseau, 0);
      egal(Object.keys(window.localStorage.boite).indexOf("wally.overlay.brouillon") >= 0, true);
      console.log("ok");
    """) == "ok"


def test_oublier_efface_vraiment():
    assert _node("""
      OA.etat.layout = layout();
      OA.etat.brouillon = 1;
      OA.rangerBrouillon();
      OA.oublierBrouillon();
      egal(OA.lireBrouillon(), null);
      console.log("ok");
    """) == "ok"


def test_un_brouillon_a_zero_modification_n_est_pas_proposé():
    """Sinon on proposerait de « reprendre » ce qui est déjà à l'antenne."""
    assert _node("""
      OA.etat.layout = layout();
      OA.etat.brouillon = 0;
      OA.rangerBrouillon();
      egal(OA.lireBrouillon(), null);
      console.log("ok");
    """) == "ok"


def test_un_stockage_illisible_ne_casse_rien():
    """JSON tronqué par un quota, ou reliquat d'une version d'avant."""
    assert _node("""
      window.localStorage.setItem(CLE, "{ceci n'est pas du JSON");
      egal(OA.lireBrouillon(), null);
      window.localStorage.setItem(CLE, JSON.stringify({n: 3}));          // sans layout
      egal(OA.lireBrouillon(), null);
      window.localStorage.setItem(CLE, JSON.stringify({n: 3, layout: {scenes: []}}));
      egal(OA.lireBrouillon(), null);
      console.log("ok");
    """) == "ok"


def test_un_stockage_qui_leve_ne_casse_rien():
    """Mode privé, stockage refusé, quota dépassé : trois façons de lever."""
    assert _node("""
      window.localStorage = {
        getItem: function () { throw new Error("refusé"); },
        setItem: function () { throw new Error("plein"); },
        removeItem: function () { throw new Error("refusé"); },
      };
      OA.etat.layout = layout();
      OA.etat.brouillon = 2;
      OA.rangerBrouillon();       // ne doit pas lever
      OA.oublierBrouillon();      // ne doit pas lever
      egal(OA.lireBrouillon(), null);
      console.log("ok");
    """) == "ok"
