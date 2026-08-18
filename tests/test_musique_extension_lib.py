"""Le titre YouTube n'est pas un titre de chanson.

Relevé sur la vraie page avant d'écrire une ligne : `navigator.mediaSession`
donne bien l'artiste séparé (« Linkin Park »), mais le titre reste celui de la
VIDÉO — « Numb (Official Music Video) [4K UPGRADE] – Linkin Park ». Annoncé tel
quel dans le chat Twitch et sur l'overlay, c'est illisible.

Ce module ne fait que du texte : il est donc exécuté par ces tests, sous node,
comme `overlay_virus.js`. Le reste de l'extension (lecture du lecteur,
application des ordres) touche le DOM de YouTube et se vérifie dans un
navigateur, pas ici.

Le garde-fou qui compte : **ne jamais rendre une chaîne vide**. Un nettoyage trop
zélé qui mange tout laisserait Wally annoncer « ça joue : » suivi de rien.
"""
import json
import subprocess
from pathlib import Path

import pytest

_EXT = Path(__file__).resolve().parents[1] / "extension-musique"

_PRELUDE = """
global.window = global;
require(%s);
const L = window.WallyMusiqueLib;
""" % json.dumps(str(_EXT / "lib.js"))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def _node(script: str) -> str:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ── le nettoyage du titre ───────────────────────────────────────────────────

def test_le_cas_reel_releve_sur_youtube():
    """Exactement ce que la page a rendu, artiste compris."""
    assert _node("""
      console.log(L.nettoyerTitre(
        "Numb (Official Music Video) [4K UPGRADE] – Linkin Park", "Linkin Park"));
    """) == "Numb"


def test_les_mentions_de_production_sautent():
    assert _node("""
      const cas = [
        ["Song (Official Video)", ""],
        ["Song [Official Audio]", ""],
        ["Song (Lyrics)", ""],
        ["Song (HD)", ""],
        ["Song [4K Remaster]", ""],
        ["Song (Clip Officiel)", ""],
        ["Song (Visualizer)", ""],
      ];
      console.log(JSON.stringify(cas.map(([t, a]) => L.nettoyerTitre(t, a))));
    """) == '["Song","Song","Song","Song","Song","Song","Song"]'


def test_une_parenthese_UTILE_est_gardee():
    """« (feat. X) » ou « (Remix) » font partie du titre : les manger
    donnerait un autre morceau."""
    assert _node("""
      const cas = ["Song (feat. Quelqu'un)", "Song (Remix)", "Song (Live à Bercy)"];
      console.log(JSON.stringify(cas.map(t => L.nettoyerTitre(t, ""))));
    """) == '["Song (feat. Quelqu\'un)","Song (Remix)","Song (Live à Bercy)"]'


def test_l_artiste_en_double_est_retire_des_DEUX_cotes():
    """YouTube l'écrit tantôt devant, tantôt derrière, avec un tiret court ou
    long. Le répéter donne « Linkin Park — Numb par Linkin Park »."""
    assert _node("""
      const cas = [
        ["Linkin Park - Numb", "Linkin Park"],
        ["Numb – Linkin Park", "Linkin Park"],
        ["LINKIN PARK — Numb", "Linkin Park"],
      ];
      console.log(JSON.stringify(cas.map(([t, a]) => L.nettoyerTitre(t, a))));
    """) == '["Numb","Numb","Numb"]'


def test_un_titre_deja_propre_n_est_pas_touche():
    assert _node("""
      console.log(L.nettoyerTitre("Une chanson toute simple", "Un artiste"));
    """) == "Une chanson toute simple"


