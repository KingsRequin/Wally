"""Le spam de popups : ça commence doucement et ça ACCÉLÈRE.

Demande de l'owner (2026-08-17), en essai à côté de l'avalanche de memes :
« popup de virus qui spam et qui se superpose, ça commence doucement et ça
accélère ». Deux gabarits mêlés — fausses alertes et fenêtres à meme — qui
s'empilent sans jamais disparaître : c'est l'accumulation qui fait le gag, pas le
mouvement.

Le séquencement vit dans `overlay_virus.js`, hors du DOM, pour être EXÉCUTÉ ici
plutôt que relu au grep — même parti pris que `overlay_avalanche.js`, et pour la
même raison : un test qui cherche un bout de code fige l'écriture du jour.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
require(%s);
require(%s);
const V = window.WallyVirus;
""" % (json.dumps(str(_STATIC / "overlay_avalanche.js")),
       json.dumps(str(_STATIC / "overlay_virus.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ── 1. L'accélération ───────────────────────────────────────────────────────

def test_l_intervalle_DECROIT_du_debut_a_la_fin():
    """Le cœur de la demande. Chaque fenêtre arrive plus vite que la
    précédente — pas de palier, pas de retour en arrière."""
    assert _node("""
      const t = V.rythme(23);
      let decroit = true;
      for (let i = 2; i < t.length; i++) {
        if ((t[i] - t[i - 1]) > (t[i - 1] - t[i - 2]) + 0.001) decroit = false;
      }
      console.log(JSON.stringify([t.length > 10, decroit]));
    """) == "[true,true]"


def test_ca_commence_DOUCEMENT_et_ca_finit_en_rafale():
    """« Doucement » se mesure : environ une par seconde au départ, dix fois
    plus vite à l'arrivée. Sans cet écart, l'accélération ne se voit pas."""
    assert _node("""
      const t = V.rythme(23);
      const premier = t[1] - t[0];
      const dernier = t[t.length - 1] - t[t.length - 2];
      console.log(JSON.stringify([premier >= 700, dernier <= 200,
                                  premier / dernier >= 5]));
    """) == "[true,true,true]"


def test_le_spam_tient_dans_sa_FENETRE():
    """La dernière fenêtre doit s'ouvrir avant l'écran bleu, sinon elle naît
    sous lui — invisible, et le compte du spectacle est faux."""
    assert _node("""
      const cas = [10, 23, 40];
      const ok = cas.map(d => {
        const t = V.rythme(d);
        return t[t.length - 1] <= d * 1000 + 1;
      });
      console.log(JSON.stringify(ok));
    """) == "[true,true,true]"


def test_TOUT_le_dossier_passe_sur_la_duree_que_le_serveur_annonce():
    """« Y a pas tous les memes si ? » (owner) — non : 42 sur 134 au premier
    essai. Le plafond bornait le SPECTACLE au lieu de borner le DOM.

    Le serveur dimensionne la fenêtre sur le stock (`_duree_virus`), le client
    doit y faire tenir toutes ses ouvertures. La formule vit des deux côtés :
    c'est leur ACCORD que ce test surveille, pas son écriture.
    """
    assert _node("""
      const memes = 134;
      const total = Math.ceil(memes / (1 - V.PART_ALERTES));
      const duree = V.dureePour(total);
      const stock = [];
      for (let i = 0; i < memes; i++) stock.push({nom: "m" + i, genre: "image"});
      const f = V.fenetres(V.rythme(duree), stock);
      const passes = new Set(f.filter(x => x.genre === "meme").map(x => x.media.nom));
      console.log(JSON.stringify([f.length >= total, passes.size === memes]));
    """) == "[true,true]"


def test_AUCUNE_fenetre_ne_se_ferme_pour_un_dossier_de_taille_reelle():
    """« Elles doivent toutes s'empiler » (owner). Le plafond de 80 en fermait
    les deux tiers en cours de route : c'était un arbitrage de perf pris sans
    lui — chaque fenêtre reste un nœud vivant avec son image, sur la machine qui
    ENCODE le live.

    Il reste un filet, mais placé au-dessus de ce que le dossier peut produire :
    134 memes ouvrent 224 fenêtres, et il en faudrait plus de 240 dans le
    dossier pour qu'une seule se referme.
    """
    assert _node("""
      const pourStock = (n) => Math.ceil(n / (1 - V.PART_ALERTES));
      console.log(JSON.stringify([
        V.PLAFOND_VIVANTES > pourStock(134),
        V.PLAFOND_VIVANTES > pourStock(240),
      ]));
    """) == "[true,true]"


def test_une_duree_absurde_ne_fait_pas_boucler_a_l_infini():
    """Filet : `rythme()` n'est plus borné par un compte de fenêtres, seulement
    par le temps. Une durée délirante ne doit pas figer la page du live."""
    assert _node("""
      const t = V.rythme(100000);
      console.log(JSON.stringify(t.length <= V.GARDE_FOU));
    """) == "true"


def test_une_duree_minuscule_ne_leve_pas():
    """Le ▶ du panneau, un réglage tordu : rien à afficher n'est pas une
    erreur de programmation."""
    assert _node("""
      const cas = [V.rythme(0), V.rythme(-5), V.rythme(null)];
      console.log(JSON.stringify(cas.map(t => Array.isArray(t))));
    """) == "[true,true,true]"


# ── 2. Ce qu'il y a dans les fenêtres ───────────────────────────────────────

def test_les_DEUX_gabarits_se_melangent():
    """L'owner a choisi « les deux mêlés » : ni un mur d'alertes, ni un mur de
    memes."""
    assert _node("""
      const stock = [];
      for (let i = 0; i < 60; i++) stock.push({nom: "m" + i, genre: "image"});
      const f = V.fenetres(V.rythme(23), stock);
      const alertes = f.filter(x => x.genre === "alerte").length;
      const memes = f.filter(x => x.genre === "meme").length;
      console.log(JSON.stringify([alertes > 0, memes > 0, alertes + memes === f.length]));
    """) == "[true,true,true]"


def test_un_meme_ne_repasse_pas_tant_que_le_stock_n_est_pas_epuise():
    """Même règle que l'avalanche : un stock se parcourt. Voir deux fois le même
    meme pendant que d'autres dorment, ça se remarque tout de suite."""
    assert _node("""
      const stock = [];
      for (let i = 0; i < 134; i++) stock.push({nom: "m" + i, genre: "image"});
      const f = V.fenetres(V.rythme(23), stock);
      const noms = f.filter(x => x.genre === "meme").map(x => x.media.nom);
      console.log(JSON.stringify([noms.length > 5, new Set(noms).size === noms.length]));
    """) == "[true,true]"


def test_sans_AUCUN_meme_il_reste_les_alertes():
    """Contrairement à l'avalanche, ce spectacle ne dépend pas du dossier : les
    alertes se suffisent. Un dossier vide ne doit donc rien casser — et le
    narrateur n'a aucune raison de refuser."""
    assert _node("""
      const f = V.fenetres(V.rythme(15), []);
      console.log(JSON.stringify([f.length > 0,
                                  f.every(x => x.genre === "alerte")]));
    """) == "[true,true]"


def test_chaque_alerte_porte_un_titre_ET_un_message():
    """Une fenêtre sans texte est une boîte grise : le gag tient au libellé."""
    assert _node("""
      const f = V.fenetres(V.rythme(23), []);
      const ok = f.every(x => x.titre && x.message
                              && x.titre.length > 0 && x.message.length > 0);
      console.log(JSON.stringify(ok));
    """) == "true"


def test_les_alertes_ne_se_repetent_pas_a_la_suite():
    """Deux fois le même texte l'un sous l'autre casse l'illusion du spam."""
    assert _node("""
      const f = V.fenetres(V.rythme(40), []);
      let colles = 0;
      for (let i = 1; i < f.length; i++) {
        if (f[i].message === f[i - 1].message) colles++;
      }
      console.log(JSON.stringify(colles === 0));
    """) == "true"


def test_le_repertoire_de_blagues_est_LARGE():
    """« Ajoute des phrases drôles random » (owner). Sur un spam de deux cents
    fenêtres, une douzaine de textes se répète seize fois : on lit deux fois la
    même et le gag meurt."""
    assert _node("""
      console.log(JSON.stringify(V.NB_ALERTES >= 28));
    """) == "true"


def test_sur_un_LONG_spam_les_textes_ne_tournent_pas_en_rond():
    """La variété se mesure sur ce qui est réellement affiché, pas sur la taille
    du répertoire : un tirage qui repioche mal ne vaut pas mieux qu'une liste
    courte."""
    assert _node("""
      const f = V.fenetres(V.rythme(V.dureePour(200)), []);
      const distincts = new Set(f.map(x => x.message)).size;
      console.log(JSON.stringify([f.length > 100, distincts >= 25]));
    """) == "[true,true]"


# ── 3. L'écran bleu ─────────────────────────────────────────────────────────

def test_l_ecran_bleu_dit_quelque_chose_de_DROLE_et_qui_change():
    """« Même sur le BSOD mets un truc drôle » (owner). Un message figé, revu
    au troisième achat, ne fait plus rire personne : il se tire au sort comme le
    reste."""
    assert _node("""
      const vus = new Set();
      let complet = true;
      for (let i = 0; i < 40; i++) {
        const b = V.bsod();
        if (!b.titre || !b.message || !b.code) complet = false;
        vus.add(b.message);
      }
      console.log(JSON.stringify([complet, vus.size >= 4]));
    """) == "[true,true]"


def test_l_ecran_bleu_porte_un_CODE_d_erreur_a_la_windows():
    """C'est le détail qui fait reconnaître l'écran : sans code en majuscules,
    on lit un message d'erreur générique, pas un BSOD."""
    assert _node("""
      const ok = [];
      for (let i = 0; i < 20; i++) {
        const c = V.bsod().code;
        ok.push(/^[A-Z0-9_]{6,}$/.test(c));
      }
      console.log(JSON.stringify(ok.every(Boolean)));
    """) == "true"


# ── 4. Où elles s'ouvrent ───────────────────────────────────────────────────

def test_les_fenetres_couvrent_TOUT_l_ecran_et_pas_seulement_le_milieu():
    """« Elles se stackent beaucoup vers le centre on dirait » (owner) — et
    c'est géométrique, pas une impression : un coin tiré uniformément dans
    `[0, cadre - taille]` met le CENTRE de la fenêtre dans un rectangle rétréci
    de sa demi-taille. Une popup de 370 px de haut sur un écran de 1080 ne peut
    alors jamais avoir son centre au-dessus de 185 px ni en dessous de 895.

    Le semeur tire donc dans une GRILLE de cellules parcourues en ordre mêlé :
    chaque zone reçoit son tour avant qu'aucune n'en reçoive deux.
    """
    assert _node("""
      const semeur = V.semeur(1920, 1080);
      const quadrants = [0, 0, 0, 0];
      for (let i = 0; i < 240; i++) {
        const l = 300 + Math.floor(Math.random() * 160);
        const h = 210;
        const p = semeur.place(l, h);
        const cx = p.x + l / 2, cy = p.y + h / 2;
        quadrants[(cy < 540 ? 0 : 2) + (cx < 960 ? 0 : 1)] += 1;
      }
      // Chaque quart de l'écran reçoit sa part : l'idéal est 25 %, on tolère
      // large — c'est l'entassement au milieu qu'on chasse, pas l'irrégularité.
      console.log(JSON.stringify(quadrants.every(n => n >= 240 * 0.17)));
    """) == "true"


def test_le_semeur_garde_TOUTES_les_fenetres_dans_le_cadre():
    """La répartition ne doit pas rouvrir le défaut qu'on vient de fermer : une
    popup à moitié hors champ ressemble à un bug de rendu."""
    assert _node("""
      const semeur = V.semeur(1920, 1080);
      const ok = [];
      for (let i = 0; i < 300; i++) {
        const l = 220 + Math.floor(Math.random() * 240);
        const h = 150 + Math.floor(Math.random() * 220);
        const p = semeur.place(l, h);
        ok.push(p.x >= 0 && p.y >= 0 && p.x + l <= 1920 && p.y + h <= 1080);
      }
      console.log(JSON.stringify(ok.every(Boolean)));
    """) == "true"


def test_deux_fenetres_de_SUITE_ne_se_posent_pas_au_meme_endroit():
    """Le cœur de l'effet « ça se répand » : sans ordre imposé, un tirage
    indépendant colle régulièrement deux popups l'une sur l'autre, et l'écran se
    remplit par paquets."""
    assert _node("""
      const semeur = V.semeur(1920, 1080);
      let colles = 0;
      let prec = null;
      for (let i = 0; i < 120; i++) {
        const p = semeur.place(320, 210);
        if (prec && Math.abs(p.x - prec.x) < 60 && Math.abs(p.y - prec.y) < 60) colles++;
        prec = p;
      }
      console.log(JSON.stringify(colles <= 6));
    """) == "true"


def test_une_GRANDE_fenetre_peut_aussi_se_poser_tout_en_BAS():
    """Le biais qui restait après la première correction : en découpant l'écran
    puis en rabattant ce qui dépasse, les fenêtres hautes remontaient toutes —
    mesuré, 16 % des centres dans le tiers haut contre 6 % dans le tiers bas.

    La grille découpe donc l'espace des positions ADMISSIBLES : le bas du cadre
    reste atteignable pour une popup de 370 px de haut comme pour une petite.
    """
    assert _node("""
      const semeur = V.semeur(1920, 1080);
      let basse = 0, haute = 0;
      for (let i = 0; i < 200; i++) {
        const p = semeur.place(320, 370);
        if (p.y > (1080 - 370) * 0.75) basse++;
        if (p.y < (1080 - 370) * 0.25) haute++;
      }
      // Les deux extrémités sont servies, à peu près autant l'une que l'autre.
      console.log(JSON.stringify([basse > 30, haute > 30]));
    """) == "[true,true]"


def test_une_fenetre_plus_GRANDE_que_le_cadre_est_ramenee_au_coin():
    """Cas limite d'une source OBS minuscule : mieux vaut une fenêtre qui
    déborde depuis le coin qu'une position négative, quelle que soit la cellule
    que le semeur lui avait réservée."""
    assert _node("""
      const semeur = V.semeur(1920, 1080);
      const p = semeur.place(2000, 1200);
      console.log(JSON.stringify([p.x, p.y]));
    """) == "[0,0]"
