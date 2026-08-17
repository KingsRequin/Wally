"""Le glisser du panneau de mise en scène, vérifié hors navigateur.

Ce qui est testé ici n'est pas l'interface mais sa GÉOMÉTRIE : le calcul qui
transforme une position de pointeur en `x`/`y` du modèle. C'est là que tout se
joue — un élément ancré `bottom-right` mesure sa position depuis le bord droit,
un `center` depuis son centre, et se tromper d'un demi-widget est invisible à la
lecture du code.

Le code est chargé dans node avec un `window` nu : les quatre fonctions
exposées (`geometrie`, `positionDepuisPointeur`, `aimanter`, `reancrer`) sont
pures, elles ne touchent ni au DOM ni au réseau.

Ces tests échouent tous sur le code d'avant (les fonctions n'existaient pas).
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
const W = 800, H = 450;          // une surface plausible du panneau
const ANCRAGES = [
  "top-left", "top-center", "top-right",
  "middle-left", "center", "middle-right",
  "bottom-left", "bottom-center", "bottom-right",
];
function el(o) {
  return Object.assign({x: 50, y: 50, anchor: "center", scale: 1,
                        hidden: false, locked: false}, o);
}
function pointeur(x, y) { return {clientX: x, clientY: y}; }
const CADRE = {left: 0, top: 0, width: W, height: H};
function proche(a, b, tol) {
  if (Math.abs(a - b) > (tol === undefined ? 1e-9 : tol)) {
    throw new Error("attendu " + b + ", obtenu " + a);
  }
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


def test_le_point_d_ancrage_tombe_a_x_pour_cent_du_bord_gauche():
    """La propriété qui rend le glisser identique pour les neuf ancrages.

    Un ancrage à droite pose `right: (100 − x) %` : son bord droit retombe donc
    à `x %` depuis la GAUCHE. Si ce n'était pas vrai, il faudrait un calcul par
    ancrage — et c'est exactement là que les erreurs se logent.
    """
    out = _node("""
    ANCRAGES.forEach(function (a) {
      const g = OA.geometrie("bingo", el({x: 37, y: 64, anchor: a, scale: 0.9}), W, H);
      proche(g.ax, 0.37 * W);
      proche(g.ay, 0.64 * H);
    });
    console.log("ok");
    """)
    assert out == "ok"


def test_le_point_saisi_reste_sous_le_pointeur_pour_les_neuf_ancrages():
    """Le cœur du glisser : la boîte se déplace EXACTEMENT du déplacement du
    pointeur, quel que soit l'ancrage et quel que soit l'endroit saisi."""
    out = _node("""
    ANCRAGES.forEach(function (a) {
      const e = el({x: 40, y: 45, anchor: a, scale: 0.8});
      const avant = OA.geometrie("stats", e, W, H);
      // On saisit un point quelconque DANS la boîte, pas son ancrage.
      const p0 = pointeur(avant.gauche + 12, avant.haut + 30);
      const brut = OA.positionDepuisPointeur(p0, CADRE, null);
      const decalage = {x: brut.x - e.x, y: brut.y - e.y};
      const p1 = pointeur(p0.clientX + 53, p0.clientY - 27);
      const pos = OA.positionDepuisPointeur(p1, CADRE, decalage);
      e.x = pos.x; e.y = pos.y;
      const apres = OA.geometrie("stats", e, W, H);
      proche(apres.gauche - avant.gauche, 53, 1e-9);
      proche(apres.haut - avant.haut, -27, 1e-9);
    });
    console.log("ok");
    """)
    assert out == "ok"


def test_l_echelle_ne_deplace_jamais_le_point_d_ancrage():
    """Ce qui autorise les poignées à ne toucher qu'à `scale` : l'ancrage est
    le point FIXE de la mise à l'échelle. Sinon, redimensionner déplacerait."""
    out = _node("""
    ANCRAGES.forEach(function (a) {
      const petit = OA.geometrie("meme", el({x: 30, y: 70, anchor: a, scale: 0.2}), W, H);
      const grand = OA.geometrie("meme", el({x: 30, y: 70, anchor: a, scale: 2.0}), W, H);
      proche(petit.ax, grand.ax);
      proche(petit.ay, grand.ay);
      if (!(grand.largeur > petit.largeur)) throw new Error("l'échelle n'agit pas");
    });
    console.log("ok");
    """)
    assert out == "ok"


