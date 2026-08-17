// bot/dashboard/static/overlay_layout.js
//
// Le placement des éléments de l'overlay.
//
// Sorti d'overlay.js, qui fait déjà 1320 lignes et dont la responsabilité est
// le CONTENU (que montre-t-on, quand) — pas la mise en scène (où).
//
// Deux règles gouvernent tout :
//
//   1. Les positions sont en POURCENTAGE, jamais en pixels : la disposition
//      survit à un changement de résolution de la source OBS.
//   2. Les tailles passent par transform:scale() sur un canvas de référence de
//      1920×1080. Redimensionner par la largeur laisserait le texte à 16px dans
//      un widget réduit de moitié et casserait la mise en page des dix-sept —
//      il faudrait retoucher leur CSS un par un.
window.WallyLayout = (function () {
  "use strict";

  const CANVAS_W = 1920;

  // Chaque ancrage dit DEUX choses : de quel bord on mesure, et dans quel sens
  // le contenu grandit. Le `translate` déplace l'élément de sa propre taille,
  // ce que les pourcentages d'une transformation font nativement.
  const ANCRAGES = {
    "top-left":      { h: "left",  v: "top",    tx: "0",     ty: "0" },
    "top-center":    { h: "left",  v: "top",    tx: "-50%",  ty: "0" },
    "top-right":     { h: "right", v: "top",    tx: "0",     ty: "0" },
    "middle-left":   { h: "left",  v: "top",    tx: "0",     ty: "-50%" },
    "center":        { h: "left",  v: "top",    tx: "-50%",  ty: "-50%" },
    "middle-right":  { h: "right", v: "top",    tx: "0",     ty: "-50%" },
    "bottom-left":   { h: "left",  v: "bottom", tx: "0",     ty: "0" },
    "bottom-center": { h: "left",  v: "bottom", tx: "-50%",  ty: "0" },
    "bottom-right":  { h: "right", v: "bottom", tx: "0",     ty: "0" },
  };

  // Les clés du modèle (bot/core/overlay_layout.py). Un test Python vérifie que
  // les deux listes ne divergent pas, et qu'un conteneur existe pour chacune.
  //
  // Elles suivent `BUILDERS` **∪ `APEX_BUILDERS`** — ce que la page RESTITUE —
  // et non l'enum de l'outil `show_overlay`, qui dit ce que le bot peut
  // DEMANDER. Les DEUX objets de builders comptent : `overlay.js` les fusionne
  // par `Object.assign`, et ne lire que le premier a fait manquer les huit
  // panneaux `apex_*` d'`overlay_apex.js`, pourtant publiés en vrai.
  // Les listes ne coïncident pas avec l'enum : `goal` est publié en `gauge`,
  // `uptime` en `counter`, et six widgets rendus (`clip`, `planning`,
  // `prediction`, `quote`, `raid`, `wave`) ne figurent dans aucun enum.
  // Une clé absente est un widget qu'on ne peut PAS placer (`appliquer()`
  // n'itère que sur cette liste) ; une clé en trop n'est qu'un réglage sans
  // effet. L'asymétrie tranche.
  const ELEMENTS = [
    "avatar", "bubble", "rotator", "image",
    "bingo", "stats", "talkers",
    "meme", "clip", "clip_top", "planning", "prediction", "quote", "raid", "wave",
    "versus", "poll", "hangman", "pinned", "counter",
    "coinflip", "dice", "wheel", "gauge", "countdown", "rps",
    "apex_rank", "apex_progress", "apex_status", "apex_stats",
    "apex_map", "apex_craft", "apex_predator", "apex_servers",
  ];

  // Les tailles, en pixels du canvas 1920×1080. Elles servent aux rectangles de
  // manipulation du panneau de mise en scène et aux repères que « Tout
  // afficher » pose sur la page.
  //
  // DEUX NATURES, et la différence compte :
  //
  //   · Un widget de TEXTE se dimensionne par son contenu (`width: max-content`)
  //     et sa taille exacte ne peut pas se connaître à l'avance : « 3 votes » et
  //     « 47 votes » ne font pas la même largeur. Sa valeur ici est donc un
  //     REPLI, le temps que l'aperçu la mesure pour de bon (`tailleRendue`).
  //     Mais un repli se MESURE aussi : celles-ci ont été relevées le
  //     2026-08-17 en affichant chaque widget avec l'échantillon officiel du
  //     bouton ▶ (`_ECHANTILLONS`, routes/overlay.py) et en lisant sa boîte,
  //     ramenée au canvas. Les valeurs d'avant étaient écrites au jugé et
  //     TOUTES trop grandes, de deux à trois fois : le dé annonçait 240 × 240
  //     pour 170 × 78, la jauge 520 × 160 pour 230 × 39. C'est le reproche
  //     d'origine — « les box correspondent pas vraiment à la taille du
  //     widget ». Refaire la mesure après un changement de style est le bon
  //     réflexe ; l'inventer ne l'est jamais.
  //     Trois exceptions, laissées telles quelles faute d'une mesure fiable :
  //     `avatar` et `bubble` (hors du chemin `showWidget`) et `planning` (son
  //     image dépend de celle qu'on lui donne).
  //
  //   · Un widget à MÉDIA (`meme`, `rotator`) affiche une image dont les
  //     dimensions sont arbitraires : le dossier va de 260 à 2100 px de côté,
  //     30 % en portrait. Laisser le cadre épouser le média donnait un
  //     encombrement qui changeait à chaque rotation, donc AUCUN repère juste :
  //     on plaçait sur un rectangle que le rendu n'atteignait jamais. Pour
  //     ceux-là, la valeur ci-dessous est IMPOSÉE — c'est la boîte, le média se
  //     range dedans (réduit, ou agrandi au plus ×2). Elle est carrée parce que
  //     les memes le sont : rapport médian 1,07 sur les 121 du dossier.
  //     L'échelle de la scène s'applique par-dessus, comme pour tout le reste.
  //
  // Ici et pas dans `overlay_admin.js` : la page ET le panneau s'en servent, et
  // deux tables auraient divergé au premier widget ajouté — c'est exactement le
  // reproche auquel ce chantier répond. Une valeur imposée qui serait recopiée
  // en dur dans `overlay.html` rouvrirait la même plaie : le CSS lit ce chiffre,
  // il ne le redit pas.
  const TAILLES = {
    // Non mesurés — voir l'exception ci-dessus.
    avatar: [200, 200], bubble: [460, 170], planning: [520, 380],
    // Calculés par le serveur sur les dossiers (memes, galerie) : ces valeurs
    // ne sont que le repli de la frame qui précède sa réponse.
    image: [720, 720], meme: [400, 400], rotator: [400, 400],
    // `clip` porte l'état LECTURE (540 × 363), pas la carte d'annonce
    // (300 × 81) : c'est le plus encombrant des deux, et un repère trop petit
    // laisserait la vidéo recouvrir ce qui l'entoure.
    clip: [540, 363], clip_top: [320, 118],
    bingo: [420, 144], stats: [260, 126], talkers: [260, 113],
    hangman: [400, 130], poll: [260, 192],
    wheel: [220, 220], versus: [260, 118], gauge: [230, 39],
    counter: [275, 51], countdown: [220, 220], coinflip: [90, 90],
    dice: [170, 78], rps: [320, 137], pinned: [290, 74],
    prediction: [280, 61], quote: [300, 92], raid: [256, 100],
    wave: [180, 39],
    // Les panneaux Apex tombaient sur le défaut (400 × 260) faute d'entrée :
    // ils annonçaient donc une boîte une fois et demie trop large.
    apex_rank: [260, 133], apex_status: [260, 129], apex_stats: [260, 106],
    apex_map: [260, 86], apex_craft: [260, 118], apex_predator: [260, 106],
    apex_servers: [260, 86],
  };
  const TAILLE_DEFAUT = [400, 260];

  // Les boîtes MESURÉES par le serveur sur le dossier de memes. Elles arrivent
  // avec le layout (`tailles`) et l'emportent sur la table : celle-ci n'est plus
  // qu'un repli, pour la frame qui précède la réponse et pour le cas où le
  // dossier n'est pas mesurable.
  const MESUREES = {};

  /** Pose les boîtes calculées côté serveur. Ignore tout ce qui n'est pas un
   *  couple de nombres positifs : une valeur tordue rendrait des repères d'un
   *  pixel, ce qui est pire que l'ordre de grandeur qu'elle remplace. */
  function poserTailles(tailles) {
    if (!tailles || typeof tailles !== "object") return;
    Object.keys(tailles).forEach(function (cle) {
      const t = tailles[cle];
      if (!Array.isArray(t) || t.length !== 2) return;
      const l = Number(t[0]), h = Number(t[1]);
      if (!(l > 0) || !(h > 0)) return;
      MESUREES[cle] = [l, h];
    });
  }

  /** L'encombrement d'un élément, en pixels du canvas : mesuré si le serveur a
   *  su le dire, supposé sinon. */
  function taille(cle) {
    return MESUREES[cle] || TAILLES[cle] || TAILLE_DEFAUT;
  }

  /** Cette taille a-t-elle été MESURÉE, ou seulement supposée ?
   *
   *  Le panneau de mise en scène marque d'un pointillé les repères qui portent
   *  une estimation. Sans cette question, les widgets à média — dont la boîte
   *  est mesurée par le SERVEUR sur le dossier, ce que le navigateur ne peut
   *  pas faire — s'affichaient en pointillés comme des suppositions, et le
   *  compte annonçait moins de mesures qu'il n'y en avait vraiment.
   */
  function estMesuree(cle) {
    return !!MESUREES[cle];
  }

  /** Le rapport entre la source réelle et le canvas de référence.
   *  Sans lui, un scale de 1 ne rendrait pas la même taille relative sur une
   *  source en 1920 et sur une en 2560 : la disposition se déferait. */
  function facteurCanvas() {
    return (window.innerWidth || CANVAS_W) / CANVAS_W;
  }

  /** Le style de placement d'un élément. Pur : c'est ce qu'on teste. */
  function styleDepuisElement(el) {
    const a = ANCRAGES[el.anchor] || ANCRAGES["center"];
    // Un ancrage à droite ou en bas mesure depuis CE bord : la position est
    // donc le complément. Sans ça, un élément ancré à droite s'éloignerait du
    // bord quand on augmente son x, ce qui est l'inverse de l'attendu.
    const h = a.h === "right" ? 100 - el.x : el.x;
    const v = a.v === "bottom" ? 100 - el.y : el.y;
    const echelle = (el.scale || 1) * facteurCanvas();
    return {
      [a.h]: h + "%",
      [a.v]: v + "%",
      // `scale` AVANT `translate`, et pas l'inverse : les pourcentages d'un
      // `translate` se mesurent toujours sur la taille NON transformée. Écrit
      // `translate(-50%) scale(s)`, le décalage valait la moitié de la taille
      // à l'échelle 1 alors que l'élément en occupait `s` fois moins — un
      // widget centré à 50 % atterrissait à 30 % de large, décalé de
      // `largeur × (1 − s) / 2`. Dans cet ordre, le décalage subit la même
      // échelle que l'élément et le point d'ancrage tombe juste.
      // Invisible tant que `scale` valait 1 ET la source 1920 de large ;
      // relevé sur la surface du panneau de mise en scène, qui est étroite.
      transform: `scale(${echelle}) translate(${a.tx}, ${a.ty})`,
      transformOrigin: `${a.h === "right" ? "right" : "left"} ${a.v === "bottom" ? "bottom" : "top"}`,
    };
  }

  /** Applique un élément du modèle à un nœud. */
  function placer(noeud, el) {
    if (!noeud || !el) return;
    // Les quatre bords sont remis à `auto` avant : changer d'ancrage laissait
    // sinon l'ancien bord posé, et l'élément restait accroché des deux côtés.
    noeud.style.left = noeud.style.right = "auto";
    noeud.style.top = noeud.style.bottom = "auto";
    const style = styleDepuisElement(el);
    Object.keys(style).forEach((k) => { noeud.style[k] = style[k]; });
    noeud.style.display = el.hidden ? "none" : "";
  }

  /** Oriente la pointe de la bulle vers l'avatar, où qu'il soit.
   *
   *  L'angle est posé en variable CSS plutôt qu'en règles miroir : il y en
   *  avait quatre jeux (gauche/droite × parole/pensée), et une cinquième
   *  position n'aurait pas de règle.
   *
   *  Si l'avatar est masqué dans la scène, la pointe DISPARAÎT — elle viserait
   *  le vide, ce qui se voit immédiatement à l'écran.
   *
   *  Elle vise `#bubble` et non son conteneur : c'est LUI qui porte les
   *  pseudo-éléments de la pointe. Le conteneur ne porte que le placement.
   */
  function orienterPointe(scene) {
    const bulle = document.getElementById("bubble");
    if (!bulle || !scene || !scene.elements) return;
    const avatar = scene.elements.avatar;
    const el = scene.elements.bubble;
    if (!avatar || avatar.hidden || !el) {
      bulle.classList.add("sans-pointe");
      return;
    }
    bulle.classList.remove("sans-pointe");
    // Repère écran : y croît vers le bas, d'où l'ordre des arguments.
    const angle = Math.atan2(avatar.y - el.y, avatar.x - el.x) * 180 / Math.PI;
    bulle.style.setProperty("--angle-pointe", angle.toFixed(1) + "deg");
    // Le COIN d'où part la pointe suit l'avatar lui aussi : partie du coin
    // gauche vers un avatar à droite, elle traverserait toute la bulle.
    bulle.style.setProperty(
      "--x-pointe", avatar.x >= el.x ? "calc(100% - 24px)" : "24px");
  }

  /** Borne le texte de la bulle à la place RÉELLEMENT disponible au-dessus
   *  (ou au-dessous) d'elle.
   *
   *  Aucune valeur statique ne peut être juste : la place dépend de l'ancrage
   *  — la bulle grandit vers le haut, vers le bas, ou des deux côtés —, de la
   *  position réglée, et de l'échelle, le rendu valant la hauteur de mise en
   *  page MULTIPLIÉE par elle. Une borne en dur promettait plus que ce qui
   *  tient : la réplique était rognée par le HAUT, hors du cadre, au lieu
   *  d'être coupée par le bas. C'est le piège « borner une hauteur sans
   *  compter les marges », déjà payé ici.
   *
   *  Le repli du CSS sous-promet volontairement : couper trop tôt se voit et
   *  se règle, déborder hors de la source ne se voit pas.
   */
  function bornerBulle(el) {
    const bulle = document.getElementById("bubble");
    if (!bulle || !el) return;
    const a = ANCRAGES[el.anchor] || ANCRAGES["center"];
    // Le sens de croissance suit l'ancrage, en pourcentage de la hauteur.
    let dispo;
    if (a.ty === "-50%") dispo = 2 * Math.min(el.y, 100 - el.y);  // des deux côtés
    else if (a.v === "bottom") dispo = el.y;                      // vers le haut
    else dispo = 100 - el.y;                                      // vers le bas
    const echelle = (el.scale || 1) * facteurCanvas() || 1;
    const place = (dispo / 100) * (window.innerHeight || 1080) / echelle;
    bulle.style.setProperty("--bulle-place", Math.max(0, place).toFixed(0) + "px");
  }

  /** Place tous les éléments d'une scène, et pose l'empilement. */
  function appliquer(slug, scene) {
    if (!scene || !scene.elements) return;
    const ordre = scene.ordre || ELEMENTS;
    ELEMENTS.forEach((cle) => {
      const noeud = document.querySelector(`[data-element="${cle}"]`);
      if (!noeud) return;
      placer(noeud, scene.elements[cle]);
      // L'ordre de la liste EST l'empilement : le premier passe devant.
      const rang = ordre.indexOf(cle);
      noeud.style.zIndex = String(rang < 0 ? 1 : ordre.length - rang);
    });
    orienterPointe(scene);
    bornerBulle(scene.elements.bubble);
    document.body.dataset.scene = slug || "";
  }

  return {
    appliquer, placer, orienterPointe, bornerBulle, styleDepuisElement,
    facteurCanvas, taille, poserTailles, estMesuree,
    ELEMENTS, ANCRAGES, TAILLES, TAILLE_DEFAUT,
  };
})();
