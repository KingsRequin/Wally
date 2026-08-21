"""La fête d'un raid, EXÉCUTÉE — pas relue au grep.

Demande de l'owner (2026-08-21) : « on a juste des confettis pour le moment, je
veux pousser le truc avec plus de confettis, des lights, des effets ».

Le module manipule le DOM, d'où le faux document ci-dessous. Il n'imite pas un
navigateur pour le plaisir : il enregistre ce qui est AJOUTÉ et ce qui est
RETIRÉ, seule façon de vérifier qu'une couche plein écran de 4,2 s disparaît
bien — et qu'un second raid n'en laisse pas deux derrière lui.

L'horloge est fausse elle aussi : attendre 4,2 s réelles par test rendrait cette
suite plus lente que tout le reste du dossier.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;

// ── Faux DOM : le strict nécessaire, et rien qui ressemble à un navigateur.
class FauxNoeud {
  constructor(tag) {
    this.tag = tag; this.id = ""; this.className = ""; this.attrs = {};
    this.children = []; this.parentNode = null; this.offsetWidth = 0;
    const s = new Set();
    this.classes = s;
    this.classList = {
      add: (c) => s.add(c), remove: (c) => s.delete(c), contains: (c) => s.has(c),
    };
  }
  appendChild(n) { n.parentNode = this; this.children.push(n); return n; }
  removeChild(n) { this.children = this.children.filter((x) => x !== n); n.parentNode = null; }
  setAttribute(k, v) { this.attrs[k] = v; }
}
const stage = new FauxNoeud("div");
stage.id = "stage";
global.document = {
  createElement: (t) => new FauxNoeud(t),
  getElementById: (id) => (id === "stage" ? stage : null),
};

// ── Fausse horloge : les minuteurs ne partent que quand on avance.
let maintenant = 0;
let seq = 0;
const taches = [];
global.setTimeout = (fn, ms) => {
  const id = ++seq;
  taches.push({ id, at: maintenant + (Number(ms) || 0), fn });
  return id;
};
global.clearTimeout = (id) => {
  const i = taches.findIndex((t) => t.id === id);
  if (i >= 0) taches.splice(i, 1);
};
const avancer = (ms) => {
  const fin = maintenant + ms;
  for (;;) {
    taches.sort((a, b) => a.at - b.at);
    const t = taches[0];
    if (!t || t.at > fin) break;
    taches.shift();
    maintenant = t.at;
    t.fn();
  }
  maintenant = fin;
};

const tirs = [];
global.confetti = (p) => { tirs.push(p); };
let sonsJoues = 0;
let chargements = 0;
global.WallySons = { charger() { chargements++; }, raid() { sonsJoues++; } };

require(%s);
const R = window.WallyRaid;
const couches = () => stage.children.filter((n) => n.id === "raid-fx");
const sortie = (v) => console.log(JSON.stringify(v));
""" % json.dumps(str(_STATIC / "overlay_raid.js"))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def _node(script: str):
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── le plan des salves ──────────────────────────────────────────────────────

def test_aucune_salve_ne_part_du_centre():
    """Une salve tirée du centre retombe SUR la carte et masque le nom — qui
    est tout l'objet du widget. Les canons tirent des bords, ou du plafond."""
    r = _node("sortie(R.SALVES.map((s) => [s.origin.x, s.origin.y]));")
    for x, y in r:
        # Le plafond fait exception : ce qui tombe de -0,1 traverse l'écran
        # au lieu de s'accumuler devant la carte.
        assert not (0.35 < x < 0.65) or y < 0, (x, y)


def test_toutes_les_salves_partent_avant_la_fin_de_la_couche():
    """Une salve lâchée après le nettoyage ferait pleuvoir des confettis sur un
    écran redevenu calme, sans lumière ni carte pour les expliquer."""
    r = _node("sortie({retards: R.SALVES.map((s) => s.t || 0), duree: R.DUREE_MS});")
    assert max(r["retards"]) < r["duree"]


def test_la_fete_se_joue_en_plusieurs_vagues():
    """Tout tirer d'un coup, c'est ce qu'on avait : une bouffée puis plus rien
    pendant huit secondes, alors que la carte est encore là."""
    r = _node("sortie([...new Set(R.SALVES.map((s) => s.t || 0))].sort((a, b) => a - b));")
    assert len(r) >= 3


def test_les_serpentins_flottent_plus_longtemps_que_les_confettis():
    """Ce sont des rubans, pas des paillettes : gravité basse et vol long. Sans
    cet écart ils retombent avec le reste et ne se distinguent de rien."""
    r = _node("""
      const rubans = R.SALVES.filter((s) => (s.gravity || 1) < 0.6);
      const confettis = R.SALVES.filter((s) => (s.gravity || 1) >= 0.6);
      sortie({
        nbRubans: rubans.length,
        volRuban: Math.min(...rubans.map((s) => s.ticks)),
        volConfetti: Math.max(...confettis.map((s) => s.ticks)),
        taille: Math.min(...rubans.map((s) => s.scalar)),
      });
    """)
    assert r["nbRubans"] >= 2
    assert r["volRuban"] > r["volConfetti"]
    assert r["taille"] > 1.5


def test_la_fete_reste_tenable_pour_la_machine_qui_encode():
    """L'overlay tourne à côté du jeu et de l'encodage. « Toujours à fond » est
    un choix de mise en scène, pas un blanc-seing sur le nombre de particules."""
    r = _node("sortie(R.SALVES.reduce((n, s) => n + s.particleCount, 0));")
    assert r <= 750


