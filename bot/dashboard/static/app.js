// bot/dashboard/static/app.js
// WARNING: Auth token stored in localStorage — acceptable for personal use.
// For public exposure, replace with HttpOnly cookies.

'use strict';

// ── Constants ────────────────────────────────────────────────────────────────

const AUTH_KEY = 'wally_token';
const EMOTION_COLORS = {
  anger:    '#FF4D4D',
  joy:      '#FFD700',
  curiosity:'#00E5A0',
  sadness:  '#4DA6FF',
  boredom:  '#AAAAAA',
};
const EMOTION_EMOJIS = {
  anger: '😤', joy: '😊', sadness: '😢', curiosity: '🤔', boredom: '😴',
};
const EMOTION_LABELS = {
  anger: 'ANGER', joy: 'JOY', curiosity: 'CURIOSITY', sadness: 'SADNESS', boredom: 'BOREDOM',
};
const EMOTIONS = ['anger', 'joy', 'sadness', 'curiosity', 'boredom'];

// ── State ────────────────────────────────────────────────────────────────────

let currentMode = 'public';
let currentTab  = 'status';
let emotionSSE  = null;
let logSSE      = null;
let logFilter   = 'ALL';
let currentEmotions = {};
let currentGraphSince = null;  // null = 24h glissantes par défaut
let _graphMeta  = null;  // { history, tMin, tRange, PAD, gW, gH, W, H }
let _rafPending = false;

// ── Mode & tabs ───────────────────────────────────────────────────────────────

function switchMode(mode) {
  if (mode === 'admin') {
    if (!getToken()) { showAuthModal(); return; }
  }
  currentMode = mode;

  document.getElementById('btn-public').classList.toggle('active', mode === 'public');
  document.getElementById('btn-admin').classList.toggle('active',  mode === 'admin');
  document.getElementById('tabs-public').style.display = mode === 'public' ? 'flex' : 'none';
  document.getElementById('tabs-admin').style.display  = mode === 'admin'  ? 'flex' : 'none';

  const firstTab = mode === 'public' ? 'status' : 'admin-config';
  showTab(firstTab);

  if (mode === 'admin') {
    loadConfig();
    startLogSSE();
  } else {
    stopLogSSE();
  }
}

