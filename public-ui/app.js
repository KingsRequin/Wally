// public-ui/app.js
import { mount as mountStatus, unmount as unmountStatus } from './tabs/status.js';
import { mount as mountChat, unmount as unmountChat } from './tabs/chat.js';
import { mount as mountGallery, unmount as unmountGallery } from './tabs/gallery.js';
import { mount as mountJournal, unmount as unmountJournal } from './tabs/journal.js';
import { mount as mountAbout, unmount as unmountAbout } from './tabs/about.js';

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
  status:  { mount: mountStatus,  unmount: unmountStatus },
  chat:    { mount: mountChat,    unmount: unmountChat },
  gallery: { mount: mountGallery, unmount: unmountGallery },
  journal: { mount: mountJournal, unmount: unmountJournal },
  about:   { mount: mountAbout,   unmount: unmountAbout },
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
route();

// ── Stars canvas ──
(function initStars() {
  const canvas = document.getElementById('stars');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let mouse = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  window.addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; });

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  const stars = [];
  for (let i = 0; i < 130; i++) {
    stars.push({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      r: Math.random() * 1.3 + 0.3,
      alpha: Math.random(),
      da: (Math.random() * 0.004 + 0.001) * (Math.random() < 0.5 ? 1 : -1),
      vx: (Math.random() - 0.5) * 0.15,
      vy: (Math.random() - 0.5) * 0.15,
    });
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const s of stars) {
      // Gentle mouse attraction — force proportional to 1/dist, capped
      const distX = mouse.x - s.x;
      const distY = mouse.y - s.y;
      const dist = Math.sqrt(distX * distX + distY * distY) || 1;
      const force = Math.min(60 / (dist * dist), 0.012);
      s.vx += distX * force;
      s.vy += distY * force;
      // Dampen velocity
      s.vx *= 0.97;
      s.vy *= 0.97;
      s.x += s.vx;
      s.y += s.vy;
      // Wrap around edges
      if (s.x < 0) s.x = canvas.width;
      if (s.x > canvas.width) s.x = 0;
      if (s.y < 0) s.y = canvas.height;
      if (s.y > canvas.height) s.y = 0;
      // Twinkle
      s.alpha += s.da;
      if (s.alpha <= 0.05 || s.alpha >= 1) s.da = -s.da;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${Math.max(0, Math.min(1, s.alpha)).toFixed(3)})`;
      ctx.fill();
    }
    requestAnimationFrame(draw);
  }
  draw();
}());
