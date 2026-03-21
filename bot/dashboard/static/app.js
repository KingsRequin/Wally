// bot/dashboard/static/app.js
// WARNING: Auth token stored in localStorage — acceptable for personal use.
// For public exposure, replace with HttpOnly cookies.

'use strict';

// ── Constants ────────────────────────────────────────────────────────────────

const AUTH_KEY = 'wally_token';
const EMOTION_COLORS = {
  anger:    '#ef4444',
  joy:      '#eab308',
  curiosity:'#22c55e',
  sadness:  '#3b82f6',
  boredom:  '#a855f7',
};
const EMOTION_EMOJIS = {
  anger: '😤', joy: '😊', sadness: '😢', curiosity: '🤔', boredom: '😴',
};
const EMOTION_LABELS = {
  anger: 'ANGER', joy: 'JOY', curiosity: 'CURIOSITY', sadness: 'SADNESS', boredom: 'BOREDOM',
};
const EMOTIONS = ['anger', 'joy', 'sadness', 'curiosity', 'boredom'];

const PLATFORM_COLORS = {
  discord: '#5865F2',
  twitch: '#9146FF',
};

const PLATFORM_ICONS = {
  discord: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>',
  twitch: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/></svg>',
};

// ── State ────────────────────────────────────────────────────────────────────

let currentMode = 'public';
let currentTab  = 'status';
let emotionSSE  = null;
let logSSE      = null;
let logFilter   = 'ALL';
let currentEmotions = {};
let currentGraphSince = null;
let _graphMeta  = null;
let _rafPending = false;
let hiddenEmotions = new Set(); // for interactive legend

// ── Web Chat state ──────────────────────────────────────────────
let _chatWs = null;
let _chatUser = null;
let _chatTypingTimer = null;

// ── Mode & tabs ───────────────────────────────────────────────────────────────

function toggleMode() {
  switchMode(currentMode === 'public' ? 'admin' : 'public');
}

function _isMobileNav() {
  return document.body.classList.contains('is-mobile');
}

function switchMode(mode, restoreTab = null) {
  if (mode === 'admin') {
    if (!getToken()) { showAuthModal(); return; }
  }
  currentMode = mode;
  document.body.classList.toggle('admin-mode', mode === 'admin');

  const publicNav = document.getElementById('nav-public');
  const adminNav = document.getElementById('nav-admin');
  const divider = document.getElementById('sidebar-divider');
  const modeBtn = document.getElementById('sidebar-mode-toggle');

  if (_isMobileNav()) {
    // Mobile: swap nav groups — show one at a time
    publicNav.style.display = mode === 'admin' ? 'none' : 'flex';
    adminNav.style.display = mode === 'admin' ? 'flex' : 'none';
    if (divider) divider.style.display = 'none';
    // Update toggle button: back arrow + "Retour" label in admin, lock icon in public
    if (modeBtn) {
      modeBtn.classList.toggle('active', mode === 'admin');
      const svg = modeBtn.querySelector('svg');
      const span = modeBtn.querySelector('span');
      if (svg) {
        svg.innerHTML = mode === 'admin'
          ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>'
          : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>';
      }
      if (span) {
        span.textContent = mode === 'admin' ? 'Retour' : 'Admin';
        span.style.display = mode === 'admin' ? 'block' : '';
      }
    }
  } else {
    // Desktop: show both nav groups
    publicNav.style.display = 'flex';
    adminNav.style.display = mode === 'admin' ? 'flex' : 'none';
    if (divider) divider.style.display = mode === 'admin' ? 'block' : 'none';
    if (modeBtn) modeBtn.classList.toggle('active', mode === 'admin');
  }

  const firstTab = restoreTab || (mode === 'public' ? 'status' : 'admin-config');
  showTab(firstTab);

  if (mode === 'admin') {
    loadConfig();
    startLogSSE();
  } else {
    stopLogSSE();
  }
}

