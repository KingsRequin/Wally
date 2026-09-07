// public-ui/pages/demo-carte-azrael.js — la carte d'Azraël, en démonstration
//
// Page HORS NAVIGATION, servie à `/demo/carte-azrael` : une URL qu'on donne à
// la main pour montrer à quoi ressemblera une carte du TCG. Elle n'est ni dans
// la barre du haut, ni dans celle du pouce, ni dans les ancres héritées.
//
// 🚨 Comme `tcg-demo.js`, cette page ne calcule AUCUNE règle. La carte est un
// objet écrit à la main ci-dessous ; le moteur du jeu vit côté serveur, en
// Python. Une règle dupliquée en JavaScript est une porte de triche ouverte.
//
// Les valeurs viennent du canon du 2026-09-07 (`1219dd9c`) :
// `docs/superpowers/specs/2026-09-04-tcg-catalogue-reflexes.md` §F07 pour le
// Rework, `2026-09-05-tcg-regles-heros-tactiques.md` §2 pour le budget
// (12 + 8 d'Archange = 20 = 5 + 10 + 5).
//
// ⚠️ Elles ne coïncident PAS avec la fiche `azrael` de `tcg-demo.js`, qui
// montre encore un Azraël de rareté Âme (3/6/3, « Le mur tient »). Ce fichier
// se déclare lui-même comme un jeu de placeholders ; l'écart est à arbitrer par
// l'owner, pas ici.

import { h } from '../app.js';

// ── La carte ──────────────────────────────────────────────────────────────
const CARTE = {
  nom: 'AZRAËL',
  classe: 'ARCHANGE · UNIQUE',
  ultime: 'REWORK',
  cout: 10,
  atk: 5,
  pv: 10,
  aura: 5,
  description: 'Rework : désigne un héros adverse. Pour le reste de la partie, '
    + 'son Ultime coûte +3 et tous ses nombres baissent de 2.',
  ambiance: 'Il ne te dit jamais non. Il attend le prochain patch, '
    + 'et un matin plus personne ne te craint.',
  hero: '/assets/tcg-azrael-hero.webp',
  fond: '/assets/tcg-azrael-fond.webp',
};

// L'accent de la carte. `--gold` du thème braise vaut déjà `#ffb02e`, la
// couleur de la maquette : la carte le lit par défaut depuis le CSS, et cette
// constante n'existe que pour la lueur des braises, qui se dessine au canvas
// et n'a donc pas accès à la cascade.
const ACCENT = '#ffb02e';

// L'inclinaison au curseur, en degrés à fond de course. La maquette la tenait
// avec vanilla-tilt ; 30 lignes ici évitent une dépendance de plus pour une
// seule page. Le `brancherTilt()` de la coquille ne convient pas : il écrit un
// `transform` et ne publie AUCUN angle, alors que tout le parallaxe de la carte
// est piloté par les deux variables `--dca-px/py` dérivées de cet angle.
const TILT_MAX = 15;
const TILT_ECHELLE = 1.04;
const TILT_MS = 900;
const TILT_EASE = 'cubic-bezier(.03,.98,.52,.99)';
const PARALLAXE = 1.4;

// La feuille de la page et la police du titre : chargées au montage, retirées
// au démontage. Archivo Black ne sert QU'ICI — l'ajouter à la ligne de polices
// d'`index.html` la ferait télécharger par les cinq pages du site.
const FEUILLE = '/pages/demo-carte-azrael.css';
const POLICE = 'https://fonts.googleapis.com/css2?family=Archivo+Black&display=swap';

let _etat = null;

/** Pose un `<link>` dans le `<head>` et rend de quoi le retirer. */
function poserLien(href) {
  const existant = document.head.querySelector(`link[href="${href}"]`);
  if (existant) return () => {};
  const lien = document.createElement('link');
  lien.rel = 'stylesheet';
  lien.href = href;
  document.head.appendChild(lien);
  return () => lien.remove();
}

// ── Les braises ───────────────────────────────────────────────────────────

/** Dessine les braises dans le canvas et rend un objet de pilotage.
 *
 * Trente particules, 30 images par seconde, en pause dès que la carte sort de
 * l'écran ou que l'onglet passe en arrière-plan. Les lueurs sont pré-rendues
 * une fois dans des sprites de 64 px : un dégradé radial par particule et par
 * image coûterait trente créations de dégradé à chaque frame.
 */
