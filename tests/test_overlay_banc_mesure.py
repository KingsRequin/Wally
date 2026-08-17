"""Les cadres du panneau sont justes SANS avoir à lancer l'élément.

Le défaut, dans les mots du streamer : « certaines box ne se mettent à jour que
au lancement de l'élément ». Deux mécanismes le produisaient, et il fallait les
deux pour que ça se voie :

  1. Une taille n'était connue que pendant que le widget était À L'ÉCRAN. Au
     chargement du panneau, aucun ne l'est : vingt-sept cadres sur trente-quatre
     portaient donc une valeur de table, et ne devenaient justes qu'au premier ▶.
  2. Pire, la mesure était PERDUE au départ du widget : `mesurerTout()` vidait
     le dictionnaire à chaque passe avant d'y remettre ce qui était visible. Le
     cadre se calait le temps de l'affichage, puis retombait sur l'estimation —
     « perdu après coup », dit l'owner.

Le ▶ ne pouvait pas servir de mesure automatique : il publie sur le bus SSE
(`POST /overlay/preview`), donc mesurer les vingt-sept widgets au chargement les
aurait affichés EN DIRECT devant les viewers si la scène réglée est celle du
live. La mesure se fait donc dans la page d'aperçu elle-même, sans un seul
appel au serveur (`WallyBanc.mesurer`, overlay.js).

Ce fichier vérifie les trois maillons :

  1. `fusionnerMesures` — une taille lue est ACQUISE : elle survit à la
     disparition du widget, et ne se remplace que par une autre mesure.
  2. `mesurerBanc` — le panneau lit le banc de l'aperçu et pose ses tailles,
     sans jamais parler au serveur.
  3. Les échantillons voyagent avec le layout admin : la table de prod
     (`_ECHANTILLONS`) est servie telle quelle, jamais recopiée en JS.

Ces tests échouent sur le code d'avant : `fusionnerMesures` et `mesurerBanc`
n'existaient pas, et la route ne servait pas les échantillons.
"""
import json
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"

_PRELUDE = """
global.window = global;
global.navigator = {};
require(%s);
require(%s);
const OA = window.OverlayAdmin;
function oublier() {
  Object.keys(OA.mesures).forEach(function (c) { delete OA.mesures[c]; });
}
// La fenêtre de l'aperçu, réduite à ce que `mesurerBanc` lui demande : un banc
// qui rend des tailles, et le compte des appels reçus.
function vueAvecBanc(vues, options) {
  const o = options || {};
  const vue = {appels: [], WallyBanc: {mesurer: function (ech) {
    vue.appels.push(ech);
    if (o.leve) throw new Error("banc cassé");
    return vues;
  }}};
  return vue;
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


# ── 1. Une mesure est ACQUISE ───────────────────────────────────────────────

def test_une_mesure_survit_a_la_disparition_du_widget():
    """Le défaut « perdu après coup ».

    Le dé s'affiche, sa taille est lue. Il s'en va — la passe suivante ne le
    voit plus. Sa taille reste : elle a été mesurée pour de bon, et l'oublier
    ferait retomber le cadre sur l'estimation qu'on vient précisément de
    remplacer.
    """
    assert _node("""
      oublier();
      OA.fusionnerMesures({dice: [170, 78]});
      OA.fusionnerMesures({});            // le dé n'est plus à l'écran
      const r = OA.tailleRendue("dice");
      console.log(JSON.stringify([r.taille, r.reelle]));
    """) == "[[170,78],true]"


def test_une_nouvelle_mesure_remplace_l_ancienne():
    """Acquise ne veut pas dire figée : un sondage à cinq options est plus large
    qu'à deux, et c'est la DERNIÈRE lecture qui vaut."""
    assert _node("""
      oublier();
      OA.fusionnerMesures({poll: [260, 192]});
      OA.fusionnerMesures({poll: [260, 320]});
      console.log(JSON.stringify(OA.tailleRendue("poll").taille));
    """) == "[260,320]"


def test_la_fusion_signale_ce_qui_a_change():
    """Le redessin des trente-quatre repères est conditionné à ce retour : une
    passe qui ne change rien ne doit pas les reconstruire, sans quoi ils
    clignotent à chaque frame d'une animation d'entrée."""
    assert _node("""
      oublier();
      const cas = [
        OA.fusionnerMesures({dice: [170, 78]}),   // nouvelle
        OA.fusionnerMesures({dice: [170, 78]}),   // identique
        OA.fusionnerMesures({}),                  // plus rien à l'écran
        OA.fusionnerMesures({dice: [171, 78]}),   // un pixel de plus
      ];
      console.log(JSON.stringify(cas));
    """) == "[true,false,false,true]"


def test_une_taille_tordue_est_refusee():
    """Un zéro, un négatif ou un non-nombre poserait un repère d'un pixel au
    milieu de la scène — pire que l'ordre de grandeur qu'il remplace."""
    assert _node("""
      oublier();
      OA.fusionnerMesures({dice: [0, 78], poll: [-3, 10], wheel: ["gros", 2],
                           quote: [220, null], raid: [256, 100]});
      console.log(JSON.stringify(Object.keys(OA.mesures).sort()));
    """) == '["raid"]'


# ── 2. Le banc de l'aperçu ──────────────────────────────────────────────────

def test_le_banc_pose_les_tailles_sans_lancer_le_widget():
    """C'est le cœur du lot : les cadres sont justes à l'ouverture du panneau,
    sans qu'aucun widget n'ait été déclenché."""
    assert _node("""
      oublier();
      const vue = vueAvecBanc({dice: [170, 78], wheel: [220, 220]});
      const change = OA.mesurerBanc(vue, {dice: {result: "4"}});
      const r = OA.tailleRendue("wheel");
      console.log(JSON.stringify([change, r.taille, r.reelle]));
    """) == "[true,[220,220],true]"


def test_le_banc_recoit_les_echantillons_du_serveur():
    """Les paramètres viennent de la table de prod, servie avec le layout : un
    sondage construit sans options ne dirait rien de son encombrement."""
    assert _node("""
      oublier();
      const vue = vueAvecBanc({});
      OA.mesurerBanc(vue, {poll: {question: "?", options: ["a", "b"]}});
      console.log(JSON.stringify(vue.appels));
    """) == '[{"poll":{"question":"?","options":["a","b"]}}]'


def test_le_banc_absent_ne_casse_rien():
    """Aperçu pas encore chargé, page servie par une version plus ancienne,
    origine devenue étrangère : le panneau garde ses estimations et continue."""
    assert _node("""
      oublier();
      const cas = [
        OA.mesurerBanc(null, {}),
        OA.mesurerBanc({}, {}),
        OA.mesurerBanc({WallyBanc: {}}, {}),
        OA.mesurerBanc(vueAvecBanc(null, {leve: true}), {}),
      ];
      console.log(JSON.stringify([cas, Object.keys(OA.mesures)]));
    """) == "[[false,false,false,false],[]]"


def test_une_mesure_a_l_ecran_l_emporte_sur_le_banc():
    """Le banc mesure un ÉCHANTILLON — quatre options de sondage, deux dés. Ce
    qui est vraiment à l'écran porte les vraies données, et c'est cela qu'on
    règle : sa lecture doit donc écraser celle du banc, jamais l'inverse."""
    assert _node("""
      oublier();
      OA.mesurerBanc(vueAvecBanc({poll: [260, 192]}), {});
      OA.fusionnerMesures({poll: [260, 420]});   // le vrai sondage, à l'écran
      OA.mesurerBanc(vueAvecBanc({poll: [260, 192]}), {});
      console.log(JSON.stringify(OA.tailleRendue("poll").taille));
    """) == "[260,420]"