function showTab(tabId) {
  document.querySelectorAll('.sidebar-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  const btn = document.querySelector(`.sidebar-item[data-tab="${tabId}"]`);
  if (btn) btn.classList.add('active');

  const content = document.getElementById(`tab-${tabId}`);
  if (content) content.classList.add('active');

  currentTab = tabId;
  location.hash = `${currentMode}/${tabId}`;

  if (tabId === 'status') {
    loadStreamStatus();
    requestAnimationFrame(() => loadEmotionHistory(currentGraphSince));
  }
  if (tabId === 'roadmap') loadRoadmap();
  if (tabId === 'chat') renderChatTab();
  if (tabId === 'journal-detail') renderJournalDetailTab();
  if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
  if (tabId !== 'memory' && _linkMode) { _linkMode = false; _linkSelection = []; }
  if (tabId === 'admin-costs') loadCosts();
  pollCostsBadge();
  pollLinksBadge();
  if (tabId === 'admin-logs') {
    requestAnimationFrame(() => {
      const el = document.getElementById('log-stream');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
}

// ── Auth ─────────────────────────────────────────────────────────────────────

function getToken()       { return localStorage.getItem(AUTH_KEY); }
function saveToken(t)     { localStorage.setItem(AUTH_KEY, t); }
function clearToken()     { localStorage.removeItem(AUTH_KEY); }
function showAuthModal()  { document.getElementById('auth-modal').classList.add('visible'); }
function hideAuthModal()  { document.getElementById('auth-modal').classList.remove('visible'); }

async function submitToken() {
  const t = document.getElementById('token-input').value.trim();
  if (!t) return;
  const r = await fetch('/api/admin/config', { headers: { 'Authorization': `Bearer ${t}` } });
  if (r.ok) {
    saveToken(t);
    hideAuthModal();
    document.getElementById('token-input').value = '';
    _sessionExpiredFired = false;
    switchMode('admin');
    toast('Accès admin accordé', 'success');
  } else {
    toast('Token invalide', 'error');
  }
}

// ── API helpers ───────────────────────────────────────────────────────────────

let _sessionExpiredFired = false;

async function apiFetch(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(url, { ...opts, headers });
  if (r.status === 401) {
    if (token && !_sessionExpiredFired) {
      _sessionExpiredFired = true;
      toast('Session expirée', 'error');
    }
    clearToken();
    switchMode('public');
    return null;
  }
  return r;
}

// ── Toasts — improved durations & close button ───────────────────────────────

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;

  const textSpan = document.createElement('span');
  textSpan.textContent = msg;
  el.appendChild(textSpan);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'toast-close';
  closeBtn.textContent = '×';
  closeBtn.setAttribute('aria-label', 'Fermer');
  closeBtn.onclick = () => dismissToast(el);
  el.appendChild(closeBtn);

  document.getElementById('toast-container').appendChild(el);

  const duration = type === 'error' ? 6000 : 3000;
  el._timeout = setTimeout(() => dismissToast(el), duration);
}

function dismissToast(el) {
  if (el._dismissed) return;
  el._dismissed = true;
  clearTimeout(el._timeout);
  el.style.animation = 'toast-out 0.2s ease forwards';
  setTimeout(() => el.remove(), 200);
}

// ── Status polling ────────────────────────────────────────────────────────────

async function loadStatus() {
  const r = await fetch('/api/public/status');
  if (!r.ok) return;
  const d = await r.json();

  const s = Math.floor(d.uptime_seconds);
  const days = Math.floor(s / 86400);
  const hrs  = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  document.getElementById('uptime').textContent =
    days > 0 ? `${days}j ${hrs}h ${mins}m` : `${hrs}h ${mins}m`;

  const setDot = (id, online) => {
    const dot = document.getElementById(id);
    dot.classList.toggle('online',  online);
    dot.classList.toggle('offline', !online);
    dot.setAttribute('aria-label', `${id.replace('dot-', '')} ${online ? 'en ligne' : 'hors ligne'}`);
  };
  setDot('dot-discord', d.discord_online);
  setDot('dot-twitch',  d.twitch_online);
  document.getElementById('stat-messages').textContent = d.total_messages.toLocaleString();
}

// ── Emotions SSE ──────────────────────────────────────────────────────────────

function buildGauges(containerId, editable) {
  const c = document.getElementById(containerId);
  c.innerHTML = '';
  for (const e of EMOTIONS) {
    const row = document.createElement('div');
    row.className = 'emotion-row';
    if (!editable) {
      row.innerHTML = `
        <span class="emotion-label" style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
        <div class="gauge-track" role="progressbar" aria-label="${EMOTION_LABELS[e]}" aria-valuenow="0" aria-valuemin="0" aria-valuemax="1">
          <div class="gauge-fill ${e}" id="fill-${e}"></div>
        </div>
        <span class="gauge-val" id="val-${e}">0.00</span>
      `;
    } else {
      row.innerHTML = `
        <span class="emotion-label" style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
        <input type="range" class="emotion-slider" id="slider-${e}" min="0" max="1" step="0.01" value="0"
               aria-label="${EMOTION_LABELS[e]}"
               oninput="document.getElementById('val-${e}').textContent=parseFloat(this.value).toFixed(2)"
               onchange="setEmotion('${e}', parseFloat(this.value))">
        <span class="gauge-val" id="val-${e}">0.00</span>
      `;
    }
    c.appendChild(row);
  }
}

function updateEmotionGauges(emotions) {
  currentEmotions = emotions;
  for (const e of EMOTIONS) {
    const v = emotions[e] ?? 0;
    const fill = document.getElementById(`fill-${e}`);
    if (fill) {
      fill.style.width = `${(v * 100).toFixed(1)}%`;
      const track = fill.parentElement;
      if (track) track.setAttribute('aria-valuenow', v.toFixed(2));
    }
    const slider = document.getElementById(`slider-${e}`);
    if (slider) slider.value = v;
    const val = document.getElementById(`val-${e}`);
    if (val) val.textContent = v.toFixed(2);
  }
  updateEmotionSummary(emotions);
  updateFavicon(emotions);
}

function updateEmotionSummary(emotions) {
  const dominant = EMOTIONS.filter(e => emotions[e] >= 0.4);
  const el = document.getElementById('emotion-summary');
  if (!el) return;
  if (dominant.length === 0) { el.textContent = 'Wally est dans un état neutre.'; return; }
  const names = { anger:'en colère', joy:'joyeux', sadness:'triste', curiosity:'curieux', boredom:'ennuyé' };
  el.textContent = `Wally est ${dominant.map(e => names[e]).join(' et ')}.`;
}

function updateFavicon(emotions) {
  const dominant = EMOTIONS.reduce((a, b) => (emotions[a] > emotions[b] ? a : b));
  const color = emotions[dominant] >= 0.2 ? EMOTION_COLORS[dominant] : '#888888';
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='13' fill='${color}'/><circle cx='16' cy='16' r='14' fill='none' stroke='rgba(255,255,255,0.4)' stroke-width='1.5'/></svg>`;
  document.getElementById('favicon').href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function startEmotionSSE() {
  if (emotionSSE) emotionSSE.close();
  emotionSSE = new EventSource('/api/public/sse/emotions');
  emotionSSE.onmessage = (e) => {
    try { updateEmotionGauges(JSON.parse(e.data)); } catch {}
  };
  emotionSSE.onerror = () => {};
}

// ── Emotion canvas graph ──────────────────────────────────────────────────────

async function loadEmotionHistory(since) {
  const url = since != null
    ? `/api/public/emotions/history?since=${since}`
    : '/api/public/emotions/history';
  const r = await fetch(url);
  if (!r.ok) return;
  const { history } = await r.json();

  if (!history || history.length < 2) {
    showGraphEmpty('emotionCanvas', 'Pas assez de données pour cette période.');
    const avgEl = document.getElementById('emotion-averages');
    if (avgEl) avgEl.style.display = 'none';
    _graphMeta = null;
    return;
  }

  drawEmotionGraph(history);
  renderEmotionAverages(history);
  buildEmotionLegend();
}

function showGraphEmpty(canvasId, message) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const W = canvas.offsetWidth || 800;
  const H = 165;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.fillStyle = '#11151c';
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.font = '13px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(message, W / 2, H / 2);
}

function setGraphRange(range) {
  const now = Date.now() / 1000;
  const titles = {
    '1h':  '📈 DERNIÈRE HEURE',
    '24h': '📈 DERNIÈRES 24H',
    '7d':  '📈 7 DERNIERS JOURS',
    '30d': '📈 30 DERNIERS JOURS',
  };
  const offsets = { '1h': 3600, '24h': 86400, '7d': 7*86400, '30d': 30*86400 };
  currentGraphSince = now - offsets[range];

  const titleEl = document.getElementById('graph-title');
  if (titleEl) titleEl.textContent = titles[range];

  const btnLabels = { '1h': '1H', '24h': '24H', '7d': '7J', '30d': '30J' };
  document.querySelectorAll('.graph-range-btn').forEach(btn => {
    btn.classList.toggle('active', btn.textContent === btnLabels[range]);
  });

  loadEmotionHistory(currentGraphSince);
}

function renderEmotionAverages(history) {
  const el = document.getElementById('emotion-averages');
  if (!el) return;
  if (!history || history.length < 2) { el.style.display = 'none'; return; }
  const avgs = {};
  for (const e of EMOTIONS) {
    const sum = history.reduce((acc, snap) => acc + (snap[e] ?? 0), 0);
    avgs[e] = sum / history.length;
  }
  el.innerHTML = EMOTIONS.map(e =>
    `<span style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]} ${avgs[e].toFixed(2)}</span>`
  ).join('');
  el.style.display = 'flex';
}

// ── Interactive legend ───────────────────────────────────────────────────────

function buildEmotionLegend() {
  const el = document.getElementById('emotion-graph-legend');
  if (!el) return;
  el.innerHTML = EMOTIONS.map(e => {
    const hidden = hiddenEmotions.has(e);
    return `<div class="graph-legend-item ${hidden ? 'hidden-emotion' : ''}"
                 onclick="toggleEmotion('${e}')" title="Cliquer pour ${hidden ? 'afficher' : 'masquer'}">
      <span class="legend-line" style="background:${EMOTION_COLORS[e]}"></span>
      <span>${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
    </div>`;
  }).join('');
}

function toggleEmotion(emotion) {
  if (hiddenEmotions.has(emotion)) hiddenEmotions.delete(emotion);
  else hiddenEmotions.add(emotion);
  buildEmotionLegend();
  if (_graphMeta) drawEmotionGraph(_graphMeta.history);
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function drawEmotionGraph(history) {
  const canvas = document.getElementById('emotionCanvas');
  if (!canvas || !history || history.length < 2) return;

  const W = canvas.offsetWidth || 800;
  const H = 165;
  const dpr = window.devicePixelRatio || 1;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width  = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  ctx.fillStyle = '#11151c';
  ctx.fillRect(0, 0, W, H);

  const PAD = { top: 10, bottom: 24, left: 4, right: 4 };
  const gW = W - PAD.left - PAD.right;
  const gH = H - PAD.top - PAD.bottom;

  const tMin = history[0].snapshot_at;
  const tMax = history[history.length - 1].snapshot_at;
  const tRange = tMax - tMin || 1;

  _graphMeta = { history, tMin, tRange, PAD, gW, gH, W, H };

  // Grid
  ctx.lineWidth = 1;
  for (let pct = 0.25; pct <= 1.0; pct += 0.25) {
    const y = PAD.top + (1 - pct) * gH;
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(W - PAD.right, y);
    ctx.stroke();
  }

  // Time ticks
  {
    const rawRange = tMax - tMin;
    let tickStep, tickMode;
    if (rawRange <= 1.1 * 3600) { tickStep = 600; tickMode = 'minute'; }
    else if (rawRange <= 27 * 3600) { tickStep = 7200; tickMode = 'hour'; }
    else if (rawRange <= 8 * 86400) { tickStep = 86400; tickMode = 'day'; }
    else { tickStep = 172800; tickMode = 'day'; }

    let firstTick;
    if (tickMode === 'minute') firstTick = Math.ceil(tMin / 600) * 600;
    else if (tickMode === 'hour') firstTick = Math.ceil(tMin / 3600) * 3600;
    else {
      const d = new Date(tMin * 1000);
      d.setHours(0, 0, 0, 0);
      if (d.getTime() / 1000 < tMin) d.setDate(d.getDate() + 1);
      firstTick = d.getTime() / 1000;
    }

    ctx.globalAlpha = 1;
    for (let t = firstTick; t <= tMax; t += tickStep) {
      const x = PAD.left + ((t - tMin) / tRange) * gW;
      if (x < PAD.left + 40 || x > W - PAD.right - 40) continue;

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, PAD.top);
      ctx.lineTo(x, PAD.top + gH);
      ctx.stroke();

      const label = tickMode === 'minute'
        ? new Date(t * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' })
        : tickMode === 'hour'
          ? new Date(t * 1000).toLocaleTimeString('fr', { hour: '2-digit' })
          : new Date(t * 1000).toLocaleDateString('fr', { day: 'numeric', month: 'numeric' });
      ctx.fillStyle = 'rgba(255,255,255,0.3)';
      ctx.font = '10px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(label, x, H - 8);
    }
  }

  // Emotion lines + area fill
  const visibleEmotions = EMOTIONS.filter(e => !hiddenEmotions.has(e));

  for (const e of visibleEmotions) {
    let firstX = 0, lastX = 0;

    ctx.beginPath();
    ctx.strokeStyle = EMOTION_COLORS[e];
    ctx.lineWidth = 2;
    ctx.globalAlpha = 0.85;
    history.forEach((snap, i) => {
      const x = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
      const y = PAD.top  + (1 - (snap[e] ?? 0)) * gH;
      if (i === 0) { ctx.moveTo(x, y); firstX = x; }
      else ctx.lineTo(x, y);
      lastX = x;
    });
    ctx.stroke();

    ctx.beginPath();
    ctx.globalAlpha = 1;
    history.forEach((snap, i) => {
      const x = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
      const y = PAD.top  + (1 - (snap[e] ?? 0)) * gH;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.lineTo(lastX,  PAD.top + gH);
    ctx.lineTo(firstX, PAD.top + gH);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + gH);
    grad.addColorStop(0, hexToRgba(EMOTION_COLORS[e], 0.2));
    grad.addColorStop(1, hexToRgba(EMOTION_COLORS[e], 0.01));
    ctx.fillStyle = grad;
    ctx.fill();
  }

  ctx.globalAlpha = 1;

  // Time axis endpoints
  ctx.fillStyle = 'rgba(255,255,255,0.35)';
  ctx.font = '10px monospace';
  ctx.textAlign = 'left';
  ctx.fillText(new Date(tMin * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' }), PAD.left, H - 8);
  ctx.textAlign = 'right';
  ctx.fillText(new Date(tMax * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' }), W - PAD.right, H - 8);
}

// ── Stream status ─────────────────────────────────────────────────────────────

async function loadStreamStatus() {
  const r = await fetch('/api/public/twitch/stream');
  if (!r.ok) return;
  const d = await r.json();
  const el = document.getElementById('stream-content');

  if (d.live) {
    el.innerHTML = `
      <div class="stream-live-badge"><span class="dot"></span> LIVE</div>
      <div style="font-size:1.05rem;font-weight:700;margin-bottom:6px">${escHtml(d.title || '')}</div>
      <div style="color:var(--text-muted);margin-bottom:4px;font-size:0.85rem">${escHtml(d.category || '')}</div>
      <div style="font-size:1.4rem;font-weight:800;color:var(--c-curiosity)">${(d.viewers || 0).toLocaleString()} viewers</div>
    `;
  } else {
    el.innerHTML = `
      <div class="stream-offline-badge"><span class="dot"></span> OFFLINE</div>
      ${d.started_at ? `<div style="color:var(--text-muted);margin-top:6px;font-size:0.85rem">Dernier stream : ${new Date(d.started_at).toLocaleString('fr')}</div>` : ''}
    `;
  }
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Admin config ──────────────────────────────────────────────────────────────

async function loadConfig() {
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) return;
  const cfg = await r.json();
  renderConfigForm(cfg);
}

async function loadOpenAIModels() {
  const r = await apiFetch('/api/admin/openai/models');
  if (!r || !r.ok) return [];
  const { models } = await r.json();
  return models;
}

async function renderConfigForm(cfg) {
  const container = document.getElementById('config-form-container');
  const models = await loadOpenAIModels();

  const REASONING_EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'];
  const TEXT_VERBOSITIES = ['low', 'medium', 'high'];

  container.innerHTML = `
    <!-- OpenAI -->
    <div class="card config-section">
      <div class="config-section-title">OPENAI</div>
      <div class="field-group">
        <label class="field-label" for="cfg-primary-model">Modèle principal</label>
        <select id="cfg-primary-model">
          ${models.map(m => `<option value="${m}" ${m === cfg.openai.primary_model ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-secondary-model">Modèle secondaire</label>
        <select id="cfg-secondary-model">
          ${models.map(m => `<option value="${m}" ${m === cfg.openai.secondary_model ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-reasoning-effort">Niveau d'effort (reasoning)</label>
        <select id="cfg-reasoning-effort">
          ${REASONING_EFFORTS.map(e => `<option value="${e}" ${e === cfg.openai.reasoning_effort ? 'selected' : ''}>${e.toUpperCase()}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-text-verbosity">Verbosité des réponses</label>
        <select id="cfg-text-verbosity">
          ${TEXT_VERBOSITIES.map(v => `<option value="${v}" ${v === cfg.openai.text_verbosity ? 'selected' : ''}>${v.toUpperCase()}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-max-tokens">Max output tokens</label>
        <input type="number" id="cfg-max-tokens" min="100" max="32000" value="${cfg.openai.max_tokens}">
      </div>
      <button class="btn btn-success" onclick="saveOpenAI()">💾 SAUVEGARDER</button>
    </div>

    <!-- Émotions — lambdas -->
    <div class="card config-section">
      <div class="config-section-title">DÉCROISSANCE ÉMOTIONS (λ)</div>
      ${Object.entries(cfg.emotions).map(([name, ec]) => `
        <div class="field-group">
          <label class="field-label" for="cfg-lambda-${name}" style="color:${EMOTION_COLORS[name] || 'var(--text-muted)'}">${name.toUpperCase()} λ</label>
          <input type="range" id="cfg-lambda-${name}" min="0.01" max="2" step="0.01" value="${ec.decay_lambda}"
            oninput="document.getElementById('lbl-lambda-${name}').textContent=parseFloat(this.value).toFixed(2)">
          <span id="lbl-lambda-${name}" style="font-family:var(--font-mono);font-size:0.85rem">${ec.decay_lambda.toFixed(2)}</span>
        </div>
      `).join('')}
      <button class="btn btn-success" onclick="saveEmotionLambdas()">💾 SAUVEGARDER</button>
    </div>

    <!-- Bot général -->
    <div class="card config-section">
      <div class="config-section-title">BOT GÉNÉRAL</div>
      <div class="field-group">
        <label class="field-label" for="cfg-lang">Langue par défaut</label>
        <input type="text" id="cfg-lang" value="${cfg.bot.language_default}">
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-journal-time">Heure journal (HH:MM)</label>
        <input type="text" id="cfg-journal-time" value="${cfg.bot.journal_time}">
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-ctx-size">Taille fenêtre contexte</label>
        <input type="number" id="cfg-ctx-size" value="${cfg.bot.context_window_size}">
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-triggers">Triggers (séparés par virgule)</label>
        <input type="text" id="cfg-triggers" value="${(cfg.bot.trigger_names || []).join(', ')}">
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-cost-threshold">Seuil d'alerte coûts ($)</label>
        <input type="number" id="cfg-cost-threshold" min="1" max="1000" step="0.5" value="${cfg.bot.cost_alert_threshold || 25}">
      </div>
      <button class="btn btn-success" onclick="saveBotGeneral()">💾 SAUVEGARDER</button>
    </div>

    <!-- Chaînes Twitch invitées -->
    <div class="card config-section" id="guest-channels-card">
      <div class="config-section-title">CHAÎNES TWITCH INVITÉES</div>
      <div id="guest-channels-list">
        ${(cfg.twitch.guest_channels || []).length === 0
          ? '<p style="color:var(--text-muted);margin:0 0 12px">Aucune chaîne invitée.</p>'
          : (cfg.twitch.guest_channels || []).map(ch => `
            <div class="guest-channel-item" id="guest-ch-${ch}" style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <span style="flex:1;font-family:var(--font-mono);font-size:0.85rem">${ch}</span>
              <button class="btn btn-danger" style="padding:2px 8px;font-size:0.8em"
                onclick="removeGuestChannel('${ch}')">✕</button>
            </div>`).join('')
        }
      </div>
      <div style="display:flex;gap:8px;margin-top:8px">
        <input type="text" id="guest-channel-input" placeholder="nom de chaîne twitch…"
               style="flex:1" onkeydown="if(event.key==='Enter') addGuestChannel()">
        <button class="btn btn-success" onclick="addGuestChannel()">+ Ajouter</button>
      </div>
      <div id="guest-channel-error" style="color:var(--c-offline);font-size:0.85em;margin-top:6px;display:none"></div>
      <p style="color:var(--text-muted);font-size:0.8em;margin-top:10px">
        Le broadcaster doit avoir autorisé le bot (scope <code>channel:bot</code>) pour que Wally puisse parler.
      </p>
    </div>
  `;
}

async function saveOpenAI() {
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify({ openai: {
      primary_model:    document.getElementById('cfg-primary-model').value,
      secondary_model:  document.getElementById('cfg-secondary-model').value,
      reasoning_effort: document.getElementById('cfg-reasoning-effort').value,
      text_verbosity:   document.getElementById('cfg-text-verbosity').value,
      max_tokens:       parseInt(document.getElementById('cfg-max-tokens').value),
    }}),
  });
  if (r && r.ok) toast('Config OpenAI sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
}

async function saveEmotionLambdas() {
  const emotions = {};
  for (const e of EMOTIONS) {
    const el = document.getElementById(`cfg-lambda-${e}`);
    if (el) emotions[e] = { decay_lambda: parseFloat(el.value) };
  }
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify({ emotions }) });
  if (r && r.ok) toast('Lambdas sauvegardés', 'success'); else toast('Erreur sauvegarde', 'error');
}

async function saveBotGeneral() {
  const triggers = document.getElementById('cfg-triggers').value
    .split(',').map(s => s.trim()).filter(Boolean);
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify({ bot: {
      language_default: document.getElementById('cfg-lang').value,
      journal_time:     document.getElementById('cfg-journal-time').value,
      context_window_size: parseInt(document.getElementById('cfg-ctx-size').value),
      trigger_names:    triggers,
      cost_alert_threshold: parseFloat(document.getElementById('cfg-cost-threshold').value),
    }}),
  });
  if (r && r.ok) toast('Config bot sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
}

// ── Guest channels ─────────────────────────────────────────────────────────────

async function addGuestChannel() {
  const input = document.getElementById('guest-channel-input');
  const errEl = document.getElementById('guest-channel-error');
  const name = input.value.trim().toLowerCase();
  errEl.style.display = 'none';

  if (!name || !/^[a-z0-9_]{1,25}$/.test(name)) {
    errEl.textContent = 'Nom de chaîne invalide (1–25 caractères, alphanumériques + _).';
    errEl.style.display = 'block';
    return;
  }

  const r = await apiFetch('/api/admin/twitch/channels', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });

  if (!r) { errEl.textContent = 'Erreur réseau.'; errEl.style.display = 'block'; return; }
  if (r.status === 409) { errEl.textContent = 'Chaîne déjà ajoutée.'; errEl.style.display = 'block'; return; }
  if (r.status === 404) { errEl.textContent = 'Chaîne introuvable sur Twitch.'; errEl.style.display = 'block'; return; }
  if (r.status === 503) { errEl.textContent = 'API Twitch indisponible.'; errEl.style.display = 'block'; return; }
  if (!r.ok) { errEl.textContent = 'Erreur serveur.'; errEl.style.display = 'block'; return; }

  const list = document.getElementById('guest-channels-list');
  const empty = list.querySelector('p');
  if (empty) empty.remove();
  const item = document.createElement('div');
  item.id = `guest-ch-${name}`;
  item.className = 'guest-channel-item';
  item.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px';
  item.innerHTML = `<span style="flex:1;font-family:var(--font-mono);font-size:0.85rem">${name}</span>
    <button class="btn btn-danger" style="padding:2px 8px;font-size:0.8em"
      onclick="removeGuestChannel('${name}')">✕</button>`;
  list.appendChild(item);
  input.value = '';
  toast(`Wally rejoint ${name}`, 'success');
}

async function removeGuestChannel(name) {
  const r = await apiFetch(`/api/admin/twitch/channels/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (r && r.ok) {
    const el = document.getElementById(`guest-ch-${name}`);
    if (el) el.remove();
    const list = document.getElementById('guest-channels-list');
    if (list && !list.querySelector('.guest-channel-item')) {
      list.innerHTML = '<p style="color:var(--text-muted);margin:0 0 12px">Aucune chaîne invitée.</p>';
    }
    toast(`Wally a quitté ${name}`, 'success');
  } else {
    toast('Erreur lors de la suppression', 'error');
  }
}

// ── Admin emotions ────────────────────────────────────────────────────────────

async function setEmotion(emotion, value) {
  const r = await apiFetch('/api/admin/emotions/set', {
    method: 'POST',
    body: JSON.stringify({ emotion, value }),
  });
  if (r && r.ok) toast(`${emotion}: ${value.toFixed(2)}`, 'success');
  else toast('Erreur', 'error');
}

async function resetEmotions() {
  const r = await apiFetch('/api/admin/emotions/reset', { method: 'POST' });
  if (r && r.ok) {
    for (const e of EMOTIONS) {
      const s = document.getElementById(`slider-${e}`);
      if (s) { s.value = 0.5; document.getElementById(`val-${e}`).textContent = '0.50'; }
    }
    toast('Émotions reset à 0.5', 'success');
  } else {
    toast('Erreur reset', 'error');
  }
}

// ── Admin logs SSE ────────────────────────────────────────────────────────────

async function startLogSSE() {
  if (logSSE) logSSE.close();
  const token = getToken();
  if (!token) return;

  await loadLogHistory();

  logSSE = new EventSource(`/api/admin/sse/logs`);
  logSSE.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'links_analyzed' || data.type === 'link_accepted' || data.type === 'link_rejected' || data.type === 'link_unlinked') {
        const filter = document.getElementById('mem-user-filter')?.value || '';
        loadMemoryUsers(filter);
        if (_selectedMemUser) loadUserDetail(_selectedMemUser);
        pollLinksBadge();
        if (data.type === 'links_analyzed' && data.count > 0) {
          toast(`🔗 ${data.count} liaison(s) à vérifier`, 'info');
        }
        return;
      }
      appendLog(data);
    } catch {}
  };
}

async function loadLogHistory() {
  const r = await apiFetch('/api/admin/logs/history');
  if (!r || !r.ok) return;
  const { entries } = await r.json();
  for (const entry of entries) appendLog(entry);
}

function stopLogSSE() {
  if (logSSE) { logSSE.close(); logSSE = null; }
}

const MAX_LOG_ENTRIES = 200;

function appendLog(entry) {
  const el = document.getElementById('log-stream');
  if (!el) return;
  const div = document.createElement('div');
  div.className = `log-entry ${entry.level}`;
  if (logFilter !== 'ALL' && entry.level !== logFilter) div.classList.add('hidden');
  div.textContent = `[${entry.time}] ${entry.level.padEnd(7)} ${entry.message}`;
  el.appendChild(div);
  while (el.children.length > MAX_LOG_ENTRIES) el.removeChild(el.firstChild);
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) {
    el.scrollTop = el.scrollHeight;
  }
}

function setLogFilter(level) {
  logFilter = level;
  document.querySelectorAll('.log-controls .btn').forEach(b => {
    b.classList.toggle('active', b.id === `log-filter-${level}`);
  });
  document.querySelectorAll('.log-entry').forEach(e => {
    e.classList.toggle('hidden', level !== 'ALL' && !e.classList.contains(level));
  });
}

function clearLogs() {
  const el = document.getElementById('log-stream');
  if (el) el.innerHTML = '';
}

// ── Init ──────────────────────────────────────────────────────────────────────

// ── Naker blur behind cards ──────────────────────────────────────────────────

function initNakerBlur() {
  const blurred = document.getElementById('naker-blurred');
  if (!blurred) return;
  const ctx = blurred.getContext('2d');
  let src = null;

  function findSource() {
    if (src) return src;
    const el = document.querySelector('#naker-bg canvas');
    if (el) { src = el; return src; }
    return null;
  }

  function loop() {
    const s = findSource();
    if (s && s.width && s.height) {
      if (blurred.width !== s.width || blurred.height !== s.height) {
        blurred.width = s.width;
        blurred.height = s.height;
      }
      ctx.clearRect(0, 0, blurred.width, blurred.height);
      ctx.drawImage(s, 0, 0);
      blurred.style.opacity = '1';
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
}

document.addEventListener('DOMContentLoaded', async () => {
  // Start naker blur mirror (delayed to let naker init)
  setTimeout(initNakerBlur, 1000);

  buildGauges('gauges-public', false);
  buildGauges('gauges-admin',  true);

  await loadStatus();
  startEmotionSSE();
  setInterval(loadStatus, 30000);

  loadStreamStatus();
  requestAnimationFrame(() => setGraphRange('1h'));
  pollCostsBadge();
  pollLinksBadge();

  // ── Tooltip hover — emotion graph ─────────────────────────────────────
  const emotionCanvas = document.getElementById('emotionCanvas');
  if (emotionCanvas) {
    emotionCanvas.addEventListener('mousemove', (ev) => {
      if (!_graphMeta || _rafPending) return;
      const clientX = ev.clientX;
      _rafPending = true;
      requestAnimationFrame(() => {
        _rafPending = false;
        const { history, tMin, tRange, PAD, gW, gH, W, H } = _graphMeta;
        const rect = emotionCanvas.getBoundingClientRect();
        const mouseX = clientX - rect.left;

        let nearest = null, minDist = Infinity;
        for (const snap of history) {
          const sx = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
          const dist = Math.abs(sx - mouseX);
          if (dist < minDist) { minDist = dist; nearest = snap; }
        }

        drawEmotionGraph(history);
        if (!nearest) return;

        const ctx = emotionCanvas.getContext('2d');
        const visibleEmotions = EMOTIONS.filter(e => !hiddenEmotions.has(e));
        const tw = 150;
        const th = 12 + visibleEmotions.length * 16 + 8;
        const tx = Math.min(mouseX + 12, W - tw - 4);
        const ty = 8;

        // Glass tooltip background
        ctx.fillStyle = 'rgba(17,21,28,0.88)';
        ctx.strokeStyle = 'rgba(0,212,255,0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(tx, ty, tw, th, 10);
        else { ctx.moveTo(tx + 10, ty); ctx.lineTo(tx + tw - 10, ty); ctx.quadraticCurveTo(tx + tw, ty, tx + tw, ty + 10); ctx.lineTo(tx + tw, ty + th - 10); ctx.quadraticCurveTo(tx + tw, ty + th, tx + tw - 10, ty + th); ctx.lineTo(tx + 10, ty + th); ctx.quadraticCurveTo(tx, ty + th, tx, ty + th - 10); ctx.lineTo(tx, ty + 10); ctx.quadraticCurveTo(tx, ty, tx + 10, ty); }
        ctx.fill();
        ctx.stroke();

        // Inner highlight
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.moveTo(tx + 12, ty + 1);
        ctx.lineTo(tx + tw - 12, ty + 1);
        ctx.stroke();

        ctx.textAlign = 'left';
        ctx.font = '10px monospace';
        visibleEmotions.forEach((e, i) => {
          ctx.fillStyle = EMOTION_COLORS[e];
          ctx.fillText(
            `${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}: ${(nearest[e] ?? 0).toFixed(2)}`,
            tx + 10, ty + 18 + i * 16
          );
        });
      });
    });
    emotionCanvas.addEventListener('mouseleave', () => {
      if (_graphMeta) drawEmotionGraph(_graphMeta.history);
    });
  }

  // ── Tooltip hover — cost graph ────────────────────────────────────────
  const costCanvas = document.getElementById('costCanvas');
  if (costCanvas) {
    costCanvas.addEventListener('mousemove', (ev) => {
      if (!_costGraphMeta || _costRafPending) return;
      const clientX = ev.clientX;
      _costRafPending = true;
      requestAnimationFrame(() => {
        _costRafPending = false;
        const { current, PAD, gW, gH, W, H, xStep, maxCost } = _costGraphMeta;
        const rect = costCanvas.getBoundingClientRect();
        const mouseX = clientX - rect.left;

        let nearestIdx = 0, minDist = Infinity;
        for (let i = 0; i < current.length; i++) {
          const sx = PAD.left + i * xStep;
          const dist = Math.abs(sx - mouseX);
          if (dist < minDist) { minDist = dist; nearestIdx = i; }
        }

        drawCostGraph(current, _costGraphMeta.previous);
        const d = current[nearestIdx];
        if (!d) return;

        const ctx = costCanvas.getContext('2d');
        const px = PAD.left + nearestIdx * xStep;
        const py = PAD.top + (1 - d.cost / maxCost) * gH;

        // Vertical line
        ctx.strokeStyle = 'rgba(255,215,0,0.3)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(px, PAD.top);
        ctx.lineTo(px, PAD.top + gH);
        ctx.stroke();
        ctx.setLineDash([]);

        // Point
        ctx.beginPath();
        ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#FFD700';
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.5)';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Tooltip
        const label = `${d.date}  $${d.cost.toFixed(4)}`;
        ctx.font = '11px monospace';
        const tw = ctx.measureText(label).width + 20;
        const th = 26;
        const ttx = Math.min(Math.max(px - tw / 2, 2), W - tw - 2);
        const tty = Math.max(py - th - 10, 2);

        ctx.fillStyle = 'rgba(17,21,28,0.9)';
        ctx.strokeStyle = 'rgba(255,215,0,0.25)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(ttx, tty, tw, th, 6);
        else { ctx.rect(ttx, tty, tw, th); }
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = '#FFD700';
        ctx.textAlign = 'center';
        ctx.fillText(label, ttx + tw / 2, tty + 17);
      });
    });
    costCanvas.addEventListener('mouseleave', () => {
      if (_costGraphMeta) drawCostGraph(_costGraphMeta.current, _costGraphMeta.previous);
    });
  }

  // Restore mode+tab from hash
  const hash = location.hash.replace('#', '');
  if (hash) {
    const [hashMode, hashTab] = hash.split('/');
    if (hashMode === 'admin' && getToken()) {
      switchMode('admin', hashTab || null);
    } else if (hashMode === 'public' && hashTab) {
      showTab(hashTab);
    }
  }
});

// ── Memory tab ────────────────────────────────────────────────────────────────

function escAttr(str) {
  return String(str).replace(/\\/g, '\\\\').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

let _showAllUsers = true; // show users without memories by default
let _linkMode = false;
let _linkSelection = []; // [{user_id, username}]

function renderMemoryTab() {
  document.getElementById('tab-memory').innerHTML = `
    <div class="mem-toolbar">
      <input type="text" id="mem-search" placeholder="Recherche globale…"
             oninput="onMemSearch(this.value)"
             style="flex:1;max-width:260px" aria-label="Recherche mémoire">
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <button class="btn ${_showAllUsers ? 'active' : ''}" onclick="toggleShowAll()" id="btn-show-all"
                style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">Tous les users</button>
        <button class="btn" onclick="toggleLinkMode()" id="btn-link-mode"
                style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">🔗 Lier deux users</button>
        <button class="btn" onclick="syncMemoryUsers()"
                style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">↻ Sync</button>
        <button class="btn" onclick="resolveUsernames()"
                style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">👤 Noms</button>
        <button class="btn btn-success" onclick="analyzeLinks()"
                style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">🔗 Auto-analyser</button>
      </div>
    </div>
    <div id="link-mode-bar" class="link-mode-bar" style="display:none"></div>
    <div class="mem-layout">
      <div class="mem-sidebar">
        <div class="mem-sidebar-filter">
          <input type="text" id="mem-user-filter" placeholder="Filtrer…"
                 oninput="onUserFilter(this.value)"
                 style="width:100%;font-size:0.8rem" aria-label="Filtrer utilisateurs">
        </div>
        <div class="mem-sidebar-actions">
          <button class="btn" onclick="showAddUserForm()" style="width:100%;font-size:0.72rem;padding:5px 8px">+ Ajouter un utilisateur</button>
        </div>
        <div class="mem-global-section" style="padding:12px;border-bottom:1px solid var(--glass-border)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span class="mem-detail-section-title" style="margin:0">🌐 MÉMOIRE GLOBALE <span id="global-mem-count" class="badge" style="font-size:0.6rem"></span></span>
            <button class="btn btn-sm" onclick="toggleAddGlobalMemory()" style="font-size:0.7rem;padding:2px 8px">+ Ajouter</button>
          </div>
          <div id="add-global-memory-form" style="display:none"></div>
          <div id="global-memory-list"></div>
        </div>
        <div id="mem-add-user-form" style="display:none"></div>
        <div id="mem-user-list" class="mem-user-list"></div>
      </div>
      <div id="mem-detail" class="mem-detail">
        <div class="mem-empty-state">
          Sélectionne un utilisateur pour voir ses souvenirs et liaisons.
        </div>
      </div>
    </div>
  `;
  loadMemoryUsers();
  loadGlobalMemories();
}

function toggleLinkMode() {
  _linkMode = !_linkMode;
  _linkSelection = [];
  const btn = document.getElementById('btn-link-mode');
  if (btn) btn.classList.toggle('active', _linkMode);
  updateLinkModeBar();
  // Re-render list to show link-mode styling
  refreshUserList();
  if (_linkMode) {
    document.getElementById('mem-detail').innerHTML =
      '<div class="mem-empty-state">Clique sur deux utilisateurs pour les lier.</div>';
  }
}

function updateLinkModeBar() {
  const bar = document.getElementById('link-mode-bar');
  if (!bar) return;
  if (!_linkMode) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';

  if (_linkSelection.length === 0) {
    bar.innerHTML = '<span>Sélectionne le <strong>premier</strong> utilisateur</span>'
      + '<button class="btn" onclick="toggleLinkMode()" style="font-size:0.68rem;padding:2px 8px;margin-left:auto">Annuler</button>';
  } else if (_linkSelection.length === 1) {
    const s = _linkSelection[0];
    bar.innerHTML = `<span>${PLATFORM_ICONS[s.platform] || ''} <strong>${escHtml(s.name)}</strong> ↔ sélectionne le <strong>second</strong></span>`
      + '<button class="btn" onclick="toggleLinkMode()" style="font-size:0.68rem;padding:2px 8px;margin-left:auto">Annuler</button>';
  } else {
    const a = _linkSelection[0], b = _linkSelection[1];
    bar.innerHTML = `<span>${PLATFORM_ICONS[a.platform] || ''} <strong>${escHtml(a.name)}</strong> ↔ ${PLATFORM_ICONS[b.platform] || ''} <strong>${escHtml(b.name)}</strong></span>`
      + '<div style="margin-left:auto;display:flex;gap:6px">'
      + '<button class="btn btn-success" onclick="confirmLinkSelection()" style="font-size:0.72rem;padding:4px 10px">✓ Lier</button>'
      + '<button class="btn" onclick="toggleLinkMode()" style="font-size:0.68rem;padding:2px 8px">Annuler</button>'
      + '</div>';
  }
}

function handleLinkModeClick(userId, username, platform) {
  // Don't add same user twice
  if (_linkSelection.some(s => s.user_id === userId)) return;
  // Max 2
  if (_linkSelection.length >= 2) return;

  _linkSelection.push({ user_id: userId, name: username, platform });
  updateLinkModeBar();

  // Highlight selected items
  document.querySelectorAll('.mem-user-item').forEach(el => {
    const isSelected = _linkSelection.some(s => s.user_id === el.dataset.uid);
    el.classList.toggle('link-selected', isSelected);
  });
}

async function confirmLinkSelection() {
  if (_linkSelection.length !== 2) return;
  const a = _linkSelection[0], b = _linkSelection[1];

  // Discord is always canonical if possible
  let canonical, alias;
  if (a.platform === 'discord') {
    canonical = a.user_id; alias = b.user_id;
  } else if (b.platform === 'discord') {
    canonical = b.user_id; alias = a.user_id;
  } else {
    // Both same platform — first selected is canonical
    canonical = a.user_id; alias = b.user_id;
  }

  const r = await apiFetch('/api/admin/links/manual', {
    method: 'POST',
    body: JSON.stringify({ canonical_id: canonical, alias_id: alias }),
  });
  if (r && r.ok) {
    toast('Comptes liés avec succès', 'success');
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur liaison', 'error');
  }
  // Exit link mode and refresh
  _linkMode = false;
  _linkSelection = [];
  const btn = document.getElementById('btn-link-mode');
  if (btn) btn.classList.remove('active');
  updateLinkModeBar();
  refreshUserList();
}

function refreshUserList() {
  const filter = document.getElementById('mem-user-filter')?.value || '';
  loadMemoryUsers(filter);
}

function toggleShowAll() {
  _showAllUsers = !_showAllUsers;
  const btn = document.getElementById('btn-show-all');
  if (btn) btn.classList.toggle('active', _showAllUsers);
  refreshUserList();
}

function showAddUserForm() {
  const el = document.getElementById('mem-add-user-form');
  if (!el) return;
  if (el.style.display !== 'none') { el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.innerHTML = `
    <div style="padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08)">
      <select id="add-user-platform" style="width:100%;margin-bottom:6px;font-size:0.8rem">
        <option value="discord">Discord</option>
        <option value="twitch">Twitch</option>
      </select>
      <input type="text" id="add-user-id" placeholder="ID ou username" style="width:100%;font-size:0.8rem;margin-bottom:6px">
      <input type="text" id="add-user-name" placeholder="Nom affiché (optionnel)" style="width:100%;font-size:0.8rem;margin-bottom:6px">
      <div style="display:flex;gap:6px">
        <button class="btn btn-success" onclick="submitAddUser()" style="flex:1;font-size:0.72rem;padding:4px 6px">Ajouter</button>
        <button class="btn" onclick="document.getElementById('mem-add-user-form').style.display='none'" style="font-size:0.72rem;padding:4px 6px">Annuler</button>
      </div>
    </div>
  `;
}

async function submitAddUser() {
  const platform = document.getElementById('add-user-platform').value;
  const userId = document.getElementById('add-user-id').value.trim();
  const username = document.getElementById('add-user-name').value.trim();
  if (!userId) { toast('ID requis', 'error'); return; }
  const r = await apiFetch('/api/admin/memory/users', {
    method: 'POST',
    body: JSON.stringify({ platform, user_id: userId, username }),
  });
  if (r && r.ok) {
    toast('Utilisateur ajouté', 'success');
    document.getElementById('mem-add-user-form').style.display = 'none';
    refreshUserList();
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

let _selectedMemUser = null;
let _selectedMemUsername = null;

async function loadMemoryUsers(filter = '') {
  const params = new URLSearchParams();
  if (filter) params.set('q', filter);
  if (_showAllUsers) params.set('show_all', '1');
  const url = '/api/admin/memory/users' + (params.toString() ? `?${params}` : '');
  const r = await apiFetch(url);
  if (!r || !r.ok) return;
  const { users } = await r.json();
  const el = document.getElementById('mem-user-list');
  if (!el) return;
  if (users.length === 0) {
    el.innerHTML = '<div style="color:var(--text-muted);font-size:0.75rem;padding:8px">Aucun utilisateur</div>';
    return;
  }
  el.innerHTML = users.map(u => {
    const selected = u.user_id === _selectedMemUser;
    const lastSeen = u.last_updated
      ? new Date(u.last_updated * 1000).toLocaleString('fr', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' })
      : '—';
    const trustColor = u.trust_score >= 0.7 ? 'var(--c-curiosity)' : u.trust_score <= 0.3 ? 'var(--c-offline)' : 'var(--text-muted)';
    const platformIcon = PLATFORM_ICONS[u.platform] || '';

    const pColor = PLATFORM_COLORS[u.platform] || 'var(--accent)';
    const linkedBadge = (u.linked_accounts || []).map(a =>
      `<span class="mem-link-badge" title="Lié à ${escAttr(a.alias_id)}">🔗 ${escHtml(a.alias_username)}</span>`
    ).join('');
    const noMemBadge = u.in_memory_users === false
      ? '<span class="mem-no-memory-badge">sans mémoire</span>'
      : '';
    const displayName = u.username || u.user_id.split(':').slice(1).join(':') || u.user_id;
    const linkSelected = _linkMode && _linkSelection.some(s => s.user_id === u.user_id);
    const clickHandler = _linkMode
      ? `handleLinkModeClick('${escAttr(u.user_id)}','${escAttr(displayName)}','${escAttr(u.platform)}')`
      : `selectMemUser('${escAttr(u.user_id)}','${escAttr(u.username || '')}', ${u.in_memory_users !== false})`;
    return `
    <div class="mem-user-item ${selected && !_linkMode ? 'selected' : ''} ${u.in_memory_users === false ? 'no-memory' : ''} ${linkSelected ? 'link-selected' : ''} ${_linkMode ? 'link-mode' : ''}"
         data-uid="${escAttr(u.user_id)}"
         onclick="${clickHandler}">
      <div class="mem-user-header">
        <span class="mem-platform-icon" style="color:${pColor}">${platformIcon}</span>
        <span class="mem-user-name">${escHtml(displayName)}</span>
        ${noMemBadge}${linkedBadge}
      </div>
      <div class="mem-user-meta">
        <span style="color:${trustColor}">🛡️ ${u.trust_score !== undefined ? u.trust_score.toFixed(2) : '—'}</span>
        <span>· ${escHtml(lastSeen)}</span>
      </div>
    </div>`;
  }).join('');
}

async function syncMemoryUsers() {
  const r = await apiFetch('/api/admin/memory/sync', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur sync', 'error'); return; }
  const { synced } = await r.json();
  toast(`${synced} utilisateur(s) importé(s)`, 'success');
  refreshUserList();
}

async function resolveUsernames() {
  const r = await apiFetch('/api/admin/memory/resolve-usernames', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur résolution', 'error'); return; }
  const { resolved } = await r.json();
  toast(`${resolved} nom(s) résolu(s)`, 'success');
  refreshUserList();
}

async function selectMemUser(userId, username, hasMemories = true) {
  _selectedMemUser = userId;
  _selectedMemUsername = username || null;
  document.querySelectorAll('.mem-user-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.uid === userId);
  });
  await loadUserDetail(userId, hasMemories);
}

async function loadUserDetail(userId, hasMemories = true) {
  const el = document.getElementById('mem-detail');
  if (!el) return;

  // Charger mémoires + liens en parallèle
  const [memR, linksR] = await Promise.all([
    hasMemories ? apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId)) : null,
    apiFetch('/api/admin/links?_t=' + Date.now()),
  ]);

  const memories = memR && memR.ok ? (await memR.json()).memories : [];
  const allLinks = linksR && linksR.ok ? (await linksR.json()).proposals : [];

  // Filtrer les liens pertinents pour cet utilisateur
  const userLinks = allLinks.filter(p =>
    p.canonical_id === userId || p.alias_id === userId
  );
  const pendingLinks = userLinks.filter(p => p.status === 'pending');
  const acceptedLinks = userLinks.filter(p => p.status === 'accepted');

  const displayName = _selectedMemUsername || userId.split(':').slice(1).join(':') || userId;
  const platform = userId.split(':')[0];
  const platformColors = { discord: '#5865F2', twitch: '#9146FF' };
  const pColor = PLATFORM_COLORS[platform] || 'var(--accent)';
  const platformIcon = PLATFORM_ICONS[platform] || '';

  el.innerHTML = `
    <!-- User header -->
    <div class="mem-detail-header">
      <div class="mem-detail-user">
        <span class="mem-detail-platform" style="color:${pColor}">${platformIcon}</span>
        <div>
          <div class="mem-detail-name">${escHtml(displayName)}</div>
          <div class="mem-detail-id">${escHtml(userId)}</div>
        </div>
      </div>
      <div class="mem-detail-actions">
        ${memories.length > 0 ? `<button class="btn btn-danger" onclick="deleteAllMemories('${escAttr(userId)}')"
                style="font-size:0.72rem;padding:4px 10px">🗑 Supprimer tout</button>` : ''}
      </div>
    </div>

    <!-- Link section -->
    ${acceptedLinks.length > 0 || pendingLinks.length > 0 ? `
    <div class="mem-detail-section">
      <div class="mem-detail-section-title">🔗 LIAISONS</div>
      ${acceptedLinks.map(p => {
        const otherId = p.canonical_id === userId ? p.alias_id : p.canonical_id;
        const otherName = p.canonical_id === userId
          ? (p.alias_username || otherId.split(':').slice(1).join(':'))
          : (p.canonical_username || otherId.split(':').slice(1).join(':'));
        const otherPlatform = otherId.split(':')[0];
        const otherIcon = PLATFORM_ICONS[otherPlatform] || '';
        const otherColor = PLATFORM_COLORS[otherPlatform] || 'var(--accent)';
        return `<div class="mem-link-card accepted">
          <span style="color:${otherColor}">${otherIcon}</span>
          <span>${escHtml(otherName)}</span>
          <span class="mem-link-status accepted">LIÉ</span>
          <button onclick="unlinkAccounts(${p.id})" class="btn btn-danger" style="font-size:0.62rem;padding:2px 8px;margin-left:4px" title="Délier ces comptes">✗ Délier</button>
        </div>`;
      }).join('')}
      ${pendingLinks.map(p => {
        const otherId = p.canonical_id === userId ? p.alias_id : p.canonical_id;
        const otherName = p.canonical_id === userId
          ? (p.alias_username || otherId.split(':').slice(1).join(':'))
          : (p.canonical_username || otherId.split(':').slice(1).join(':'));
        const otherPlatform = otherId.split(':')[0];
        const otherIcon = PLATFORM_ICONS[otherPlatform] || '';
        const otherColor = PLATFORM_COLORS[otherPlatform] || 'var(--accent)';
        return `<div class="mem-link-card pending">
          <span style="color:${otherColor}">${otherIcon}</span>
          <span>${escHtml(otherName)}</span>
          <span class="mem-link-confidence">${Math.round(p.confidence * 100)}%</span>
          <div class="mem-link-actions">
            <button onclick="acceptLink(${p.id})" class="btn btn-success" style="font-size:0.68rem;padding:2px 8px">✓</button>
            <button onclick="rejectLink(${p.id})" class="btn btn-danger" style="font-size:0.68rem;padding:2px 8px">✗</button>
          </div>
        </div>`;
      }).join('')}
    </div>
    ` : ''}

    <!-- Manual link + add memory -->
    <div class="mem-detail-section">
      <div class="mem-detail-section-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>${memories.length} SOUVENIR(S)</span>
        <div style="display:flex;gap:6px">
          <button class="btn" onclick="showAddMemoryForm('${escAttr(userId)}')" style="font-size:0.68rem;padding:2px 8px">+ Ajouter</button>
          <button class="btn" onclick="showInlineLink('${escAttr(userId)}')" style="font-size:0.68rem;padding:2px 8px">+ Lier un compte</button>
        </div>
      </div>
      <div id="add-memory-form" style="display:none"></div>
      <div id="inline-link-form" style="display:none"></div>
    </div>

    <!-- Memories -->
    <div class="mem-detail-memories">
      ${memories.length === 0
        ? '<div class="mem-empty-state">Aucun souvenir enregistré.</div>'
        : memories.map(m => {
          const mPlatform = m.source_platform || (m.source ? m.source.split(':')[0] : '');
          const mColor = PLATFORM_COLORS[mPlatform] || 'rgba(6,182,212,0.7)';
          const mSvg = PLATFORM_ICONS[mPlatform] || '';
          const mBadge = mSvg
            ? `<span class="mem-entry-platform" style="background:${mColor}20;color:${mColor};border-color:${mColor}40" title="${escAttr(mPlatform)}">${mSvg}${mPlatform}</span>`
            : '';
          const dateStr = m.updated_at || m.created_at;
          const dateBadge = dateStr
            ? `<span class="mem-entry-date">${new Date(dateStr).toLocaleString('fr', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' })}</span>`
            : '';
          return `
          <div class="mem-entry" id="mem-entry-${escAttr(m.id)}">
            <div class="mem-entry-content">
              <div class="mem-entry-meta">${mBadge}${dateBadge}</div>
              <span class="mem-entry-text" id="mem-text-${escAttr(m.id)}">${escHtml(m.memory)}</span>
            </div>
            <div class="mem-entry-actions">
              <button onclick="startEditMemory('${escAttr(m.source || userId)}','${escAttr(m.id)}')"
                      class="mem-entry-edit" aria-label="Modifier ce souvenir">&#9998;</button>
              <button onclick="deleteMemory('${escAttr(m.source || userId)}','${escAttr(m.id)}')"
                      class="mem-entry-delete" aria-label="Supprimer ce souvenir">&#10005;</button>
            </div>
          </div>`;
        }).join('')
      }
    </div>
  `;
}

function startEditMemory(userId, memoryId) {
  const textEl = document.getElementById('mem-text-' + memoryId);
  if (!textEl) return;
  const current = textEl.textContent;
  const entry = document.getElementById('mem-entry-' + memoryId);
  if (!entry) return;
  const contentDiv = entry.querySelector('.mem-entry-content');
  const actionsDiv = entry.querySelector('.mem-entry-actions');
  if (actionsDiv) actionsDiv.style.display = 'none';
  const metaHtml = contentDiv.querySelector('.mem-entry-meta')?.outerHTML || '';
  contentDiv.innerHTML = `
    ${metaHtml}
    <div style="display:flex;gap:6px;align-items:center;margin-top:4px">
      <input type="text" id="edit-memory-input-${escAttr(memoryId)}" value="${escAttr(current)}"
             style="flex:1;font-size:0.8rem" onkeydown="if(event.key==='Enter') submitEditMemory('${escAttr(userId)}','${escAttr(memoryId)}'); if(event.key==='Escape') cancelEditMemory();">
      <button onclick="submitEditMemory('${escAttr(userId)}','${escAttr(memoryId)}')" class="btn btn-success" style="font-size:0.68rem;padding:2px 8px">OK</button>
      <button onclick="cancelEditMemory()" class="btn" style="font-size:0.68rem;padding:2px 8px">✗</button>
    </div>
  `;
  document.getElementById('edit-memory-input-' + memoryId)?.focus();
}

async function submitEditMemory(userId, memoryId) {
  const input = document.getElementById('edit-memory-input-' + memoryId);
  const content = input?.value.trim();
  if (!content) { toast('Contenu requis', 'error'); return; }
  const r = await apiFetch(
    `/api/admin/memory/users/${encodeURIComponent(userId)}/memories/${encodeURIComponent(memoryId)}`,
    { method: 'PUT', body: JSON.stringify({ content }) }
  );
  if (r && r.ok) {
    toast('Souvenir modifié', 'success');
    await loadUserDetail(_selectedMemUser, true);
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

function cancelEditMemory() {
  if (_selectedMemUser) loadUserDetail(_selectedMemUser, true);
}

function showAddMemoryForm(userId) {
  const el = document.getElementById('add-memory-form');
  if (!el) return;
  if (el.style.display !== 'none') { el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.innerHTML = `
    <div style="display:flex;gap:8px;align-items:center;padding:8px 0">
      <input type="text" id="add-memory-input" placeholder="Nouveau souvenir…"
             style="flex:1;font-size:0.8rem" onkeydown="if(event.key==='Enter') submitAddMemory('${escAttr(userId)}')">
      <button onclick="submitAddMemory('${escAttr(userId)}')" class="btn btn-success" style="font-size:0.72rem;padding:4px 10px">Ajouter</button>
    </div>
  `;
  document.getElementById('add-memory-input')?.focus();
}

async function submitAddMemory(userId) {
  const input = document.getElementById('add-memory-input');
  const content = input?.value.trim();
  if (!content) { toast('Contenu requis', 'error'); return; }
  const r = await apiFetch(`/api/admin/memory/users/${encodeURIComponent(userId)}/memories`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
  if (r && r.ok) {
    toast('Souvenir ajouté', 'success');
    document.getElementById('add-memory-form').style.display = 'none';
    await loadUserDetail(_selectedMemUser, true);
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

function showInlineLink(userId) {
  const el = document.getElementById('inline-link-form');
  if (!el) return;
  if (el.style.display !== 'none') { el.style.display = 'none'; return; }
  const platform = userId.split(':')[0];
  const otherPlatform = platform === 'discord' ? 'twitch' : 'discord';
  el.style.display = 'block';
  el.innerHTML = `
    <div style="display:flex;gap:8px;align-items:center;padding:8px 0">
      <span style="font-size:0.75rem;color:var(--text-muted);white-space:nowrap">Lier à ${otherPlatform}:</span>
      <input type="text" id="inline-link-target" placeholder="${otherPlatform === 'discord' ? 'Discord ID' : 'Twitch username'}"
             style="flex:1;font-size:0.8rem" onkeydown="if(event.key==='Enter') submitInlineLink('${escAttr(userId)}')">
      <button onclick="submitInlineLink('${escAttr(userId)}')" class="btn btn-success" style="font-size:0.72rem;padding:4px 10px">Lier</button>
    </div>
  `;
}

async function submitInlineLink(userId) {
  const target = document.getElementById('inline-link-target')?.value.trim();
  if (!target) { toast('ID requis', 'error'); return; }
  const platform = userId.split(':')[0];
  const otherPlatform = platform === 'discord' ? 'twitch' : 'discord';
  const canonical = platform === 'discord' ? userId : `discord:${target}`;
  const alias = platform === 'discord' ? `twitch:${target}` : userId;
  const r = await apiFetch('/api/admin/links/manual', {
    method: 'POST',
    body: JSON.stringify({ canonical_id: canonical, alias_id: alias }),
  });
  if (r && r.ok) {
    toast('Liaison créée et fusionnée', 'success');
    await loadUserDetail(_selectedMemUser);
    refreshUserList();
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

async function deleteMemory(userId, memoryId) {
  const r = await apiFetch(
    `/api/admin/memory/users/${encodeURIComponent(userId)}/memories/${encodeURIComponent(memoryId)}`,
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    document.getElementById('mem-entry-' + memoryId)?.remove();
    toast('Souvenir supprimé', 'success');
  } else {
    toast('Erreur suppression', 'error');
  }
}

async function deleteAllMemories(userId) {
  const r = await apiFetch(
    '/api/admin/memory/users/' + encodeURIComponent(userId),
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    toast('Mémoire supprimée', 'success');
    // Recharger le detail (user existe encore mais sans mémoires)
    await loadUserDetail(userId, false);
    refreshUserList();
  } else {
    toast('Erreur suppression', 'error');
  }
}

let _memSearchTimer = null;
function onMemSearch(value) {
  clearTimeout(_memSearchTimer);
  _memSearchTimer = setTimeout(async () => {
    if (value.length >= 2) {
      await searchMemories(value);
    } else if (_selectedMemUser) {
      await loadUserDetail(_selectedMemUser);
    } else {
      document.getElementById('mem-detail').innerHTML =
        '<div class="mem-empty-state">Sélectionne un utilisateur pour voir ses souvenirs et liaisons.</div>';
    }
  }, 400);
}

async function searchMemories(q) {
  const r = await apiFetch('/api/admin/memory/search?q=' + encodeURIComponent(q));
  if (!r || !r.ok) return;
  const { results } = await r.json();
  const el = document.getElementById('mem-detail');
  if (!el) return;
  el.innerHTML = `
    <div style="padding:10px 16px;border-bottom:1px solid var(--glass-border)">
      <span style="font-size:0.7rem;color:var(--text-muted);letter-spacing:1px">${results.length} résultat(s) pour "${escHtml(q)}"</span>
    </div>
    <div style="padding:12px">
      ${results.length === 0
        ? '<div style="color:var(--text-muted);font-size:0.85rem">Aucun résultat.</div>'
        : results.map(res => `
          <div class="card" style="padding:12px 14px;margin-bottom:8px">
            <span style="font-size:0.62rem;color:var(--text-dim);display:block;margin-bottom:4px">${res.username ? escHtml(res.username) + ' · ' : ''}${escHtml(res.user_id)}</span>
            <span style="font-size:0.82rem;line-height:1.5">${escHtml(res.memory)}</span>
          </div>`).join('')
      }
    </div>
  `;
}

let _userFilterTimer = null;
function onUserFilter(value) {
  clearTimeout(_userFilterTimer);
  _userFilterTimer = setTimeout(() => loadMemoryUsers(value), 300);
}

// ── Global memory ─────────────────────────────────────────────────────────────

async function loadGlobalMemories() {
  const r = await apiFetch('/api/admin/memory/global');
  if (!r || !r.ok) return;
  const { memories } = await r.json();
  const countEl = document.getElementById('global-mem-count');
  if (countEl) countEl.textContent = memories.length;
  const listEl = document.getElementById('global-memory-list');
  if (!listEl) return;
  if (memories.length === 0) {
    listEl.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem;padding:4px 0">Aucune mémoire globale.</div>';
    return;
  }
  listEl.innerHTML = memories.map(m => {
    const dateStr = m.created_at || m.updated_at;
    const dateFmt = dateStr
      ? new Date(dateStr).toLocaleString('fr', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' })
      : '';
    return `
      <div class="mem-entry" id="mem-entry-${escAttr(m.id)}">
        <div class="mem-entry-content">
          <div class="mem-entry-meta">
            ${dateFmt ? '<span class="mem-entry-date">' + dateFmt + '</span>' : ''}
          </div>
          <span class="mem-entry-text" id="mem-text-${escAttr(m.id)}">${escHtml(m.memory)}</span>
        </div>
        <div class="mem-entry-actions">
          <button class="mem-entry-edit" onclick="startEditGlobalMemory('${escAttr(m.id)}')">&#9998;</button>
          <button class="mem-entry-delete" onclick="deleteGlobalMemory('${escAttr(m.id)}')">&#10005;</button>
        </div>
      </div>`;
  }).join('');
}

function toggleAddGlobalMemory() {
  const el = document.getElementById('add-global-memory-form');
  if (!el) return;
  if (el.style.display !== 'none') { el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.innerHTML = '<div style="display:flex;gap:8px;align-items:center;padding:8px 0">'
    + '<input type="text" id="add-global-memory-input" placeholder="Nouvelle connaissance globale…"'
    + ' style="flex:1;font-size:0.8rem" onkeydown="if(event.key===\'Enter\') submitAddGlobalMemory()">'
    + '<button onclick="submitAddGlobalMemory()" class="btn btn-success" style="font-size:0.72rem;padding:4px 10px">Ajouter</button>'
    + '</div>';
  document.getElementById('add-global-memory-input')?.focus();
}

async function submitAddGlobalMemory() {
  const input = document.getElementById('add-global-memory-input');
  const content = input?.value.trim();
  if (!content) { toast('Contenu requis', 'error'); return; }
  const r = await apiFetch('/api/admin/memory/global', {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
  if (r && r.ok) {
    toast('Mémoire globale ajoutée', 'success');
    document.getElementById('add-global-memory-form').style.display = 'none';
    await loadGlobalMemories();
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

function startEditGlobalMemory(memoryId) {
  const textEl = document.getElementById('mem-text-' + memoryId);
  if (!textEl) return;
  const current = textEl.textContent;
  const entry = document.getElementById('mem-entry-' + memoryId);
  if (!entry) return;
  const contentDiv = entry.querySelector('.mem-entry-content');
  const actionsDiv = entry.querySelector('.mem-entry-actions');
  if (actionsDiv) actionsDiv.style.display = 'none';
  const metaHtml = contentDiv.querySelector('.mem-entry-meta')?.outerHTML || '';
  contentDiv.innerHTML = metaHtml
    + '<div style="display:flex;gap:6px;align-items:center;margin-top:4px">'
    + '<input type="text" id="edit-global-memory-input-' + escAttr(memoryId) + '" value="' + escAttr(current) + '"'
    + ' style="flex:1;font-size:0.8rem" onkeydown="if(event.key===\'Enter\') submitEditGlobalMemory(\'' + escAttr(memoryId) + '\'); if(event.key===\'Escape\') loadGlobalMemories();">'
    + '<button onclick="submitEditGlobalMemory(\'' + escAttr(memoryId) + '\')" class="btn btn-success" style="font-size:0.68rem;padding:2px 8px">OK</button>'
    + '<button onclick="loadGlobalMemories()" class="btn" style="font-size:0.68rem;padding:2px 8px">\u2717</button>'
    + '</div>';
  document.getElementById('edit-global-memory-input-' + memoryId)?.focus();
}

async function submitEditGlobalMemory(memoryId) {
  const input = document.getElementById('edit-global-memory-input-' + memoryId);
  const content = input?.value.trim();
  if (!content) { toast('Contenu requis', 'error'); return; }
  const r = await apiFetch(
    '/api/admin/memory/global/' + encodeURIComponent(memoryId),
    { method: 'PUT', body: JSON.stringify({ content }) }
  );
  if (r && r.ok) {
    toast('Mémoire globale modifiée', 'success');
    await loadGlobalMemories();
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

async function deleteGlobalMemory(memoryId) {
  const r = await apiFetch(
    '/api/admin/memory/global/' + encodeURIComponent(memoryId),
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    document.getElementById('mem-entry-' + memoryId)?.remove();
    const countEl = document.getElementById('global-mem-count');
    if (countEl) {
      const current = parseInt(countEl.textContent) || 0;
      if (current > 0) countEl.textContent = current - 1;
    }
    toast('Mémoire globale supprimée', 'success');
  } else {
    toast('Erreur suppression', 'error');
  }
}

// ── Roadmap ──────────────────────────────────────────────────────────────────

async function loadRoadmap() {
  const r = await fetch('/api/public/roadmap');
  if (!r.ok) return;
  const data = await r.json();
  renderRoadmap(data);
}

function renderRoadmap(data) {
  const el = document.getElementById('roadmap-container');
  if (!el) return;

  const { sections, stats } = data;
  const pct = stats.total > 0 ? Math.round((stats.done / stats.total) * 100) : 0;

  let html = `
    <div class="card roadmap-progress">
      <span class="roadmap-progress-text">${stats.done} / ${stats.total} tâches</span>
      <div class="roadmap-progress-bar">
        <div class="roadmap-progress-fill" style="width:${pct}%"></div>
      </div>
      <span class="roadmap-progress-text">${pct}%</span>
    </div>
  `;

  for (const section of sections) {
    html += `<div class="roadmap-section">`;
    html += `<div class="roadmap-section-title">${escHtml(section.title)}</div>`;

    for (const item of section.items) {
      const cls = item.done ? 'done' : 'todo';
      const check = item.done ? '✓' : '○';
      const checkColor = item.done ? 'var(--c-online)' : 'var(--accent)';

      html += `<div class="card roadmap-item ${cls}">`;
      html += `<div class="roadmap-item-header">`;
      html += `<span class="roadmap-check" style="color:${checkColor}">${check}</span>`;
      html += `<span class="roadmap-item-title">${escHtml(item.title)}</span>`;
      html += `</div>`;

      if (item.description) {
        html += `<div class="roadmap-item-desc">${escHtml(item.description)}</div>`;
      }

      if (item.sub_items.length > 0) {
        html += `<div class="roadmap-sub-list">`;
        for (const sub of item.sub_items) {
          const subCls = sub.done ? 'done' : '';
          const subCheck = sub.done ? '✓' : '○';
          const subColor = sub.done ? 'var(--c-online)' : 'var(--text-dim)';
          html += `<div class="roadmap-sub-item ${subCls}">`;
          html += `<span class="roadmap-sub-check" style="color:${subColor}">${subCheck}</span>`;
          html += `<span>${escHtml(sub.title)}</span>`;
          html += `</div>`;
        }
        html += `</div>`;
      }

      html += `</div>`;
    }

    html += `</div>`;
  }

  el.innerHTML = html;
}

// ── Liaisons de comptes (fonctions utilitaires conservées) ─────────────────────

async function analyzeLinks() {
  const r = await apiFetch('/api/admin/links/analyze', { method: 'POST' });
  if (r && r.ok) toast('Analyse déclenchée', 'success');
  else toast('Erreur analyse', 'error');
}

async function acceptLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/accept`, { method: 'POST' });
  if (r && r.ok) {
    toast('Liaison acceptée — mémoires fusionnées', 'success');
    if (_selectedMemUser) await loadUserDetail(_selectedMemUser);
    refreshUserList();
    pollLinksBadge();
  } else {
    toast('Erreur', 'error');
  }
}

async function rejectLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/reject`, { method: 'POST' });
  if (r && r.ok) {
    toast('Liaison rejetée', 'success');
    if (_selectedMemUser) await loadUserDetail(_selectedMemUser);
    pollLinksBadge();
  } else {
    toast('Erreur', 'error');
  }
}

async function unlinkAccounts(id) {
  const r = await apiFetch(`/api/admin/links/${id}/unlink`, { method: 'POST' });
  if (r && r.ok) {
    toast('Comptes déliés', 'success');
    if (_selectedMemUser) await loadUserDetail(_selectedMemUser);
    refreshUserList();
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur déliaison', 'error');
  }
}

// ── Admin costs ────────────────────────────────────────────────────────────────

let currentCostRange = '7d';
let _costGraphMeta = null;
let _costRafPending = false;

async function loadCosts() {
  const days = { '7d': 7, '30d': 30, '90d': 90 }[currentCostRange] || 7;

  const [summaryR, dailyR, modelR, purposeR, usersR, alertR] = await Promise.all([
    apiFetch('/api/admin/costs/summary'),
    apiFetch(`/api/admin/costs/daily?days=${days}`),
    apiFetch(`/api/admin/costs/breakdown/model?days=${days}`),
    apiFetch(`/api/admin/costs/breakdown/purpose?days=${days}`),
    apiFetch(`/api/admin/costs/top-users?days=${days}&limit=10`),
    apiFetch('/api/admin/costs/alert'),
  ]);

  if (!summaryR || !summaryR.ok) return;

  const summary = await summaryR.json();
  const daily = await dailyR.json();
  const models = await modelR.json();
  const purposes = await purposeR.json();
  const users = await usersR.json();
  const alert = await alertR.json();

  // KPIs
  document.getElementById('cost-month-total').textContent = `$${summary.total.toFixed(2)}`;
  const changeEl = document.getElementById('cost-month-change');
  if (summary.pct_change !== 0) {
    const arrow = summary.pct_change < 0 ? '▼' : '▲';
    const color = summary.pct_change < 0 ? '#00E5A0' : '#FF4D4D';
    changeEl.innerHTML = `<span style="color:${color}">${arrow} ${Math.abs(summary.pct_change).toFixed(1)}% vs mois préc.</span>`;
  } else {
    changeEl.textContent = '';
  }

  const today = new Date().toISOString().slice(0, 10);
  const todayEntry = daily.current.find(d => d.date === today);
  document.getElementById('cost-today-total').textContent = `$${(todayEntry ? todayEntry.cost : 0).toFixed(2)}`;

  document.getElementById('cost-avg-msg').textContent = `$${summary.avg_per_msg.toFixed(4)}`;

  // Threshold KPI
  const threshEl = document.getElementById('cost-threshold');
  threshEl.textContent = `$${alert.threshold.toFixed(2)}`;
  const pctEl = document.getElementById('cost-threshold-pct');
  pctEl.textContent = `${alert.pct_used.toFixed(1)}% utilisé`;
  const threshColor = alert.status === 'critical' ? '#FF4D4D' : alert.status === 'warning' ? '#FFD700' : '#00E5A0';
  threshEl.style.color = threshColor;
  pctEl.style.color = threshColor;

  // Graph
  if (!daily.current || daily.current.length === 0) {
    showGraphEmpty('costCanvas', 'Aucune donnée de coûts pour cette période.');
  } else {
    drawCostGraph(daily.current, daily.previous);
  }

  // Breakdowns
  renderCostBreakdown('cost-by-model', models, 'model');
  renderCostBreakdown('cost-by-purpose', purposes, 'category');
  renderCostUsers(users);

  // Alert bar
  updateCostAlertBar(alert);
  updateCostBadge(alert);
}

function setCostRange(range) {
  currentCostRange = range;
  const titles = { '7d': '💸 7 DERNIERS JOURS', '30d': '💸 30 DERNIERS JOURS', '90d': '💸 90 DERNIERS JOURS' };
  const el = document.getElementById('cost-graph-title');
  if (el) el.textContent = titles[range];

  document.querySelectorAll('.cost-range-btn').forEach(btn => {
    const labels = { '7d': '7J', '30d': '30J', '90d': '90J' };
    btn.classList.toggle('active', btn.textContent === labels[range]);
  });

  loadCosts();
}

function drawCostGraph(current, previous) {
  const canvas = document.getElementById('costCanvas');
  if (!canvas || !current || current.length < 1) return;

  const W = canvas.offsetWidth || 800;
  const H = 165;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  ctx.fillStyle = '#11151c';
  ctx.fillRect(0, 0, W, H);

  const PAD = { top: 10, bottom: 40, left: 50, right: 10 };
  const gW = W - PAD.left - PAD.right;
  const gH = H - PAD.top - PAD.bottom;

  const allCosts = [...current.map(d => d.cost), ...(previous || []).map(d => d.cost)];
  const maxCost = Math.max(...allCosts, 0.01);

  const xStep = current.length > 1 ? gW / (current.length - 1) : gW;

  // Y grid
  ctx.lineWidth = 1;
  const ySteps = 4;
  for (let i = 0; i <= ySteps; i++) {
    const pct = i / ySteps;
    const y = PAD.top + (1 - pct) * gH;
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(W - PAD.right, y);
    ctx.stroke();

    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(`$${(maxCost * pct).toFixed(2)}`, PAD.left - 4, y + 3);
  }

  // X axis labels
  ctx.textAlign = 'center';
  const labelEvery = current.length > 14 ? Math.ceil(current.length / 7) : (current.length > 7 ? 2 : 1);
  current.forEach((d, i) => {
    if (i % labelEvery !== 0 && i !== current.length - 1) return;
    const x = PAD.left + i * xStep;
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '10px monospace';
    const parts = d.date.split('-');
    ctx.fillText(`${parts[2]}/${parts[1]}`, x, H - 26);
  });

  // Previous period (dashed)
  if (previous && previous.length > 0) {
    const prevXStep = previous.length > 1 ? gW / (previous.length - 1) : gW;
    ctx.beginPath();
    ctx.strokeStyle = '#4DA6FF';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.globalAlpha = 0.4;
    previous.forEach((d, i) => {
      const x = PAD.left + i * prevXStep;
      const y = PAD.top + (1 - d.cost / maxCost) * gH;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  // Current period (solid + area)
  ctx.beginPath();
  ctx.strokeStyle = '#FFD700';
  ctx.lineWidth = 2;
  let firstX = 0, lastX = 0;
  current.forEach((d, i) => {
    const x = PAD.left + i * xStep;
    const y = PAD.top + (1 - d.cost / maxCost) * gH;
    if (i === 0) { ctx.moveTo(x, y); firstX = x; }
    else ctx.lineTo(x, y);
    lastX = x;
  });
  ctx.stroke();

  // Area fill
  ctx.beginPath();
  current.forEach((d, i) => {
    const x = PAD.left + i * xStep;
    const y = PAD.top + (1 - d.cost / maxCost) * gH;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.lineTo(lastX, PAD.top + gH);
  ctx.lineTo(firstX, PAD.top + gH);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + gH);
  grad.addColorStop(0, 'rgba(255, 215, 0, 0.2)');
  grad.addColorStop(1, 'rgba(255, 215, 0, 0.01)');
  ctx.fillStyle = grad;
  ctx.fill();

  _costGraphMeta = { current, previous, PAD, gW, gH, W, H, xStep, maxCost };
}

function renderCostBreakdown(containerId, data, keyField) {
  const el = document.getElementById(containerId);
  if (!el || !data || data.length === 0) { if (el) el.innerHTML = '<span style="color:var(--text-dim)">—</span>'; return; }

  const maxTotal = data[0].total;
  el.innerHTML = data.map(d => {
    const pct = maxTotal > 0 ? (d.total / maxTotal * 100) : 0;
    const label = d[keyField] || 'Inconnu';
    return `<div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:3px">
        <span>${escHtml(label)}</span>
        <span style="color:#FFD700;font-family:var(--font-mono)">$${d.total.toFixed(2)}</span>
      </div>
      <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden">
        <div style="width:${pct}%;height:100%;background:linear-gradient(90deg,#FFD700,#ffe066);border-radius:2px;transition:width 0.4s ease"></div>
      </div>
    </div>`;
  }).join('');
}

function renderCostUsers(users) {
  const el = document.getElementById('cost-top-users');
  if (!el || !users || users.length === 0) { if (el) el.innerHTML = '<span style="color:var(--text-dim)">—</span>'; return; }

  const maxTotal = users[0].total;
  el.innerHTML = users.map(u => {
    const pct = maxTotal > 0 ? (u.total / maxTotal * 100) : 0;
    return `<div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:3px">
        <span>${escHtml(u.username)}</span>
        <span style="color:#FFD700;font-family:var(--font-mono)">$${u.total.toFixed(2)}</span>
      </div>
      <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden">
        <div style="width:${pct}%;height:100%;background:linear-gradient(90deg,#FFD700,#ffe066);border-radius:2px;transition:width 0.4s ease"></div>
      </div>
    </div>`;
  }).join('');
}

function updateCostAlertBar(alert) {
  const bar = document.getElementById('cost-alert-bar');
  if (!bar) return;

  if (alert.status === 'ok') { bar.style.display = 'none'; return; }

  bar.style.display = 'block';
  const color = alert.status === 'critical' ? '#FF4D4D' : '#FFD700';
  bar.style.borderColor = color;
  bar.style.background = alert.status === 'critical'
    ? 'rgba(255,77,77,0.08)' : 'rgba(255,215,0,0.08)';

  document.getElementById('cost-alert-text').innerHTML =
    `<span style="color:${color}">⚠ Seuil d'alerte : <strong>$${alert.threshold.toFixed(2)}</strong></span>`;
  document.getElementById('cost-alert-pct').textContent = `${alert.pct_used.toFixed(1)}% utilisé`;
}

function updateCostBadge(alert) {
  const badge = document.getElementById('costs-badge');
  if (!badge) return;
  badge.style.display = alert.status === 'critical' ? 'flex' : 'none';
}

async function pollCostsBadge() {
  if (!getToken()) return;
  try {
    const r = await apiFetch('/api/admin/costs/alert');
    if (!r || !r.ok) return;
    const alert = await r.json();
    updateCostBadge(alert);
  } catch (e) { /* ignore */ }
}

async function pollLinksBadge() {
  if (!getToken()) return;
  try {
    const r = await apiFetch('/api/admin/links?status=pending');
    if (!r || !r.ok) return;
    const { proposals } = await r.json();
    const badge = document.getElementById('links-badge');
    if (!badge) return;
    const count = proposals.length;
    badge.textContent = count;
    badge.style.display = count > 0 ? 'flex' : 'none';
  } catch (e) { /* ignore */ }
}

// ── Chat Auth ───────────────────────────────────────────────────

function getChatJwt() { return localStorage.getItem('chat_jwt'); }
function getChatRefresh() { return localStorage.getItem('chat_refresh'); }
function setChatTokens(jwt, refresh) {
  localStorage.setItem('chat_jwt', jwt);
  localStorage.setItem('chat_refresh', refresh);
}
function clearChatTokens() {
  localStorage.removeItem('chat_jwt');
  localStorage.removeItem('chat_refresh');
  _chatUser = null;
}

async function chatCheckAuth() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('chat_code')) {
    const code = params.get('chat_code');
    window.history.replaceState({}, '', '/');
    const resp = await fetch('/api/chat/auth/exchange?code=' + encodeURIComponent(code));
    if (resp.ok) {
      const data = await resp.json();
      setChatTokens(data.jwt, data.refresh_token);
    }
  }

  const jwt = getChatJwt();
  if (!jwt) return false;

  const r = await fetch('/api/chat/auth/me', { headers: { Authorization: 'Bearer ' + jwt } });
  if (r.ok) {
    _chatUser = await r.json();
    return true;
  }

  const refresh = getChatRefresh();
  if (!refresh) { clearChatTokens(); return false; }

  const rr = await fetch('/api/chat/auth/refresh', { headers: { Authorization: 'Bearer ' + refresh } });
  if (rr.ok) {
    const data = await rr.json();
    setChatTokens(data.jwt, data.refresh_token);
    return chatCheckAuth();
  }

  clearChatTokens();
  return false;
}

// ── Chat Tab Render ─────────────────────────────────────────────

async function renderChatTab() {
  const el = document.getElementById('tab-chat');
  if (!el) return;

  const authed = await chatCheckAuth();

  if (!authed) {
    el.innerHTML = `
      <div class="chat-login-prompt">
        <div class="login-title">Avant de te connecter...</div>
        <div class="login-subtitle">Wally a besoin de savoir qui tu es pour se souvenir de toi.</div>

        <div class="login-why-block">
          <div class="login-why-icon">🔗</div>
          <div class="login-why-title">Pourquoi Discord ?</div>
          <div class="login-why-text">
            Wally utilise ton compte Discord comme identifiant pour rattacher tes souvenirs à ton profil.
            C'est ce qui lui permet de te reconnaître et de se souvenir de tes échanges passés,
            que ce soit ici ou sur le serveur Discord.
          </div>
        </div>

        <div class="login-cards">
          <div class="login-card" style="--card-accent: var(--c-curiosity)">
            <div class="login-card-icon" aria-hidden="true">🧠</div>
            <div class="login-card-title">Ta mémoire personnelle</div>
            <div class="login-card-text">Au fil de vos échanges, Wally retient tes goûts, ton humour, tes sujets favoris. Chaque conversation devient plus naturelle.</div>
          </div>
          <div class="login-card" style="--card-accent: var(--c-joy)">
            <div class="login-card-icon" aria-hidden="true">🔒</div>
            <div class="login-card-title">Données minimales</div>
            <div class="login-card-text">Seuls ton pseudo, ton ID et ton avatar Discord sont récupérés. Aucun accès à tes messages, serveurs ou liste d'amis.</div>
          </div>
          <div class="login-card" style="--card-accent: var(--c-sadness)">
            <div class="login-card-icon" aria-hidden="true">📦</div>
            <div class="login-card-title">Hébergement local</div>
            <div class="login-card-text">Tout est stocké sur le serveur de Wally. Rien ne transite par des services tiers. Tes données restent chez moi.</div>
          </div>
          <div class="login-card" style="--card-accent: var(--c-anger)">
            <div class="login-card-icon" aria-hidden="true">🗑️</div>
            <div class="login-card-title">Droit de regard</div>
            <div class="login-card-text">Tu peux consulter tes souvenirs à tout moment. Pour une suppression, fais-en la demande à KingsRequin sur Discord.</div>
          </div>
        </div>

        <a href="/api/chat/auth/login" class="chat-login-btn">
          <svg width="20" height="15" viewBox="0 0 71 55" fill="white"><path d="M60.1 4.9A58.5 58.5 0 0 0 45.4.2a.2.2 0 0 0-.2.1 40.8 40.8 0 0 0-1.8 3.7 54 54 0 0 0-16.2 0A37.4 37.4 0 0 0 25.4.3a.2.2 0 0 0-.2-.1A58.4 58.4 0 0 0 10.5 4.9a.2.2 0 0 0-.1.1C1.5 18.7-.9 32.2.3 45.5v.2a58.9 58.9 0 0 0 17.8 9a.2.2 0 0 0 .3-.1 42.1 42.1 0 0 0 3.6-5.9.2.2 0 0 0-.1-.3 38.8 38.8 0 0 1-5.5-2.6.2.2 0 0 1 0-.4l1.1-.9a.2.2 0 0 1 .2 0 42 42 0 0 0 35.8 0 .2.2 0 0 1 .2 0l1.1.9a.2.2 0 0 1 0 .3 36.4 36.4 0 0 1-5.5 2.7.2.2 0 0 0-.1.3 47.3 47.3 0 0 0 3.6 5.8.2.2 0 0 0 .3.1A58.7 58.7 0 0 0 70.5 45.7v-.2c1.4-15-2.3-28.4-9.8-40.1a.2.2 0 0 0-.1-.1zM23.7 37.3c-3.5 0-6.3-3.2-6.3-7.1s2.8-7.1 6.3-7.1 6.4 3.2 6.3 7.1c0 3.9-2.8 7.1-6.3 7.1zm23.2 0c-3.5 0-6.3-3.2-6.3-7.1s2.8-7.1 6.3-7.1 6.4 3.2 6.3 7.1c0 3.9-2.8 7.1-6.3 7.1z"/></svg>
          Se connecter avec Discord
        </a>
      </div>`;
    return;
  }

  el.innerHTML = `
    <div class="chat-container">
      <div class="chat-hero">
        <div class="chat-hero-side chat-hero-emotions" id="chat-hero-emotions"></div>
        <div class="chat-hero-center">
          <img class="chat-hero-avatar" id="chat-wally-avatar" src="/static/avatar/emotions/neutral/idle.gif" alt="Wally">
          <div class="chat-hero-name">Wally</div>
          <div class="chat-hero-status" id="chat-avatar-status">neutre</div>
          <div class="chat-hero-user">
            <strong>${escHtml(_chatUser.username)}</strong>
            <button onclick="chatLogout()" style="font-size:0.65rem;padding:2px 8px" class="btn">Déconnexion</button>
          </div>
        </div>
        <div class="chat-hero-side chat-hero-memories" id="chat-hero-memories">
          <div class="chat-hero-side-title">
            Ce que Wally sait de toi
            <button class="chat-mem-expand-btn" onclick="chatOpenMemoryPanel()" title="Voir tout">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>
            </button>
          </div>
          <div class="chat-hero-memories-list" id="chat-memories-list">
            <span style="color:rgba(255,255,255,0.3);font-size:0.7rem">Chargement...</span>
          </div>
        </div>
        <button class="chat-mem-mobile-btn" onclick="chatOpenMemoryPanel()" title="Ce que Wally sait de toi">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z"/><path d="M10 21h4"/></svg>
        </button>
      </div>
      <div class="chat-session-bar">
        <span class="chat-session-label" id="chat-session-label">Aujourd'hui</span>
        <button class="chat-session-btn" onclick="chatToggleSessionPanel()" title="Sessions précédentes">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
        </button>
      </div>
      <div class="chat-session-panel" id="chat-session-panel" style="display:none">
        <div class="chat-session-panel-title">Sessions précédentes</div>
        <div class="chat-session-list" id="chat-session-list">
          <span style="color:rgba(255,255,255,0.3);font-size:0.75rem">Chargement...</span>
        </div>
      </div>
      <div class="chat-messages" id="chat-messages"></div>
      <div class="chat-typing" id="chat-typing">Wally réfléchit...</div>
      <div class="chat-cooldown-msg" id="chat-cooldown"></div>
      <div class="chat-input-bar">
        <input type="text" id="chat-input" placeholder="Envoyer un message..." maxlength="2000"
               onkeydown="if(event.key==='Enter') chatSend()">
        <button class="btn btn-success" onclick="chatSend()">Envoyer</button>
      </div>
    </div>`;

  // Memory panel overlay (inserted once into the page)
  if (!document.getElementById('chat-memory-panel')) {
    document.body.insertAdjacentHTML('beforeend', `
      <div class="chat-mem-overlay" id="chat-memory-panel" onclick="chatCloseMemoryPanel(event)">
        <div class="chat-mem-panel">
          <div class="chat-mem-panel-header">
            <span class="chat-mem-panel-title">Ce que Wally sait de toi</span>
            <button class="chat-mem-panel-close" onclick="chatCloseMemoryPanel()">&times;</button>
          </div>
          <div class="chat-mem-panel-body" id="chat-mem-panel-body">
            <span style="color:rgba(255,255,255,0.3)">Chargement...</span>
          </div>
        </div>
      </div>`);
  }

  chatBuildHeroEmotions();
  chatConnectWs();
  chatStartAvatarUpdates();
  chatLoadMyMemories();
}

function chatLogout() {
  clearChatTokens();
  if (_chatWs) { _chatWs.close(); _chatWs = null; }
  renderChatTab();
}

// ── Chat WebSocket ──────────────────────────────────────────────

function chatConnectWs() {
  if (_chatWs) { _chatWs.close(); _chatWs = null; }
  const jwt = getChatJwt();
  if (!jwt) return;

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  _chatWs = new WebSocket(`${proto}//${location.host}/ws/chat?token=${jwt}`);

  _chatWs.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'history') {
      const el = document.getElementById('chat-messages');
      if (el) el.innerHTML = '';
      (data.messages || []).forEach(m => chatAppendMessage(m));
      chatScrollBottom();
    } else if (data.type === 'message') {
      chatAppendMessage(data);
      chatScrollBottom();
      chatHideTyping();
    } else if (data.type === 'typing') {
      chatShowTyping();
    } else if (data.type === 'system') {
      chatAppendSystem(data.content || '');
      chatScrollBottom();
    } else if (data.type === 'cooldown') {
      const el = document.getElementById('chat-cooldown');
      if (el) {
        el.textContent = `Cooldown: attends ${data.remaining_seconds}s`;
        setTimeout(() => { el.textContent = ''; }, 3000);
      }
    }
  };

  _chatWs.onclose = () => {
    _chatWs = null;
    setTimeout(() => { if (getChatJwt()) chatConnectWs(); }, 3000);
  };
}

function chatAppendMessage(msg) {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  const isWally = msg.is_wally;
  const avatarSrc = isWally
    ? (document.getElementById('chat-wally-avatar')?.src || '/static/avatar/emotions/neutral/idle.gif')
    : (msg.avatar_url || '');
  const avatarHtml = avatarSrc
    ? `<img class="chat-msg-avatar" src="${escAttr(avatarSrc)}" alt="">`
    : `<div class="chat-msg-avatar" style="background:var(--accent)"></div>`;

  const time = msg.created_at
    ? new Date(msg.created_at * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' })
    : '';

  const div = document.createElement('div');
  div.className = `chat-msg ${isWally ? 'wally' : 'user'}`;
  div.innerHTML = `
    ${avatarHtml}
    <div class="chat-msg-bubble">
      <div class="chat-msg-username ${isWally ? 'wally' : ''}">${escHtml(msg.username)} <span class="chat-msg-time">${time}</span></div>
      <div class="chat-msg-content">${escHtml(msg.content)}</div>
    </div>`;
  el.appendChild(div);
}

function chatAppendSystem(text) {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  const div = document.createElement('div');
  div.className = 'chat-msg system';
  const inner = document.createElement('div');
  inner.className = 'chat-msg-system';
  inner.textContent = text;
  div.appendChild(inner);
  el.appendChild(div);
}

function chatScrollBottom() {
  const el = document.getElementById('chat-messages');
  if (el) el.scrollTop = el.scrollHeight;
}

function chatShowTyping() {
  const el = document.getElementById('chat-typing');
  if (el) el.classList.add('visible');
  clearTimeout(_chatTypingTimer);
  _chatTypingTimer = setTimeout(chatHideTyping, 30000);
}

function chatHideTyping() {
  const el = document.getElementById('chat-typing');
  if (el) el.classList.remove('visible');
}

function chatSend() {
  const input = document.getElementById('chat-input');
  const content = input?.value.trim();
  if (!content || !_chatWs || _chatWs.readyState !== WebSocket.OPEN) return;
  _chatWs.send(JSON.stringify({ type: 'message', content }));
  input.value = '';
}

// ── Mobile virtual keyboard handling ────────────────────────────
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', () => {
    const chatInput = document.getElementById('chat-input');
    if (chatInput && document.activeElement === chatInput) {
      requestAnimationFrame(() => chatInput.scrollIntoView({ block: 'nearest' }));
    }
  });
}

