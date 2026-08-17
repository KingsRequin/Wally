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


def test_le_nombre_de_fenetres_est_PLAFONNE():
    """Elles ne disparaissent jamais : chacune reste un nœud vivant, avec son
    image, sur la machine qui ENCODE le live. Une durée absurde ne doit pas en
    empiler mille."""
    assert _node("""
      const cas = [V.rythme(23).length, V.rythme(120).length, V.rythme(600).length];
      console.log(JSON.stringify(cas.map(n => n <= V.PLAFOND)));
    """) == "[true,true,true]"


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


# ── 3. Où elles s'ouvrent ───────────────────────────────────────────────────

def test_une_fenetre_s_ouvre_ENTIEREMENT_dans_le_cadre():
    """Une popup à moitié hors champ ressemble à un bug de rendu, pas à un gag.
    Le tirage tient compte de sa taille — le piège déjà corrigé sur l'avalanche,
    où un meme large sortait par la droite.
    """
    assert _node("""
      const ok = [];
      for (let i = 0; i < 200; i++) {
        const p = V.place(320, 180, 1920, 1080);
        ok.push(p.x >= 0 && p.y >= 0 && p.x + 320 <= 1920 && p.y + 180 <= 1080);
      }
      console.log(JSON.stringify(ok.every(Boolean)));
    """) == "true"


def test_une_fenetre_plus_GRANDE_que_le_cadre_est_ramenee_au_coin():
    """Cas limite d'une source OBS minuscule : mieux vaut une fenêtre qui
    déborde depuis le coin qu'une position négative aléatoire."""
    assert _node("""
      const p = V.place(2000, 1200, 1920, 1080);
      console.log(JSON.stringify([p.x, p.y]));
    """) == "[0,0]"
