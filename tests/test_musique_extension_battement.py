"""La boucle de l'extension : ce qu'elle demande au bot, et quand elle repart.

Le défaut que ces tests verrouillent a coûté la commande « mets lecture »
pendant toute la vie de l'extension. `content.js` battait sur
`setInterval(…, 2000)` ; or Chrome ramène les timers d'un onglet caché et
silencieux à UN PAR MINUTE (« intensive throttling », Chrome 88). Mesuré dans
les logs de prod le 2026-08-21 : soixante secondes pile entre deux battements,
huit fois de suite, pendant que deux ordres `play` périmaient sans jamais partir.

Le piège se refermait sur lui-même : un onglet qui JOUE est exempté du
throttling. Seule la commande qui s'adresse à un lecteur ARRÊTÉ tombait donc
dans le trou — c'est-à-dire exactement `play`.

D'où ces tests : la boucle ne doit plus rien attendre d'un timer, et c'est ce
qu'elle demande au bot (`attente`) qui porte la cadence. On l'exécute vraiment,
sous node, avec un faux navigateur — la mesurer autrement reviendrait à
asserter le code qu'on vient d'écrire.
"""
import json
import subprocess
from pathlib import Path

import pytest

_EXT = Path(__file__).resolve().parents[1] / "extension-musique"

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")

# Un navigateur juste assez complet pour que `content.js` s'exécute : le
# stockage de l'extension, le fil de messages avec le pont, et `fetch`.
#
# Seuls les délais qui se comptent en SECONDES sont raccourcis (le repli quand
# le bot est injoignable) : ils immobiliseraient la suite de tests. Les délais
# courts gardent leur durée réelle — ce sont des filets d'erreur, et les
# raccourcir rendrait invisible ce qu'ils rattrapent.
_PRELUDE = """
global.window = global;
const vraiSetTimeout = global.setTimeout;
let RACCOURCIR_REPLI = true;    // les replis se comptent en secondes
global.setTimeout = (fn, ms) => vraiSetTimeout(
  fn, (ms || 0) >= 1000 && RACCOURCIR_REPLI ? 5 : ms);

const ecouteurs = [];
window.addEventListener = (type, fn) => { if (type === "message") ecouteurs.push(fn); };
window.postMessage = (msg) => queueMicrotask(
  () => ecouteurs.slice().forEach((fn) => fn({ source: window, data: msg })));
global.location = {
  href: "https://www.youtube.com/watch?v=abc",
  assign: (u) => { JOURNAL.navigations.push({ u, a: Date.now() }); },
};
global.document = { addEventListener: () => {} };
const RANGEMENT = new Map();
global.sessionStorage = {
  getItem: (c) => (RANGEMENT.has(c) ? RANGEMENT.get(c) : null),
  setItem: (c, v) => RANGEMENT.set(c, String(v)),
};

global.chrome = {
  storage: {
    local: { get: (_cles, cb) => cb(
      { url: "https://bot.test", jeton: "letoken", actif: true }) },
    onChanged: { addListener: () => {} },
  },
  runtime: {
    getManifest: () => ({ version: "1.3.0" }),
    onMessage: { addListener: () => {} },
    sendMessage: () => ({ catch: () => {} }),
  },
};

// Ce que le faux pont répondra, et ce qu'il aura reçu.
const JOURNAL = { envois: [], ordres: [], navigations: [] };
let ETAT = { titre: "Snakes", artiste: "MIYAVI", url: location.href, joue: false };
let PROCHAINS_ORDRES = [];
let ACCUSER = false;
let ACCUSE_RETARD_MS = 0;       // le pont constate avant de répondre
let ALLER = "";                 // l'url que le pont demande d'ouvrir ensuite
let TENUE_MS_PAR_S = 20;        // ce que le faux bot tient, par seconde demandée
let CROISER = 0;                // nombre de « change » émis PENDANT un « lire »
let ECHOUER = false;
let ECHOUER_APRES = -1;         // tombe à partir du Nième envoi

window.addEventListener("message", (ev) => {
  const m = ev.data;
  if (!m || m.marque !== "wally-musique" || m.pour !== "pont") return;
  if (m.type === "lire") {
    if (CROISER > 0) {
      CROISER--;
      window.postMessage({ marque: "wally-musique", pour: "content",
                           type: "change" }, "*");
    }
    window.postMessage({ marque: "wally-musique", pour: "content",
                         type: "etat", etat: ETAT }, "*");
  }
  if (m.type === "ordre") {
    JOURNAL.ordres.push(m.ordre);
    if (ACCUSER) {
      vraiSetTimeout(() => {
        JOURNAL.accuseEmisA = Date.now();
        window.postMessage({ marque: "wally-musique", pour: "content",
                             type: "accuse", id: m.ordre.id, ok: true,
                             titre: "La suivante", aller: ALLER }, "*");
      }, ACCUSE_RETARD_MS);
    }
  }
});

const patience = (ms) => new Promise((r) => vraiSetTimeout(r, ms));

global.fetch = async (_url, options) => {
  const corps = JSON.parse(options.body);
  corps.a = Date.now();
  JOURNAL.envois.push(corps);
  if (ECHOUER || (ECHOUER_APRES >= 0 && JOURNAL.envois.length > ECHOUER_APRES)) {
    throw new Error("bot injoignable");
  }
  const ordres = PROCHAINS_ORDRES;
  PROCHAINS_ORDRES = [];
  // Le bot tient sa réponse quand il n'a rien à rendre — c'est tout l'objet du
  // correctif. À l'échelle du test : vingt millisecondes par seconde demandée.
  if (!ordres.length && corps.attente > 0) {
    await patience(Math.min(corps.attente * TENUE_MS_PAR_S, 400));
  }
  return { ok: true, json: async () => ({ ordres, version: "1.3.0" }) };
};

const souffler = (tours) => new Promise((r) => {
  let n = 0;
  const tic = () => (++n >= tours ? r() : vraiSetTimeout(tic, 5));
  vraiSetTimeout(tic, 5);
});

require(%s);
""" % json.dumps(str(_EXT / "content.js"))


