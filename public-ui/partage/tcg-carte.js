// public-ui/partage/tcg-carte.js — une carte de héros du TCG
//
// Port de la maquette Claude Design `Carte Hero.dc.html`. Ce module RENDU du
// DOM et ne calcule AUCUNE règle : il reçoit un objet décrivant une carte et
// l'affiche. Le moteur du jeu vit côté serveur, en Python — une règle dupliquée
// en JavaScript est une porte de triche ouverte et un second jeu à maintenir.
//
// Utilisé par `/tcg` (la collection) et `/demo/carte-azrael` (la démo d'une
// carte seule). Un seul rendu pour les deux : deux copies divergeraient au
// premier réglage.
//
// 🚨 Toute la tenue en performance de ce module tient à trois choses. Les
// défaire, c'est faire ramer une grille de vingt cartes :
//
//   1. **La 3D n'existe que sous le curseur.** `set3d()` pose `perspective`,
//      `preserve-3d`, `translateZ` et `will-change` à l'entrée et les retire à
//      la sortie. Au repos une carte est un APLAT : un calque GPU au lieu de
//      neuf. La perspective n'est retirée qu'une fois les Z revenus à zéro,
//      sinon la coupure se voit.
//   2. **Une seule boucle `requestAnimationFrame` pour toute la page**, à
//      30 images/s, et à l'arrêt quand l'onglet passe derrière. Vingt cartes
//      avec leur propre boucle, c'est vingt réveils par image.
//   3. **Les sprites de particules sont partagés** entre toutes les cartes, et
//      le canvas fait la MOITIÉ de la carte en pixels.

import { h } from './dom.js';

// La feuille de la carte. Elle porte aussi le `@font-face` d'Archivo Black,
// VENDORÉE : un overlay OBS qui dépend d'une requête vers Google au démarrage
// afficherait son premier titre dans la police de repli si le réseau traîne —
// et sur un stream, ça ne se rattrape pas.
const FEUILLE = '/partage/tcg-carte.css';

/** L'AVIF et son repli WebP, depuis un chemin SANS extension.
 *
 * Les deux formats sont servis ensemble (`<picture>` pour les images,
 * `image-set()` pour le fond) : l'AVIF pèse deux fois et demie moins qu'un
 * WebP de même qualité, mais Safari ne le lit que depuis 16.4 et un téléphone
 * plus vieux n'afficherait RIEN.
 *
 * 🚨 C'est le SEUL endroit qui sait comment une illustration se sert. Le site
 * appliquait la transformation de son côté avant de construire la carte, pas
 * l'overlay — qui reçoit les chemins bruts du bus. Résultat : `src.avif` valait
 * `undefined` et l'overlay demandait `/static/undefined`, un 404 sans image et
 * sans erreur JS. Un composant qui accepte les deux formes n'a plus ce piège.
 *
 * Une paire déjà construite passe telle quelle : l'appelant n'a pas à savoir
 * dans quel état arrive ce qu'il transmet.
 */
function paire(base) {
  if (base && typeof base === 'object') return base;
  // ⚠️ Le chemin porte une empreinte (`/assets/x?v=a1b2c3d4`) : l'extension
  // s'insère AVANT le `?`. Collée à la fin, on demanderait `x?v=….avif`, que
  // le serveur ne connaît pas — et la carte serait noire.
  const [chemin, requete] = String(base).split('?');
  const suffixe = requete ? `?${requete}` : '';
  return { avif: `${chemin}.avif${suffixe}`, webp: `${chemin}.webp${suffixe}` };
}

/** Charge la feuille de la carte. Rend de quoi la retirer.
 *
 * Appelé par la page, pas par la carte : une grille de vingt cartes ne doit
 * poser le `<link>` qu'une fois.
 */
export function monterStylesCarte() {
  if (document.head.querySelector(`link[href="${FEUILLE}"]`)) return () => {};
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = FEUILLE;
  document.head.appendChild(lien);
  return () => lien.remove();
}

// ── Les trois ressources partagées par toutes les cartes ──────────────────

/** Les sprites de particules, dessinés UNE fois pour la page.
 *
 * Un dégradé radial par particule et par image coûterait trente créations de
 * dégradé à chaque frame, sur chaque carte.
 */
const sprites = (() => {
  let cache = null;
  return () => {
    if (cache) return cache;
    const S = 64;
    const dessin = (peindre) => {
      const o = document.createElement('canvas');
      o.width = S;
      o.height = S;
      peindre(o.getContext('2d'), S / 2);
      return o;
    };
    const lueur = (c0, c1, c2) => dessin((x, m) => {
      const g = x.createRadialGradient(m, m, 0, m, m, m);
      g.addColorStop(0, c0);
      g.addColorStop(0.3, c1);
      g.addColorStop(1, c2);
      x.fillStyle = g;
      x.fillRect(0, 0, S, S);
    });
    const noyau = (sombre, clair) => dessin((x, m) => {
      if (sombre) {
        x.fillStyle = sombre;
        x.beginPath();
        x.arc(m, m, m, 0, Math.PI * 2);
        x.fill();
      }
      x.fillStyle = clair;
      x.beginPath();
      x.arc(m + m * .25, m - m * .2, m * .6, 0, Math.PI * 2);
      x.fill();
    });
    cache = {
      braise: { lueur: lueur('rgba(255,90,20,.9)', 'rgba(230,50,10,.6)', 'rgba(160,20,0,0)'), noyau: noyau('rgba(20,6,4,.9)', 'rgba(255,70,20,1)') },
      chaude: { lueur: lueur('rgba(255,220,150,1)', 'rgba(230,50,10,.6)', 'rgba(160,20,0,0)'), noyau: noyau('rgba(20,6,4,.9)', 'rgba(255,200,120,1)') },
      poussiere: { lueur: lueur('rgba(255,215,140,.9)', 'rgba(255,190,80,.4)', 'rgba(255,176,46,0)'), noyau: noyau(null, 'rgba(255,240,210,1)') },
      cendre: { lueur: null, noyau: noyau('rgba(12,8,6,.85)', 'rgba(120,30,10,.5)') },
    };
    return cache;
  };
})();

/** La boucle d'animation de la page : une seule, plafonnée à 30 images/s. */
const BOUCLE = (() => {
  const abonnes = new Set();
  let raf = 0;
  let derniere = 0;
  const image = (maintenant) => {
    raf = abonnes.size ? requestAnimationFrame(image) : 0;
    if (document.hidden || maintenant - derniere < 31) return;
    derniere = maintenant;
    abonnes.forEach((fn) => fn(maintenant));
  };
  return {
    ajouter(fn) {
      abonnes.add(fn);
      if (!raf) raf = requestAnimationFrame(image);
    },
    retirer(fn) { abonnes.delete(fn); },
  };
})();

/** Abonne `fn` à la boucle de la page. Rend de quoi la désabonner.
 *
 * Exposé pour la chorégraphie de l'overlay, qui doit avancer image par image
 * sans ouvrir un second `requestAnimationFrame` : une carte qui joue son
 * animation pendant que ses particules tournent ferait deux réveils par image
 * là où un seul suffit, et les deux se désynchroniseraient.
 */