// ── Chat Hero: Emotions panel ───────────────────────────────────

function chatBuildHeroEmotions() {
  const el = document.getElementById('chat-hero-emotions');
  if (!el) return;
  let html = '<div class="chat-hero-side-title">Humeur</div>';
  for (const e of EMOTIONS) {
    html += `
      <div class="chat-hero-gauge">
        <span class="chat-hero-gauge-icon" style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]}</span>
        <div class="chat-hero-gauge-track">
          <div class="chat-hero-gauge-fill ${e}" id="chat-fill-${e}"></div>
        </div>
      </div>`;
  }
  el.innerHTML = html;
  chatUpdateHeroEmotions();
}

function chatUpdateHeroEmotions() {
  if (typeof currentEmotions === 'undefined' || !currentEmotions) return;
  for (const e of EMOTIONS) {
    const fill = document.getElementById(`chat-fill-${e}`);
    if (fill) fill.style.width = `${((currentEmotions[e] ?? 0) * 100).toFixed(1)}%`;
  }
}

// ── Chat Sessions ───────────────────────────────────────────────

let _chatViewingDate = null; // null = today (live), string = archived day

async function chatToggleSessionPanel() {
  const panel = document.getElementById('chat-session-panel');
  if (!panel) return;
  if (panel.style.display === 'none') {
    panel.style.display = 'block';
    await chatLoadSessions();
  } else {
    panel.style.display = 'none';
  }
}

