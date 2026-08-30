// public-ui/app.js — coquille du site public (thème braise)
//
// Rôle : le décor, la nav, l'auth, les flux partagés et le ROUTEUR. Les quatre
// pages (`pages/*.js`) n'exportent que `mount(el)` / `unmount()`.

// DÉCLARÉ AVANT LES IMPORTS, et c'est la seule chose qui compte ici : un
// `let` reste en zone morte temporelle jusqu'à sa ligne, et les modules de
// page s'évaluent AVANT elle. Placé plus bas, `nomBot()` levait
// « Cannot access 'NOM_BOT' before initialization » et cassait le site
// entier — que ni `node --check` ni le lint JS ne voient.
//
// Le nom du bot vient de la CONFIG, jamais du HTML. Ce site sert aussi Cindy,
// qui partage cette source et son API : avec « Wally » en dur, son propre site
// public l'appelait Wally — titre, wordmark et pied de page compris — pendant
// que son API répondait « Cindy ». Repli sur « Wally » tant que le status n'est
// pas revenu : c'est le cas de très loin le plus fréquent, et un nom vide serait
// pire qu'un nom par défaut.
let NOM_BOT = 'Wally';

export function nomBot() { return NOM_BOT; }

/** Applique le nom partout où il s'affiche. Idempotent : rappelable. */
function appliquerNom() {
  document.title = NOM_BOT;
  // Les emplacements se DÉCLARENT dans le DOM (`data-nom-bot`), ils ne sont
  // pas listés ici : un nouvel endroit qui porte le nom se sert tout seul.
  document.querySelectorAll('[data-nom-bot]').forEach((el) => {
    el.textContent = el.dataset.nomBot === 'maj' ? NOM_BOT.toUpperCase() : NOM_BOT;
  });
}

// Même précaution de TDZ que ci-dessus : `mount()` d'une page peut appeler
// `ensureFreshToken()` pendant l'évaluation du module.
//
// Le JWT expire après 1 h mais le refresh token vit 30 jours. Au chargement,
// si le JWT est absent/expiré, on le rafraîchit silencieusement pour rester
// connecté après un reload. La promesse est mémoïsée : app.js et la page chat
// partagent le même appel (le refresh token est à usage unique côté serveur).
let _refreshPromise = null;
export function ensureFreshToken() {
  if (_refreshPromise) return _refreshPromise;
  _refreshPromise = (async () => {
    const jwt = localStorage.getItem('discord_jwt');
    const p = jwt ? decodeJwt(jwt) : null;
    if (p && (!p.exp || p.exp * 1000 > Date.now())) return true;  // encore valide

    const refresh = localStorage.getItem('discord_refresh');
    if (!refresh) return false;

    try {
      const r = await fetch('/api/chat/auth/refresh', { headers: { Authorization: 'Bearer ' + refresh } });
      if (!r.ok) throw new Error('refresh failed');
      const d = await r.json();
      if (!d || !d.jwt) throw new Error('no jwt');
      localStorage.setItem('discord_jwt', d.jwt);
      if (d.refresh_token) localStorage.setItem('discord_refresh', d.refresh_token);
      return true;
    } catch (_) {
      // Refresh token invalide/expiré → vraie déconnexion, on nettoie
      localStorage.removeItem('discord_jwt');
      localStorage.removeItem('discord_refresh');
      return false;
    }
  })();
  _refreshPromise.finally(() => { _refreshPromise = null; });
  return _refreshPromise;
}

// ── Horloge d'animation ───────────────────────────────────────────────────
// UN seul `requestAnimationFrame` pour tout le site. Les pages s'y abonnent
// pour ce qui leur appartient — deux boucles, ce sont deux mesures du viewport
// qui divergent d'une image, et un bandeau qui ne colle plus au défilement.
//
// DÉCLARÉ ICI, avant les imports, pour la même raison que `NOM_BOT` juste
// au-dessus : le routeur monte la première page pendant l'évaluation de ce
// module, et le `mount()` de l'accueil s'abonne aussitôt. Déclaré plus bas,
// `surAnimation()` levait « Cannot access '_abonnesAnim' before
// initialization » — et un `throw` dans un `mount()` ne casse pas seulement
// l'animation : il laisse la page à moitié montée, compteurs figés compris.
const _abonnesAnim = [];

