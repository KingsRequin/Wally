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

// ── Mode & tabs ───────────────────────────────────────────────────────────────

function toggleMode() {
  switchMode(currentMode === 'public' ? 'admin' : 'public');
}

function switchMode(mode, restoreTab = null) {
  if (mode === 'admin') {
    if (!getToken()) { showAuthModal(); return; }
  }
  currentMode = mode;

  const adminNav = document.getElementById('nav-admin');
  const divider = document.getElementById('sidebar-divider');
  const modeBtn = document.getElementById('sidebar-mode-toggle');

  adminNav.style.display = mode === 'admin' ? 'flex' : 'none';
  if (divider) divider.style.display = mode === 'admin' ? 'block' : 'none';
  if (modeBtn) modeBtn.classList.toggle('active', mode === 'admin');

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
  if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
  if (tabId === 'admin-links') loadLinks();
  if (tabId === 'admin-costs') loadCosts();
  pollCostsBadge();
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
    clearToken();
    if (!_sessionExpiredFired) {
      _sessionExpiredFired = true;
      toast('Session expirée', 'error');
      switchMode('public');
    }
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
      if (data.type === 'links_analyzed') { loadLinks(); return; }
      if (data.type === 'link_accepted')  { loadLinks(); loadMemoryUsers(); return; }
      if (data.type === 'link_rejected')  { loadLinks(); return; }
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
  return String(str).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderMemoryTab() {
  document.getElementById('tab-memory').innerHTML = `
    <div class="mem-toolbar">
      <span style="font-size:0.7rem;color:var(--text-muted);letter-spacing:2px;white-space:nowrap">CHERCHER</span>
      <button class="btn" onclick="syncMemoryUsers()"
              style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">↻ SYNC</button>
      <button class="btn" onclick="resolveUsernames()"
              style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">👤 RÉSOUDRE NOMS</button>
      <input type="text" id="mem-search" placeholder="Recherche dans tous les souvenirs…"
             oninput="onMemSearch(this.value)"
             style="flex:1;max-width:320px" aria-label="Recherche mémoire">
    </div>
    <div class="mem-layout">
      <div class="mem-sidebar">
        <div class="mem-sidebar-filter">
          <input type="text" id="mem-user-filter" placeholder="Filtrer users…"
                 oninput="onUserFilter(this.value)"
                 style="width:100%;font-size:0.8rem" aria-label="Filtrer utilisateurs">
        </div>
        <div id="mem-user-list" class="mem-user-list"></div>
      </div>
      <div id="mem-detail" class="mem-detail">
        <div style="padding:16px;color:var(--text-muted);font-size:0.85rem">
          Sélectionne un utilisateur pour voir ses souvenirs.
        </div>
      </div>
    </div>
  `;
  loadMemoryUsers();
}

let _selectedMemUser = null;
let _selectedMemUsername = null;

async function loadMemoryUsers(filter = '') {
  const url = '/api/admin/memory/users' + (filter ? `?q=${encodeURIComponent(filter)}` : '');
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
    const linkedBadge = (u.linked_accounts || []).map(a =>
      `<span style="font-size:0.58rem;background:rgba(0,212,255,0.1);color:var(--accent);border:1px solid rgba(0,212,255,0.25);padding:1px 5px;border-radius:4px;margin-left:4px" title="Lié à ${escAttr(a.alias_id)}">🔗 ${escHtml(a.alias_username)}</span>`
    ).join('');
    return `
    <div class="mem-user-item ${selected ? 'selected' : ''}"
         data-uid="${escAttr(u.user_id)}"
         onclick="selectMemUser('${escAttr(u.user_id)}','${escAttr(u.username || '')}')">
      <span style="font-size:0.62rem;color:var(--text-dim);display:block">${escHtml(u.platform)} · ${escHtml(lastSeen)}</span>
      <span style="font-size:0.82rem">${escHtml(u.username || u.user_id.split(':').slice(1).join(':') || u.user_id)}${linkedBadge}</span>
      <span style="font-size:0.62rem;color:${trustColor};display:block">trust: ${u.trust_score !== undefined ? u.trust_score.toFixed(2) : '—'}</span>
    </div>`;
  }).join('');
}