async function chatLoadSessions() {
  const list = document.getElementById('chat-session-list');
  if (!list) return;
  const jwt = getChatJwt();
  if (!jwt) return;
  try {
    const r = await fetch('/api/chat/sessions', {
      headers: { 'Authorization': `Bearer ${jwt}` },
    });
    const data = await r.json();
    const dates = data.dates || [];
    const today = new Date().toISOString().slice(0, 10);
    if (dates.length === 0) {
      list.innerHTML = '<div style="color:rgba(255,255,255,0.3);font-size:0.75rem;padding:8px">Aucune session</div>';
      return;
    }
    list.innerHTML = dates.map(d => {
      const isToday = d === today;
      const isActive = isToday ? !_chatViewingDate : _chatViewingDate === d;
      const label = isToday ? "Aujourd'hui" : _formatSessionDate(d);
      return `<button class="chat-session-item${isActive ? ' active' : ''}" onclick="chatLoadDay('${d}')">${label}</button>`;
    }).join('');
  } catch (e) {
    list.innerHTML = '<div style="color:var(--c-anger);font-size:0.75rem;padding:8px">Erreur</div>';
  }
}

function _formatSessionDate(dateStr) {
  const d = new Date(dateStr + 'T12:00:00');
  const days = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];
  const months = ['jan', 'fév', 'mar', 'avr', 'mai', 'jun', 'jul', 'aoû', 'sep', 'oct', 'nov', 'déc'];
  return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`;
}

async function chatLoadDay(dateStr) {
  const today = new Date().toISOString().slice(0, 10);
  const label = document.getElementById('chat-session-label');
  const el = document.getElementById('chat-messages');
  const inputBar = document.querySelector('.chat-input-bar');

  if (dateStr === today) {
    // Back to live mode
    _chatViewingDate = null;
    if (label) label.textContent = "Aujourd'hui";
    if (inputBar) inputBar.style.display = '';
    // Reconnect WS to get today's messages
    chatConnectWs();
  } else {
    _chatViewingDate = dateStr;
    if (label) label.textContent = _formatSessionDate(dateStr);
    if (inputBar) inputBar.style.display = 'none'; // hide input for archived sessions
    // Load archived day via REST
    const jwt = getChatJwt();
    if (!jwt || !el) return;
    try {
      const r = await fetch(`/api/chat/history/${dateStr}`, {
        headers: { 'Authorization': `Bearer ${jwt}` },
      });
      const data = await r.json();
      el.innerHTML = '';
      (data.messages || []).forEach(m => chatAppendMessage(m));
      chatScrollBottom();
    } catch (e) {
      if (el) el.innerHTML = '<div style="text-align:center;color:rgba(255,255,255,0.3);padding:40px">Erreur de chargement</div>';
    }
  }
  // Close panel & refresh list
  const panel = document.getElementById('chat-session-panel');
  if (panel) panel.style.display = 'none';
}

// ── Chat Hero: Memories panel ───────────────────────────────────

async function chatLoadMyMemories() {
  const el = document.getElementById('chat-memories-list');
  if (!el) return;

  const jwt = getChatJwt();
  if (!jwt) { el.innerHTML = '<span style="color:rgba(255,255,255,0.3);font-size:0.7rem">Non connecté</span>'; return; }

  try {
    const r = await fetch('/api/chat/my-memories', {
      headers: { 'Authorization': `Bearer ${jwt}` },
    });
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    const memories = data.memories || [];
    _chatMemoriesCache = memories;

    if (memories.length === 0) {
      el.innerHTML = '<span style="color:rgba(255,255,255,0.3);font-size:0.7rem">Aucun souvenir</span>';
    } else {
      el.innerHTML = memories.map(m =>
        `<div class="chat-hero-memory-item">${escHtml(m)}</div>`
      ).join('');
    }

    // Also update the expanded panel if it exists
    const panelBody = document.getElementById('chat-mem-panel-body');
    if (panelBody) _renderMemoryPanelBody(panelBody, memories);
  } catch {
    el.innerHTML = '<span style="color:rgba(255,255,255,0.3);font-size:0.7rem">Indisponible</span>';
  }
}

// ── Chat Memory Panel ───────────────────────────────────────────

let _chatMemoriesCache = null;

function chatOpenMemoryPanel(evt) {
  const overlay = document.getElementById('chat-memory-panel');
  if (!overlay) return;
  overlay.classList.add('open');

  const body = document.getElementById('chat-mem-panel-body');
  if (body && _chatMemoriesCache !== null) {
    _renderMemoryPanelBody(body, _chatMemoriesCache);
  }
}

function chatCloseMemoryPanel(evt) {
  if (evt && evt.target !== evt.currentTarget) return;
  const overlay = document.getElementById('chat-memory-panel');
  if (overlay) overlay.classList.remove('open');
}

function _renderMemoryPanelBody(el, memories) {
  if (memories.length === 0) {
    el.innerHTML = '<div style="color:rgba(255,255,255,0.35);text-align:center;padding:32px 0">Wally ne sait encore rien de toi. Discute avec lui !</div>';
    return;
  }
  el.innerHTML = memories.map(m =>
    `<div class="chat-mem-panel-item">${escHtml(m)}</div>`
  ).join('');
}

// ── Chat Avatar ─────────────────────────────────────────────────

function chatStartAvatarUpdates() {
  setInterval(chatUpdateAvatar, 5000);
  chatUpdateAvatar();
}

function chatUpdateAvatar() {
  if (typeof currentEmotions === 'undefined' || !currentEmotions) return;
  chatUpdateHeroEmotions();

  const emotions = currentEmotions;
  let dominant = 'neutral';
  let maxVal = 0.2;

  for (const [emotion, value] of Object.entries(emotions)) {
    if (value > maxVal) {
      dominant = emotion;
      maxVal = value;
    }
  }

  let tier = 'idle';
  if (dominant !== 'neutral') {
    if (maxVal >= 0.7) tier = 'high';
    else if (maxVal >= 0.4) tier = 'mid';
    else tier = 'low';
  }

  const basePath = dominant === 'neutral'
    ? '/static/avatar/emotions/neutral/idle'
    : `/static/avatar/emotions/${dominant}/${tier}`;

  const img = document.getElementById('chat-wally-avatar');
  if (!img) return;

  const gifUrl = basePath + '.gif';
  const pngUrl = basePath + '.png';

  const testImg = new Image();
  testImg.onload = () => { img.src = gifUrl; };
  testImg.onerror = () => { img.src = pngUrl; };
  testImg.src = gifUrl;

  const statusEl = document.getElementById('chat-avatar-status');
  if (statusEl) {
    const labels = { neutral: 'neutre', joy: 'joyeux', anger: 'en colère', sadness: 'triste', curiosity: 'curieux', boredom: 'ennuyé' };
    statusEl.textContent = labels[dominant] || dominant;
  }
}

// ── Journal détaillé ────────────────────────────────────────────────────────

function renderJournalDetailTab() {
  const el = document.getElementById('tab-journal-detail');
  if (!el || el.querySelector('.jd-container')) return;

  el.innerHTML = `
    <div class="jd-container">
      <div class="jd-header">
        <h2 class="jd-title">Comment fonctionne Wally ?</h2>
        <p class="jd-subtitle">Découvre ce qui se passe dans la tête de Wally, étape par étape. Clique sur « Aller plus loin » pour voir le code source et les détails techniques.</p>
      </div>

      <!-- Section 1: Cycle de vie d'un message -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-curiosity)">1</span>
          <h3>Cycle de vie d'un message</h3>
        </div>
        <div class="jd-body">
          <p>Quand quelqu'un envoie un message sur Discord ou Twitch, Wally le reçoit et lance une série d'étapes en quelques secondes :</p>
          <p>D'abord, il <strong>détecte la langue</strong> du message (français, anglais…) pour répondre dans la bonne langue. Ensuite, il <strong>analyse le ton émotionnel</strong> grâce à NRCLex, un dictionnaire qui associe chaque mot à des émotions (joie, colère, tristesse…). En parallèle, il <strong>consulte sa mémoire</strong> : que sait-il sur l'auteur du message ? Quels sont ses goûts, ses sujets favoris ?</p>
          <p>Avec toutes ces informations, il <strong>construit un prompt personnalisé</strong> : sa personnalité (qui il est, comment il parle), son humeur actuelle, les souvenirs pertinents, et les derniers messages de la conversation. Ce prompt est envoyé à <strong>OpenAI</strong>, qui génère la réponse.</p>
          <p>En arrière-plan, Wally met à jour le <strong>score de confiance</strong> de l'utilisateur et enregistre le <strong>coût de l'appel API</strong>.</p>

          <div class="jd-pipeline">
            <span class="jd-pipe-step" style="background: #5865F2">📨 Message</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">🌍 Langue</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">🧠 Émotion</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">💾 Mémoire</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">✍️ Prompt</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">🤖 OpenAI</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step" style="background: var(--c-curiosity)">💬 Réponse</span>
          </div>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — le pipeline en code</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/discord/handlers.py — handle_message()</div>
              <pre><code>async def handle_message(self, message):
    # 1. Détection de la langue (asyncio.to_thread pour ne pas bloquer)
    lang = await asyncio.to_thread(detect_language, message.content)

    # 2. Analyse émotionnelle via NRCLex (aussi en thread séparé)
    trust = await self.db.get_trust_score(platform, user_id)
    emotion_result = await self.emotion.process_message(
        text, trust_score=trust, context_messages=context
    )

    # 3. Recherche en mémoire (Qdrant — similarité vectorielle)
    memories = await self.memory.search(user_id, message.content)

    # 4. Construction du prompt (persona + émotion + mémoire + contexte)
    prompt = self.prompt_builder.build(
        emotion_state=self.emotion.get_state(),
        memories=memories,
        context=recent_messages
    )

    # 5. Appel OpenAI → réponse
    response = await self.openai.complete(prompt)

    # 6. Post-traitement : trust score, coût, extraction de faits
    await self._post_process(message, response)</code></pre>
              <p class="jd-tech-note">Le pipeline est entièrement <strong>asynchrone</strong>. Les opérations CPU-bound (NRCLex, détection de langue) tournent dans <code>asyncio.to_thread()</code> pour ne pas bloquer la boucle événementielle — ce qui permet à Wally de continuer à écouter les autres messages pendant qu'il traite celui-ci.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 2: Système émotionnel -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-joy); color: #000">2</span>
          <h3>Système émotionnel</h3>
        </div>
        <div class="jd-body">
          <p>Wally ressent <strong>5 émotions en permanence</strong>, chacune mesurée entre 0.0 (absente) et 1.0 (maximale) :</p>

          <div class="jd-gauges">
            <div class="jd-gauge"><span class="jd-gauge-label">Colère</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:15%;background:var(--c-anger)"></div></div></div>
            <div class="jd-gauge"><span class="jd-gauge-label">Joie</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:65%;background:var(--c-joy)"></div></div></div>
            <div class="jd-gauge"><span class="jd-gauge-label">Tristesse</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:10%;background:var(--c-sadness)"></div></div></div>
            <div class="jd-gauge"><span class="jd-gauge-label">Curiosité</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:45%;background:var(--c-curiosity)"></div></div></div>
            <div class="jd-gauge"><span class="jd-gauge-label">Ennui</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:30%;background:var(--c-boredom)"></div></div></div>
          </div>

          <p>Chaque message fait bouger ces émotions. Un compliment booste la <strong>joie</strong>, une insulte monte la <strong>colère</strong>, une question intéressante pique la <strong>curiosité</strong>. L'impact dépend aussi du <strong>score de confiance</strong> de l'auteur : un inconnu (trust bas) provoque des réactions plus vives qu'un habitué.</p>
          <p>Avec le temps, chaque émotion <strong>retombe naturellement vers zéro</strong>, comme un humain qui se calme. La vitesse de retombée est différente pour chaque émotion — la colère s'apaise vite, la tristesse persiste plus longtemps.</p>
          <p>Si un utilisateur déclenche la colère au-delà d'un seuil trop souvent, Wally le <strong>mute temporairement</strong> : il ne répond plus avec du texte, seulement avec des réactions emoji (💩 ⛔ 😤).</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — décroissance exponentielle et formules</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/emotion.py — _apply_decay()</div>
              <pre><code># Formule de décroissance : E(t) = E₀ × e^(−λ × Δt)
