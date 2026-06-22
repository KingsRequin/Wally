// public-ui/app.js — arcade theme
import { mount as mountStatus } from './tabs/status.js';
import { mount as mountChat } from './tabs/chat.js';
import { mount as mountGallery } from './tabs/gallery.js';
import { mount as mountJournal } from './tabs/journal.js';
import { mount as mountAbout } from './tabs/about.js';

// ── Shared emotion state ──
export const emotions = { anger: 0, joy: 0, curiosity: 0, sadness: 0, boredom: 0 };
const emotionListeners = [];
export function onEmotionUpdate(fn) {
  emotionListeners.push(fn);
  return () => {
    const i = emotionListeners.indexOf(fn);
    if (i !== -1) emotionListeners.splice(i, 1);
  };
}
function notifyEmotions() { emotionListeners.forEach(fn => fn({ ...emotions })); }

// ── SSE emotions ──
function connectSSE() {
  const es = new EventSource('/api/public/sse/emotions');
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      Object.assign(emotions, data);
      notifyEmotions();
    } catch (_) {}
  };
  es.onerror = () => setTimeout(connectSSE, 5000);
}
connectSSE();

// ── Cognitive SSE (live brain feed) ──
export function connectCognitiveSSE(onEvent) {
  const es = new EventSource('/api/public/sse/cognitive');
  es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch (_) {} };
  return es; // caller closes on unmount
}

// ── Modal ──
const overlay = document.getElementById('modal-overlay');
const modalImg = document.getElementById('modal-img');
const modalCaption = document.getElementById('modal-caption');
document.getElementById('modal-close').addEventListener('click', closeModal);
overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

export function openModal(src, caption) {
  modalImg.src = src;
  modalImg.alt = caption || '';
  modalCaption.textContent = caption || '';
  overlay.classList.add('open');
}
function closeModal() { overlay.classList.remove('open'); }

// ── Pixel flame sprite (box-shadow art) ──
export function drawFlame(id, P = 4) {
  const bm = [
    ".....O.....", "....OOO....", "....OYO....", "...OOYOO...", "...OYYYO...",
    "..OOYYYOO..", "..OYYWYYO..", ".OOYYWWYOO.", ".OYYWWWYYO.", ".OYYWWWYYO.",
    ".OOYYWYYOO.", "..OYYYYYO..", "..OOYYYOO..", "...OOOOO.."
  ];
  const pal = { O: "#ff4d1f", Y: "#ffb020", W: "#fff2c2" };
  const el = document.getElementById(id);
  if (!el) return;
  el.style.position = "relative"; el.style.display = "inline-block";
  el.style.width = (P * 11) + "px"; el.style.height = (P * 14) + "px";
  const dot = document.createElement('i');
  dot.style.position = "absolute"; dot.style.left = "0"; dot.style.top = "0";
  dot.style.width = P + "px"; dot.style.height = P + "px";
  const s = [];
  for (let r = 0; r < bm.length; r++)
    for (let c = 0; c < bm[r].length; c++) {
      const ch = bm[r][c];
      if (ch !== ".") s.push(`${c * P}px ${r * P}px 0 0 ${pal[ch]}`);
    }
  dot.style.boxShadow = s.join(",");
  el.innerHTML = ''; el.appendChild(dot);
}

// ── Single-page sections ──
// Toutes les sections sont montées en même temps et empilées verticalement.
// La nav fait défiler (ancres) ; un scroll-spy met en surbrillance l'onglet actif.
const TABS_ORDER = ['status', 'chat', 'gallery', 'journal', 'about'];
const TABS = {
  status:    mountStatus,
  chat:      mountChat,
  gallery:   mountGallery,
  journal:   mountJournal,
  about:     mountAbout,
};

