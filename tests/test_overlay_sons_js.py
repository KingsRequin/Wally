"""Les sons de l'overlay, exécutés — pas relus au grep.

Demande de l'owner (2026-08-19) : « le son de Windows à chaque fenêtre, et au
blue screen aussi ». Le module vit hors du DOM et crée son contexte audio au
dernier moment, précisément pour être EXÉCUTÉ ici sous node : un test qui
cherche un bout de code fige l'écriture du jour et laisse passer le défaut
suivant.

Le faux contexte audio ci-dessous n'imite pas Web Audio pour le plaisir : il
enregistre ce qui DÉMARRE et ce qui S'ARRÊTE, seule façon de vérifier qu'un
écran bleu coupe bien le chaos avant de poser son impact.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

# `window = global` puis un faux Web Audio et un faux réseau, posés AVANT le
# require : le module lit `window.AudioContext` au dernier moment, donc c'est
# celui-là qu'il prendra.
_PRELUDE = """
global.window = global;
const demarrees = [];
const arretees = [];
let decodes = 0;
global.AudioContext = class {
  constructor() { this.state = "running"; this.destination = {nom: "sortie"}; }
  createGain() { return {gain: {value: 1}, connect() {}}; }
  createBufferSource() {
    const s = {buffer: null, playbackRate: {value: 1}, onended: null,
               connect(cible) { s.branche = cible; },
               start() { demarrees.push(s); },
               stop() { arretees.push(s); if (s.onended) s.onended(); }};
    return s;
  }
  decodeAudioData(brut) { decodes++; return Promise.resolve({taille: brut.byteLength}); }
  resume() { this.state = "running"; return Promise.resolve(); }
};
let inventaireServeur = {popup: ["ding.mp3", "erreur.wav"], bsod: ["impact.mp3"],
                         raid: ["fanfare.mp3"]};