function braises(canvas, ctxSurvol) {
  const L = 340;
  const H = 476;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = L * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const S = 64;
  const sprite = (dessin) => {
    const o = document.createElement('canvas');
    o.width = S;
    o.height = S;
    dessin(o.getContext('2d'), S / 2);
    return o;
  };
  const lueur = (c0, c1, c2) => sprite((x, m) => {
    const g = x.createRadialGradient(m, m, 0, m, m, m);
    g.addColorStop(0, c0);
    g.addColorStop(0.3, c1);
    g.addColorStop(1, c2);
    x.fillStyle = g;
    x.fillRect(0, 0, S, S);
  });
  const noyau = (sombre, clair) => sprite((x, m) => {
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

  const SPRITES = {
    braise: { lueur: lueur('rgba(255,90,20,.9)', 'rgba(230,50,10,.6)', 'rgba(160,20,0,0)'), noyau: noyau('rgba(20,6,4,.9)', 'rgba(255,70,20,1)') },
    chaude: { lueur: lueur('rgba(255,220,150,1)', 'rgba(230,50,10,.6)', 'rgba(160,20,0,0)'), noyau: noyau('rgba(20,6,4,.9)', 'rgba(255,200,120,1)') },
    cendre: { lueur: null, noyau: noyau('rgba(12,8,6,.85)', 'rgba(120,30,10,.5)') },
  };

  const N = 30;
  const vivantes = [];
  const semer = (e, initiale, jet) => {
    e.x = jet ? L * (0.3 + Math.random() * 0.4) : 10 + Math.random() * (L - 20);
    e.y = initiale ? Math.random() * H : (jet ? H * 0.72 : H * (0.6 + Math.random() * 0.4));
    e.r = 1 + Math.random() * 2.6;
    e.vy = jet ? 1.6 + Math.random() * 1.8 : 0.3 + Math.random() * 0.7;
    e.vx = jet ? (Math.random() - 0.5) * 2.4 : 0;
    e.ph = Math.random() * Math.PI * 2;
    e.sw = 0.3 + Math.random() * 0.7;
    e.vie = 0;
    e.max = jet ? 120 + Math.random() * 100 : 260 + Math.random() * 300;
    e.type = Math.random() < 0.22 ? 'cendre' : (Math.random() < 0.25 ? 'chaude' : 'braise');
    e.jet = !!jet;
    return e;
  };
  for (let i = 0; i < N; i += 1) vivantes.push(semer({}, true));

  const pilote = {
    raf: 0,
    visible: true,
    pause: false,
    /** Une bouffée de braises au survol : douze particules jetées vers le haut,
     * qui meurent au lieu de se re-semer. */
    bouffee() {
      for (let i = 0; i < 12; i += 1) vivantes.push(semer({}, false, true));
    },
    detruire() {},
  };

  let t = 0;
  let derniere = 0;
  const image = (maintenant) => {
    if (pilote.pause) { pilote.raf = 0; return; }
    pilote.raf = requestAnimationFrame(image);
    if (maintenant - derniere < 31) return; // ~30 images/s
    derniere = maintenant;
    t += 2;
    ctx.clearRect(0, 0, L, H);
    for (let i = vivantes.length - 1; i >= 0; i -= 1) {
      const e = vivantes[i];
      e.vie += 2;
      e.y -= e.vy * 2;
      e.x += (Math.sin(t * 0.02 + e.ph) * e.sw * 0.5 + ctxSurvol.vent + e.vx) * 2;
      e.vx *= 0.92;
      if (e.jet) e.vy *= 0.97;
      const k = e.vie / e.max;
      if (e.y < -12 || e.vie > e.max || e.x < -10 || e.x > L + 10) {
        if (e.jet) { vivantes.splice(i, 1); continue; }
        semer(e, false);
      }
      const a = k < 0.12 ? k / 0.12 : 1 - (k - 0.12) / 0.88;
      const scintille = 0.6 + 0.4 * Math.sin(t * 0.3 + e.ph * 3) * Math.sin(t * 0.07 + e.ph);
      const sp = SPRITES[e.type];
      ctx.globalAlpha = Math.max(0, Math.min(1, a * scintille));
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

  const synchroniser = () => {
    pilote.pause = !pilote.visible || document.hidden;
    if (!pilote.pause && !pilote.raf) pilote.raf = requestAnimationFrame(image);
  };
  const oeil = new IntersectionObserver((entrees) => {
    pilote.visible = entrees[0].isIntersecting;
    synchroniser();
  }, { threshold: 0.02 });
  oeil.observe(canvas);
  const surVisibilite = () => synchroniser();
  document.addEventListener('visibilitychange', surVisibilite);

  pilote.detruire = () => {
    if (pilote.raf) cancelAnimationFrame(pilote.raf);
    pilote.raf = 0;
    pilote.pause = true;
    oeil.disconnect();
    document.removeEventListener('visibilitychange', surVisibilite);
  };

  pilote.raf = requestAnimationFrame(image);
  return pilote;
}

// ── L'inclinaison ─────────────────────────────────────────────────────────

/** Branche l'inclinaison au curseur sur la carte. Rend de quoi la débrancher.
 *
 * Le suivi est coalescé dans un `requestAnimationFrame` : un `pointermove`
 * arrive plus souvent qu'une image sur un pavé tactile, et chaque écriture de
 * `--dca-px` invalide le style de neuf couches.
 */
function inclinaison(wrap, carte, survol) {
  let dernier = null;
  let raf = 0;
  let minuteur = 0;

  const ecrire = () => {
    raf = 0;
    if (!dernier) return;
    const { tiltX, tiltY } = dernier;
    carte.style.transform = `perspective(1100px) rotateX(${tiltY.toFixed(2)}deg)`
      + ` rotateY(${tiltX.toFixed(2)}deg)`
      + ` scale3d(${TILT_ECHELLE}, ${TILT_ECHELLE}, ${TILT_ECHELLE})`;
    wrap.style.setProperty('--dca-px', `${(tiltX * PARALLAXE).toFixed(2)}px`);
    wrap.style.setProperty('--dca-py', `${(-tiltY * PARALLAXE).toFixed(2)}px`);
    wrap.style.setProperty('--dca-sx', `${(50 - tiltX * 3.2).toFixed(1)}%`);
    survol.vent = tiltX * 0.06;
  };

  const surMouvement = (e) => {
    const r = carte.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top) / r.height;
    dernier = {
      tiltX: TILT_MAX - x * TILT_MAX * 2,
      tiltY: y * TILT_MAX * 2 - TILT_MAX,
    };
    if (!raf) raf = requestAnimationFrame(ecrire);
  };

  // La transition n'est POSÉE qu'à l'entrée et à la sortie. La laisser en
  // permanence ferait traîner la carte derrière le curseur ; l'enlever tout à
  // fait ferait sauter le retour au repos.
  const lisser = () => {
    carte.style.transition = `transform ${TILT_MS}ms ${TILT_EASE}`;
    clearTimeout(minuteur);
    minuteur = setTimeout(() => { carte.style.transition = ''; }, TILT_MS);
  };

  const surSortie = () => {
    dernier = null;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    lisser();
    carte.style.transform = '';
    wrap.style.setProperty('--dca-px', '0px');
    wrap.style.setProperty('--dca-py', '0px');
    wrap.style.setProperty('--dca-sx', '50%');
    survol.vent = 0;
  };

  carte.addEventListener('pointerenter', lisser);
  carte.addEventListener('pointermove', surMouvement);
  carte.addEventListener('pointerleave', surSortie);

  return () => {
    clearTimeout(minuteur);
    if (raf) cancelAnimationFrame(raf);
    carte.removeEventListener('pointerenter', lisser);
    carte.removeEventListener('pointermove', surMouvement);
    carte.removeEventListener('pointerleave', surSortie);
  };
}

// ── Le DOM de la carte ────────────────────────────────────────────────────

function carteDom(c) {
  const fond = h('div', { class: 'dca-fond' },
    h('div', { class: 'dca-fond-img', style: `--dca-fond-url: url('${c.fond}')` }),
    h('div', { class: 'dca-trame' }),
    h('div', { class: 'dca-rayons' }),
    h('div', { class: 'dca-cadre dca-cadre-1' }),
    h('div', { class: 'dca-cadre dca-cadre-2' }),
    h('div', { class: 'dca-cadre dca-cadre-3' }),
    h('div', { class: 'dca-cadre dca-cadre-4' }),
    h('div', { class: 'dca-vignette' }),
    h('div', { class: 'dca-lueur' }),
  );

  // Le héros deux fois : détouré par la carte au repos, libre de déborder au
  // survol. `aria-hidden` sur le second — c'est la même personne.
  const clip = h('div', { class: 'dca-clip' },
    h('div', { class: 'dca-clipped' },
      h('img', { src: c.hero, alt: c.nom, loading: 'eager', decoding: 'async' })),
  );
  const libre = h('div', { class: 'dca-libre', 'aria-hidden': 'true' },
    h('div', { class: 'dca-libre-img' },
      h('img', { src: c.hero, alt: '', decoding: 'async' })),
  );

  const bord = h('div', { class: 'dca-bord' }, h('div', { class: 'dca-reflet' }));

  const cout = h('div', { class: 'dca-cout' },
    h('span', { class: 'dca-cout-n', text: String(c.cout) }),
    h('span', { class: 'dca-cout-lbl', text: 'ULTIME' }),
  );

  const bas = h('div', { class: 'dca-bas' },
    h('div', { class: 'dca-nom-plan' },
      h('span', { class: 'dca-nom', text: c.nom })),
    h('div', { class: 'dca-fiche' },
      h('div', { class: 'dca-fiche-top' },
        h('span', { text: c.classe }),
        h('span', { class: 'dca-ult', text: `ULT · ${c.ultime}` }),
      ),
      h('p', { class: 'dca-desc', text: c.description }),
      h('p', { class: 'dca-ambiance', text: c.ambiance }),
      h('div', { class: 'dca-stats' },
        h('span', { class: 'dca-stat dca-stat-atk', text: `ATK ${c.atk}` }),
        h('span', { class: 'dca-stat dca-stat-pv', text: `PV ${c.pv}` }),
        h('span', { class: 'dca-stat dca-stat-aura', text: `AURA ${c.aura}` }),
      ),
    ),
  );

  const canvas = h('canvas', { class: 'dca-braises', 'aria-hidden': 'true' });
  const carte = h('div', { class: 'dca-carte' }, fond, canvas, clip, libre, bord, cout, bas);
  const wrap = h('div', { class: 'dca-wrap' }, h('div', { class: 'dca-ombre' }), carte);

  return { wrap, carte, canvas };
}

// ── Montage ───────────────────────────────────────────────────────────────

export function mount(el) {
  const retirerFeuille = poserLien(FEUILLE);
  const retirerPolice = poserLien(POLICE);

  const { wrap, carte, canvas } = carteDom(CARTE);
  const echelle = h('div', { class: 'dca-echelle' }, wrap);
  const scene = h('section', { class: 'dca-scene' },
    echelle,
    h('div', {
      class: 'dca-note',
      text: 'MAQUETTE — LA CARTE NE SE JOUE PAS ENCORE',
    }),
  );
  el.appendChild(scene);

  // Le mouvement n'est pas le sujet : sous `prefers-reduced-motion`, les
  // braises ne démarrent pas du tout et la carte ne s'incline plus. Couper
  // seulement les animations CSS laisserait tourner la boucle du canvas.
  const sobre = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const survol = { vent: 0 };
  const pilote = sobre ? null : braises(canvas, survol);
  const debrancherTilt = sobre ? null : inclinaison(wrap, carte, survol);

  // L'état « ouvert » : les quatre cadres, le reflet, le débordement du héros
  // et le flottement du nom. Sur un écran tactile il n'y a pas de survol —
  // c'est le tap qui bascule, sinon la démo serait morte sur téléphone.
  const tactile = window.matchMedia('(hover: none)').matches;
  const ouvrir = () => {
    wrap.classList.add('dca-ouvert');
    wrap.style.setProperty('--dca-d', '1');
    if (pilote) pilote.bouffee();
  };
  const fermer = () => {
    wrap.classList.remove('dca-ouvert');
    wrap.style.setProperty('--dca-d', '0');
  };
  const basculer = () => {
    if (wrap.classList.contains('dca-ouvert')) fermer();
    else ouvrir();
  };

  if (tactile) {
    wrap.addEventListener('click', basculer);
  } else {
    wrap.addEventListener('pointerenter', ouvrir);
    wrap.addEventListener('pointerleave', fermer);
  }

  _etat = () => {
    if (pilote) pilote.detruire();
    if (debrancherTilt) debrancherTilt();
    wrap.removeEventListener('click', basculer);
    wrap.removeEventListener('pointerenter', ouvrir);
    wrap.removeEventListener('pointerleave', fermer);
    retirerFeuille();
    retirerPolice();
  };
}

export function unmount() {
  if (_etat) _etat();
  _etat = null;
}