export function abonnerAnimation(fn) {
  BOUCLE.ajouter(fn);
  return () => BOUCLE.retirer(fn);
}

/** L'œil qui dit quelles cartes sont à l'écran. Un observateur pour la page. */
const OEIL = (() => {
  const rappels = new Map();
  let io = null;
  return {
    observer(el, fn) {
      if (!io) {
        io = new IntersectionObserver((entrees) => entrees.forEach((e) => {
          const rappel = rappels.get(e.target);
          if (rappel) rappel(e.isIntersecting);
        }), { threshold: 0.02, rootMargin: '10% 0px' });
      }
      rappels.set(el, fn);
      io.observe(el);
    },
    oublier(el) {
      rappels.delete(el);
      if (io) io.unobserve(el);
    },
  };
})();

// L'intensité du reflet holographique. Réglée à 0,34 le 2026-09-08 après
// comparaison à l'écran, puis MONTÉE : sur un vrai écran l'owner le voyait à
// peine. Un reflet holographique doit dénaturer les couleurs — c'est ce qu'il
// fait sur une vraie carte sous une lampe ; le retenir pour « préserver
// l'illustration » revenait à ne pas faire l'effet.
//
// ⚠️ Indépendant de `gainReflet`, qui règle l'éclat des quatre BORDS. Les
// multiplier ensemble portait l'holo à 0,80 sur l'overlay — la carte y était
// repeinte.
//
// ⚠️ 0,62 → 0,80 le 2026-09-09, choisi sur un banc à trois valeurs capturé
// côte à côte (0,45 · 0,80 · 1,0). La couche est passée SOUS le héros et dans
// le fond : elle n'a plus à se retenir pour préserver le personnage, il est
// devant. Et le fond d'Azraël est une explosion orange claire — en dessous de
// 0,8, le vitrage s'y noie. C'est un réglage d'OEIL : il se juge à l'écran,
// sur les trois cartes, pas au calcul.
const OPACITE_HOLO = 0.8;

// ── Le vitrage irisé ──────────────────────────────────────────────────────
// Le chatoiement seul rend des BANDES : joli, mais lisse. Une vraie carte
// holographique porte une GRAVURE — un pavage de cellules, et dans chacune des
// anneaux concentriques qui parcourent l'arc-en-ciel en s'éloignant de
// l'arête. C'est ce motif-là qui fait « carte holo » et pas « dégradé ».
//
// 🚨 La tuile est une IMAGE COULEUR, pas un masque. Un masque monochrome ne
// peut que doser l'irisation déjà présente — essayé le 2026-09-09, capturé :
// on obtenait des facettes plus ou moins vives, jamais un anneau rouge à côté
// d'un anneau cyan. La teinte doit être DANS la texture.
//
// 🚨 Elle est CUITE UNE FOIS, rangée dans `--chero-voronoi` sur `<html>` et
// partagée par TOUTES les cartes. La calculer par carte referait la même
// boucle cinq fois pour une image identique ; la calculer par image serait un
// pavage de Voronoï à 60 Hz. La couche ne porte au final qu'un fond statique
// de plus, et le mouvement reste ce qu'il était : le dégradé qui GLISSE
// dessous, et que la gravure multiplie.
//
// 🚨 Le fond des joints est NOIR et non gris. La couche est en
// `plus-lighter` : le noir n'ajoute rien, un gris ajouterait un voile sur
// toute la carte, y compris là où il n'y a aucun reflet à montrer.
//
// 🚨 La tuile est SANS COUTURE — les distances sont prises sur un TORE
// (`dx > T/2 → T − dx`). Sans ça, la répétition dessine une grille de joints
// rectilignes à chaque tuile : on lit un carrelage, pas un vitrage.
//
// 🚨 Le tirage est DÉTERMINISTE (générateur à graine fixe). Avec `Math.random`
// la carte n'aurait pas deux fois la même gravure, et une capture d'écran ne
// prouverait plus rien d'un rendu à l'autre.
const VORONOI_TUILE = 256;
// 🚨 La cellule à l'écran vaut `background-size / VORONOI_COTE`. La tuile est
// posée à sa taille NATIVE (256 px) : les anneaux font deux à trois pixels, et
// les réduire au filtrage les moyennerait en un aplat.
// 12 × 12 germes dans une tuile POSÉE à 96 px : la cellule fait 8 px et le
// vitrage se lit comme un grain, pas comme des plaques de couleur. C'est le
// grain retenu par l'owner le 2026-09-09, après deux jets plus gros écartés à
// l'écran — 32 px, puis 21 px. La MÊME valeur sur la surface et sur le
// liseré : elle a été jugée sur le liseré de KingsRequin, et reprise telle
// quelle sur Azraël et Rhae.
//
// 🚨 La tuile est cuite à 256 px et posée à 96, donc RÉDUITE d'un facteur
// 0,37 — et c'est voulu. Les anneaux font deux à trois pixels dans la tuile ;
// le filtrage du navigateur les fond en un dégradé continu au lieu de les
// crêner. Cuire directement à 96 px donnerait le même grain pour quatre fois
// moins cher, mais avec l'escalier que ce suréchantillonnage évite.
const VORONOI_COTE = 12;
// Combien de fois l'arc-en-ciel se répète du bord vers le cœur d'une cellule.
// 2,5 et non 3,5 : dans une cellule de 21 px, trois anneaux et demi tombent
// sous la largeur du pixel.
const VORONOI_ANNEAUX = 2.5;

let voronoiCuit = false;

