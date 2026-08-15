"""Les repères du panneau de mise en scène épousent la taille RÉELLE.

Le défaut, dans les mots du streamer : « les box correspondent pas vraiment à la
taille du widget, genre les memes j'ai dû mettre la box giga grande comparé à la
taille des memes ». Le panneau dimensionnait chaque repère avec une table écrite
à la main (`WallyLayout.TAILLES`), qui n'a jamais été qu'un ordre de grandeur —
et l'écart se voyait dans les deux sens : `meme` supposé 720×540 pour un contenu
mesuré à 191×278, `planning` supposé 520×380 pour un contenu mesuré à 1298×738.

Tout ce que le panneau calcule passe par cette taille : l'alignement colle la
BOÎTE au bord, la répartition compte les espaces entre boîtes, le détecteur de
débordement compare les bords au cadre. Une taille fausse les fausse tous les
trois.

L'aperçu étant désormais la vraie page d'overlay, de même origine, la taille se
LIT. Ce fichier vérifie les trois maillons :

  1. `mesurerConteneur` — ce qui compte comme « affiché » et ce qui n'en est
     pas : les repères de « Tout afficher » (`.ghost`, taillés sur la table),
     un enfant à `opacity: 0`, un `display: none`.
  2. `geometrie` — la mesure l'emporte sur la table, et la table reste le repli.
  3. `positionAlignee` — un meme collé à droite pose son bord droit MESURÉ sur
     le bord du cadre, pas son bord supposé.

Plus la règle du cadenas (`cibleBascule`) : verrouillé vaut aussi pour la
visibilité, et `Suppr` ne masque plus un élément mis à l'abri.

Ces tests échouent sur le code d'avant : `mesurerConteneur`, `tailleRendue` et
`cibleBascule` n'existaient pas, et `geometrie` ne lisait que la table.
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
const W = 1920, H = 1080;        // le canvas lui-même : les px sont lisibles
function el(o) {
  return Object.assign({x: 50, y: 50, anchor: "center", scale: 1,
                        hidden: false, locked: false}, o);
}
// Un enfant de conteneur d'overlay, tel que `mesurerConteneur` le lit.
function enfant(l, h, opts) {
  const o = Object.assign({ghost: false, opacity: "1", visibility: "visible",
                           display: "block"}, opts || {});
  return {
    offsetWidth: l, offsetHeight: h,
    classList: {contains: function (c) { return c === "ghost" && o.ghost; }},
    _style: o,
  };
}
function hote(enfants) { return {children: enfants}; }
// La fenêtre de l'aperçu, réduite à ce que la mesure lui demande.
const VUE = {getComputedStyle: function (n) { return n._style; }};
function mesurer(enfants) { return OA.mesurerConteneur(hote(enfants), VUE); }
function poser(cle, l, h) { OA.mesures[cle] = [l, h]; }
function oublier() {
  Object.keys(OA.mesures).forEach(function (c) { delete OA.mesures[c]; });
}
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


# ── 1. Ce qui compte comme une taille, et ce qui n'en est pas ───────────────

def test_mesure_le_contenu_affiche():
    """Un conteneur qui montre quelque chose rend la taille de ce quelque chose."""
    assert _node("""
      console.log(JSON.stringify(mesurer([enfant(191, 278)])));
    """) == "[191,278]"


def test_conteneur_vide_ne_rend_aucune_taille():
    """`null`, jamais `[0, 0]` : « je ne sais pas » ne s'écrit pas en chiffres.

    C'est toute la question de ce lot. Un widget non déclenché n'a PAS de
    taille ; inventer un zéro poserait un repère d'un pixel au milieu de la
    scène, et personne ne saurait que c'est une absence de mesure.
    """
    assert _node("console.log(String(mesurer([])));") == "null"


def test_les_reperes_de_tout_afficher_ne_comptent_pas():
    """« Tout afficher » pose dans les conteneurs des `.ghost` taillés SUR LA
    TABLE. Les mesurer rendrait l'estimation déguisée en mesure — le repère
    dirait « 720 × 540 mesurés » pour un chiffre écrit à la main."""
    assert _node("""
      console.log(String(mesurer([enfant(720, 540, {ghost: true})])));
    """) == "null"


def test_un_enfant_invisible_ne_compte_pas():
    """La bulle et le cadre du rotateur restent dans le document à `opacity: 0`.
    Ils ont une boîte, mais personne ne les voit : mesurer une bulle vide
    donnerait la taille de ses marges."""
    assert _node("""
      const cas = [
        mesurer([enfant(460, 170, {opacity: "0"})]),
        mesurer([enfant(460, 170, {visibility: "hidden"})]),
        mesurer([enfant(0, 0)]),
      ];
      console.log(JSON.stringify(cas));
    """) == "[null,null,null]"


def test_le_max_des_enfants_superposes():
    """Les enfants d'un conteneur sont tous dans LA cellule de grille
    (`[data-element] > * { grid-area: pile }`) : ils se superposent. La taille
    du conteneur est donc leur maximum, pas leur somme — c'est exactement ce que
    `width: max-content` calcule. La carte qui sort et celle qui entre
    coexistent le temps d'une transition : les additionner ferait doubler le
    repère à chaque changement de widget."""
    assert _node("""
      console.log(JSON.stringify(mesurer([enfant(300, 100), enfant(120, 400)])));
    """) == "[300,400]"


def test_un_ghost_a_cote_dun_vrai_contenu_est_ignore():
    assert _node("""
      console.log(JSON.stringify(mesurer([
        enfant(720, 540, {ghost: true}), enfant(191, 278)])));
    """) == "[191,278]"


# ── 2. La mesure l'emporte sur la table, la table reste le repli ────────────

def test_taille_rendue_dit_dou_vient_le_chiffre():
    """Sans mesure, on rend la table EN LE DISANT. Un panneau qui affiche un
    ordre de grandeur avec l'aplomb d'une mesure est précisément ce qu'on
    corrige."""
    assert _node("""
      oublier();
      const sans = OA.tailleRendue("meme");
      poser("meme", 191, 278);
      const avec = OA.tailleRendue("meme");
      oublier();
      console.log(JSON.stringify([sans.taille, sans.reelle,
                                  avec.taille, avec.reelle]));
    """) == '[[720,540],false,[191,278],true]'


def test_la_geometrie_suit_la_mesure():
    """Le meme réel fait 191 × 278, la table en annonçait 720 × 540 : le repère
    passait de 2,8 à 3,8 fois trop grand sur chaque côté."""
    assert _node("""
      oublier();
      const table = OA.geometrie("meme", el({}), W, H);
      poser("meme", 191, 278);
      const vrai = OA.geometrie("meme", el({}), W, H);
      oublier();
      proche(table.largeur, 720); proche(table.hauteur, 540);
      proche(vrai.largeur, 191);  proche(vrai.hauteur, 278);
      console.log("ok");
    """) == "ok"


def test_une_mesure_nulle_ne_remplace_pas_la_table():
    """Une taille dégénérée (un widget saisi en pleine animation d'entrée) ne
    doit pas écraser l'estimation par un repère invisible."""
    assert _node("""
      oublier();
      OA.mesures.meme = [0, 0];
      const g = OA.geometrie("meme", el({}), W, H);
      oublier();
      proche(g.largeur, 720);
      console.log("ok");
    """) == "ok"


# ── 3. Ce qui dépendait de la table : alignement, débordement ───────────────

def test_aligner_a_droite_colle_le_bord_mesure():
    """LE test du lot. Ancrage `center`, meme mesuré à 191 px de large :
    son bord droit doit tomber sur 1920, donc `x = 100 − (191/2)/1920×100`
    ≈ 95,03. Avec la table (720), le panneau posait `x = 81,25` — et le meme
    RÉEL s'arrêtait 264 px avant le bord, sans que rien ne le dise."""
    assert _node("""
      oublier();
      poser("meme", 191, 278);
      const e = el({});
      const p = OA.positionAlignee("meme", e, "droite", W, H);
      e.x = p.x;
      const g = OA.geometrie("meme", e, W, H);
      oublier();
      proche(p.x, 95.03, 0.01);
      proche(g.droite, W, 0.5);      // le bord droit MESURÉ touche le cadre
      console.log("ok");
    """) == "ok"


def test_aligner_a_droite_avec_la_table_ratait_le_bord():
    """Le même geste sur le code d'avant, rejoué : la boîte supposée touchait le
    bord, le contenu réel restait 264 px en deçà. C'est ce que le streamer
    voyait — « la box giga grande comparé à la taille des memes »."""
    assert _node("""
      oublier();                       // pas de mesure : on est sur la table
      const e = el({});
      const p = OA.positionAlignee("meme", e, "droite", W, H);
      proche(p.x, 81.25, 0.01);
      // Là où le contenu RÉEL (191 px) se serait arrêté avec ce x :
      const reste = W - (p.x / 100 * W + 191 / 2);
      proche(reste, 264.5, 1);
      console.log("ok");
    """) == "ok"


def test_le_debordement_se_voit_avec_la_vraie_taille():
    """Le planning mesure 1298 × 738 là où la table en annonçait 520 × 380 :
    posé à `x = 80`, il sort de 385 px du cadre, et le détecteur ne disait
    rien."""
    assert _node("""
      oublier();
      const e = el({x: 80});
      const table = OA.geometrie("planning", e, W, H);
      poser("planning", 1298, 738);
      const vrai = OA.geometrie("planning", e, W, H);
      oublier();
      if (OA.horsCadre(table, W, H)) throw new Error("la table croyait tenir : c'est le défaut");
      if (!OA.horsCadre(vrai, W, H)) throw new Error("le débordement réel doit être vu");
      console.log("ok");
    """) == "ok"


def test_repartir_compte_les_vraies_boites():
    """La répartition égalise les BLANCS entre les boîtes. Avec des largeurs
    fausses, les blancs calculés le sont aussi : trois éléments réputés larges
    de 720 se seraient chevauchés là où les vrais (191) laissent de l'air."""
    assert _node("""
      oublier();
      poser("meme", 200, 200);
      poser("poll", 200, 200);
      poser("bingo", 200, 200);
      const boites = [
        OA.geometrie("meme",  el({x: 10}), W, H),
        OA.geometrie("poll",  el({x: 50}), W, H),
        OA.geometrie("bingo", el({x: 90}), W, H),
      ];
      const places = OA.repartitionEgale(boites, true);
      oublier();
      // Trois boîtes de 200 dans une travée [92 ; 1828] : deux blancs de 468.
      const debuts = places.map(function (p) { return Math.round(p.debut); });
      if (debuts.join(",") !== "92,860,1628") {
        throw new Error("débuts " + debuts.join(","));
      }
      console.log("ok");
    """) == "ok"


# ── 4. Le cadenas bloque TOUT, la visibilité comprise ───────────────────────

def test_le_cadenas_retient_le_masquage():
    """`Suppr` masquait un élément VERROUILLÉ, au motif que le verrou ne
    porterait que sur la position. C'est le geste le plus facile à faire par
    mégarde du panneau, et il faisait disparaître de l'antenne un élément qu'on
    avait explicitement mis à l'abri."""
    assert _node("""
      const scene = {elements: {
        a: el({locked: true}), b: el({}), c: el({locked: true})}};
      const t = OA.cibleBascule(scene, ["a", "b", "c"], "hidden");
      if (t.libres.join(",") !== "b") throw new Error("libres " + t.libres);
      if (t.bloques.join(",") !== "a,c") throw new Error("bloqués " + t.bloques);
      console.log("ok");
    """) == "ok"


def test_le_verrou_reste_levable():
    """Le cadenas fait exception à lui-même : sinon, une fois posé, plus rien ne
    pourrait jamais le lever."""
    assert _node("""
      const scene = {elements: {a: el({locked: true}), b: el({})}};
      const t = OA.cibleBascule(scene, ["a", "b"], "locked");
      if (t.libres.join(",") !== "a,b") throw new Error("libres " + t.libres);
      if (t.bloques.length) throw new Error("rien ne doit être retenu");
      console.log("ok");
    """) == "ok"


def test_une_cle_fantome_ne_compte_nulle_part():
    """Une clé de sélection qui n'existe plus dans la scène (brouillon d'une
    version d'avant) ne doit ni bouger ni être annoncée comme retenue."""
    assert _node("""
      const scene = {elements: {a: el({})}};
      const t = OA.cibleBascule(scene, ["a", "disparu"], "hidden");
      if (t.libres.join(",") !== "a") throw new Error("libres " + t.libres);
      if (t.bloques.length) throw new Error("bloqués " + t.bloques);
      console.log("ok");
    """) == "ok"