/** Abonne `fn(sy, vh, prog)` à l'horloge. Rend la fonction de désabonnement. */
export function surAnimation(fn) {
  _abonnesAnim.push(fn);
  return () => {
    const i = _abonnesAnim.indexOf(fn);
    if (i !== -1) _abonnesAnim.splice(i, 1);
  };
}

import * as pageAccueil from './pages/accueil.js';
import * as pageChat from './pages/chat.js';
import * as pageGalerie from './pages/galerie.js';
import * as pageTcg from './pages/tcg.js';

// ── Fabrique de DOM ───────────────────────────────────────────────────────
// Les pages construisent leur arbre avec `h()` : jamais d'innerHTML, jamais de
// chaîne HTML interpolée. Un titre d'image ou un pseudo peut contenir du code
// (vécu : un nom de fichier de son exécutait un `onclick` interpolé).
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'style') el.style.cssText = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k.startsWith('data-') || k === 'role' || k.startsWith('aria-')) el.setAttribute(k, v);
      else el[k] = v;
    }
  }
  kids.flat().forEach((k) => {
    if (k === null || k === undefined || k === false) return;
    el.appendChild(typeof k === 'string' || typeof k === 'number' ? document.createTextNode(String(k)) : k);
  });
  return el;
}

/** Bandeau de titre d'une section : « 03 · CHAT WEB » + h2 + chapô facultatif. */
export function sectionHead(eyebrow, titre, chapo) {
  return h('div', { class: 'reveal' },
    h('div', { class: 'eyebrow', text: eyebrow }),
    h('h2', { class: 'h2', text: titre }),
    chapo ? h('p', { class: 'lead', text: chapo }) : null,
  );
}

/** Pied de page commun aux trois pages qui défilent (le chat n'en a pas). */
export function pageFooter() {
  return h('footer', { class: 'footer' },
    h('div', { class: 'brand' },
      h('video', { src: '/wally.webm', autoplay: true, loop: true, muted: true, playsInline: true, 'aria-hidden': 'true' }),
      h('span', {}, 'fait avec une petite flamme · © 2026 ', h('span', { 'data-nom-bot': '' }, NOM_BOT)),
    ),
    h('a', { class: 'repo', href: 'https://github.com/KingsRequin/Wally', target: '_blank', rel: 'noopener', text: 'github.com/KingsRequin/Wally' }),
  );
}

// ── État émotionnel partagé ───────────────────────────────────────────────
export const emotions = { anger: 0, joy: 0, curiosity: 0, sadness: 0, boredom: 0 };
const emotionListeners = [];
export function onEmotionUpdate(fn) {
  emotionListeners.push(fn);
  return () => {
    const i = emotionListeners.indexOf(fn);
    if (i !== -1) emotionListeners.splice(i, 1);
  };
}
function notifyEmotions() { emotionListeners.forEach((fn) => fn({ ...emotions })); }

function connectSSE() {
  const es = new EventSource('/api/public/sse/emotions');
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      Object.assign(emotions, data);
      notifyEmotions();
    } catch (err) {
      // Muet, les cinq jauges se figent sur leur dernière valeur et le site a
      // l'air vivant alors qu'il ne reçoit plus rien.
      console.warn('flux émotions : message ignoré', err, e.data);
    }
  };
  es.onerror = () => setTimeout(connectSSE, 5000);
}
connectSSE();

/** Flux cognitif en direct. L'appelant ferme l'EventSource à son démontage. */
export function connectCognitiveSSE(onEvent) {
  const es = new EventSource('/api/public/sse/cognitive');
  es.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)); }
    catch (err) { console.warn('flux cognitif : message ignoré', err, e.data); }
  };
  return es;
}

