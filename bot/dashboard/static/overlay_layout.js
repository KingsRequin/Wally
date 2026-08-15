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
      transform: `translate(${a.tx}, ${a.ty}) scale(${echelle})`,
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
    facteurCanvas, ELEMENTS, ANCRAGES,
  };
})();