async function syncMemoryUsers() {
  const r = await apiFetch('/api/admin/memory/sync', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur sync', 'error'); return; }
  const { synced } = await r.json();
  toast(`${synced} utilisateur(s) importé(s)`, 'success');
  const filter = document.getElementById('mem-user-filter')?.value || '';
  loadMemoryUsers(filter);
}

async function resolveUsernames() {
  const r = await apiFetch('/api/admin/memory/resolve-usernames', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur résolution', 'error'); return; }
  const { resolved } = await r.json();
  toast(`${resolved} nom(s) résolu(s)`, 'success');
  const filter = document.getElementById('mem-user-filter')?.value || '';
  loadMemoryUsers(filter);
}

async function selectMemUser(userId, username) {
  _selectedMemUser = userId;
  _selectedMemUsername = username || null;
  document.querySelectorAll('.mem-user-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.uid === userId);
  });
  await loadUserMemories(userId);
}

async function loadUserMemories(userId) {
  const r = await apiFetch('/api/admin/memory/users/' + encodeURIComponent(userId));
  if (!r || !r.ok) return;
  const { memories } = await r.json();
  renderMemories(userId, memories, _selectedMemUsername);
}

function renderMemories(userId, memories, username = null) {
  const el = document.getElementById('mem-detail');
  if (!el) return;
  el.innerHTML = `
    <div style="padding:10px 16px;border-bottom:1px solid var(--glass-border);display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:0.7rem;color:var(--text-muted);letter-spacing:1px">${username ? escHtml(username) + ' (' + escHtml(userId) + ')' : escHtml(userId)} — ${memories.length} souvenir(s)</span>
      <button class="btn btn-danger" onclick="deleteAllMemories('${escAttr(userId)}')"
              style="font-size:0.72rem;padding:4px 10px">🗑 TOUT SUPPRIMER</button>
    </div>
    <div style="padding:12px">
      ${memories.length === 0
        ? '<div style="color:rgba(255,255,255,0.45);font-size:0.85rem">Aucun souvenir.</div>'
        : memories.map(m => {
          const platform = m.source_platform || (m.source ? m.source.split(':')[0] : '');
          const platformColors = { discord: '#5865F2', twitch: '#9146FF' };
          const platformColor = platformColors[platform] || 'rgba(6,182,212,0.7)';
          const platformSvg = PLATFORM_ICONS[platform] || '';
          const platformBadge = platformSvg
            ? `<span style="display:inline-flex;align-items:center;gap:4px;font-size:0.58rem;background:${platformColor}20;color:${platformColor};border:1px solid ${platformColor}40;padding:2px 6px;border-radius:4px;margin-right:4px" title="${escAttr(platform)}">${platformSvg}${platform}</span>`
            : '';
          const dateStr = m.updated_at || m.created_at;
          const dateBadge = dateStr
            ? `<span style="font-size:0.6rem;color:rgba(255,255,255,0.35);white-space:nowrap">${new Date(dateStr).toLocaleString('fr', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' })}</span>`
            : '';
          return `
          <div class="card" style="padding:12px 14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-start"
               id="mem-entry-${escAttr(m.id)}">
            <div style="flex:1;line-height:1.5">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">${platformBadge}${dateBadge}</div>
              <span style="font-size:0.82rem">${escHtml(m.memory)}</span>
            </div>
            <button onclick="deleteMemory('${escAttr(m.source || userId)}','${escAttr(m.id)}')"
                    style="background:none;border:none;color:var(--c-anger);cursor:pointer;font-size:1.1rem;margin-left:12px;flex-shrink:0;line-height:1" aria-label="Supprimer ce souvenir">&#10005;</button>
          </div>`;
        }).join('')
      }
    </div>
  `;
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
    document.getElementById('mem-detail').innerHTML =
      '<div style="padding:16px;color:var(--text-muted);font-size:0.85rem">Aucun souvenir.</div>';
    _selectedMemUser = null;
    const filter = document.getElementById('mem-user-filter')?.value || '';
    loadMemoryUsers(filter);
    toast('Mémoire supprimée', 'success');
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
      await loadUserMemories(_selectedMemUser);
    } else {
      document.getElementById('mem-detail').innerHTML =
        '<div style="padding:16px;color:var(--text-muted);font-size:0.85rem">Sélectionne un utilisateur.</div>';
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

// ── Liaisons de comptes ───────────────────────────────────────────────────────

let currentLinksTab = 'all';

function setLinksTab(tab, btn) {
  currentLinksTab = tab;
  document.querySelectorAll('#tab-admin-links .log-controls .btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  loadLinks();
}

async function loadLinks() {
  const params = new URLSearchParams();
  if (currentLinksTab !== 'all') params.set('status', currentLinksTab);
  params.set('_t', Date.now());
  const r = await apiFetch(`/api/admin/links?${params}`);
  if (!r || !r.ok) return;
  const data = await r.json();
  renderLinks(data.proposals);
}

function renderLinks(proposals) {
  const container = document.getElementById('links-list');
  if (!container) return;
  if (!proposals || proposals.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:0.85rem;padding:8px">Aucune liaison trouvée.</div>';
    return;
  }
  container.innerHTML = proposals.map(p => {
    const conf = Math.round(p.confidence * 100);
    const twitchRaw   = p.alias_id.replace('twitch:', '');
    const twitchUser  = p.alias_username || twitchRaw;
    const twitchUrl   = `https://www.twitch.tv/${p.alias_username || twitchRaw}`;
    const discordUser = p.canonical_username || p.canonical_id.replace('discord:', '');
    const statusBadge = {
      pending:  '<span style="background:rgba(255,160,0,0.15);color:#FFA000;border:1px solid rgba(255,160,0,0.3);padding:2px 6px;border-radius:var(--radius-xs);font-size:0.68rem;font-weight:600">EN ATTENTE</span>',
      accepted: '<span style="background:rgba(0,229,160,0.1);color:var(--c-online);border:1px solid rgba(0,229,160,0.25);padding:2px 6px;border-radius:var(--radius-xs);font-size:0.68rem;font-weight:600">ACCEPTÉ</span>',
      rejected: '<span style="background:rgba(255,77,77,0.1);color:var(--c-anger);border:1px solid rgba(255,77,77,0.25);padding:2px 6px;border-radius:var(--radius-xs);font-size:0.68rem;font-weight:600">REJETÉ</span>',
    }[p.status] || '';
    const actions = p.status === 'pending' ? `
      <button onclick="acceptLink(${p.id})" class="btn btn-success" style="font-size:0.72rem;padding:4px 10px">✓ Accepter</button>
      <button onclick="rejectLink(${p.id})" class="btn btn-danger"  style="font-size:0.72rem;padding:4px 10px">✗ Rejeter</button>
    ` : '';
    return `
      <div class="card" style="padding:12px 16px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;gap:12px">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          ${statusBadge}
          <span style="font-weight:700;color:var(--accent)">${conf}%</span>
          <span style="font-size:0.85rem">Discord: <strong>${escHtml(discordUser)}</strong></span>
          <span style="color:var(--text-dim)">↔</span>
          <span style="font-size:0.85rem">Twitch: <a href="${twitchUrl}" target="_blank" rel="noopener" style="color:var(--c-curiosity)">${escHtml(twitchUser)}</a></span>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0">${actions}</div>
      </div>
    `;
  }).join('');
}

