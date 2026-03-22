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
    renderLogsTab();  // ensure log-stream element exists before SSE starts
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
  if (tabId === 'memory' && !document.getElementById('mem-grid')) renderMemoryTab();
  if (tabId !== 'memory' && tabId !== 'admin-memoire' && _memLinkMode) { cancelLinkMode(); }
  if (tabId === 'global-memory') renderGlobalMemoryTab();
  if (tabId === 'gallery') loadGallery(true);
  if (tabId === 'admin-overlay') loadOverlayTab();
  if (tabId === 'admin-costs') loadCosts();
  if (tabId === 'admin-memory-dash') loadMemoryDashboard();
  if (tabId === 'admin-memoire') renderMemoireTab();
  if (tabId === 'admin-actions') renderActionsTab();
  pollCostsBadge();
  pollLinksBadge();
  if (tabId === 'admin-logs') {
    renderLogsTab();
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

  // Per-platform breakdown
  const breakdownEl = document.getElementById('stat-messages-breakdown');
  if (breakdownEl) {
    const parts = [];
    if (d.messages_discord) parts.push(`Discord ${d.messages_discord}`);
    if (d.messages_twitch) parts.push(`Twitch ${d.messages_twitch}`);
    if (d.messages_web) parts.push(`Web ${d.messages_web}`);
    breakdownEl.textContent = parts.length ? parts.join(' · ') : '';
  }
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
    <!-- Émotions (force + reset) -->
    <div class="card config-section">
      <div class="config-section-title">ÉMOTIONS</div>
      <div id="gauges-admin-inline" role="group" aria-label="Controle des emotions"></div>
      <div class="mt-4">
        <button class="btn btn-danger" onclick="resetEmotions()">RESET À NEUTRE (0.5)</button>
      </div>
    </div>

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

    <!-- Émotions — lambdas (boredom exclu : monte avec l'inactivité, pas de decay) -->
    <div class="card config-section">
      <div class="config-section-title">DÉCROISSANCE ÉMOTIONS (λ)</div>
      <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:0 0 12px">λ = vitesse de décroissance par heure. Plus la valeur est élevée, plus l'émotion retombe vite. Boredom monte avec l'inactivité et n'utilise pas ce paramètre.</p>
      ${Object.entries(cfg.emotions).filter(([name]) => name !== 'boredom').map(([name, ec]) => {
        const lam = ec.decay_lambda;
        const timeToZeroH = lam > 0 ? (Math.log(1/0.01)) / lam : Infinity;
        const timeLabel = timeToZeroH === Infinity ? '∞' : timeToZeroH < 1 ? Math.round(timeToZeroH * 60) + ' min' : Math.round(timeToZeroH * 10) / 10 + ' h';
        return `
        <div class="field-group" style="display:flex;align-items:center;gap:12px">
          <label class="field-label" for="cfg-lambda-${name}" style="color:${EMOTION_COLORS[name] || 'var(--text-muted)'}; min-width:100px">${name.toUpperCase()} λ</label>
          <input type="number" id="cfg-lambda-${name}" min="0" max="1" step="0.001" value="${lam}" style="width:90px" oninput="updateDecayTime(this, '${name}')">
          <span id="decay-time-${name}" style="font-size:0.8rem;color:rgba(255,255,255,0.5);white-space:nowrap">100→0% en <strong style="color:#e2e8f0">${timeLabel}</strong></span>
        </div>`;
      }).join('')}

      <!-- Boredom rise config -->
      <div style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.08)">
        <div style="display:flex;align-items:center;gap:12px">
          <label class="field-label" for="cfg-boredom-rise" style="color:${EMOTION_COLORS['boredom'] || 'var(--text-muted)'}; min-width:100px">BOREDOM ↑/h</label>
          <input type="number" id="cfg-boredom-rise" min="0" max="10" step="0.1" value="${cfg.emotions.boredom?.boredom_rise_per_hour ?? 1.2}" style="width:90px" oninput="updateBoredomTime(this)">
          <span id="boredom-time-info" style="font-size:0.8rem;color:rgba(255,255,255,0.5);white-space:nowrap">0→100% en <strong style="color:#e2e8f0">${(() => { const r = cfg.emotions.boredom?.boredom_rise_per_hour ?? 1.2; if (r <= 0) return '∞'; const h = 1/r; return h < 1 ? Math.round(h*60) + ' min' : Math.round(h*10)/10 + ' h'; })()}</strong></span>
        </div>
        <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:8px 0 0">Vitesse de montée de l'ennui par heure d'inactivité. 1.2 = ennui max en ~50 min.</p>
      </div>

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
      <div class="field-group">
        <label class="field-label">Notifications Discord</label>
        <select id="cfg-notif-channel" style="width:100%">
          <option value="">Désactivé</option>
        </select>
        <p style="font-size:0.7rem;color:rgba(255,255,255,0.35);margin-top:4px">Alertes coûts et erreurs envoyées dans ce salon</p>
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

  // Build emotion sliders inline
  buildGauges('gauges-admin-inline', true);
  // Update with current values if available
  if (currentEmotions && Object.keys(currentEmotions).length > 0) {
    updateEmotionGauges(currentEmotions);
  }

  // Load notification channels into the select
  loadNotificationChannels(cfg);
}