# Chaque émotion a son propre λ (lambda) configurable dans config.yaml

def _apply_decay(self):
    now = time.time()
    dt = now - self._last_decay
    for emotion in EMOTIONS:
        lam = self._lambdas[emotion]
        self._state[emotion] *= math.exp(-lam * dt)
        if self._state[emotion] < DECAY_FLOOR:
            self._state[emotion] = 0.0
    self._last_decay = now</code></pre>
              <p class="jd-tech-note"><strong>Décroissance exponentielle</strong> : un λ élevé = retombée rapide. La colère a typiquement λ=0.003 (retombe en ~10min) tandis que la tristesse a λ=0.001 (persiste ~30min). Un task en arrière-plan applique cette décroissance toutes les 60 secondes.</p>
              <p class="jd-tech-note"><strong>Trust score et colère</strong> : quand le trust score est bas (&lt;0.3), les deltas de colère sont amplifiés. Un nouvel utilisateur (trust=0.0) provoquera une réaction de colère plus forte qu'un habitué (trust=0.8). C'est un mécanisme de protection naturel.</p>
              <p class="jd-tech-note"><strong>Timeout</strong> : si la colère dépasse le seuil configuré N fois pour un même utilisateur, il est mute pendant X minutes (configurable). Pendant ce mute, Wally réagit uniquement avec des emoji.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 3: Mémoire -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-sadness)">3</span>
          <h3>Mémoire</h3>
        </div>
        <div class="jd-body">
          <p>Wally a <strong>trois types de mémoire</strong> :</p>
          <p><strong>La mémoire courte</strong> — les derniers messages de la conversation en cours. Wally garde en tête les N derniers échanges (configurable) pour garder le fil. Quand cette fenêtre devient trop grande, il la résume automatiquement via un modèle secondaire pour économiser des tokens.</p>
          <p><strong>La mémoire longue</strong> — des faits extraits automatiquement au fil du temps et stockés dans une base vectorielle (Qdrant). « Aime les crevettes », « fan d'Apex Legends », « déteste le lundi matin », « a un chat qui s'appelle Pixel ». Ces faits sont extraits par le <strong>FactExtractor</strong>, qui analyse les conversations par batch après une période d'inactivité.</p>
          <p>Quand Wally reçoit un message, il cherche dans sa mémoire longue les souvenirs les plus <strong>pertinents par similarité sémantique</strong> — pas juste par mots-clés, mais par sens. Si tu parles de « mon félin », il retrouvera le souvenir de Pixel même si le mot « chat » n'apparaît pas.</p>
          <p>Par défaut, chaque plateforme a sa propre mémoire (namespace <code>discord:user_id</code> vs <code>twitch:username</code>). Mais un administrateur peut <strong>lier manuellement</strong> les profils Discord et Twitch d'un même utilisateur pour que Wally partage ses souvenirs entre les deux.</p>
          <p><strong>La mémoire globale</strong> — des connaissances partagées par toute la communauté : liens importants, événements du serveur, ressources communes. Contrairement à la mémoire individuelle, ces faits sont consultés <strong>pour chaque requête</strong>, peu importe qui pose la question. Les administrateurs peuvent gérer ces connaissances via l'onglet « Mémoire » du dashboard, et le FactExtractor les détecte aussi automatiquement dans les conversations.</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — mem0, Qdrant, trust score</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/memory.py — search() + FactExtractor</div>
              <pre><code># Recherche par similarité vectorielle dans Qdrant