def _node(script: str) -> dict:
    r = subprocess.run(["node", "-e", _PRELUDE + script],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


def test_un_lecteur_A_L_ARRET_demande_au_bot_de_TENIR_sa_reponse():
    """Le cas qui ne marchait pas : onglet caché, vidéo en pause, donc timers
    ralentis à un tour par minute. C'est au bot d'attendre, plus au navigateur."""
    vu = _node("""
      souffler(4).then(() => {
        console.log(JSON.stringify({ attente: JOURNAL.envois[0].attente,
                                     joue: JOURNAL.envois[0].joue }));
        process.exit(0);
      });
    """)
    assert vu["joue"] is False
    assert vu["attente"] >= 20


def test_un_lecteur_QUI_JOUE_garde_la_cadence_courte():
    """Là, l'onglet est exempté du throttling (Chrome ne ralentit pas une page
    qui fait du son) : rien ne justifie de tenir la réponse, et un morceau qui
    change doit remonter tout de suite."""
    vu = _node("""
      ETAT = { titre: "Numb", artiste: "Linkin Park", url: location.href, joue: true };
      souffler(4).then(() => {
        console.log(JSON.stringify({ attente: JOURNAL.envois[0].attente }));
        process.exit(0);
      });
    """)
    assert 0 < vu["attente"] <= 5


def test_l_etat_envoye_est_celui_de_MAINTENANT_pas_du_tour_precedent():
    """La boucle ne repassant plus toutes les deux secondes, se contenter de la
    réponse du tour d'avant enverrait au bot un titre vieux de vingt secondes."""
    vu = _node("""
      souffler(3).then(() => {
        ETAT = { titre: "Autre chose", artiste: "Quelqu'un", url: location.href,
                 joue: false };
        window.postMessage({ marque: "wally-musique", pour: "content",
                             type: "change" }, "*");
        return souffler(4);
      }).then(() => {
        console.log(JSON.stringify({ titres: JOURNAL.envois.map((e) => e.titre) }));
        process.exit(0);
      });
    """)
    assert vu["titres"][0] == "Snakes"
    assert "Autre chose" in vu["titres"]


def test_l_accuse_part_SANS_attendre_le_tour_suivant():
    """Le bot guette cet accusé pour répondre dans le chat. Le 2026-08-21 à
    10:29:05, il est arrivé trop tard : Wally a annoncé « ça n'a pas marché »
    et le morceau a changé cinq secondes plus tard, sous les yeux du chat."""
    vu = _node("""
      ACCUSER = true;
      // Le pont constate avant de répondre (« suivante » attend le changement
      // d'url) : quand son accusé arrive, la boucle est déjà repartie attendre.
      ACCUSE_RETARD_MS = 40;
      PROCHAINS_ORDRES = [{ id: "abc123", action: "next", query: "" }];
      souffler(60).then(() => {
        const porteur = JOURNAL.envois.find((e) => e.accuses.length);
        console.log(JSON.stringify({
          ordres: JOURNAL.ordres.map((o) => o.action),
          accuse: porteur ? porteur.accuses[0].id : "",
          delai: porteur ? porteur.a - JOURNAL.accuseEmisA : -1,
        }));
        process.exit(0);
      });
    """)
    assert vu["ordres"] == ["next"]
    assert vu["accuse"] == "abc123"
    # Le bot tient sa réponse 400 ms dans ce harnais : attendre le tour suivant
    # se verrait tout de suite ici, et se compterait en secondes en vrai.
    assert 0 <= vu["delai"] < 100


def test_un_accuse_n_est_pas_PERDU_quand_l_envoi_echoue():
    """Perdu, il ferait dire « ça n'a pas marché » sur un geste fait — le défaut
    même que l'accusé existe pour éviter."""
    vu = _node("""
      ACCUSER = true;
      PROCHAINS_ORDRES = [{ id: "abc123", action: "next", query: "" }];
      souffler(4).then(() => {
        ECHOUER = true;
        return souffler(3);
      }).then(() => {
        ECHOUER = false;
        return souffler(20);
      }).then(() => {
        console.log(JSON.stringify({
          accuses: JOURNAL.envois.filter((e) => e.accuses.length).length }));
        process.exit(0);
      });
    """)
    assert vu["accuses"] >= 1


def test_la_boucle_ne_TOURNE_PAS_A_VIDE_si_le_bot_repond_sans_tenir():
    """Un bot d'avant ce correctif répond immédiatement. Sans repli, la boucle
    le martèlerait à plein régime sur la machine d'Azraël."""
    vu = _node("""
      souffler(40).then(() => {
        console.log(JSON.stringify({ envois: JOURNAL.envois.length }));
        process.exit(0);
      });
    """)
    # Le repli vaut deux secondes en vrai ; ce test l'a raccourci à 5 ms, d'où
    # le plafond large. Ce qu'on vérifie, c'est qu'il y a un frein — sans lui,
    # ce compte se chiffrerait en dizaines de milliers.
    assert vu["envois"] < 100


def test_un_accuse_qui_ne_PART_PAS_ne_fait_pas_tourner_la_boucle_a_plein_regime():
    """Le bot redémarre pile après un ordre : l'accusé revient dans la file, et
    le relancer aussitôt à chaque échec martèlerait un bot mort aussi vite que
    la machine le permet — sans aucun timer pour freiner, puisque c'est
    justement ce qu'on a retiré."""
    vu = _node("""
      ACCUSER = true;
      ECHOUER_APRES = 1;            // le premier envoi rend l'ordre, puis tout tombe
      PROCHAINS_ORDRES = [{ id: "abc123", action: "next", query: "" }];
      souffler(30).then(() => {
        console.log(JSON.stringify({ envois: JOURNAL.envois.length }));
        process.exit(0);
      });
    """)
    assert vu["envois"] < 60


def test_deux_lectures_d_etat_qui_se_CROISENT_se_repondent_toutes_les_deux():
    """La boucle et un tour hors rang peuvent demander l'état en même temps. Si
    la seconde demande écrasait la première, celle-ci ne serait plus rendue que
    par son filet — un `setTimeout`, donc jusqu'à une MINUTE en arrière-plan, la
    boucle bloquée pendant ce temps."""
    vu = _node("""
      TENUE_MS_PAR_S = 5;        // le bot tient cent millisecondes
      CROISER = 20;              // et le lecteur bouge à chaque interrogation
      souffler(200).then(() => {
        console.log(JSON.stringify({
          boucle: JOURNAL.envois.filter((e) => e.attente > 0).length }));
        process.exit(0);
      });
    """)
    # En une seconde, la boucle fait un tour par tenue (cent millisecondes).
    # Si sa lecture d'état se fait écraser, elle attend son filet de 500 ms à
    # chaque tour et n'en fait plus que deux.
    assert vu["boucle"] >= 5


def test_chaque_battement_dit_DE_QUEL_ONGLET_il_vient():
    """Sans cette clé, la page d'accueil de l'onglet d'à côté efface le morceau
    en cours : le bot n'avait qu'un seul état pour toutes les pages ouvertes."""
    vu = _node("""
      TENUE_MS_PAR_S = 1;        // des battements rapprochés, pour en compter
      souffler(40).then(() => {
        const ids = [...new Set(JOURNAL.envois.map((e) => e.onglet))];
        console.log(JSON.stringify({ ids, envois: JOURNAL.envois.length,
                                     vide: ids.filter((i) => !i).length }));
        process.exit(0);
      });
    """)
    assert vu["envois"] >= 3, "trop peu de battements pour conclure"
    # Un seul identifiant, non vide, pour tous les battements de cet onglet.
    assert len(vu["ids"]) == 1 and vu["vide"] == 0


def test_l_identifiant_d_onglet_SURVIT_a_un_rechargement():
    """Il est rangé dans le stockage de session, pas tiré au chargement : sinon
    chaque vidéo ouverte passerait pour un nouvel onglet, et l'ancien resterait
    quarante-cinq secondes à raconter un morceau parti."""
    vu = _node("""
      souffler(4).then(() => {
        const premier = JOURNAL.envois[0].onglet;
        // On rejoue le script comme le ferait un rechargement de la page.
        delete require.cache[require.resolve(%s)];
        require(%s);
        return souffler(6).then(() => {
          console.log(JSON.stringify({
            premier, dernier: JOURNAL.envois[JOURNAL.envois.length - 1].onglet }));
          process.exit(0);
        });
      });
    """ % (json.dumps(str(_EXT / "content.js")), json.dumps(str(_EXT / "content.js"))))
    assert vu["premier"] == vu["dernier"]


def test_lancer_un_titre_NAVIGUE_APRES_avoir_livre_son_accuse():
    """La page partait avant : document déchargé, script tué, accusé perdu — et
    Wally annonçait « ça n'a pas marché » sur une recherche pourtant lancée."""
    vu = _node("""
      ACCUSER = true;
      ALLER = "https://www.youtube.com/results?search_query=linkin+park";
      PROCHAINS_ORDRES = [{ id: "abc123", action: "play_query",
                            query: "linkin park" }];
      souffler(60).then(() => {
        const porteur = JOURNAL.envois.find((e) => e.accuses.length);
        console.log(JSON.stringify({
          accuse: porteur ? porteur.accuses[0].id : "",
          envoyeA: porteur ? porteur.a : -1,
          navigations: JOURNAL.navigations.map((n) => n.u),
          navigueA: JOURNAL.navigations.length ? JOURNAL.navigations[0].a : -1,
        }));
        process.exit(0);
      });
    """)
    assert vu["accuse"] == "abc123", "l'accusé n'est jamais parti"
    assert vu["navigations"] == [
        "https://www.youtube.com/results?search_query=linkin+park"]
    assert vu["navigueA"] >= vu["envoyeA"], "la page est partie avant l'accusé"


def test_apres_une_coupure_du_bot_le_premier_REESSAI_est_immediat():
    """Le repli passe par un `setTimeout`, que Chrome étire à la minute dans un
    onglet caché : sans ce premier essai à chaud, chaque rebuild du bot coûterait
    une minute de silence de plus."""
    vu = _node("""
      ECHOUER = true;
      RACCOURCIR_REPLI = false;  // le repli garde ses deux vraies secondes
      souffler(20).then(() => {
        console.log(JSON.stringify({ envois: JOURNAL.envois.length }));
        process.exit(0);
      });
    """)
    # Deux tours en cent millisecondes, alors que le repli vaut deux secondes :
    # le second ne peut venir que du réessai à chaud.
    assert vu["envois"] >= 2
