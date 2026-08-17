"""La capture de stream en fond de la surface de placement.

« On place par rapport au décor réel — le cadre du chat, la zone de jeu — plutôt
que dans le vide » (`docs/plans/2026-08-15-overlay-scenes-layout-design.md`).

Une aide au placement, donc : elle vit dans le NAVIGATEUR, ne va pas en base et
ne part jamais vers l'overlay. Trois propriétés la rendent utilisable sans
danger, et la deuxième est celle qui compte vraiment :

  1. L'opacité est bornée : à 0 %, le fond disparaît sans qu'on comprenne
     pourquoi le bouton ne fait rien.
  2. **Le fond ne chasse JAMAIS le brouillon.** Les deux vivent dans le même
     `localStorage`, cinq mégaoctets en tout, et une capture 1920 × 1080 en PNG
     en pèse plusieurs à elle seule. Un travail non publié perdu au profit d'une
     image de décor serait le pire échange possible.
  3. Ce qu'on relit est refusé si ce n'est pas une image. La valeur repart en
     `src` d'une balise : y laisser passer n'importe quelle chaîne rangée sous
     cette clé, c'est offrir le point d'entrée.

Ces tests échouent sur le code d'avant : `rangerFond`, `lireFond` et
`bornerOpaciteFond` n'existaient pas.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
global.navigator = {};
// Un `localStorage` de poche, avec un quota qu'on peut fermer à volonté : c'est
// le contrat du navigateur qu'on rejoue, y compris son refus.
function stockage(plafond) {
  const boite = {};
  return {
    boite: boite,
    plein: false,
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(boite, k) ? boite[k] : null; },
    setItem: function (k, v) {
      if (this.plein) {
        const e = new Error("QuotaExceededError");
        e.name = "QuotaExceededError";
        throw e;
      }
      boite[k] = String(v);
    },
    removeItem: function (k) { delete boite[k]; },
  };
}
global.window.localStorage = stockage();
require(%s);
require(%s);
const OA = window.OverlayAdmin;
// Une dataURL d'image minuscule mais authentique (un GIF d'un pixel).
const IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
""" % (json.dumps(str(_STATIC / "overlay_layout.js")),
       json.dumps(str(_STATIC / "overlay_admin.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_lopacite_reste_dans_des_bornes_utiles():
    """En dessous de 20 %, le fond est invisible et le curseur passe pour cassé.
    Au-dessus de 100 %, la valeur n'a pas de sens."""
    out = _node("""
      console.log(JSON.stringify([0, 5, 20, 55, 100, 140, -3, NaN, null, "abc"]
        .map(function (v) { return OA.bornerOpaciteFond(v); })));
    """)
    valeurs = json.loads(out)
    assert valeurs[:6] == [20, 20, 20, 55, 100, 100]
    # Ce qui n'est pas un nombre retombe sur un défaut lisible, jamais sur 0.
    for v in valeurs[6:]:
        assert 20 <= v <= 100


def test_le_fond_range_se_relit():
    out = _node("""
      OA.rangerFond(IMAGE, 45);
      console.log(JSON.stringify(OA.lireFond()));
    """)
    d = json.loads(out)
    assert d["image"].startswith("data:image/")
    assert d["opacite"] == 45


def test_un_stockage_plein_ne_fait_pas_perdre_le_brouillon():
    """LE test du lot. Le brouillon est rangé d'abord ; le fond arrive ensuite et
    le quota se ferme. Le brouillon doit être intact, et le refus DIT — un fond
    qui ne survit pas au rechargement sans que rien ne l'annonce se lit comme un
    bug du bouton."""
    out = _node("""
      OA.etat.layout = {version: 1, defaut: "jeu", scenes: [
        {slug: "jeu", nom: "En jeu", ordre: [], groupes: [], elements: {}}]};
      OA.etat.brouillon = 3;
      OA.rangerBrouillon();
      const avant = window.localStorage.getItem("wally.overlay.brouillon");
      window.localStorage.plein = true;
      const range = OA.rangerFond(IMAGE, 60);
      window.localStorage.plein = false;
      const apres = window.localStorage.getItem("wally.overlay.brouillon");
      console.log(JSON.stringify({range: range, intact: avant === apres,
                                  brouillonPresent: !!apres}));
    """)
    d = json.loads(out)
    assert d["range"] is False, "un rangement refusé doit se dire, pas se taire"
    assert d["brouillonPresent"] and d["intact"], "le brouillon a été touché"


def test_ce_qui_nest_pas_une_image_est_refuse_a_la_relecture():
    """La valeur repart en `src` d'une balise. Une autre extension du dashboard,
    un ancien format, une clé écrasée à la main : on ne pose que ce qu'on
    reconnaît."""
    out = _node("""
      const cas = ["javascript:alert(1)", "http://ailleurs/x.png", "",
                   "data:text/html,<script>alert(1)</script>",
                   "data:image/svg+xml,<svg onload=alert(1)>"];
      const vus = cas.map(function (v) {
        window.localStorage.setItem("wally:overlay:fond",
          JSON.stringify({image: v, opacite: 50}));
        return OA.lireFond();
      });
      console.log(JSON.stringify(vus));
    """)
    vus = json.loads(out)
    # Aucun de ces cas ne doit ressortir. Le SVG est le plus discret : en `<img>`
    # ses scripts ne s'exécutent pas, mais rien ne garantit qu'il restera dans
    # une `<img>` — la reconnaissance ne s'appuie pas sur cette subtilité.
    assert all(v is None for v in vus), vus


def test_un_rangement_tordu_ne_casse_pas_louverture():
    """Le panneau se règle en plein live : une préférence d'affichage illisible
    ne doit jamais l'empêcher de s'ouvrir."""
    out = _node("""
      const cas = ["pas du json", "null", "[]", "{}", '{"image":123}'];
      const vus = cas.map(function (v) {
        window.localStorage.setItem("wally:overlay:fond", v);
        return OA.lireFond();
      });
      console.log(JSON.stringify(vus));
    """)
    assert json.loads(out) == [None] * 5


def test_oublier_le_fond_le_retire_du_rangement():
    out = _node("""
      OA.rangerFond(IMAGE, 70);
      OA.oublierFond();
      console.log(JSON.stringify([OA.lireFond(),
        window.localStorage.getItem("wally:overlay:fond")]));
    """)
    assert json.loads(out) == [None, None]


def test_le_fond_ne_part_jamais_dans_le_modele_publie():
    """Il n'a rien à faire à l'antenne : c'est un décor de travail. Rangé dans le
    modèle, il partirait au premier « Mettre à jour » — et le PUT le rendrait au
    panneau comme un réglage de scène."""
    out = _node("""
      OA.etat.layout = {version: 1, defaut: "jeu", scenes: [
        {slug: "jeu", nom: "En jeu", ordre: [], groupes: [], elements: {}}]};
      const avant = JSON.stringify(OA.etat.layout);
      OA.rangerFond(IMAGE, 80);
      console.log(JSON.stringify({
        modeleIntact: JSON.stringify(OA.etat.layout) === avant,
        brouillon: OA.etat.brouillon}));
    """)
    d = json.loads(out)
    assert d["modeleIntact"], "le fond a touché au modèle"
    assert d["brouillon"] == 0, "poser un fond ne se publie pas"