async def search(self, user_id, query, limit=5):
    results = await self.client.search(
        collection="memories",
        query=query,
        filter={"user_id": user_id},
        limit=limit
    )
    return [r.payload for r in results]

# FactExtractor : extraction de faits par batch
# Après 20min d'inactivité dans un canal, le FactExtractor
# analyse la conversation et extrait les faits durables :
# "### pseudo\n- fait 1\n- fait 2\n..."
# Chaque fait est stocké via memory.add() dans Qdrant.</code></pre>
              <p class="jd-tech-note"><strong>mem0</strong> est la couche d'abstraction pour la mémoire longue. Elle gère l'embedding (conversion texte → vecteur), le stockage dans <strong>Qdrant</strong> (base vectorielle auto-hébergée), et la recherche par similarité.</p>
              <p class="jd-tech-note"><strong>Trust score</strong> : chaque utilisateur a un score de confiance (0.0 → 1.0) qui évolue avec le temps. +0.01 par interaction positive, -0.05 pour les comportements toxiques. Le score part à 0.0 — la confiance se mérite.</p>
              <p class="jd-tech-note"><strong>Sliding window</strong> : la mémoire courte garde les N derniers messages. Quand le nombre de tokens dépasse un seuil, les messages les plus anciens sont résumés par un modèle secondaire et remplacés par un bloc résumé.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 4: Personnalité -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-anger)">4</span>
          <h3>Personnalité</h3>
        </div>
        <div class="jd-body">
          <p>La personnalité de Wally est définie dans <strong>4 fichiers texte</strong> (Markdown), chacun avec un rôle précis :</p>
          <p><strong>SOUL.md</strong> — Son âme. Qui il est fondamentalement : un pote loyal, un peu cynique, avec un humour pince-sans-rire. Ce fichier définit les valeurs profondes qui ne changent jamais, peu importe l'humeur.</p>
          <p><strong>IDENTITY.md</strong> — Son histoire. D'où il vient, ce qu'il aime (la tech, les jeux, la musique), ses opinions, ses running jokes. C'est ce qui le rend unique et cohérent dans le temps.</p>
          <p><strong>VOICE.md</strong> — Comment il parle. Son registre de langue, ses tics verbaux, la longueur de ses réponses, quand il utilise des emoji et quand il n'en met pas. Le style, pas le fond.</p>
          <p><strong>EXEMPLES.md</strong> — Des exemples concrets de réponses « à la Wally » pour calibrer le ton. Le modèle s'en inspire sans les copier.</p>
          <p>À chaque message, ces 4 fichiers sont <strong>assemblés dans cet ordre</strong> et injectés dans le prompt système. L'émotion dominante du moment ajoute une <strong>directive comportementale</strong> tirée de <strong>EMOTIONS.md</strong> — si Wally est joyeux, il est plus bavard et taquin ; s'il est en colère, ses réponses sont courtes et impatientes.</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — PersonaService et prompt building</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/persona.py + bot/core/prompts.py</div>
              <pre><code># PersonaService charge les 4 fichiers persona au démarrage