let appelsListe = 0;
global.fetch = async (url) => {
  if (url === "/api/public/sons") {
    appelsListe++;
    return {ok: true, json: async () => ({sons: inventaireServeur})};
  }
  return {ok: true, arrayBuffer: async () => new ArrayBuffer(8)};
};
require(%s);
const S = window.WallySons;
const sortie = (v) => console.log(JSON.stringify(v));
""" % json.dumps(str(_STATIC / "overlay_sons.js"))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def _node(script: str):
    r = subprocess.run(["node", "-e", _PRELUDE + "(async () => {" + script + "})()"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── le chargement ───────────────────────────────────────────────────────────

def test_les_sons_du_dossier_sont_decodes_une_fois_chacun():
    r = _node("""
      await S.charger();
      sortie({inv: S.inventaire(), decodes});
    """)
    assert r["inv"] == {"popup": ["ding.mp3", "erreur.wav"], "bsod": ["impact.mp3"],
                        "raid": ["fanfare.mp3"], "commande": []}
    assert r["decodes"] == 4


def test_recharger_ne_retelecharge_pas_ce_qui_est_deja_decode():
    """`charger()` est rappelée à CHAQUE déclenchement du spam pour voir les
    sons déposés pendant le live. Si elle redécodait tout, chaque achat de la
    récompense paierait un aller-retour réseau par fichier."""
    r = _node("""
      await S.charger(); await S.charger(); await S.charger();
      sortie({decodes, inv: S.inventaire()});
    """)
    assert r["decodes"] == 4
    assert r["inv"]["popup"] == ["ding.mp3", "erreur.wav"]


def test_deux_chargements_simultanes_ne_doublent_pas_le_tirage():
    """Le boot de la page et un déclenchement peuvent se croiser. Un fichier
    décodé deux fois sortirait deux fois plus souvent du tirage au sort."""
    r = _node("""
      await Promise.all([S.charger(), S.charger()]);
      sortie(S.inventaire());
    """)
    assert r["popup"] == ["ding.mp3", "erreur.wav"]
    assert r["bsod"] == ["impact.mp3"]


def test_un_son_retire_du_dossier_cesse_de_sonner():
    r = _node("""
      await S.charger();
      inventaireServeur = {popup: ["ding.mp3"], bsod: [], raid: [], commande: []};
      await S.charger();
      sortie(S.inventaire());
    """)
    assert r == {"popup": ["ding.mp3"], "bsod": [], "raid": [], "commande": []}


def test_un_dossier_injoignable_ne_casse_rien():
    """Le réseau ne décide pas s'il y a un spectacle : le spam doit partir même
    si la liste des sons ne répond pas."""
    r = _node("""
      global.fetch = async () => { throw new Error("réseau coupé"); };
      await S.charger();
      S.popup();
      sortie({inv: S.inventaire(), demarrees: demarrees.length});
    """)
    assert r["inv"] == {"popup": [], "bsod": [], "raid": [], "commande": []}
    assert r["demarrees"] == 0


# ── la lecture ──────────────────────────────────────────────────────────────

def test_chaque_fenetre_fait_sonner_un_ding():
    r = _node("""
      await S.charger();
      for (let i = 0; i < 50; i++) S.popup();
      sortie({demarrees: demarrees.length, branchees: demarrees.every(s => s.branche)});
    """)
    assert r["demarrees"] == 50
    assert r["branchees"] is True


def test_le_chaos_n_a_AUCUN_plafond():
    """Choix de l'owner, contre un plafond de voix : « chaos total ». Le tampon
    est décodé une fois et partagé, c'est ce qui rend la chose tenable sur la
    machine qui encode le live."""
    r = _node("""
      await S.charger();
      for (let i = 0; i < 400; i++) S.popup();
      sortie({demarrees: demarrees.length, vivantes: S.nbVivantes(), decodes});
    """)
    assert r["demarrees"] == 400
    assert r["vivantes"] == 400
    assert r["decodes"] == 4


def test_les_dings_ne_sonnent_pas_tous_a_la_meme_hauteur():
    """Trois cents fois le même échantillon à la même hauteur ne s'entend pas
    comme trois cents fenêtres, mais comme un seul son qui bave."""
    r = _node("""
      await S.charger();
      for (let i = 0; i < 60; i++) S.popup();
      sortie([...new Set(demarrees.map(s => s.playbackRate.value))].length);
    """)
    assert r > 1


def test_un_dossier_de_popups_vide_ne_fait_pas_sonner_l_ecran_bleu():
    """Les deux tiroirs sont séparés : un impact grave lâché au milieu du spam
    parce que le dossier des dings est vide serait pire que le silence."""
    r = _node("""
      inventaireServeur = {popup: [], bsod: ["impact.mp3"], raid: []};
      await S.charger();
      S.popup();
      sortie(demarrees.length);
    """)
    assert r == 0


# ── l'écran bleu ────────────────────────────────────────────────────────────

def test_l_ecran_bleu_coupe_TOUT_avant_de_poser_son_impact():
    r = _node("""
      await S.charger();
      for (let i = 0; i < 20; i++) S.popup();
      S.bsod();
      const juste_apres = {arretees: arretees.length, vivantes: S.nbVivantes(),
                           demarrees: demarrees.length};
      await new Promise(r => setTimeout(r, S.SILENCE_MS + 60));
      sortie({juste_apres, apres: demarrees.length});
    """)
    # Tout ce qui sonnait est arrêté, et RIEN ne démarre dans l'intervalle :
    # c'est le silence qui fait la fin.
    assert r["juste_apres"]["arretees"] == 20
    assert r["juste_apres"]["vivantes"] == 0
    assert r["juste_apres"]["demarrees"] == 20
    # Puis l'impact, une seule fois.
    assert r["apres"] == 21


def test_l_impact_final_garde_sa_hauteur():
    """Le ding varie pour ne pas baver ; l'impact, lui, doit sortir exactement
    tel qu'il a été choisi."""
    r = _node("""
      await S.charger();
      S.bsod();
      await new Promise(r => setTimeout(r, S.SILENCE_MS + 60));
      sortie(demarrees.map(s => s.playbackRate.value));
    """)
    assert r == [1]


def test_sans_contexte_audio_rien_n_explose():
    """L'aperçu du dashboard, un navigateur trop vieux : le spectacle continue,
    muet, plutôt que de s'arrêter sur une exception."""
    r = subprocess.run(
        ["node", "-e", """
        global.window = global;
        require(%s);
        window.WallySons.popup();
        window.WallySons.bsod();
        window.WallySons.raid();
        window.WallySons.couperTout();
        console.log(JSON.stringify(window.WallySons.inventaire()));
        """ % json.dumps(str(_STATIC / "overlay_sons.js"))],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip()) == {"popup": [], "bsod": [], "raid": [],
                                            "commande": []}


def test_un_raid_sonne_une_fois_et_garde_sa_hauteur():
    """Ce n'est pas un ding parmi trois cents : c'est l'événement. Le varier en
    hauteur, comme les popups, le ferait sonner faux d'un raid à l'autre."""
    r = _node("""
      await S.charger();
      S.raid();
      sortie({demarrees: demarrees.length,
              hauteurs: demarrees.map(s => s.playbackRate.value)});
    """)
    assert r["demarrees"] == 1
    assert r["hauteurs"] == [1]


def test_un_dossier_de_raid_vide_reste_muet_sans_broncher():
    """Le dossier est livré VIDE (choix de l'owner) : la fête doit avoir lieu
    quand même, et les deux autres tiroirs ne doivent pas la dépanner."""
    r = _node("""
      inventaireServeur = {popup: ["ding.mp3"], bsod: ["impact.mp3"], raid: []};
      await S.charger();
      S.raid();
      sortie(demarrees.length);
    """)
    assert r == 0