# ── la couche d'effets ──────────────────────────────────────────────────────

def test_la_couche_est_posee_dans_le_stage_avec_ses_lumieres():
    r = _node("""
      R.celebrer(stage);
      const fx = couches()[0];
      sortie({n: couches().length, enfants: fx.children.map((c) => c.className),
              masquee: fx.attrs["aria-hidden"]});
    """)
    assert r["n"] == 1
    assert r["enfants"] == ["raid-flash", "raid-faisceaux", "raid-vignette"]
    assert r["masquee"] == "true"


def test_la_couche_disparait_du_DOM_a_la_fin():
    """Une couche plein cadre laissée en place coûte à CHAQUE frame du live,
    même invisible. Elle ne survit pas à sa propre durée."""
    r = _node("""
      R.celebrer(stage);
      avancer(R.DUREE_MS - 1);
      const pendant = couches().length;
      avancer(2);
      sortie({pendant, apres: couches().length});
    """)
    assert r["pendant"] == 1
    assert r["apres"] == 0


def test_deux_raids_coup_sur_coup_ne_laissent_qu_une_couche():
    """Deux raids à quelques secondes d'écart arrivent pour de vrai. La seconde
    fête repart propre, et le nettoyage de la première ne doit pas emporter la
    couche de la seconde."""
    r = _node("""
      R.celebrer(stage);
      avancer(1200);
      R.celebrer(stage);
      const juste_apres = couches().length;
      // La fin du PREMIER raid tombe ici : elle ne doit rien retirer.
      avancer(R.DUREE_MS - 1200 + 10);
      const encore_la = couches().length;
      avancer(R.DUREE_MS);
      sortie({juste_apres, encore_la, fin: couches().length});
    """)
    assert r["juste_apres"] == 1
    assert r["encore_la"] == 1
    assert r["fin"] == 0


def test_la_secousse_est_posee_puis_retiree():
    r = _node("""
      R.celebrer(stage);
      const pendant = stage.classList.contains("raid-secousse");
      avancer(R.SECOUSSE_MS + 1);
      sortie({pendant, apres: stage.classList.contains("raid-secousse")});
    """)
    assert r["pendant"] is True
    assert r["apres"] is False


def test_toutes_les_salves_finissent_par_partir():
    r = _node("""
      R.celebrer(stage);
      const immediat = tirs.length;
      avancer(R.DUREE_MS);
      sortie({immediat, total: tirs.length, attendu: R.SALVES.length});
    """)
    # La première vague est SYNCHRONE : un flash qui précède ses confettis se
    # lit comme deux événements, pas comme un.
    assert r["immediat"] == 4
    assert r["total"] == r["attendu"]


def test_un_raid_coupe_ne_crache_pas_ses_confettis_apres_coup():
    r = _node("""
      R.celebrer(stage);
      const immediat = tirs.length;
      R.arreter();
      avancer(5000);
      sortie({immediat, apres: tirs.length, couches: couches().length});
    """)
    assert r["apres"] == r["immediat"]
    assert r["couches"] == 0


def test_la_palette_vient_de_l_appelant():
    """`overlay.js` détient les tokens de la page. Les recopier ici en ferait
    une seconde source de vérité, qui divergerait au premier ajustement."""
    r = _node("""
      R.celebrer(stage, ["#111111", "#222222"]);
      avancer(R.DUREE_MS);
      sortie([...new Set(tirs.map((t) => JSON.stringify(t.colors)))]);
    """)
    assert r == [json.dumps(["#111111", "#222222"]).replace(" ", "")]


def test_sans_palette_canvas_confetti_garde_les_siennes():
    r = _node("""
      R.celebrer(stage);
      sortie(tirs.map((t) => "colors" in t));
    """)
    assert r == [False] * 4


def test_sans_confettis_la_fete_a_quand_meme_lieu():
    """Un overlay sans confettis reste un overlay. Une exception ici
    emporterait la lumière, la secousse et le son avec elle."""
    r = _node("""
      global.confetti = undefined;
      const ok = R.celebrer(stage);
      sortie({ok, couches: couches().length,
              secousse: stage.classList.contains("raid-secousse")});
    """)
    assert r["ok"] is True
    assert r["couches"] == 1
    assert r["secousse"] is True


def test_le_son_part_une_fois_par_raid():
    r = _node("""
      R.celebrer(stage);
      avancer(R.DUREE_MS);
      R.celebrer(stage);
      avancer(R.DUREE_MS);
      sortie({sons: sonsJoues, chargements});
    """)
    assert r["sons"] == 2
    # Relu à chaque raid : l'owner dépose ses fichiers pendant le live.
    assert r["chargements"] == 2


def test_sans_module_de_sons_rien_n_explose():
    """Le dossier des sons reste vide pour l'instant (choix de l'owner) — et la
    page doit tourner même si le module n'a pas été servi."""
    r = _node("""
      global.WallySons = undefined;
      sortie({ok: R.celebrer(stage), couches: couches().length});
    """)
    assert r["ok"] is True
    assert r["couches"] == 1


def test_sans_hote_la_fete_ne_part_pas():
    """Une page sans `#stage` n'est pas l'overlay : mieux vaut ne rien faire que
    de coller une couche plein écran sur le dashboard."""
    r = _node("""
      global.document.getElementById = () => null;
      sortie({ok: R.celebrer(), couches: couches().length});
    """)
    assert r["ok"] is False
    assert r["couches"] == 0