def test_un_element_centre_et_reduit_est_bien_centre():
    """Le piège maison : `translate(-50%,-50%)` se mesure sur la taille NON
    transformée. Écrit dans le mauvais ordre, un élément centré et réduit
    atterrissait à 39 % au lieu de 50."""
    out = _node("""
    [1, 0.5, 0.2, 2].forEach(function (s) {
      const g = OA.geometrie("image", el({x: 50, y: 50, anchor: "center", scale: s}), W, H);
      proche((g.gauche + g.droite) / 2, W / 2);
      proche((g.haut + g.bas) / 2, H / 2);
      // La taille rendue suit l'échelle. La largeur de référence est LUE dans
      // la table et non recopiée ici : elle se mesure sur le contenu réel et a
      // déjà changé une fois (1280 écrits au jugé, 720 mesurés). Un test qui la
      // duplique fait passer un relevé légitime pour une régression.
      proche(g.largeur, window.WallyLayout.taille("image")[0] * s * (W / 1920), 1e-9);
    });
    console.log("ok");
    """)
    assert out == "ok"


def test_changer_d_ancrage_ne_deplace_pas_l_element():
    """Sans ça, changer d'ancrage est un déplacement involontaire — et
    personne n'ose plus y toucher."""
    out = _node("""
    ANCRAGES.forEach(function (depuis) {
      ANCRAGES.forEach(function (vers) {
        const e = el({x: 50, y: 50, anchor: depuis, scale: 0.6});
        const avant = OA.geometrie("bingo", e, W, H);
        OA.reancrer(e, "bingo", vers, W, H);
        const apres = OA.geometrie("bingo", e, W, H);
        if (e.anchor !== vers) throw new Error("ancrage non posé");
        // Deux décimales de pourcentage : la tolérance est celle de l'arrondi
        // qu'on écrit dans le modèle, soit 0,01 % de la surface.
        proche(apres.gauche, avant.gauche, W / 10000 + 1e-9);
        proche(apres.haut, avant.haut, H / 10000 + 1e-9);
      });
    });
    console.log("ok");
    """)
    assert out == "ok"


def test_l_aimantation_accroche_la_grille_les_bords_et_le_centre():
    out = _node("""
    // Rien dans la portée : la valeur passe telle quelle.
    proche(OA.aimanter(48.5, 1.0, true).valeur, 48.5);
    if (OA.aimanter(48.5, 1.0, true).ligne !== null) throw new Error("ligne parasite");
    // Le centre.
    proche(OA.aimanter(49.4, 1.0, true).valeur, 50);
    proche(OA.aimanter(49.4, 1.0, true).ligne, 50);
    // Les bords.
    proche(OA.aimanter(0.4, 1.0, true).valeur, 0);
    proche(OA.aimanter(99.6, 1.0, true).valeur, 100);
    // Une graduation de la grille.
    proche(OA.aimanter(21.0, 1.5, true).valeur, 20);
    // À distance égale, le centre l'emporte sur la graduation de 40.
    proche(OA.aimanter(45.0, 6.0, true).valeur, 50);
    // Alt suspend tout.
    proche(OA.aimanter(49.4, 1.0, false).valeur, 49.4);
    if (OA.aimanter(49.4, 1.0, false).ligne !== null) throw new Error("ligne malgré Alt");
    console.log("ok");
    """)
    assert out == "ok"


def test_la_position_est_bornee_a_la_saisie():
    """Borner au relâchement seulement laisserait le repère filer hors du cadre
    puis revenir en arrière : on ne saurait plus ce qu'on a posé."""
    out = _node("""
    proche(OA.positionDepuisPointeur(pointeur(-400, -400), CADRE, null).x, 0);
    proche(OA.positionDepuisPointeur(pointeur(-400, -400), CADRE, null).y, 0);
    proche(OA.positionDepuisPointeur(pointeur(9000, 9000), CADRE, null).x, 100);
    proche(OA.positionDepuisPointeur(pointeur(9000, 9000), CADRE, null).y, 100);
    console.log("ok");
    """)
    assert out == "ok"


def test_le_debordement_est_detecte():
    out = _node("""
    const dedans = OA.geometrie("bingo", el({x: 50, y: 50, anchor: "center", scale: 0.5}), W, H);
    if (OA.horsCadre(dedans, W, H)) throw new Error("faux positif");
    const dehors = OA.geometrie("bingo", el({x: 99, y: 50, anchor: "center", scale: 1}), W, H);
    if (!OA.horsCadre(dehors, W, H)) throw new Error("débordement manqué");
    // Un élément ancré en bas à droite, posé sur le coin, tient dans le cadre.
    const coin = OA.geometrie("bingo", el({x: 100, y: 100, anchor: "bottom-right", scale: 1}), W, H);
    if (OA.horsCadre(coin, W, H)) throw new Error("faux positif sur le coin");
    console.log("ok");
    """)
    assert out == "ok"


def test_le_javascript_du_panneau_reste_syntaxiquement_valide():
    r = subprocess.run(["node", "--check", str(_STATIC / "overlay_admin.js")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
