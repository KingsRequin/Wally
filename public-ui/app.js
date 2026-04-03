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