function syncNav(tabName) {
  document.querySelectorAll('.arc-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
}

const _sections = {};
(function buildSections() {
  const main = document.getElementById('tab-content');
  main.innerHTML = '';
  TABS_ORDER.forEach(name => {
    const sec = document.createElement('section');
    sec.id = 'sec-' + name;
    sec.className = 'arc-section';
    main.appendChild(sec);
    _sections[name] = sec;
    TABS[name](sec);
  });
})();

function scrollToSection(name) {
  const sec = _sections[name];
  if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

document.querySelectorAll('[data-tab]').forEach(el => {
  el.addEventListener('click', () => {
    const name = el.dataset.tab;
    if (!_sections[name]) return;
    scrollToSection(name);
    history.replaceState(null, '', '#' + name);
  });
});

// Scroll-spy : surligne l'onglet de la section au centre du viewport
if (window.IntersectionObserver) {
  const spy = new IntersectionObserver(entries => {
    entries.forEach(e => { if (e.isIntersecting) syncNav(e.target.id.replace('sec-', '')); });
  }, { rootMargin: '-45% 0px -50% 0px', threshold: 0 });
  TABS_ORDER.forEach(n => spy.observe(_sections[n]));
}

// Empêcher le browser de restaurer automatiquement la position de scroll
// (évite le conflit entre restauration + smooth scroll + scroll anchoring Chrome).
history.scrollRestoration = 'manual';

// Position initiale : ancre dans l'URL, ou section chat si retour OAuth Discord
const _initial = (location.hash.slice(1) && _sections[location.hash.slice(1)])
  ? location.hash.slice(1)
  : (new URLSearchParams(location.search).get('chat_code') ? 'chat' : null);
if (_initial) {
  // Attendre 'load' (polices + images stables) avant de scroller,
  // sinon les layout shifts post-chargement décalent la destination.
  const _doScroll = () => requestAnimationFrame(() => scrollToSection(_initial));
  if (document.readyState === 'complete') _doScroll();
  else window.addEventListener('load', _doScroll, { once: true });
}
syncNav(_initial || 'status');

drawFlame('spx-nav', 4);

// ── Auth widget (Discord) ──
// Bouton de connexion Discord en haut à droite. Si l'owner est connecté,
// un bouton ADMIN apparaît (token récupéré via le JWT, sans mot de passe).
const OWNER_DISCORD_ID = '610550333042589752';

function decodeJwt(t) {
  try {
    const b64 = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(b64));
  } catch (_) { return null; }
}

function renderAuth() {
  const host = document.getElementById('arc-auth');
  if (!host) return;
  host.textContent = '';

  const jwt = localStorage.getItem('discord_jwt');
  const p = jwt ? decodeJwt(jwt) : null;
  const valid = p && (!p.exp || p.exp * 1000 > Date.now());

  if (!valid) {
    const btn = document.createElement('button');
    btn.className = 'arc-auth-btn';
    btn.textContent = 'CONNEXION DISCORD';
    btn.addEventListener('click', () => { window.location.href = '/api/chat/auth/login'; });
    host.appendChild(btn);
    return;
  }

  const who = document.createElement('span');
  who.className = 'arc-auth-user';
  if (p.avatar_url) {
    const img = document.createElement('img');
    img.className = 'arc-auth-av';
    img.src = p.avatar_url;
    img.alt = '';
    who.appendChild(img);
  }
  who.appendChild(document.createTextNode(p.username || 'connecté'));
  host.appendChild(who);

  if (String(p.discord_id) === OWNER_DISCORD_ID) {
    const adm = document.createElement('button');
    adm.className = 'arc-auth-btn admin';
    adm.textContent = 'ADMIN';
    adm.addEventListener('click', async () => {
      adm.disabled = true;
      try {
        const r = await fetch('/api/chat/auth/admin-token', { headers: { Authorization: 'Bearer ' + jwt } });
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

  const out = document.createElement('button');
  out.className = 'arc-auth-btn ghost';
  out.textContent = '✕';
  out.title = 'Déconnexion';
  out.addEventListener('click', () => {
    localStorage.removeItem('discord_jwt');
    localStorage.removeItem('discord_refresh');
    renderAuth();
  });
  host.appendChild(out);
}

renderAuth();

// Retour OAuth : chat.js échange le code de façon asynchrone puis émet
// `wally-auth-changed` quand le JWT est posé — on re-render le widget aussitôt,
// sans recharger la page.
window.addEventListener('wally-auth-changed', renderAuth);

// ── Animated arcade background (canvas) ──
(function initBg() {
  const cv = document.getElementById('bg-canvas');
  if (!cv) return;
  const ctx = cv.getContext('2d');
  let W = 0, H = 0, mpx = null, mpy = null, raf = 0;
  let embers = [], nodes = [], orbs = [];
  const dpr = Math.min(window.devicePixelRatio || 1, 2);

  function currentMfx() {
    try {
      const v = localStorage.getItem('wally_mfx');
      return ['grille', 'constellation', 'aimant', 'vortex', 'onde'].includes(v) ? v : 'aimant';
    } catch (_) { return 'aimant'; }
  }

  function newEmber() {
    return { x: Math.random() * W, y: H + Math.random() * H, vy: 0.3 + Math.random() * 1.0,
      size: 1 + Math.floor(Math.random() * 3), hue: Math.random(), drift: (Math.random() - 0.5) * 0.4, life: Math.random() * 6 };
  }
  function initParticles() {
    embers = Array.from({ length: 64 }, newEmber);
    nodes = Array.from({ length: 56 }, () => ({ x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.5, vy: (Math.random() - 0.5) * 0.5 }));
    const cols = ["#ffd400", "#ff3b6b", "#43e0ff", "#bf94ff"];
    orbs = Array.from({ length: 120 }, () => ({ ang: Math.random() * Math.PI * 2, rad: 24 + Math.random() * 250,
      spd: (0.004 + Math.random() * 0.016) * (Math.random() < 0.5 ? 1 : -1),
      size: 2 + Math.floor(Math.random() * 3), col: cols[Math.floor(Math.random() * cols.length)] }));
  }

  function fxGrille(ts, mx, my, sy) {
    const step = 46;
    const ox = (mx / W - 0.5) * -30, oy = (my / H - 0.5) * -30 - sy * 0.05;
    ctx.lineWidth = 1;
    for (let x = (ox % step) - step; x < W + step; x += step) {
      ctx.strokeStyle = `rgba(124,77,255,${0.05 + 0.20 * Math.max(0, 1 - Math.abs(x - mx) / 380)})`;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = (oy % step) - step; y < H + step; y += step) {
      ctx.strokeStyle = `rgba(124,77,255,${0.05 + 0.20 * Math.max(0, 1 - Math.abs(y - my) / 320)})`;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }
    const g = ctx.createRadialGradient(mx, my, 0, mx, my, 220);
    g.addColorStop(0, "rgba(124,77,255,0.18)"); g.addColorStop(1, "rgba(124,77,255,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  }
  function fxConstellation(ts, mx, my) {
    const ns = nodes, D = 124;
    for (const n of ns) {
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0 || n.x > W) n.vx *= -1;
      if (n.y < 0 || n.y > H) n.vy *= -1;
    }
    ctx.lineWidth = 1;
    for (let i = 0; i < ns.length; i++) {
      const a = ns[i], dm = Math.hypot(a.x - mx, a.y - my);
      if (dm < 190) { ctx.strokeStyle = `rgba(67,224,255,${0.45 * (1 - dm / 190)})`; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(mx, my); ctx.stroke(); }
      for (let j = i + 1; j < ns.length; j++) {
        const b = ns[j], d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d < D) {
          const lit = dm < 170 || Math.hypot(b.x - mx, b.y - my) < 170;
          ctx.strokeStyle = lit ? `rgba(67,224,255,${0.28 * (1 - d / D)})` : `rgba(124,77,255,${0.12 * (1 - d / D)})`;
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        }
      }
    }
    for (const n of ns) {
      const lit = Math.hypot(n.x - mx, n.y - my) < 170, s = lit ? 4 : 3;
      ctx.fillStyle = lit ? "#43e0ff" : "rgba(190,148,255,.85)";
      ctx.fillRect(n.x - s / 2, n.y - s / 2, s, s);
    }
  }
  function fxAimant(ts, mx, my) {
    const step = 42, R = 140;
    for (let x = step / 2; x < W; x += step)
      for (let y = step / 2; y < H; y += step) {
        const dx = x - mx, dy = y - my, d = Math.hypot(dx, dy) || 1;
        if (d < R) {
          const t = 1 - d / R, f = t * 42;
          const px = x + dx / d * f, py = y + dy / d * f, gg = Math.round(59 + 153 * t);
          ctx.fillStyle = `rgba(255,${gg},${Math.round(107 * (1 - t))},${0.5 + 0.5 * t})`;
          const s = 2 + 2.5 * t; ctx.fillRect(px - s / 2, py - s / 2, s, s);
        } else {
          ctx.fillStyle = "rgba(170,150,230,0.22)";
          ctx.fillRect(x - 1, y - 1, 2, 2);
        }
      }
  }
  function fxVortex(ts, mx, my) {
    for (const o of orbs) {
      o.ang += o.spd;
      const x = mx + Math.cos(o.ang) * o.rad, y = my + Math.sin(o.ang) * o.rad * 0.62;
      ctx.fillStyle = o.col; ctx.fillRect(x - o.size / 2, y - o.size / 2, o.size, o.size);
    }
  }
  function fxOnde(ts, mx, my) {
    const step = 40;
    for (let x = step / 2; x < W; x += step)
      for (let y = step / 2; y < H; y += step) {
        const d = Math.hypot(x - mx, y - my);
        const f = Math.max(0, Math.sin(d / 26 - ts / 260)) * Math.max(0, 1 - d / 540);
        const s = 1.5 + 2.4 * f;
        ctx.fillStyle = `rgba(67,224,255,${0.05 + 0.28 * f})`;
        ctx.fillRect(x - s / 2, y - s / 2, s, s);
      }
  }
  const FX = { grille: fxGrille, constellation: fxConstellation, aimant: fxAimant, vortex: fxVortex, onde: fxOnde };

  function draw(ts) {
    const sy = window.scrollY || 0;
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";
    for (const e of embers) {
      e.y -= e.vy; e.x += e.drift;
      if (e.y < -10) { Object.assign(e, newEmber()); e.y = H + 10; }
      const col = e.hue < 0.5 ? "255,90,30" : (e.hue < 0.8 ? "255,180,40" : "255,60,120");
      const a = 0.28 + 0.38 * Math.abs(Math.sin(ts / 500 + e.life));
      ctx.fillStyle = `rgba(${col},${a})`;
      ctx.fillRect(e.x, e.y, e.size, e.size);
    }
    ctx.globalCompositeOperation = "source-over";
    const mx = mpx == null ? W / 2 : mpx, my = mpy == null ? H / 2 : mpy;
    (FX[currentMfx()] || fxAimant)(ts, mx, my, sy);
  }

  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    initParticles();
  }
  window.addEventListener('resize', resize);
  window.addEventListener('mousemove', (e) => { mpx = e.clientX; mpy = e.clientY; });
  resize();
  const loop = (ts) => { draw(ts || 0); raf = requestAnimationFrame(loop); };
  raf = requestAnimationFrame(loop);
}());
