// public-ui/pages/tcg-carte-hero.js — une carte de héros du TCG
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

import { h } from '../app.js';

// La feuille de la carte et la police de son titre. Archivo Black ne sert
// QU'ICI — l'ajouter à la ligne de polices d'`index.html` la ferait
// télécharger par les cinq pages du site.
const FEUILLE = '/pages/tcg-carte-hero.css';
const POLICE = 'https://fonts.googleapis.com/css2?family=Archivo+Black&display=swap';

/** Charge la feuille et la police de la carte. Rend de quoi les retirer.
 *
 * Appelé par la page, pas par la carte : une grille de vingt cartes ne doit
 * poser le `<link>` qu'une fois.
 */
export function monterStylesCarte() {
  const liens = [FEUILLE, POLICE].map((href) => {
    if (document.head.querySelector(`link[href="${href}"]`)) return null;
    const lien = document.createElement('link');
    lien.rel = 'stylesheet';
    lien.href = href;
    document.head.appendChild(lien);
    return lien;
  });
  return () => liens.forEach((l) => l && l.remove());
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
  fond: '', hero: '',
  heroCote: '-14%', heroHaut: '4%', heroEchelle: 1.12,
  avantPlan: '', avantPlanLargeur: '86%', avantPlanBas: '-6%',
  particules: 'braises',
  intensite: 1, parallaxe: 1,
  reflet: true, pulsation: true, debordement: true, selectionnee: false,
};

const BORDS = ['haut', 'bas', 'gauche', 'droite'];

/** Construit une carte de héros. Rend `{ boite, detruire }`.
 *
 * `boite` est le nœud à insérer (il réserve la taille de la carte, échelle
 * comprise) ; `detruire()` doit être appelé au démontage de la page, sinon la
 * carte reste abonnée à la boucle et à l'œil de la page.
 */