// ── Modale d'image ────────────────────────────────────────────────────────
const _modal = document.getElementById('modal');
const _modalImg = document.getElementById('modal-img');
const _modalCaption = document.getElementById('modal-caption');
document.getElementById('modal-close').addEventListener('click', closeModal);
_modal.addEventListener('click', (e) => { if (e.target === _modal) closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

/** Ouvre la lightbox. `legende` accepte une chaîne ou un nœud (fiche complète). */
export function openModal(src, legende) {
  _modalImg.src = src;
  _modalImg.alt = typeof legende === 'string' ? legende : '';
  _modalCaption.textContent = '';
  if (legende instanceof Node) _modalCaption.appendChild(legende);
  else if (legende) _modalCaption.textContent = legende;
  _modal.classList.add('open');
}
function closeModal() { _modal.classList.remove('open'); }

// ── Apparition au défilement ──────────────────────────────────────────────
// Une seule instance pour tout le site : les pages appellent `observeReveals()`
// après avoir monté leur DOM.
const _revealObserver = window.IntersectionObserver
  ? new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add('on'); _revealObserver.unobserve(e.target); }
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 })
  : null;

function observeReveals(root) {
  const els = (root || document).querySelectorAll('.reveal:not(.on)');
  if (!_revealObserver) { els.forEach((el) => el.classList.add('on')); return; }
  els.forEach((el) => _revealObserver.observe(el));
  // Filet : un `IntersectionObserver` qui ne se déclenche jamais (onglet en
  // arrière-plan au chargement, viewport de 0 px) laisserait la page INVISIBLE.
  setTimeout(() => els.forEach((el) => el.classList.add('on')), 3500);
}

// ── Relief au survol ──────────────────────────────────────────────────────
// La carte s'incline vers le curseur, son ombre suit, sa bordure s'allume.
// C'est le geste qui distingue une carte d'un rectangle : sans lui, la page
// est un empilement de blocs morts, quel que soit le soin mis au CSS.
function brancherTilt(racine) {
  // Sur un écran tactile il n'y a pas de survol : les gestionnaires ne
  // serviraient qu'à faire clignoter la carte au moment du tap.
  if (window.matchMedia('(hover: none)').matches) return;

  (racine || document).querySelectorAll('[data-tilt]').forEach((el) => {
    el.classList.add('tiltable');
    const bordBase = el.style.borderColor;

    el.addEventListener('mousemove', (e) => {
      // Une carte pas encore révélée porte un `translateY(28px)` : l'incliner
      // maintenant écraserait ce transform et elle n'apparaîtrait jamais.
      if (el.classList.contains('reveal') && !el.classList.contains('on')) return;
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      el.style.zIndex = '8';
      el.style.borderColor = 'rgba(255,140,60,.42)';
      el.style.transform = 'perspective(900px)'
        + ' rotateY(' + (x * 8).toFixed(2) + 'deg)'
        + ' rotateX(' + (-y * 8).toFixed(2) + 'deg)'
        + ' translateY(-6px) scale(1.022)';
      el.style.boxShadow = (16 + x * 22).toFixed(0) + 'px ' + (26 - y * 14).toFixed(0)
        + 'px 60px -28px rgba(255,106,43,.55), inset 0 0 0 1px rgba(255,176,46,.14)';
    });

    el.addEventListener('mouseleave', () => {
      // On EFFACE la propriété au lieu d'y reposer une valeur : `.reveal.on`
      // reprend la main, et une carte non révélée garde son décalage.
      el.style.transform = '';
      el.style.boxShadow = '';
      el.style.borderColor = bordBase;
      setTimeout(() => { el.style.zIndex = ''; }, 300);
    });
  });
}

// ── Routeur ───────────────────────────────────────────────────────────────
const ROUTES = {
  '/':        { page: pageAccueil, plein: false },
  '/chat':    { page: pageChat,    plein: true },
  '/galerie': { page: pageGalerie, plein: false },
  '/tcg':     { page: pageTcg,     plein: false },
};

// Les ancres de l'ancien site arcade. Un lien partagé ou un marque-page ne doit
// pas tomber sur une page blanche.
const HASH_LEGACY = {
  status: '/', chat: '/chat', gallery: '/galerie', galerie: '/galerie',
  journal: '/', about: '/', tcg: '/tcg',
};

const _vue = document.getElementById('vue');
let _routeActive = null;

function normaliser(pathname) {
  const p = (pathname || '/').replace(/\/+$/, '') || '/';
  return ROUTES[p] ? p : '/';
}