async function loadNotificationChannels(cfg) {
  const select = document.getElementById('cfg-notif-channel');
  if (!select) return;
  try {
    const r = await apiFetch('/api/admin/notification-channels');
    if (!r || !r.ok) return;
    const data = await r.json();
    const currentChannelId = cfg.bot.notification_channel_id;
    for (const guild of (data.guilds || [])) {
      const group = document.createElement('optgroup');
      group.label = guild.name;
      for (const ch of guild.channels) {
        const opt = document.createElement('option');
        opt.value = String(ch.id);
        opt.textContent = '#' + ch.name;
        if (currentChannelId && String(ch.id) === String(currentChannelId)) opt.selected = true;
        group.appendChild(opt);
      }
      select.appendChild(group);
    }
  } catch (e) { /* silently fail */ }
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

function updateDecayTime(input, name) {
  const lam = parseFloat(input.value) || 0;
  const timeToZeroH = lam > 0 ? (Math.log(1/0.01)) / lam : Infinity;
  const timeLabel = timeToZeroH === Infinity ? '∞' : timeToZeroH < 1 ? Math.round(timeToZeroH * 60) + ' min' : Math.round(timeToZeroH * 10) / 10 + ' h';
  const span = document.getElementById(`decay-time-${name}`);
  if (span) span.innerHTML = `100→0% en <strong style="color:#e2e8f0">${timeLabel}</strong>`;
}

function updateBoredomTime(input) {
  const r = parseFloat(input.value) || 0;
  let label;
  if (r <= 0) { label = '\u221e'; }
  else { const h = 1/r; label = h < 1 ? Math.round(h*60) + ' min' : Math.round(h*10)/10 + ' h'; }
  const span = document.getElementById('boredom-time-info');
  if (span) {
    span.textContent = '';
    span.append('0\u2192100% en ');
    const strong = document.createElement('strong');
    strong.style.color = '#e2e8f0';
    strong.textContent = label;
    span.appendChild(strong);
  }
}

async function saveEmotionLambdas() {
  const emotions = {};
  for (const e of EMOTIONS) {
    if (e === 'boredom') continue;
    const el = document.getElementById(`cfg-lambda-${e}`);
    if (el) emotions[e] = { decay_lambda: parseFloat(el.value) };
  }
  const boredomRise = document.getElementById('cfg-boredom-rise');
  if (boredomRise) emotions['boredom'] = { decay_lambda: 0.01, boredom_rise_per_hour: parseFloat(boredomRise.value) };
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
      notification_channel_id: document.getElementById('cfg-notif-channel').value || null,
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
        loadMemoryUsers();
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

// ── Logs tab with sub-navigation (Flux + Visiteurs) ─────────────────────────

let _logsSubTab = 'flux';

function renderLogsTab() {
  const el = document.getElementById('tab-admin-logs');
  if (!el) return;

  // Build structure once
  if (!el.querySelector('.mem-subnav')) {
    el.innerHTML = `
      <div class="mem-subnav">
        <button class="mem-subnav-pill active" data-subtab="flux" onclick="switchLogsSubTab('flux')">Flux</button>
        <button class="mem-subnav-pill" data-subtab="visitors" onclick="switchLogsSubTab('visitors')">Visiteurs</button>
      </div>
      <div class="mem-subnav-content active" id="logs-sub-flux">
        <div class="log-controls">
          <button class="btn active" id="log-filter-ALL" onclick="setLogFilter('ALL')">TOUS</button>
          <button class="btn" id="log-filter-INFO" onclick="setLogFilter('INFO')">INFO</button>
          <button class="btn" id="log-filter-WARNING" onclick="setLogFilter('WARNING')">WARNING</button>
          <button class="btn" id="log-filter-ERROR" onclick="setLogFilter('ERROR')">ERROR</button>
          <button class="btn" onclick="clearLogs()" aria-label="Vider les logs">VIDER</button>
        </div>
        <div class="log-stream" id="log-stream" role="log" aria-live="polite" aria-label="Flux de logs"></div>
      </div>
      <div class="mem-subnav-content" id="logs-sub-visitors"></div>
    `;
  }

  switchLogsSubTab(_logsSubTab);
}

function switchLogsSubTab(subtab) {
  _logsSubTab = subtab;
  const el = document.getElementById('tab-admin-logs');
  if (!el) return;

  el.querySelectorAll('.mem-subnav-pill').forEach(function(p) {
    p.classList.toggle('active', p.dataset.subtab === subtab);
  });
  el.querySelectorAll('.mem-subnav-content').forEach(function(c) { c.classList.remove('active'); });

  const panel = document.getElementById('logs-sub-' + subtab);
  if (panel) panel.classList.add('active');

  if (subtab === 'flux') {
    requestAnimationFrame(function() {
      var logEl = document.getElementById('log-stream');
      if (logEl) logEl.scrollTop = logEl.scrollHeight;
    });
  } else if (subtab === 'visitors') {
    loadVisitorsInPanel();
  }
}

async function loadVisitorsInPanel() {
  const el = document.getElementById('logs-sub-visitors');
  if (!el) return;

  const r = await apiFetch('/api/admin/chat-connections?limit=100');
  if (!r || !r.ok) { el.textContent = 'Erreur de chargement'; return; }
  const data = await r.json();
  const conns = data.connections || [];

  if (conns.length === 0) {
    el.innerHTML = '<div class="card"><p style="color:rgba(255,255,255,0.45)">Aucune connexion enregistrée</p></div>';
    return;
  }

  let rows = '';
  for (const c of conns) {
    const connTime = new Date(c.connected_at * 1000);
    const dateStr = connTime.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
    const timeStr = connTime.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    const duration = c.disconnected_at
      ? formatDuration(c.disconnected_at - c.connected_at)
      : '<span style="color:#00E5A0">en ligne</span>';
    const avatarHtml = c.avatar_url
      ? `<img src="${escAttr(c.avatar_url)}" class="visitor-avatar" alt="">`
      : '<div class="visitor-avatar-placeholder"></div>';
    rows += `
      <div class="visitor-row">
        ${avatarHtml}
        <div class="visitor-info">
          <strong>${escHtml(c.username)}</strong>
          <span class="visitor-date">${escHtml(dateStr)} ${escHtml(timeStr)}</span>
        </div>
        <div class="visitor-meta">
          <span class="visitor-msgs">${parseInt(c.message_count, 10)} msg</span>
          <span class="visitor-duration">${duration}</span>
        </div>
      </div>`;
  }

  el.innerHTML = `
    <div class="card">
      <div class="card-title">CONNEXIONS RECENTES AU CHAT WEB</div>
      <div class="visitor-list">${rows}</div>
    </div>`;
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

  await loadStatus();
  startEmotionSSE();
  setInterval(loadStatus, 30000);

  loadStreamStatus();
  requestAnimationFrame(() => setGraphRange('1h'));
  pollCostsBadge();
  pollLinksBadge();
  pollOverlayStatus();

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

// ── Memory Tab State ────────────────────────────────────────────
let _memShowAll = false;
let _memPlatformFilter = '';
let _memSortBy = 'memories';
let _memSearchTimer = null;
let _memLinkMode = false;
let _memLinkSourceId = null;
let _memLinkSourceName = null;
let _memCurrentUsers = []; // cached users for link mode

const MEM_CATEGORIES = [
  { key: 'FAIT', label: 'Faits', css: 'fait', color: '#22c55e' },
  { key: 'PREF', label: 'Préférences', css: 'pref', color: '#3b82f6' },
  { key: 'LANG', label: 'Langue', css: 'lang', color: '#eab308' },
  { key: 'REL', label: 'Relations', css: 'rel', color: '#a855f7' },
  { key: '', label: 'Non classé', css: 'other', color: '#64748b' },
];

function renderMemoryTab() {
  const el = document.getElementById('tab-memory');
  if (!el) return;
  el.innerHTML = '<div class="mem-toolbar">'
    + '<input type="text" class="mem-search" id="mem-search" placeholder="Rechercher un utilisateur..." aria-label="Recherche utilisateur">'
    + '<div class="mem-platform-pills">'
    + '<button class="mem-platform-pill active" data-platform="" onclick="setMemPlatform(this)">Tous</button>'
    + '<button class="mem-platform-pill" data-platform="discord" onclick="setMemPlatform(this)">Discord</button>'
    + '<button class="mem-platform-pill" data-platform="twitch" onclick="setMemPlatform(this)">Twitch</button>'
    + '</div>'
    + '<select class="mem-sort-select" id="mem-sort" onchange="setMemSort(this.value)">'
    + '<option value="memories">Mémoires</option>'
    + '<option value="trust">Trust</option>'
    + '<option value="love">Love</option>'
    + '<option value="name">Nom</option>'
    + '</select>'
    + '<label class="mem-toggle" onclick="toggleMemShowAll()">'
    + '<div class="mem-toggle-track" id="mem-toggle-track"><div class="mem-toggle-thumb"></div></div>'
    + '<span>Sans mémoire</span>'
    + '</label>'
    + '<button class="mem-action-btn" onclick="syncMemoryUsers()">↻ Sync</button>'
    + '<button class="mem-action-btn" onclick="analyzeLinks()">🔗 Analyser</button>'
    + '</div>'
    + '<div id="mem-link-banner" style="display:none"></div>'
    + '<div class="mem-grid" id="mem-grid"></div>';

  // Wire search with debounce
  var searchInput = document.getElementById('mem-search');
  if (searchInput) {
    searchInput.addEventListener('input', function() {
      clearTimeout(_memSearchTimer);
      _memSearchTimer = setTimeout(function() { loadMemoryUsers(); }, 300);
    });
  }

  loadMemoryUsers();
}

function setMemPlatform(btn) {
  _memPlatformFilter = btn.dataset.platform;
  document.querySelectorAll('.mem-platform-pill').forEach(function(p) { p.classList.remove('active'); });
  btn.classList.add('active');
  loadMemoryUsers();
}

function setMemSort(value) {
  _memSortBy = value;
  loadMemoryUsers();
}

function toggleMemShowAll() {
  _memShowAll = !_memShowAll;
  var track = document.getElementById('mem-toggle-track');
  if (track) track.classList.toggle('active', _memShowAll);
  loadMemoryUsers();
}

async function loadMemoryUsers() {
  var params = new URLSearchParams();
  var q = (document.getElementById('mem-search') || {}).value || '';
  if (q) params.set('q', q);
  if (_memShowAll) params.set('show_all', '1');
  if (_memSortBy) params.set('sort_by', _memSortBy);
  var url = '/api/admin/memory/users' + (params.toString() ? '?' + params : '');
  var r = await apiFetch(url);
  if (!r || !r.ok) return;
  var data = await r.json();
  var users = data.users;
  _memCurrentUsers = users;

  // Client-side platform filter
  var filtered = users;
  if (_memPlatformFilter) {
    filtered = users.filter(function(u) { return u.platform === _memPlatformFilter; });
  }

  var grid = document.getElementById('mem-grid');
  if (!grid) return;

  if (filtered.length === 0) {
    grid.textContent = '';
    var emptyDiv = document.createElement('div');
    emptyDiv.className = 'mem-empty-state';
    emptyDiv.textContent = 'Aucun utilisateur trouvé.';
    grid.appendChild(emptyDiv);
    return;
  }

  grid.innerHTML = filtered.map(function(u) {
    var displayName = u.username || u.user_id.split(':').slice(1).join(':') || u.user_id;
    var platform = u.platform || u.user_id.split(':')[0];
    var memCount = u.memory_count || 0;
    var trust = u.trust_score != null ? u.trust_score : 0;
    var love = u.love_score != null ? u.love_score : 0;
    var hasLinks = (u.linked_accounts || []).length > 0;
    var noMem = memCount === 0;
    var avatarUrl = u.avatar_url;
    var initial = (displayName || '?')[0].toUpperCase();

    var avatarStyle = avatarUrl
      ? "background-image:url('" + escAttr(avatarUrl) + "');background-size:cover;background-position:center"
      : '';
    var avatarContent = avatarUrl ? '' : escHtml(initial);

    // Link mode classes
    var cardClasses = 'mem-card';
    if (noMem) cardClasses += ' no-memory';
    if (_memLinkMode) {
      if (u.user_id === _memLinkSourceId) {
        cardClasses += ' link-source';
      } else {
        cardClasses += ' link-mode';
      }
    }

    var clickHandler = _memLinkMode
      ? "handleMemLinkClick('" + escAttr(u.user_id) + "','" + escAttr(displayName) + "','" + escAttr(platform) + "')"
      : "openUserModal('" + escAttr(u.user_id) + "')";

    return '<div class="' + cardClasses + '" data-uid="' + escAttr(u.user_id) + '" onclick="' + clickHandler + '">'
      + (hasLinks ? '<span class="mem-card-link-badge">🔗 lié</span>' : '')
      + '<div class="mem-card-avatar ' + escAttr(platform) + '" style="' + avatarStyle + '">' + avatarContent + '</div>'
      + '<div class="mem-card-name" title="' + escAttr(displayName) + '">' + escHtml(displayName) + '</div>'
      + '<div class="mem-card-sub">' + escHtml(platform) + ' · ' + (noMem ? '<em>sans mémoire</em>' : memCount + ' mémoire' + (memCount > 1 ? 's' : '')) + '</div>'
      + '<div class="mem-card-bars">'
      + '<div class="mem-card-bar"><div class="mem-card-bar-fill trust" style="width:' + Math.round(trust * 100) + '%"></div></div>'
      + '<div class="mem-card-bar"><div class="mem-card-bar-fill love" style="width:' + Math.round(love * 100) + '%"></div></div>'
      + '</div>'
      + '<div class="mem-card-stats">'
      + '<span style="color:#06b6d4">Trust ' + trust.toFixed(2) + '</span>'
      + '<span style="color:#ec4899">Love ' + love.toFixed(2) + '</span>'
      + '</div>'
      + '</div>';
  }).join('');
}

async function syncMemoryUsers() {
  var r = await apiFetch('/api/admin/memory/sync', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur sync', 'error'); return; }
  var data = await r.json();
  var msg = data.synced + ' importé(s)' + (data.resolved ? ', ' + data.resolved + ' nom(s) résolu(s)' : '');
  toast(msg, 'success');
  loadMemoryUsers();
}

// ── User Detail Modal ─────────────────────────────────────────────

async function openUserModal(userId, userData) {
  // Fetch memories
  var memR = await apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId));
  var memories = memR && memR.ok ? (await memR.json()).memories : [];

  // Find user data from cached list if not passed
  if (!userData) {
    userData = _memCurrentUsers.find(function(u) { return u.user_id === userId; }) || {};
  }

  var displayName = userData.username || userId.split(':').slice(1).join(':') || userId;
  var platform = userData.platform || userId.split(':')[0];
  var trust = userData.trust_score != null ? userData.trust_score : 0;
  var love = userData.love_score != null ? userData.love_score : 0;
  var avatarUrl = userData.avatar_url;
  var initial = (displayName || '?')[0].toUpperCase();
  var linkedAccounts = userData.linked_accounts || [];

  // Group memories by category
  var grouped = {};
  MEM_CATEGORIES.forEach(function(cat) { grouped[cat.key] = []; });
  memories.forEach(function(m) {
    var catKey = m.category || '';
    if (!grouped[catKey]) grouped[catKey] = grouped[''];
    grouped[catKey].push(m);
  });
  // Sort each group by date desc
  Object.keys(grouped).forEach(function(key) {
    grouped[key].sort(function(a, b) {
      var da = new Date(b.updated_at || b.created_at || 0);
      var db = new Date(a.updated_at || a.created_at || 0);
      return da - db;
    });
  });

  // Create backdrop
  var backdrop = document.createElement('div');
  backdrop.className = 'mem-modal-backdrop';
  backdrop.addEventListener('click', function(e) {
    if (e.target === backdrop) backdrop.remove();
  });

  var avatarStyle = avatarUrl
    ? "background-image:url('" + escAttr(avatarUrl) + "');background-size:cover;background-position:center"
    : '';
  var avatarContent = avatarUrl ? '' : escHtml(initial);

  // Build category sections HTML
  var categoriesHtml = '';
  MEM_CATEGORIES.forEach(function(cat) {
    var items = grouped[cat.key] || [];
    if (items.length === 0) return;
    categoriesHtml += '<div class="mem-category" data-cat="' + escAttr(cat.key) + '">'
      + '<div class="mem-category-header" onclick="toggleMemCategory(this)">'
      + '<span class="mem-category-chevron">▼</span>'
      + '<span class="mem-category-name ' + escAttr(cat.css) + '">' + escHtml(cat.label) + '</span>'
      + '<span class="mem-category-count">(' + items.length + ')</span>'
      + '</div>'
      + '<div class="mem-category-body">'
      + items.map(function(m) {
          var isOwn = (m.source || '') === userId || (m.source_platform || '') === platform;
          var sourceIcon = isOwn ? '🤖' : '✍️';
          var dateStr = m.updated_at || m.created_at;
          var shortDate = dateStr ? new Date(dateStr).toLocaleString('fr', { day:'numeric', month:'short' }) : '';
          return '<div class="mem-entry" id="mem-entry-' + escAttr(m.id) + '" style="border-left:2px solid ' + cat.color + '4d">'
            + '<span class="mem-entry-text" id="mem-text-' + escAttr(m.id) + '">' + escHtml(m.memory) + '</span>'
            + '<span class="mem-entry-source" title="' + (isOwn ? 'Auto-extrait' : 'Ajouté manuellement') + '">' + sourceIcon + '</span>'
            + '<span class="mem-entry-date">' + escHtml(shortDate) + '</span>'
            + '<div class="mem-entry-actions">'
            + '<button class="mem-entry-action" onclick="startModalEditMemory(\'' + escAttr(userId) + '\',\'' + escAttr(m.id) + '\')" title="Modifier">✏️</button>'
            + '<button class="mem-entry-action" onclick="deleteModalMemory(\'' + escAttr(userId) + '\',\'' + escAttr(m.id) + '\')" title="Supprimer">🗑</button>'
            + '</div></div>';
        }).join('')
      + '</div></div>';
  });

  if (categoriesHtml === '') {
    categoriesHtml = '<div class="mem-empty-state">Aucun souvenir enregistré.</div>';
  }

  // Build linked accounts section
  var linkedHtml = '';
  if (linkedAccounts.length > 0) {
    linkedHtml = '<div class="mem-linked-section">'
      + '<div class="mem-linked-title">Comptes liés</div>'
      + '<div class="mem-linked-pills">'
      + linkedAccounts.map(function(a) {
          var aPlatform = a.alias_platform || a.alias_id.split(':')[0];
          var aName = a.alias_username || a.alias_id.split(':').slice(1).join(':');
          return '<div class="mem-linked-pill ' + escAttr(aPlatform) + '">'
            + (PLATFORM_ICONS[aPlatform] || '') + ' ' + escHtml(aName)
            + '<button class="mem-linked-pill-unlink" onclick="unlinkFromModal(' + (a.link_id || 0) + ',\'' + escAttr(userId) + '\')" title="Délier">✕</button>'
            + '</div>';
        }).join('')
      + '</div></div>';
  }

  var modal = document.createElement('div');
  modal.className = 'mem-modal';
  modal.innerHTML = '<div class="mem-modal-header">'
    + '<div class="mem-modal-avatar ' + escAttr(platform) + '" style="' + avatarStyle + '">' + avatarContent + '</div>'
    + '<div class="mem-modal-info">'
    + '<div class="mem-modal-name">' + escHtml(displayName) + '</div>'
    + '<div class="mem-modal-sub">' + escHtml(platform) + ' · ' + escHtml(userId) + '</div>'
    + '</div>'
    + '<div class="mem-modal-stats">'
    + '<div class="mem-modal-stat"><div class="mem-modal-stat-value trust">' + trust.toFixed(2) + '</div><div class="mem-modal-stat-label">Trust</div></div>'
    + '<div class="mem-modal-stat"><div class="mem-modal-stat-value love">' + love.toFixed(2) + '</div><div class="mem-modal-stat-label">Love</div></div>'
    + '<div class="mem-modal-stat"><div class="mem-modal-stat-value count">' + memories.length + '</div><div class="mem-modal-stat-label">Mémoires</div></div>'
    + '</div>'
    + '<button class="mem-modal-close" onclick="this.closest(\'.mem-modal-backdrop\').remove()">✕</button>'
    + '</div>'
    + '<div class="mem-modal-actions">'
    + '<button class="mem-modal-action add" onclick="showModalAddForm(\'' + escAttr(userId) + '\')">+ Ajouter mémoire</button>'
    + '<button class="mem-modal-action link" onclick="startLinkMode(\'' + escAttr(userId) + '\',\'' + escAttr(displayName) + '\')">🔗 Lier un compte</button>'
    + (memories.length > 0 ? '<button class="mem-modal-action danger" onclick="deleteAllModalMemories(\'' + escAttr(userId) + '\')">🗑 Supprimer tout</button>' : '')
    + '</div>'
    + '<div id="modal-add-form"></div>'
    + '<input type="text" class="mem-modal-search" id="modal-mem-search" placeholder="🔍 Rechercher dans les mémoires..." oninput="filterModalMemories(this.value)">'
    + '<div id="modal-categories">' + categoriesHtml + '</div>'
    + linkedHtml;

  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);
}

function toggleMemCategory(headerEl) {
  var chevron = headerEl.querySelector('.mem-category-chevron');
  var body = headerEl.nextElementSibling;
  if (!chevron || !body) return;
  var isCollapsed = body.classList.toggle('collapsed');
  chevron.classList.toggle('collapsed', isCollapsed);
}

function filterModalMemories(query) {
  var q = query.toLowerCase();
  document.querySelectorAll('.mem-modal .mem-entry').forEach(function(entry) {
    var textEl = entry.querySelector('.mem-entry-text');
    var text = textEl ? textEl.textContent.toLowerCase() : '';
    entry.style.display = text.indexOf(q) >= 0 ? '' : 'none';
  });
}

function showModalAddForm(userId) {
  var el = document.getElementById('modal-add-form');
  if (!el) return;
  if (el.children.length > 0) { el.textContent = ''; return; }
  var catOptions = MEM_CATEGORIES.filter(function(c) { return c.key; }).map(function(c) {
    return '<option value="' + escAttr(c.key) + '">' + escHtml(c.label) + '</option>';
  }).join('') + '<option value="">Non classé</option>';
  el.innerHTML = '<div class="mem-add-form">'
    + '<input type="text" id="modal-add-input" placeholder="Nouveau souvenir...">'
    + '<select id="modal-add-category">' + catOptions + '</select>'
    + '<button onclick="submitModalAddMemory(\'' + escAttr(userId) + '\')">Ajouter</button>'
    + '</div>';
  var inp = document.getElementById('modal-add-input');
  if (inp) inp.focus();
}

async function submitModalAddMemory(userId) {
  var input = document.getElementById('modal-add-input');
  var catEl = document.getElementById('modal-add-category');
  var cat = catEl ? catEl.value : '';
  var content = input ? input.value.trim() : '';
  if (!content) { toast('Contenu requis', 'error'); return; }
  var body = { content: content };
  if (cat) body.category = cat;
  var r = await apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId) + '/memories', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (r && r.ok) {
    toast('Souvenir ajouté', 'success');
    var bdrop = document.querySelector('.mem-modal-backdrop');
    if (bdrop) bdrop.remove();
    await openUserModal(userId);
    loadMemoryUsers();
  } else {
    var err = r ? await r.json().catch(function() { return {}; }) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

function startModalEditMemory(userId, memoryId) {
  var textEl = document.getElementById('mem-text-' + memoryId);
  if (!textEl) return;
  var current = textEl.textContent;
  var entry = document.getElementById('mem-entry-' + memoryId);
  if (!entry) return;
  var actionsDiv = entry.querySelector('.mem-entry-actions');
  if (actionsDiv) actionsDiv.style.display = 'none';
  textEl.outerHTML = '<div style="display:flex;gap:6px;align-items:center;flex:1">'
    + '<input type="text" id="edit-mem-input-' + escAttr(memoryId) + '" value="' + escAttr(current) + '"'
    + ' style="flex:1;font-size:11px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:4px 8px;color:#e2e8f0"'
    + ' onkeydown="if(event.key===\'Enter\') submitModalEditMemory(\'' + escAttr(userId) + '\',\'' + escAttr(memoryId) + '\'); if(event.key===\'Escape\') reopenModal(\'' + escAttr(userId) + '\');">'
    + '<button class="mem-entry-action" onclick="submitModalEditMemory(\'' + escAttr(userId) + '\',\'' + escAttr(memoryId) + '\')" style="opacity:1;font-size:11px">OK</button>'
    + '<button class="mem-entry-action" onclick="reopenModal(\'' + escAttr(userId) + '\')" style="opacity:1;font-size:11px">✕</button>'
    + '</div>';
  var inp = document.getElementById('edit-mem-input-' + memoryId);
  if (inp) inp.focus();
}

async function submitModalEditMemory(userId, memoryId) {
  var input = document.getElementById('edit-mem-input-' + memoryId);
  var content = input ? input.value.trim() : '';
  if (!content) { toast('Contenu requis', 'error'); return; }
  var r = await apiFetch(
    '/api/admin/memory/users/' + encodeURIComponent(userId) + '/memories/' + encodeURIComponent(memoryId),
    { method: 'PUT', body: JSON.stringify({ content: content }) }
  );
  if (r && r.ok) {
    toast('Souvenir modifié', 'success');
    await reopenModal(userId);
  } else {
    var err = r ? await r.json().catch(function() { return {}; }) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

async function deleteModalMemory(userId, memoryId) {
  var r = await apiFetch(
    '/api/admin/memory/users/' + encodeURIComponent(userId) + '/memories/' + encodeURIComponent(memoryId),
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    toast('Souvenir supprimé', 'success');
    await reopenModal(userId);
    loadMemoryUsers();
  } else {
    toast('Erreur suppression', 'error');
  }
}

async function deleteAllModalMemories(userId) {
  if (!confirm('Supprimer tous les souvenirs de cet utilisateur ?')) return;
  var r = await apiFetch(
    '/api/admin/memory/users/' + encodeURIComponent(userId),
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    toast('Mémoire supprimée', 'success');
    var bdrop = document.querySelector('.mem-modal-backdrop');
    if (bdrop) bdrop.remove();
    loadMemoryUsers();
  } else {
    toast('Erreur suppression', 'error');
  }
}

async function reopenModal(userId) {
  var bdrop = document.querySelector('.mem-modal-backdrop');
  if (bdrop) bdrop.remove();
  await openUserModal(userId);
}

async function unlinkFromModal(linkId, userId) {
  var r = await apiFetch('/api/admin/links/' + linkId + '/unlink', { method: 'POST' });
  if (r && r.ok) {
    toast('Comptes déliés', 'success');
    await reopenModal(userId);
    loadMemoryUsers();
  } else {
    var err = r ? await r.json().catch(function() { return {}; }) : {};
    toast(err.detail || 'Erreur déliaison', 'error');
  }
}

// ── Account Linking Flow (grid selection mode) ─────────────────────

function startLinkMode(sourceUserId, sourceUsername) {
  _memLinkMode = true;
  _memLinkSourceId = sourceUserId;
  _memLinkSourceName = sourceUsername;
  // Close modal
  var bdrop = document.querySelector('.mem-modal-backdrop');
  if (bdrop) bdrop.remove();
  // Show banner
  var banner = document.getElementById('mem-link-banner');
  if (banner) {
    banner.style.display = 'flex';
    banner.className = 'mem-link-banner';
    banner.innerHTML = '<div class="mem-link-banner-info">'
      + '<strong>' + escHtml(sourceUsername) + '</strong> ↔ Cliquer sur un utilisateur...'
      + '</div>'
      + '<button class="mem-action-btn" onclick="cancelLinkMode()">Annuler</button>';
  }
  // Re-render grid with link mode classes
  loadMemoryUsers();
}

function cancelLinkMode() {
  _memLinkMode = false;
  _memLinkSourceId = null;
  _memLinkSourceName = null;
  var banner = document.getElementById('mem-link-banner');
  if (banner) banner.style.display = 'none';
  loadMemoryUsers();
}

async function handleMemLinkClick(targetUserId, targetName, targetPlatform) {
  if (!_memLinkMode || !_memLinkSourceId) return;
  if (targetUserId === _memLinkSourceId) return;

  if (!confirm('Lier ' + _memLinkSourceName + ' avec ' + targetName + ' ?')) return;

  // Determine canonical (Discord preferred)
  var sourcePlatform = _memLinkSourceId.split(':')[0];
  var canonical, alias;
  if (sourcePlatform === 'discord') {
    canonical = _memLinkSourceId; alias = targetUserId;
  } else if (targetPlatform === 'discord') {
    canonical = targetUserId; alias = _memLinkSourceId;
  } else {
    canonical = _memLinkSourceId; alias = targetUserId;
  }

  var r = await apiFetch('/api/admin/links/manual', {
    method: 'POST',
    body: JSON.stringify({ canonical_id: canonical, alias_id: alias }),
  });
  if (r && r.ok) {
    toast('Comptes liés avec succès', 'success');
    var sourceId = _memLinkSourceId;
    cancelLinkMode();
    // Reopen modal on source user
    await openUserModal(sourceId);
    pollLinksBadge();
  } else {
    var err = r ? await r.json().catch(function() { return {}; }) : {};
    toast(err.detail || 'Erreur liaison', 'error');
  }
}

// ── Global memory (dedicated tab) ─────────────────────────────────────────────

function renderGlobalMemoryTab() {
  const el = document.getElementById('tab-global-memory');
  if (!el) return;
  el.innerHTML = `
    <div style="max-width:800px;margin:0 auto;padding:20px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
        <div>
          <h2 style="margin:0;font-size:1.3rem">Memoire globale</h2>
          <p style="margin:4px 0 0;font-size:0.82rem;color:var(--text-muted)">
            Connaissances partagees par toute la communaute (liens, regles, infos serveur).
            Consultees automatiquement a chaque requete.
          </p>
        </div>
        <span id="global-mem-count" class="badge" style="font-size:0.75rem;padding:4px 10px"></span>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:20px">
        <input type="text" id="add-global-memory-input" placeholder="Ajouter une connaissance globale…"
               style="flex:1" onkeydown="if(event.key==='Enter') submitAddGlobalMemory()">
        <button class="btn btn-success" onclick="submitAddGlobalMemory()" style="white-space:nowrap">Ajouter</button>
      </div>
      <div id="global-memory-list"></div>
    </div>
  `;
  loadGlobalMemories();
}

async function loadGlobalMemories() {
  const r = await apiFetch('/api/admin/memory/global');
  if (!r || !r.ok) return;
  const { memories } = await r.json();
  const countEl = document.getElementById('global-mem-count');
  if (countEl) countEl.textContent = memories.length + ' souvenir' + (memories.length !== 1 ? 's' : '');
  const listEl = document.getElementById('global-memory-list');
  if (!listEl) return;
  if (memories.length === 0) {
    listEl.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px 0;font-size:0.9rem">Aucune memoire globale pour l\'instant.<br>Ajoute des liens, regles ou infos communaute ci-dessus.</div>';
    return;
  }
  listEl.innerHTML = memories.map(m => {
    const dateStr = m.updated_at || m.created_at;
    const dateFmt = dateStr
      ? new Date(dateStr).toLocaleString('fr', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' })
      : '';
    return `
      <div class="mem-entry" id="mem-entry-${escAttr(m.id)}" style="margin-bottom:8px">
        <div class="mem-entry-content">
          <div class="mem-entry-meta">
            <span class="mem-entry-platform" style="background:var(--accent);color:#fff;border-color:var(--accent)">Global</span>
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

async function submitAddGlobalMemory() {
  const input = document.getElementById('add-global-memory-input');
  const content = input?.value.trim();
  if (!content) { toast('Contenu requis', 'error'); return; }
  const r = await apiFetch('/api/admin/memory/global', {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
  if (r && r.ok) {
    toast('Memoire globale ajoutee', 'success');
    input.value = '';
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
    toast('Memoire globale modifiee', 'success');
    await loadGlobalMemories();
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur', 'error');
    await loadGlobalMemories();
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
      const n = (parseInt(countEl.textContent) || 1) - 1;
      countEl.textContent = n + ' souvenir' + (n !== 1 ? 's' : '');
    }
    toast('Memoire globale supprimee', 'success');
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
    loadMemoryUsers();
    pollLinksBadge();
  } else {
    toast('Erreur', 'error');
  }
}

async function rejectLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/reject`, { method: 'POST' });
  if (r && r.ok) {
    toast('Liaison rejetée', 'success');
    pollLinksBadge();
  } else {
    toast('Erreur', 'error');
  }
}

async function unlinkAccounts(id) {
  const r = await apiFetch(`/api/admin/links/${id}/unlink`, { method: 'POST' });
  if (r && r.ok) {
    toast('Comptes déliés', 'success');
    loadMemoryUsers();
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

  // Forecast KPI
  const forecastEl = document.getElementById('cost-forecast');
  if (forecastEl && summary.forecast !== undefined) {
    forecastEl.textContent = `$${summary.forecast.toFixed(2)}`;
    const forecastColor = summary.forecast > alert.threshold ? '#FF4D4D' : '#00E5A0';
    forecastEl.style.color = forecastColor;
    const detailEl = document.getElementById('cost-forecast-detail');
    if (detailEl) detailEl.textContent = `J${summary.days_elapsed}/${summary.days_in_month} — moy. $${(summary.total / summary.days_elapsed).toFixed(2)}/j`;
  }

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
  setupSlashAutocomplete();
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
    } else if (data.type === 'image_generating') {
      chatAppendImageGenerating(data);
      chatScrollBottom();
    } else if (data.type === 'image_result') {
      chatReplaceImageResult(data);
      chatScrollBottom();
    } else if (data.type === 'image_cancelled') {
      chatReplaceImageCancelled(data);
      chatScrollBottom();
    } else if (data.type === 'vote_result') {
      chatUpdateVoteState(data);
    } else if (data.type === 'title_updated') {
      chatUpdateEmbedTitle(data);
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

// ── Overlay toggle ──────────────────────────────────────────────────────────

async function toggleOverlay() {
  const r = await apiFetch('/api/admin/overlay/toggle', { method: 'POST' });
  if (r && r.ok) {
    const data = await r.json();
    updateOverlaySwitch(data.visible);
    toast(data.visible ? 'Overlay visible' : 'Overlay masqué');
  }
}

function updateOverlaySwitch(visible) {
  const sw = document.getElementById('overlay-switch');
  if (sw) {
    if (visible) sw.classList.add('on');
    else sw.classList.remove('on');
  }
  // Also update the tab-based switch if present
  if (typeof updateOverlaySwitchTab === 'function') updateOverlaySwitchTab(visible);
}

async function pollOverlayStatus() {
  try {
    const r = await apiFetch('/api/admin/overlay/status');
    if (r && r.ok) {
      const data = await r.json();
      updateOverlaySwitch(data.visible);
    }
  } catch {}
}

// ── Visitors ────────────────────────────────────────────────────────────────

async function loadVisitors() {
  const el = document.getElementById('tab-admin-visitors');
  if (!el) return;

  const r = await apiFetch('/api/admin/chat-connections?limit=100');
  if (!r || !r.ok) { el.textContent = 'Erreur de chargement'; return; }
  const data = await r.json();
  const conns = data.connections || [];

  if (conns.length === 0) {
    el.innerHTML = '<div class="card"><p style="color:rgba(255,255,255,0.45)">Aucune connexion enregistrée</p></div>';
    return;
  }

  // All user-provided fields escaped via escHtml()
  let rows = '';
  for (const c of conns) {
    const connTime = new Date(c.connected_at * 1000);
    const dateStr = connTime.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
    const timeStr = connTime.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    const duration = c.disconnected_at
      ? formatDuration(c.disconnected_at - c.connected_at)
      : '<span style="color:#00E5A0">en ligne</span>';
    const avatarHtml = c.avatar_url
      ? `<img src="${escAttr(c.avatar_url)}" class="visitor-avatar" alt="">`
      : '<div class="visitor-avatar-placeholder"></div>';
    rows += `
      <div class="visitor-row">
        ${avatarHtml}
        <div class="visitor-info">
          <strong>${escHtml(c.username)}</strong>
          <span class="visitor-date">${escHtml(dateStr)} ${escHtml(timeStr)}</span>
        </div>
        <div class="visitor-meta">
          <span class="visitor-msgs">${parseInt(c.message_count, 10)} msg</span>
          <span class="visitor-duration">${duration}</span>
        </div>
      </div>`;
  }

  el.innerHTML = `
    <div class="card">
      <div class="card-title">CONNEXIONS RECENTES AU CHAT WEB</div>
      <div class="visitor-list">${rows}</div>
    </div>`;
}

function formatDuration(seconds) {
  const s = Math.floor(seconds);
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s / 60) + 'min';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h + 'h' + (m > 0 ? m + 'min' : '');
}

// ── Memory Dashboard ────────────────────────────────────────────────────────

async function loadMemoryDashboard() {
  const el = document.getElementById('tab-admin-memory-dash');
  if (!el) return;

  const r = await apiFetch('/api/admin/memory/dashboard');
  if (!r || !r.ok) { el.textContent = 'Erreur de chargement'; return; }
  const data = await r.json();

  const qs = data.question_stats || {};
  const pending = data.pending_questions || [];
  const userCounts = data.user_memory_counts || [];

  // All user-provided data is escaped via escHtml() before injection
  let questionsHtml = '';
  if (pending.length === 0) {
    questionsHtml = '<p style="color:rgba(255,255,255,0.45);padding:8px">Aucune question en attente</p>';
  } else {
    questionsHtml = '<div class="mem-dash-questions">';
    for (const q of pending) {
      const name = escHtml(q.username || q.user_id);
      const prioColor = q.priority === 'high' ? '#FF4D4D' : q.priority === 'medium' ? '#FFD700' : '#00E5A0';
      const qId = parseInt(q.id, 10);
      questionsHtml += `
        <div class="mem-dash-q-row" id="mem-q-${qId}">
          <div class="mem-dash-q-info">
            <span class="mem-dash-q-prio" style="background:${prioColor}"></span>
            <strong>${name}</strong>
            <span style="color:rgba(255,255,255,0.45);margin-left:8px">tentative ${parseInt(q.attempts, 10)}/3</span>
          </div>
          <div class="mem-dash-q-memory">${escHtml(q.memory_text)}</div>
          <div class="mem-dash-q-question" id="mem-q-text-${qId}">${escHtml(q.question)}</div>
          <div class="mem-dash-q-actions">
            <button class="btn btn-sm" onclick="resolveMemQuestion(${qId})">Résoudre</button>
            <button class="btn btn-sm btn-outline" onclick="editMemQuestion(${qId})">Modifier</button>
            <button class="btn btn-sm btn-danger" onclick="deleteMemQuestion(${qId})">Supprimer</button>
          </div>
        </div>`;
    }
    questionsHtml += '</div>';
  }

  let barsHtml = '';
  if (userCounts.length > 0) {
    const maxCount = userCounts[0].count || 1;
    for (const u of userCounts) {
      const pct = Math.round(u.count / maxCount * 100);
      const platIcon = u.platform === 'discord' ? '🟣' : u.platform === 'twitch' ? '🟪' : '🌐';
      barsHtml += `
        <div class="mem-dash-bar-row">
          <span class="mem-dash-bar-label">${platIcon} ${escHtml(u.username)}</span>
          <div class="mem-dash-bar-track"><div class="mem-dash-bar-fill" style="width:${pct}%"></div></div>
          <span class="mem-dash-bar-count">${parseInt(u.count, 10)}</span>
        </div>`;
    }
  } else {
    barsHtml = '<p style="color:rgba(255,255,255,0.45);padding:8px">Aucune donnée</p>';
  }

  // KPI values are integers from the backend, safe to inject
  el.innerHTML = `
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
      <div class="card">
        <div class="card-title">QUESTIONS EN ATTENTE</div>
        <div class="card-value" id="kpi-q-pending" style="color:#FFD700">${parseInt(qs.pending, 10) || 0}</div>
      </div>
      <div class="card">
        <div class="card-title">QUESTIONS RESOLUES</div>
        <div class="card-value" id="kpi-q-resolved" style="color:#00E5A0">${parseInt(qs.resolved, 10) || 0}</div>
      </div>
      <div class="card">
        <div class="card-title">TOTAL QUESTIONS</div>
        <div class="card-value" id="kpi-q-total">${parseInt(qs.total, 10) || 0}</div>
      </div>
    </div>
    <div class="card mb-6">
      <div class="card-title">QUESTIONS A POSER</div>
      ${questionsHtml}
    </div>
    <div class="card">
      <div class="card-title">SOUVENIRS PAR UTILISATEUR (TOP 20)</div>
      <div class="mem-dash-bars">${barsHtml}</div>
    </div>
  `;
}

function _removeQuestionRow(id, action) {
  const row = document.getElementById('mem-q-' + id);
  if (row) {
    row.style.transition = 'opacity 0.3s, transform 0.3s';
    row.style.opacity = '0';
    row.style.transform = 'translateX(20px)';
    setTimeout(function() { row.remove(); }, 300);
  }
  const pendingEl = document.getElementById('kpi-q-pending');
  const resolvedEl = document.getElementById('kpi-q-resolved');
  const totalEl = document.getElementById('kpi-q-total');
  const pending = pendingEl ? (parseInt(pendingEl.textContent, 10) || 0) : 0;
  if (action === 'resolve') {
    if (pendingEl && pending > 0) pendingEl.textContent = pending - 1;
    if (resolvedEl) resolvedEl.textContent = (parseInt(resolvedEl.textContent, 10) || 0) + 1;
  } else if (action === 'delete') {
    if (pendingEl && pending > 0) pendingEl.textContent = pending - 1;
    if (totalEl) totalEl.textContent = Math.max(0, (parseInt(totalEl.textContent, 10) || 0) - 1);
  }
}

async function resolveMemQuestion(id) {
  id = parseInt(id, 10);
  _removeQuestionRow(id, 'resolve');
  const r = await apiFetch(`/api/admin/memory/questions/${id}/resolve`, { method: 'POST' });
  if (r && r.ok) {
    toast('Question marquée comme résolue');
  } else {
    toast('Erreur lors de la résolution', 'error');
    loadMemoryDashboard();
  }
}

async function editMemQuestion(id) {
  id = parseInt(id, 10);
  const textEl = document.getElementById('mem-q-text-' + id);
  if (!textEl) return;
  const current = textEl.textContent;
  const newText = prompt('Modifier la question :', current);
  if (newText === null || newText.trim() === '' || newText.trim() === current) return;
  textEl.textContent = newText.trim();
  const r = await apiFetch(`/api/admin/memory/questions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: newText.trim() }),
  });
  if (r && r.ok) {
    toast('Question modifiée');
  } else {
    toast('Erreur lors de la modification', 'error');
    textEl.textContent = current;
  }
}

async function deleteMemQuestion(id) {
  id = parseInt(id, 10);
  if (!confirm('Supprimer cette question ?')) return;
  _removeQuestionRow(id, 'delete');
  const r = await apiFetch(`/api/admin/memory/questions/${id}`, { method: 'DELETE' });
  if (r && r.ok) {
    toast('Question supprimée');
  } else {
    toast('Erreur lors de la suppression', 'error');
    loadMemoryDashboard();
  }
}

// ── Merged Mémoire Tab (Users + Global + Dashboard) ──────────────────────────

let _memoireSubTab = 'users';

function renderMemoireTab() {
  const el = document.getElementById('tab-admin-memoire');
  if (!el) return;

  // Only build structure once
  if (!el.querySelector('.mem-subnav')) {
    el.innerHTML = `
      <div class="mem-subnav">
        <button class="mem-subnav-pill active" data-subtab="users" onclick="switchMemoireSubTab('users')">Utilisateurs</button>
        <button class="mem-subnav-pill" data-subtab="global" onclick="switchMemoireSubTab('global')">Globale</button>
        <button class="mem-subnav-pill" data-subtab="dashboard" onclick="switchMemoireSubTab('dashboard')">Questions</button>
      </div>
      <div class="mem-subnav-content active" id="memoire-sub-users"></div>
      <div class="mem-subnav-content" id="memoire-sub-global"></div>
      <div class="mem-subnav-content" id="memoire-sub-dashboard"></div>
    `;
  }

  switchMemoireSubTab(_memoireSubTab);
}

function switchMemoireSubTab(subtab) {
  _memoireSubTab = subtab;
  const el = document.getElementById('tab-admin-memoire');
  if (!el) return;

  el.querySelectorAll('.mem-subnav-pill').forEach(function(p) {
    p.classList.toggle('active', p.dataset.subtab === subtab);
  });
  el.querySelectorAll('.mem-subnav-content').forEach(function(c) { c.classList.remove('active'); });
  const panel = document.getElementById('memoire-sub-' + subtab);
  if (panel) panel.classList.add('active');

  if (subtab === 'users') {
    // Move memory tab content into the sub-panel
    const memTab = document.getElementById('tab-memory');
    if (!document.getElementById('mem-grid')) renderMemoryTab();
    if (memTab && panel && memTab.children.length > 0 && panel.children.length === 0) {
      while (memTab.firstChild) panel.appendChild(memTab.firstChild);
    }
  } else if (subtab === 'global') {
    const gmTab = document.getElementById('tab-global-memory');
    renderGlobalMemoryTab();
    if (gmTab && panel && gmTab.children.length > 0 && panel.children.length === 0) {
      while (gmTab.firstChild) panel.appendChild(gmTab.firstChild);
    }
  } else if (subtab === 'dashboard') {
    const mdTab = document.getElementById('tab-admin-memory-dash');
    if (panel && panel.children.length === 0) {
      // Temporarily point loadMemoryDashboard to our sub-panel
      const origId = mdTab ? mdTab.id : null;
      if (mdTab) mdTab.id = '_tmp_mem_dash';
      panel.id = 'tab-admin-memory-dash';
      loadMemoryDashboard().then(function() {
        panel.id = 'memoire-sub-dashboard';
        if (mdTab && origId) mdTab.id = origId;
      });
    }
  }
}

// ── Merged Overlay Tab (toggle + config) ────────────────────────────────────

function loadOverlayTab() {
  const container = document.getElementById('overlay-config-container');
  if (!container) return;

  // Add the toggle at the top if not already present
  if (!document.getElementById('overlay-tab-toggle')) {
    const toggleCard = document.createElement('div');
    toggleCard.className = 'card';
    toggleCard.id = 'overlay-tab-toggle';
    toggleCard.style.marginBottom = '20px';
    toggleCard.innerHTML = `
      <div class="card-title">OVERLAY ON/OFF</div>
      <div style="display:flex;align-items:center;gap:16px">
        <span style="color:rgba(255,255,255,0.55);font-size:0.85rem">Basculer la visibilité de l'overlay OBS</span>
        <div class="overlay-switch" id="overlay-switch-tab" style="cursor:pointer" onclick="toggleOverlayFromTab()">
          <div class="overlay-switch-knob"></div>
        </div>
        <span id="overlay-status-label" style="font-size:0.78rem;color:rgba(255,255,255,0.45)"></span>
      </div>
    `;
    container.parentElement.insertBefore(toggleCard, container);

    // Sync the switch state
    pollOverlayStatusForTab();
  }

  loadOverlayConfig();
}

async function toggleOverlayFromTab() {
  const r = await apiFetch('/api/admin/overlay/toggle', { method: 'POST' });
  if (r && r.ok) {
    const data = await r.json();
    updateOverlaySwitch(data.visible);
    updateOverlaySwitchTab(data.visible);
    toast(data.visible ? 'Overlay visible' : 'Overlay masqué');
  }
}

function updateOverlaySwitchTab(visible) {
  const sw = document.getElementById('overlay-switch-tab');
  const lbl = document.getElementById('overlay-status-label');
  if (sw) {
    if (visible) sw.classList.add('on');
    else sw.classList.remove('on');
  }
  if (lbl) lbl.textContent = visible ? 'Visible' : 'Masqué';
}

async function pollOverlayStatusForTab() {
  try {
    const r = await apiFetch('/api/admin/overlay/status');
    if (r && r.ok) {
      const data = await r.json();
      updateOverlaySwitchTab(data.visible);
    }
  } catch {}
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
          <p><strong>Maintenance automatique</strong> — Wally ne se contente pas de stocker des souvenirs, il les entretient. Chaque nouveau souvenir est évalué pour sa complétude : si une information est vague ou incomplète (une date sans mois, un lieu non précisé), Wally note une question à poser et la glisse naturellement dans une prochaine conversation. Chaque soir, 30 minutes avant son journal, il fait le tri : il supprime les faits périmés, reformule les vagues, et identifie de nouvelles questions. Maximum 1 question par conversation, maximum 3 tentatives — Wally insiste, mais pas trop.</p>

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
              <p class="jd-tech-note"><strong>Memory scoring</strong> : chaque <code>memory.add()</code> déclenche un appel LLM secondaire (<code>_evaluate_memory</code>) qui évalue la complétude du souvenir. Les questions générées sont stockées dans la table <code>memory_questions</code> et injectées dans le prompt (max 1 par conversation, max 3 tentatives). Si le nouveau souvenir répond à une question existante, elle est automatiquement résolue.</p>
              <p class="jd-tech-note"><strong>Nettoyage quotidien</strong> : cron 30min avant le journal (<code>run_memory_cleanup</code>). Passe en revue les souvenirs des 20 utilisateurs les plus actifs, identifie les faits périmés/vagues via LLM, et applique suppressions + reformulations. Appelle <code>mem0</code> directement pour éviter les cascades avec la consolidation.</p>
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

      <!-- Section 6: Galerie d'images et vision -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-joy); color: #000">6</span>
          <h3>Galerie d'images et vision</h3>
        </div>
        <div class="jd-body">
          <p>Wally peut <strong>générer des images</strong> via la commande <code>/imagine</code> sur Discord ou dans le chat web. Il utilise l'API OpenAI Images pour créer l'image, puis un modèle secondaire génère automatiquement un <strong>titre court et créatif</strong>.</p>
          <p>Chaque image est sauvegardée dans la <strong>galerie</strong>, accessible depuis le dashboard. Les utilisateurs peuvent <strong>voter</strong> avec une flamme (toggle), trier par date ou par votes, filtrer par créateur, et le créateur peut <strong>modifier le titre</strong> de son image.</p>
          <p>Wally a aussi la <strong>vision</strong> : quand quelqu'un envoie une image en pièce jointe, il la voit et peut la commenter. Et quand quelqu'un <strong>répond à une image qu'il a générée</strong>, il sait que c'est la sienne — il reconnaît le titre, le prompt original, et peut en discuter naturellement.</p>
          <p>Des <strong>limites configurables</strong> empêchent les abus : limite journalière globale et par utilisateur. Le coût de chaque génération est logué dans la base de données.</p>

          <div class="jd-pipeline">
            <span class="jd-pipe-step" style="background: var(--c-joy); color: #000">✨ /imagine</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">🎨 OpenAI Images</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">📝 Titre LLM</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">💾 Galerie</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step" style="background: var(--c-anger)">🔥 Votes</span>
          </div>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — génération et vision</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/discord/commands/imagine.py + bot/discord/handlers.py</div>
              <pre><code># Génération d'image
result = await openai.generate_image(prompt, sender_id)

# Titre auto via modèle secondaire
title = await openai.complete_secondary(
    "Génère un titre court et créatif (max 6 mots)...",
    purpose="image_title"
)

# Vision : quand on répond à un message avec une image
# Wally récupère l'image du message référencé
if message.reference:
    ref_msg = message.reference.resolved
    # Extrait les URLs d'images (attachments + embeds)
    # Si c'est une image de Wally → contexte enrichi :
    # "[Tu as généré cette image. Titre: X. Prompt: Y]"
    # Sinon → "[L'utilisateur répond à une image.]"</code></pre>
              <p class="jd-tech-note"><strong>Vision multimodale</strong> : les URLs d'images sont passées à OpenAI via le paramètre <code>image_urls</code>. Le modèle voit l'image et peut la décrire, la commenter ou répondre à des questions dessus.</p>
              <p class="jd-tech-note"><strong>Reconnaissance d'auteur</strong> : quand le message référencé vient de Wally lui-même, le contexte injecté précise « c'est une image que TU as générée », avec le titre et le prompt original. Wally peut ainsi en parler naturellement.</p>
              <p class="jd-tech-note"><strong>Stockage</strong> : images sur disque (<code>data/gallery/</code>), métadonnées dans SQLite (<code>gallery_images</code> + <code>gallery_votes</code>). Coût logué dans <code>cost_log</code>.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 7: Architecture -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: #ff8800">7</span>
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

// ── Debounce utility ──────────────────────────────────────────────────────────

function debounce(fn, ms) {
  let t;
  return function(...args) { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), ms); };
}

// ── Gallery ───────────────────────────────────────────────────────────────────

let _galleryOffset = 0;
const _galleryLimit = 20;

async function loadGallery(reset) {
  if (reset) _galleryOffset = 0;
  const search = document.getElementById('gallery-search')?.value || '';
  const sort = document.getElementById('gallery-sort')?.value || 'date';
  const userFilter = document.getElementById('gallery-user-filter')?.value || '';
  const params = new URLSearchParams({ sort_by: sort, limit: _galleryLimit, offset: _galleryOffset });
  if (search) params.set('search', search);
  if (userFilter) params.set('user_filter', userFilter);
  const r = await fetch('/api/public/gallery?' + params);
  if (!r.ok) return;
  const data = await r.json();
  const grid = document.getElementById('gallery-grid');
  if (reset) grid.textContent = '';
  data.images.forEach(function(img) { grid.appendChild(renderGalleryCard(img)); });
  document.getElementById('gallery-load-more').style.display = data.images.length >= _galleryLimit ? '' : 'none';
  _galleryOffset += data.images.length;
}

function loadMoreGallery() { loadGallery(false); }

function renderGalleryCard(img) {
  const card = document.createElement('div');
  card.className = 'gallery-card';
  card.dataset.id = img.id;
  const dateStr = img.created_at ? new Date(img.created_at + 'Z').toLocaleString('fr-FR') : '';

  const imgEl = document.createElement('img');
  imgEl.src = '/api/public/gallery/' + img.id + '/image';
  imgEl.alt = img.title || '';
  imgEl.loading = 'lazy';
  imgEl.onclick = function() { openLightbox(img.id); };
  card.appendChild(imgEl);

  const info = document.createElement('div');
  info.className = 'gallery-card-info';

  const title = document.createElement('div');
  title.className = 'gallery-card-title';
  title.textContent = img.title || 'Sans titre';
  info.appendChild(title);

  const prompt = document.createElement('div');
  prompt.className = 'gallery-card-prompt';
  prompt.title = img.prompt || '';
  prompt.textContent = img.prompt || '';
  info.appendChild(prompt);

  const meta = document.createElement('div');
  meta.className = 'gallery-card-meta';
  const userSpan = document.createElement('span');
  userSpan.textContent = img.username;
  const dateSpan = document.createElement('span');
  dateSpan.textContent = dateStr;
  meta.appendChild(userSpan);
  meta.appendChild(dateSpan);
  info.appendChild(meta);
  card.appendChild(info);

  const footer = document.createElement('div');
  footer.className = 'gallery-card-footer';

  const flameBtn = document.createElement('button');
  flameBtn.className = 'flame-btn' + (img.user_voted ? ' active' : '');
  flameBtn.onclick = function(e) { e.stopPropagation(); toggleFlame(img.id, flameBtn); };
  flameBtn.textContent = '';
  const fireText = document.createTextNode('🔥 ');
  const voteSpan = document.createElement('span');
  voteSpan.textContent = img.votes || 0;
  flameBtn.appendChild(fireText);
  flameBtn.appendChild(voteSpan);
  footer.appendChild(flameBtn);

  if (currentMode === 'admin') {
    const delBtn = document.createElement('button');
    delBtn.className = 'gallery-delete-btn';
    delBtn.textContent = '🗑️';
    delBtn.onclick = function(e) { e.stopPropagation(); deleteGalleryImage(img.id); };
    footer.appendChild(delBtn);
  }

  card.appendChild(footer);
  return card;
}

async function toggleFlame(imageId, btn) {
  const r = await fetch('/api/public/gallery/' + imageId + '/vote', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + (getChatJwt() || '') }
  });
  if (!r.ok) {
    if (r.status === 401) toast('Connectez-vous au chat pour voter', 'error');
    return;
  }
  const data = await r.json();
  btn.classList.toggle('active', data.voted);
  const detail = await fetch('/api/public/gallery/' + imageId);
  if (detail.ok) {
    const img = await detail.json();
    btn.querySelector('span').textContent = img.votes || 0;
  }
}

async function deleteGalleryImage(imageId) {
  if (!confirm('Supprimer cette image ?')) return;
  const r = await apiFetch('/api/admin/gallery/' + imageId, { method: 'DELETE' });
  if (r && r.ok) {
    const card = document.querySelector('.gallery-card[data-id="' + imageId + '"]');
    if (card) card.remove();
    toast('Image supprimée', 'success');
  }
}

function openLightbox(imageId) {
  fetch('/api/public/gallery/' + imageId).then(function(r) { return r.json(); }).then(function(img) {
    const dateStr = img.created_at ? new Date(img.created_at + 'Z').toLocaleString('fr-FR') : '';
    const lb = document.createElement('div');
    lb.className = 'gallery-lightbox';
    lb.onclick = function(e) { if (e.target === lb) lb.remove(); };

    const closeSpan = document.createElement('span');
    closeSpan.className = 'gallery-lightbox-close';
    closeSpan.textContent = '\u00d7';
    closeSpan.onclick = function() { lb.remove(); };
    lb.appendChild(closeSpan);

    const lbImg = document.createElement('img');
    lbImg.src = '/api/public/gallery/' + img.id + '/image';
    lbImg.alt = '';
    lb.appendChild(lbImg);

    const infoDiv = document.createElement('div');
    infoDiv.className = 'gallery-lightbox-info';
    const h3 = document.createElement('h3');
    h3.textContent = img.title || 'Sans titre';
    infoDiv.appendChild(h3);
    const p = document.createElement('p');
    p.textContent = img.prompt || '';
    infoDiv.appendChild(p);
    const metaDiv = document.createElement('div');
    metaDiv.className = 'meta';
    metaDiv.textContent = (img.username || '') + ' — ' + dateStr;
    infoDiv.appendChild(metaDiv);
    lb.appendChild(infoDiv);

    document.body.appendChild(lb);
  });
}

// Gallery event listeners (initialized on DOMContentLoaded)
document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('gallery-search')?.addEventListener('input', debounce(function() { loadGallery(true); }, 400));
  document.getElementById('gallery-sort')?.addEventListener('change', function() { loadGallery(true); });
  document.getElementById('gallery-user-filter')?.addEventListener('change', function() { loadGallery(true); });
});

// ── Overlay Config (Admin) ────────────────────────────────────────────────────

const ANIMATE_CSS_IN = ['fadeIn','fadeInDown','fadeInLeft','fadeInRight','fadeInUp','bounceIn','bounceInDown','bounceInLeft','bounceInRight','bounceInUp','zoomIn','zoomInDown','zoomInLeft','zoomInRight','zoomInUp','slideInDown','slideInLeft','slideInRight','slideInUp','flipInX','flipInY','backInDown','backInLeft','backInRight','backInUp','rotateIn'];
const ANIMATE_CSS_OUT = ['fadeOut','fadeOutDown','fadeOutLeft','fadeOutRight','fadeOutUp','bounceOut','bounceOutDown','bounceOutLeft','bounceOutRight','bounceOutUp','zoomOut','zoomOutDown','zoomOutLeft','zoomOutRight','zoomOutUp','slideOutDown','slideOutLeft','slideOutRight','slideOutUp','flipOutX','flipOutY','backOutDown','backOutLeft','backOutRight','backOutUp','rotateOut'];

async function loadOverlayConfig() {
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) return;
  const cfg = await r.json();
  const oi = cfg.overlay_image || {};
  const ig = cfg.image_generation || {};
  const container = document.getElementById('overlay-config-container');
  container.textContent = '';

  // Image generation section
  const igSection = document.createElement('div');
  igSection.className = 'overlay-section';
  const igTitle = document.createElement('h3');
  igTitle.textContent = 'Génération d\'images';
  igSection.appendChild(igTitle);

  function makeFormRow(labelText, inputEl) {
    const row = document.createElement('div');
    row.className = 'form-row';
    const lbl = document.createElement('label');
    lbl.textContent = labelText;
    row.appendChild(lbl);
    row.appendChild(inputEl);
    return row;
  }

  function makeSelect(id, options, selected) {
    const sel = document.createElement('select');
    sel.id = id;
    sel.className = 'neo-select';
    options.forEach(function(o) {
      const opt = document.createElement('option');
      opt.value = o;
      opt.textContent = o;
      if (o === selected) opt.selected = true;
      sel.appendChild(opt);
    });
    return sel;
  }

  igSection.appendChild(makeFormRow('Modèle', makeSelect('ig-model', ['gpt-image-1.5','gpt-image-1','gpt-image-1-mini'], ig.model)));
  igSection.appendChild(makeFormRow('Qualité', makeSelect('ig-quality', ['low','medium','high'], ig.quality)));
  igSection.appendChild(makeFormRow('Taille', makeSelect('ig-size', ['1024x1024','1024x1536','1536x1024'], ig.size)));
  igSection.appendChild(makeFormRow('Format', makeSelect('ig-format', ['png','jpeg','webp'], ig.format)));
  igSection.appendChild(makeFormRow('Background', makeSelect('ig-background', ['auto','transparent','opaque'], ig.background)));

  // Daily limit
  const dlRow = document.createElement('div');
  dlRow.className = 'form-row';
  const dlLabel = document.createElement('label');
  dlLabel.textContent = 'Limite/jour (global)';
  dlRow.appendChild(dlLabel);
  const dlInput = document.createElement('input');
  dlInput.type = 'number'; dlInput.id = 'ig-daily-limit'; dlInput.className = 'neo-input';
  dlInput.value = ig.daily_limit; dlInput.style.width = '80px';
  dlRow.appendChild(dlInput);
  const dlHint = document.createElement('span');
  dlHint.style.color = 'rgba(255,255,255,0.35)'; dlHint.style.fontSize = '0.78rem'; dlHint.textContent = '-1 = illimité';
  dlRow.appendChild(dlHint);
  igSection.appendChild(dlRow);

  // Per user limit
  const puRow = document.createElement('div');
  puRow.className = 'form-row';
  const puLabel = document.createElement('label');
  puLabel.textContent = 'Limite/jour (par user)';
  puRow.appendChild(puLabel);
  const puInput = document.createElement('input');
  puInput.type = 'number'; puInput.id = 'ig-per-user-limit'; puInput.className = 'neo-input';
  puInput.value = ig.per_user_limit; puInput.style.width = '80px';
  puRow.appendChild(puInput);
  const puHint = document.createElement('span');
  puHint.style.color = 'rgba(255,255,255,0.35)'; puHint.style.fontSize = '0.78rem'; puHint.textContent = '-1 = illimité';
  puRow.appendChild(puHint);
  igSection.appendChild(puRow);

  const costEst = document.createElement('div');
  costEst.className = 'form-row';
  costEst.id = 'ig-cost-estimate';
  costEst.style.color = 'var(--accent)';
  costEst.style.fontWeight = '600';
  costEst.style.fontSize = '0.85rem';
  igSection.appendChild(costEst);

  const igSaveBtn = document.createElement('button');
  igSaveBtn.className = 'neo-btn';
  igSaveBtn.textContent = 'Sauvegarder';
  igSaveBtn.onclick = saveImageGenConfig;
  igSection.appendChild(igSaveBtn);

  container.appendChild(igSection);

  // Overlay image section
  const oiSection = document.createElement('div');
  oiSection.className = 'overlay-section';
  const oiTitle = document.createElement('h3');
  oiTitle.textContent = 'Overlay Image (Twitch)';
  oiSection.appendChild(oiTitle);

  // Enabled checkbox
  const enRow = document.createElement('div');
  enRow.className = 'form-row';
  const enLabel = document.createElement('label');
  enLabel.textContent = 'Activé';
  enRow.appendChild(enLabel);
  const enCheck = document.createElement('input');
  enCheck.type = 'checkbox'; enCheck.id = 'oi-enabled';
  if (oi.enabled) enCheck.checked = true;
  enRow.appendChild(enCheck);
  oiSection.appendChild(enRow);

  // Command
  const cmdRow = document.createElement('div');
  cmdRow.className = 'form-row';
  const cmdLabel = document.createElement('label');
  cmdLabel.textContent = 'Commande Twitch';
  cmdRow.appendChild(cmdLabel);
  const cmdInput = document.createElement('input');
  cmdInput.type = 'text'; cmdInput.id = 'oi-command'; cmdInput.className = 'neo-input';
  cmdInput.value = oi.command || '!image'; cmdInput.style.width = '120px';
  cmdRow.appendChild(cmdInput);
  oiSection.appendChild(cmdRow);

  // Duration slider
  const durRow = document.createElement('div');
  durRow.className = 'form-row';
  const durLabel = document.createElement('label');
  durLabel.textContent = 'Durée affichage (s)';
  durRow.appendChild(durLabel);
  const durRange = document.createElement('input');
  durRange.type = 'range'; durRange.id = 'oi-duration';
  durRange.min = '5'; durRange.max = '60'; durRange.value = oi.display_duration || 15;
  durRow.appendChild(durRange);
  const durVal = document.createElement('span');
  durVal.id = 'oi-duration-val'; durVal.textContent = (oi.display_duration || 15) + 's';
  durRow.appendChild(durVal);
  oiSection.appendChild(durRow);

  // Animation in
  oiSection.appendChild(makeFormRow('Animation entrée', makeSelect('oi-anim-in', ANIMATE_CSS_IN, oi.animation_in)));

  // Animation out
  oiSection.appendChild(makeFormRow('Animation sortie', makeSelect('oi-anim-out', ANIMATE_CSS_OUT, oi.animation_out)));

  // Animation duration slider
  const adRow = document.createElement('div');
  adRow.className = 'form-row';
  const adLabel = document.createElement('label');
  adLabel.textContent = 'Durée animation (s)';
  adRow.appendChild(adLabel);
  const adRange = document.createElement('input');
  adRange.type = 'range'; adRange.id = 'oi-anim-duration';
  adRange.min = '0.5'; adRange.max = '3'; adRange.step = '0.1'; adRange.value = oi.animation_duration || 1;
  adRow.appendChild(adRange);
  const adVal = document.createElement('span');
  adVal.id = 'oi-anim-duration-val'; adVal.textContent = (oi.animation_duration || 1) + 's';
  adRow.appendChild(adVal);
  oiSection.appendChild(adRow);

  // Filter
  oiSection.appendChild(makeFormRow('Filtre images', makeSelect('oi-filter', ['all','top','recent'], oi.random_filter)));

  // Buttons row
  const btnRow = document.createElement('div');
  btnRow.className = 'form-row';
  const oiSaveBtn = document.createElement('button');
  oiSaveBtn.className = 'neo-btn';
  oiSaveBtn.textContent = 'Sauvegarder';
  oiSaveBtn.onclick = saveOverlayImageConfig;
  btnRow.appendChild(oiSaveBtn);
  const oiTestBtn = document.createElement('button');
  oiTestBtn.className = 'neo-btn';
  oiTestBtn.textContent = 'Tester';
  oiTestBtn.style.marginLeft = '8px';
  oiTestBtn.onclick = testOverlayImage;
  btnRow.appendChild(oiTestBtn);
  oiSection.appendChild(btnRow);

  container.appendChild(oiSection);

  updateCostEstimate();
  document.getElementById('ig-model')?.addEventListener('change', updateCostEstimate);
  document.getElementById('ig-quality')?.addEventListener('change', updateCostEstimate);
  document.getElementById('ig-size')?.addEventListener('change', updateCostEstimate);

  durRange.addEventListener('input', function() { durVal.textContent = durRange.value + 's'; });
  adRange.addEventListener('input', function() { adVal.textContent = adRange.value + 's'; });
}

async function updateCostEstimate() {
  const model = document.getElementById('ig-model')?.value;
  const quality = document.getElementById('ig-quality')?.value;
  const size = document.getElementById('ig-size')?.value;
  const r = await fetch('/api/public/gallery/estimate-cost?model=' + model + '&quality=' + quality + '&size=' + size);
  if (r.ok) {
    const data = await r.json();
    const el = document.getElementById('ig-cost-estimate');
    if (el) el.textContent = 'Coût estimé : $' + data.cost_usd.toFixed(4) + ' par image';
  }
}

async function saveImageGenConfig() {
  const body = { image_generation: {
    model: document.getElementById('ig-model').value,
    quality: document.getElementById('ig-quality').value,
    size: document.getElementById('ig-size').value,
    format: document.getElementById('ig-format').value,
    background: document.getElementById('ig-background').value,
    daily_limit: parseInt(document.getElementById('ig-daily-limit').value),
    per_user_limit: parseInt(document.getElementById('ig-per-user-limit').value),
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config image sauvegardée', 'success');
}

async function saveOverlayImageConfig() {
  const body = { overlay_image: {
    enabled: document.getElementById('oi-enabled').checked,
    command: document.getElementById('oi-command').value,
    display_duration: parseInt(document.getElementById('oi-duration').value),
    animation_in: document.getElementById('oi-anim-in').value,
    animation_out: document.getElementById('oi-anim-out').value,
    animation_duration: parseFloat(document.getElementById('oi-anim-duration').value),
    random_filter: document.getElementById('oi-filter').value,
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config overlay sauvegardée', 'success');
}

async function testOverlayImage() {
  const r = await apiFetch('/api/admin/overlay-image/test', { method: 'POST' });
  if (r && r.ok) toast('Image envoyée à l\'overlay', 'success');
  else if (r && r.status === 404) toast('Aucune image dans la galerie', 'error');
  else if (r && r.status === 429) toast('Une image est déjà affichée', 'error');
}

// ── Slash Commands Autocomplete ───────────────────────────────────────────────

const SLASH_COMMANDS = [
  { name: '/imagine', desc: 'Générer une image', adminOnly: false },
  { name: '/scan', desc: 'Scanner la mémoire du chat', adminOnly: true },
];
let _slashSelectedIdx = -1;

function setupSlashAutocomplete() {
  const chatInput = document.getElementById('chat-input');
  if (!chatInput) return;

  let popup = document.getElementById('slash-popup');
  if (!popup) {
    popup = document.createElement('div');
    popup.id = 'slash-popup';
    popup.className = 'slash-autocomplete';
    chatInput.parentElement.style.position = 'relative';
    chatInput.parentElement.insertBefore(popup, chatInput);
  }

  chatInput.addEventListener('input', function() {
    const val = chatInput.value;
    if (!val.startsWith('/')) { hideSlashPopup(); return; }
    const prefix = val.split(' ')[0].toLowerCase();
    if (val.includes(' ') && val.split(' ').length > 1) { hideSlashPopup(); return; }
    const isAdmin = !!getToken();
    const filtered = SLASH_COMMANDS.filter(function(c) { return c.name.startsWith(prefix) && (!c.adminOnly || isAdmin); });
    if (filtered.length === 0) { hideSlashPopup(); return; }
    renderSlashPopup(filtered);
  });

  chatInput.addEventListener('keydown', function(e) {
    const popup = document.getElementById('slash-popup');
    if (!popup || !popup.classList.contains('visible')) return;
    const items = popup.querySelectorAll('.slash-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _slashSelectedIdx = Math.min(_slashSelectedIdx + 1, items.length - 1);
      items.forEach(function(it, i) { it.classList.toggle('selected', i === _slashSelectedIdx); });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _slashSelectedIdx = Math.max(_slashSelectedIdx - 1, 0);
      items.forEach(function(it, i) { it.classList.toggle('selected', i === _slashSelectedIdx); });
    } else if (e.key === 'Tab') {
      e.preventDefault();
      if (_slashSelectedIdx >= 0 && _slashSelectedIdx < items.length) {
        selectSlashCommand(items[_slashSelectedIdx].dataset.name);
      } else if (items.length === 1) {
        selectSlashCommand(items[0].dataset.name);
      }
    }
  });
}

function renderSlashPopup(commands) {
  const popup = document.getElementById('slash-popup');
  if (!popup) return;
  _slashSelectedIdx = -1;
  popup.textContent = '';
  commands.forEach(function(c) {
    const item = document.createElement('div');
    item.className = 'slash-item';
    item.dataset.name = c.name;
    item.onclick = function() { selectSlashCommand(c.name); };
    const nameSpan = document.createElement('span');
    nameSpan.className = 'slash-item-name';
    nameSpan.textContent = c.name;
    const descSpan = document.createElement('span');
    descSpan.className = 'slash-item-desc';
    descSpan.textContent = c.desc;
    item.appendChild(nameSpan);
    item.appendChild(descSpan);
    popup.appendChild(item);
  });
  popup.classList.add('visible');
}

function hideSlashPopup() {
  const popup = document.getElementById('slash-popup');
  if (popup) popup.classList.remove('visible');
  _slashSelectedIdx = -1;
}

function selectSlashCommand(name) {
  const chatInput = document.getElementById('chat-input');
  if (chatInput) {
    chatInput.value = name + ' ';
    chatInput.focus();
  }
  hideSlashPopup();
}

// ── Chat Image Embeds ─────────────────────────────────────────────────────────

function chatAppendImageGenerating(data) {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  const div = document.createElement('div');
  div.className = 'chat-msg wally';
  div.id = 'chat-embed-' + data.id;

  const bubble = document.createElement('div');
  bubble.className = 'chat-msg-bubble';
  const embed = document.createElement('div');
  embed.className = 'chat-image-embed';
  const loading = document.createElement('div');
  loading.className = 'embed-loading';
  const icon = document.createElement('div');
  icon.style.fontSize = '2rem';
  icon.style.marginBottom = '8px';
  icon.textContent = '🎨';
  loading.appendChild(icon);
  const msg = document.createElement('div');
  msg.textContent = 'Génération en cours...';
  loading.appendChild(msg);
  const promptDiv = document.createElement('div');
  promptDiv.style.fontSize = '0.75rem';
  promptDiv.style.color = 'rgba(255,255,255,0.35)';
  promptDiv.style.marginTop = '4px';
  promptDiv.textContent = data.prompt || '';
  loading.appendChild(promptDiv);
  embed.appendChild(loading);
  bubble.appendChild(embed);
  div.appendChild(bubble);
  el.appendChild(div);
}

function chatReplaceImageResult(data) {
  const existing = document.getElementById('chat-embed-' + data.id);
  const dateStr = data.created_at ? new Date(data.created_at + 'Z').toLocaleString('fr-FR') : '';

  const wrapper = document.createElement('div');
  wrapper.className = 'chat-msg wally';
  wrapper.id = 'chat-embed-' + data.id;

  const bubble = document.createElement('div');
  bubble.className = 'chat-msg-bubble';
  const embed = document.createElement('div');
  embed.className = 'chat-image-embed';

  const imgEl = document.createElement('img');
  imgEl.src = '/api/public/gallery/' + data.image_id + '/image';
  imgEl.alt = data.title || '';
  imgEl.style.cursor = 'pointer';
  imgEl.onclick = function() { openLightbox(data.image_id); };
  embed.appendChild(imgEl);

  const infoDiv = document.createElement('div');
  infoDiv.className = 'embed-info';
  const titleDiv = document.createElement('div');
  titleDiv.className = 'embed-title';
  titleDiv.id = 'chat-embed-title-' + data.image_id;
  titleDiv.textContent = data.title || 'Sans titre';
  infoDiv.appendChild(titleDiv);
  const promptDiv = document.createElement('div');
  promptDiv.className = 'embed-prompt';
  promptDiv.textContent = data.prompt || '';
  infoDiv.appendChild(promptDiv);
  const footerDiv = document.createElement('div');
  footerDiv.className = 'embed-footer';
  footerDiv.textContent = (data.username || '') + ' — ' + dateStr;
  infoDiv.appendChild(footerDiv);
  embed.appendChild(infoDiv);

  const actions = document.createElement('div');
  actions.className = 'embed-actions';
  const flameBtn = document.createElement('button');
  flameBtn.className = 'flame-btn';
  flameBtn.onclick = function() { toggleFlameEmbed(data.image_id, flameBtn); };
  flameBtn.appendChild(document.createTextNode('🔥 '));
  const vSpan = document.createElement('span');
  vSpan.textContent = '0';
  flameBtn.appendChild(vSpan);
  actions.appendChild(flameBtn);
  embed.appendChild(actions);

  bubble.appendChild(embed);
  wrapper.appendChild(bubble);

  if (existing) {
    existing.replaceWith(wrapper);
  } else {
    const container = document.getElementById('chat-messages');
    if (container) container.appendChild(wrapper);
  }
}

function chatReplaceImageCancelled(data) {
  const existing = document.getElementById('chat-embed-' + data.id);
  if (!existing) return;
  existing.textContent = '';
  const bubble = document.createElement('div');
  bubble.className = 'chat-msg-bubble';
  const embed = document.createElement('div');
  embed.className = 'chat-image-embed';
  const infoDiv = document.createElement('div');
  infoDiv.className = 'embed-info';
  const titleDiv = document.createElement('div');
  titleDiv.className = 'embed-title';
  titleDiv.style.color = 'var(--c-anger)';
  titleDiv.textContent = 'Génération annulée';
  infoDiv.appendChild(titleDiv);
  const reasonDiv = document.createElement('div');
  reasonDiv.className = 'embed-prompt';
  reasonDiv.textContent = data.reason || 'Erreur inconnue';
  infoDiv.appendChild(reasonDiv);
  embed.appendChild(infoDiv);
  bubble.appendChild(embed);
  existing.appendChild(bubble);
}

function chatUpdateVoteState(data) {
  const embedEl = document.getElementById('chat-embed-' + data.id);
  if (!embedEl) return;
  const btn = embedEl.querySelector('.flame-btn');
  if (btn) {
    btn.classList.toggle('active', data.voted);
    const span = btn.querySelector('span');
    if (span && data.votes !== undefined) span.textContent = data.votes;
  }
}

function chatUpdateEmbedTitle(data) {
  const el = document.getElementById('chat-embed-title-' + data.image_id);
  if (el) el.textContent = data.title || 'Sans titre';
}

async function toggleFlameEmbed(imageId, btn) {
  const r = await fetch('/api/public/gallery/' + imageId + '/vote', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + (getChatJwt() || '') }
  });
  if (!r.ok) {
    if (r.status === 401) toast('Connectez-vous au chat pour voter', 'error');
    return;
  }
  const data = await r.json();
  btn.classList.toggle('active', data.voted);
  const detail = await fetch('/api/public/gallery/' + imageId);
  if (detail.ok) {
    const img = await detail.json();
    btn.querySelector('span').textContent = img.votes || 0;
  }
}

// ── Actions Tab ──────────────────────────────────────────────────────────────

let _actionsSubTab = 'tasks';

function renderActionsTab() {
  const el = document.getElementById('tab-admin-actions');
  if (!el) return;

  // Build sub-nav + content containers
  var subnavHtml = '<div class="actions-subnav">'
    + '<button class="actions-subnav-pill' + (_actionsSubTab === 'tasks' ? ' active' : '') + '" onclick="switchActionsSubTab(\'tasks\')">Tâches</button>'
    + '<button class="actions-subnav-pill' + (_actionsSubTab === 'permissions' ? ' active' : '') + '" onclick="switchActionsSubTab(\'permissions\')">Permissions</button>'
    + '</div>';

  el.textContent = '';
  el.insertAdjacentHTML('beforeend', subnavHtml);

  var tasksDiv = document.createElement('div');
  tasksDiv.id = 'actions-tasks-content';
  tasksDiv.className = 'actions-subcontent' + (_actionsSubTab === 'tasks' ? ' active' : '');
  el.appendChild(tasksDiv);

  var permsDiv = document.createElement('div');
  permsDiv.id = 'actions-perms-content';
  permsDiv.className = 'actions-subcontent' + (_actionsSubTab === 'permissions' ? ' active' : '');
  el.appendChild(permsDiv);

  if (_actionsSubTab === 'tasks') {
    loadActionTasks();
  } else {
    loadActionPermissions();
  }
}

function switchActionsSubTab(tab) {
  _actionsSubTab = tab;
  renderActionsTab();
}

function _buildActionCard(t) {
  var statusClass = t.status || 'active';
  var isPaused = t.status === 'paused';
  var isTerminal = t.status === 'completed' || t.status === 'cancelled';
  var nextRun = t.next_run_at ? new Date(t.next_run_at).toLocaleString('fr-FR') : '—';
  var execInfo = t.execution_count + (t.max_executions ? '/' + t.max_executions : '');
  var creator = escHtml(t.creator_id || '?');
  var platform = t.creator_platform || '';

  var card = document.createElement('div');
  card.className = 'action-card';

  // Header
  var header = document.createElement('div');
  header.className = 'action-card-header';
  var typeBadge = document.createElement('span');
  typeBadge.className = 'action-type-badge';
  typeBadge.textContent = t.action_type;
  var statusBadge = document.createElement('span');
  statusBadge.className = 'action-status-badge ' + statusClass;
  statusBadge.textContent = t.status;
  header.appendChild(typeBadge);
  header.appendChild(statusBadge);
  card.appendChild(header);

  // Description
  var desc = document.createElement('div');
  desc.className = 'action-card-desc';
  desc.textContent = t.description || 'Pas de description';
  card.appendChild(desc);

  // Meta
  var meta = document.createElement('div');
  meta.className = 'action-card-meta';

  var rows = [
    ['Créateur', creator + ' (' + escHtml(platform) + ')'],
    ['Prochaine exécution', nextRun],
    ['Exécutions', execInfo],
    ['Type planification', t.schedule_type || '—'],
  ];
  if (t.last_error) {
    rows.push(['Dernière erreur', t.last_error]);
  }
  rows.forEach(function(pair) {
    var row = document.createElement('div');
    row.className = 'action-card-meta-row';
    var label = document.createElement('span');
    label.className = 'action-meta-label';
    label.textContent = pair[0];
    var val = document.createElement('span');
    val.textContent = pair[1];
    if (pair[0] === 'Dernière erreur') val.style.color = '#ef4444';
    row.appendChild(label);
    row.appendChild(val);
    meta.appendChild(row);
  });
  card.appendChild(meta);

  // Action buttons (only for non-terminal tasks)
  if (!isTerminal) {
    var actions = document.createElement('div');
    actions.className = 'action-card-actions';

    var pauseBtn = document.createElement('button');
    pauseBtn.className = 'action-btn';
    pauseBtn.textContent = isPaused ? '▶ Reprendre' : '⏸ Pause';
    pauseBtn.addEventListener('click', function() { actionTaskTogglePause(t.id, isPaused); });
    actions.appendChild(pauseBtn);

    var execBtn = document.createElement('button');
    execBtn.className = 'action-btn action-btn-exec';
    execBtn.textContent = '⚡ Exécuter';
    execBtn.addEventListener('click', function() { actionTaskExecuteNow(t.id); });
    actions.appendChild(execBtn);

    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'action-btn action-btn-cancel';
    cancelBtn.textContent = '✕ Annuler';
    cancelBtn.addEventListener('click', function() { actionTaskCancel(t.id); });
    actions.appendChild(cancelBtn);

    card.appendChild(actions);
  }

  return card;
}

async function loadActionTasks() {
  var container = document.getElementById('actions-tasks-content');
  if (!container) return;
  container.textContent = '';
  var loading = document.createElement('div');
  loading.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
  loading.textContent = 'Chargement...';
  container.appendChild(loading);

  var r = await apiFetch('/api/actions/tasks');
  if (!r || !r.ok) {
    loading.textContent = 'Erreur de chargement';
    return;
  }
  var data = await r.json();
  var tasks = data.tasks || [];

  container.textContent = '';

  if (tasks.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
    empty.textContent = 'Aucune tâche programmée';
    container.appendChild(empty);
    return;
  }

  var grid = document.createElement('div');
  grid.className = 'action-grid';
  tasks.forEach(function(t) {
    grid.appendChild(_buildActionCard(t));
  });
  container.appendChild(grid);
}

async function actionTaskTogglePause(id, isPaused) {
  var endpoint = isPaused ? 'resume' : 'pause';
  var r = await apiFetch('/api/actions/tasks/' + id + '/' + endpoint, { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur ' + endpoint, 'error'); return; }
  toast(isPaused ? 'Tâche reprise' : 'Tâche en pause', 'success');
  loadActionTasks();
}

async function actionTaskExecuteNow(id) {
  var r = await apiFetch('/api/actions/tasks/' + id + '/execute', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur exécution', 'error'); return; }
  toast('Exécution lancée', 'success');
  loadActionTasks();
}

async function actionTaskCancel(id) {
  if (!confirm('Annuler cette tâche ?')) return;
  var r = await apiFetch('/api/actions/tasks/' + id + '/cancel', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur annulation', 'error'); return; }
  toast('Tâche annulée', 'success');
  loadActionTasks();
}

var DISCORD_ROLES = ['everyone', 'subscriber', 'moderator', 'admin'];
var TWITCH_ROLES = ['everyone', 'subscriber', 'vip', 'moderator', 'admin'];

function _buildPermRow(p) {
  var actionType = p.action_type;
  var enabled = p.enabled !== false && p.enabled !== 0;

  var tr = document.createElement('tr');

  // Action name
  var tdName = document.createElement('td');
  tdName.className = 'action-perm-name';
  tdName.textContent = actionType;
  tr.appendChild(tdName);

  // Enabled toggle
  var tdEnabled = document.createElement('td');
  var toggleLabel = document.createElement('label');
  toggleLabel.className = 'action-toggle';
  var checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = enabled;
  checkbox.addEventListener('change', function() { updateActionPerm(actionType, 'enabled', this.checked); });
  var trackSpan = document.createElement('span');
  trackSpan.className = 'action-toggle-track';
  var thumbSpan = document.createElement('span');
  thumbSpan.className = 'action-toggle-thumb';
  trackSpan.appendChild(thumbSpan);
  toggleLabel.appendChild(checkbox);
  toggleLabel.appendChild(trackSpan);
  tdEnabled.appendChild(toggleLabel);
  tr.appendChild(tdEnabled);

  // Discord role dropdown
  var tdDiscord = document.createElement('td');
  var discordSelect = document.createElement('select');
  discordSelect.className = 'neo-select action-perm-select';
  DISCORD_ROLES.forEach(function(role) {
    var opt = document.createElement('option');
    opt.value = role;
    opt.textContent = role;
    if (p.min_role_discord === role) opt.selected = true;
    discordSelect.appendChild(opt);
  });
  discordSelect.addEventListener('change', function() { updateActionPerm(actionType, 'min_role_discord', this.value); });
  tdDiscord.appendChild(discordSelect);
  tr.appendChild(tdDiscord);

  // Twitch role dropdown
  var tdTwitch = document.createElement('td');
  var twitchSelect = document.createElement('select');
  twitchSelect.className = 'neo-select action-perm-select';
  TWITCH_ROLES.forEach(function(role) {
    var opt = document.createElement('option');
    opt.value = role;
    opt.textContent = role;
    if (p.min_role_twitch === role) opt.selected = true;
    twitchSelect.appendChild(opt);
  });
  twitchSelect.addEventListener('change', function() { updateActionPerm(actionType, 'min_role_twitch', this.value); });
  tdTwitch.appendChild(twitchSelect);
  tr.appendChild(tdTwitch);

  return tr;
}

async function loadActionPermissions() {
  var container = document.getElementById('actions-perms-content');
  if (!container) return;
  container.textContent = '';
  var loading = document.createElement('div');
  loading.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
  loading.textContent = 'Chargement...';
  container.appendChild(loading);

  var r = await apiFetch('/api/actions/permissions');
  if (!r || !r.ok) {
    loading.textContent = 'Erreur de chargement';
    return;
  }
  var data = await r.json();
  var perms = data.permissions || [];

  container.textContent = '';

  if (perms.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
    empty.textContent = 'Aucune permission configurée';
    container.appendChild(empty);
    return;
  }

  var wrap = document.createElement('div');
  wrap.className = 'action-perms-table-wrap';
  var table = document.createElement('table');
  table.className = 'action-perms-table';

  var thead = document.createElement('thead');
  var headerRow = document.createElement('tr');
  ['Action', 'Activé', 'Rôle Discord', 'Rôle Twitch'].forEach(function(text) {
    var th = document.createElement('th');
    th.textContent = text;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  var tbody = document.createElement('tbody');
  perms.forEach(function(p) {
    tbody.appendChild(_buildPermRow(p));
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  container.appendChild(wrap);
}

async function updateActionPerm(actionType, field, value) {
  var body = {};
  body[field] = value;
  var r = await apiFetch('/api/actions/permissions/' + encodeURIComponent(actionType), {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!r || !r.ok) { toast('Erreur mise à jour permission', 'error'); return; }
  toast('Permission mise à jour', 'success');
}
