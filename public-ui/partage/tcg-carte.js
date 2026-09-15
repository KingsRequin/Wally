// public-ui/partage/tcg-carte.js — une carte de héros du TCG
//
// Port de la maquette Claude Design `Carte Hero.dc.html` (reprise du
// 2026-09-15 : décor allégé, dépli et repli sur une seule horloge, bordure
// dorée, couche lointaine, ultime au clic). Ce module RENDU du DOM et ne
// calcule AUCUNE règle : il reçoit un objet décrivant une carte et l'affiche.
// Le moteur du jeu vit côté serveur, en Python — une règle dupliquée en
// JavaScript est une porte de triche ouverte et un second jeu à maintenir.
//
// Utilisé par `/wallycard/bibliotheque` (la collection), `/demo/carte-azrael`
// et l'overlay OBS. Un seul rendu pour les trois : deux copies divergeraient
// au premier réglage.
//
// 🚨 La tenue en performance tient à deux choses. Les défaire, c'est faire
// ramer une grille de cartes :
//
//   1. **La 3D n'existe que sous le curseur.** `set3d()` pose `perspective` et
//      `preserve-3d` à l'entrée, `aplatir()` les retire une fois le repli fini.
//      Au repos une carte est un APLAT : un calque GPU au lieu de neuf.
//   2. **Une seule boucle `requestAnimationFrame` pour toute la page**,
//      plafonnée à 30 images/s sauf quand une carte se déplie ou se replie.

import { h } from './dom.js';

// La feuille de la carte. Elle porte aussi le `@font-face` d'Archivo Black,
// VENDORÉE : un overlay OBS qui dépend d'une requête vers Google au démarrage
// afficherait son premier titre dans la police de repli si le réseau traîne.
const FEUILLE = '/partage/tcg-carte.css';

/** L'AVIF et son repli WebP, depuis un chemin SANS extension.
 *
 * Les deux formats sont servis ensemble (`<picture>` pour les images,
 * `image-set()` pour le fond) : l'AVIF pèse deux fois et demie moins qu'un
 * WebP de même qualité, mais Safari ne le lit que depuis 16.4.
 *
 * 🚨 C'est le SEUL endroit qui sait comment une illustration se sert : le site
 * et l'overlay passent tous deux des chemins bruts. Une paire déjà construite
 * passe telle quelle.
 */
function paire(base) {
  if (base && typeof base === 'object') return base;
  // ⚠️ Le chemin porte une empreinte (`/assets/x?v=a1b2c3d4`) : l'extension
  // s'insère AVANT le `?`.
  const [chemin, requete] = String(base).split('?');
  const suffixe = requete ? `?${requete}` : '';
  return { avif: `${chemin}.avif${suffixe}`, webp: `${chemin}.webp${suffixe}` };
}

/** Charge la feuille de la carte. Rend de quoi la retirer.
 *
 * Appelé par la page, pas par la carte : une grille ne pose le `<link>`
 * qu'une fois.
 */
export function monterStylesCarte() {
  if (document.head.querySelector(`link[href="${FEUILLE}"]`)) return () => {};
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);
  return () => lien.remove();
}

// ── La boucle de la page ──────────────────────────────────────────────────

/** Une seule boucle rAF pour la page, plafonnée à 30 images/s — SAUF quand un
 * abonné demande le plein régime. Le dépli, le repli et l'inclinaison passent
 * tous par cette horloge : à 30 images/s ils se verraient par paliers de
 * 33 ms. Il n'y a qu'une carte survolée à la fois, le reste garde le plafond.
 */
const BOUCLE = (() => {
  const abonnes = new Set();
  const vifs = new Set();
  let raf = 0;
  let derniere = 0;
  const image = (maintenant) => {
    raf = abonnes.size ? requestAnimationFrame(image) : 0;
    if (document.hidden || (!vifs.size && maintenant - derniere < 31)) return;
    derniere = maintenant;
    abonnes.forEach((fn) => fn(maintenant));
  };
  return {
    // 🚨 On REPLANIFIE toujours, au lieu de faire confiance à l'id mémorisé.
    // Une frame perdue une seule fois (onglet bridé, capture d'écran) laissait
    // `raf` non nul alors que plus rien n'était programmé : la boucle était
    // morte pour le reste de la vie de la page, sans une erreur.
    ajouter(fn, vif) {
      abonnes.add(fn);
      if (vif) vifs.add(fn);
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(image);
    },
    retirer(fn) { abonnes.delete(fn); vifs.delete(fn); },
  };
})();

/** Abonne `fn` à la boucle de la page. Rend de quoi la désabonner.
 *
 * Exposé pour la chorégraphie de l'overlay, qui doit avancer image par image
 * sans ouvrir un second `requestAnimationFrame`.
 */
export function abonnerAnimation(fn) {
  BOUCLE.ajouter(fn);
  return () => BOUCLE.retirer(fn);
}

// ── Le vitrage gravé ──────────────────────────────────────────────────────
// Le chatoiement seul rend des BANDES : joli, mais lisse. Une vraie carte
// holographique porte une gravure — un pavage de cellules, et dans chacune
// des anneaux concentriques qui parcourent l'arc-en-ciel. La tuile est une
// IMAGE COULEUR (un masque monochrome ne peut que doser une irisation déjà
// là), cuite UNE fois pour la page et rangée dans `--chero-voronoi` sur
// <html> : la calculer par carte referait la même image à chaque fois.
const VORONOI_TUILE = 256;
const VORONOI_COTE = 12;
const VORONOI_ANNEAUX = 2.5;
let voronoiCuit = false;