function showTab(tabId) {
  // Désactiver tous les onglets du mode courant
  const navId = currentMode === 'public' ? 'tabs-public' : 'tabs-admin';
  document.querySelectorAll(`#${navId} .tab-btn`).forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  const btn = document.querySelector(`#${navId} [data-tab="${tabId}"]`);
  if (btn) btn.classList.add('active');

  const content = document.getElementById(`tab-${tabId}`);
  if (content) content.classList.add('active');

  currentTab = tabId;

  // Chargements spécifiques par onglet
  if (tabId === 'status') {
    loadStreamStatus();
    requestAnimationFrame(() => loadEmotionHistory(currentGraphSince));
  }
  if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
  if (tabId === 'admin-links') loadLinks();
  if (tabId === 'admin-costs') loadCosts();
  pollCostsBadge();
  if (tabId === 'admin-logs') {
    // L'historique a pu être chargé quand le tab était caché (display:none → scrollHeight=0).
    // On force le scroll vers le bas au prochain frame, une fois l'élément visible.
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
  // Vérifier le token en appelant un endpoint admin
  const r = await fetch('/api/admin/config', { headers: { 'Authorization': `Bearer ${t}` } });
  if (r.ok) {
    saveToken(t);
    hideAuthModal();
    document.getElementById('token-input').value = '';
    switchMode('admin');
    toast('Accès admin accordé', 'success');
  } else {
    toast('Token invalide', 'error');
  }
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function apiFetch(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(url, { ...opts, headers });
  if (r.status === 401) { clearToken(); switchMode('public'); toast('Session expirée', 'error'); return null; }
  return r;
}

// ── Toasts ────────────────────────────────────────────────────────────────────

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Status polling ────────────────────────────────────────────────────────────

async function loadStatus() {
  const r = await fetch('/api/public/status');
  if (!r.ok) return;
  const d = await r.json();

  // Uptime
  const s = Math.floor(d.uptime_seconds);
  const days = Math.floor(s / 86400);
  const hrs  = Math.floor((s % 86400) / 3600);
  const mins = Math.floor((s % 3600) / 60);
  document.getElementById('uptime').textContent =
    days > 0 ? `${days}j ${hrs}h ${mins}m` : `${hrs}h ${mins}m`;

  // Dots
  const setDot = (id, online) => {
    const dot = document.getElementById(id);
    dot.classList.toggle('online',  online);
    dot.classList.toggle('offline', !online);
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
    row.innerHTML = `
      <span class="emotion-label" style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
      ${editable
        ? `<input type="range" class="emotion-slider" id="slider-${e}" min="0" max="1" step="0.01" value="0"
             oninput="document.getElementById('val-${e}').textContent=parseFloat(this.value).toFixed(2)"
             onchange="setEmotion('${e}', parseFloat(this.value))">`
        : `<div class="gauge-track"><div class="gauge-fill ${e}" id="fill-${e}"></div></div>`
      }
      <span class="gauge-val" id="val-${e}">0.00</span>
    `;
    c.appendChild(row);
  }
}

function updateEmotionGauges(emotions) {
  currentEmotions = emotions;
  for (const e of EMOTIONS) {
    const v = emotions[e] ?? 0;
    const fill = document.getElementById(`fill-${e}`);
    if (fill) fill.style.width = `${(v * 100).toFixed(1)}%`;
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
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='14' fill='${color}'/></svg>`;
  document.getElementById('favicon').href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function startEmotionSSE() {
  if (emotionSSE) emotionSSE.close();
  emotionSSE = new EventSource('/api/public/sse/emotions');
  emotionSSE.onmessage = (e) => {
    try { updateEmotionGauges(JSON.parse(e.data)); } catch {}
  };
  emotionSSE.onerror = () => {
    // Reconnexion automatique gérée par EventSource
  };
}

// ── Emotion canvas graph ──────────────────────────────────────────────────────

async function loadEmotionHistory(since) {
  const url = since != null
    ? `/api/public/emotions/history?since=${since}`
    : '/api/public/emotions/history';
  const r = await fetch(url);
  if (!r.ok) return;
  const { history } = await r.json();
  drawEmotionGraph(history);
  renderEmotionAverages(history);
}

function setGraphRange(range) {
  const now = Date.now() / 1000;
  const titles = {
    '1h':  '📈 DERNIÈRE HEURE',
    '24h': '📈 DERNIÈRES 24H',
    '7d':  '📈 7 DERNIERS JOURS',
    '30d': '📈 30 DERNIERS JOURS',
  };
  const offsets = {
    '1h':  3600,
    '24h': 86400,
    '7d':  7 * 86400,
    '30d': 30 * 86400,
  };
  currentGraphSince = now - offsets[range];

  // Mettre à jour le titre
  const titleEl = document.getElementById('graph-title');
  if (titleEl) titleEl.textContent = titles[range];

  // Mettre à jour l'état actif des boutons
  const btnLabels = { '1h': '1H', '24h': '24H', '7d': '7J', '30d': '30J' };
  document.querySelectorAll('.graph-range-btn').forEach(btn => {
    btn.classList.toggle('active', btn.textContent === btnLabels[range]);
  });

  loadEmotionHistory(currentGraphSince);
}

function renderEmotionAverages(history) {
  const el = document.getElementById('emotion-averages');
  if (!el) return;
  if (!history || history.length < 2) {
    el.style.display = 'none';
    return;
  }
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

  // Fond sombre (--bg-alt)
  ctx.fillStyle = '#0f0f1c';
  ctx.fillRect(0, 0, W, H);

  const PAD = { top: 10, bottom: 40, left: 4, right: 4 };
  const gW = W - PAD.left - PAD.right;
  const gH = H - PAD.top - PAD.bottom;

  const tMin = history[0].snapshot_at;
  const tMax = history[history.length - 1].snapshot_at;
  const tRange = tMax - tMin || 1;

  // Stocker pour le tooltip
  _graphMeta = { history, tMin, tRange, PAD, gW, gH, W, H };

  // Grille — 4 lignes horizontales à 25/50/75/100%
  ctx.lineWidth = 1;
  for (let pct = 0.25; pct <= 1.0; pct += 0.25) {
    const y = PAD.top + (1 - pct) * gH;
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(W - PAD.right, y);
    ctx.stroke();
  }

  // ── Ticks temporels ──────────────────────────────────────────────────────
  {
    const rawRange = tMax - tMin;
    let tickStep, tickMode;
    if (rawRange <= 1.1 * 3600) {
      tickStep = 600;    // toutes les 10 min
      tickMode = 'minute';
    } else if (rawRange <= 27 * 3600) {
      tickStep = 7200;   // toutes les 2h
      tickMode = 'hour';
    } else if (rawRange <= 8 * 86400) {
      tickStep = 86400;  // tous les jours
      tickMode = 'day';
    } else {
      tickStep = 172800; // tous les 2 jours
      tickMode = 'day';
    }

    let firstTick;
    if (tickMode === 'minute') {
      firstTick = Math.ceil(tMin / 600) * 600;
    } else if (tickMode === 'hour') {
      firstTick = Math.ceil(tMin / 3600) * 3600;
    } else {
      const d = new Date(tMin * 1000);
      d.setHours(0, 0, 0, 0);
      if (d.getTime() / 1000 < tMin) d.setDate(d.getDate() + 1);
      firstTick = d.getTime() / 1000;
    }

    ctx.globalAlpha = 1;
    for (let t = firstTick; t <= tMax; t += tickStep) {
      const x = PAD.left + ((t - tMin) / tRange) * gW;
      if (x < PAD.left + 40 || x > W - PAD.right - 40) continue;

      // Ligne verticale (même hauteur que la zone graphique)
      ctx.strokeStyle = 'rgba(255,255,255,0.12)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, PAD.top);
      ctx.lineTo(x, PAD.top + gH);
      ctx.stroke();

      // Label centré
      const label = tickMode === 'minute'
        ? new Date(t * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' })
        : tickMode === 'hour'
          ? new Date(t * 1000).toLocaleTimeString('fr', { hour: '2-digit' })
          : new Date(t * 1000).toLocaleDateString('fr', { day: 'numeric', month: 'numeric' });
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.font = '10px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(label, x, H - 26);
    }
  }

  // Tracé ligne + area fill par émotion
  for (const e of EMOTIONS) {
    let firstX = 0, lastX = 0;

    // 1. Ligne (stroke)
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

    // 2. Area fill (path séparé, gradient du haut vers le bas)
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
    grad.addColorStop(0, hexToRgba(EMOTION_COLORS[e], 0.25));
    grad.addColorStop(1, hexToRgba(EMOTION_COLORS[e], 0.02));
    ctx.fillStyle = grad;
    ctx.fill();
  }

  ctx.globalAlpha = 1;

  // Axe temporel
  ctx.fillStyle = 'rgba(255,255,255,0.4)';
  ctx.font = '10px monospace';
  ctx.textAlign = 'left';
  const label0 = new Date(tMin * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' });
  const labelN = new Date(tMax * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' });
  ctx.fillText(label0, PAD.left, H - 26);
  ctx.textAlign = 'right';
  ctx.fillText(labelN, W - PAD.right, H - 26);

  // Légende des émotions
  ctx.font = '9px monospace';
  const itemW = gW / EMOTIONS.length;
  EMOTIONS.forEach((e, i) => {
    const x = PAD.left + i * itemW;
    const ly = H - 10;
    ctx.strokeStyle = EMOTION_COLORS[e];
    ctx.lineWidth = 2;
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.moveTo(x, ly);
    ctx.lineTo(x + 14, ly);
    ctx.stroke();
    ctx.fillStyle = EMOTION_COLORS[e];
    ctx.textAlign = 'left';
    ctx.fillText(EMOTION_LABELS[e], x + 18, ly + 3);
  });
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
      <div style="font-size:1.1rem;font-weight:700;margin-bottom:6px">${escHtml(d.title || '')}</div>
      <div style="color:var(--text-muted);margin-bottom:4px">${escHtml(d.category || '')}</div>
      <div style="font-size:1.5rem;font-weight:900;color:var(--c-curiosity)">${(d.viewers || 0).toLocaleString()} viewers</div>
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

  container.innerHTML = `
    <!-- OpenAI -->
    <div class="card config-section">
      <div class="config-section-title">OPENAI</div>
      <div class="field-group">
        <label class="field-label">Modèle principal</label>
        <select id="cfg-primary-model">
          ${models.map(m => `<option value="${m}" ${m === cfg.openai.primary_model ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label">Modèle secondaire</label>
        <select id="cfg-secondary-model">
          ${models.map(m => `<option value="${m}" ${m === cfg.openai.secondary_model ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label">Température (0.0 – 2.0)</label>
        <input type="number" id="cfg-temperature" min="0" max="2" step="0.1" value="${cfg.openai.temperature}">
      </div>
      <div class="field-group">
        <label class="field-label">Max tokens</label>
        <input type="number" id="cfg-max-tokens" min="100" max="8000" value="${cfg.openai.max_tokens}">
      </div>
      <button class="btn btn-success" onclick="saveOpenAI()">💾 SAUVEGARDER</button>
    </div>

    <!-- Émotions — lambdas -->
    <div class="card config-section">
      <div class="config-section-title">DÉCROISSANCE ÉMOTIONS (λ)</div>
      ${Object.entries(cfg.emotions).map(([name, ec]) => `
        <div class="field-group">
          <label class="field-label" style="color:${EMOTION_COLORS[name] || 'var(--text-muted)'}">${name.toUpperCase()} λ</label>
          <input type="range" id="cfg-lambda-${name}" min="0.01" max="2" step="0.01" value="${ec.decay_lambda}"
            oninput="document.getElementById('lbl-lambda-${name}').textContent=parseFloat(this.value).toFixed(2)">
          <span id="lbl-lambda-${name}">${ec.decay_lambda.toFixed(2)}</span>
        </div>
      `).join('')}
      <button class="btn btn-success" onclick="saveEmotionLambdas()">💾 SAUVEGARDER</button>
    </div>

    <!-- Bot général -->
    <div class="card config-section">
      <div class="config-section-title">BOT GÉNÉRAL</div>
      <div class="field-group">
        <label class="field-label">Langue par défaut</label>
        <input type="text" id="cfg-lang" value="${cfg.bot.language_default}">
      </div>
      <div class="field-group">
        <label class="field-label">Heure journal (HH:MM)</label>
        <input type="text" id="cfg-journal-time" value="${cfg.bot.journal_time}">
      </div>
      <div class="field-group">
        <label class="field-label">Taille fenêtre contexte</label>
        <input type="number" id="cfg-ctx-size" value="${cfg.bot.context_window_size}">
      </div>
      <div class="field-group">
        <label class="field-label">Triggers (séparés par virgule)</label>
        <input type="text" id="cfg-triggers" value="${(cfg.bot.trigger_names || []).join(', ')}">
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
              <span style="flex:1;font-family:monospace">${ch}</span>
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
      <div id="guest-channel-error" style="color:var(--danger);font-size:0.85em;margin-top:6px;display:none"></div>
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
      primary_model:   document.getElementById('cfg-primary-model').value,
      secondary_model: document.getElementById('cfg-secondary-model').value,
      temperature:     parseFloat(document.getElementById('cfg-temperature').value),
      max_tokens:      parseInt(document.getElementById('cfg-max-tokens').value),
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

  if (r.status === 409) {
    errEl.textContent = 'Chaîne déjà ajoutée.'; errEl.style.display = 'block'; return;
  }
  if (r.status === 404) {
    errEl.textContent = 'Chaîne introuvable sur Twitch.'; errEl.style.display = 'block'; return;
  }
  if (r.status === 503) {
    errEl.textContent = 'API Twitch indisponible.'; errEl.style.display = 'block'; return;
  }
  if (!r.ok) {
    errEl.textContent = 'Erreur serveur.'; errEl.style.display = 'block'; return;
  }

  // Ajout visuel immédiat
  const list = document.getElementById('guest-channels-list');
  const empty = list.querySelector('p');
  if (empty) empty.remove();
  const item = document.createElement('div');
  item.id = `guest-ch-${name}`;
  item.className = 'guest-channel-item';
  item.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px';
  item.innerHTML = `<span style="flex:1;font-family:monospace">${name}</span>
    <button class="btn btn-danger" style="padding:2px 8px;font-size:0.8em"
      onclick="removeGuestChannel('${name}')">✕</button>`;
  list.appendChild(item);
  input.value = '';
  toast(`Wally rejoint ${name}`, 'success');
}

async function removeGuestChannel(name) {
  const r = await apiFetch(`/api/admin/twitch/channels/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
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
    // Mettre à jour les sliders admin
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

  // Charger l'historique du fichier log avant de brancher le SSE live
  // (résout la perte des logs au reload)
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
  // Limiter le nombre d'entrées
  while (el.children.length > MAX_LOG_ENTRIES) el.removeChild(el.firstChild);
  // Auto-scroll si en bas
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

// Note: EventSource ne supporte pas les headers — pour admin SSE logs,
// une solution production utiliserait un cookie HttpOnly ou un token dans
// le query string (ex: /api/admin/sse/logs?token=xxx).
// Pour usage perso réseau local, la route est accessible sans vérification
// du token SSE (le middleware vérifie uniquement les requêtes HTTP standard).

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  // Construire les jauges
  buildGauges('gauges-public', false);
  buildGauges('gauges-admin',  true);

  // Charger le statut initial
  await loadStatus();

  // Démarrer SSE émotions
  startEmotionSSE();

  // Polling statut toutes les 30s
  setInterval(loadStatus, 30000);

  // Chargement initial du bento (stream + graphe) — 1H par défaut
  loadStreamStatus();
  requestAnimationFrame(() => setGraphRange('1h'));

  // Poll cost alert badge (shows red badge on COÛTS tab if threshold exceeded)
  pollCostsBadge();

  // ── Tooltip hover sur le graphe ─────────────────────────────────────────
  const emotionCanvas = document.getElementById('emotionCanvas');
  if (!emotionCanvas) return;
  emotionCanvas.addEventListener('mousemove', (ev) => {
    if (!_graphMeta || _rafPending) return;
    const clientX = ev.clientX;
    _rafPending = true;
    requestAnimationFrame(() => {
      _rafPending = false;
      const { history, tMin, tRange, PAD, gW, gH, W, H } = _graphMeta;
      const rect = emotionCanvas.getBoundingClientRect();
      const mouseX = clientX - rect.left;

      // Trouver le snapshot dont la position X canvas est la plus proche du curseur
      let nearest = null, minDist = Infinity;
      for (const snap of history) {
        const sx = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
        const dist = Math.abs(sx - mouseX);
        if (dist < minDist) { minDist = dist; nearest = snap; }
      }

      // Redessiner le graphe complet, puis superposer le tooltip
      drawEmotionGraph(history);
      if (!nearest) return;

      const ctx = emotionCanvas.getContext('2d');
      const tw = 140;
      const th = 12 + EMOTIONS.length * 16 + 8;
      const tx = Math.min(mouseX + 12, W - tw - 4);
      const ty = 8;

      // Fond glassmorphism — roundRect dispo Chrome 99+ / Firefox 112+ / Safari 15.4+
      ctx.fillStyle = 'rgba(11,11,20,0.85)';
      ctx.strokeStyle = 'rgba(0,212,255,0.3)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(tx, ty, tw, th, 8);
      ctx.fill();
      ctx.stroke();

      // Valeurs d'émotions
      ctx.textAlign = 'left';
      ctx.font = '10px monospace';
      EMOTIONS.forEach((e, i) => {
        ctx.fillStyle = EMOTION_COLORS[e];
        ctx.fillText(
          `${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}: ${(nearest[e] ?? 0).toFixed(2)}`,
          tx + 8, ty + 16 + i * 16
        );
      });
    });
  });
  emotionCanvas.addEventListener('mouseleave', () => {
    if (_graphMeta) drawEmotionGraph(_graphMeta.history);
  });

  // Si token existant → proposer mode admin
  // (mais ne pas switcher automatiquement)
});

// ── Memory tab ────────────────────────────────────────────────────────────────

function escAttr(str) {
  return String(str).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderMemoryTab() {
  document.getElementById('tab-memory').innerHTML = `
    <div style="padding:12px 16px;border-bottom:2px solid #eee;display:flex;gap:10px;align-items:center">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px;white-space:nowrap">CHERCHER</span>
      <button class="btn" onclick="syncMemoryUsers()"
              style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">↻ SYNC</button>
      <button class="btn" onclick="resolveUsernames()"
              style="font-size:0.72rem;padding:4px 10px;white-space:nowrap">👤 RÉSOUDRE NOMS</button>
      <input type="text" id="mem-search" placeholder="Recherche dans tous les souvenirs…"
             oninput="onMemSearch(this.value)"
             style="flex:1;max-width:320px;padding:7px 10px;background:var(--card);border:2px solid var(--border);color:var(--text);font-family:var(--font);font-size:0.9rem;box-shadow:var(--shadow-sm);outline:none;border-radius:var(--radius-sm)">
    </div>
    <div style="display:flex;min-height:400px">
      <div style="width:220px;border-right:2px solid #eee;display:flex;flex-direction:column">
        <div style="padding:10px 12px;border-bottom:1px solid #eee">
          <input type="text" id="mem-user-filter" placeholder="Filtrer users…"
                 oninput="onUserFilter(this.value)"
                 style="width:100%;padding:7px 10px;background:var(--card);border:2px solid var(--border);color:var(--text);font-family:var(--font);font-size:0.8rem;outline:none;border-radius:var(--radius-sm)">
        </div>
        <div id="mem-user-list" style="flex:1;overflow-y:auto;padding:8px"></div>
      </div>
      <div id="mem-detail" style="flex:1;overflow-y:auto;min-height:0">
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
    return `
    <div class="mem-user-item"
         data-uid="${escAttr(u.user_id)}"
         onclick="selectMemUser('${escAttr(u.user_id)}','${escAttr(u.username || '')}')"
         style="padding:7px 10px;background:${selected ? 'var(--accent-soft)' : 'var(--card)'};border:1px solid ${selected ? 'var(--accent)' : 'var(--card-border)'};border-radius:var(--radius-sm);box-shadow:${selected ? 'var(--shadow-sm)' : 'none'};margin-bottom:4px;cursor:pointer;color:var(--text)">
      <span style="font-size:0.65rem;color:#888;display:block">${escHtml(u.platform)} · ${escHtml(lastSeen)}</span>
      <span style="font-size:0.8rem">${escHtml(u.username || u.user_id.split(':').slice(1).join(':') || u.user_id)}</span>
      <span style="font-size:0.65rem;color:${trustColor};display:block">trust: ${u.trust_score !== undefined ? u.trust_score.toFixed(2) : '—'}</span>
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
  // Update visual selection without reloading the whole list
  document.querySelectorAll('.mem-user-item').forEach(el => {
    const selected = el.dataset.uid === userId;
    el.style.background  = selected ? 'var(--accent-soft)' : 'var(--card)';
    el.style.borderColor = selected ? 'var(--accent)' : 'rgba(255,255,255,0.08)';
    el.style.boxShadow = selected ? 'var(--shadow-sm)' : 'none';
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
    <div style="padding:10px 16px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">${username ? escHtml(username) + ' (' + escHtml(userId) + ')' : escHtml(userId)} — ${memories.length} souvenir(s)</span>
      <button class="btn btn-danger" onclick="deleteAllMemories('${escAttr(userId)}')"
              style="font-size:0.72rem;padding:4px 10px">🗑 TOUT SUPPRIMER</button>
    </div>
    <div style="padding:12px">
      ${memories.length === 0
        ? '<div style="color:var(--text-muted);font-size:0.85rem">Aucun souvenir.</div>'
        : memories.map(m => `
          <div style="background:var(--card);border:1.5px solid #ddd;border-radius:var(--radius-sm);padding:10px 12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-start"
               id="mem-entry-${escAttr(m.id)}">
            <span style="font-size:0.82rem;flex:1;line-height:1.5">${escHtml(m.memory)}</span>
            <button onclick="deleteMemory('${escAttr(userId)}','${escAttr(m.id)}')"
                    style="background:none;border:none;color:var(--c-anger);cursor:pointer;font-size:1.1rem;margin-left:12px;flex-shrink:0;line-height:1">✕</button>
          </div>`).join('')
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
    <div style="padding:10px 16px;border-bottom:1px solid #eee">
      <span style="font-size:0.7rem;color:#aaa;letter-spacing:2px">${results.length} résultat(s) pour "${escHtml(q)}"</span>
    </div>
    <div style="padding:12px">
      ${results.length === 0
        ? '<div style="color:var(--text-muted);font-size:0.85rem">Aucun résultat.</div>'
        : results.map(res => `
          <div style="background:var(--card);border:1.5px solid #ddd;border-radius:var(--radius-sm);padding:10px 12px;margin-bottom:8px">
            <span style="font-size:0.65rem;color:#888;display:block;margin-bottom:4px">${res.username ? escHtml(res.username) + ' · ' : ''}${escHtml(res.user_id)}</span>
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
      pending:  '<span class="badge" style="background:rgba(255,160,0,0.2);color:#FFA000;border:1px solid #FFA000;padding:2px 6px;border-radius:4px;font-size:0.7rem">EN ATTENTE</span>',
      accepted: '<span class="badge" style="background:rgba(0,229,160,0.2);color:var(--c-curiosity);border:1px solid var(--c-curiosity);padding:2px 6px;border-radius:4px;font-size:0.7rem">ACCEPTÉ</span>',
      rejected: '<span class="badge" style="background:rgba(255,77,77,0.2);color:var(--c-anger);border:1px solid var(--c-anger);padding:2px 6px;border-radius:4px;font-size:0.7rem">REJETÉ</span>',
    }[p.status] || '';
    const actions = p.status === 'pending' ? `
      <button onclick="acceptLink(${p.id})" class="btn btn-success" style="font-size:0.75rem;padding:4px 10px">✓ Accepter</button>
      <button onclick="rejectLink(${p.id})" class="btn btn-danger"  style="font-size:0.75rem;padding:4px 10px">✗ Rejeter</button>
    ` : '';
    return `
      <div style="background:var(--card);border:1.5px solid var(--card-border);border-radius:var(--radius-sm);padding:10px 14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;gap:12px">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          ${statusBadge}
          <span style="font-weight:700;color:var(--accent)">${conf}%</span>
          <span style="font-size:0.85rem">Discord: <strong>${escHtml(discordUser)}</strong></span>
          <span style="color:var(--text-muted)">↔</span>
          <span style="font-size:0.85rem">Twitch: <a href="${twitchUrl}" target="_blank" style="color:var(--c-curiosity)">${escHtml(twitchUser)}</a></span>
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
    toast('Liaison créée', 'success');
    document.getElementById('manual-link-discord').value = '';
    document.getElementById('manual-link-twitch').value = '';
    loadLinks();
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
  if (r && r.ok) toast('Liaison acceptée', 'success');
  else toast('Erreur', 'error');
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

  // Today: calculate from daily data (last entry if it's today)
  const today = new Date().toISOString().slice(0, 10);
  const todayEntry = daily.current.find(d => d.date === today);
  document.getElementById('cost-today-total').textContent = `$${(todayEntry ? todayEntry.cost : 0).toFixed(2)}`;

  document.getElementById('cost-avg-msg').textContent = `$${summary.avg_per_msg.toFixed(4)}`;

  // Threshold KPI
  const threshEl = document.getElementById('cost-threshold');
  threshEl.textContent = `$${alert.threshold.toFixed(2)}`;
  const pctEl = document.getElementById('cost-threshold-pct');
  pctEl.textContent = `${alert.pct_used.toFixed(1)}% utilisé`;
  // Color based on status
  const threshColor = alert.status === 'critical' ? '#FF4D4D' : alert.status === 'warning' ? '#FFD700' : '#00E5A0';
  threshEl.style.color = threshColor;
  pctEl.style.color = threshColor;

  // Graph
  drawCostGraph(daily.current, daily.previous);

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

  ctx.fillStyle = '#0f0f1c';
  ctx.fillRect(0, 0, W, H);

  const PAD = { top: 10, bottom: 40, left: 50, right: 10 };
  const gW = W - PAD.left - PAD.right;
  const gH = H - PAD.top - PAD.bottom;

  // Find max cost for Y scale
  const allCosts = [...current.map(d => d.cost), ...(previous || []).map(d => d.cost)];
  const maxCost = Math.max(...allCosts, 0.01);

  // X positions: evenly spaced
  const xStep = current.length > 1 ? gW / (current.length - 1) : gW;

  // Y grid lines
  ctx.lineWidth = 1;
  const ySteps = 4;
  for (let i = 0; i <= ySteps; i++) {
    const pct = i / ySteps;
    const y = PAD.top + (1 - pct) * gH;
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(W - PAD.right, y);
    ctx.stroke();

    // Y axis labels
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(`$${(maxCost * pct).toFixed(2)}`, PAD.left - 4, y + 3);
  }

  // X axis labels (dates)
  ctx.textAlign = 'center';
  const labelEvery = current.length > 14 ? Math.ceil(current.length / 7) : (current.length > 7 ? 2 : 1);
  current.forEach((d, i) => {
    if (i % labelEvery !== 0 && i !== current.length - 1) return;
    const x = PAD.left + i * xStep;
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '10px monospace';
    const parts = d.date.split('-');
    ctx.fillText(`${parts[2]}/${parts[1]}`, x, H - 26);
  });

  // Draw previous period (dashed line)
  if (previous && previous.length > 0) {
    const prevXStep = previous.length > 1 ? gW / (previous.length - 1) : gW;
    ctx.beginPath();
    ctx.strokeStyle = '#4DA6FF';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.globalAlpha = 0.5;
    previous.forEach((d, i) => {
      const x = PAD.left + i * prevXStep;
      const y = PAD.top + (1 - d.cost / maxCost) * gH;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  // Draw current period (solid line + area fill)
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
  grad.addColorStop(0, 'rgba(255, 215, 0, 0.25)');
  grad.addColorStop(1, 'rgba(255, 215, 0, 0.02)');
  ctx.fillStyle = grad;
  ctx.fill();
}

function renderCostBreakdown(containerId, data, keyField) {
  const el = document.getElementById(containerId);
  if (!el || !data || data.length === 0) { if (el) el.textContent = '—'; return; }

  const maxTotal = data[0].total;
  el.innerHTML = data.map(d => {
    const pct = maxTotal > 0 ? (d.total / maxTotal * 100) : 0;
    const label = d[keyField] || 'Inconnu';
    return `<div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:2px">
        <span>${escHtml(label)}</span>
        <span style="color:#FFD700">$${d.total.toFixed(2)}</span>
      </div>
      <div style="height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden">
        <div style="width:${pct}%;height:100%;background:#FFD700;border-radius:2px"></div>
      </div>
    </div>`;
  }).join('');
}

function renderCostUsers(users) {
  const el = document.getElementById('cost-top-users');
  if (!el || !users || users.length === 0) { if (el) el.textContent = '—'; return; }

  const maxTotal = users[0].total;
  el.innerHTML = users.map(u => {
    const pct = maxTotal > 0 ? (u.total / maxTotal * 100) : 0;
    return `<div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:2px">
        <span>${escHtml(u.username)}</span>
        <span style="color:#FFD700">$${u.total.toFixed(2)}</span>
      </div>
      <div style="height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden">
        <div style="width:${pct}%;height:100%;background:#FFD700;border-radius:2px"></div>
      </div>
    </div>`;
  }).join('');
}

function updateCostAlertBar(alert) {
  const bar = document.getElementById('cost-alert-bar');
  if (!bar) return;

  if (alert.status === 'ok') {
    bar.style.display = 'none';
    return;
  }

  bar.style.display = 'block';
  const color = alert.status === 'critical' ? '#FF4D4D' : '#FFD700';
  bar.style.borderColor = color;
  bar.style.background = alert.status === 'critical'
    ? 'rgba(255,77,77,0.1)' : 'rgba(255,215,0,0.1)';

  document.getElementById('cost-alert-text').innerHTML =
    `<span style="color:${color}">⚠ Seuil d'alerte : <strong>$${alert.threshold.toFixed(2)}</strong></span>`;
  document.getElementById('cost-alert-pct').textContent = `${alert.pct_used.toFixed(1)}% utilisé`;
}

function updateCostBadge(alert) {
  const badge = document.getElementById('costs-badge');
  if (!badge) return;
  badge.style.display = alert.status === 'critical' ? 'inline-block' : 'none';
}

async function pollCostsBadge() {
  try {
    const r = await apiFetch('/api/admin/costs/alert');
    if (!r || !r.ok) return;
    const alert = await r.json();
    updateCostBadge(alert);
  } catch (e) { /* ignore */ }
}