function syncNav(route) {
  document.querySelectorAll('.nav-link').forEach((a) => {
    a.classList.toggle('active', a.dataset.route === route);
  });
}

function rendre(route) {
  if (_routeActive === route) return;
  const precedent = _routeActive ? ROUTES[_routeActive] : null;
  if (precedent && typeof precedent.page.unmount === 'function') precedent.page.unmount();
  _routeActive = route;

  const def = ROUTES[route];
  document.documentElement.classList.toggle('vue-chat', def.plein);
  document.body.classList.toggle('vue-chat', def.plein);
  _vue.textContent = '';
  syncNav(route);
  def.page.mount(_vue);
  observeReveals(_vue);
  brancherTilt(_vue);
  window.scrollTo(0, 0);
  window.dispatchEvent(new CustomEvent('wally-vue-changed'));
}

/** Navigation interne : pousse l'URL puis rend. Exporté pour les boutons. */
export function naviguer(route, remplacer) {
  const cible = normaliser(route);
  if (remplacer) history.replaceState({}, '', cible);
  else history.pushState({}, '', cible);
  rendre(cible);
}

document.addEventListener('click', (e) => {
  const a = e.target.closest('[data-route]');
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
  e.preventDefault();
  naviguer(a.dataset.route);
});

window.addEventListener('popstate', () => rendre(normaliser(location.pathname)));

// Position initiale. Trois entrées possibles, dans cet ordre :
//   1. le retour OAuth (`/?chat_code=…`) — le serveur ne sait rediriger que
//      vers la racine, c'est ici qu'on le remet sur le chat ;
//   2. une ancre de l'ancien site (`#chat`, `#gallery`…) ;
//   3. le chemin demandé.
(function routeInitiale() {
  history.scrollRestoration = 'manual';
  const params = new URLSearchParams(location.search);
  if (params.get('chat_code')) {
    history.replaceState({}, '', '/chat' + location.search);
    rendre('/chat');
    return;
  }
  const hash = location.hash.slice(1);
  if (hash && HASH_LEGACY[hash]) {
    const cible = HASH_LEGACY[hash];
    history.replaceState({}, '', cible);
    rendre(cible);
    return;
  }
  rendre(normaliser(location.pathname));
}());

// ── Auth Discord ──────────────────────────────────────────────────────────
function decodeJwt(t) {
  try {
    const b64 = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(b64));
  } catch (_) { return null; }
}

/** Payload du JWT si présent ET non expiré, sinon `null`. */
export function utilisateur() {
  const jwt = localStorage.getItem('discord_jwt');
  const p = jwt ? decodeJwt(jwt) : null;
  return (p && (!p.exp || p.exp * 1000 > Date.now())) ? p : null;
}

async function chargerStatutGlobal() {
  try {
    const r = await fetch('/api/public/status');
    if (r.ok) {
      const d = await r.json();
      if (d.bot_name) NOM_BOT = String(d.bot_name);
      majPastilleEnLigne(d);
    } else {
      majPastilleEnLigne(null);
    }
  } catch (err) {
    // Repli explicite : la pastille passe à HORS LIGNE plutôt que de mentir.
    majPastilleEnLigne(null);
    console.warn('statut public indisponible', err);
  }
  appliquerNom();
  renderAuth();
}

function majPastilleEnLigne(status) {
  const el = document.getElementById('nav-state');
  if (!el) return;
  // `uptime_seconds` renseigné = le process répond, donc il est en ligne. Une
  // pastille verte codée en dur mentirait pendant les 15 s d'un rebuild.
  const enLigne = !!(status && status.uptime_seconds);
  el.classList.toggle('off', !enLigne);
  el.textContent = '';
  el.appendChild(h('span', { class: 'dot' }));
  el.appendChild(document.createTextNode(enLigne ? 'EN LIGNE' : 'HORS LIGNE'));
}