/** Cuit le vitrage et le range dans `--chero-voronoi` sur `<html>`.
 *
 * Appelée à la PREMIÈRE carte holographique, et une seule fois : une page sans
 * carte holo ne paie rien. Différée hors du chemin de construction — la boucle
 * fait 9,4 M d'itérations, chronométrées à 32 ms au navigateur le 2026-09-09,
 * et la couche irisée est à `opacity: 0` tant que personne ne penche la
 * carte. Tant que la tuile n'est pas là, la couche
 * retombe sur son repli `none` : la carte garde son chatoiement sans gravure,
 * jamais un trou.
 */
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
    // LCG à graine fixe (Numerical Recipes) : même gravure à chaque
    // chargement, sur chaque machine.
    let graine = 0x9e3779b9;
    const alea = () => {
      graine = (graine * 1664525 + 1013904223) >>> 0;
      return graine / 4294967296;
    };
    // Les germes sortent d'une grille SECOUÉE, pas d'un tirage libre : au
    // hasard pur ils se groupent, et le pavage alterne des cellules énormes et
    // des échardes — ça se lit comme du bruit, pas comme un vitrage.
    const pas = T / VORONOI_COTE;
    const gx = [];
    const gy = [];
    const decal = [];
    const gain = [];
    for (let j = 0; j < VORONOI_COTE; j++) {
      for (let i = 0; i < VORONOI_COTE; i++) {
        gx.push((i + 0.18 + alea() * 0.64) * pas);
        gy.push((j + 0.18 + alea() * 0.64) * pas);
        // Chaque cellule démarre son arc-en-ciel à une teinte différente,
        // sinon toutes portent les mêmes anneaux et le pavage se lit comme un
        // papier peint.
        decal.push(alea());
        // Et toutes ne brillent pas pareil : c'est cet écart qui donne
        // l'impression d'éclats qui accrochent la lumière chacun leur tour.
        gain.push(0.55 + alea() * 0.45);
      }
    }
    const img = ctx.createImageData(T, T);
    const d = img.data;
    // La largeur du joint gravé, où la couleur s'éteint vers le noir.
    const joint = pas * 0.22;
    // Sur quelle distance l'arc-en-ciel se déroule du bord vers le cœur.
    const rayon = pas * 0.9;
    for (let y = 0; y < T; y++) {
      for (let x = 0; x < T; x++) {
        let f1 = Infinity;
        let f2 = Infinity;
        let cel = 0;
        for (let k = 0; k < gx.length; k++) {
          let dx = Math.abs(x - gx[k]);
          if (dx > T / 2) dx = T - dx;
          let dy = Math.abs(y - gy[k]);
          if (dy > T / 2) dy = T - dy;
          const dd = dx * dx + dy * dy;
          if (dd < f1) { f2 = f1; f1 = dd; cel = k; }
          else if (dd < f2) { f2 = dd; }
        }
        // F2 − F1 s'annule EXACTEMENT sur l'arête entre deux germes et croît
        // vers le cœur : c'est à la fois la gravure et la coordonnée des
        // anneaux, et elle sort sans construire le moindre polygone.
        const e = Math.sqrt(f2) - Math.sqrt(f1);
        const b = Math.min(1, e / joint);
        // Le joint, lissé en `smoothstep` : sans lissage il crénelle.
        const eclat = b * b * (3 - 2 * b) * gain[cel];
        // La teinte tourne avec la distance à l'arête — d'où les anneaux.
        let t = (e / rayon) * VORONOI_ANNEAUX + decal[cel];
        t -= Math.floor(t);
        // HSL(t, 100 %, 50 %) → RGB, écrit à plat : la roue en trois rampes
        // triangulaires. Passer par `ctx.fillStyle` coûterait 65 536 analyses
        // de chaîne de caractères.
        const h = t * 6;
        const o = (y * T + x) * 4;
        d[o] = Math.round(Math.max(0, Math.min(1, Math.abs(h - 3) - 1)) * eclat * 255);
        d[o + 1] = Math.round(Math.max(0, Math.min(1, 2 - Math.abs(h - 2))) * eclat * 255);
        d[o + 2] = Math.round(Math.max(0, Math.min(1, 2 - Math.abs(h - 4))) * eclat * 255);
        d[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    // 🚨 Un BLOB, pas un `toDataURL`. Le vitrage est une image en couleurs
    // pures : elle compresse mal, et son data-URI pesait 232 ko — 232 ko de
    // CHAÎNE posés dans une custom property, relus à chaque `getComputedStyle`
    // et gonflés d'un tiers par le base64. L'URL d'objet en fait cinquante.
    // Elle n'est jamais révoquée : elle vit aussi longtemps que le document,
    // exactement comme la tuile qu'elle désigne.
    cv.toBlob((blob) => {
      if (!blob) return;
      document.documentElement.style.setProperty(
        '--chero-voronoi', `url("${URL.createObjectURL(blob)}")`);
    }, 'image/png');
  });
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

// ── Les particules ────────────────────────────────────────────────────────

/** Dessine les particules d'une carte. Rend `{ pas, bouffee }`.
 *
 * `pas(maintenant)` est destiné à `BOUCLE` : il s'auto-limite à ~10 images/s
 * au repos et passe à 30 sous le curseur. `bouffee()` jette une poignée de
 * particules vers le haut à l'entrée du curseur.
 */
function particules(canvas, etat, mode) {
  const L = 170;
  const H = 238;
  canvas.width = L;
  canvas.height = H;
  const ctx = canvas.getContext('2d', { alpha: true });
  const SP = sprites();
  const legere = mode === 'poussiere';
  const N = legere ? 12 : 16;
  const vivantes = [];

  const semer = (e, initiale, jet) => {
    e.x = jet ? L * (0.3 + Math.random() * 0.4) : 5 + Math.random() * (L - 10);
    e.y = initiale ? Math.random() * H : (jet ? H * 0.72 : H * (0.6 + Math.random() * 0.4));
    e.r = ((legere ? 0.8 : 1) + Math.random() * (legere ? 1.6 : 2.6)) * .5;
    e.vy = (jet ? 1.6 + Math.random() * 1.8 : 0.3 + Math.random() * 0.7) * .5;
    e.vx = jet ? (Math.random() - 0.5) * 1.2 : 0;
    e.ph = Math.random() * Math.PI * 2;
    e.sw = 0.3 + Math.random() * 0.7;
    e.vie = 0;
    e.max = jet ? 120 + Math.random() * 100 : 260 + Math.random() * 300;
    e.type = legere
      ? (Math.random() < 0.3 ? 'chaude' : 'poussiere')
      : (Math.random() < 0.22 ? 'cendre' : (Math.random() < 0.25 ? 'chaude' : 'braise'));
    e.jet = !!jet;
    return e;
  };
  for (let i = 0; i < N; i += 1) vivantes.push(semer({}, true));

  let t = 0;
  let derniere = 0;

  const pas = (maintenant) => {
    // Au repos ~10 images/s, sous le curseur 30 : une braise qui monte
    // lentement ne se lit pas plus vite, et la carte n'est pas regardée.
    if (maintenant - derniere < (etat.survol ? 0 : 95)) return;
    const dt = Math.min(4, (maintenant - derniere) / 33);
    derniere = maintenant;
    t += 2 * dt;
    ctx.clearRect(0, 0, L, H);
    for (let i = vivantes.length - 1; i >= 0; i -= 1) {
      const e = vivantes[i];
      e.vie += 2 * dt;
      e.y -= e.vy * 2 * dt;
      e.x += (Math.sin(t * 0.02 + e.ph) * e.sw * 0.25 + etat.vent * .5 + e.vx) * 2 * dt;
      e.vx *= 0.92;
      if (e.jet) e.vy *= 0.97;
      const k = e.vie / e.max;
      if (e.y < -6 || e.vie > e.max || e.x < -5 || e.x > L + 5) {
        if (e.jet) { vivantes.splice(i, 1); continue; }
        semer(e, false);
      }
      const a = k < 0.12 ? k / 0.12 : 1 - (k - 0.12) / 0.88;
      const scintille = 0.6 + 0.4 * Math.sin(t * 0.3 + e.ph * 3) * Math.sin(t * 0.07 + e.ph);
      ctx.globalAlpha = Math.max(0, Math.min(1, a * scintille));
      const sp = SP[e.type];
      if (sp.lueur) {
        const R = e.r * 6;
        ctx.globalCompositeOperation = 'lighter';
        ctx.drawImage(sp.lueur, e.x - R, e.y - R, R * 2, R * 2);
      }
      ctx.globalCompositeOperation = 'source-over';
      const r = e.type === 'cendre' ? e.r * 1.1 : e.r;
      ctx.drawImage(sp.noyau, e.x - r, e.y - r, r * 2, r * 2);
    }
    ctx.globalAlpha = 1;
  };

  // Plafond volontaire : une bouffée par entrée du curseur, et pas de
  // cumul si on survole la même carte dix fois de suite.
  const bouffee = () => {
    if (vivantes.length >= 36) return;
    for (let i = 0; i < 8; i += 1) vivantes.push(semer({}, false, true));
  };

  return { pas, bouffee };
}

// ── Le DOM ────────────────────────────────────────────────────────────────

const DEFAUTS = {
  nom: 'AZRAËL',
  classe: 'ARCHANGE · UNIQUE',
  ultime: 'REWORK',
  description: '',
  ambiance: '',
  cout: 0, atk: 0, pv: 0, aura: 0,
  accent: '#ffb02e',
  // `hero` et `fond` n'ont PAS de défaut : une carte sans illustration
  // n'existe pas (cf. la règle en tête de `bot/core/tcg_cartes.py`), et un défaut
  // vide donnerait une carte noire au lieu d'une erreur qu'on voit passer.
  heroCote: '-14%', heroHaut: '4%', heroEchelle: 1.12,
  // Le calque de SURVOL peut porter une autre illustration, avec son propre
  // cadrage : rhae___ montre un portrait assis au repos et un bond griffes en
  // avant quand la carte s'ouvre. À `null`, il reprend le visuel du repos —
  // c'est le cas d'Azraël et de Claker.
  hero3d: null, hero3dCote: null, hero3dHaut: null,
  avantPlan: null, avantPlanLargeur: '86%', avantPlanBas: '-6%',
  particules: 'braises',
  holographique: false,
  // Où court le chatoiement : sur la SURFACE de l'illustration (le défaut),
  // ou seulement dans l'épaisseur du LISERÉ (`'bords'`). Le second existe
  // pour les fonds déjà très colorés, où une irisation de surface se noie —
  // c'est le cas de KingsRequin, dont le fond est un bleu saturé.
  holoZone: 'surface',
  // Deux nappes de bulles qui montent derrière l'illustration. Réservé aux
  // cartes aquatiques : ailleurs, ce sont des taches claires sans raison.
  bulles: false,
  // Le palier de rareté, tel que le sert `bot/core/tcg_cartes.py`. Le défaut
  // est `indefinie` et pas le palier le plus bas : une carte dont le palier
  // n'est pas décidé n'est pas une carte commune.
  rarete: 'indefinie',
  intensite: 1, parallaxe: 1,
  reflet: true, pulsation: true, debordement: true, selectionnee: false,
};

const BORDS = ['haut', 'bas', 'gauche', 'droite'];

// Les six paliers de la base Notion, plus l'absence de palier. Les CLÉS sont
// celles du YAML (sans accent, lisibles dans un attribut) ; les libellés sont
// ce qui s'écrit sur la carte.
//
// 🚨 « INDÉFINIE » s'affiche, il ne se cache pas. Deux cartes sur cinq n'ont
// pas de palier saisi dans Notion au 2026-09-09 : masquer le cartouche les
// ferait passer pour des cartes sans rareté, alors qu'elles en ont une qui
// n'est pas encore écrite. Un blanc muet se lit comme une réponse.
const RARETES = {
  ame: 'ÂME',
  fidele: 'FIDÈLE',
  ame_promise: 'ÂME PROMISE',
  elu: 'ÉLU',
  ange: 'ANGE',
  archange: 'ARCHANGE',
  indefinie: 'INDÉFINIE',
};

// Les paliers qui reçoivent le traitement de faveur — liseré doublé, nom en
// foil. Ils sont ÉNUMÉRÉS et pas calculés par un seuil sur l'ordre : deux
// paliers existent en base aujourd'hui (`ange`, `archange`), et écrire un
// seuil ordonné ferait entrer `elu` et `ame_promise` dans le traitement le
// jour où quelqu'un les saisira, sans que personne ne l'ait décidé.
const RARETES_HAUTES = new Set(['ange', 'archange']);

/** Construit une carte de héros. Rend `{ boite, detruire }`.
 *
 * `boite` est le nœud à insérer (il réserve la taille de la carte, échelle
 * comprise) ; `detruire()` doit être appelé au démontage de la page, sinon la
 * carte reste abonnée à la boucle et à l'œil de la page.
 */
export function carteHero(carte, options = {}) {
  const c = { ...DEFAUTS, ...carte };
  // `interactif` faux : aucun écouteur de pointeur, la carte est pilotée par
  // du code. C'est le mode de l'overlay OBS.
  // 🚨 `depli` et `etape` se posent sur `racine` et pas sur la boîte : la
  // règle `.chero` de la feuille porte leurs valeurs par défaut, et une custom
  // property déclarée sur l'élément lui-même ÉCRASE celle héritée du parent.
  // Posées sur la boîte, elles n'avaient aucun effet — la transition restait à
  // 0,45 s alors que l'overlay demandait 0,85.
  const { interactif = true, gainReflet = 1, depli = null, etape = null } = options;
  // 🚨 Le lissage du saut d'entrée doit durer AU MOINS le temps du dépliage,
  // délai d'échelonnement compris. Il était fixé à 500 ms : la classe partait
  // avant la fin de la transition, et le héros SAUTAIT à sa position finale —
  // mesuré, il restait à Z 0 pendant 1,1 s puis bondissait à 56. Les valeurs
  // par défaut de la feuille sont .45s et .05s ; l'overlay les rallonge.
  const lissageMs = enMs(depli, 450) + enMs(etape, 50) * 2 + 60;
  // 🚨 Le dépliage du héros est CALCULÉ, pas transitionné, et c'est la seule
  // façon qui marche. `incliner()` réécrit son `transform` trente fois par
  // seconde : une transition CSS redémarre à chaque écriture et n'atteint
  // jamais sa cible. Deux contournements ont échoué avant celui-ci — la
  // transition dans la règle de base laissait le `translateZ` à ZÉRO (et le
  // liseré, lui à 30, passait DEVANT le héros : vu sur Lilith, les ailes
  // derrière le cadre) ; la poser par une classe le temps de l'entrée faisait
  // sauter le Z d'un coup au retrait de la classe.
  //
  // Un seul écrivain, une progression continue : c'est le principe de tout ce
  // composant, et il n'y avait pas de raison d'y faire exception.
  let ouvertA = 0;
  // La dernière inclinaison demandée, pour pouvoir la RÉAPPLIQUER pendant le
  // dépliage sans nouvel événement.
  let dernierNx = 0;
  let dernierNy = 0;
  let arretDepliage = null;

  const l1 = h('div', { class: 'chero-l1' });
  const l2 = h('div', { class: 'chero-l2' });
  const l3 = h('div', { class: 'chero-l3' });
  const cadres = h('div', { class: 'chero-cadres' },
    h('div'), h('div'), h('div'), h('div'));
  const halo = h('div', { class: 'chero-halo' });
  // 🚨 Le chatoiement des BORDS ne vit pas au même endroit que celui de la
  // surface : il monte en Z avec le liseré (`data-z="30"`) et doit donc en
  // être l'enfant. Posé dans un cadrage à plat comme l'autre, il se décalait
  // du liseré dès que la carte s'ouvre — le reflet flottait à côté du cadre.
  const holoBords = c.holographique && c.holoZone === 'bords';
  if (c.holographique) cuireVoronoi();
  const holo = c.holographique
    ? h('div', { class: `chero-holo${holoBords ? ' chero-holo--bords' : ''}` })
    : null;
  // Les deux nappes de bulles montent en boucle et se SÉPARENT en profondeur
  // sous l'inclinaison : la proche se déplace 2,5 fois plus que la lointaine.
  // Sous `prefers-reduced-motion`, pas de nappes du tout — une animation en
  // boucle infinie ne se coupe pas seulement au survol.
  const bullesLoin = c.bulles && !SOBRE()
    ? h('div', { class: 'chero-bulles chero-bulles--loin' }, h('div')) : null;
  const bullesPres = c.bulles && !SOBRE()
    ? h('div', { class: 'chero-bulles chero-bulles--pres' }, h('div')) : null;
  // 🚨 Le chatoiement de surface vit DANS le fond, sous le héros. Décision de
  // l'owner du 2026-09-09, à l'écran : le vitrage posé par-dessus l'illustration
  // irisait le personnage lui-même, ce qui le dénature ; seul le FOND est
  // holographique, le héros reste net devant.
  //
  // Il est le dernier enfant du fond, donc au-dessus de la trame, des cadres,
  // de la vignette et du halo — mais l'illustration du héros est un frère de
  // `.chero-fond` déclaré APRÈS lui, et le héros libre monte en plus à
  // `translateZ(56px)` : il passe devant dans les deux régimes, à plat comme
  // en 3D.
  const fond = h('div', { class: 'chero-fond' },
    l1, l2, l3, cadres, bullesLoin, bullesPres,
    h('div', { class: 'chero-vignette' }), halo,
    holoBords ? null : holo);

  const avecParticules = c.particules !== 'aucune' && !SOBRE();
  const canvas = avecParticules
    ? h('canvas', { class: 'chero-canvas', 'aria-hidden': 'true' })
    : null;

  // 🚨 En mode piloté (l'overlay), les illustrations passent DEVANT tout le
  // reste. Mesuré le 2026-09-08 à 700 kbit/s : l'overlay précharge le jeu
  // entier au boot, et la carte demandée pendant ce préchargement partait en
  // FIN de file — ses deux images n'avaient pas commencé à charger 14 s après
  // l'ouverture, et la carte s'affichait sans son héros. Le symptôme grandit
  // avec le nombre de cartes : à cinq il coûtait la dernière du registre.
  // `high` ne réserve pas de bande passante, il réordonne la file — c'est
  // exactement ce qu'il faut ici, puisque le préchargement peut attendre.
  const priorite = interactif ? null : 'high';
  const img = (source, alt, chargement) => {
    const { avif, webp } = paire(source);
    return h('picture', {},
      h('source', { srcset: avif, type: 'image/avif' }),
      h('img', {
        src: webp, alt, loading: chargement, decoding: 'async',
        fetchPriority: priorite,
      }),
    );
  };
  // 🚨 `lazy` seulement quand un humain pointe la carte. Piloté par script
  // (l'overlay), TOUT est `eager` : une image `loading="lazy"` dont le nœud
  // n'est pas encore dans le document ne commence JAMAIS son chargement, et
  // son `decode()` reste en attente indéfiniment — vérifié au navigateur le
  // 2026-09-08. La chorégraphie attendait donc pour rien, tombait sur son
  // plafond et jouait la carte SANS ses illustrations, qui apparaissaient
  // ensuite une par une. C'est ce qui donnait « parfois il n'y a que le
  // fond », et l'avant-plan de Claker manquant.
  const chargement = interactif ? 'lazy' : 'eager';
  const clip = h('div', { class: 'chero-clip' }, img(c.hero, c.nom, chargement));
  // `eager` sur le calque de survol : quand c'est une SECONDE illustration, la
  // charger paresseusement ferait apparaître un trou à l'ouverture de la carte
  // — le calque du repos passe à `opacity: 0` en même temps. Quand les deux
  // visuels sont la même image (le cas courant), la requête est déjà faite et
  // `eager` ne coûte rien.
  const libre = h('div', { class: 'chero-libre', 'aria-hidden': 'true' },
    img(c.hero3d || c.hero, '', 'eager'));

  // L'avant-plan (les pieds de Claker, par exemple) : la couche qui passe
  // DEVANT le héros. Elle n'existe que si la carte en déclare une.
  const apClip = c.avantPlan
    ? h('div', { class: 'chero-ap-clip' }, img(c.avantPlan, '', chargement))
    : null;
  const apLibre = c.avantPlan
    ? h('div', { class: 'chero-ap-libre', 'aria-hidden': 'true' },
        img(c.avantPlan, '', 'eager'))
    : null;

  const bords = {};
  const reflet = c.reflet
    ? h('div', { class: 'chero-reflet' }, ...BORDS.map((nom) => {
      const el = h('div', { 'data-bord': nom });
      bords[nom] = el;
      return el;
    }))
    : null;
  const bord = h('div', { class: 'chero-bord', 'data-z': '30' },
    reflet,
    holoBords ? holo : null,
    c.selectionnee ? h('div', { class: 'chero-selection' }) : null,
  );

  const cout = h('div', { class: 'chero-cout', 'data-z': '70', 'data-net': '1' },
    h('span', { class: 'chero-cout-n', text: String(c.cout) }),
    h('span', { class: 'chero-cout-lbl', text: 'ULTIME' }),
  );

  // Le cartouche de rareté, sous le coût. Il monte au MÊME Z que lui (70) et
  // compense la perspective comme lui (`data-net`) : il porte du texte de
  // 9 px, et 6,4 % d'agrandissement suffisent à l'empâter.
  const cartouche = h('div', { class: 'chero-rarete', 'data-z': '70', 'data-net': '1' },
    h('span', { text: RARETES[c.rarete] || RARETES.indefinie }));

  // 🚨 Le nom en FOIL, et seulement sur les cartes qui portent déjà le
  // vitrage EN SURFACE. Sur la variante `bords`, l'irisation est confinée au
  // liseré par choix — un titre irisé la ferait déborder au milieu de la
  // carte, ce que la variante existe justement pour éviter.
  const nomFoil = c.holographique && !holoBords && RARETES_HAUTES.has(c.rarete);
  const nom = h('span', {
    class: `chero-nom${nomFoil ? ' chero-nom--foil' : ''}`, text: c.nom });
  const bas = h('div', { class: 'chero-bas', 'data-z': '70', 'data-net': '1' },
    h('div', {}, nom),
    h('div', { class: 'chero-fiche' },
      h('div', { class: 'chero-fiche-top' },
        h('span', { text: c.classe }),
        h('span', { class: 'chero-ult', text: `ULT · ${c.ultime}` }),
      ),
      h('p', { class: 'chero-desc', text: c.description }),
      h('p', { class: 'chero-ambiance', text: c.ambiance }),
      // 🚨 Une stat à ZÉRO n'est pas une petite stat : c'est une stat qui
      // n'est pas décidée (cf. l'en-tête de `tcg/cartes.yaml`). Elle passe
      // donc au NEUTRE. Peinte en rouge vif comme un vrai 9, elle prétend
      // être une valeur de jeu — c'est ce que faisaient les cinq cartes
      // jusqu'au 2026-09-09.
      //
      // ⚠️ Les trois teintes ne suivent PAS `--chero-acc`, et c'est
      // délibéré : rouge/vert/violet distinguent l'attaque, les PV et l'aura
      // d'un coup d'œil. Les fondre dans l'accent de la carte ferait joli et
      // coûterait le seul code de lecture des stats.
      h('div', { class: 'chero-stats' },
        ...[['atk', 'ATK', c.atk], ['pv', 'PV', c.pv], ['aura', 'AURA', c.aura]]
          .map(([cle, libelle, valeur]) => h('span', {
            class: `chero-stat chero-stat-${cle}${valeur ? '' : ' chero-stat--vide'}`,
            text: `${libelle} ${valeur}`,
          })),
      ),
    ),
  );

  const plateau = h('div', { class: 'chero-carte' },
    fond,
    canvas,
    h('div', { class: 'chero-cadrage' }, clip),
    libre,
    apClip ? h('div', { class: 'chero-cadrage' }, apClip) : null,
    apLibre,
    bord,
    cout,
    cartouche,
    bas,
  );

  // Le palier part en ATTRIBUT et pas en classe : le CSS a besoin de le
  // lire, et un attribut nommé dit ce qu'il porte là où `chero--ange` ne dit
  // rien.
  const racine = h('div', { class: 'chero', 'data-rarete': c.rarete },
    h('div', { class: 'chero-ombre' }), plateau);
  racine.style.cssText = `--chero-acc:${c.accent}`
    + `;--chero-cote:${c.heroCote}`
    + `;--chero-haut:${c.heroHaut}`
    + `;--chero-echelle:${c.heroEchelle}`
    + `;--chero-ap-largeur:${c.avantPlanLargeur}`
    + `;--chero-ap-bas:${c.avantPlanBas}`
    + `;--chero-3d-cote:${c.hero3dCote || c.heroCote}`
    + `;--chero-3d-haut:${c.hero3dHaut || c.heroHaut}`
    + (depli ? `;--chero-depli:${depli}` : '')
    + (etape ? `;--chero-etape:${etape}` : '');

  // Le fond est un `background-image`, il n'a pas de `<picture>`. Les deux
  // affectations SONT le repli : un navigateur qui ne comprend pas
  // `image-set()` (ou son `type()`) rejette la seconde et garde le WebP. Sans
  // la première, il n'aurait pas de fond du tout.
  const fondSrc = paire(c.fond);
  l1.style.backgroundImage = `url('${fondSrc.webp}')`;
  l1.style.backgroundImage = `image-set(url('${fondSrc.avif}') type("image/avif"),`
    + ` url('${fondSrc.webp}') type("image/webp"))`;

  const boite = h('div', { class: 'chero-boite' }, racine);

  // ── Le comportement ─────────────────────────────────────────────────────
  const etat = { survol: false, visible: true, vent: 0 };
  const zEls = [bord, cout, cartouche, bas];
  const particulesCarte = canvas ? particules(canvas, etat, c.particules) : null;
  let dansBoucle = false;
  let minuteurAplat = 0;
  let minuteurLissage = 0;

  const syncBoucle = () => {
    if (!particulesCarte) return;
    if (etat.visible && !dansBoucle) {
      BOUCLE.ajouter(particulesCarte.pas);
      dansBoucle = true;
    } else if (!etat.visible && dansBoucle) {
      BOUCLE.retirer(particulesCarte.pas);
      dansBoucle = false;
    }
  };

  // Le halo ne pulse que sur la carte SURVOLÉE et visible : vingt dégradés
  // animés au repos, c'est vingt calques de trop.
  const syncHalo = () => {
    const actif = c.pulsation && etat.survol && etat.visible && !SOBRE();
    halo.style.animation = actif ? 'chero-pulse 2.8s ease-in-out infinite' : '';
    halo.style.opacity = actif ? '' : '.7';
  };

  /** Le `transform` d'une couche qui monte en Z.
   *
   * 🚨 Les couches qui portent du TEXTE compensent l'agrandissement de la
   * perspective. À `translateZ(70px)` sous `perspective: 1100px`, un élément
   * grossit de 6,8 % — et Chromium le rastérise à sa taille d'origine AVANT
   * de l'étirer. Le texte des stats en sortait visiblement flou : vérifié en
   * l'agrandissant trois fois, bords des lettres empâtés, là où
   * `will-change: transform` ne changeait RIEN. Compenser rend le rendu aussi
   * net qu'à plat.
   *
   * Les autres couches — fond, cadres, héros, liseré — gardent leur
   * grossissement : c'est lui qui fait voir la profondeur, et elles n'ont pas
   * de texte à abîmer.
   */
  const zTransform = (el) => {
    const z = Number(el.dataset.z) || 0;
    if (el.dataset.net !== '1') return `translateZ(${z}px)`;
    return `translateZ(${z}px) scale(${((1100 - z) / 1100).toFixed(5)})`;
  };

  const set3d = (actif) => {
    if (actif) {
      racine.style.zIndex = '10';
      racine.style.perspective = '1100px';
      plateau.style.transformStyle = 'preserve-3d';
      plateau.style.willChange = 'transform';
      [l1, l2, l3, cadres].forEach((el) => { el.style.willChange = 'transform'; });
      // Les Z montent à l'image SUIVANTE : posés dans la même frame que la
      // perspective, ils n'ont pas d'état de départ et sautent sans transition.
      requestAnimationFrame(() => {
        if (!etat.survol) return;
        zEls.forEach((el) => { el.style.transform = zTransform(el); });
        // Le premier pas seulement : la suite est écrite par `incliner()`,
        // qui calcule l'avancement.
        libre.style.transform = 'translateZ(0px) scale(1)';
        if (apLibre) apLibre.style.transform = 'translateZ(0px) scale(1)';
        if (canvas) canvas.style.transform = 'translateZ(8px)';
      });
    } else {
      zEls.forEach((el) => { el.style.transform = 'translateZ(0px)'; });
      libre.style.transform = 'translateZ(0px) scale(1)';
      if (apLibre) apLibre.style.transform = 'translateZ(0px) scale(1)';
      if (canvas) canvas.style.transform = 'translateZ(0px)';
    }
  };

  // La perspective n'est retirée qu'une fois tout revenu à plat : à Z 0, la
  // coupure est invisible. L'enlever tout de suite ferait sauter la carte.
  const aplatir = () => {
    if (etat.survol) return;
    racine.style.zIndex = '';
    racine.style.perspective = '';
    plateau.style.transformStyle = '';
    plateau.style.willChange = '';
    zEls.forEach((el) => { el.style.transform = ''; });
    libre.style.transform = '';
    if (apLibre) apLibre.style.transform = '';
    if (canvas) canvas.style.transform = '';
    [l1, l2, l3, cadres].forEach((el) => { el.style.willChange = ''; });
  };

  /** Incline la carte. `nx` et `ny` ∈ [−0.5, +0.5], 0,0 au centre.
   *
   * 🚨 Le calcul depuis un événement de pointeur ne disparaît pas : il vit
   * chez l'appelant (`surMouvement`). C'est ce qui rend la carte jouable SANS
   * curseur — l'overlay OBS n'en a pas, et sa chorégraphie appelle ici
   * directement, depuis sa propre horloge.
   *
   * ⚠️ Un seul écrivain sur le `transform` du plateau. Deux `transform` sur un
   * même nœud ne se cumulent pas, ils se REMPLACENT : une chorégraphie qui
   * écrirait le style en parallèle effacerait l'inclinaison, ou l'inverse.
   */
  /** L'avancement du dépliage, de 0 à 1, adouci. */
  const ouverture = () => {
    if (!ouvertA) return 1;
    const t = Math.min(1, (performance.now() - ouvertA) / lissageMs);
    // La même allure que les transitions CSS des autres couches : parti vite,
    // fini doucement. Le héros doit les accompagner, pas les devancer.
    return 1 - (1 - t) ** 3;
  };

  const incliner = (nx, ny) => {
    dernierNx = nx;
    dernierNy = ny;
    const max = 15 * c.intensite;
    const tiltX = nx * max * 2;
    const tiltY = ny * max * 2;
    plateau.style.transform = `rotateX(${(-tiltY).toFixed(2)}deg)`
      + ` rotateY(${tiltX.toFixed(2)}deg) scale(1.04)`;
    etat.vent = tiltX * 0.06;
    const p = c.parallaxe * 1.4;
    const tx = tiltX * p;
    const ty = tiltY * p;
    l1.style.transform = `translate3d(${(tx * 1.1).toFixed(1)}px,${(ty * 1.1).toFixed(1)}px,0) scale(1.06)`;
    l2.style.transform = `translate3d(${(tx * .5).toFixed(1)}px,${(ty * .5).toFixed(1)}px,0)`;
    l3.style.transform = `translate(-50%,-50%) translate3d(${(tx * 1.6).toFixed(1)}px,${(ty * 1.6).toFixed(1)}px,0)`;
    cadres.style.transform = `translate3d(${(tx * 2.4).toFixed(1)}px,${(ty * 2.4).toFixed(1)}px,0)`;
    // Les deux nappes de bulles se séparent en profondeur : la proche bouge
    // 2,5 fois la lointaine. C'est cet écart, et pas leur montée, qui donne
    // l'impression d'eau — la montée seule se lit comme un fond animé.
    if (bullesLoin) bullesLoin.style.transform = `translate3d(${(tx * .7).toFixed(1)}px,${(ty * .7).toFixed(1)}px,0)`;
    if (bullesPres) bullesPres.style.transform = `translate3d(${(tx * 1.8).toFixed(1)}px,${(ty * 1.8).toFixed(1)}px,0)`;
    // Héros et avant-plan sont écrits dans la MÊME image : sinon le héros
    // monte en Z avant les pieds et lui passe devant quelques frames.
    // Le Z et l'échelle suivent l'avancement : la couche s'élève et grandit
    // en même temps que les autres montent, au lieu d'y sauter.
    const av = ouverture();
    libre.style.transform = `translateZ(${(56 * av).toFixed(1)}px) translate3d(${(tx * 1.6).toFixed(1)}px,${(ty * 1.6).toFixed(1)}px,0) scale(${(1 + (c.heroEchelle - 1) * av).toFixed(4)})`;
    if (apLibre) {
      apLibre.style.transform = `translateZ(${(62 * av).toFixed(1)}px) translate3d(${(tx * 2.8).toFixed(1)}px,${(ty * 2.8).toFixed(1)}px,0) scale(${(1 + 0.16 * av).toFixed(4)})`;
    }
    // Le bord tourné vers la lumière (en haut à gauche) s'allume, l'opposé
    // s'éteint : c'est ça qui fait « carte plastifiée » plutôt qu'un balayage.
    const lx = -nx * 2;
    const ly = -ny * 2;
    // `--chero-reflet` module le contraste des quatre bords. Réglé pour une
    // carte de galerie, à 340 px, où un éclat franc serait criard ; l'overlay
    // la montre à 680 px, seule sur l'écran et regardée — il le monte.
    const eclat = (v) => Math.min(1, .12 + Math.max(0, v) * .95 * gainReflet).toFixed(2);
    // Le chatoiement suit l'inclinaison : la teinte tourne avec l'angle et le
    // dégradé glisse. Trois variables, écrites dans la même image que le
    // reste — pas de boucle propre, pas de second réveil par frame.
    if (holo) {
      // L'ORIENTATION des bandes tourne avec l'inclinaison, et le dégradé
      // glisse : c'est la combinaison des deux qui donne le reflet qui
      // « coule » sur la carte plutôt qu'un motif qui se translate.
      holo.style.setProperty('--chero-holo-a', `${(108 + nx * 40).toFixed(1)}deg`);
      holo.style.setProperty('--chero-holo-x', `${(50 + nx * 160).toFixed(1)}%`);
      holo.style.setProperty('--chero-holo-y', `${(50 + ny * 160).toFixed(1)}%`);
    }
    if (bords.gauche) bords.gauche.style.opacity = eclat(lx);
    if (bords.droite) bords.droite.style.opacity = eclat(-lx);
    if (bords.haut) bords.haut.style.opacity = eclat(ly);
    if (bords.bas) bords.bas.style.opacity = eclat(-ly);
  };

  // Le suivi du pointeur, coalescé dans un `requestAnimationFrame` : un
  // `pointermove` arrive plus souvent qu'une image sur un pavé tactile, et
  // chaque passage écrit sept transforms.
  //
  // ⚠️ La coalescence reste ICI, sur le chemin du pointeur, et pas dans
  // `incliner()` : la chorégraphie de l'overlay appelle déjà depuis une
  // boucle, un second rAF lui coûterait une image de retard.
  let attend = false;
  let px = 0;
  let py = 0;

  const inclinerVersLeCurseur = () => {
    attend = false;
    if (!etat.survol) return;
    const r = racine.getBoundingClientRect();
    if (!r.width || !r.height) return;
    incliner((px - r.left) / r.width - .5, (py - r.top) / r.height - .5);
  };

  const surMouvement = (e) => {
    px = e.clientX;
    py = e.clientY;
    if (!attend) {
      attend = true;
      requestAnimationFrame(inclinerVersLeCurseur);
    }
  };

  const entrer = (e) => {
    if (etat.survol) return;
    etat.survol = true;
    if (e) { px = e.clientX; py = e.clientY; }
    clearTimeout(minuteurAplat);
    clearTimeout(minuteurLissage);
    set3d(true);
    // 🚨 Deux besoins opposés sur le même `transform`, et il a fallu les
    // séparer :
    //
    // · le SAUT d'entrée (de plat à incliné, en une écriture) doit être lissé,
    //   sinon la carte claque en 3D sans transition ;
    // · le SUIVI continu ne doit PAS l'être — la chorégraphie écrit une
    //   nouvelle cible toutes les 33 ms, et une transition de 160 ms n'atteint
    //   jamais la sienne avant d'être remplacée. Elle traîne à un cinquième du
    //   parcours : mesuré, ±0,3° d'inclinaison au lieu de ±5,8°.
    //
    // On pose donc la transition pour l'entrée, et on la RETIRE une fois
    // qu'elle a joué. Sous le curseur, `pointermove` la remplace de lui-même
    // à chaque mouvement, il n'y a rien à retirer.
    plateau.style.transition = `transform ${lissageMs}ms cubic-bezier(.2,.8,.2,1)`;
    ouvertA = performance.now();
    // 🚨 Le dépliage tourne sur la boucle partagée le temps qu'il dure.
    //
    // Sans ça il ne progressait qu'à chaque `pointermove` : un survol SANS
    // bouger la souris — pointer la carte et s'arrêter — figeait le héros à
    // son premier pas, `translateZ(1px)`. Le liseré, lui à 30, passait alors
    // devant. Sur l'overlay le défaut ne se voyait pas : la chorégraphie
    // appelle `incliner()` trente fois par seconde de toute façon.
    if (arretDepliage) arretDepliage();
    arretDepliage = abonnerAnimation(() => {
      incliner(dernierNx, dernierNy);
      if (performance.now() - ouvertA >= lissageMs) {
        arretDepliage();
        arretDepliage = null;
      }
    });
    minuteurLissage = setTimeout(() => {
      plateau.style.transition = interactif ? 'transform .16s ease-out' : 'none';
    }, lissageMs);
    cadres.style.visibility = 'visible';
    cadres.style.opacity = '1';
    if (reflet) { reflet.style.visibility = 'visible'; reflet.style.opacity = '.9'; }
    if (holo) holo.style.opacity = String(OPACITE_HOLO);
    if (!SOBRE()) nom.style.animation = 'chero-float 3.2s ease-in-out infinite';
    if (particulesCarte) particulesCarte.bouffee();
    if (c.debordement) {
      libre.style.visibility = 'visible';
      libre.style.opacity = '1';
      clip.style.opacity = '0';
      if (apLibre) { apLibre.style.visibility = 'visible'; apLibre.style.opacity = '1'; }
      if (apClip) apClip.style.opacity = '0';
    }
    syncBoucle();
    syncHalo();
  };

  const sortir = () => {
    if (!etat.survol) return;
    etat.survol = false;
    etat.vent = 0;
    ouvertA = 0;
    if (arretDepliage) { arretDepliage(); arretDepliage = null; }
    // Au retour au repos la transition sert dans les DEUX modes : là, il y a
    // bien un saut à lisser — de l'angle courant vers zéro, en une écriture.
    plateau.style.transition = 'transform .5s cubic-bezier(.03,.98,.52,.99)';
    plateau.style.transform = '';
    l1.style.transform = 'scale(1.06)';
    l2.style.transform = '';
    l3.style.transform = 'translate(-50%,-50%)';
    cadres.style.opacity = '0';
    cadres.style.visibility = 'hidden';
    cadres.style.transform = '';
    // Le `transform` est RETIRÉ et non remis à zéro : l'animation de montée
    // vit dans l'enfant, mais un `translate3d(0,0,0)` laissé sur le parent y
    // fabrique un contexte d'empilement pour rien.
    if (bullesLoin) bullesLoin.style.transform = '';
    if (bullesPres) bullesPres.style.transform = '';
    if (reflet) { reflet.style.opacity = '0'; reflet.style.visibility = 'hidden'; }
    if (holo) holo.style.opacity = '0';
    Object.values(bords).forEach((el) => { el.style.opacity = '.25'; });
    nom.style.animation = 'none';
    libre.style.opacity = '0';
    libre.style.visibility = 'hidden';
    clip.style.opacity = '1';
    if (apLibre) { apLibre.style.opacity = '0'; apLibre.style.visibility = 'hidden'; }
    if (apClip) apClip.style.opacity = '1';
    set3d(false);
    clearTimeout(minuteurAplat);
    minuteurAplat = setTimeout(aplatir, 520);
    syncBoucle();
    syncHalo();
  };

  // Sur un écran tactile il n'y a pas de survol : c'est le tap qui ouvre et
  // referme, sinon les cartes seraient mortes sur téléphone. Pas
  // d'inclinaison là-bas — il n'y a pas de curseur à suivre.
  const basculer = () => { if (etat.survol) sortir(); else entrer(null); };
  const tactile = TACTILE();
  if (!interactif) {
    // L'overlay ne branche RIEN : il n'a ni curseur ni doigt, et sa
    // chorégraphie appelle `ouvrir`, `incliner` et `fermer` elle-même.
  } else if (tactile) {
    racine.addEventListener('click', basculer);
  } else if (!SOBRE()) {
    racine.addEventListener('pointerenter', entrer);
    racine.addEventListener('pointermove', surMouvement, { passive: true });
    racine.addEventListener('pointerleave', sortir);
  }

  OEIL.observer(racine, (visible) => {
    etat.visible = visible;
    syncBoucle();
    syncHalo();
  });
  syncBoucle();
  syncHalo();

  const detruire = () => {
    if (arretDepliage) { arretDepliage(); arretDepliage = null; }
    clearTimeout(minuteurAplat);
    clearTimeout(minuteurLissage);
    if (dansBoucle && particulesCarte) BOUCLE.retirer(particulesCarte.pas);
    dansBoucle = false;
    OEIL.oublier(racine);
    racine.removeEventListener('click', basculer);
    racine.removeEventListener('pointerenter', entrer);
    racine.removeEventListener('pointermove', surMouvement);
    racine.removeEventListener('pointerleave', sortir);
  };

  // `ouvrir`, `fermer` et `incliner` sortent pour la chorégraphie de
  // l'overlay. `ouvrir()` passe `null` : `entrer` sait déjà se passer d'un
  // événement, c'est le chemin du tap sur téléphone.
  return { boite, detruire, ouvrir: () => entrer(null), fermer: sortir, incliner };
}