def test_le_nettoyage_ne_VIDE_jamais_un_titre_qui_existait():
    """Le garde-fou. Un titre qui n'est QUE le nom de l'artiste, ou que des
    mentions de production, ne doit pas s'évaporer : mieux vaut le titre brut
    qu'un blanc annoncé en direct.

    Un titre vide EN ENTRÉE, lui, ressort vide — il n'y a rien à inventer, et
    c'est `etatLecteur` qui refuse alors de parler (test plus bas).
    """
    assert _node("""
      const cas = [
        ["Linkin Park", "Linkin Park"],
        ["(Official Video)", ""],
        ["Song [Official Audio]", "Song"],
      ];
      const r = cas.map(([t, a]) => L.nettoyerTitre(t, a));
      console.log(JSON.stringify(r.map(x => x.trim().length > 0)));
    """) == "[true,true,true]"


def test_un_titre_VIDE_ne_devient_pas_un_faux_titre():
    """L'autre moitié de la règle : on ne remplit pas un trou avec du bruit."""
    assert _node("""
      console.log(JSON.stringify([L.nettoyerTitre("   ", "Artiste"),
                                  L.nettoyerTitre("", "")]));
    """) == '["",""]'


def test_les_entrees_TORDUES_ne_font_pas_lever():
    """Le titre vient d'une page web : `null`, un nombre, un objet."""
    assert _node("""
      const cas = [L.nettoyerTitre(null, null), L.nettoyerTitre(undefined, "x"),
                   L.nettoyerTitre(42, {}), L.nettoyerTitre("", "")];
      console.log(JSON.stringify(cas.map(x => typeof x === "string")));
    """) == "[true,true,true,true]"


def test_le_titre_est_BORNE():
    """Il finit dans le chat Twitch, dont les messages sont plafonnés, et sur
    l'overlay."""
    assert _node("""
      console.log(L.nettoyerTitre("x".repeat(1000), "").length <= 200);
    """) == "true"


# ── ce qu'on annonce ────────────────────────────────────────────────────────

def test_la_phrase_d_annonce_met_l_artiste_devant():
    assert _node("""
      console.log(L.pourAnnonce("Numb", "Linkin Park"));
    """) == "Linkin Park — Numb"


def test_sans_artiste_connu_on_annonce_le_titre_seul():
    """Et surtout pas « — Numb », qui a l'air cassé."""
    assert _node("""
      console.log(JSON.stringify([L.pourAnnonce("Numb", ""),
                                  L.pourAnnonce("Numb", null)]));
    """) == '["Numb","Numb"]'


# ── ce qu'on envoie au bot ──────────────────────────────────────────────────

def test_l_etat_lu_du_lecteur_est_normalise():
    """`playbackState` de mediaSession disait « paused » sur une page dont la
    vidéo tournait : c'est `video.paused` qui fait foi, et c'est mesuré."""
    assert _node("""
      const etat = L.etatLecteur({
        metadata: {title: "Numb (Official Video)", artist: "Linkin Park"},
        videoEnPause: false,
        url: "https://www.youtube.com/watch?v=abc",
      });
      console.log(JSON.stringify([etat.titre, etat.artiste, etat.joue]));
    """) == '["Numb","Linkin Park",true]'


def test_sans_METADATA_on_retombe_sur_ce_qu_on_a():
    """mediaSession n'est remplie qu'une fois la lecture lancée : avant, il
    reste le titre du document, qu'il faut débarrasser de son « - YouTube »."""
    assert _node("""
      const etat = L.etatLecteur({
        metadata: null,
        titreDocument: "Numb (Official Music Video) - YouTube",
        videoEnPause: true,
      });
      console.log(JSON.stringify([etat.titre, etat.joue]));
    """) == '["Numb",false]'


def test_une_page_SANS_lecteur_ne_pretend_rien():
    """La page d'accueil de YouTube, une recherche : il n'y a pas de morceau en
    cours, et inventer un titre serait pire que se taire."""
    assert _node("""
      const etat = L.etatLecteur({metadata: null, titreDocument: "YouTube",
                                  videoEnPause: true, sansVideo: true});
      console.log(JSON.stringify(etat));
    """) == "null"