function cuireVoronoi() {
  if (voronoiCuit) return;
  voronoiCuit = true;
  const differer = window.requestIdleCallback || ((f) => setTimeout(f, 0));
  differer(() => {
    const T = VORONOI_TUILE;
    const cv = document.createElement('canvas');
    cv.width = T;
    cv.height = T;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    // LCG à graine fixe : même gravure à chaque chargement.
    let graine = 0x9e3779b9;
    const alea = () => {
      graine = (graine * 1664525 + 1013904223) >>> 0;
      return graine / 4294967296;
    };
    // Grille SECOUÉE et non tirage libre : au hasard pur les germes se
    // groupent et le pavage alterne cellules énormes et échardes.
    const pas = T / VORONOI_COTE;
    const gx = [];
    const gy = [];
    const decal = [];
    const gain = [];
    for (let j = 0; j < VORONOI_COTE; j++) {
      for (let i = 0; i < VORONOI_COTE; i++) {
        gx.push((i + 0.18 + alea() * 0.64) * pas);
        gy.push((j + 0.18 + alea() * 0.64) * pas);
        decal.push(alea());
        gain.push(0.55 + alea() * 0.45);
      }
    }
    const img = ctx.createImageData(T, T);
    const d = img.data;
    const joint = pas * 0.22;
    const rayon = pas * 0.9;
    for (let y = 0; y < T; y++) {
      for (let x = 0; x < T; x++) {
        let f1 = Infinity;
        let f2 = Infinity;
        let cel = 0;
        for (let k = 0; k < gx.length; k++) {
          // Distances prises sur un TORE : sans ça la répétition dessine une
          // grille de joints rectilignes — on lit un carrelage.
          let dx = Math.abs(x - gx[k]);
          if (dx > T / 2) dx = T - dx;
          let dy = Math.abs(y - gy[k]);
          if (dy > T / 2) dy = T - dy;
          const dd = dx * dx + dy * dy;
          if (dd < f1) { f2 = f1; f1 = dd; cel = k; } else if (dd < f2) { f2 = dd; }
        }
        // F2 − F1 s'annule sur l'arête et croît vers le cœur : c'est à la fois
        // la gravure et la coordonnée des anneaux, sans un seul polygone.
        const e = Math.sqrt(f2) - Math.sqrt(f1);
        const b = Math.min(1, e / joint);
        const eclat = b * b * (3 - 2 * b) * gain[cel];
        let t = (e / rayon) * VORONOI_ANNEAUX + decal[cel];
        t -= Math.floor(t);
        const hh = t * 6;
        const o = (y * T + x) * 4;
        d[o] = Math.round(Math.max(0, Math.min(1, Math.abs(hh - 3) - 1)) * eclat * 255);
        d[o + 1] = Math.round(Math.max(0, Math.min(1, 2 - Math.abs(hh - 2))) * eclat * 255);
        d[o + 2] = Math.round(Math.max(0, Math.min(1, 2 - Math.abs(hh - 4))) * eclat * 255);
        d[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    // Un BLOB et non un data-URI : en couleurs pures l'image compresse mal,
    // son data-URI pesait 232 ko posés dans une custom property.
    cv.toBlob((blob) => {
      if (!blob) return;
      document.documentElement.style.setProperty(
        '--chero-voronoi', `url("${URL.createObjectURL(blob)}")`);
    }, 'image/png');
    // 🚨 La tuile VIVE de la bande des bords, avec son éclat CUIT DEDANS au
    // lieu d'un `filter` CSS sur la couche. Un descendant filtré d'un contexte
    // preserve-3d est aplati dans un plan qui ne tourne pas avec la carte :
    // penchée, ce plan COUPE celui du héros, et la bande passait devant lui
    // d'un côté, derrière de l'autre — la bordure qui traversait les
    // nageoires du requin.
    const vif = document.createElement('canvas');
    vif.width = T;
    vif.height = T;
    const ctxVif = vif.getContext('2d');
    if (!ctxVif) return;
    ctxVif.filter = 'brightness(2.2) contrast(1.1) saturate(1.2)';
    ctxVif.drawImage(cv, 0, 0);
    vif.toBlob((blob) => {
      if (!blob) return;
      document.documentElement.style.setProperty(
        '--chero-voronoi-vif', `url("${URL.createObjectURL(blob)}")`);
    }, 'image/png');
  });
}

// ── Les réglages de mouvement ─────────────────────────────────────────────

// Le chatoiement : la couche est SOUS le héros et dans le fond, elle n'a pas à
// se retenir pour préserver le personnage.
const OPACITE_HOLO = 0.8;
// Le VERNIS, bien plus bas : il passe sur la carte ENTIÈRE, texte compris, et
// son travail est de faire croire au plastique, pas de se voir.
const OPACITE_VERNIS = 0.34;
// Le REPLI, plus court que le dépli : une carte qu'on relâche retombe, elle ne
// se range pas. Animé par la même horloge que l'ouverture — le héros pliait
// d'un coup pendant que le reste descendait, et c'est ce décrochage qu'on
// voyait en quittant la carte.
const FERME = 440;
// 🚨 PERSPECTIVE LONGUE, et c'est une question de NETTETÉ. Une couche poussée
// en translateZ est tramée à sa taille de mise en page puis ÉTIRÉE par la
// projection : à perspective 1100, le héros (z 80) était étiré de 8 %. À 4000
// le même z ne grossit plus que de 2 %. La profondeur perdue est RENDUE par
// `COMP`, en scale 2D, que Chromium retrame depuis l'image source.
const PERSP = 4000;
// 🚨 Sous une perspective, le compositeur de Chromium APPROXIME l'échelle de
// trame d'une couche puis l'ARRONDIT à l'entier (cc/layers/layer_impl.cc,
// GetIdealContentsScale). Tout ce qui s'affiche entre 1,0× et 1,5× est donc
// tramé à 1× puis étiré. On met en page la carte à ZOOM× et on la réduit
// d'autant : en survol chaque couche s'affiche à au plus ~0,97× de sa trame.
const ZOOM = 1.3;
const REF = 1100; // la perspective d'origine
const persp = (z) => PERSP / (PERSP - z);
const COMP = (z) => (REF / (REF - z)) / persp(z); // ce que le scale doit rendre

// Contour du héros déplié pour les cartes à bordure dorée : un PNG découpé ne
// prend pas de `border`, on empile des drop-shadows. L'or ne fait qu'un quart
// du tour, le reste passe par le cyan et le magenta — l'écart de teinte dit
// « holo ». Quatre directions et pas huit : au-delà, le survol tombe sous les
// 60 images par seconde.
const CONTOUR_DIRS = ['0 -2px', '2px 0', '0 2px', '-2px 0'];
const CONTOUR_TEINTES = ['#fff6e2', '#8fe9ff', '#ff8fd0', '#e1a947'];
const CONTOURS = Array.from({ length: 4 }, (_, k) => CONTOUR_DIRS
  .map((o, i) => `drop-shadow(${o} 0 ${CONTOUR_TEINTES[(i + k) % 4]})`)
  .join(' ') + ' drop-shadow(0 14px 18px rgba(0,0,0,.5))');
const CONTOUR_SIMPLE = 'drop-shadow(0 14px 18px rgba(0,0,0,.5))';

/** L'avancement propre d'une couche à la profondeur `z0`, pour un dépli `f`.
 *
 * La CASCADE : une couche profonde part un peu après une couche proche, sinon
 * la carte se lève en bloc.
 */
function cascade(z0, f) {
  const d = 0.15 * Math.min(1, z0 / 130);
  return Math.max(0, Math.min(1, (f - d) / (1 - d)));
}

/** Les millisecondes d'une durée CSS (« .85s », « 450ms »). */
function enMs(valeur, defaut) {
  const v = String(valeur || '').trim();
  if (v.endsWith('ms')) return parseFloat(v) || defaut;
  if (v.endsWith('s')) return (parseFloat(v) || 0) * 1000 || defaut;
  return defaut;
}

const SOBRE = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const TACTILE = () => window.matchMedia('(hover: none)').matches;

// ── Le DOM ────────────────────────────────────────────────────────────────

const DEFAUTS = {
  nom: 'AZRAËL',
  classe: 'ARCHANGE',
  ultime: 'REWORK',
  description: '',
  ambiance: '',
  cout: 0, atk: 0, pv: 0, aura: 0,
  accent: '#e1a947',
  // `hero` et `fond` n'ont PAS de défaut : une carte sans illustration
  // n'existe pas (cf. `bot/core/tcg_cartes.py`), et un défaut vide donnerait
  // une carte noire au lieu d'une erreur qu'on voit passer.
  heroCote: '-14%', heroHaut: '4%', heroEchelle: 1.12,
  // Le calque de SURVOL peut porter une autre illustration, avec son propre
  // cadrage. À `null`, il reprend le visuel et le cadrage du repos.
  hero3d: null, hero3dCote: null, hero3dHaut: null,
  avantPlan: null, avantPlanLargeur: '86%', avantPlanBas: '-6%',
  avantPlanSurvol: false,
  ovni: null, ovniCote: '50%', ovniHaut: '-6%', ovniLargeur: '88%', ovniOpacite: 0.85,
  heroUlt: null, hero3dUlt: null, fondUlt: null,
  heroUltCote: null, heroUltHaut: null, hero3dUltCote: null, hero3dUltHaut: null,
  heroUltEchelle: null,
  piedsLigne: null, piedsMarge: null,
  holographique: false,
  holoZone: 'surface',
  holoForce: 1,
  bordureDoree: false,
  faveur: false,
  // Le grade (S, A ou B), tel que le sert `bot/core/tcg_cartes.py`. `null` et
  // pas B par défaut : une carte non notée n'est pas une carte faible.
  grade: null,
  intensite: 1, parallaxe: 1,
  reflet: true, debordement: true, selectionnee: false,
};

const BORDS = ['haut', 'bas', 'gauche', 'droite'];

// La sentinelle que porte `tcg/cartes.yaml` partout où rien n'est décidé.
// `tests/test_tcg_cartes.py` vérifie que la graphie d'ici est celle du YAML.
export const INDEFINI = 'INDÉFINI';

// ⚖️ Le grade REMPLACE la rareté, retirée le 2026-09-14. « GRADE ? »
// s'affiche, il ne se cache pas : un cartouche absent ferait passer la carte
// pour une carte sans grade plutôt que pour une carte pas encore notée.
function libelleGrade(grade) {
  return grade ? `GRADE ${grade}` : 'GRADE ?';
}

/** Construit une carte de héros. Rend `{ boite, detruire, ouvrir, fermer, incliner }`.
 *
 * `boite` est le nœud à insérer (il réserve la taille de la carte, échelle
 * comprise) ; `detruire()` doit être appelé au démontage de la page, sinon la
 * carte reste abonnée à la boucle.
 */
export function carteHero(carte, options = {}) {
  const c = { ...DEFAUTS, ...carte };
  // `interactif` faux : aucun écouteur de pointeur, la carte est pilotée par
  // du code (l'overlay OBS, ou la page au gyroscope).
  // `depli` et `etape` rallongent le dépliage sur l'overlay, où il est le
  // spectacle. `gainReflet` y monte l'éclat des bords, la carte fait 680 px.
  const { interactif = true, gainReflet = 1, depli = null, etape = null } = options;
  // Le lissage du saut d'entrée couvre tout le dépliage, échelonnement
  // compris : dépli .45s + 2 × étape .05s + marge = 610 ms sous le curseur.
  const LISSAGE = enMs(depli, 450) + enMs(etape, 50) * 2 + 60;
  const holoSurface = c.holographique && c.holoZone !== 'bords';
  const holoBords = c.holographique && c.holoZone === 'bords';
  // Le nom en foil seulement sur les cartes de faveur qui portent déjà le
  // vitrage EN SURFACE : sur la variante `bords`, l'irisation est confinée au
  // liseré par choix, et un titre irisé la ferait déborder.
  const nomFoil = holoSurface && c.faveur;
  if (c.holographique) cuireVoronoi();

  // L'état de l'ultime : `vrai` quand la carte montre son second visuel.
  // `versionUltime` la fait NAÎTRE dessus — c'est Wally qui montre « Lilio en
  // slip » sur l'overlay, où personne ne peut cliquer. ⚠️ Pas `ultime` : ce
  // champ-là porte déjà le NOM de l'Ultime (« REWORK »).
  let ult = Boolean(c.versionUltime && c.heroUlt);
  const visuel = () => ({
    hero: (ult && c.heroUlt) || c.hero,
    heroCote: (ult ? c.heroUltCote : null) ?? c.heroCote,
    heroHaut: (ult ? c.heroUltHaut : null) ?? c.heroHaut,
    heroEchelle: (ult ? c.heroUltEchelle : null) ?? c.heroEchelle,
    hero3d: (ult && (c.hero3dUlt || c.heroUlt)) || c.hero3d || c.hero,
    hero3dCote: (ult ? (c.hero3dUltCote || c.heroUltCote) : null)
      || c.hero3dCote || c.heroCote,
    hero3dHaut: (ult ? (c.hero3dUltHaut || c.heroUltHaut) : null)
      || c.hero3dHaut || c.heroHaut,
    fond: (ult && c.fondUlt) || c.fond,
  });

  // 🚨 En mode piloté (l'overlay), les illustrations passent DEVANT tout le
  // reste de la file : l'overlay précharge le jeu entier au boot, et la carte
  // demandée partait en FIN de file (mesuré le 2026-09-08 à 700 kbit/s).
  const priorite = interactif ? null : 'high';
  // 🚨 `lazy` seulement quand un humain pointe la carte. Piloté par script,
  // une image `lazy` dont le nœud n'est pas encore dans le document ne charge
  // JAMAIS, et la chorégraphie jouait la carte sans ses illustrations.
  const chargement = interactif ? 'lazy' : 'eager';
  const img = (source, alt, charge) => {
    const { avif, webp } = paire(source);
    return h('picture', {},
      h('source', { srcset: avif, type: 'image/avif' }),
      h('img', { src: webp, alt, loading: charge, decoding: 'async', fetchPriority: priorite }),
    );
  };
  const changerImage = (conteneur, source) => {
    const { avif, webp } = paire(source);
    conteneur.querySelector('source').srcset = avif;
    conteneur.querySelector('img').src = webp;
  };

  const l1 = h('div', { class: 'chero-l1' });
  // La nappe d'ovnis vit DANS le décor : derrière le héros, sous le
  // vignettage du bas, sinon les soucoupes flottent devant la scène.
  const ovni = c.ovni ? h('div', {}, img(c.ovni, '', 'eager')) : null;
  const holo = c.holographique
    ? h('div', { class: `chero-holo${holoBords ? ' chero-holo--bords' : ''}` })
    : null;
  const fond = h('div', { class: 'chero-fond' },
    l1,
    ovni ? h('div', { class: 'chero-ovni' }, ovni) : null,
    h('div', { class: 'chero-trame' }),
    h('div', { class: 'chero-vignette' }),
    holoSurface ? holo : null);

  const visuelDepart = visuel();
  const clip = h('div', { class: 'chero-clip' }, img(visuelDepart.hero, c.nom, chargement));
  // L'avant-plan (les pieds de Claker) : la couche qui passe DEVANT le héros.
  const apClip = c.avantPlan
    ? h('div', { class: 'chero-ap-clip' }, img(c.avantPlan, '', chargement))
    : null;
  // 🚨 `avantPlanSurvol` : l'avant-plan n'existe QUE dépliée. Posé ici, avant
  // l'insertion, pour ne pas clignoter.
  const apRepos = c.avantPlanSurvol ? '0' : '1';
  if (apClip) apClip.style.opacity = apRepos;

  // Le flash blanc de l'ultime : l'échange des visuels se fait à son pic.
  const flash = h('div', { class: 'chero-flash' });

  const bords = {};
  const reflet = c.reflet
    ? h('div', { class: 'chero-reflet' }, ...BORDS.map((nom) => {
      const el = h('div', { 'data-bord': nom });
      bords[nom] = el;
      return el;
    }))
    : null;
  const or = c.bordureDoree ? h('div', { class: 'chero-or' }) : null;
  const bord = h('div', { class: 'chero-bord', 'data-z': '44' },
    or,
    reflet,
    holoBords ? holo : null,
    c.selectionnee ? h('div', { class: 'chero-selection' }) : null,
  );

  // 🚨 Les calques LIBRES (soucoupe, héros, avant-plan) viennent APRÈS le
  // cadre dans le document, et ce n'est pas cosmétique : un descendant filtré
  // d'un contexte preserve-3d ne participe plus au TRI par profondeur dans
  // Chromium — c'est l'ordre du document qui décide. Posés avant, ils
  // passaient sous la bande de vitrage.
  //
  // Le jumeau LIBRE de la nappe vit à 52 — devant le liseré (44), derrière le
  // héros (80) : les soucoupes débordent du cadre mais restent dans le ciel.
  const ovniLibre = c.ovni
    ? h('div', { class: 'chero-ovni-libre', 'aria-hidden': 'true' }, img(c.ovni, '', 'eager'))
    : null;
  // `eager` sur le calque de survol : quand c'est une SECONDE illustration, la
  // charger paresseusement ferait apparaître un trou à l'ouverture.
  const libre = h('div', { class: 'chero-libre', 'aria-hidden': 'true' },
    img(visuelDepart.hero3d, '', 'eager'));
  const apLibre = c.avantPlan
    ? h('div', { class: 'chero-ap-libre', 'aria-hidden': 'true' }, img(c.avantPlan, '', 'eager'))
    : null;

  const cout = h('div', { class: 'chero-cout', 'data-z': '130', 'data-grossit': '1.04' },
    h('span', { class: 'chero-cout-n', text: String(c.cout) }),
    h('span', { class: 'chero-cout-lbl', text: 'ULTIME' }),
  );
  const cartouche = h('div', { class: 'chero-grade', 'data-z': '130', 'data-grossit': '1.04' },
    h('span', { text: libelleGrade(c.grade) }));

  const nom = h('span', { class: `chero-nom${nomFoil ? ' chero-nom--foil' : ''}`, text: c.nom });
  const nomBoite = h('div', { class: 'chero-nom-boite', 'data-z': '60', 'data-grossit': '1.02' }, nom);
  const fiche = h('div', { class: 'chero-fiche', 'data-z': '60' },
    // 🚨 Une carte pas encore écrite le dit UNE fois : répéter une absence ne
    // la rend pas plus claire, elle la rend illisible.
    h('div', { class: 'chero-fiche-top' },
      h('span', { text: c.classe }),
      c.ultime === INDEFINI ? null : h('span', { class: 'chero-ult', text: `ULT · ${c.ultime}` }),
    ),
    c.description === INDEFINI
      ? h('p', { class: 'chero-desc chero-desc--vide', text: 'Règles et chiffres pas encore écrits.' })
      : h('p', { class: 'chero-desc', text: c.description }),
    // L'ambiance survit à part : Claker en a une alors que sa règle n'existe
    // pas encore.
    c.ambiance === INDEFINI ? null : h('p', { class: 'chero-ambiance', text: c.ambiance }),
    // 🚨 Une stat à ZÉRO n'est pas une petite stat : c'est une stat qui n'est
    // pas décidée. Peinte en rouge vif comme un vrai 9, elle prétendrait être
    // une valeur de jeu.
    h('div', { class: 'chero-stats' },
      ...[['atk', 'ATK', c.atk], ['pv', 'PV', c.pv], ['aura', 'AURA', c.aura]]
        .map(([cle, libelle, valeur]) => h('span', {
          class: `chero-stat chero-stat-${cle}${valeur ? '' : ' chero-stat--vide'}`,
          text: `${libelle} ${valeur}`,
        })),
    ),
  );
  const bas = h('div', { class: 'chero-bas', 'data-z': '40' }, nomBoite, fiche);

  const vernis = h('div', { class: 'chero-vernis', 'data-z': '200', 'data-net': '1', 'aria-hidden': 'true' });

  const plateau = h('div', { class: 'chero-carte' },
    fond,
    h('div', { class: 'chero-cadrage' }, clip),
    apClip ? h('div', { class: 'chero-cadrage' }, apClip) : null,
    flash,
    bord,
    ovniLibre,
    libre,
    apLibre,
    cout,
    cartouche,
    bas,
    vernis,
  );
  // La boîte zoomée entre le plateau (perspective) et la carte (rotation).
  const zoom = h('div', { class: 'chero-zoom' }, plateau);

  const racine = h('div', {
    class: `chero${c.faveur ? ' chero--faveur' : ''}`,
    'data-grade': c.grade || 'aucun',
  },
  h('div', { class: 'chero-zone', 'aria-hidden': 'true' }),
  h('div', { class: 'chero-ombre' }),
  zoom);
  racine.style.cssText = `--chero-acc:${c.accent}`
    + `;--chero-ap-largeur:${c.avantPlanLargeur}`
    + `;--chero-ap-bas:${c.avantPlanBas}`
    + `;--chero-ovni-cote:${c.ovniCote}`
    + `;--chero-ovni-haut:${c.ovniHaut}`
    + `;--chero-ovni-largeur:${c.ovniLargeur}`
    + `;--chero-ovni-opacite:${c.ovniOpacite}`
    + `;--chero-holo-force:${c.holoForce}`;

  /** Pose les sources et les cadrages du visuel courant (repos ou ultime). */
  const appliquerVisuel = () => {
    const v = visuel();
    racine.style.setProperty('--chero-cote', v.heroCote);
    racine.style.setProperty('--chero-haut', v.heroHaut);
    racine.style.setProperty('--chero-3d-cote', v.hero3dCote);
    racine.style.setProperty('--chero-3d-haut', v.hero3dHaut);
    // Le fond est un `background-image`, il n'a pas de `<picture>`. Les deux
    // affectations SONT le repli : un navigateur qui ne comprend pas
    // `image-set()` rejette la seconde et garde le WebP.
    const f = paire(v.fond);
    l1.style.backgroundImage = `url('${f.webp}')`;
    l1.style.backgroundImage = `image-set(url('${f.avif}') type("image/avif"),`
      + ` url('${f.webp}') type("image/webp"))`;
  };
  appliquerVisuel();

  const boite = h('div', { class: 'chero-boite' }, racine);

  // ── Le comportement ─────────────────────────────────────────────────────
  const zEls = [bord, cout, cartouche, bas, nomBoite, fiche, vernis];
  let survol = false;
  let dernierNx = 0;
  let dernierNy = 0;
  let ouvertA = 0;
  let fermeA = 0;
  let avSortie = 1;
  let depliage = null;
  let repli = null;
  let suivi = null;
  let minuteurFin = 0;
  let tCard = '';
  let tLibre = '';
  let cleDecoupe = '';
  let decoupeFixe = false;
  let contourK = 0;
  let zoomK = 0;
  let basculeEnCours = false;

  // 🚨 La mise en page agrandie ne sert QU'À DPR 1. Au-delà, le compositeur
  // trame déjà à 2× : payer 1,3× de surface par-dessus ne gagne pas un pixel.
  // Relu au redimensionnement, parce que zoomer le navigateur change le DPR.
  const majZoom = () => {
    const z = (window.devicePixelRatio || 1) >= 1.5 ? 1 : ZOOM;
    if (zoomK === z) return;
    zoomK = z;
    zoom.style.zoom = z;
    zoom.style.transform = z === 1 ? 'none' : `scale(${(1 / z).toFixed(5)})`;
  };
  majZoom();

  const imgLibre = libre.querySelector('img');
  // Le contour métal reste sous le liseré holo : c'est lui qui donne l'or là
  // où l'irisation passe dans ses tons sombres. Sans `will-change`, Chromium
  // refait la passe de filtre à chaque frame du parallaxe.
  imgLibre.style.filter = c.bordureDoree ? CONTOURS[0] : '';
  imgLibre.style.willChange = c.bordureDoree ? 'filter' : '';

  // Le filtre du contour n'est plus coupé en survol : avec la mise en page à
  // ZOOM×, la couche filtrée n'est plus étirée, elle est réduite.
  const netteteHero = () => {
    imgLibre.style.width = '100%';
    imgLibre.style.transform = '';
    imgLibre.style.transformOrigin = '';
    if (!survol && !c.bordureDoree) imgLibre.style.filter = CONTOUR_SIMPLE;
    imgLibre.style.backfaceVisibility = 'hidden';
    libre.style.willChange = '';
    libre.style.backfaceVisibility = 'hidden';
  };

  // Un cran de teinte par quart de tour du pointeur : l'irisation glisse quand
  // on penche la carte, sans réécrire le filtre trente fois par seconde.
  const majContour = (nx, ny) => {
    if (!c.bordureDoree) return;
    const k = ((Math.round(Math.atan2(ny, nx) / (Math.PI / 2)) % 4) + 4) % 4;
    if (k === contourK) return;
    contourK = k;
    imgLibre.style.filter = CONTOURS[k];
  };

  /** La découpe du héros libre : il sort par le HAUT et les CÔTÉS, jamais par
   * le bas. Sous la LIGNE, il est borné à l'intérieur du cadre.
   *
   * 🚨 La conversion ne peut PAS être une formule fermée : un plan soulevé à
   * z = 80 ne se projette pas comme le plan z = 0 où vit le cadre, donc une
   * borne écrite à la main glissait avec l'inclinaison. On inverse la VRAIE
   * chaîne : les coins du cadre sont envoyés dans l'espace post-carte, ramenés
   * dans l'espace local du calque, et on cherche où le rayon parti de l'œil
   * traverse le plan du calque.
   */
  const ajusterPieds = () => {
    if (typeof DOMMatrix === 'undefined') return;
    // ⚠️ La borne latérale n'est PAS le comportement par défaut : ailleurs, le
    // héros qui sort du cadre par les côtés est tout l'effet. Sans marge, un
    // clip fixe écrit une fois — il retombe sous le héros pour laisser passer
    // son ombre portée sur la fiche.
    if (c.piedsMarge == null) {
      if (!decoupeFixe) { decoupeFixe = true; libre.style.clipPath = 'inset(-60% -30% -14% -30%)'; }
      return;
    }
    // Ne se recalcule que si la carte ou le héros ont bougé.
    const cle = `${tCard}|${tLibre}`;
    if (cle === cleDecoupe) return;
    cleDecoupe = cle;
    const W = libre.offsetWidth;
    const H = libre.offsetHeight;
    if (!W || !H) return;
    const cw = plateau.offsetWidth;
    const ch = plateau.offsetHeight;
    const cx = cw / 2;
    const cy = ch / 2;
    // ⚠️ Deux horloges, deux lectures. La carte et le liseré ont des
    // transitions CSS : leur état vrai ne peut être que RELU. Le calque libre
    // n'en a pas — il est déjà à la cible mémorisée.
    const tc = getComputedStyle(plateau).transform;
    let C;
    let F;
    try {
      C = new DOMMatrix(tc === 'none' ? '' : tc);
      F = new DOMMatrix(tLibre || '');
    } catch (e) {
      console.warn('TCG : découpe des pieds impossible', e);
      return;
    }
    const versCarte = new DOMMatrix().translate(cx, cy).multiply(C).translate(-cx, -cy);
    const A = new DOMMatrix(versCarte.toString())
      .translate(libre.offsetLeft, libre.offsetTop)
      .translate(W / 2, H).multiply(F).translate(-W / 2, -H);
    let Ainv;
    try {
      Ainv = A.inverse();
    } catch (e) {
      console.warn('TCG : découpe des pieds non inversible', e);
      return;
    }
    const oeil = Ainv.transformPoint(new DOMPoint(cx, cy, PERSP));
    // 🚨 Le cadre n'est PAS à z = 0 : le liseré est lui aussi soulevé (z 44)
    // quand la carte se déplie.
    const tb = getComputedStyle(bord).transform;
    let B;
    try {
      B = new DOMMatrix(tb === 'none' ? '' : tb);
    } catch (e) {
      B = new DOMMatrix();
    }
    const versBord = new DOMMatrix().translate(cx, cy).multiply(B).translate(-cx, -cy);
    const local = (X, Y) => {
      const q = versCarte.multiply(versBord).transformPoint(new DOMPoint(X, Y, 0));
      const p = Ainv.transformPoint(q);
      const dz = oeil.z - p.z;
      if (Math.abs(dz) < 1e-6) return { x: p.x, y: p.y };
      const t = oeil.z / dz;
      return { x: oeil.x + (p.x - oeil.x) * t, y: oeil.y + (p.y - oeil.y) * t };
    };
    const m = c.piedsMarge;
    const yl = (parseFloat(c.piedsLigne ?? 100) / 100) * ch;
    const lg = local(m, yl);
    const ld = local(cw - m, yl);
    const bg = local(m, ch - m);
    const bd = local(cw - m, ch - m);
    const gl = -0.3 * W;
    const dl = 1.3 * W;
    const hl = -0.6 * H;
    // 🚨 La ligne est OBLIQUE dans l'espace du calque dès que la carte penche :
    // deux seuils horizontaux laissaient un côté sans borne juste sous elle.
    const pente = Math.abs(ld.x - lg.x) < 1e-6 ? 0 : (ld.y - lg.y) / (ld.x - lg.x);
    const yA = (x) => lg.y + pente * (x - lg.x);
    const pt = (x, y) => `${x.toFixed(1)}px ${y.toFixed(1)}px`;
    libre.style.clipPath = `polygon(${[
      pt(gl, hl), pt(dl, hl), pt(dl, yA(dl)), pt(ld.x, ld.y), pt(bd.x, bd.y),
      pt(bg.x, bg.y), pt(lg.x, lg.y), pt(gl, yA(gl)),
    ].join(',')})`;
  };

  /** Le `transform` d'une couche qui monte en Z, à l'avancement `f`.
   *
   * 🚨 Les couches de TEXTE ne compensent PLUS l'agrandissement de la
   * perspective : compensées, elles RÉTRÉCISSAIENT sous l'inclinaison au lieu
   * de se lever. `data-net` ne sert plus qu'au VERNIS, qui doit garder la
   * taille du cadre.
   */
  const zTransform = (el, f) => {
    const z0 = Number(el.dataset.z) || 0;
    const p = cascade(z0, f);
    const z = z0 * p;
    const tz = `translateZ(${z.toFixed(1)}px)`;
    if (el.dataset.net === '1') return `${tz} scale(${((PERSP - z) / PERSP).toFixed(5)})`;
    // `data-grossit` s'AJOUTE à la profondeur, donc les deux se multiplient.
    const grossit = 1 + ((Number(el.dataset.grossit) || 1) - 1) * p;
    return `${tz} scale(${(grossit * COMP(z)).toFixed(5)})`;
  };

  /** L'avancement du dépliage, de 0 à 1. Il monte au dépli, redescend au
   * repli, et TOUT s'y accroche — inclinaison, profondeurs, héros. */
  const ouverture = () => {
    // Le repli repart de l'avancement atteint, pas de 1.
    if (fermeA) {
      const t = Math.min(1, (performance.now() - fermeA) / FERME);
      return avSortie * (1 - t * t * (3 - 2 * t));
    }
    if (!ouvertA) return survol ? 1 : 0;
    const t = Math.min(1, (performance.now() - ouvertA) / LISSAGE);
    return 1 - (1 - t) ** 3;
  };

  /** Incline la carte. `nx` et `ny` ∈ [−0.5, +0.5], 0,0 au centre.
   *
   * ⚠️ Un seul écrivain sur le `transform` du plateau : deux ne se cumulent
   * pas, ils se remplacent. L'overlay et la page au gyroscope appellent ici
   * directement.
   */
  const incliner = (nx, ny) => {
    dernierNx = nx;
    dernierNy = ny;
    const max = 15 * c.intensite;
    const av = ouverture();
    const f = fermeA ? av / (avSortie || 1) : av;
    const tiltX = nx * max * 2 * f;
    const tiltY = ny * max * 2 * f;
    // 🚨 Le transform est MÉMORISÉ, pas relu : la carte porte une transition
    // de .16s, et la découpe des pieds se calait sur l'état intermédiaire.
    tCard = `rotateX(${(-tiltY).toFixed(2)}deg) rotateY(${tiltX.toFixed(2)}deg) scale(${(1 + 0.04 * f).toFixed(4)})`;
    plateau.style.transform = tCard;
    const p = c.parallaxe * 1.4;
    const tx = tiltX * p;
    const ty = tiltY * p;
    // Fond fixe : seuls le héros, l'avant-plan et les habillages prennent la
    // parallaxe.
    l1.style.transform = 'scale(1.06)';
    // Une valeur identique n'est pas réécrite : la trame du texte ne se
    // refait plus pendant le suivi du pointeur.
    zEls.forEach((el) => {
      const t = zTransform(el, av);
      if (el.__t === t) return;
      el.__t = t;
      el.style.transform = t;
    });
    // 🚨 L'ordre des plans à CHAQUE image : liseré < ovnis < héros <
    // avant-plan ≤ fiche. Le design disait les profondeurs « proportionnelles
    // sur une horloge unique », mais la cascade retarde la colonne du bas
    // (40 + 60) : pendant les ~100 premières ms, le héros à 80·f passait
    // DEVANT les stats. Les calques libres sont donc plafonnés à la profondeur
    // réelle de la fiche — arbitrage de l'owner du 2026-09-15. Au bout du
    // dépli le plafond (100) ne mord plus, et les tailles ne changent pas.
    const zColonne = Number(bas.dataset.z) * cascade(Number(bas.dataset.z), av)
      + Number(fiche.dataset.z) * cascade(Number(fiche.dataset.z), av);
    // Le demi-pixel de marge absorbe les arrondis au dixième des transforms
    // écrits : à égalité, c'est l'ordre du document qui décide.
    const plafond = Math.max(0, zColonne - 0.5);
    const zHero = Math.min(80 * av, plafond);
    const zOvni = Math.min(52 * av, zHero);
    const zAvant = Math.min(88 * av, plafond);
    // Les ovnis sont LOIN : 0,28× au repos là où le héros prend 1,6×. Dépliée,
    // la carte les fait RESSORTIR (0,62× et +8 %), sans rattraper le héros.
    const ov = 0.28 + 0.34 * av;
    if (ovni) {
      ovni.style.transform = `translate3d(${(tx * ov).toFixed(1)}px,${(ty * ov).toFixed(1)}px,0) scale(${(1 + 0.08 * av).toFixed(4)})`;
    }
    // Le jumeau libre doit SORTIR : il monte de 22 px et grossit de 18 %.
    if (ovniLibre) {
      ovniLibre.style.transform = `translateZ(${zOvni.toFixed(1)}px) translate3d(${(tx * ov).toFixed(1)}px,${(ty * ov - 22 * av).toFixed(1)}px,0) scale(${((1 + 0.18 * av) * COMP(52 * av)).toFixed(4)})`;
    }
    const echelle = visuel().heroEchelle;
    tLibre = `translateZ(${zHero.toFixed(1)}px) translate3d(${(tx * 1.6).toFixed(1)}px,${(ty * 1.6).toFixed(1)}px,0) scale(${((1 + (echelle - 1) * av) * COMP(80 * av)).toFixed(4)})`;
    libre.style.transform = tLibre;
    ajusterPieds();
    if (apLibre) {
      apLibre.style.transform = `translateZ(${zAvant.toFixed(1)}px) translate3d(${(tx * 2.8).toFixed(1)}px,${(ty * 2.8).toFixed(1)}px,0) scale(${((1 + 0.16 * av) * COMP(88 * av)).toFixed(4)})`;
    }
    // Le vitrage suit l'inclinaison : la GRAVURE ne bouge jamais, c'est la
    // lumière qui la parcourt.
    majContour(nx, ny);
    if (holo) {
      holo.style.setProperty('--chero-holo-a', `${(108 + nx * 40).toFixed(1)}deg`);
      holo.style.setProperty('--chero-holo-x', `${(50 + nx * 160).toFixed(1)}%`);
      holo.style.setProperty('--chero-holo-y', `${(50 + ny * 160).toFixed(1)}%`);
    }
    // Le vernis : la tache de lumière reste sous le pointeur.
    vernis.style.setProperty('--chero-vernis-x', `${(50 + nx * 100).toFixed(1)}%`);
    vernis.style.setProperty('--chero-vernis-y', `${(50 + ny * 100).toFixed(1)}%`);
    // Le métal de la bordure et celui du nom GLISSENT : c'est ce qui fait la
    // différence entre du métal et un dégradé.
    if (or) {
      or.style.setProperty('--chero-or-a', `${(104 + nx * 34).toFixed(1)}deg`);
      or.style.setProperty('--chero-or-x', `${(50 + nx * 150).toFixed(1)}%`);
      or.style.setProperty('--chero-or-y', `${(50 + ny * 150).toFixed(1)}%`);
    }
    if (nomFoil) {
      nom.style.setProperty('--chero-foil-a', `${(178 + nx * 30).toFixed(1)}deg`);
      nom.style.setProperty('--chero-foil-x', `${(50 + nx * 140).toFixed(1)}%`);
      nom.style.setProperty('--chero-foil-y', `${(50 + ny * 140).toFixed(1)}%`);
    }
    // Le bord tourné vers la lumière (en haut à gauche) s'allume, l'opposé
    // s'éteint. `gainReflet` le monte sur l'overlay, où la carte fait 680 px.
    const lx = -nx * 2;
    const ly = -ny * 2;
    const eclat = (v) => Math.min(1, 0.12 + Math.max(0, v) * 0.95 * gainReflet).toFixed(2);
    if (bords.gauche) bords.gauche.style.opacity = eclat(lx);
    if (bords.droite) bords.droite.style.opacity = eclat(-lx);
    if (bords.haut) bords.haut.style.opacity = eclat(ly);
    if (bords.bas) bords.bas.style.opacity = eclat(-ly);
  };

  // La 3D n'existe que sous le curseur. La transition des couches est coupée
  // le temps du survol : leur profondeur est écrite frame par frame.
  const set3d = (actif) => {
    if (actif) {
      racine.style.zIndex = '10';
      racine.style.perspective = `${PERSP}px`;
      zoom.style.transformStyle = 'preserve-3d';
      plateau.style.transformStyle = 'preserve-3d';
      l1.style.willChange = 'transform';
      zEls.forEach((el) => {
        el.style.transition = 'none';
        el.__t = zTransform(el, 0);
        el.style.transform = el.__t;
      });
      requestAnimationFrame(() => {
        if (!survol) return;
        zEls.forEach((el) => { el.style.transform = zTransform(el, ouverture()); });
        libre.style.transform = 'translateZ(0px) scale(1)';
        if (apLibre) apLibre.style.transform = 'translateZ(0px) scale(1)';
      });
    } else if (!fermeA) {
      // Tout est plié par la boucle du repli : remettre à plat ici le faisait
      // claquer avant que la carte ait bougé.
      zEls.forEach((el) => { el.__t = 'translateZ(0px)'; el.style.transform = el.__t; });
      libre.style.transform = 'translateZ(0px) scale(1)';
      if (apLibre) apLibre.style.transform = 'translateZ(0px) scale(1)';
    }
  };

  const aplatir = () => {
    if (survol) return;
    racine.style.zIndex = '';
    racine.style.perspective = '';
    zoom.style.transformStyle = '';
    plateau.style.transformStyle = '';
    plateau.style.willChange = '';
    zEls.forEach((el) => { el.__t = ''; el.style.transform = ''; el.style.transition = ''; });
    libre.style.transform = '';
    tCard = '';
    tLibre = '';
    requestAnimationFrame(ajusterPieds);
    if (apLibre) apLibre.style.transform = '';
    if (ovni) ovni.style.transform = '';
    if (ovniLibre) ovniLibre.style.transform = '';
    l1.style.willChange = '';
  };

  const entrer = () => {
    if (survol) return;
    survol = true;
    clearTimeout(minuteurFin);
    set3d(true);
    // 🚨 AUCUNE transition pendant le dépli : l'inclinaison est écrite frame
    // par frame comme les profondeurs. Le suivi du pointeur retrouve son
    // lissage de 160 ms à la fin du dépli.
    plateau.style.transition = 'none';
    // Revenir sur une carte encore en train de se replier REPREND son
    // avancement : remis à zéro, l'aller-retour du pointeur la faisait
    // clignoter.
    const avNow = fermeA ? ouverture() : 0;
    if (repli) { BOUCLE.retirer(repli); repli = null; }
    fermeA = 0;
    ouvertA = performance.now() - (1 - Math.cbrt(1 - Math.min(0.999, avNow))) * LISSAGE;
    if (depliage) BOUCLE.retirer(depliage);
    depliage = () => {
      incliner(dernierNx, dernierNy);
      if (performance.now() - ouvertA >= LISSAGE) {
        BOUCLE.retirer(depliage);
        depliage = null;
        // Piloté par script, la chorégraphie écrit une cible toutes les 33 ms :
        // une transition de 160 ms n'atteindrait jamais la sienne.
        plateau.style.transition = interactif ? 'transform .16s ease-out' : 'none';
      }
    };
    BOUCLE.ajouter(depliage, true);
    // Les transitions CSS de la carte et du liseré ne préviennent pas quand
    // elles avancent : la découpe se recalcule tant que le survol dure.
    if (!suivi) { suivi = ajusterPieds; BOUCLE.ajouter(suivi, true); }
    if (reflet) { reflet.style.visibility = 'visible'; reflet.style.opacity = '.9'; }
    netteteHero();
    if (holo) holo.style.opacity = String(OPACITE_HOLO);
    vernis.style.opacity = String(OPACITE_VERNIS);
    fiche.style.boxShadow = '0 16px 30px rgba(0,0,0,.55), 0 3px 0 rgba(18,16,12,.5)';
    nom.style.animation = 'chero-float 3.2s ease-in-out infinite';
    if (c.debordement) {
      libre.style.visibility = 'visible';
      libre.style.opacity = '1';
      clip.style.opacity = '0';
      if (ovniLibre) {
        ovniLibre.style.visibility = 'visible';
        ovniLibre.style.opacity = String(c.ovniOpacite);
        ovni.style.opacity = '0';
      }
      if (apLibre) { apLibre.style.visibility = 'visible'; apLibre.style.opacity = '1'; }
      if (apClip) apClip.style.opacity = '0';
    }
  };

  const sortir = () => {
    if (!survol) return;
    survol = false;
    // Le repli part de là où l'ouverture en était, et il est ÉCRIT à chaque
    // frame : une transition CSS par-dessus ajouterait sa propre horloge.
    avSortie = ouverture();
    ouvertA = 0;
    fermeA = performance.now();
    if (depliage) { BOUCLE.retirer(depliage); depliage = null; }
    plateau.style.transition = 'none';
    l1.style.transform = 'scale(1.06)';
    if (reflet) { reflet.style.opacity = '0'; reflet.style.visibility = 'hidden'; }
    if (holo) holo.style.opacity = '0';
    setTimeout(netteteHero, 60);
    vernis.style.opacity = '0';
    fiche.style.boxShadow = 'none';
    Object.values(bords).forEach((el) => { el.style.opacity = '.25'; });
    nom.style.animation = 'none';
    // 🚨 Les jumeaux 2D ne reviennent PAS ici : le héros libre met 440 ms à se
    // replier, et rallumer le 2D tout de suite les superposait — la bande de
    // vitrage entre deux héros qui ne coïncident pas. L'échange se fait dans
    // `fin()`, quand le libre est revenu à la géométrie du 2D.
    set3d(false);
    const fin = () => {
      if (repli) { BOUCLE.retirer(repli); repli = null; }
      if (!fermeA) return;
      fermeA = 0;
      plateau.style.transition = 'transform .16s ease-out';
      plateau.style.transform = '';
      libre.style.transform = '';
      if (apLibre) apLibre.style.transform = '';
      if (ovniLibre) ovniLibre.style.transform = '';
      libre.style.opacity = '0';
      libre.style.visibility = 'hidden';
      clip.style.opacity = '1';
      if (ovniLibre) { ovniLibre.style.opacity = '0'; ovniLibre.style.visibility = 'hidden'; }
      if (ovni) { ovni.style.opacity = '1'; ovni.style.transform = ''; }
      if (apLibre) { apLibre.style.opacity = '0'; apLibre.style.visibility = 'hidden'; }
      if (apClip) apClip.style.opacity = apRepos;
      aplatir();
    };
    if (repli) BOUCLE.retirer(repli);
    repli = () => {
      incliner(dernierNx, dernierNy);
      if (performance.now() - fermeA >= FERME) fin();
    };
    BOUCLE.ajouter(repli, true);
    // Le filet : la boucle est suspendue quand l'onglet passe en fond.
    clearTimeout(minuteurFin);
    minuteurFin = setTimeout(fin, FERME + 220);
    if (suivi) {
      const s = suivi;
      setTimeout(() => {
        if (survol) return;
        BOUCLE.retirer(s);
        if (suivi === s) suivi = null;
      }, 560);
    }
  };

  // L'ultime ne DUPLIQUE pas les couches : il échange les sources au pic du
  // flash blanc. Le héros en slip hérite exactement de la profondeur du héros
  // habillé.
  const basculerUlt = () => {
    if (basculeEnCours) return;
    basculeEnCours = true;
    flash.style.transition = 'opacity .09s ease-out';
    flash.style.opacity = '1';
    setTimeout(() => {
      ult = !ult;
      const v = visuel();
      appliquerVisuel();
      changerImage(clip, v.hero);
      changerImage(libre, v.hero3d);
      cleDecoupe = '';
      netteteHero();
      if (survol) incliner(dernierNx, dernierNy);
      else ajusterPieds();
      flash.style.transition = 'opacity .34s ease-in';
      flash.style.opacity = '0';
      setTimeout(() => { basculeEnCours = false; }, 340);
    }, 95);
  };

  // Le suivi du pointeur, coalescé dans un `requestAnimationFrame`.
  let attend = false;
  let px = 0;
  let py = 0;
  const inclinerVersLeCurseur = () => {
    attend = false;
    if (!survol) return;
    const r = racine.getBoundingClientRect();
    if (!r.width || !r.height) return;
    incliner((px - r.left) / r.width - 0.5, (py - r.top) / r.height - 0.5);
  };
  const surMouvement = (e) => {
    px = e.clientX;
    py = e.clientY;
    if (!attend) { attend = true; requestAnimationFrame(inclinerVersLeCurseur); }
  };
  const surEntree = (e) => { px = e.clientX; py = e.clientY; entrer(); };

  // Sur un écran tactile il n'y a pas de survol : c'est le tap qui ouvre et
  // referme. 🚨 Un GLISSEMENT n'ouvre ni ne ferme : le doigt qui promène la
  // page finit par un click. Au-delà de 10 px, le tap n'en est plus un.
  let sx = 0;
  let sy = 0;
  let glisse = false;
  const surAppui = (e) => { sx = e.clientX; sy = e.clientY; glisse = false; };
  const surGlisse = (e) => { if (Math.hypot(e.clientX - sx, e.clientY - sy) > 10) glisse = true; };
  const surTap = () => {
    if (glisse) { glisse = false; return; }
    if (survol) sortir(); else entrer();
  };

  const surImageLibre = () => { netteteHero(); ajusterPieds(); };
  const ecouteurs = [];
  const ecouter = (cible, type, fn, opts) => {
    cible.addEventListener(type, fn, opts);
    ecouteurs.push(() => cible.removeEventListener(type, fn, opts));
  };
  netteteHero();
  if (imgLibre.complete) ajusterPieds();
  ecouter(imgLibre, 'load', surImageLibre);
  ecouter(window, 'resize', majZoom, { passive: true });
  if (c.heroUlt) {
    // Préchargement : sans lui, le premier appui laisse voir un trou pendant
    // que l'image du slip arrive, juste au moment où le flash s'efface.
    [c.heroUlt, c.hero3dUlt, c.fondUlt].forEach((u) => {
      if (u) new Image().src = paire(u).webp;
    });
    ecouter(racine, 'click', basculerUlt);
  }
  if (!interactif) {
    // L'overlay et la page au gyroscope ne branchent RIEN ici : ils appellent
    // `ouvrir`, `incliner` et `fermer` eux-mêmes.
  } else if (TACTILE()) {
    ecouter(racine, 'pointerdown', surAppui, { passive: true });
    ecouter(racine, 'pointermove', surGlisse, { passive: true });
    ecouter(racine, 'click', surTap);
  } else if (!SOBRE()) {
    ecouter(racine, 'pointermove', surMouvement, { passive: true });
    ecouter(racine, 'pointerenter', surEntree);
    ecouter(racine, 'pointerleave', sortir);
  }

  const detruire = () => {
    clearTimeout(minuteurFin);
    if (repli) { BOUCLE.retirer(repli); repli = null; }
    if (depliage) { BOUCLE.retirer(depliage); depliage = null; }
    if (suivi) { BOUCLE.retirer(suivi); suivi = null; }
    ecouteurs.forEach((retirer) => retirer());
    ecouteurs.length = 0;
  };

  return { boite, detruire, ouvrir: entrer, fermer: sortir, incliner };
}
