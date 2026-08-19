/* Ce que l'extension sait dire de la musique — le texte, et rien d'autre.
 *
 * Séparé du reste pour être EXÉCUTÉ par les tests (sous node) plutôt que relu :
 * même parti pris que `overlay_virus.js` côté overlay. Tout ce qui touche au DOM
 * de YouTube vit dans `pont.js`, et se vérifie dans un navigateur.
 *
 * Le problème que ce fichier résout, relevé sur la vraie page avant d'écrire une
 * ligne : `navigator.mediaSession` donne l'artiste proprement séparé, mais le
 * titre reste celui de la VIDÉO —
 *   « Numb (Official Music Video) [4K UPGRADE] – Linkin Park »
 * Annoncé tel quel dans le chat Twitch, c'est illisible.
 */
(() => {
  "use strict";

  // Il finit dans un message Twitch (plafonné) et sur l'overlay.
  const MAX = 200;

  // Ce qui est de la DÉCORATION DE MISE EN LIGNE, pas du titre. Volontairement
  // étroit : « (feat. X) », « (Remix) », « (Live à Bercy) » font partie du
  // morceau — les manger désignerait une autre chanson.
  const DECOR = /\b(official|officiel|officielle|video|vidéo|audio|lyrics?|paroles|hd|hq|4k|8k|1080p|720p|remaster(ed)?|mv|m\/v|visuali[sz]er|clip|full album stream)\b/i;

  const texte = (v) => (typeof v === "string" ? v : v == null ? "" : String(v));

  /* Le titre débarrassé de ce qui n'est pas lui.
   *
   * Ne rend JAMAIS une chaîne vide : un nettoyage trop zélé — un titre qui
   * n'est que le nom de l'artiste, ou que des mentions de production — laisserait
   * Wally annoncer « ça joue : » suivi de rien. Dans le doute, le brut.
   */
  function nettoyerTitre(titre, artiste) {
    const brut = texte(titre).trim();
    if (!brut) return "";
    let out = brut;

    // 1. Les parenthèses et crochets de mise en ligne, eux seuls.
    out = out.replace(/[([][^()[\]]*[)\]]/g, (bloc) => (DECOR.test(bloc) ? " " : bloc));

    // 2. L'artiste, s'il est déjà dit par ailleurs. YouTube l'écrit devant ou
    //    derrière, avec un tiret court, long, ou un demi-cadratin.
    const nom = texte(artiste).trim();
    if (nom) {
      const echappe = nom.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      out = out.replace(new RegExp(`^\\s*${echappe}\\s*[-–—]\\s*`, "i"), "");
      out = out.replace(new RegExp(`\\s*[-–—]\\s*${echappe}\\s*$`, "i"), "");
    }

    out = out.replace(/\s{2,}/g, " ").trim();
    // Un tiret resté orphelin d'un bout à l'autre du ménage.
    out = out.replace(/^\s*[-–—]\s*|\s*[-–—]\s*$/g, "").trim();

    return (out || brut).slice(0, MAX);
  }

  /* La phrase que Wally dira. Sans artiste connu, le titre seul — « — Numb »
   * aurait l'air cassé. */
  function pourAnnonce(titre, artiste) {
    const t = texte(titre).trim();
    const a = texte(artiste).trim();
    return a ? `${a} — ${t}` : t;
  }

  /* Ce qu'on envoie au bot, ou `null` s'il n'y a pas de morceau.
   *
   * `null` sur une page sans lecteur (accueil, recherche) : inventer un titre
   * serait pire que se taire. Et l'état de lecture vient de `video.paused`, pas
   * de `playbackState` — mesuré sur la vraie page, celui-ci annonçait « paused »
   * sur une vidéo qui tournait.
   */
  function etatLecteur(lu) {
    const src = lu || {};
    if (src.sansVideo) return null;

    const meta = src.metadata || null;
    let artiste = texte(meta && meta.artist).trim();
    let titre = texte(meta && meta.title).trim();

    // La FICHE musicale de YouTube l'emporte : c'est sa source de vérité,
    // tirée du catalogue, là où le reste n'est que le titre tapé par
    // l'uploadeur. Sur un album entier, elle suit même le morceau en cours
    // pendant que le titre de la vidéo, lui, ne bouge jamais — aucun nettoyage
    // ne peut deviner ça.
    //
    // Champ par champ, et non tout ou rien : le DOM de YouTube change sans
    // prévenir, et ce qui manque se reprend ailleurs plutôt que de tout jeter.
    const fiche = src.fiche || null;
    const ficheTitre = texte(fiche && fiche.titre).trim();
    const ficheArtiste = texte(fiche && fiche.artiste).trim();
    if (ficheTitre) titre = ficheTitre;
    if (ficheArtiste) artiste = ficheArtiste;
    if (ficheTitre) {
      // Déjà propre : le nettoyage n'a plus rien à retirer, et pourrait mordre
      // sur un vrai titre (« Numb (Live) » est un autre morceau).
      return {
        titre: ficheTitre.slice(0, MAX),
        artiste: artiste.slice(0, MAX),
        url: texte(src.url).slice(0, 500),
        joue: !src.videoEnPause,
      };
    }

    if (!titre) {
      // mediaSession n'est remplie qu'une fois la lecture lancée : avant, il
      // reste le titre du document, qu'il faut débarrasser de son suffixe.
      titre = texte(src.titreDocument).replace(/\s*-\s*YouTube\s*$/i, "").trim();
    }
    if (!titre) return null;

    return {
      titre: nettoyerTitre(titre, artiste),
      artiste: artiste.slice(0, MAX),
      url: texte(src.url).slice(0, 500),
      joue: !src.videoEnPause,
    };
  }

  /* La version servie par le bot est-elle plus récente que celle installée ?
   *
   * Une extension chargée depuis un dossier ne se met JAMAIS à jour seule —
   * seul le Web Store le fait. Sans cette comparaison, Azraël garderait une
   * version corrigée depuis des semaines sans le savoir : c'est exactement ce
   * qui vient de se produire.
   *
   * Comparaison NOMBRE PAR NOMBRE, jamais par `!==` ni par ordre alphabétique :
   * `1.10.0` vient après `1.9.0`, et une version plus VIEILLE côté bot (un
   * retour arrière, un déploiement en retard) ne doit pas réclamer une mise à
   * jour. Tout ce qui n'est pas lisible ne réclame rien : un avertissement à
   * tort, et il ne le croira plus.
   */
  function versionPlusRecente(servie, installee) {
    const decouper = (v) => texte(v).trim().split(".").map((n) => parseInt(n, 10));
    const a = decouper(servie);
    const b = decouper(installee);
    if (!a.length || a.some(isNaN) || !b.length || b.some(isNaN)) return false;
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const x = a[i] || 0;
      const y = b[i] || 0;
      if (x !== y) return x > y;
    }
    return false;
  }

  window.WallyMusiqueLib = { nettoyerTitre, pourAnnonce, etatLecteur,
                             versionPlusRecente, MAX };
})();