function renderAuth() {
  const host = document.getElementById('auth');
  if (!host) return;
  host.textContent = '';

  const p = utilisateur();
  if (!p) {
    // Deux libellés, un seul visible : sous 620 px, « Connexion Discord »
    // poussait la nav à 404 px de large sur un écran de 360 et le bouton
    // sortait de l'écran, hors de portée du pouce.
    host.appendChild(h('button', {
      class: 'btn btn-sm btn-ghost',
      onclick: () => { window.location.href = '/api/chat/auth/login'; },
    }, h('span', { class: 'lbl-long', text: 'Connexion Discord' }),
       h('span', { class: 'lbl-court', text: 'Discord' })));
    return;
  }

  const who = h('div', { class: 'auth-user' });
  if (p.avatar_url) who.appendChild(h('img', { class: 'auth-avatar', src: p.avatar_url, alt: '' }));
  who.appendChild(h('span', { text: p.username || 'connecté' }));
  host.appendChild(who);

  // `is_owner` est SIGNÉ dans le JWT par `chat_auth.create_jwt` : le site n'a
  // rien à comparer, et le snowflake du propriétaire ne circule plus.
  if (p.is_owner) {
    const adm = h('button', { class: 'auth-icon auth-admin', text: 'ADMIN' });
    adm.addEventListener('click', async () => {
      adm.disabled = true;
      try {
        const r = await fetch('/api/chat/auth/admin-token', {
          headers: { Authorization: 'Bearer ' + localStorage.getItem('discord_jwt') },
        });
        if (!r.ok) throw new Error('denied');
        const d = await r.json();
        localStorage.setItem('wally_token', d.token);
        window.location.href = '/admin';
      } catch (_) {
        adm.textContent = 'REFUSÉ';
      }
    });
    host.appendChild(adm);
  }

  host.appendChild(h('button', {
    class: 'auth-icon',
    text: '✕',
    title: 'Déconnexion',
    onclick: () => {
      localStorage.removeItem('discord_jwt');
      localStorage.removeItem('discord_refresh');
      renderAuth();
    },
  }));
}

ensureFreshToken().then(chargerStatutGlobal);

// Retour OAuth : la page chat échange le code de façon asynchrone puis émet
// `wally-auth-changed` quand le JWT est posé — on re-render le widget aussitôt,
// sans recharger la page.
window.addEventListener('wally-auth-changed', renderAuth);

// ── Compagnon ─────────────────────────────────────────────────────────────
// Il ne se contente pas d'apparaître : il flotte au rythme de la descente et
// change de phrase selon l'endroit de la page où on est arrivé. Sans ça, c'est
// un autocollant.
const COMPAGNON_PHRASES = [
  'il te regarde lire',
  'il retient ce passage',
  'il a une idée',
  'il attend ton message',
  'il pense à autre chose',
];
let _phraseCompagnon = -1;

function majCompagnon(el, sy, prog) {
  if (!el) return;
  // Le chat occupe tout l'écran : le compagnon s'y poserait sur le champ de
  // saisie.
  if (document.body.classList.contains('vue-chat')) { el.classList.remove('on'); return; }

  el.classList.toggle('on', sy > 300);
  el.style.transform = 'translateY(' + (-Math.sin(prog * Math.PI) * 24).toFixed(1) + 'px)'
    + ' scale(' + (0.94 + prog * 0.06).toFixed(3) + ')';

  const k = Math.min(COMPAGNON_PHRASES.length - 1, Math.floor(prog * COMPAGNON_PHRASES.length));
  if (k === _phraseCompagnon) return;
  _phraseCompagnon = k;
  const lab = el.querySelector('.companion-label');
  if (!lab) return;
  // Couper l'animation, forcer un reflow, la relancer : sans le reflow le
  // navigateur regroupe les deux écritures et l'animation ne rejoue pas.
  lab.style.animation = 'none';
  void lab.offsetWidth;
  lab.textContent = COMPAGNON_PHRASES[k];
  lab.style.animation = 'wTick 4s ease';
}