def test_une_boite_mesuree_par_le_serveur_n_est_pas_une_supposition():
    """Les widgets à média ne sont mesurables QUE par le serveur, sur le dossier
    — le navigateur n'y a pas accès. Leur cadre s'affichait pourtant en
    pointillés « taille supposée », et le compte annonçait moins de mesures
    qu'il n'y en avait vraiment."""
    assert _node("""
      oublier();
      const avant = OA.tailleRendue("meme").reelle;
      window.WallyLayout.poserTailles({meme: [380, 420]});
      const apres = OA.tailleRendue("meme");
      console.log(JSON.stringify([avant, apres.reelle, apres.taille]));
    """) == "[false,true,[380,420]]"


# ── 3. Les échantillons viennent du serveur, jamais d'une table en JS ───────

def test_le_layout_admin_sert_les_echantillons():
    """Ils voyagent avec le layout, comme les libellés et les boîtes de médias :
    le panneau fait déjà cet appel, et une seconde table écrite en JavaScript
    aurait divergé de celle de prod au premier widget ajouté."""
    from unittest.mock import MagicMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from bot.dashboard.routes.overlay import _ECHANTILLONS, admin_router

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/admin")
    app.state.wally = MagicMock()
    app.state.wally.db = None
    r = TestClient(app).get("/api/admin/overlay/layout")
    assert r.status_code == 200
    assert r.json()["echantillons"] == _ECHANTILLONS


def test_le_banc_ecarte_ce_qu_il_ne_sait_pas_mesurer():
    """Cinq exclusions, chacune pour une raison qui tient :

    · `meme`, `rotator`, `image` — leur boîte est IMPOSÉE, mesurée par le
      serveur sur le dossier. Le banc afficherait une image particulière et
      rendrait un cadre qui change à chaque rotation.
    · `planning` — sa taille est celle de l'image qu'on lui donne.
    · `clip` — la table porte volontairement l'état LECTURE (le plus
      encombrant) ; l'échantillon ne monte que la carte d'annonce, trois fois
      plus petite, et un repère trop petit laisserait la vidéo recouvrir ses
      voisins.
    · `apex_progress` — la courbe se retire faute de relevés. Relevée au banc
      dans un vrai navigateur : 560 × 22, un trait plat pour un panneau qui
      porte une courbe en live.
    """
    src = (_STATIC / "overlay.js").read_text(encoding="utf-8")
    assert "BANC_HORS" in src, "le banc doit dire ce qu'il n'inclut pas"
    bloc = src.split("const BANC_HORS", 1)[1].split("}", 1)[0]
    for cle in ("meme", "rotator", "image", "planning", "clip", "apex_progress"):
        assert cle in bloc, f"{cle} doit rester hors du banc"
