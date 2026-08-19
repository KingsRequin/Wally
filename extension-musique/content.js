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
 */
(() => {
  "use strict";

  const MARQUE = "wally-musique";
  const PERIODE_MS = 2000;
  // Le bot considère l'extension muette au-delà de 45 s : on bat bien plus
  // souvent, pour qu'un hoquet réseau ne le fasse pas conclure au silence.

  let reglages = { url: "", jeton: "", actif: false };
  let dernierEtat = null;
  const accusesEnAttente = [];
  // Ce que la fenêtre de réglages viendra demander : cet onglet-ci parle-t-il ?
  // Un onglet YouTube ouvert AVANT l'installation n'a pas ce script et se tait
  // pour toujours — sans ce rapport, rien ne le disait, et l'essai du bouton
  // « Enregistrer » réussissait quand même (il part de l'extension, pas d'ici).
  const rapport = { dernierOk: 0, erreur: "", majVersion: "" };

  // La version installée, telle que Chrome la connaît. Comparée à celle que le
  // bot sert : une extension chargée depuis un dossier ne se met jamais à jour
  // seule, et rien ne le disait.
  const MA_VERSION = chrome.runtime.getManifest().version;

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

    if (msg.type === "etat") { dernierEtat = msg.etat; return; }
    if (msg.type === "accuse") {
      accusesEnAttente.push({ id: msg.id, ok: !!msg.ok,
                              titre: msg.titre || "", raison: msg.raison || "" });
    }
  });

  const demanderAuPont = (charge) =>
    window.postMessage({ marque: MARQUE, pour: "pont", ...charge }, "*");

  // ── Le battement ─────────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _expediteur, repondre) => {
    if (!msg || msg.marque !== MARQUE || msg.type !== "diagnostic") return;
    repondre({ dernierOk: rapport.dernierOk, erreur: rapport.erreur,
               actif: reglages.actif, maVersion: MA_VERSION,
               majVersion: rapport.majVersion,
               titre: (dernierEtat && dernierEtat.titre) || "" });
  });

  /* La pastille sur l'icône, posée par `fond.js` — seul à pouvoir le faire.
   *
   * Envoyée seulement quand l'état CHANGE : le battement passe toutes les deux
   * secondes, et trois onglets YouTube ouverts en feraient quatre-vingt-dix
   * messages par minute pour une pastille qui ne bouge pas.
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

  async function battre() {
    demanderAuPont({ type: "lire" });          // l'état arrivera par message
    if (!reglages.actif || !reglages.url || !reglages.jeton) {
      rapport.erreur = reglages.actif ? "adresse ou jeton manquant"
                                      : "partage éteint";
      return;
    }

    // Sur une page sans lecteur, on bat quand même : le bot doit savoir que
    // l'extension est VIVANTE, sinon il conclut au silence et se tait.
    const etat = dernierEtat || {};
    const corps = {
      actif: true,
      joue: !!etat.joue,
      titre: etat.titre || "",
      artiste: etat.artiste || "",
      url: etat.url || location.href,
      accuses: accusesEnAttente.splice(0, accusesEnAttente.length),
    };

    let reponse;
    try {
      reponse = await fetch(reglages.url + "/api/music/beat", {
        method: "POST",
        headers: { "Content-Type": "application/json",
                   "Authorization": "Bearer " + reglages.jeton },
        body: JSON.stringify(corps),
      });
    } catch (e) {
      // Le bot redémarre, le réseau tousse : on réessaiera dans 2 s. Mais on
      // le NOTE — c'est ce que la fenêtre montrera au lieu d'un silence.
      rapport.erreur = "bot injoignable";
      return;
    }
    if (!reponse.ok) {
      rapport.erreur = "le bot a répondu " + reponse.status;
      return;
    }
    rapport.dernierOk = Date.now();
    rapport.erreur = "";

    let data;
    try { data = await reponse.json(); } catch (e) { return; }
    signalerMiseAJour(data.version || "");
    // Quel onglet obéit se décide côté BOT, à partir du `joue` envoyé
    // ci-dessus : un ordre reçu ici a déjà quitté la file, l'ignorer le
    // perdrait pour tout le monde. Ici, on exécute.
    (data.ordres || []).forEach((ordre) => demanderAuPont({ type: "ordre", ordre }));
  }

  setInterval(battre, PERIODE_MS);
  battre();
})();
