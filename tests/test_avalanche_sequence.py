"""Le stock se PARCOURT — il ne se tire pas au sort.

Le tirage d'origine était `medias[Math.random() * medias.length]` à chaque
lâcher : avec remise. Sur 134 médias et 120 lâchers, environ 40 % du dossier ne
sortait jamais pendant que d'autres repassaient trois fois — exactement ce que
l'owner a vu (« y a pas tous les memes »).

La logique de séquencement vit dans `overlay_avalanche.js`, hors du DOM, pour
être exécutée ici pour de vrai plutôt que relue au grep : un test qui cherche un
bout de code fige l'écriture du jour et laisse le défaut suivant passer (piège
déjà mordu cinq fois dans ce dépôt).
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
require(%s);
const A = window.WallyAvalanche;
""" % json.dumps(str(_STATIC / "overlay_avalanche.js"))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ── 1. Tous les memes, une fois chacun ──────────────────────────────────────

def test_l_ordre_contient_TOUT_le_stock_exactement_une_fois():
    """Le cœur du retour de l'owner. Une permutation, ni plus ni moins."""
    assert _node("""
      const stock = [];
      for (let i = 0; i < 134; i++) stock.push({nom: "m" + i});
      const ordre = A.ordre(stock);
      const noms = ordre.map(m => m.nom).sort();
      const attendus = stock.map(m => m.nom).sort();
      console.log(JSON.stringify([
        ordre.length,
        JSON.stringify(noms) === JSON.stringify(attendus),
      ]));
    """) == "[134,true]"


def test_l_ordre_est_bien_MELANGE():
    """Sinon l'avalanche déroule le dossier par ordre alphabétique, et deux
    achats de suite donnent deux fois le même spectacle."""
    assert _node("""
      const stock = [];
      for (let i = 0; i < 134; i++) stock.push({nom: "m" + i});
      const a = A.ordre(stock).map(m => m.nom).join();
      const b = A.ordre(stock).map(m => m.nom).join();
      const range = stock.map(m => m.nom).join();
      console.log(JSON.stringify([a !== range, a !== b]));
    """) == "[true,true]"


def test_l_ordre_ne_TOUCHE_pas_au_stock_d_origine():
    """La liste est partagée avec le rotateur : la mélanger en place mêlerait
    aussi son défilé, et un `pop()` la viderait pour de bon."""
    assert _node("""
      const stock = [{nom: "a"}, {nom: "b"}, {nom: "c"}];
      A.ordre(stock);
      console.log(JSON.stringify(stock.map(m => m.nom)));
    """) == '["a","b","c"]'


def test_un_stock_vide_ou_absent_ne_leve_pas():
    """Le rotateur peut n'avoir pas encore répondu. Rien à faire tomber n'est
    pas une erreur de programmation."""
    assert _node("""
      console.log(JSON.stringify([A.ordre([]).length, A.ordre(null).length,
                                  A.ordre(undefined).length]));
    """) == "[0,0,0]"


# ── 2. La cadence fait tenir le stock dans la fenêtre ───────────────────────

def test_tout_le_stock_est_lache_avant_la_fin_de_la_fenetre():
    """Le serveur dimensionne la fenêtre sur SON décompte, le client répartit le
    SIEN dedans. Les deux viennent du même dossier, mais un meme ajouté entre
    les deux lectures ne doit pas faire déborder — sinon la carte se retire sur
    des memes encore en attente."""
    assert _node("""
      const cas = [[134, 39], [200, 39], [10, 8], [1, 6]];
      const ok = cas.map(([n, duree]) => {
        const pas = A.cadence(n, duree);
        return (n * pas) / 1000 <= duree - A.CHUTE_S + 0.001;
      });
      console.log(JSON.stringify(ok));
    """) == "[true,true,true,true]"


def test_une_fenetre_trop_COURTE_ne_declenche_pas_de_rafale():
    """Le ▶ du panneau n'essaie que cinq secondes — moins que ce qu'il faut au
    dossier. Sans plafond de débit, les 134 memes partaient en une seconde :
    52 flocons vivants d'un coup, mesurés dans le navigateur. « Pas tous les
    lâcher en même temps » (owner) vaut aussi pour ce chemin-là.
    """
    assert _node("""
      const parSeconde = 1000 / A.cadence(134, 5);
      console.log(JSON.stringify(parSeconde <= 6));
    """) == "true"


def test_la_cadence_ne_tombe_jamais_a_zero():
    """`setInterval(0)` sature la boucle d'événements de la machine qui ENCODE
    le live. Un plancher, même sur une fenêtre absurde."""
    assert _node("""
      const cas = [A.cadence(500, 1), A.cadence(1, 0), A.cadence(0, 30),
                   A.cadence(-3, 30), A.cadence(10, -5)];
      console.log(JSON.stringify(cas.map(ms => ms > 0 && isFinite(ms))));
    """) == "[true,true,true,true,true]"


def test_un_petit_stock_ne_part_pas_en_rafale_d_une_seconde():
    """Trois memes sur une fenêtre de 8 s se répartissent : les lâcher tous dans
    la première frame ferait une avalanche d'une demi-seconde."""
    assert _node("""
      const pas = A.cadence(3, 8);
      console.log(JSON.stringify(pas >= 500));
    """) == "true"


def test_le_stock_reel_tombe_a_environ_TROIS_par_seconde():
    """La demande de l'owner, sur le dossier tel qu'il est (134 memes) et la
    fenêtre que le serveur en déduit : une pluie continue, pas un lâcher en
    bloc. Marge large — c'est l'ordre de grandeur qui compte, pas la décimale.
    """
    assert _node("""
      const duree = Math.ceil(134 / 3) + A.CHUTE_S;   // ce que calcule le serveur
      const parSeconde = 1000 / A.cadence(134, duree);
      console.log(JSON.stringify(parSeconde >= 2.5 && parSeconde <= 3.5));
    """) == "true"
