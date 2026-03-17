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
    requestAnimationFrame(() => loadEmotionHistory());
  }
  if (tabId === 'memory' && !document.getElementById('mem-user-list')) renderMemoryTab();
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

async function loadEmotionHistory() {
  const r = await fetch('/api/public/emotions/history');
  if (!r.ok) return;
  const { history } = await r.json();
  drawEmotionGraph(history);
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
  canvas.width  = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');

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
    try { appendLog(JSON.parse(e.data)); } catch {}
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

  // Chargement initial du bento (stream + graphe)
  loadStreamStatus();
  requestAnimationFrame(() => loadEmotionHistory());

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