async function createManualLink() {
  const discordId = document.getElementById('manual-link-discord').value.trim();
  const twitchUser = document.getElementById('manual-link-twitch').value.trim();
  if (!discordId || !twitchUser) { toast('Remplis les deux champs', 'error'); return; }
  const r = await apiFetch('/api/admin/links/manual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ canonical_id: `discord:${discordId}`, alias_id: `twitch:${twitchUser}` }),
  });
  if (r && r.ok) {
    toast('Liaison créée et fusionnée', 'success');
    document.getElementById('manual-link-discord').value = '';
    document.getElementById('manual-link-twitch').value = '';
    loadLinks();
    if (document.getElementById('mem-user-list')) {
      const filter = document.getElementById('mem-user-filter')?.value || '';
      loadMemoryUsers(filter);
    }
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur', 'error');
  }
}

async function analyzeLinks() {
  const r = await apiFetch('/api/admin/links/analyze', { method: 'POST' });
  if (r && r.ok) toast('Analyse déclenchée', 'success');
  else toast('Erreur analyse', 'error');
}

async function acceptLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/accept`, { method: 'POST' });
  if (r && r.ok) {
    toast('Liaison acceptée — mémoires fusionnées', 'success');
    if (document.getElementById('mem-user-list')) {
      const filter = document.getElementById('mem-user-filter')?.value || '';
      loadMemoryUsers(filter);
    }
  } else {
    toast('Erreur', 'error');
  }
  loadLinks();
}

async function rejectLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/reject`, { method: 'POST' });
  if (r && r.ok) toast('Liaison rejetée', 'success');
  else toast('Erreur', 'error');
  loadLinks();
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
  try {
    const r = await apiFetch('/api/admin/costs/alert');
    if (!r || !r.ok) return;
    const alert = await r.json();
    updateCostBadge(alert);
  } catch (e) { /* ignore */ }
}