# Ordre canonique : SOUL → IDENTITY → VOICE → EXEMPLES
persona_block = PersonaService.load()
# → Un seul bloc texte injecté dans le system prompt

# EMOTIONS.md est parsé séparément en {emotion: directive}
# Sections délimitées par "## emotion_name"
# Ex: "## anger" → "Tes réponses sont courtes et impatientes."

# PromptBuilder assemble le prompt final :
# [persona_block] + [emotion_directive] + [memories] + [context]
prompt = PromptBuilder.build(
    emotion_state=current_emotions,
    memories=relevant_memories,
    context=recent_messages
)</code></pre>
              <p class="jd-tech-note">Les fichiers persona sont chargés au démarrage et mis en cache. La commande <code>/wally reload-persona</code> permet de les recharger à chaud sans redémarrer le bot.</p>
              <p class="jd-tech-note"><strong>Directive émotionnelle</strong> : le prompt ne dit jamais « tu es en colère » — il dit « tes réponses sont courtes et impatientes ». C'est un choix de design : on décrit le comportement, pas l'état interne. Le LLM interprète mieux des instructions concrètes.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 5: Journal quotidien -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-curiosity)">5</span>
          <h3>Journal quotidien</h3>
        </div>
        <div class="jd-body">
          <p>Chaque soir, Wally <strong>écrit son journal de la journée</strong>. C'est un texte rédigé avec ses propres mots, comme un vrai journal intime.</p>
          <p>Il commence par compiler <strong>toutes les conversations de la journée</strong> depuis sa base de données. Il identifie les <strong>moments forts</strong> : les pics d'émotion (quand il a ri, quand il s'est énervé, quand il était curieux) et qui les a déclenchés.</p>
          <p>Il note les <strong>statistiques</strong> : combien de messages, combien de participants uniques, les top 5 des plus actifs, les heures de pointe, la répartition Discord vs Twitch.</p>
          <p>Puis il rédige un <strong>résumé narratif</strong> de sa journée. Pour les grosses journées (beaucoup de messages), il utilise une technique de résumé multi-passes : il découpe en blocs de 30 messages, résume chaque bloc, puis synthétise les résumés en un texte final.</p>
          <p>Il génère aussi un <strong>graphe d'émotions</strong> (image PNG) montrant l'évolution de ses 5 émotions au cours de la journée, et <strong>forme des opinions</strong> sur les sujets récurrents qu'il a rencontrés (fire-and-forget, en arrière-plan).</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — DailyJournal et sources de données</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/journal.py — DailyJournal</div>
              <pre><code># Sources de données (ordre de priorité / fallback) :
