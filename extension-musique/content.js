/* Le battement : ce qui passe part vers Wally, les ordres en reviennent.
 *
 * S'exécute dans le monde isolé de l'extension — c'est lui qui a le droit de
 * parler au réseau et au stockage, que `pont.js` (monde de la page) n'a pas.
 * Les deux se passent les messages par `window.postMessage`.
 *
 * Un seul canal dans les deux sens : la réponse au battement porte les ordres
 * en attente. Le flux SSE envisagé d'abord aurait demandé des tickets à usage
 * unique (`EventSource` ne porte pas d'en-tête), une route de flux et sa
 * reconnexion, pour gagner une seconde sur une action que Wally met déjà plus
 * longtemps à décider.
 *
 * La cadence, elle, n'est plus ici : c'est le BOT qui tient la réponse jusqu'à
 * ce qu'un ordre arrive. Chrome ramène les `setInterval` d'un onglet caché et
 * silencieux à UN PAR MINUTE (« intensive throttling », Chrome 88) — mesuré en
 * prod le 2026-08-21, soixante secondes pile entre deux battements. Le piège
 * était refermé sur lui-même : un onglet qui JOUE est exempté du throttling,
 * donc seule la commande qui s'adresse à un lecteur ARRÊTÉ tombait dans le
 * trou, et « mets lecture » ne pouvait par construction jamais partir. On
 * enchaîne donc sur la promesse `fetch` au lieu d'un timer : un rappel réseau
 * n'est ralenti par rien.
 */