// ── Décor animé : halos, emojis, parallaxe, compagnon ─────────────────────
(function decor() {
  const reduit = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const halos = document.getElementById('bg-halos');
  const icons = document.getElementById('bg-icons');
  const companion = document.getElementById('companion');
  if (!halos || !icons) return;

  halos.appendChild(h('div', { class: 'bg-halo ember' }));
  halos.appendChild(h('div', { class: 'bg-halo cyan' }));

  // Quatre plans de profondeur, semés au hasard à chaque chargement : deux
  // visites ne voient jamais le même fond. Les cellules sont tirées sans
  // remise, sinon deux emojis se superposent une fois sur trois.
  const R = (a, b) => a + Math.random() * (b - a);
  const plans = [
    { es: ['📺', '💬', '🕹️', '✨', '🎲'], n: 4, s: [15, 19], o: [0.09, 0.13], b: [2.2, 2.7], sp: [0.10, 0.22] },
    { es: ['🎮', '🧠', '🎙️', '🃏'],       n: 3, s: [25, 31], o: [0.13, 0.17], b: [1.1, 1.5], sp: [0.42, 0.58] },
    { es: ['🤖', '📺', '💬'],             n: 2, s: [38, 46], o: [0.18, 0.23], b: [0.3, 0.5], sp: [0.95, 1.20] },
    { es: ['🔥'],                          n: 2, s: [56, 80], o: [0.32, 0.48], b: [0, 0],    sp: [1.80, 2.30] },
  ];
  const cells = [];
  for (let cx = 0; cx < 4; cx++) for (let cy = 0; cy < 3; cy++) cells.push([cx, cy]);
  for (let i = cells.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const t = cells[i]; cells[i] = cells[j]; cells[j] = t;
  }
  let k = 0;
  plans.forEach((p) => {
    for (let i = 0; i < p.n; i++) {
      const [cx, cy] = cells[k++ % cells.length];
      const el = h('div', { class: 'bg-icon', text: p.es[Math.floor(Math.random() * p.es.length)] });
      el.style.left = Math.round(R(cx * 25 + 3, cx * 25 + 20)) + '%';
      el.style.top = Math.round(R(cy * 30 + 6, cy * 30 + 26)) + '%';
      el.style.fontSize = Math.round(R(p.s[0], p.s[1])) + 'px';
      el.style.opacity = R(p.o[0], p.o[1]).toFixed(2);
      el.style.filter = 'blur(' + R(p.b[0], p.b[1]).toFixed(1) + 'px) saturate(.8)';
      el.dataset.sp = R(p.sp[0], p.sp[1]).toFixed(2);
      icons.appendChild(el);
    }
  });

  const mobile = window.matchMedia('(max-width: 900px)').matches;
  let listeIcons = Array.from(icons.children);
  if (mobile) listeIcons.forEach((el, i) => { if (i % 2) el.style.display = 'none'; });
  listeIcons = listeIcons.filter((el) => el.style.display !== 'none');
  listeIcons.forEach((el, i) => { el._ph = i * 1.7; });

  // Le décalage est plus discret sur un téléphone : à 390 px de large, la même
  // amplitude fait sortir les couches de l'écran.
  const K = mobile ? 0.55 : 1;

  let mx = 0, my = 0, tmx = 0, tmy = 0, aSy = -1, aMx = 99, aMy = 99;
  if (!reduit) {
    window.addEventListener('mousemove', (e) => {
      tmx = (e.clientX / window.innerWidth - 0.5) * 2;
      tmy = (e.clientY / window.innerHeight - 0.5) * 2;
    });
  }

  // Sur un téléphone il n'y a pas de curseur : tout le mouvement LATÉRAL du
  // décor est perdu, il ne reste que le défilement. On lit l'inclinaison de
  // l'appareil et on la fait entrer par la MÊME porte que la souris (tmx/tmy) :
  // la boucle d'animation n'a rien à savoir de la source.
  // Réservé aux pointeurs grossiers — un portable à écran tactile a un capteur
  // qui ne bouge jamais, et sa valeur figée écraserait celle de la souris.
  if (!reduit && window.DeviceOrientationEvent
      && window.matchMedia('(hover: none) and (pointer: coarse)').matches) {
    const AMPL = 24;   // degrés d'inclinaison pour aller d'un bord à l'autre
    let x0 = null, y0 = null;

    const surInclinaison = (e) => {
      if (e.beta == null || e.gamma == null) return;
      const ang = (screen.orientation && screen.orientation.angle) || window.orientation || 0;
      // En paysage, les deux axes du capteur ont tourné AVEC l'appareil : sans
      // cet échange, incliner vers la gauche fait monter le décor.
      let gx = e.gamma, gy = e.beta;
      if (ang === 90) { gx = e.beta; gy = -e.gamma; }
      else if (ang === 270 || ang === -90) { gx = -e.beta; gy = e.gamma; }
      // La première mesure devient le neutre : personne ne tient son téléphone
      // à plat, et sans repère le décor démarre collé dans un coin, en butée.
      if (x0 == null) { x0 = gx; y0 = gy; }
      const borne = (v) => Math.max(-1, Math.min(1, v));
      tmx = borne((gx - x0) / AMPL);
      tmy = borne((gy - y0) / AMPL);
    };

    // Le neutre est RELATIF à l'orientation : le garder au passage en paysage
    // enverrait le décor en butée d'un côté et il n'en reviendrait plus.
    window.addEventListener('orientationchange', () => { x0 = null; y0 = null; });

    const brancher = () => window.addEventListener('deviceorientation', surInclinaison);
    const DOE = window.DeviceOrientationEvent;
    if (typeof DOE.requestPermission === 'function') {
      // iOS 13+ : l'autorisation ne se demande QUE depuis un geste de
      // l'utilisateur. Le premier appui sur la page sert de geste ; un refus
      // laisse le décor immobile, exactement comme avant.
      window.addEventListener('pointerdown', () => {
        DOE.requestPermission()
          .then((r) => { if (r === 'granted') brancher(); })
          .catch((err) => console.warn('gyroscope refusé', err));
      }, { once: true });
    } else {
      brancher();
    }
  }

  let vh = window.innerHeight;
  let max = Math.max(1, document.body.scrollHeight - vh);
  let listePx = Array.from(document.querySelectorAll('[data-px]'));

  const remesurer = () => {
    vh = window.innerHeight;
    max = Math.max(1, document.body.scrollHeight - vh);
    listeIcons.forEach((el) => { el._y0 = null; });
    // `_top` est une position ABSOLUE dans le document : dès que la hauteur
    // bouge, la valeur gardée devient fausse. Elle l'était : les couches se
    // figeaient à leur profondeur d'avant.
    listePx.forEach((el) => { el._top = null; });
    aSy = -1;   // force un rendu, sinon le garde « rien n'a bougé » l'annule
  };
  window.addEventListener('resize', remesurer);

  // La hauteur du document change SANS redimensionnement : le journal, la
  // galerie et le fil cognitif arrivent en asynchrone et rallongent la page de
  // plusieurs milliers de pixels. Sans cet observateur, `max` reste calé sur la
  // page vide et le fond a fini sa course au premier tiers.
  if (window.ResizeObserver) new ResizeObserver(remesurer).observe(document.body);

  window.addEventListener('wally-vue-changed', () => {
    listePx = Array.from(document.querySelectorAll('[data-px]'));
    remesurer();
  });

  const boucle = (ts) => {
    if (document.hidden) { requestAnimationFrame(boucle); return; }
    mx += (tmx - mx) * 0.06;
    my += (tmy - my) * 0.06;
    const sy = window.scrollY || 0;
    const prog = Math.min(1, sy / max);
    // Rien n'a bougé : on ne touche pas au DOM. C'est ce garde qui rend la
    // boucle gratuite quand la page est immobile.
    if (Math.abs(sy - aSy) < 0.4 && Math.abs(mx - aMx) < 0.0015 && Math.abs(my - aMy) < 0.0015) {
      requestAnimationFrame(boucle);
      return;
    }
    aSy = sy; aMx = mx; aMy = my;

    if (!reduit) {
      listePx.forEach((el) => {
        const sp = parseFloat(el.dataset.px) || 0;
        if (el._top == null) el._top = el.getBoundingClientRect().top + sy;
        const rel = el._top - vh * 0.5;
        el.style.transform = 'translate3d('
          + (mx * sp * 12 * K).toFixed(2) + 'px,'
          + ((-(sy - Math.max(0, rel)) * sp * 0.16 + my * sp * 8) * K).toFixed(2) + 'px,0)';
      });

      listeIcons.forEach((el) => {
        const sp = parseFloat(el.dataset.sp) || 0;
        if (el._y0 == null) el._y0 = el.offsetTop;
        const ht = el.offsetHeight || 30;
        const bob = Math.sin(ts * 0.00028 + el._ph) * 9;
        const brut = -prog * vh * 0.42 * sp * K;
        const course = Math.max(-(el._y0 + ht * 0.25), Math.min(vh - ht - el._y0, brut));
        el.style.transform = 'translate3d('
          + (mx * sp * 22 * K + bob * 0.5).toFixed(1) + 'px,'
          + (course + my * sp * 16 * K + bob).toFixed(1) + 'px,0) rotate(' + (bob * 0.5).toFixed(2) + 'deg)';
      });

      halos.style.transform = 'translate3d('
        + (mx * -10 * K).toFixed(1) + 'px,'
        + ((-prog * vh * 0.2 + my * -8) * K).toFixed(1) + 'px,0)';
    }

    majCompagnon(companion, sy, prog);

    // La page courante s'abonne pour ce qui lui appartient : le bandeau, le
    // fil de la boucle, le rail. Un seul rAF pour tout le site — deux boucles,
    // c'est deux mesures de viewport qui divergent d'une image.
    for (let i = 0; i < _abonnesAnim.length; i++) _abonnesAnim[i](sy, vh, prog);

    requestAnimationFrame(boucle);
  };
  requestAnimationFrame(boucle);
}());

