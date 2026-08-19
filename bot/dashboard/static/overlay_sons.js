/* Les sons de l'overlay — le ding de chaque fenêtre du spam, l'impact du BSOD.
 *
 * Demande de l'owner (2026-08-19) : « je voudrais avoir le son de Windows à
 * chaque fenêtre, et au blue screen aussi ».
 *
 * Web Audio et NON `new Audio()`. À la fin du spam une fenêtre s'ouvre toutes
 * les 100 ms : trois cents lectures en une trentaine de secondes. Trois cents
 * éléments `<audio>` sont trois cents pipelines média sur la machine qui ENCODE
 * le live ; trois cents `AudioBufferSourceNode` partagent un même tampon décodé
 * une seule fois et se détruisent tout seuls à la fin. C'est ce qui rend le
 * « chaos total, sans plafond » demandé par l'owner tenable — en régime, le
 * ding durant 0,7 s, il n'y a de toute façon jamais plus de sept voix vivantes.
 *
 * Le contexte audio est créé PARESSEUSEMENT, à la première lecture : sans lui,
 * ce fichier s'exécute tel quel hors navigateur, et le tirage se teste sous
 * node comme celui d'`overlay_virus.js`.
 */
(() => {
  "use strict";

  // Le battement de silence entre la coupure du chaos et l'impact du BSOD.
  // C'est le silence qui fait l'effet : l'impact posé par-dessus les derniers
  // dings ne s'entend pas comme une fin, seulement comme un son de plus.
  const SILENCE_MS = 250;

  // Un demi-ton d'écart au plus. Trois cents fois le MÊME échantillon à la même
  // hauteur, ça ne s'entend pas comme trois cents fenêtres mais comme un seul
  // son qui bave (le battement entre copies identiques). Réservé aux popups :
  // l'impact final, lui, doit rester exactement tel qu'il a été choisi.
  const PITCH_MIN = 0.94;
  const PITCH_MAX = 1.06;

  // Six dings superposés à plein volume saturent la sortie, et OBS enregistre
  // la saturation telle quelle. Le mur de bruit reste un mur ; il ne crache pas.
  const VOLUME = 0.8;

  const GENRES = ["popup", "bsod"];

  let ctx = null;
  let maitre = null;
  // { popup: [{nom, buffer}], bsod: [...] } — décodé une fois, rejoué à volonté.
  const tampons = { popup: [], bsod: [] };
  // Les sources en train de sonner, pour pouvoir toutes les couper d'un coup.
  const vivantes = new Set();
  // Le chargement en cours, s'il y en a un. Le boot de la page et le
  // déclenchement du spam s'appellent l'un après l'autre à quelques
  // millisecondes d'intervalle : sans ce partage, les deux téléchargeaient et
  // décodaient les MÊMES fichiers en parallèle — mesuré, six décodages pour
  // trois sons. Le second appel attend simplement le travail du premier.
  let enCours = null;

  /* Le contexte audio, créé au dernier moment.
   *
   * Dans OBS il démarre actif : la source navigateur tourne avec
   * `--autoplay-policy=no-user-gesture-required`. Dans un navigateur ordinaire
   * — l'aperçu du dashboard — il naît « suspended » et le restera tant que
   * personne n'a cliqué dans la page. C'est le comportement attendu, pas une
   * panne : on tente un `resume()` à chaque lecture et on n'insiste pas.
   */
  function contexte() {
    if (ctx) return ctx;
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return null;
    try {
      ctx = new C();
    } catch (e) {
      return null;
    }
    maitre = ctx.createGain();
    maitre.gain.value = VOLUME;
    maitre.connect(ctx.destination);
    return ctx;
  }

  /* Relit le dossier et décode ce qui est nouveau.
   *
   * Appelée au chargement de la page ET au déclenchement du spam, pour la même
   * raison que le stock de memes est relu : l'owner dépose ou retire un son
   * pendant le live, et la page ne doit pas rester sur l'inventaire de son
   * ouverture. Ce qui est déjà décodé n'est jamais retéléchargé.
   *
   * Ne rejette jamais : un son illisible en laisse passer d'autres, et un
   * overlay muet vaut mieux qu'un overlay en erreur.
   */
  function charger() {
    if (enCours) return enCours;
    enCours = _charger();
    // `finally` et non `then` : un chargement qui échoue doit rendre la main
    // aux suivants, sinon un réseau coupé une fois fige l'inventaire pour tout
    // le live.
    enCours = enCours.finally(() => { enCours = null; });
    return enCours;
  }

  async function _charger() {
    const c = contexte();
    if (!c) return;
    let dispo = {};
    try {
      const r = await fetch("/api/public/sons");
      const data = await r.json();
      dispo = (data && data.sons) || {};
    } catch (e) {
      return;                         // dossier injoignable : on garde l'acquis
    }
    for (const genre of GENRES) {
      const noms = Array.isArray(dispo[genre]) ? dispo[genre] : [];
      // Un son retiré du dossier cesse de sonner, sans rechargement de page.
      tampons[genre] = tampons[genre].filter((s) => noms.indexOf(s.nom) >= 0);
      for (const nom of noms) {
        if (tampons[genre].some((s) => s.nom === nom)) continue;
        try {
          const rep = await fetch(
            "/api/public/son/" + encodeURIComponent(genre) + "/"
            + encodeURIComponent(nom));
          if (!rep.ok) continue;
          const brut = await rep.arrayBuffer();
          const buffer = await c.decodeAudioData(brut);
          tampons[genre].push({ nom, buffer });
        } catch (e) {
          // Un fichier illisible ne doit pas emporter les suivants.
        }
      }
    }
  }

  /* Joue un son du genre demandé, tiré au sort. Rend la source, ou null. */
  function jouer(genre, varier) {
    const c = contexte();
    if (!c) return null;
    const pool = tampons[genre] || [];
    if (!pool.length) return null;
    // Hors OBS, ceci ne débloque rien tant que la page n'a pas été cliquée —
    // et c'est très bien ainsi : on ne réclame pas l'audio à un aperçu.
    if (c.state === "suspended" && c.resume) {
      try { c.resume(); } catch (e) { /* rien à faire de plus */ }
    }
    const choix = pool[Math.floor(Math.random() * pool.length)];
    const src = c.createBufferSource();
    src.buffer = choix.buffer;
    if (varier) {
      src.playbackRate.value = PITCH_MIN + Math.random() * (PITCH_MAX - PITCH_MIN);
    }
    src.connect(maitre || c.destination);
    src.onended = () => vivantes.delete(src);
    vivantes.add(src);
    try {
      src.start();
    } catch (e) {
      vivantes.delete(src);
      return null;
    }
    return src;
  }

  /* Une fenêtre s'ouvre. */
  function popup() {
    return jouer("popup", true);
  }

  /* Coupe net tout ce qui sonne. */
  function couperTout() {
    vivantes.forEach((src) => {
      try { src.stop(); } catch (e) { /* déjà finie */ }
    });
    vivantes.clear();
  }

  /* L'écran bleu : le chaos s'arrête d'un coup, un silence, puis l'impact. */
  function bsod() {
    couperTout();
    if (!contexte()) return;
    setTimeout(() => jouer("bsod", false), SILENCE_MS);
  }

  window.WallySons = {
    charger, popup, bsod, couperTout,
    // Pour les tests : ce que la page a réellement en mémoire, et ce qui sonne.
    inventaire: () => ({ popup: tampons.popup.map((s) => s.nom),
                         bsod: tampons.bsod.map((s) => s.nom) }),
    nbVivantes: () => vivantes.size,
    SILENCE_MS, VOLUME, PITCH_MIN, PITCH_MAX,
  };

  // Décodage dès l'ouverture de la page : le premier ding du spam ne doit pas
  // attendre un aller-retour réseau. Sans AudioContext (node, ou navigateur
  // trop vieux) `charger()` rend la main immédiatement.
  charger();
})();
