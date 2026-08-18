/* Le pont avec le lecteur YouTube — s'exécute dans le monde de la PAGE.
 *
 * Pourquoi ici et pas dans `content.js` : un content script ordinaire vit dans
 * un « isolated world » et ne voit donc PAS `navigator.mediaSession.metadata`,
 * que YouTube renseigne côté page. Vérifié dans la doc Chrome avant d'écrire :
 * il faut `"world": "MAIN"`. En contrepartie, ce fichier n'a AUCUN accès aux
 * API de l'extension (ni réseau autorisé, ni stockage) — c'est `content.js` qui
 * parle au bot, et les deux se passent les messages par `window.postMessage`.
 *
 * Ce fichier ne décide rien : il lit le lecteur et applique les ordres. Tout ce
 * qui est jugement (nettoyer un titre, choisir quoi annoncer) vit dans `lib.js`,
 * exécuté par les tests.
 */
(() => {
  "use strict";

  const MARQUE = "wally-musique";
  const L = window.WallyMusiqueLib;

  const video = () => document.querySelector("video");

  /* Ce que le lecteur dit de lui-même, à cet instant. */
  function lire() {
    const v = video();
    const media = navigator.mediaSession || {};
    return L.etatLecteur({
      metadata: media.metadata || null,
      titreDocument: document.title,
      videoEnPause: !v || v.paused,
      url: location.href,
      // Pas de balise vidéo : page d'accueil, recherche, chaîne. Il n'y a pas
      // de morceau, et en inventer un serait pire que se taire.
      sansVideo: !v,
    });
  }

  /* Applique un ordre et dit ce qui s'est passé. JAMAIS « c'est fait » sans
   * l'avoir constaté : le bot attend cet accusé pour répondre, et une réponse
   * optimiste ferait mentir Wally en direct. */
  async function appliquer(ordre) {
    const v = video();
    const action = ordre && ordre.action;
    try {
      if (action === "play") {
        if (!v) return { ok: false, raison: "aucune vidéo sur cette page" };
        await v.play();
        return { ok: !v.paused, raison: v.paused ? "le lecteur a refusé" : "" };
      }
      if (action === "pause") {
        if (!v) return { ok: false, raison: "aucune vidéo sur cette page" };
        v.pause();
        return { ok: v.paused, raison: v.paused ? "" : "le lecteur a refusé" };
      }
      if (action === "next" || action === "prev") {
        const bouton = document.querySelector(
          action === "next" ? ".ytp-next-button" : ".ytp-prev-button");
        if (!bouton || bouton.getAttribute("aria-disabled") === "true") {
          return { ok: false,
                   raison: action === "next" ? "pas de vidéo suivante"
                                             : "pas de vidéo précédente" };
        }
        const avant = location.href;
        bouton.click();
        // On CONSTATE le changement au lieu de le supposer : le bouton peut
        // exister et ne rien faire en fin de playlist.
        const change = await attendre(() => location.href !== avant, 2500);
        return change ? { ok: true, titre: titreCourt() }
                      : { ok: false, raison: "le lecteur n'a pas bougé" };
      }
      if (action === "play_query") {
        const cible = versUrl(ordre.query);
        if (!cible) return { ok: false, raison: "recherche vide" };
        location.assign(cible);
        return { ok: true, titre: "" };   // la page s'en va : le titre suivra
      }
    } catch (e) {
      return { ok: false, raison: String((e && e.message) || e).slice(0, 120) };
    }
    return { ok: false, raison: "action inconnue" };
  }

  function titreCourt() {
    const etat = lire();
    return etat ? L.pourAnnonce(etat.titre, etat.artiste) : "";
  }

  /* Un lien YouTube est suivi tel quel ; tout le reste devient une recherche.
   * Un lien HORS YouTube est refusé : cette extension n'a aucune raison
   * d'emmener le navigateur d'Azraël ailleurs. */
  function versUrl(query) {
    const q = String(query || "").trim();
    if (!q) return "";
    if (/^https?:\/\//i.test(q)) {
      try {
        const u = new URL(q);
        return /(^|\.)youtube\.com$|(^|\.)youtu\.be$/i.test(u.hostname) ? u.href : "";
      } catch (e) { return ""; }
    }
    return "https://www.youtube.com/results?search_query=" + encodeURIComponent(q);
  }

  function attendre(condition, plafondMs) {
    return new Promise((resoudre) => {
      const debut = Date.now();
      const tic = setInterval(() => {
        if (condition()) { clearInterval(tic); resoudre(true); }
        else if (Date.now() - debut > plafondMs) { clearInterval(tic); resoudre(false); }
      }, 100);
    });
  }

  // ── Le fil avec `content.js` ─────────────────────────────────────────────
  // `event.source !== window` écarte les messages venus d'une iframe (YouTube
  // en a beaucoup, publicités comprises).
  window.addEventListener("message", async (event) => {
    if (event.source !== window) return;
    const msg = event.data;
    if (!msg || msg.marque !== MARQUE || msg.pour !== "pont") return;

    if (msg.type === "lire") {
      window.postMessage({ marque: MARQUE, pour: "content", type: "etat",
                           etat: lire() }, "*");
      return;
    }
    if (msg.type === "ordre") {
      const resultat = await appliquer(msg.ordre);
      window.postMessage({ marque: MARQUE, pour: "content", type: "accuse",
                           id: msg.ordre.id, ...resultat }, "*");
    }
  });
})();
