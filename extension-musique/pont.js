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

  /* La fiche musicale que YouTube pose sous la vidéo, quand il reconnaît le
   * morceau : « Numb » · « Linkin Park » · « Meteora (Bonus Edition) ».
   *
   * C'est la source la plus propre disponible — celle du catalogue, pas le
   * titre tapé par l'uploadeur — et elle existe sur YouTube ORDINAIRE : Azraël
   * n'a donc pas à passer sur YouTube Music pour que le chat lise un titre
   * correct. Relevée sur la vraie page avant d'écrire ces sélecteurs.
   *
   * Absente pour tout ce que YouTube ne reconnaît pas (mix, reprise, gameplay),
   * et c'est normal : `lib.js` retombe alors sur le nettoyage du titre.
   */
  function ficheMusicale() {
    const titre = document.querySelector(".ytVideoAttributeViewModelTitle");
    if (!titre) return null;
    // L'artiste est le premier texte qui suit le titre dans la même carte. Pris
    // par position et non par classe : celle-ci n'en portait aucune, et une
    // classe inventée serait fausse dès le prochain remaniement de YouTube.
    const carte = titre.closest("ytd-horizontal-card-list-renderer") || titre.parentElement;
    const feuilles = carte
      ? [...carte.querySelectorAll("*")].filter(
          (n) => !n.children.length && (n.innerText || "").trim())
      : [];
    const rang = feuilles.indexOf(titre);
    const suivant = rang >= 0 ? feuilles[rang + 1] : null;
    return {
      titre: (titre.innerText || "").trim(),
      artiste: suivant ? (suivant.innerText || "").trim() : "",
    };
  }

  /* Ce que le lecteur dit de lui-même, à cet instant. */
  function lire() {
    const v = video();
    const media = navigator.mediaSession || {};
    return L.etatLecteur({
      fiche: ficheMusicale(),
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
        // On ne navigue PAS ici : la page partirait avant que l'accusé ait pu
        // être livré — document déchargé, script tué, et le bot conclurait « le
        // lecteur n'a pas répondu » sur une recherche pourtant lancée. C'est
        // `content.js` qui ira, une fois l'accusé parti.
        return { ok: true, titre: "", aller: cible };
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

  /* Ce qui bouge sans qu'on l'ait demandé : le morceau suivant, une mise en
   * pause, une vidéo qui en remplace une autre.
   *
   * `content.js` en a besoin TOUT DE SUITE : sa boucle ne repasse plus toutes
   * les deux secondes — c'est le bot qui tient désormais la réponse, parce que
   * Chrome ralentit les timers d'un onglet caché — et un titre annoncé vingt
   * secondes en retard se verrait dans le chat.
   *
   * En CAPTURE depuis le document, et non sur la balise `<video>` : les
   * événements média ne remontent pas d'eux-mêmes, et YouTube remplace son
   * lecteur au fil des navigations — un écouteur posé sur l'élément serait
   * perdu au premier morceau suivant.
   */
  let dernierSignal = null;
  const signalerChangement = () => {
    // YouTube émet ces événements en rafale — une publicité qui démarre, une
    // vignette survolée qui se met à jouer toute seule. On ne réveille le
    // battement que si ce qu'on RAPPORTE change vraiment, sinon on lui ferait
    // marteler le bot pendant qu'Azraël fait défiler sa page d'accueil.
    const etat = lire();
    const empreinte = etat
      ? JSON.stringify([etat.titre, etat.artiste, etat.joue]) : "";
    if (empreinte === dernierSignal) return;
    dernierSignal = empreinte;
    window.postMessage({ marque: MARQUE, pour: "content", type: "change" }, "*");
  };
  ["play", "pause", "loadedmetadata", "emptied"].forEach(
    (evenement) => document.addEventListener(evenement, signalerChangement, true));

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
