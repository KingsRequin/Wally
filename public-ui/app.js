// public-ui/app.js
import { mount as mountStatus, unmount as unmountStatus } from './tabs/status.js';
import { mount as mountChat, unmount as unmountChat } from './tabs/chat.js';
import { mount as mountGallery, unmount as unmountGallery } from './tabs/gallery.js';
import { mount as mountJournal, unmount as unmountJournal } from './tabs/journal.js';
import { mount as mountAbout, unmount as unmountAbout } from './tabs/about.js';
import { mount as mountCommunity, unmount as unmountCommunity } from './tabs/community.js';

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

// ── Router ──
const TABS = {
  status:    { mount: mountStatus,    unmount: unmountStatus },
  chat:      { mount: mountChat,      unmount: unmountChat },
  gallery:   { mount: mountGallery,   unmount: unmountGallery },
  journal:   { mount: mountJournal,   unmount: unmountJournal },
  community: { mount: mountCommunity, unmount: unmountCommunity },
  about:     { mount: mountAbout,     unmount: unmountAbout },
};

let currentTab = null;

function route() {
  const hash = location.hash.slice(1) || 'status';
  const tabName = TABS[hash] ? hash : 'status';

  // Unmount previous
  if (currentTab && TABS[currentTab] && TABS[currentTab].unmount) {
    TABS[currentTab].unmount();
  }

  // Update nav buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  const content = document.getElementById('tab-content');
  content.style.animation = 'none';
  content.offsetHeight; // reflow
  content.style.animation = '';

  TABS[tabName].mount(content);
  currentTab = tabName;
}

// Nav button clicks
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    location.hash = btn.dataset.tab;
  });
});

window.addEventListener('hashchange', route);

// If returning from Discord OAuth, navigate to #chat before routing
if (new URLSearchParams(location.search).get('chat_code')) {
  location.hash = 'chat';
}

route();

// ── Stars canvas — parallax 3D ──
(function initStars() {
  const canvas = document.getElementById('stars');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  // Smooth mouse/gyro offset (normalised -0.5..0.5, lerped)
  let targetMX = 0, targetMY = 0, curMX = 0, curMY = 0;

  window.addEventListener('mousemove', e => {
    targetMX = e.clientX / window.innerWidth - 0.5;
    targetMY = e.clientY / window.innerHeight - 0.5;
  });

  // Mobile: accelerometer parallax via DeviceOrientation
  // Request permission on iOS 13+ on first interaction
  function enableGyro() {
    if (typeof DeviceOrientationEvent !== 'undefined' &&
        typeof DeviceOrientationEvent.requestPermission === 'function') {
      DeviceOrientationEvent.requestPermission().catch(() => {});
    }
    window.addEventListener('deviceorientation', e => {
      // gamma = left/right tilt (-90..90), beta = front/back (-180..180)
      targetMX = Math.max(-0.5, Math.min(0.5, (e.gamma || 0) / 40));
      targetMY = Math.max(-0.5, Math.min(0.5, ((e.beta || 0) - 30) / 60));
    }, { passive: true });
  }

  // Trigger gyro on first touch (iOS permission gate)
  window.addEventListener('touchstart', enableGyro, { once: true });
  // Android / non-gated — enable directly
  if (typeof DeviceOrientationEvent !== 'undefined' &&
      typeof DeviceOrientationEvent.requestPermission !== 'function') {
    enableGyro();
  }

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  // depth 0..1: 0 = far (tiny, moves little), 1 = close (bigger, moves more)
  const stars = [];
  for (let i = 0; i < 150; i++) {
    const depth = Math.random();               // parallax layer
    stars.push({
      bx: Math.random() * window.innerWidth,   // base position
      by: Math.random() * window.innerHeight,
      r: 0.3 + depth * 1.4,                   // size proportional to depth
      alpha: Math.random(),
      da: (Math.random() * 0.003 + 0.001) * (Math.random() < 0.5 ? 1 : -1),
      dx: (Math.random() - 0.5) * 0.08,       // slow drift
      dy: (Math.random() - 0.5) * 0.08,
      depth,
    });
  }

  const MAX_SHIFT = 120; // px max parallax shift for the closest layer

  function draw() {
    // Lerp toward target mouse position
    curMX += (targetMX - curMX) * 0.06;
    curMY += (targetMY - curMY) * 0.06;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const s of stars) {
      // Slow drift of base position
      s.bx += s.dx;
      s.by += s.dy;
      if (s.bx < 0) s.bx = canvas.width;
      if (s.bx > canvas.width) s.bx = 0;
      if (s.by < 0) s.by = canvas.height;
      if (s.by > canvas.height) s.by = 0;

      // Parallax offset — deeper stars shift more
      const rx = s.bx + curMX * MAX_SHIFT * s.depth;
      const ry = s.by + curMY * MAX_SHIFT * s.depth;

      // Twinkle
      s.alpha += s.da;
      if (s.alpha <= 0.05 || s.alpha >= 1) s.da = -s.da;

      ctx.beginPath();
      ctx.arc(rx, ry, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${Math.max(0, Math.min(1, s.alpha)).toFixed(3)})`;
      ctx.fill();
    }
    requestAnimationFrame(draw);
  }
  draw();
}());