export function carteHero(carte) {
  const c = { ...DEFAUTS, ...carte };

  const l1 = h('div', { class: 'chero-l1' });
  const l2 = h('div', { class: 'chero-l2' });
  const l3 = h('div', { class: 'chero-l3' });
  const cadres = h('div', { class: 'chero-cadres' },
    h('div'), h('div'), h('div'), h('div'));
  const halo = h('div', { class: 'chero-halo' });
  const fond = h('div', { class: 'chero-fond' },
    l1, l2, l3, cadres, h('div', { class: 'chero-vignette' }), halo);

  const avecParticules = c.particules !== 'aucune' && !SOBRE();
  const canvas = avecParticules
    ? h('canvas', { class: 'chero-canvas', 'aria-hidden': 'true' })
    : null;

  const img = (src, alt) => h('img', { src, alt, loading: 'lazy', decoding: 'async' });
  const clip = h('div', { class: 'chero-clip' }, img(c.hero, c.nom));
  const libre = h('div', { class: 'chero-libre', 'aria-hidden': 'true' }, img(c.hero, ''));

  // L'avant-plan (les pieds de Claker, par exemple) : la couche qui passe
  // DEVANT le héros. Elle n'existe que si la carte en déclare une.
  const apClip = c.avantPlan
    ? h('div', { class: 'chero-ap-clip' }, img(c.avantPlan, ''))
    : null;
  const apLibre = c.avantPlan
    ? h('div', { class: 'chero-ap-libre', 'aria-hidden': 'true' }, img(c.avantPlan, ''))
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
    c.selectionnee ? h('div', { class: 'chero-selection' }) : null,
  );

  const cout = h('div', { class: 'chero-cout', 'data-z': '70' },
    h('span', { class: 'chero-cout-n', text: String(c.cout) }),
    h('span', { class: 'chero-cout-lbl', text: 'ULTIME' }),
  );

  const nom = h('span', { class: 'chero-nom', text: c.nom });
  const bas = h('div', { class: 'chero-bas', 'data-z': '70' },
    h('div', {}, nom),
    h('div', { class: 'chero-fiche' },
      h('div', { class: 'chero-fiche-top' },
        h('span', { text: c.classe }),
        h('span', { class: 'chero-ult', text: `ULT · ${c.ultime}` }),
      ),
      h('p', { class: 'chero-desc', text: c.description }),
      h('p', { class: 'chero-ambiance', text: c.ambiance }),
      h('div', { class: 'chero-stats' },
        h('span', { class: 'chero-stat chero-stat-atk', text: `ATK ${c.atk}` }),
        h('span', { class: 'chero-stat chero-stat-pv', text: `PV ${c.pv}` }),
        h('span', { class: 'chero-stat chero-stat-aura', text: `AURA ${c.aura}` }),
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
    bas,
  );

  const racine = h('div', { class: 'chero' },
    h('div', { class: 'chero-ombre' }), plateau);
  racine.style.cssText = `--chero-acc:${c.accent}`
    + `;--chero-cote:${c.heroCote}`
    + `;--chero-haut:${c.heroHaut}`
    + `;--chero-echelle:${c.heroEchelle}`
    + `;--chero-ap-largeur:${c.avantPlanLargeur}`
    + `;--chero-ap-bas:${c.avantPlanBas}`
    + `;--chero-fond-url:url('${c.fond}')`;

  const boite = h('div', { class: 'chero-boite' }, racine);

  // ── Le comportement ─────────────────────────────────────────────────────
  const etat = { survol: false, visible: true, vent: 0 };
  const zEls = [bord, cout, bas];
  const particulesCarte = canvas ? particules(canvas, etat, c.particules) : null;
  let dansBoucle = false;
  let minuteurAplat = 0;

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
        zEls.forEach((el) => { el.style.transform = `translateZ(${el.dataset.z}px)`; });
        libre.style.transform = `translateZ(56px) scale(${c.heroEchelle})`;
        if (apLibre) apLibre.style.transform = 'translateZ(62px) scale(1.16)';
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

  // L'inclinaison, coalescée dans un `requestAnimationFrame` : un
  // `pointermove` arrive plus souvent qu'une image sur un pavé tactile, et
  // chaque passage écrit sept transforms.
  let attend = false;
  let px = 0;
  let py = 0;
  const incliner = () => {
    attend = false;
    if (!etat.survol) return;
    const max = 15 * c.intensite;
    const r = racine.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const nx = (px - r.left) / r.width - .5;
    const ny = (py - r.top) / r.height - .5;
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
    // Héros et avant-plan sont écrits dans la MÊME image : sinon le héros
    // monte en Z avant les pieds et lui passe devant quelques frames.
    libre.style.transform = `translateZ(56px) translate3d(${(tx * 1.6).toFixed(1)}px,${(ty * 1.6).toFixed(1)}px,0) scale(${c.heroEchelle})`;
    if (apLibre) {
      apLibre.style.transform = `translateZ(62px) translate3d(${(tx * 2.8).toFixed(1)}px,${(ty * 2.8).toFixed(1)}px,0) scale(1.16)`;
    }
    // Le bord tourné vers la lumière (en haut à gauche) s'allume, l'opposé
    // s'éteint : c'est ça qui fait « carte plastifiée » plutôt qu'un balayage.
    const lx = -nx * 2;
    const ly = -ny * 2;
    const eclat = (v) => Math.min(1, .12 + Math.max(0, v) * .95).toFixed(2);
    if (bords.gauche) bords.gauche.style.opacity = eclat(lx);
    if (bords.droite) bords.droite.style.opacity = eclat(-lx);
    if (bords.haut) bords.haut.style.opacity = eclat(ly);
    if (bords.bas) bords.bas.style.opacity = eclat(-ly);
  };

  const surMouvement = (e) => {
    px = e.clientX;
    py = e.clientY;
    if (!attend) {
      attend = true;
      requestAnimationFrame(incliner);
    }
  };

  const entrer = (e) => {
    if (etat.survol) return;
    etat.survol = true;
    if (e) { px = e.clientX; py = e.clientY; }
    clearTimeout(minuteurAplat);
    set3d(true);
    plateau.style.transition = 'transform .16s ease-out';
    cadres.style.visibility = 'visible';
    cadres.style.opacity = '1';
    if (reflet) { reflet.style.visibility = 'visible'; reflet.style.opacity = '.9'; }
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
    plateau.style.transition = 'transform .5s cubic-bezier(.03,.98,.52,.99)';
    plateau.style.transform = '';
    l1.style.transform = 'scale(1.06)';
    l2.style.transform = '';
    l3.style.transform = 'translate(-50%,-50%)';
    cadres.style.opacity = '0';
    cadres.style.visibility = 'hidden';
    cadres.style.transform = '';
    if (reflet) { reflet.style.opacity = '0'; reflet.style.visibility = 'hidden'; }
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
  if (tactile) {
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
    clearTimeout(minuteurAplat);
    if (dansBoucle && particulesCarte) BOUCLE.retirer(particulesCarte.pas);
    dansBoucle = false;
    OEIL.oublier(racine);
    racine.removeEventListener('click', basculer);
    racine.removeEventListener('pointerenter', entrer);
    racine.removeEventListener('pointermove', surMouvement);
    racine.removeEventListener('pointerleave', sortir);
  };

  return { boite, detruire };
}