# 1. daily_log (SQLite) — tous les messages du jour, survit aux redémarrages
# 2. Discord channel history — fallback API si daily_log vide
# 3. RAM context windows — buffers mémoire de la session en cours
# 4. mem0 memory banks — faits stockés en mémoire longue

# Taille dynamique du journal :
# &lt; 50 messages → 150-250 mots
# 50-200 messages → 250-400 mots
# &gt; 200 messages → 400-600 mots

# Multi-pass summarization pour les grosses journées :
# 1. Découper en chunks de 30 messages
# 2. Résumer chaque chunk via modèle secondaire
# 3. Synthétiser les résumés en texte final

# Le journal inclut aussi :
# - Comparaison hebdo (émotions vs moyenne 7 jours)
# - Le journal de la veille (pour la continuité narrative)
# - Un graphe Matplotlib (PNG) des émotions du jour</code></pre>
              <p class="jd-tech-note">Le journal est déclenché par <strong>apscheduler</strong> (cron async) à une heure configurable. Il peut aussi être déclenché manuellement via <code>/wally journal</code>.</p>
              <p class="jd-tech-note">Le résultat est découpé en messages de max 1900 caractères (limite Discord = 2000) et posté dans le salon configuré. Le graphe PNG est envoyé en pièce jointe.</p>
              <p class="jd-tech-note"><strong>Formation d'opinions</strong> : en parallèle du journal, Wally analyse les sujets récurrents de la journée et forme des opinions nuancées qu'il stocke en mémoire. C'est un processus fire-and-forget qui enrichit sa personnalité au fil du temps.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 6: Architecture -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: #ff8800">6</span>
          <h3>Architecture</h3>
        </div>
        <div class="jd-body">
          <p>Wally est un <strong>programme Python unique</strong> (monolithe modulaire) qui gère Discord et Twitch en parallèle dans la même boucle asynchrone.</p>
          <p>Les deux plateformes partagent le <strong>même cerveau</strong> : le même moteur d'émotions, la même mémoire, la même personnalité, le même client OpenAI. C'est de l'<strong>injection de dépendances</strong> : les services sont créés une seule fois au démarrage, puis passés aux adaptateurs Discord et Twitch.</p>
          <p>Les souvenirs sont stockés dans <strong>Qdrant</strong>, une base de données spécialisée dans la recherche par similarité vectorielle. Les données opérationnelles (coûts, trust scores, timeouts, logs) sont dans <strong>SQLite</strong> via aiosqlite (async).</p>
          <p>Le tout tourne dans <strong>2 conteneurs Docker</strong> : un pour Wally (bot + dashboard web), un pour Qdrant. Qdrant a un healthcheck, et Wally attend qu'il soit prêt avant de démarrer.</p>

          <div class="jd-arch-diagram">
            <div class="jd-arch-row">
              <div class="jd-arch-box" style="border-color: #5865F2">
                <strong>Discord Bot</strong><br><span>discord.py 2.x</span>
              </div>
              <div class="jd-arch-box" style="border-color: #9146FF">
                <strong>Twitch Bot</strong><br><span>twitchio 2.x</span>
              </div>
              <div class="jd-arch-box" style="border-color: var(--accent)">
                <strong>Dashboard Web</strong><br><span>FastAPI + SSE</span>
              </div>
            </div>
            <div class="jd-arch-arrow">↓ injection de dépendances ↓</div>
            <div class="jd-arch-row">
              <div class="jd-arch-box jd-arch-core">
                <strong>Core Services</strong><br>
                <span>EmotionEngine · MemoryService · OpenAIClient · PersonaService · Config</span>
              </div>
            </div>
            <div class="jd-arch-arrow">↓ stockage ↓</div>
            <div class="jd-arch-row">
              <div class="jd-arch-box" style="border-color: var(--c-anger)">
                <strong>Qdrant</strong><br><span>Mémoire vectorielle</span>
              </div>
              <div class="jd-arch-box" style="border-color: var(--c-joy)">
                <strong>SQLite</strong><br><span>Coûts, trust, logs</span>
              </div>
              <div class="jd-arch-box" style="border-color: var(--c-curiosity)">
                <strong>OpenAI API</strong><br><span>GPT / o-series</span>
              </div>
            </div>
          </div>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — main.py et asyncio.gather()</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/main.py — point d'entrée</div>
              <pre><code># Injection de dépendances : tout est créé une fois, partagé partout
config = Config.load()
db = await Database.create(config)
emotion = EmotionEngine(config)
memory = MemoryService(config)
openai_client = OpenAIClient(config, db)
persona = PersonaService(config)

# Les deux bots reçoivent les mêmes services
discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, persona)
twitch_bot = WallyTwitch(config, db, emotion, memory, openai_client, persona)
dashboard = create_dashboard(config, db, emotion, memory, openai_client)

# Tout tourne en parallèle dans la même boucle événementielle
await asyncio.gather(
    discord_bot.start(token),
    twitch_bot.start(),
    dashboard.serve()
)</code></pre>
              <p class="jd-tech-note"><strong>asyncio.gather()</strong> lance les 3 services en parallèle dans la même boucle événementielle Python. Pas besoin de multi-threading ou de multi-processing — l'async/await suffit car tout le I/O est non-bloquant.</p>
              <p class="jd-tech-note"><strong>Docker</strong> : le <code>docker-compose.yml</code> définit 2 services. Wally dépend de Qdrant avec <code>condition: service_healthy</code> (healthcheck sur <code>/healthz</code>). La config et les données sont montées en volumes — pas besoin de rebuild pour changer la config.</p>
              <p class="jd-tech-note"><strong>Hot-reload</strong> : <code>config.save()</code> écrit la config en mémoire directement dans <code>config.yaml</code>. Les changements via le dashboard sont appliqués instantanément sans redémarrage.</p>
            </div>
          </details>
        </div>
      </section>
    </div>`;
}