// ── Défilement inertiel ───────────────────────────────────────────────────
// Sans lui, chaque cran de molette est un saut, et toutes les couches sautent
// avec : le parallaxe, le bandeau, le fil, le compagnon.
(function scrollInertiel() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const L = window.Lenis;
  // Le script vendoré n'a pas chargé : on garde le défilement natif plutôt que
  // de casser la page. Mais on le DIT — un site muet qui a perdu la moitié de
  // son mouvement, personne ne remonte le fil jusqu'à un 404.
  if (!L) { console.warn('Lenis absent — défilement natif, parallaxe saccadé'); return; }

  // Les conteneurs qui défilent EUX-MÊMES. Lenis intercepte la molette du
  // document entier : sans cette liste, le fil du chat, le flux cognitif de
  // l'accueil et la fiche image de la lightbox sont FIGÉS sous le curseur —
  // sans erreur, sans rien dans la console, juste une page qui ne répond pas.
  // Une liste en UN seul endroit, jamais un attribut semé dans chaque page :
  // le prochain conteneur qui défile se déclare ici ou nulle part.
  const SANS_LENIS = '.chat-scroll, .chat-side, .feed-body, .modal';

  const lenis = new L({
    prevent: (noeud) => !!noeud.matches?.(SANS_LENIS),
    duration: 0.55,
    easing: (x) => 1 - Math.pow(1 - x, 3),
    wheelMultiplier: 1.25,
    touchMultiplier: 1.6,
    smoothWheel: true,
  });
  const raf = (ts) => { lenis.raf(ts); requestAnimationFrame(raf); };
  requestAnimationFrame(raf);

  window.addEventListener('wally-vue-changed', () => {
    // Le chat ne défile PAS au niveau du document : son fil défile dans un
    // conteneur. Lenis y volerait la molette et les messages seraient figés.
    if (document.body.classList.contains('vue-chat')) lenis.stop();
    else { lenis.start(); lenis.scrollTo(0, { immediate: true }); }
  });

  // Les ancres internes (« Voir son cerveau penser ») : `scrollIntoView` et
  // Lenis se disputeraient la position et la page tremblerait.
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const cible = document.querySelector(a.getAttribute('href'));
    if (!cible) return;
    e.preventDefault();
    lenis.scrollTo(cible, { offset: -90, duration: 1.1 });
  });
}());

// Les vidéos `autoplay muted` sont bloquées par certains navigateurs tant
// qu'aucun geste n'a eu lieu : on relance, puis on réessaie au premier clic.
(function lancerVideos() {
  const kick = () => {
    document.querySelectorAll('video').forEach((v) => {
      v.muted = true; v.loop = true; v.playsInline = true;
      const p = v.play();
      if (p && p.catch) p.catch(() => {});
    });
  };
  kick();
  [200, 800, 2000].forEach((t) => setTimeout(kick, t));
  document.addEventListener('pointerdown', kick, { once: true });
  window.addEventListener('wally-vue-changed', kick);
}());