(() => {
  "use strict";

  const MARQUE = "wally-musique";
  // Le repli, et lui seul : bot injoignable, partage éteint, réponse rendue si
  // vite qu'elle ne peut pas avoir tenu. Ce `setTimeout`-là sera ralenti en
  // arrière-plan, et c'est très bien — on ne veut pas marteler un bot absent.
  const REPLI_MS = 2000;
  // Ce qu'on demande au bot de tenir. Deux secondes quand ça joue : l'onglet
  // n'est alors pas ralenti, et on garde la réactivité d'avant sur les
  // changements de morceau. Vingt quand c'est à l'arrêt — l'état ne bouge plus,
  // mais c'est précisément là qu'un « lecture » peut arriver.
  const ATTENTE_JOUE_S = 2;
  const ATTENTE_ARRET_S = 20;
  // Le bot considère l'extension muette au-delà de 45 s : les deux valeurs
  // ci-dessus restent dessous, réponse tenue comprise.

  /* Qui parle. Azraël peut avoir trois pages YouTube ouvertes, et le bot ne
   * savait pas les distinguer : la dernière qui battait écrasait les autres, si
   * bien qu'un onglet posé sur la page d'accueil effaçait le morceau en cours.
   *
   * Dans `sessionStorage` et non en variable : il est propre à l'ONGLET et
   * survit aux navigations. Un identifiant tiré à chaque chargement changerait à
   * chaque vidéo ouverte, et le bot croirait à un nouvel onglet — l'ancien,
   * encore marqué « en lecture », resterait quarante-cinq secondes à raconter un
   * morceau parti.
   */
  const MON_ONGLET = (() => {
    const CLE = "wally-musique-onglet";
    try {
      let id = sessionStorage.getItem(CLE);
      if (!id) {
        id = Math.random().toString(36).slice(2) + Date.now().toString(36);
        sessionStorage.setItem(CLE, id);
      }
      return id;
    } catch (e) {
      // Stockage refusé (mode restreint) : un identifiant par chargement vaut
      // mieux que pas d'identifiant du tout.
      return Math.random().toString(36).slice(2);
    }
  })();

  let reglages = { url: "", jeton: "", actif: false };
  let allerApres = "";             // l'url où partir une fois l'accusé livré
  let dernierEtat = null;
  const attentesEtat = [];         // les `lireEtat()` en cours, s'il y en a
  let horsTourEnVol = false;       // une requête lancée sans attendre son tour
  const accusesEnAttente = [];
  // Ce que la fenêtre de réglages viendra demander : cet onglet-ci parle-t-il ?
  // Un onglet YouTube ouvert AVANT l'installation n'a pas ce script et se tait
  // pour toujours — sans ce rapport, rien ne le disait, et l'essai du bouton
  // « Enregistrer » réussissait quand même (il part de l'extension, pas d'ici).
  const rapport = { dernierOk: 0, erreur: "", majVersion: "", enVol: false };

  // La version installée, telle que Chrome la connaît. Comparée à celle que le
  // bot sert : une extension chargée depuis un dossier ne se met jamais à jour
  // seule, et rien ne le disait.
  const MA_VERSION = chrome.runtime.getManifest().version;

  const patienter = (ms) => new Promise((r) => setTimeout(r, ms));

  // ── Réglages, posés par la fenêtre de l'extension ────────────────────────

  function relireReglages() {
    chrome.storage.local.get(["url", "jeton", "actif"], (r) => {
      reglages = {
        url: String(r.url || "").replace(/\/+$/, ""),
        jeton: String(r.jeton || ""),
        // L'interrupteur commande l'ENVOI : éteint, rien ne part. L'extension
        // voit tout ce qui est ouvert sur YouTube, pas seulement la musique —
        // la confidentialité se joue ici, à la source, pas chez celui qui
        // reçoit.
        actif: r.actif === true,
      };
    });
  }
  relireReglages();
  chrome.storage.onChanged.addListener(relireReglages);

  // ── Le fil avec le pont ──────────────────────────────────────────────────

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const msg = event.data;
    if (!msg || msg.marque !== MARQUE || msg.pour !== "content") return;

    if (msg.type === "etat") {
      dernierEtat = msg.etat;
      // Toutes, et non la dernière : elles veulent le même état, et celle qu'on
      // laisserait tomber ne serait plus rendue que par son filet — un
      // `setTimeout`, donc jusqu'à une MINUTE en arrière-plan, la boucle
      // bloquée pendant ce temps.
      attentesEtat.splice(0, attentesEtat.length).forEach((rendre) => rendre(msg.etat));
      return;
    }
    if (msg.type === "accuse") {
      accusesEnAttente.push({ id: msg.id, ok: !!msg.ok,
                              titre: msg.titre || "", raison: msg.raison || "" });
      // « Lance-moi tel titre » : le pont a validé l'adresse mais n'y est pas
      // allé. S'il l'avait fait, la page serait partie avec le script avant que
      // l'accusé ait pu être livré, et le bot aurait annoncé un échec sur une
      // recherche pourtant lancée. On y va après l'envoi, plus bas.
      if (msg.aller) allerApres = String(msg.aller);
      // L'accusé ne doit pas attendre le tour suivant : le bot le guette pour
      // répondre dans le chat, et une réponse tenue vingt secondes ferait dire
      // « ça n'a pas marché » sur un geste déjà fait. C'est exactement ce qui
      // s'est produit le 2026-08-21 à 10:29:05 — « next » annoncé raté, morceau
      // changé cinq secondes plus tard.
      horsTour();
      return;
    }
    if (msg.type === "change") {
      // Le lecteur a bougé de lui-même (morceau suivant, mise en pause) : ce
      // qu'on a envoyé au bot est périmé, on le rafraîchit sans attendre.
      horsTour();
    }
  });

  const demanderAuPont = (charge) =>
    window.postMessage({ marque: MARQUE, pour: "pont", ...charge }, "*");

  /* Ce que le lecteur dit de lui-même, MAINTENANT.
   *
   * Attendu et non supposé : la boucle ne repasse plus toutes les deux
   * secondes, et se contenter de la réponse du tour précédent enverrait au bot
   * un titre vieux de vingt secondes.
   */
  function lireEtat() {
    return new Promise((resoudre) => {
      attentesEtat.push(resoudre);
      demanderAuPont({ type: "lire" });
      // Filet, jamais le chemin normal : le pont répond en une tâche. S'il
      // n'est pas là du tout (script du monde MAIN non injecté), rien ne doit
      // bloquer la boucle pour toujours. Ce délai-là sera ralenti en
      // arrière-plan, et c'est sans conséquence — il ne sert qu'en panne.
      setTimeout(() => {
        const rang = attentesEtat.indexOf(resoudre);
        if (rang >= 0) { attentesEtat.splice(rang, 1); resoudre(dernierEtat); }
      }, 500);
    });
  }

  // ── Le battement ─────────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _expediteur, repondre) => {
    if (!msg || msg.marque !== MARQUE || msg.type !== "diagnostic") return;
    repondre({ dernierOk: rapport.dernierOk, erreur: rapport.erreur,
               actif: reglages.actif, maVersion: MA_VERSION,
               majVersion: rapport.majVersion, enVol: rapport.enVol,
               titre: (dernierEtat && dernierEtat.titre) || "" });
  });

  /* La pastille sur l'icône, posée par `fond.js` — seul à pouvoir le faire.
   *
   * Envoyée seulement quand l'état CHANGE : trois onglets YouTube ouverts en
   * feraient sinon un flot de messages pour une pastille qui ne bouge pas.
   */
  function signalerMiseAJour(servie) {
    const lib = window.WallyMusiqueLib;
    const enRetard = !!lib && lib.versionPlusRecente(servie, MA_VERSION);
    const version = enRetard ? String(servie) : "";
    if (version === rapport.majVersion) return;
    rapport.majVersion = version;
    // Le `catch` n'est pas décoratif : sans callback, `sendMessage` rend une
    // promesse, et elle est REJETÉE quand le service worker n'est pas encore
    // réveillé ou que l'extension se recharge. Une promesse rejetée sans
    // preneur remplit la console de la page d'erreurs rouges — sur le YouTube
    // d'Azraël, pas sur le nôtre.
    try {
      const envoi = chrome.runtime.sendMessage({ marque: MARQUE, type: "maj",
                                                 disponible: enRetard, version });
      if (envoi && envoi.catch) envoi.catch(() => {});
    } catch (e) { /* extension en cours de rechargement */ }
  }

  /* Un tour de battement. Rend ce que la boucle doit en conclure :
   *   · `temporiser` — rien n'est parti, ou le bot n'a pas répondu ;
   *   · `ordres`     — on a reçu du travail, donc on repart tout de suite.
   *
   * `attente_s` à zéro pour les tours hors rang : ils ne servent qu'à porter un
   * accusé ou un état frais, et laisser DEUX requêtes ouvertes en même temps
   * n'aurait aucun intérêt.
   */
  async function battre(attenteS) {
    const etat = await lireEtat();
    if (!reglages.actif || !reglages.url || !reglages.jeton) {
      rapport.erreur = reglages.actif ? "adresse ou jeton manquant"
                                      : "partage éteint";
      return { temporiser: true };
    }

    // Sur une page sans lecteur, on bat quand même : le bot doit savoir que
    // l'extension est VIVANTE, sinon il conclut au silence et se tait.
    const lu = etat || {};
    const joue = !!lu.joue;
    // Les accusés quittent la file AVANT l'envoi, et y reviennent si l'envoi
    // échoue : perdus, ils feraient dire « ça n'a pas marché » sur un geste
    // fait — le défaut même que cet accusé existe pour éviter.
    const partants = accusesEnAttente.splice(0, accusesEnAttente.length);
    const corps = {
      actif: true,
      joue: joue,
      titre: lu.titre || "",
      artiste: lu.artiste || "",
      url: lu.url || location.href,
      accuses: partants,
      // Quel onglet parle : sans lui, celui d'à côté efface le morceau en cours.
      onglet: MON_ONGLET,
      // Combien de temps le bot peut tenir sa réponse. Absent, il répond tout
      // de suite : c'est ce que fait une version d'avant ce correctif, et le
      // champ est justement ce qui les distingue.
      attente: attenteS === undefined
        ? (joue ? ATTENTE_JOUE_S : ATTENTE_ARRET_S)
        : attenteS,
    };

    let reponse;
    rapport.enVol = true;
    try {
      reponse = await fetch(reglages.url + "/api/music/beat", {
        method: "POST",
        headers: { "Content-Type": "application/json",
                   "Authorization": "Bearer " + reglages.jeton },
        body: JSON.stringify(corps),
        // `keepalive` sur les seuls tours qui portent un accusé sans rien
        // attendre : ce sont eux qui peuvent croiser une navigation (« lance-moi
        // tel titre »), et le navigateur les mène alors à terme même si le
        // document s'en va. Jamais sur un tour tenu : une requête `keepalive`
        // n'est pas faite pour rester ouverte vingt secondes.
        keepalive: corps.attente === 0 && partants.length > 0,
      });
    } catch (e) {
      // Le bot redémarre, le réseau tousse : on réessaiera. Mais on le NOTE —
      // c'est ce que la fenêtre montrera au lieu d'un silence.
      accusesEnAttente.unshift(...partants);
      rapport.erreur = "bot injoignable";
      return { temporiser: true };
    } finally {
      rapport.enVol = false;
    }
    if (!reponse.ok) {
      accusesEnAttente.unshift(...partants);
      rapport.erreur = "le bot a répondu " + reponse.status;
      return { temporiser: true };
    }
    rapport.dernierOk = Date.now();
    rapport.erreur = "";
    // L'accusé est parti : la page peut maintenant s'en aller.
    if (allerApres) {
      const cible = allerApres;
      allerApres = "";
      location.assign(cible);
      return { temporiser: true };
    }

    let data;
    try { data = await reponse.json(); } catch (e) { return { temporiser: true }; }
    signalerMiseAJour(data.version || "");
    // Quel onglet obéit se décide côté BOT, à partir du `joue` envoyé
    // ci-dessus : un ordre reçu ici a déjà quitté la file, l'ignorer le
    // perdrait pour tout le monde. Ici, on exécute.
    const ordres = data.ordres || [];
    ordres.forEach((ordre) => demanderAuPont({ type: "ordre", ordre }));
    return { ordres: ordres.length > 0 };
  }

  /* Un tour lancé sans attendre son rang, pour porter un accusé ou un état qui
   * vient de changer. Un seul à la fois : c'est une politesse, pas une file. */
  function horsTour() {
    if (horsTourEnVol) return;
    horsTourEnVol = true;
    battre(0).catch(() => ({ temporiser: true })).then((tour) => {
      horsTourEnVol = false;
      // Un accusé arrivé pendant ce tour-là n'attend pas le suivant non plus —
      // mais seulement si CELUI-CI est passé. Sinon un bot injoignable et un
      // accusé qui revient dans la file se relanceraient l'un l'autre aussi
      // vite que la machine le permet, et sans aucun timer pour freiner :
      // c'est la boucle qui porte le repli, pas ce chemin-là.
      if (!tour.temporiser && accusesEnAttente.length) horsTour();
    });
  }

  /* La boucle. Aucun timer sur le chemin normal — c'est tout l'objet du
   * correctif : la réponse du bot EST la temporisation. */
  async function boucler() {
    let echecs = 0;
    for (;;) {
      const debut = Date.now();
      let tour;
      try {
        tour = await battre();
      } catch (e) {
        tour = { temporiser: true };
      }
      echecs = tour.temporiser ? echecs + 1 : 0;
      // Le tout premier échec d'une série repart SANS attendre : le bot vient
      // peut-être de redémarrer (une quinzaine de secondes), et le repli
      // ci-dessous passe par un `setTimeout` que Chrome étire à la minute dans
      // un onglet caché. Une minute de silence de plus après chaque rebuild,
      // pour rien.
      if (echecs === 1) continue;
      // Le repli couvre aussi le bot qui répondrait sans tenir (version
      // ancienne, proxy qui coupe) : sans lui, la boucle tournerait à vide et à
      // plein régime sur la machine d'Azraël.
      if (tour.temporiser || (!tour.ordres && Date.now() - debut < 200)) {
        await patienter(REPLI_MS);
      }
    }
  }

  boucler();
})();
