// bot/dashboard/static/app.js
// WARNING: Auth token stored in localStorage — acceptable for personal use.
// For public exposure, replace with HttpOnly cookies.

'use strict';

// ── Constants ────────────────────────────────────────────────────────────────

const AUTH_KEY = 'wally_token';
const EMOTION_COLORS = {
  anger:    '#f85149',
  joy:      '#d29e0b',
  curiosity:'#3fb950',
  sadness:  '#58a6ff',
  boredom:  '#a371f7',
};
const EMOTION_EMOJIS = {
  anger: '😤', joy: '😊', sadness: '😢', curiosity: '🤔', boredom: '😴',
};
const EMOTION_LABELS = {
  anger: 'ANGER', joy: 'JOY', curiosity: 'CURIOSITY', sadness: 'SADNESS', boredom: 'BOREDOM',
};
const EMOTIONS = ['anger', 'joy', 'sadness', 'curiosity', 'boredom'];
const SECONDARY_COLORS = {
  frustration: '#f97316',
  nostalgia:   '#ec4899',
  pride:       '#f59e0b',
  anxiety:     '#8b5cf6',
  contempt:    '#6b7280',
  wonder:      '#14b8a6',
};
const SECONDARY_LABELS = ['frustration', 'nostalgia', 'pride', 'anxiety', 'contempt', 'wonder'];
const SECONDARY_LABELS_FR = {
  frustration: 'frustration', nostalgia: 'nostalgie',   pride:    'fierté',
  anxiety:     'anxiété',     contempt:  'mépris',       wonder:   'émerveillement',
};
const SECONDARY_DEFS = {
  frustration: { a: 'anger',     b: 'boredom',    threshold: 0.3         },
  nostalgia:   { a: 'joy',       b: 'sadness',    threshold: 0.3         },
  pride:       { a: 'joy',       b: 'curiosity',  threshold: 0.4         },
  anxiety:     { a: 'sadness',   b: 'curiosity',  threshold: 0.3         },
  contempt:    { a: 'anger',     b: 'boredom',    threshold: [0.4, 0.5]  },
  wonder:      { a: 'curiosity', b: 'joy',        threshold: 0.5         },
};

const PLATFORM_COLORS = {
  discord: '#5865F2',
  twitch: '#9146FF',
};

const PLATFORM_ICONS = {
  discord: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>',
  twitch: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/></svg>',
};

// ── State ────────────────────────────────────────────────────────────────────

let currentTab  = 'admin-parametres';
let logSSE      = null;
function _escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
let _twitchPendingRestart = false;
let actionSSE   = null;
let logFilter   = 'ALL';
let currentEmotions = {};
let currentMood        = {};
let currentFatigue     = {};
let currentSecondaries = [];

// ── Tab sub-navigation state ──────────────────────────────────────
let _parametresSubTab = 'emotions';
let _systemeSubTab    = 'logs';

const MOOD_ADJ_FR = {
  anger: 'irritable', joy: 'joyeux', sadness: 'mélancolique',
  curiosity: 'curieux', boredom: 'apathique',
};
const FATIGUE_LABEL_FR = {
  anger: 'colère', joy: 'joie', sadness: 'tristesse', curiosity: 'curiosité', boredom: 'ennui',
};
const FATIGUE_COLORS = {
  anger:    'rgba(239,68,68,0.7)',
  joy:      'rgba(234,179,8,0.7)',
  sadness:  'rgba(59,130,246,0.7)',
  curiosity:'rgba(34,197,94,0.7)',
  boredom:  'rgba(168,85,247,0.7)',
};
const SECONDARY_ADJ_FR = {
  frustration: 'frustré',
  nostalgia:   'nostalgique',
  pride:       'fier de lui',
  anxiety:     'anxieux',
  contempt:    'méprisant',
  wonder:      'émerveillé',
};

// -- Bot Control Bar ----------------------------------------------
var _controlBarInterval = null;

function showControlBar(visible) {
  var bar = document.getElementById('control-bar');
  if (bar) bar.style.display = visible ? 'flex' : 'none';
}

async function pollBotStatus() {
  var r = await apiFetch('/api/admin/bot/status');
  if (!r || !r.ok) return;
  var data = await r.json();

  var discordDot = document.getElementById('discord-dot');
  var twitchDot = document.getElementById('twitch-dot');
  var discordBtn = document.getElementById('discord-toggle-btn');
  var twitchBtn = document.getElementById('twitch-toggle-btn');

  if (discordDot) discordDot.className = 'control-bar-dot' + (data.discord === 'connected' ? ' online' : '');
  if (twitchDot) twitchDot.className = 'control-bar-dot' + (data.twitch === 'connected' ? ' online' : '');
  if (discordBtn) {
    discordBtn.textContent = data.discord === 'connected' ? 'Stop' : 'Start';
    discordBtn.disabled = false;
  }
  if (twitchBtn) {
    twitchBtn.textContent = data.twitch === 'connected' ? 'Stop' : 'Start';
    twitchBtn.disabled = false;
  }
  var updateGroup = document.getElementById('update-group');
  if (updateGroup) updateGroup.style.display = data.update_available ? '' : 'none';
  var versionBadge = document.getElementById('version-badge');
  if (versionBadge && data.git_hash && data.git_hash !== 'unknown') {
    versionBadge.textContent = 'build ' + data.git_hash + ' · ' + _formatBuildDate(data.build_date);
  }
}

function _formatBuildDate(iso) {
  if (!iso || iso === 'unknown') return '';
  try {
    var d = new Date(iso);
    var months = ['janv','févr','mars','avr','mai','juin','juil','août','sept','oct','nov','déc'];
    return d.getUTCDate() + ' ' + months[d.getUTCMonth()] + ' ' + String(d.getUTCHours()).padStart(2,'0') + ':' + String(d.getUTCMinutes()).padStart(2,'0');
  } catch(e) { return iso; }
}

async function triggerSelfUpdate() {
  var btn = document.getElementById('update-available-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Mise à jour…'; }
  var r = await apiFetch('/api/admin/self-update', { method: 'POST' });
  if (!r || !r.ok) {
    var d = r ? await r.json() : {};
    toast('Erreur : ' + (d.detail || '?'), 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Update dispo'; }
    return;
  }
  toast('Mise à jour lancée, redémarrage en cours…', 'success');
  setTimeout(function() { _waitForReconnect(); }, 3000);
}

function startControlBarPolling() {
  if (_controlBarInterval) return;
  pollBotStatus();
  _controlBarInterval = setInterval(pollBotStatus, 5000);
}

function stopControlBarPolling() {
  if (_controlBarInterval) {
    clearInterval(_controlBarInterval);
    _controlBarInterval = null;
  }
}

async function toggleBotAdapter(adapter) {
  var btn = document.getElementById(adapter + '-toggle-btn');
  if (!btn) return;
  var action = btn.textContent.trim() === 'Stop' ? 'stop' : 'start';
  btn.disabled = true;
  btn.textContent = '...';
  var r = await apiFetch('/api/admin/bot/' + adapter + '/' + action, { method: 'POST' });
  if (!r || !r.ok) {
    toast('Erreur ' + action + ' ' + adapter, 'error');
    btn.disabled = false;
    pollBotStatus();
    return;
  }
  toast(adapter + ' ' + (action === 'stop' ? 'arrêté' : 'démarré'), 'success');
  setTimeout(pollBotStatus, 2000);
}

async function restartContainer() {
  if (!confirm('Redémarrer le container Wally ? Le dashboard sera temporairement indisponible.')) return;
  var btn = document.getElementById('restart-btn');
  if (btn) btn.disabled = true;
  var r = await apiFetch('/api/admin/bot/restart', { method: 'POST' });
  if (!r || !r.ok) {
    toast('Erreur restart', 'error');
    if (btn) btn.disabled = false;
    return;
  }
  toast('Restart en cours...', 'success');
  _waitForReconnect();
}

function _waitForReconnect() {
  var attempts = 0;
  var maxAttempts = 60;
  var interval = setInterval(async function() {
    attempts++;
    if (attempts > maxAttempts) {
      clearInterval(interval);
      toast('Le bot ne répond plus', 'error');
      return;
    }
    try {
      var r = await fetch('/api/public/status', { signal: AbortSignal.timeout(3000) });
      if (r.ok) {
        clearInterval(interval);
        toast('Bot reconnecté !', 'success');
        var btn = document.getElementById('restart-btn');
        if (btn) btn.disabled = false;
        pollBotStatus();
      }
    } catch(e) { /* server still down */ }
  }, 2000);
}

function _onTwitchAuthSuccess(account, username) {
  _twitchPendingRestart = true;
  var label = account === 'bot' ? 'bot' : 'streamer';
  toast('Compte ' + label + ' connecte' + (username ? ' — ' + username : '') + ' ! Redemarre le container.', 'success');
  var panel = document.getElementById('systeme-sub-twitch');
  if (panel && panel.classList.contains('active')) {
    _renderSystemeTwitch(panel);
  }
}

async function startTwitchOAuth(account) {
  var r = await apiFetch('/api/admin/twitch/auth-url', {
    method: 'POST',
    body: JSON.stringify({ account: account }),
  });
  if (!r || !r.ok) { toast('Erreur generation URL OAuth', 'error'); return; }
  var data = await r.json();
  var popup = window.open(data.url, 'twitch-oauth', 'width=600,height=700,noopener');
  if (!popup) toast('Popup bloque — autorise les popups pour ce site.', 'error');
}

async function restartTwitchContainer() {
  if (!confirm('Redemarrer le container Wally ? Le dashboard sera indisponible ~10s.')) return;
  var r = await apiFetch('/api/admin/twitch/restart', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur restart', 'error'); return; }
  _twitchPendingRestart = false;
  toast('Redemerrage en cours...', 'success');
  _waitForReconnect();
}

// ── Mode & tabs ───────────────────────────────────────────────────────────────

function enterAdmin() {
  if (!getToken()) { showAuthModal(); return; }
  document.getElementById('nav-admin').style.display = 'flex';
  showControlBar(true);
  startControlBarPolling();
  renderSystemeTab();
  startLogSSE();
  showTab('admin-parametres');
}

function showTab(tabId) {
  // Redirect legacy tab names to new consolidated tabs
  const _legacyRedirect = {
    'admin-config': 'admin-parametres',
    'admin-logs':   'admin-systeme',
    'admin-overlay': 'admin-systeme',
    'admin-twitch': 'admin-systeme',
  };
  if (_legacyRedirect[tabId]) {
    // Set the appropriate sub-tab before redirecting
    if (tabId === 'admin-logs') _systemeSubTab = 'logs';
    else if (tabId === 'admin-overlay') _systemeSubTab = 'overlay';
    else if (tabId === 'admin-twitch') _systemeSubTab = 'twitch';
    tabId = _legacyRedirect[tabId];
  }

  document.querySelectorAll('.sidebar-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  const btn = document.querySelector(`.sidebar-item[data-tab="${tabId}"]`);
  if (btn) btn.classList.add('active');

  const pane = document.getElementById(`tab-${tabId}`);
  if (pane) pane.classList.add('active');

  currentTab = tabId;
  location.hash = tabId;

  if (tabId !== 'admin-memoire' && _memLinkMode) { cancelLinkMode(); }
  if (tabId === 'admin-parametres') renderParametresTab();
  if (tabId === 'admin-systeme') renderSystemeTab();
  if (tabId === 'admin-memoire') renderMemoireTab();
  if (tabId === 'admin-memory-dash') loadMemoryDashboard();
  if (tabId === 'admin-actions') { renderActionsTab(); startActionSSE(); } else { stopActionSSE(); }
  if (tabId === 'admin-prompts') renderPromptsTab();
  if (tabId === 'admin-overlay') loadOverlayTab();
  if (tabId === 'admin-twitch') loadTwitchChannelsTab();
  pollLinksBadge();
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
    enterAdmin();
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
    showAuthModal();
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

// ── Emotion gauges ────────────────────────────────────────────────────────────

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

function updateEmotionGauges(payload) {
  // Extract organic emotion fields
  currentMood        = payload.mood        || {};
  currentFatigue     = payload.fatigue     || {};
  currentSecondaries = payload.secondaries || [];

  currentEmotions = payload;
  for (const e of EMOTIONS) {
    const v = payload[e] ?? 0;
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
  updateMoodFatigueLine(currentMood, currentFatigue);
  updateEmotionalStateBlock(payload, currentMood, currentFatigue, currentSecondaries);
}

function updateMoodFatigueLine(mood, fatigue) {
  const el = document.getElementById('mood-fatigue-line');
  if (!el) return;

  const moodEntries = EMOTIONS
    .filter(e => (mood[e] ?? 0) >= 0.2)
    .sort((a, b) => (mood[b] ?? 0) - (mood[a] ?? 0))
    .slice(0, 2);

  const fatigueEntries = Object.entries(fatigue).filter(([, v]) => v > 0);

  if (moodEntries.length === 0 && fatigueEntries.length === 0) {
    el.style.display = 'none';
    return;
  }

  // Build spans from internal constants only — labels from MOOD_ADJ_FR/FATIGUE_LABEL_FR,
  // color from FATIGUE_COLORS, pct is a rounded integer. No user input reaches innerHTML.
  const parts = [];

  if (moodEntries.length > 0) {
    const labels = moodEntries.map(e => MOOD_ADJ_FR[e] || e).join(', ');
    parts.push(
      '<span class="mf-label">Humeur de fond</span>',
      `<span class="mf-value">${labels}</span>`
    );
  }

  if (fatigueEntries.length > 0) {
    if (moodEntries.length > 0) parts.push('<span class="mf-separator">|</span>');
    parts.push('<span class="mf-label">Fatigue</span>');
    for (const [emotion, v] of fatigueEntries) {
      const label = FATIGUE_LABEL_FR[emotion] || emotion;
      const pct   = Math.round(v * 100);
      const color = FATIGUE_COLORS[emotion] || 'rgba(255,255,255,0.7)';
      parts.push(
        `<span class="mf-value" style="color:${color};margin-left:6px">${label} en récupération (${pct}%)</span>`
      );
    }
  }

  el.innerHTML = parts.join(''); // safe: all content from internal constants + numeric pct
  el.style.display = 'flex';
}

function updateEmotionalStateBlock(emotions, mood, fatigue, secondaries) {
  const el     = document.getElementById('emotional-state-block');
  const textEl = document.getElementById('emotional-state-text');
  if (!el || !textEl) return;

  const fatigueActive     = Object.values(fatigue).some(v => v > 0);
  const activeSecondaries = secondaries.filter(([, intensity]) => intensity >= 0.4);

  const dominantEmotion = EMOTIONS.reduce((a, b) =>
    (emotions[a] ?? 0) > (emotions[b] ?? 0) ? a : b);
  const dominantMood = EMOTIONS.reduce((a, b) =>
    (mood[a] ?? 0) > (mood[b] ?? 0) ? a : b);
  const hasMoodDissonance = dominantMood !== dominantEmotion
    && (emotions[dominantEmotion] ?? 0) >= 0.3
    && (mood[dominantMood] ?? 0) >= 0.3;

  let sentence = '';

  // Rule 1: Secondary emotion active (intensity >= 0.4)
  if (activeSecondaries.length > 0) {
    const [secName] = activeSecondaries[0];
    const secAdj = SECONDARY_ADJ_FR[secName] || secName;
    sentence = `Wally est ${secAdj}.`;
    if (fatigueActive) {
      const firstFatigueEmotion = Object.keys(fatigue).find(k => fatigue[k] > 0);
      const fatigueLabel = firstFatigueEmotion ? (FATIGUE_LABEL_FR[firstFatigueEmotion] || firstFatigueEmotion) : '';
      if (fatigueLabel) sentence += ` Sa ${fatigueLabel} est en récupération après un pic.`;
    }
    if (hasMoodDissonance) {
      const moodAdj = MOOD_ADJ_FR[dominantMood] || dominantMood;
      sentence += ` Fond ${moodAdj} malgré tout.`;
    }
  }
  // Rule 2: Fatigue active but no secondary
  else if (fatigueActive) {
    const firstFatigueEmotion = Object.keys(fatigue).find(k => fatigue[k] > 0);
    const fatigueLabel = firstFatigueEmotion ? (FATIGUE_LABEL_FR[firstFatigueEmotion] || firstFatigueEmotion) : '';
    sentence = `Wally est dans un état normal.${fatigueLabel ? ` Sa ${fatigueLabel} est en récupération.` : ''}`;
  }
  // Rule 3: Mood dissonance
  else if (hasMoodDissonance) {
    const emotAdj = MOOD_ADJ_FR[dominantEmotion] || dominantEmotion;
    const moodAdj = MOOD_ADJ_FR[dominantMood]    || dominantMood;
    sentence = `Wally est ${emotAdj} en surface mais ${moodAdj} en profondeur.`;
  }
  // Rule 4: Nothing interesting — hide
  else {
    el.style.display = 'none';
    return;
  }

  textEl.textContent = sentence; // textContent — safe, no XSS risk
  el.style.display = 'block';
}

// ── Canvas helpers ────────────────────────────────────────────────────────────

function _canvasContentWidth(canvas) {
  const parent = canvas.parentElement;
  if (!parent) return canvas.offsetWidth || 800;
  const cs = getComputedStyle(parent);
  return Math.floor(parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) || 800;
}

function showGraphEmpty(canvasId, message) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const W = _canvasContentWidth(canvas);
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

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
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

async function loadClaudeModels() {
  const r = await apiFetch('/api/admin/claude/models');
  if (!r || !r.ok) return [];
  const { models } = await r.json();
  return models;
}

async function renderConfigForm(cfg) {
  const container = document.getElementById('config-form-container');
  const [models, claudeModels] = await Promise.all([loadOpenAIModels(), loadClaudeModels()]);

  const REASONING_EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'];
  const TEXT_VERBOSITIES = ['low', 'medium', 'high'];
  const THINKING_TYPES = ['disabled', 'enabled', 'adaptive'];
  const THINKING_EFFORTS = ['low', 'medium', 'high', 'max'];

  container.innerHTML = `
    <!-- Émotions (force + reset) -->
    <div class="card config-section">
      <div class="config-section-title">ÉMOTIONS</div>
      <div id="gauges-admin-inline" role="group" aria-label="Controle des emotions"></div>
      <div class="mt-4">
        <button class="btn btn-danger" onclick="resetEmotions()">RESET À NEUTRE (0.5)</button>
      </div>
    </div>

    <!-- LLM Providers -->
    <div class="card config-section">
      <div class="config-section-title">LLM — MODÈLES</div>
      <div class="field-group">
        <label class="field-label" for="cfg-primary-provider">Provider principal</label>
        <select id="cfg-primary-provider" onchange="onProviderChange()">
          <option value="openai" ${(cfg.llm?.primary?.provider || 'openai') === 'openai' ? 'selected' : ''}>OpenAI</option>
          <option value="claude" ${(cfg.llm?.primary?.provider || 'openai') === 'claude' ? 'selected' : ''}>Claude (Anthropic)</option>
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-primary-model">Modèle principal</label>
        <select id="cfg-primary-model">
          ${models.map(m => `<option value="${m}" ${m === cfg.openai.primary_model ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
        <select id="cfg-primary-model-claude" style="display:none">
          ${claudeModels.map(m => `<option value="${m}" ${m === (cfg.llm?.primary?.model || '') ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-secondary-provider">Provider secondaire</label>
        <select id="cfg-secondary-provider" onchange="onProviderChange()">
          <option value="openai" ${(cfg.llm?.secondary?.provider || 'openai') === 'openai' ? 'selected' : ''}>OpenAI</option>
          <option value="claude" ${(cfg.llm?.secondary?.provider || 'openai') === 'claude' ? 'selected' : ''}>Claude (Anthropic)</option>
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-secondary-model">Modèle secondaire</label>
        <select id="cfg-secondary-model">
          ${models.map(m => `<option value="${m}" ${m === cfg.openai.secondary_model ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
        <select id="cfg-secondary-model-claude" style="display:none">
          ${claudeModels.map(m => `<option value="${m}" ${m === (cfg.llm?.secondary?.model || '') ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
      <div id="openai-specific-settings">
        <div class="field-group">
          <label class="field-label" for="cfg-reasoning-effort">Niveau d'effort (reasoning) <span style="font-size:0.7rem;color:var(--text-muted)">OpenAI only</span></label>
          <select id="cfg-reasoning-effort">
            ${REASONING_EFFORTS.map(e => `<option value="${e}" ${e === cfg.openai.reasoning_effort ? 'selected' : ''}>${e.toUpperCase()}</option>`).join('')}
          </select>
        </div>
        <div class="field-group">
          <label class="field-label" for="cfg-text-verbosity">Verbosité des réponses <span style="font-size:0.7rem;color:var(--text-muted)">OpenAI only</span></label>
          <select id="cfg-text-verbosity">
            ${TEXT_VERBOSITIES.map(v => `<option value="${v}" ${v === cfg.openai.text_verbosity ? 'selected' : ''}>${v.toUpperCase()}</option>`).join('')}
          </select>
        </div>
      </div>
      <div id="claude-specific-settings" style="display:none">
        <div class="field-group">
          <label class="field-label" for="cfg-thinking-type">Réflexion (thinking) <span style="font-size:0.7rem;color:var(--text-muted)">Claude only</span></label>
          <select id="cfg-thinking-type" onchange="onThinkingTypeChange()">
            ${THINKING_TYPES.map(t => `<option value="${t}" ${t === (cfg.llm?.primary?.thinking_type || 'disabled') ? 'selected' : ''}>${t === 'disabled' ? 'DÉSACTIVÉ' : t === 'adaptive' ? 'ADAPTATIF' : 'ACTIVÉ (budget fixe)'}</option>`).join('')}
          </select>
        </div>
        <div id="thinking-effort-group" class="field-group" style="display:none">
          <label class="field-label" for="cfg-thinking-effort">Niveau d'effort thinking</label>
          <select id="cfg-thinking-effort">
            ${THINKING_EFFORTS.map(e => `<option value="${e}" ${e === (cfg.llm?.primary?.thinking_effort || 'medium') ? 'selected' : ''}>${e.toUpperCase()}</option>`).join('')}
          </select>
          <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">LOW = rapide · MEDIUM = équilibré · HIGH = défaut, pense souvent · MAX = max (Opus 4.6 only)</p>
        </div>
        <div id="thinking-budget-group" class="field-group" style="display:none">
          <label class="field-label" for="cfg-thinking-budget">Budget tokens thinking</label>
          <input type="number" id="cfg-thinking-budget" min="1000" max="128000" step="1000" value="${cfg.llm?.primary?.thinking_budget_tokens || 10000}">
          <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Doit être inférieur à max_tokens. 10k = standard, 50k+ = problèmes complexes</p>
        </div>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-max-tokens">Max output tokens</label>
        <input type="number" id="cfg-max-tokens" min="100" max="32000" value="${cfg.openai.max_tokens}">
      </div>
      <button class="btn btn-success" onclick="saveOpenAI()">💾 SAUVEGARDER</button>
      <p id="llm-restart-notice" style="display:none;font-size:0.75rem;color:#f59e0b;margin-top:8px">⚠️ Changement de provider — redémarrage requis pour prendre effet.</p>
    </div>

    <!-- Émotions — lambdas (boredom exclu : monte avec l'inactivité, pas de decay) -->
    <div class="card config-section">
      <div class="config-section-title">DÉCROISSANCE ÉMOTIONS (λ)</div>
      <p style="font-size:0.75rem;color:var(--text-muted);margin:0 0 12px">λ = vitesse de décroissance par heure. Plus la valeur est élevée, plus l'émotion retombe vite. Boredom monte avec l'inactivité et n'utilise pas ce paramètre.</p>
      ${Object.entries(cfg.emotions).filter(([name]) => name !== 'boredom').map(([name, ec]) => {
        const lam = ec.decay_lambda;
        const timeToZeroH = lam > 0 ? (Math.log(1/0.01)) / lam : Infinity;
        const timeLabel = timeToZeroH === Infinity ? '∞' : timeToZeroH < 1 ? Math.round(timeToZeroH * 60) + ' min' : Math.round(timeToZeroH * 10) / 10 + ' h';
        return `
        <div class="field-group" style="display:flex;align-items:center;gap:12px">
          <label class="field-label" for="cfg-lambda-${name}" style="color:${EMOTION_COLORS[name] || 'var(--text-muted)'}; min-width:100px">${name.toUpperCase()} λ</label>
          <input type="number" id="cfg-lambda-${name}" min="0" max="1" step="0.001" value="${lam}" style="width:90px" oninput="updateDecayTime(this, '${name}')">
          <span id="decay-time-${name}" style="font-size:0.8rem;color:var(--text-secondary);white-space:nowrap">100→0% en <strong style="color:#e2e8f0">${timeLabel}</strong></span>
        </div>`;
      }).join('')}

      <!-- Boredom rise config -->
      <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">
        <div style="display:flex;align-items:center;gap:12px">
          <label class="field-label" for="cfg-boredom-rise" style="color:${EMOTION_COLORS['boredom'] || 'var(--text-muted)'}; min-width:100px">BOREDOM ↑/h</label>
          <input type="number" id="cfg-boredom-rise" min="0" max="10" step="0.1" value="${cfg.emotions.boredom?.boredom_rise_per_hour ?? 1.2}" style="width:90px" oninput="updateBoredomTime(this)">
          <span id="boredom-time-info" style="font-size:0.8rem;color:var(--text-secondary);white-space:nowrap">0→100% en <strong style="color:#e2e8f0">${(() => { const r = cfg.emotions.boredom?.boredom_rise_per_hour ?? 1.2; if (r <= 0) return '∞'; const h = 1/r; return h < 1 ? Math.round(h*60) + ' min' : Math.round(h*10)/10 + ' h'; })()}</strong></span>
        </div>
        <p style="font-size:0.75rem;color:var(--text-muted);margin:8px 0 0">Vitesse de montée de l'ennui par heure d'inactivité. 1.2 = ennui max en ~50 min.</p>
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
        <p style="font-size:0.7rem;color:var(--text-muted);margin-top:4px">Alertes coûts et erreurs envoyées dans ce salon</p>
      </div>
      <button class="btn btn-success" onclick="saveBotGeneral()">💾 SAUVEGARDER</button>
    </div>

    <!-- Anti-spam Discord -->
    <div class="card config-section">
      <div class="config-section-title">ANTI-SPAM DISCORD</div>
      <div class="field-group" style="display:flex;align-items:center;gap:12px">
        <label class="field-label" style="margin:0" for="cfg-spam-enabled">Activé</label>
        <input type="checkbox" id="cfg-spam-enabled" ${(cfg.discord.spam_detection || {}).enabled !== false ? 'checked' : ''}>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-max">Messages max</label>
        <input type="number" id="cfg-spam-max" min="3" max="50" value="${(cfg.discord.spam_detection || {}).max_messages || 10}">
        <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Nombre de messages avant déclenchement</p>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-window">Fenêtre (secondes)</label>
        <input type="number" id="cfg-spam-window" min="30" max="600" value="${(cfg.discord.spam_detection || {}).window_seconds || 120}">
        <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Période de temps pour compter les messages</p>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-mute">Durée mute (minutes)</label>
        <input type="number" id="cfg-spam-mute" min="1" max="60" value="${(cfg.discord.spam_detection || {}).mute_minutes || 5}">
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-anger">Delta colère par message muté</label>
        <input type="number" id="cfg-spam-anger" min="0.01" max="0.2" step="0.01" value="${(cfg.discord.spam_detection || {}).spam_anger_delta || 0.05}">
        <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Augmentation de la colère quand un utilisateur muté continue de parler</p>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-exempt">Channels exemptés (IDs séparés par virgule)</label>
        <input type="text" id="cfg-spam-exempt" value="${((cfg.discord.spam_detection || {}).exempt_channels || []).join(', ')}">
        <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Ces salons ignorent la détection de spam</p>
      </div>
      <button class="btn btn-success" onclick="saveSpamConfig()">💾 SAUVEGARDER</button>
    </div>

  `;

  // Build emotion sliders inline
  buildGauges('gauges-admin-inline', true);
  // Update with current values if available
  if (currentEmotions && Object.keys(currentEmotions).length > 0) {
    updateEmotionGauges(currentEmotions);
  }

  // Initialize provider UI state
  onProviderChange();

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

function onProviderChange() {
  const primaryProv = document.getElementById('cfg-primary-provider').value;
  const secondaryProv = document.getElementById('cfg-secondary-provider').value;
  // Toggle model dropdowns based on provider (OpenAI vs Claude)
  const primarySelect = document.getElementById('cfg-primary-model');
  const primaryClaude = document.getElementById('cfg-primary-model-claude');
  const secondarySelect = document.getElementById('cfg-secondary-model');
  const secondaryClaude = document.getElementById('cfg-secondary-model-claude');
  if (primaryProv === 'claude') {
    primarySelect.style.display = 'none';
    primaryClaude.style.display = 'block';
  } else {
    primarySelect.style.display = 'block';
    primaryClaude.style.display = 'none';
  }
  if (secondaryProv === 'claude') {
    secondarySelect.style.display = 'none';
    secondaryClaude.style.display = 'block';
  } else {
    secondarySelect.style.display = 'block';
    secondaryClaude.style.display = 'none';
  }
  // Show/hide provider-specific settings based on primary provider
  const openaiSettings = document.getElementById('openai-specific-settings');
  const claudeSettings = document.getElementById('claude-specific-settings');
  if (openaiSettings) openaiSettings.style.display = primaryProv === 'openai' ? 'block' : 'none';
  if (claudeSettings) claudeSettings.style.display = primaryProv === 'claude' ? 'block' : 'none';
  if (primaryProv === 'claude') onThinkingTypeChange();
  // Show restart notice if provider changed
  const notice = document.getElementById('llm-restart-notice');
  if (notice) notice.style.display = 'block';
}

function onThinkingTypeChange() {
  const type = document.getElementById('cfg-thinking-type')?.value || 'disabled';
  const effortGroup = document.getElementById('thinking-effort-group');
  const budgetGroup = document.getElementById('thinking-budget-group');
  if (effortGroup) effortGroup.style.display = type === 'adaptive' ? 'block' : 'none';
  if (budgetGroup) budgetGroup.style.display = type === 'enabled' ? 'block' : 'none';
}

async function saveOpenAI() {
  const primaryProv = document.getElementById('cfg-primary-provider').value;
  const secondaryProv = document.getElementById('cfg-secondary-provider').value;
  const primaryModel = primaryProv === 'claude'
    ? document.getElementById('cfg-primary-model-claude').value
    : document.getElementById('cfg-primary-model').value;
  const secondaryModel = secondaryProv === 'claude'
    ? document.getElementById('cfg-secondary-model-claude').value
    : document.getElementById('cfg-secondary-model').value;

  const payload = {
    openai: {
      primary_model:    primaryModel,
      secondary_model:  secondaryModel,
      reasoning_effort: document.getElementById('cfg-reasoning-effort').value,
      text_verbosity:   document.getElementById('cfg-text-verbosity').value,
      max_tokens:       parseInt(document.getElementById('cfg-max-tokens').value),
    },
    llm: {
      primary: {
        provider: primaryProv,
        model: primaryModel,
        thinking_type: document.getElementById('cfg-thinking-type')?.value || 'disabled',
        thinking_effort: document.getElementById('cfg-thinking-effort')?.value || 'medium',
        thinking_budget_tokens: parseInt(document.getElementById('cfg-thinking-budget')?.value || '10000'),
      },
      secondary: { provider: secondaryProv, model: secondaryModel },
    },
  };
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (r && r.ok) toast('Config LLM sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
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

// ── Anti-spam config ──────────────────────────────────────────────────────────

async function saveSpamConfig() {
  const exemptRaw = document.getElementById('cfg-spam-exempt').value;
  const exempt = exemptRaw.split(',').map(s => s.trim()).filter(Boolean).map(Number).filter(n => !isNaN(n));
  const r = await apiFetch('/api/admin/config', {
    method: 'POST',
    body: JSON.stringify({ discord: { spam_detection: {
      enabled:          document.getElementById('cfg-spam-enabled').checked,
      max_messages:     parseInt(document.getElementById('cfg-spam-max').value),
      window_seconds:   parseInt(document.getElementById('cfg-spam-window').value),
      mute_minutes:     parseInt(document.getElementById('cfg-spam-mute').value),
      spam_anger_delta: parseFloat(document.getElementById('cfg-spam-anger').value),
      exempt_channels:  exempt,
    }}}),
  });
  if (r && r.ok) toast('Config anti-spam sauvegardée', 'success'); else toast('Erreur sauvegarde', 'error');
}

// ── Guest channels ─────────────────────────────────────────────────────────────

async function addGuestChannel() {
  const input = document.getElementById('guest-channel-input');
  const errEl = document.getElementById('guest-channel-error');
  if (!input || !errEl) return;
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
  item.id = 'guest-ch-' + name;
  item.className = 'twitch-channel-card';
  // name is validated ^[a-z0-9_]{1,25}$ before reaching here — safe for innerHTML
  item.innerHTML = '<div class="tc-dot pending"></div>'
    + '<span class="tc-name">' + name + '</span>'
    + '<span class="tc-badge offline">hors ligne</span>'
    + '<button class="tc-kick" onclick="removeGuestChannel(\'' + name + '\')">Déconnecter</button>';
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
    if (list && !list.querySelector('.twitch-channel-card, .guest-channel-item')) {
      list.innerHTML = '<p style="color:var(--text-muted);margin:0 0 12px">Aucune chaîne invitée.</p>';
    }
    toast(`Wally a quitté ${name}`, 'success');
  } else {
    toast('Erreur lors de la suppression', 'error');
  }
}

// ── Twitch Channels Tab ────────────────────────────────────────────

async function loadTwitchChannelsTab() {
  const el = document.getElementById('tab-admin-twitch');
  if (!el) return;

  el.innerHTML = '<p style="color:var(--text-muted);padding:16px">Chargement…</p>';

  const r = await apiFetch('/api/admin/twitch/channels');
  if (!r || !r.ok) {
    if (r && r.status === 503) {
      el.textContent = 'Twitch non disponible — BOT_ACCESS_TOKEN manquant dans .env';
      el.style.padding = '16px';
      el.style.color = 'var(--c-offline)';
    } else {
      el.textContent = 'Erreur de chargement.';
      el.style.padding = '16px';
      el.style.color = 'var(--c-offline)';
    }
    return;
  }
  const channels = await r.json();

  const cardsHtml = channels.length === 0
    ? '<p style="color:var(--text-muted);margin-bottom:12px">Aucune chaîne invitée.</p>'
    : channels.map(ch => {
        // ch.name is a validated Twitch login (^[a-z0-9_]{1,25}$) — safe for innerHTML
        const dotClass = ch.irc_connected ? 'connected' : 'pending';
        const badgeClass = ch.live ? 'live' : 'offline';
        const badgeText = ch.live ? '🔴 LIVE' : 'hors ligne';
        return '<div class="twitch-channel-card" id="guest-ch-' + ch.name + '">'
          + '<div class="tc-dot ' + dotClass + '"></div>'
          + '<span class="tc-name">' + ch.name + '</span>'
          + '<span class="tc-badge ' + badgeClass + '">' + badgeText + '</span>'
          + '<button class="tc-kick" onclick="removeGuestChannel(\'' + ch.name + '\')">Déconnecter</button>'
          + '</div>';
      }).join('');

  el.innerHTML = '<div style="padding:0 2px">'
    + '<div id="guest-channels-list">' + cardsHtml + '</div>'
    + '<div id="twitch-channels-add">'
    + '<input type="text" id="guest-channel-input" placeholder="nom de chaîne twitch…"'
    + ' style="flex:1" onkeydown="if(event.key===\'Enter\') addGuestChannel()">'
    + '<button class="btn btn-success" onclick="addGuestChannel()">+ Ajouter</button>'
    + '</div>'
    + '<div id="guest-channel-error" style="color:var(--c-offline);font-size:0.85em;margin-top:6px;display:none"></div>'
    + '<p style="color:var(--text-muted);font-size:0.8em;margin-top:10px">'
    + 'Le broadcaster doit avoir autorisé le bot (scope <code>channel:bot</code>) pour que Wally puisse parler.'
    + '</p>'
    + '</div>';
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
      if (data.type === 'twitch_auth') {
        _onTwitchAuthSuccess(data.account, data.username);
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
  el.scrollTop = el.scrollHeight;
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

  // Build structure once; skip if log-stream already created by _renderSystemeLogs
  if (!el.querySelector('.mem-subnav') && !document.getElementById('log-stream')) {
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
    el.innerHTML = '<div class="card"><p style="color:var(--text-secondary)">Aucune connexion enregistrée</p></div>';
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

document.addEventListener('DOMContentLoaded', async () => {
  // Check if already authenticated
  if (getToken()) {
    enterAdmin();
  } else {
    showAuthModal();
  }

  // Restore tab from hash
  const hash = location.hash.replace('#', '');
  if (hash && getToken()) {
    showTab(hash);
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

function renderMemoryTab(targetEl) {
  const el = targetEl || document.getElementById('tab-memory') || document.getElementById('memoire-sub-users');
  if (!el) return;
  // Build toolbar with rows for responsive layout
  var toolbar = document.createElement('div');
  toolbar.className = 'mem-toolbar';

  var search = document.createElement('input');
  search.type = 'text';
  search.className = 'mem-search';
  search.id = 'mem-search';
  search.placeholder = 'Rechercher un utilisateur...';
  search.setAttribute('aria-label', 'Recherche utilisateur');
  toolbar.appendChild(search);

  var row = document.createElement('div');
  row.className = 'mem-toolbar-row';

  var pills = document.createElement('div');
  pills.className = 'mem-platform-pills';
  ['', 'discord', 'twitch'].forEach(function(p) {
    var btn = document.createElement('button');
    btn.className = 'mem-platform-pill' + (p === '' ? ' active' : '');
    btn.dataset.platform = p;
    btn.textContent = p === '' ? 'Tous' : p.charAt(0).toUpperCase() + p.slice(1);
    btn.onclick = function() { setMemPlatform(btn); };
    pills.appendChild(btn);
  });
  row.appendChild(pills);

  var sortSel = document.createElement('select');
  sortSel.className = 'mem-sort-select';
  sortSel.id = 'mem-sort';
  sortSel.onchange = function() { setMemSort(sortSel.value); };
  [['memories','Mémoires'],['trust','Trust'],['love','Love'],['name','Nom']].forEach(function(o) {
    var opt = document.createElement('option');
    opt.value = o[0]; opt.textContent = o[1];
    sortSel.appendChild(opt);
  });
  row.appendChild(sortSel);

  var toggleLabel = document.createElement('label');
  toggleLabel.className = 'mem-toggle';
  toggleLabel.onclick = function() { toggleMemShowAll(); };
  var track = document.createElement('div');
  track.className = 'mem-toggle-track';
  track.id = 'mem-toggle-track';
  var thumb = document.createElement('div');
  thumb.className = 'mem-toggle-thumb';
  track.appendChild(thumb);
  toggleLabel.appendChild(track);
  var toggleSpan = document.createElement('span');
  toggleSpan.textContent = 'Sans mémoire';
  toggleLabel.appendChild(toggleSpan);
  row.appendChild(toggleLabel);

  var syncBtn = document.createElement('button');
  syncBtn.className = 'mem-action-btn';
  syncBtn.textContent = '↻ Sync';
  syncBtn.onclick = function() { syncMemoryUsers(); };
  row.appendChild(syncBtn);

  var analyzeBtn = document.createElement('button');
  analyzeBtn.className = 'mem-action-btn';
  analyzeBtn.textContent = '🔗 Analyser';
  analyzeBtn.onclick = function() { analyzeLinks(); };
  row.appendChild(analyzeBtn);

  toolbar.appendChild(row);
  el.appendChild(toolbar);

  var pendingDiv = document.createElement('div');
  pendingDiv.id = 'mem-pending-links';
  el.appendChild(pendingDiv);

  var bannerDiv = document.createElement('div');
  bannerDiv.id = 'mem-link-banner';
  bannerDiv.style.display = 'none';
  el.appendChild(bannerDiv);

  var grid = document.createElement('div');
  grid.className = 'mem-grid';
  grid.id = 'mem-grid';
  el.appendChild(grid);

  // Wire search with debounce
  var searchInput = document.getElementById('mem-search');
  if (searchInput) {
    searchInput.addEventListener('input', function() {
      clearTimeout(_memSearchTimer);
      _memSearchTimer = setTimeout(function() { loadMemoryUsers(); }, 300);
    });
  }

  loadMemoryUsers();
  pollLinksBadge();
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
  params.set('show_all', '1');
  params.set('limit', '200');
  if (_memSortBy) params.set('sort_by', _memSortBy);
  var url = '/api/admin/memory/users' + (params.toString() ? '?' + params : '');
  var r = await apiFetch(url);
  if (!r || !r.ok) return;
  var data = await r.json();
  var users = data.users;
  _memCurrentUsers = users;

  // Client-side filters: platform + show/hide users with no memories
  var filtered = users;
  if (!_memShowAll) {
    filtered = filtered.filter(function(u) { return (u.memory_count || 0) > 0; });
  }
  if (_memPlatformFilter) {
    filtered = filtered.filter(function(u) { return u.platform === _memPlatformFilter; });
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
      + '<button class="mem-card-delete" onclick="event.stopPropagation();deleteUser(\'' + escAttr(u.user_id) + '\',\'' + escAttr(displayName) + '\')" title="Supprimer l\'utilisateur">🗑</button>'
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

  // Fetch aliases
  var aliasesR = await apiFetch('/api/admin/aliases?canonical_uid=' + encodeURIComponent(userId));
  var aliases = aliasesR && aliasesR.ok ? (await aliasesR.json()) : [];

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

  // Build alias section HTML
  var aliasHtml = '<div class="mem-linked-section" id="alias-section-' + escAttr(userId) + '">'
    + '<div class="mem-linked-title">Alias connus</div>'
    + '<div class="mem-linked-pills" id="alias-pills-' + escAttr(userId) + '">'
    + (aliases.length === 0 ? '<span style="color:var(--text-muted);font-size:0.8rem">Aucun alias</span>' : '')
    + aliases.map(function(a) {
        var srcTag = a.source === 'llm' ? 'LLM' : 'Manuel';
        var srcColor = a.source === 'llm' ? '#06b6d4' : '#22c55e';
        return '<div class="mem-linked-pill">'
          + escHtml(a.nickname)
          + ' <span style="font-size:0.65rem;padding:1px 5px;border-radius:4px;background:' + srcColor + '22;color:' + srcColor + '">' + srcTag + '</span>'
          + '<button class="mem-linked-pill-unlink" onclick="deleteModalAlias(\'' + escAttr(a.nickname) + '\',\'' + escAttr(userId) + '\')" title="Supprimer">\u2715</button>'
          + '</div>';
      }).join('')
    + '</div>'
    + '<div style="display:flex;gap:8px;margin-top:8px">'
    + '<input type="text" id="alias-input-' + escAttr(userId) + '" placeholder="Ajouter un alias..." class="mem-modal-search" style="flex:1;min-width:0">'
    + '<button class="mem-modal-action add" style="white-space:nowrap" onclick="addModalAlias(\'' + escAttr(userId) + '\')">Ajouter</button>'
    + '</div>'
    + '</div>';

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
    + '<button class="mem-modal-action danger" onclick="deleteUser(\'' + escAttr(userId) + '\',\'' + escAttr(displayName) + '\')" title="Supprime l\'utilisateur et toutes ses mémoires">🗑 Supprimer l\'utilisateur</button>'
    + '</div>'
    + '<div id="modal-add-form"></div>'
    + '<div class="mem-modal-toolbar">'
    + '<select class="mem-sort-select" id="modal-mem-sort" onchange="sortModalMemories(this.value)">'
    + '<option value="default">Tri par défaut</option>'
    + '<option value="recent">Plus récent</option>'
    + '<option value="oldest">Plus ancien</option>'
    + '</select>'
    + '<input type="text" class="mem-modal-search" id="modal-mem-search" placeholder="🔍 Rechercher..." oninput="filterModalMemories(this.value)">'
    + '</div>'
    + '<div id="modal-categories">' + categoriesHtml + '</div>'
    + linkedHtml
    + aliasHtml;

  backdrop.appendChild(modal);
  modal._memories = memories;
  modal._userId = userId;
  modal._userData = userData;
  document.body.appendChild(backdrop);
}

function sortModalMemories(sortBy) {
  var modal = document.querySelector('.mem-modal');
  if (!modal || !modal._memories) return;
  var memories = modal._memories.slice();

  if (sortBy === 'recent') {
    memories.sort(function(a, b) {
      var da = new Date(a.created_at || a.date || 0);
      var db = new Date(b.created_at || b.date || 0);
      return db - da;
    });
  } else if (sortBy === 'oldest') {
    memories.sort(function(a, b) {
      var da = new Date(a.created_at || a.date || 0);
      var db = new Date(b.created_at || b.date || 0);
      return da - db;
    });
  }

  var grouped = {};
  MEM_CATEGORIES.forEach(function(cat) { grouped[cat.key] = []; });
  memories.forEach(function(m) {
    var catKey = m.category || '';
    if (!grouped[catKey]) grouped[catKey] = grouped[''];
    grouped[catKey].push(m);
  });

  if (sortBy === 'default') {
    Object.keys(grouped).forEach(function(key) {
      grouped[key].sort(function(a, b) {
        var da = new Date(b.updated_at || b.created_at || 0);
        var db = new Date(a.updated_at || a.created_at || 0);
        return da - db;
      });
    });
  }

  var userId = modal._userId;
  var platform = (modal._userData || {}).platform || userId.split(':')[0];
  var categoriesHtml = '';
  MEM_CATEGORIES.forEach(function(cat) {
    var items = grouped[cat.key] || [];
    if (items.length === 0) return;
    categoriesHtml += '<div class="mem-category" data-cat="' + escAttr(cat.key) + '">'
      + '<div class="mem-category-header" onclick="toggleMemCategory(this)">'
      + '<span class="mem-category-chevron">\u25bc</span>'
      + '<span class="mem-category-name ' + escAttr(cat.css) + '">' + escHtml(cat.label) + '</span>'
      + '<span class="mem-category-count">(' + items.length + ')</span>'
      + '</div>'
      + '<div class="mem-category-body">'
      + items.map(function(m) {
          var isOwn = (m.source || '') === userId || (m.source_platform || '') === platform;
          var sourceIcon = isOwn ? '\ud83e\udd16' : '\u270d\ufe0f';
          var dateStr = m.updated_at || m.created_at;
          var shortDate = dateStr ? new Date(dateStr).toLocaleString('fr', { day:'numeric', month:'short' }) : '';
          return '<div class="mem-entry" id="mem-entry-' + escAttr(m.id) + '" style="border-left:2px solid ' + cat.color + '4d">'
            + '<span class="mem-entry-text" id="mem-text-' + escAttr(m.id) + '">' + escHtml(m.memory) + '</span>'
            + '<span class="mem-entry-source" title="' + (isOwn ? 'Auto-extrait' : 'Ajout\u00e9 manuellement') + '">' + sourceIcon + '</span>'
            + '<span class="mem-entry-date">' + escHtml(shortDate) + '</span>'
            + '<div class="mem-entry-actions">'
            + '<button class="mem-entry-action" onclick="startModalEditMemory(\'' + escAttr(userId) + '\',\'' + escAttr(m.id) + '\')" title="Modifier">\u270f\ufe0f</button>'
            + '<button class="mem-entry-action" onclick="deleteModalMemory(\'' + escAttr(userId) + '\',\'' + escAttr(m.id) + '\')" title="Supprimer">\ud83d\uddd1</button>'
            + '</div></div>';
        }).join('')
      + '</div></div>';
  });

  if (categoriesHtml === '') {
    categoriesHtml = '<div class="mem-empty-state">Aucun souvenir enregistr\u00e9.</div>';
  }

  var container = document.getElementById('modal-categories');
  if (container) container.innerHTML = categoriesHtml;
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
    + ' style="flex:1;font-size:11px;background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;padding:4px 8px;color:#e2e8f0"'
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

async function deleteUser(userId, displayName) {
  if (!confirm('Supprimer l\'utilisateur "' + displayName + '" et toutes ses mémoires ?')) return;
  var r = await apiFetch(
    '/api/admin/memory/users/' + encodeURIComponent(userId),
    { method: 'DELETE' }
  );
  if (r && r.ok) {
    toast('Utilisateur supprimé', 'success');
    // Fermer la modale si ouverte
    var bdrop = document.querySelector('.mem-modal-backdrop');
    if (bdrop) bdrop.remove();
    // Retirer la carte du DOM immédiatement
    var card = document.querySelector('.mem-card[data-uid="' + userId.replace(/"/g, '\\"') + '"]');
    if (card) card.remove();
    // Recharger pour mettre à jour les compteurs
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

// ── Alias Modal Helpers ────────────────────────────────────────────

async function addModalAlias(userId) {
  var input = document.getElementById('alias-input-' + userId);
  if (!input) return;
  var nickname = input.value.trim();
  if (!nickname) return;
  var r = await apiFetch('/api/admin/aliases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nickname: nickname, canonical_uid: userId })
  });
  if (!r || !r.ok) { var e = r ? await r.json().catch(function() { return {}; }) : {}; toast(e.detail || 'Erreur lors de l\'ajout', 'error'); return; }
  input.value = '';
  await _refreshAliasPills(userId);
}

async function deleteModalAlias(nickname, userId) {
  var r = await apiFetch('/api/admin/aliases/' + encodeURIComponent(nickname), { method: 'DELETE' });
  if (!r || !r.ok) { toast('Erreur lors de la suppression', 'error'); return; }
  await _refreshAliasPills(userId);
}

async function _refreshAliasPills(userId) {
  var r = await apiFetch('/api/admin/aliases?canonical_uid=' + encodeURIComponent(userId));
  if (!r || !r.ok) return;
  var aliases = await r.json();
  var container = document.getElementById('alias-pills-' + userId);
  if (!container) return;
  container.innerHTML = aliases.length === 0
    ? '<span style="color:var(--text-muted);font-size:0.8rem">Aucun alias</span>'
    : aliases.map(function(a) {
        var srcTag = a.source === 'llm' ? 'LLM' : 'Manuel';
        var srcColor = a.source === 'llm' ? '#06b6d4' : '#22c55e';
        return '<div class="mem-linked-pill">'
          + escHtml(a.nickname)
          + ' <span style="font-size:0.65rem;padding:1px 5px;border-radius:4px;background:' + srcColor + '22;color:' + srcColor + '">' + srcTag + '</span>'
          + '<button class="mem-linked-pill-unlink" onclick="deleteModalAlias(\'' + escAttr(a.nickname) + '\',\'' + escAttr(userId) + '\')" title="Supprimer">\u2715</button>'
          + '</div>';
      }).join('');
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

function renderGlobalMemoryTab(targetEl) {
  const el = targetEl || document.getElementById('tab-global-memory') || document.getElementById('memoire-sub-global');
  if (!el) return;
  el.innerHTML = `
    <div style="max-width:800px;margin:0 auto;padding:20px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
        <div>
          <h2 style="margin:0;font-size:1.3rem">Mémoire communautaire</h2>
          <p style="margin:4px 0 0;font-size:0.82rem;color:var(--text-muted)">
            Faits sur le serveur et la communauté, retrouvés par pertinence sémantique.
            Seuls les faits pertinents au message en cours sont injectés.
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

// ── Liaisons de comptes (fonctions utilitaires conservées) ─────────────────────

async function analyzeLinks() {
  const r = await apiFetch('/api/admin/links/analyze', { method: 'POST' });
  if (r && r.ok) {
    toast('Analyse déclenchée', 'success');
    await pollLinksBadge();
  } else {
    toast('Erreur analyse', 'error');
  }
}

async function acceptLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/accept`, { method: 'POST' });
  if (r && r.ok) {
    toast('Liaison acceptée — mémoires fusionnées', 'success');
    await Promise.all([loadMemoryUsers(), pollLinksBadge()]);
  } else {
    toast('Erreur', 'error');
  }
}

async function rejectLink(id) {
  const r = await apiFetch(`/api/admin/links/${id}/reject`, { method: 'POST' });
  if (r && r.ok) {
    toast('Liaison rejetée', 'success');
    await Promise.all([loadMemoryUsers(), pollLinksBadge()]);
  } else {
    toast('Erreur', 'error');
  }
}

async function unlinkAccounts(id) {
  const r = await apiFetch(`/api/admin/links/${id}/unlink`, { method: 'POST' });
  if (r && r.ok) {
    toast('Comptes déliés', 'success');
    await Promise.all([loadMemoryUsers(), pollLinksBadge()]);
  } else {
    const err = r ? await r.json().catch(() => ({})) : {};
    toast(err.detail || 'Erreur déliaison', 'error');
  }
}

async function pollLinksBadge() {
  if (!getToken()) return;
  try {
    const r = await apiFetch('/api/admin/links?status=pending');
    if (!r || !r.ok) return;
    const { proposals } = await r.json();
    const badge = document.getElementById('links-badge');
    if (badge) {
      const count = proposals.length;
      badge.textContent = count;
      badge.style.display = count > 0 ? 'flex' : 'none';
    }
    renderPendingLinks(proposals);
  } catch (e) { /* ignore */ }
}

function renderPendingLinks(proposals) {
  var container = document.getElementById('mem-pending-links');
  if (!container) return;
  if (!proposals || proposals.length === 0) {
    container.textContent = '';
    return;
  }

  var wrapper = document.createElement('div');
  wrapper.className = 'mem-pending-links';

  var title = document.createElement('div');
  title.className = 'mem-pending-links-title';
  title.textContent = '🔗 ' + proposals.length + ' compte(s) à vérifier';
  wrapper.appendChild(title);

  proposals.forEach(function(p) {
    var card = document.createElement('div');
    card.className = 'mem-pending-link-card';

    var names = document.createElement('div');
    names.className = 'mem-pending-link-names';

    var canonical = document.createElement('span');
    canonical.className = 'mem-pending-link-user';
    canonical.textContent = p.canonical_username || p.canonical_id;
    canonical.title = p.canonical_id;
    names.appendChild(canonical);

    var arrow = document.createElement('span');
    arrow.className = 'mem-pending-link-arrow';
    arrow.textContent = '↔';
    names.appendChild(arrow);

    var alias = document.createElement('span');
    alias.className = 'mem-pending-link-user';
    alias.textContent = p.alias_username || p.alias_id;
    alias.title = p.alias_id;
    names.appendChild(alias);

    card.appendChild(names);

    if (p.confidence != null) {
      var score = document.createElement('span');
      score.className = 'mem-pending-link-score';
      score.textContent = Math.round(p.confidence * 100) + '%';
      card.appendChild(score);
    }

    var actions = document.createElement('div');
    actions.className = 'mem-pending-link-actions';

    var acceptBtn = document.createElement('button');
    acceptBtn.className = 'mem-pending-link-btn accept';
    acceptBtn.textContent = '✓';
    acceptBtn.title = 'Accepter';
    acceptBtn.onclick = function() { acceptLink(p.id); };
    actions.appendChild(acceptBtn);

    var rejectBtn = document.createElement('button');
    rejectBtn.className = 'mem-pending-link-btn reject';
    rejectBtn.textContent = '✕';
    rejectBtn.title = 'Rejeter';
    rejectBtn.onclick = function() { rejectLink(p.id); };
    actions.appendChild(rejectBtn);

    card.appendChild(actions);
    wrapper.appendChild(card);
  });

  container.textContent = '';
  container.appendChild(wrapper);
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
    el.innerHTML = '<div class="card"><p style="color:var(--text-secondary)">Aucune connexion enregistrée</p></div>';
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
    questionsHtml = '<p style="color:var(--text-secondary);padding:8px">Aucune question en attente</p>';
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
            <span style="color:var(--text-secondary);margin-left:8px">tentative ${parseInt(q.attempts, 10)}/3</span>
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
    barsHtml = '<p style="color:var(--text-secondary);padding:8px">Aucune donnée</p>';
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

// ── Paramètres Tab (Émotions · LLM · Images) ─────────────────────────────────


function renderParametresTab() {
  const el = document.getElementById('tab-admin-parametres');
  if (!el) return;

  if (!el.querySelector('.mem-subnav')) {
    el.innerHTML = `
      <div class="mem-subnav">
        <button class="mem-subnav-pill active" data-subtab="emotions" onclick="switchParametresSubTab('emotions')">Émotions</button>
        <button class="mem-subnav-pill" data-subtab="llm" onclick="switchParametresSubTab('llm')">LLM</button>
        <button class="mem-subnav-pill" data-subtab="images" onclick="switchParametresSubTab('images')">Images</button>
      </div>
      <div class="mem-subnav-content active" id="parametres-sub-emotions"></div>
      <div class="mem-subnav-content" id="parametres-sub-llm"></div>
      <div class="mem-subnav-content" id="parametres-sub-images"></div>
    `;
  }

  switchParametresSubTab(_parametresSubTab);
}

function switchParametresSubTab(subtab) {
  _parametresSubTab = subtab;
  const el = document.getElementById('tab-admin-parametres');
  if (!el) return;

  el.querySelectorAll('.mem-subnav-pill').forEach(function(p) {
    p.classList.toggle('active', p.dataset.subtab === subtab);
  });
  el.querySelectorAll('.mem-subnav-content').forEach(function(c) { c.classList.remove('active'); });
  const panel = document.getElementById('parametres-sub-' + subtab);
  if (panel) panel.classList.add('active');

  if (subtab === 'emotions') {
    _renderParametresEmotions(panel);
  } else if (subtab === 'llm') {
    _renderParametresLLM(panel);
  } else if (subtab === 'images') {
    _renderParametresImages(panel);
  }
}

async function _renderParametresEmotions(panel) {
  if (!panel || panel.children.length > 0) return;

  // Move config-form-container (emotions + lambdas + bot-general + spam sections) here
  // We load config then render only the emotion-related cards
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const cfg = await r.json();

  const wrapper = document.createElement('div');
  wrapper.id = 'parametres-emotions-inner';

  // Emotions sliders card
  const emotCard = document.createElement('div');
  emotCard.className = 'card config-section';
  emotCard.innerHTML = `
    <div class="config-section-title">ÉMOTIONS</div>
    <div id="gauges-parametres-inline" role="group" aria-label="Controle des emotions"></div>
    <div class="mt-4">
      <button class="btn btn-danger" onclick="resetEmotions()">RESET À NEUTRE (0.5)</button>
    </div>
  `;
  wrapper.appendChild(emotCard);

  // Decay lambdas card
  const lambdaCard = document.createElement('div');
  lambdaCard.className = 'card config-section';
  const lambdaRows = Object.entries(cfg.emotions).filter(function([name]) { return name !== 'boredom'; }).map(function([name, ec]) {
    const lam = ec.decay_lambda;
    const timeToZeroH = lam > 0 ? (Math.log(1/0.01)) / lam : Infinity;
    const timeLabel = timeToZeroH === Infinity ? '∞' : timeToZeroH < 1 ? Math.round(timeToZeroH * 60) + ' min' : Math.round(timeToZeroH * 10) / 10 + ' h';
    return `<div class="field-group" style="display:flex;align-items:center;gap:12px">
      <label class="field-label" for="cfg-lambda-${name}" style="color:${EMOTION_COLORS[name] || 'var(--text-muted)'};min-width:100px">${name.toUpperCase()} λ</label>
      <input type="number" id="cfg-lambda-${name}" min="0" max="1" step="0.001" value="${lam}" style="width:90px" oninput="updateDecayTime(this,'${name}')">
      <span id="decay-time-${name}" style="font-size:0.8rem;color:var(--text-secondary);white-space:nowrap">100→0% en <strong style="color:#e2e8f0">${timeLabel}</strong></span>
    </div>`;
  }).join('');
  const boredomRise = cfg.emotions.boredom && cfg.emotions.boredom.boredom_rise_per_hour != null ? cfg.emotions.boredom.boredom_rise_per_hour : 1.2;
  const boredomH = boredomRise > 0 ? 1/boredomRise : Infinity;
  const boredomLabel = boredomH === Infinity ? '∞' : boredomH < 1 ? Math.round(boredomH*60)+' min' : Math.round(boredomH*10)/10+' h';
  lambdaCard.innerHTML = `
    <div class="config-section-title">DÉCROISSANCE ÉMOTIONS (λ)</div>
    <p style="font-size:0.75rem;color:var(--text-muted);margin:0 0 12px">λ = vitesse de décroissance par heure. Plus la valeur est élevée, plus l'émotion retombe vite. Boredom monte avec l'inactivité et n'utilise pas ce paramètre.</p>
    ${lambdaRows}
    <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">
      <div style="display:flex;align-items:center;gap:12px">
        <label class="field-label" for="cfg-boredom-rise" style="color:${EMOTION_COLORS['boredom'] || 'var(--text-muted)'};min-width:100px">BOREDOM ↑/h</label>
        <input type="number" id="cfg-boredom-rise" min="0" max="10" step="0.1" value="${boredomRise}" style="width:90px" oninput="updateBoredomTime(this)">
        <span id="boredom-time-info" style="font-size:0.8rem;color:var(--text-secondary);white-space:nowrap">0→100% en <strong style="color:#e2e8f0">${boredomLabel}</strong></span>
      </div>
      <p style="font-size:0.75rem;color:var(--text-muted);margin:8px 0 0">Vitesse de montée de l'ennui par heure d'inactivité. 1.2 = ennui max en ~50 min.</p>
    </div>
    <button class="btn btn-success" onclick="saveEmotionLambdas()">💾 SAUVEGARDER</button>
  `;
  wrapper.appendChild(lambdaCard);

  // Bot général + anti-spam cards
  const botCard = document.createElement('div');
  botCard.className = 'card config-section';
  botCard.innerHTML = `
    <div class="config-section-title">BOT GÉNÉRAL</div>
    <div class="field-group">
      <label class="field-label" for="cfg-lang">Langue par défaut</label>
      <input type="text" id="cfg-lang" value="${cfg.bot.language_default || ''}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-journal-time">Heure journal (HH:MM)</label>
      <input type="text" id="cfg-journal-time" value="${cfg.bot.journal_time || ''}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-ctx-size">Taille fenêtre contexte</label>
      <input type="number" id="cfg-ctx-size" value="${cfg.bot.context_window_size || 20}">
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
      <p style="font-size:0.7rem;color:var(--text-muted);margin-top:4px">Alertes coûts et erreurs envoyées dans ce salon</p>
    </div>
    <button class="btn btn-success" onclick="saveBotGeneral()">💾 SAUVEGARDER</button>
  `;
  wrapper.appendChild(botCard);

  const spamCard = document.createElement('div');
  spamCard.className = 'card config-section';
  spamCard.innerHTML = `
    <div class="config-section-title">ANTI-SPAM DISCORD</div>
    <div class="field-group" style="display:flex;align-items:center;gap:12px">
      <label class="field-label" style="margin:0" for="cfg-spam-enabled">Activé</label>
      <input type="checkbox" id="cfg-spam-enabled" ${(cfg.discord.spam_detection || {}).enabled !== false ? 'checked' : ''}>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-max">Messages max</label>
      <input type="number" id="cfg-spam-max" min="3" max="50" value="${(cfg.discord.spam_detection || {}).max_messages || 10}">
      <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Nombre de messages avant déclenchement</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-window">Fenêtre (secondes)</label>
      <input type="number" id="cfg-spam-window" min="30" max="600" value="${(cfg.discord.spam_detection || {}).window_seconds || 120}">
      <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Période de temps pour compter les messages</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-mute">Durée mute (minutes)</label>
      <input type="number" id="cfg-spam-mute" min="1" max="60" value="${(cfg.discord.spam_detection || {}).mute_minutes || 5}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-anger">Delta colère par message muté</label>
      <input type="number" id="cfg-spam-anger" min="0.01" max="0.2" step="0.01" value="${(cfg.discord.spam_detection || {}).spam_anger_delta || 0.05}">
      <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Augmentation de la colère quand un utilisateur muté continue de parler</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-exempt">Channels exemptés (IDs séparés par virgule)</label>
      <input type="text" id="cfg-spam-exempt" value="${((cfg.discord.spam_detection || {}).exempt_channels || []).join(', ')}">
      <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Ces salons ignorent la détection de spam</p>
    </div>
    <button class="btn btn-success" onclick="saveSpamConfig()">💾 SAUVEGARDER</button>
  `;
  wrapper.appendChild(spamCard);

  panel.appendChild(wrapper);

  // Build emotion sliders
  buildGauges('gauges-parametres-inline', true);
  if (currentEmotions && Object.keys(currentEmotions).length > 0) {
    updateEmotionGauges(currentEmotions);
  }
  loadNotificationChannels(cfg);
}

async function _renderParametresLLM(panel) {
  if (!panel || panel.children.length > 0) return;

  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const cfg = await r.json();
  const [models, claudeModels] = await Promise.all([loadOpenAIModels(), loadClaudeModels()]);

  const REASONING_EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'];
  const TEXT_VERBOSITIES = ['low', 'medium', 'high'];
  const THINKING_TYPES = ['disabled', 'enabled', 'adaptive'];
  const THINKING_EFFORTS = ['low', 'medium', 'high', 'max'];

  const card = document.createElement('div');
  card.className = 'card config-section';
  card.innerHTML = `
    <div class="config-section-title">LLM — MODÈLES</div>
    <div class="field-group">
      <label class="field-label" for="cfg-primary-provider">Provider principal</label>
      <select id="cfg-primary-provider" onchange="onProviderChange()">
        <option value="openai" ${(cfg.llm?.primary?.provider || 'openai') === 'openai' ? 'selected' : ''}>OpenAI</option>
        <option value="claude" ${(cfg.llm?.primary?.provider || 'openai') === 'claude' ? 'selected' : ''}>Claude (Anthropic)</option>
      </select>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-primary-model">Modèle principal</label>
      <select id="cfg-primary-model">
        ${models.map(function(m) { return '<option value="' + m + '"' + (m === cfg.openai.primary_model ? ' selected' : '') + '>' + m + '</option>'; }).join('')}
      </select>
      <select id="cfg-primary-model-claude" style="display:none">
        ${claudeModels.map(function(m) { return '<option value="' + m + '"' + (m === (cfg.llm?.primary?.model || '') ? ' selected' : '') + '>' + m + '</option>'; }).join('')}
      </select>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-secondary-provider">Provider secondaire</label>
      <select id="cfg-secondary-provider" onchange="onProviderChange()">
        <option value="openai" ${(cfg.llm?.secondary?.provider || 'openai') === 'openai' ? 'selected' : ''}>OpenAI</option>
        <option value="claude" ${(cfg.llm?.secondary?.provider || 'openai') === 'claude' ? 'selected' : ''}>Claude (Anthropic)</option>
      </select>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-secondary-model">Modèle secondaire</label>
      <select id="cfg-secondary-model">
        ${models.map(function(m) { return '<option value="' + m + '"' + (m === cfg.openai.secondary_model ? ' selected' : '') + '>' + m + '</option>'; }).join('')}
      </select>
      <select id="cfg-secondary-model-claude" style="display:none">
        ${claudeModels.map(function(m) { return '<option value="' + m + '"' + (m === (cfg.llm?.secondary?.model || '') ? ' selected' : '') + '>' + m + '</option>'; }).join('')}
      </select>
    </div>
    <div id="openai-specific-settings">
      <div class="field-group">
        <label class="field-label" for="cfg-reasoning-effort">Niveau d'effort (reasoning) <span style="font-size:0.7rem;color:var(--text-muted)">OpenAI only</span></label>
        <select id="cfg-reasoning-effort">
          ${REASONING_EFFORTS.map(function(e) { return '<option value="' + e + '"' + (e === cfg.openai.reasoning_effort ? ' selected' : '') + '>' + e.toUpperCase() + '</option>'; }).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-text-verbosity">Verbosité des réponses <span style="font-size:0.7rem;color:var(--text-muted)">OpenAI only</span></label>
        <select id="cfg-text-verbosity">
          ${TEXT_VERBOSITIES.map(function(v) { return '<option value="' + v + '"' + (v === cfg.openai.text_verbosity ? ' selected' : '') + '>' + v.toUpperCase() + '</option>'; }).join('')}
        </select>
      </div>
    </div>
    <div id="claude-specific-settings" style="display:none">
      <div class="field-group">
        <label class="field-label" for="cfg-thinking-type">Réflexion (thinking) <span style="font-size:0.7rem;color:var(--text-muted)">Claude only</span></label>
        <select id="cfg-thinking-type" onchange="onThinkingTypeChange()">
          ${THINKING_TYPES.map(function(t) { return '<option value="' + t + '"' + (t === (cfg.llm?.primary?.thinking_type || 'disabled') ? ' selected' : '') + '>' + (t === 'disabled' ? 'DÉSACTIVÉ' : t === 'adaptive' ? 'ADAPTATIF' : 'ACTIVÉ (budget fixe)') + '</option>'; }).join('')}
        </select>
      </div>
      <div id="thinking-effort-group" class="field-group" style="display:none">
        <label class="field-label" for="cfg-thinking-effort">Niveau d'effort thinking</label>
        <select id="cfg-thinking-effort">
          ${THINKING_EFFORTS.map(function(e) { return '<option value="' + e + '"' + (e === (cfg.llm?.primary?.thinking_effort || 'medium') ? ' selected' : '') + '>' + e.toUpperCase() + '</option>'; }).join('')}
        </select>
        <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">LOW = rapide · MEDIUM = équilibré · HIGH = défaut, pense souvent · MAX = max (Opus 4.6 only)</p>
      </div>
      <div id="thinking-budget-group" class="field-group" style="display:none">
        <label class="field-label" for="cfg-thinking-budget">Budget tokens thinking</label>
        <input type="number" id="cfg-thinking-budget" min="1000" max="128000" step="1000" value="${cfg.llm?.primary?.thinking_budget_tokens || 10000}">
        <p style="font-size:0.75rem;color:var(--text-muted);margin:4px 0 0">Doit être inférieur à max_tokens. 10k = standard, 50k+ = problèmes complexes</p>
      </div>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-max-tokens">Max output tokens</label>
      <input type="number" id="cfg-max-tokens" min="100" max="32000" value="${cfg.openai.max_tokens}">
    </div>
    <button class="btn btn-success" onclick="saveOpenAI()">💾 SAUVEGARDER</button>
    <p id="llm-restart-notice" style="display:none;font-size:0.75rem;color:#f59e0b;margin-top:8px">⚠️ Changement de provider — redémarrage requis pour prendre effet.</p>
  `;
  panel.appendChild(card);

  onProviderChange();
}

async function _renderParametresImages(panel) {
  if (!panel || panel.children.length > 0) return;

  // Delegate to loadOverlayConfig but only inject image_generation section
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const cfg = await r.json();
  const ig = cfg.image_generation || {};

  const section = document.createElement('div');
  section.className = 'overlay-section';
  const title = document.createElement('h3');
  title.textContent = 'Génération d\'images';
  section.appendChild(title);

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
    sel.id = id + '-p';
    sel.className = 'neo-select';
    options.forEach(function(o) {
      const opt = document.createElement('option');
      opt.value = o; opt.textContent = o;
      if (o === selected) opt.selected = true;
      sel.appendChild(opt);
    });
    return sel;
  }

  section.appendChild(makeFormRow('Modèle', makeSelect('ig-model', ['gpt-image-1.5','gpt-image-1','gpt-image-1-mini'], ig.model)));
  section.appendChild(makeFormRow('Qualité', makeSelect('ig-quality', ['low','medium','high'], ig.quality)));
  section.appendChild(makeFormRow('Taille', makeSelect('ig-size', ['1024x1024','1024x1536','1536x1024'], ig.size)));
  section.appendChild(makeFormRow('Format', makeSelect('ig-format', ['png','jpeg','webp'], ig.format)));
  section.appendChild(makeFormRow('Background', makeSelect('ig-background', ['auto','transparent','opaque'], ig.background)));

  const dlRow = document.createElement('div'); dlRow.className = 'form-row';
  const dlLabel = document.createElement('label'); dlLabel.textContent = 'Limite/jour (global)'; dlRow.appendChild(dlLabel);
  const dlInput = document.createElement('input'); dlInput.type = 'number'; dlInput.id = 'ig-daily-limit-p'; dlInput.className = 'neo-input'; dlInput.value = ig.daily_limit; dlInput.style.width = '80px'; dlRow.appendChild(dlInput);
  const dlHint = document.createElement('span'); dlHint.style.color = 'rgba(255,255,255,0.35)'; dlHint.style.fontSize = '0.78rem'; dlHint.textContent = '-1 = illimité'; dlRow.appendChild(dlHint);
  section.appendChild(dlRow);

  const puRow = document.createElement('div'); puRow.className = 'form-row';
  const puLabel = document.createElement('label'); puLabel.textContent = 'Limite/jour (par user)'; puRow.appendChild(puLabel);
  const puInput = document.createElement('input'); puInput.type = 'number'; puInput.id = 'ig-per-user-limit-p'; puInput.className = 'neo-input'; puInput.value = ig.per_user_limit; puInput.style.width = '80px'; puRow.appendChild(puInput);
  const puHint = document.createElement('span'); puHint.style.color = 'rgba(255,255,255,0.35)'; puHint.style.fontSize = '0.78rem'; puHint.textContent = '-1 = illimité'; puRow.appendChild(puHint);
  section.appendChild(puRow);

  const costEst = document.createElement('div'); costEst.className = 'form-row'; costEst.id = 'ig-cost-estimate-p'; costEst.style.color = 'var(--accent)'; costEst.style.fontWeight = '600'; costEst.style.fontSize = '0.85rem';
  section.appendChild(costEst);

  const saveBtn = document.createElement('button'); saveBtn.className = 'neo-btn'; saveBtn.textContent = 'Sauvegarder'; saveBtn.onclick = saveImageGenConfigParams;
  section.appendChild(saveBtn);

  panel.appendChild(section);

  // Update cost estimate
  async function updateCostEstimateParams() {
    const model = document.getElementById('ig-model-p')?.value;
    const quality = document.getElementById('ig-quality-p')?.value;
    const size = document.getElementById('ig-size-p')?.value;
    if (!model || !quality || !size) return;
    const r2 = await fetch('/api/public/gallery/estimate-cost?model=' + model + '&quality=' + quality + '&size=' + size);
    if (r2.ok) {
      const data = await r2.json();
      const elCost = document.getElementById('ig-cost-estimate-p');
      if (elCost) elCost.textContent = 'Coût estimé : $' + data.cost_usd.toFixed(4) + ' par image';
    }
  }
  updateCostEstimateParams();
  document.getElementById('ig-model-p')?.addEventListener('change', updateCostEstimateParams);
  document.getElementById('ig-quality-p')?.addEventListener('change', updateCostEstimateParams);
  document.getElementById('ig-size-p')?.addEventListener('change', updateCostEstimateParams);
}

async function saveImageGenConfigParams() {
  const body = { image_generation: {
    model: document.getElementById('ig-model-p').value,
    quality: document.getElementById('ig-quality-p').value,
    size: document.getElementById('ig-size-p').value,
    format: document.getElementById('ig-format-p').value,
    background: document.getElementById('ig-background-p').value,
    daily_limit: parseInt(document.getElementById('ig-daily-limit-p').value),
    per_user_limit: parseInt(document.getElementById('ig-per-user-limit-p').value),
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config image sauvegardée', 'success');
}


// ── Système Tab (Logs · Twitch · Overlay · Instances) ────────────────────────


function renderSystemeTab() {
  const el = document.getElementById('tab-admin-systeme');
  if (!el) return;

  if (!el.querySelector('.mem-subnav')) {
    el.innerHTML = `
      <div class="mem-subnav">
        <button class="mem-subnav-pill active" data-subtab="logs" onclick="switchSystemeSubTab('logs')">Logs</button>
        <button class="mem-subnav-pill" data-subtab="twitch" onclick="switchSystemeSubTab('twitch')">Twitch</button>
        <button class="mem-subnav-pill" data-subtab="overlay" onclick="switchSystemeSubTab('overlay')">Overlay</button>
      </div>
      <div class="mem-subnav-content active" id="systeme-sub-logs"></div>
      <div class="mem-subnav-content" id="systeme-sub-twitch"></div>
      <div class="mem-subnav-content" id="systeme-sub-overlay"></div>
    `;
  }

  switchSystemeSubTab(_systemeSubTab);
}

function switchSystemeSubTab(subtab) {
  _systemeSubTab = subtab;
  const el = document.getElementById('tab-admin-systeme');
  if (!el) return;

  el.querySelectorAll('.mem-subnav-pill').forEach(function(p) {
    p.classList.toggle('active', p.dataset.subtab === subtab);
  });
  el.querySelectorAll('.mem-subnav-content').forEach(function(c) { c.classList.remove('active'); });
  const panel = document.getElementById('systeme-sub-' + subtab);
  if (panel) panel.classList.add('active');

  if (subtab === 'logs') {
    _renderSystemeLogs(panel);
  } else if (subtab === 'twitch') {
    _renderSystemeTwitch(panel);
  } else if (subtab === 'overlay') {
    _renderSystemeOverlay(panel);
  }
}

function _renderSystemeLogs(panel) {
  if (!panel) return;
  if (!panel.querySelector('.mem-subnav')) {
    // Build log sub-nav inside the systeme panel (reuse logs sub-tab structure)
    panel.innerHTML = `
      <div class="mem-subnav">
        <button class="mem-subnav-pill active" data-subtab="flux" onclick="switchLogsSubTabInSysteme('flux')">Flux</button>
        <button class="mem-subnav-pill" data-subtab="visitors" onclick="switchLogsSubTabInSysteme('visitors')">Visiteurs</button>
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
  // Activate first pill
  panel.querySelectorAll('.mem-subnav-pill').forEach(function(p) {
    p.classList.toggle('active', p.dataset.subtab === _logsSubTab);
  });
  panel.querySelectorAll('.mem-subnav-content').forEach(function(c) { c.classList.remove('active'); });
  const logPanel = panel.querySelector('#logs-sub-' + _logsSubTab);
  if (logPanel) logPanel.classList.add('active');
  if (_logsSubTab === 'visitors') loadVisitorsInPanel();
}

function switchLogsSubTabInSysteme(subtab) {
  _logsSubTab = subtab;
  const panel = document.getElementById('systeme-sub-logs');
  if (!panel) return;
  panel.querySelectorAll('.mem-subnav-pill').forEach(function(p) {
    p.classList.toggle('active', p.dataset.subtab === subtab);
  });
  panel.querySelectorAll('.mem-subnav-content').forEach(function(c) { c.classList.remove('active'); });
  const sub = panel.querySelector('#logs-sub-' + subtab);
  if (sub) sub.classList.add('active');
  if (subtab === 'flux') {
    requestAnimationFrame(function() {
      const logEl = document.getElementById('log-stream');
      if (logEl) logEl.scrollTop = logEl.scrollHeight;
    });
  } else if (subtab === 'visitors') {
    loadVisitorsInPanel();
  }
}

async function _renderSystemeTwitch(panel) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:var(--text-muted);padding:16px">Chargement...</p>';

  var statusR = await apiFetch('/api/admin/twitch/auth-status');
  var status  = statusR && statusR.ok ? await statusR.json() : null;

  var botConnected      = status && status.bot.connected;
  var streamerConnected = status && status.streamer.connected;
  var clientIdSet       = status ? status.client_id_set : false;

  var BOT_SCOPES      = 'user:read:chat · user:write:chat · user:bot · moderator:read:followers · chat:read · chat:edit';
  var STREAMER_SCOPES = 'channel:read:subscriptions · bits:read';

  function _authCard(id, icon, title, connected, username, scopes) {
    var dotColor   = connected ? '#22c55e' : '#ef4444';
    var statusText = connected ? (_escHtml(username) || 'Connecte') : 'Non connecte';
    var btnLabel   = connected ? 'Reconnecter' : 'Connecter';
    var btn = clientIdSet
      ? '<button class="btn btn-success" style="width:100%;margin-top:4px" onclick="startTwitchOAuth(\'' + id + '\')">' + btnLabel + '</button>'
      : '<p style="color:#f59e0b;font-size:0.8em;margin-top:8px">Configurer TWITCH_CLIENT_ID dans .env</p>';
    return '<div class="card" style="flex:1;min-width:220px;padding:20px">'
      + '<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">'
      + '<span style="font-size:1.5em">' + icon + '</span>'
      + '<div><div class="card-title" style="margin:0">' + title + '</div>'
      + '<div style="display:flex;align-items:center;gap:6px;margin-top:4px">'
      + '<span style="width:8px;height:8px;border-radius:50%;background:' + dotColor + ';display:inline-block"></span>'
      + '<span style="font-size:0.85em;color:' + (connected ? 'var(--text-primary)' : 'var(--text-muted)') + '">' + statusText + '</span>'
      + '</div></div></div>'
      + '<div style="font-size:0.75em;color:var(--text-muted);margin-bottom:14px;line-height:1.6"><strong>Scopes :</strong> ' + scopes + '</div>'
      + btn
      + '</div>';
  }

  // Charger les chaines invitees
  var chR = await apiFetch('/api/admin/twitch/channels');
  var channelsHtml = '';
  if (chR && chR.ok) {
    var channels = await chR.json();
    channelsHtml = channels.length === 0
      ? '<p style="color:var(--text-muted);margin-bottom:12px">Aucune chaine invitee.</p>'
      : channels.map(function(ch) {
          var dotClass   = ch.irc_connected ? 'connected' : 'pending';
          var badgeClass = ch.live ? 'live' : 'offline';
          var badgeText  = ch.live ? 'LIVE' : 'hors ligne';
          return '<div class="twitch-channel-card" id="guest-ch-' + ch.name + '">'
            + '<div class="tc-dot ' + dotClass + '"></div>'
            + '<span class="tc-name">' + ch.name + '</span>'
            + '<span class="tc-badge ' + badgeClass + '">' + badgeText + '</span>'
            + '<button class="tc-kick" onclick="removeGuestChannel(\'' + ch.name + '\')">Deconnecter</button>'
            + '</div>';
        }).join('');
  } else {
    channelsHtml = '<p style="color:var(--text-muted);font-size:0.85em">Twitch non demarre — connecte les comptes ci-dessus et redemarre.</p>';
  }

  var restartHtml = _twitchPendingRestart
    ? '<div style="margin-top:20px">'
      + '<button class="btn" style="background:#f59e0b;color:#000;font-weight:600;width:100%" onclick="restartTwitchContainer()">Redemarrer le container</button>'
      + '<p style="font-size:0.75em;color:var(--text-muted);margin-top:6px;text-align:center">Le dashboard sera indisponible ~10s.</p>'
      + '</div>'
    : '';

  panel.innerHTML = '<div style="padding:0 2px">'
    + '<div style="font-size:0.7em;letter-spacing:.08em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px">Authentification Twitch</div>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px">'
    + _authCard('bot',      '🤖', 'Compte Bot',     botConnected,      status && status.bot.username,      BOT_SCOPES)
    + _authCard('streamer', '📺', 'Compte Streamer', streamerConnected, status && status.streamer.username, STREAMER_SCOPES)
    + '</div>'
    + restartHtml
    + '<hr style="border-color:var(--border);margin:16px 0">'
    + '<div style="font-size:0.7em;letter-spacing:.08em;color:var(--text-muted);text-transform:uppercase;margin-bottom:12px">Chaines invitees</div>'
    + '<div id="guest-channels-list">' + channelsHtml + '</div>'
    + '<div id="twitch-channels-add">'
    + '<input type="text" id="guest-channel-input" placeholder="nom de chaine twitch..." style="flex:1" onkeydown="if(event.key===\'Enter\') addGuestChannel()">'
    + '<button class="btn btn-success" onclick="addGuestChannel()">+ Ajouter</button>'
    + '</div>'
    + '<div id="guest-channel-error" style="color:var(--c-offline);font-size:0.85em;margin-top:6px;display:none"></div>'
    + '<p style="color:var(--text-muted);font-size:0.8em;margin-top:10px">Le broadcaster doit avoir autorise le bot (scope channel:bot) pour que Wally puisse parler.</p>'
    + '</div>';

  // Vider le div legacy tab-admin-twitch pour eviter les doublons
  var twitchEl = document.getElementById('tab-admin-twitch');
  if (twitchEl) twitchEl.innerHTML = '';
}

async function _renderSystemeOverlay(panel) {
  if (!panel || panel.children.length > 0) return;

  const base = window.location.origin;
  const urlEmotion = base + '/overlay';
  const urlImage = base + '/overlay-image';

  // Load config to get image overlay state + command name
  const cfgR = await apiFetch('/api/admin/config');
  const cfg = cfgR && cfgR.ok ? await cfgR.json() : {};
  const oi = cfg.overlay_image || {};
  const imageEnabled = !!oi.enabled;
  const imageCmd = oi.command || '!image';

  panel.innerHTML = `
    <div class="overlay-cards-grid">

      <!-- Overlay Émotions -->
      <div class="card overlay-card">
        <div class="overlay-card-header">
          <div class="overlay-card-icon" style="background:rgba(234,179,8,0.1);border-color:rgba(234,179,8,0.2)">🎭</div>
          <div>
            <div class="card-title" style="margin:0">OVERLAY ÉMOTIONS</div>
            <div class="overlay-card-sub">Humeur en temps réel</div>
          </div>
        </div>
        <p class="overlay-card-desc">
          Affiche l'avatar, les jauges d'émotion et l'état de Wally en direct.
          Idéal en coin d'écran — fond transparent, compatible Browser Source OBS.
        </p>
        <div class="overlay-card-toggle-row">
          <span class="overlay-card-toggle-label">Afficher</span>
          <div class="overlay-switch" id="overlay-switch-emotion" style="cursor:pointer" onclick="toggleOverlayFromSysteme()">
            <div class="overlay-switch-knob"></div>
          </div>
          <span id="overlay-status-label-emotion" class="overlay-card-status">Masqué</span>
        </div>
        <div class="overlay-url-row">
          <span class="overlay-url-label">URL OBS</span>
          <code class="overlay-url-code" id="url-emotion">${urlEmotion}</code>
          <button class="overlay-copy-btn" onclick="copyOverlayUrl('url-emotion')">Copier</button>
        </div>
        <div class="overlay-url-hint">Browser Source · Largeur 400px · Hauteur 300px · Fond transparent</div>
      </div>

      <!-- Overlay Images -->
      <div class="card overlay-card">
        <div class="overlay-card-header">
          <div class="overlay-card-icon" style="background:rgba(6,182,212,0.1);border-color:rgba(6,182,212,0.2)">🖼️</div>
          <div>
            <div class="card-title" style="margin:0">OVERLAY IMAGES</div>
            <div class="overlay-card-sub">Galerie via commande Twitch</div>
          </div>
        </div>
        <p class="overlay-card-desc">
          Affiche une image de la galerie quand un viewer tape <code style="color:var(--accent)">${imageCmd}</code> dans le chat.
          Animation entrée/sortie configurable ci-dessous.
        </p>
        <div class="overlay-card-toggle-row">
          <span class="overlay-card-toggle-label">Activer</span>
          <div class="overlay-switch ${imageEnabled ? 'on' : ''}" id="overlay-switch-image" style="cursor:pointer" onclick="toggleOverlayImage()">
            <div class="overlay-switch-knob"></div>
          </div>
          <span id="overlay-status-label-image" class="overlay-card-status">${imageEnabled ? 'Activé' : 'Désactivé'}</span>
        </div>
        <div class="overlay-url-row">
          <span class="overlay-url-label">URL OBS</span>
          <code class="overlay-url-code" id="url-image">${urlImage}</code>
          <button class="overlay-copy-btn" onclick="copyOverlayUrl('url-image')">Copier</button>
        </div>
        <div class="overlay-url-hint">Browser Source · Largeur 1920px · Hauteur 1080px · Fond transparent</div>
      </div>
    </div>

    <!-- Image overlay config -->
    <div id="overlay-config-container-systeme"></div>
  `;

  pollOverlayStatusForSysteme();
  loadOverlayConfigInPanel(document.getElementById('overlay-config-container-systeme'));
}

async function toggleOverlayFromSysteme() {
  const r = await apiFetch('/api/admin/overlay/toggle', { method: 'POST' });
  if (r && r.ok) {
    const data = await r.json();
    updateOverlaySwitch(data.visible);
    const sw = document.getElementById('overlay-switch-emotion');
    const lbl = document.getElementById('overlay-status-label-emotion');
    if (sw) { if (data.visible) sw.classList.add('on'); else sw.classList.remove('on'); }
    if (lbl) lbl.textContent = data.visible ? 'Visible' : 'Masqué';
    toast(data.visible ? 'Overlay émotions visible' : 'Overlay émotions masqué');
  }
}

async function pollOverlayStatusForSysteme() {
  try {
    const r = await apiFetch('/api/admin/overlay/status');
    if (r && r.ok) {
      const data = await r.json();
      const sw = document.getElementById('overlay-switch-emotion');
      const lbl = document.getElementById('overlay-status-label-emotion');
      if (sw) { if (data.visible) sw.classList.add('on'); else sw.classList.remove('on'); }
      if (lbl) lbl.textContent = data.visible ? 'Visible' : 'Masqué';
    }
  } catch {}
}

async function toggleOverlayImage() {
  const sw = document.getElementById('overlay-switch-image');
  const lbl = document.getElementById('overlay-status-label-image');
  const isOn = sw && sw.classList.contains('on');
  const newEnabled = !isOn;
  const body = { overlay_image: { enabled: newEnabled } };
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) {
    if (sw) { if (newEnabled) sw.classList.add('on'); else sw.classList.remove('on'); }
    if (lbl) lbl.textContent = newEnabled ? 'Activé' : 'Désactivé';
    toast(newEnabled ? 'Overlay images activé' : 'Overlay images désactivé', 'success');
  }
}

function copyOverlayUrl(elId) {
  const el = document.getElementById(elId);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(function() {
    toast('URL copiée !', 'success');
  }).catch(function() {
    // Fallback for HTTP contexts
    const ta = document.createElement('textarea');
    ta.value = el.textContent;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast('URL copiée !', 'success');
  });
}

async function loadOverlayConfigInPanel(container) {
  if (!container) return;
  const r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) return;
  const cfg = await r.json();
  const oi = cfg.overlay_image || {};

  const oiSection = document.createElement('div');
  oiSection.className = 'overlay-section';
  const oiTitle = document.createElement('h3');
  oiTitle.textContent = 'Configuration — Overlay Images';
  oiSection.appendChild(oiTitle);

  function makeFormRow(labelText, inputEl) {
    const row = document.createElement('div'); row.className = 'form-row';
    const lbl = document.createElement('label'); lbl.textContent = labelText;
    row.appendChild(lbl); row.appendChild(inputEl);
    return row;
  }

  function makeSelect(id, options, selected) {
    const sel = document.createElement('select'); sel.id = id; sel.className = 'neo-select';
    options.forEach(function(o) {
      const opt = document.createElement('option'); opt.value = o; opt.textContent = o;
      if (o === selected) opt.selected = true;
      sel.appendChild(opt);
    });
    return sel;
  }

  const cmdRow = document.createElement('div'); cmdRow.className = 'form-row';
  const cmdLabel = document.createElement('label'); cmdLabel.textContent = 'Commande Twitch'; cmdRow.appendChild(cmdLabel);
  const cmdInput = document.createElement('input'); cmdInput.type = 'text'; cmdInput.id = 'oi-command-s'; cmdInput.className = 'neo-input'; cmdInput.value = oi.command || '!image'; cmdInput.style.width = '120px'; cmdRow.appendChild(cmdInput);
  oiSection.appendChild(cmdRow);

  const durRow = document.createElement('div'); durRow.className = 'form-row';
  const durLabel = document.createElement('label'); durLabel.textContent = 'Durée affichage (s)'; durRow.appendChild(durLabel);
  const durRange = document.createElement('input'); durRange.type = 'range'; durRange.id = 'oi-duration-s'; durRange.min = '5'; durRange.max = '60'; durRange.value = oi.display_duration || 15; durRow.appendChild(durRange);
  const durVal = document.createElement('span'); durVal.id = 'oi-duration-val-s'; durVal.textContent = (oi.display_duration || 15) + 's'; durRow.appendChild(durVal);
  oiSection.appendChild(durRow);

  oiSection.appendChild(makeFormRow('Animation entrée', makeSelect('oi-anim-in-s', ANIMATE_CSS_IN, oi.animation_in)));
  oiSection.appendChild(makeFormRow('Animation sortie', makeSelect('oi-anim-out-s', ANIMATE_CSS_OUT, oi.animation_out)));

  const adRow = document.createElement('div'); adRow.className = 'form-row';
  const adLabel = document.createElement('label'); adLabel.textContent = 'Durée animation (s)'; adRow.appendChild(adLabel);
  const adRange = document.createElement('input'); adRange.type = 'range'; adRange.id = 'oi-anim-duration-s'; adRange.min = '0.5'; adRange.max = '3'; adRange.step = '0.1'; adRange.value = oi.animation_duration || 1; adRow.appendChild(adRange);
  const adVal = document.createElement('span'); adVal.id = 'oi-anim-duration-val-s'; adVal.textContent = (oi.animation_duration || 1) + 's'; adRow.appendChild(adVal);
  oiSection.appendChild(adRow);

  oiSection.appendChild(makeFormRow('Filtre images', makeSelect('oi-filter-s', ['all','top','recent'], oi.random_filter)));

  const btnRow = document.createElement('div'); btnRow.className = 'form-row';
  const oiSaveBtn = document.createElement('button'); oiSaveBtn.className = 'neo-btn'; oiSaveBtn.textContent = 'Sauvegarder'; oiSaveBtn.onclick = saveOverlayImageConfigSysteme; btnRow.appendChild(oiSaveBtn);
  const oiTestBtn = document.createElement('button'); oiTestBtn.className = 'neo-btn'; oiTestBtn.textContent = 'Tester'; oiTestBtn.style.marginLeft = '8px'; oiTestBtn.onclick = testOverlayImage; btnRow.appendChild(oiTestBtn);
  oiSection.appendChild(btnRow);

  container.appendChild(oiSection);

  durRange.addEventListener('input', function() { durVal.textContent = durRange.value + 's'; });
  adRange.addEventListener('input', function() { adVal.textContent = adRange.value + 's'; });
}

async function saveOverlayImageConfigSysteme() {
  const sw = document.getElementById('overlay-switch-image');
  const body = { overlay_image: {
    enabled: sw ? sw.classList.contains('on') : false,
    command: document.getElementById('oi-command-s').value,
    display_duration: parseInt(document.getElementById('oi-duration-s').value),
    animation_in: document.getElementById('oi-anim-in-s').value,
    animation_out: document.getElementById('oi-anim-out-s').value,
    animation_duration: parseFloat(document.getElementById('oi-anim-duration-s').value),
    random_filter: document.getElementById('oi-filter-s').value,
  }};
  const r = await apiFetch('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
  if (r && r.ok) toast('Config overlay sauvegardée', 'success');
}

function _fmtNum(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
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
        <button class="mem-subnav-pill" data-subtab="global" onclick="switchMemoireSubTab('global')">Mémoire communautaire</button>
        <button class="mem-subnav-pill" data-subtab="dashboard" onclick="switchMemoireSubTab('dashboard')">Questions</button>
        <button class="mem-subnav-pill" data-subtab="notes" onclick="switchMemoireSubTab('notes')">Notes du bot</button>
        <button class="mem-subnav-pill" data-subtab="graph" onclick="switchMemoireSubTab('graph')">Graphe social</button>
      </div>
      <div class="mem-subnav-content active" id="memoire-sub-users"></div>
      <div class="mem-subnav-content" id="memoire-sub-global"></div>
      <div class="mem-subnav-content" id="memoire-sub-dashboard"></div>
      <div class="mem-subnav-content" id="memoire-sub-notes"></div>
      <div class="mem-subnav-content" id="memoire-sub-graph"></div>
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
    if (!document.getElementById('mem-grid')) renderMemoryTab(panel);
  } else if (subtab === 'global') {
    if (panel.children.length === 0) renderGlobalMemoryTab(panel);
  } else if (subtab === 'dashboard') {
    if (panel && panel.children.length === 0) {
      panel.id = 'tab-admin-memory-dash';
      loadMemoryDashboard().then(function() {
        panel.id = 'memoire-sub-dashboard';
      });
    }
  } else if (subtab === 'notes') {
    if (panel) loadNotesTab(panel);
  } else if (subtab === 'graph') {
    if (panel) loadGraphTab(panel);
  }
}


// ── Persistent notes tab ─────────────────────────────────────────────────────

async function loadNotesTab(panel) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:var(--text-secondary);padding:16px">Chargement...</p>';

  const r = await apiFetch('/api/admin/notes');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const data = await r.json();
  const notes = data.notes || [];

  const addFormId = 'notes-add-form';
  let html = '<div class="card mb-4">';
  html += '<div class="card-title">AJOUTER UNE NOTE</div>';
  html += '<div style="display:flex;flex-direction:column;gap:8px" id="' + addFormId + '">';
  html += '<input id="note-new-title" class="input" placeholder="Titre" style="background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;color:#fff" />';
  html += '<textarea id="note-new-content" class="input" rows="3" placeholder="Contenu" style="background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;color:#fff;resize:vertical"></textarea>';
  html += '<button class="btn btn-sm" onclick="saveNewNote()">Enregistrer</button>';
  html += '</div></div>';
  html += '<p style="color:var(--text-muted);font-size:0.82rem;margin:0 0 12px;padding:0 4px">Règles et engagements toujours injectés dans chaque conversation. Pour les infos critiques que le bot doit garder en tête.</p>';

  if (notes.length === 0) {
    html += '<p style="color:var(--text-secondary);padding:8px">Aucune note persistante</p>';
  } else {
    html += '<div class="card"><div class="card-title">NOTES DU BOT (' + notes.length + ')</div><div id="notes-list">';
    for (const n of notes) {
      html += renderNoteRow(n);
    }
    html += '</div></div>';
  }

  panel.innerHTML = html;
}

function renderNoteRow(n) {
  const id = parseInt(n.id, 10);
  const title = escHtml(n.title);
  const content = escHtml(n.content);
  const date = new Date(n.updated_at * 1000).toLocaleDateString('fr-FR');
  return '<div class="mem-dash-q-row" id="note-row-' + id + '" style="flex-direction:column;align-items:flex-start;gap:6px">'
    + '<div style="display:flex;justify-content:space-between;width:100%;align-items:center">'
    + '<strong>' + title + '</strong>'
    + '<span style="color:var(--text-muted);font-size:11px">' + date + '</span>'
    + '</div>'
    + '<div id="note-content-' + id + '" style="color:var(--text-primary);font-size:13px;white-space:pre-wrap">' + content + '</div>'
    + '<div class="mem-dash-q-actions">'
    + '<button class="btn btn-sm btn-outline" onclick="editNote(' + id + ')">Modifier</button>'
    + '<button class="btn btn-sm btn-danger" onclick="deleteNote(' + id + ')">Supprimer</button>'
    + '</div>'
    + '</div>';
}

async function saveNewNote() {
  const title = (document.getElementById('note-new-title') || {}).value || '';
  const content = (document.getElementById('note-new-content') || {}).value || '';
  if (!title.trim() || !content.trim()) { toast('Titre et contenu requis', 'error'); return; }
  const r = await apiFetch('/api/admin/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title.trim(), content: content.trim() }),
  });
  if (r && r.ok) {
    toast('Note enregistrée');
    const panel = document.getElementById('memoire-sub-notes');
    if (panel) loadNotesTab(panel);
  } else {
    toast('Erreur lors de l\'enregistrement', 'error');
  }
}

async function editNote(id) {
  id = parseInt(id, 10);
  const contentEl = document.getElementById('note-content-' + id);
  if (!contentEl) return;
  const current = contentEl.textContent;
  const newContent = prompt('Modifier la note :', current);
  if (newContent === null || newContent.trim() === '' || newContent.trim() === current) return;
  contentEl.textContent = newContent.trim();
  const r = await apiFetch('/api/admin/notes/' + id, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: document.getElementById('note-row-' + id).querySelector('strong').textContent, content: newContent.trim() }),
  });
  if (r && r.ok) {
    toast('Note modifiée');
  } else {
    toast('Erreur lors de la modification', 'error');
    contentEl.textContent = current;
  }
}

async function deleteNote(id) {
  id = parseInt(id, 10);
  if (!confirm('Supprimer cette note ?')) return;
  const row = document.getElementById('note-row-' + id);
  if (row) { row.style.opacity = '0'; row.style.transition = 'opacity 0.3s'; setTimeout(function() { row.remove(); }, 300); }
  const r = await apiFetch('/api/admin/notes/' + id, { method: 'DELETE' });
  if (r && r.ok) {
    toast('Note supprimée');
  } else {
    toast('Erreur lors de la suppression', 'error');
    const panel = document.getElementById('memoire-sub-notes');
    if (panel) loadNotesTab(panel);
  }
}

// ── Social Graph Tab (vis-network) ──────────────────────────────────────────

async function loadGraphTab(panel) {
  if (!panel) return;
  await _renderGraph(panel, '/api/admin/social-graph/data', true);
}

async function _renderGraph(panel, apiUrl, isAdmin) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:var(--text-secondary);padding:16px">Chargement du graphe...</p>';

  // Lazy-load vis-network from CDN
  if (typeof vis === 'undefined') {
    try {
      await new Promise(function(resolve, reject) {
        var script = document.createElement('script');
        script.src = 'https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js';
        script.onload = resolve;
        script.onerror = function() { reject(new Error('Failed to load vis-network')); };
        document.head.appendChild(script);
      });
    } catch (_e) {
      panel.textContent = 'Impossible de charger vis-network depuis le CDN.';
      return;
    }
  }

  // Build the tab layout
  var wrapper = document.createElement('div');
  wrapper.style.cssText = 'max-width:1200px;margin:0 auto;padding:20px';

  var header = document.createElement('div');
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px';

  var titleBlock = document.createElement('div');
  var h2 = document.createElement('h2');
  h2.style.cssText = 'margin:0;font-size:1.3rem';
  h2.textContent = 'Graphe social';
  var subtitle = document.createElement('p');
  subtitle.style.cssText = 'margin:4px 0 0;font-size:0.82rem;color:var(--text-secondary)';
  subtitle.textContent = 'Relations et interactions entre les membres du serveur.';
  titleBlock.appendChild(h2);
  titleBlock.appendChild(subtitle);

  var pfx = isAdmin ? 'admin' : 'pub';
  var statsEl = document.createElement('span');
  statsEl.id = pfx + '-graph-stats';
  statsEl.style.cssText = 'font-size:0.75rem;padding:4px 10px;background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;color:var(--text-secondary)';

  header.appendChild(titleBlock);
  header.appendChild(statsEl);
  wrapper.appendChild(header);

  var card = document.createElement('div');
  card.className = 'card';
  card.style.cssText = 'padding:0;overflow:hidden;position:relative;min-height:500px';
  var graphContainer = document.createElement('div');
  graphContainer.id = pfx + '-graph-container';
  graphContainer.style.cssText = 'width:100%;height:600px;background:var(--bg-canvas);border-radius:12px';
  card.appendChild(graphContainer);
  wrapper.appendChild(card);

  var detailPanel = document.createElement('div');
  detailPanel.id = pfx + '-graph-detail';
  detailPanel.className = 'card';
  detailPanel.style.cssText = 'margin-top:16px;display:none';
  var detailTitle = document.createElement('div');
  detailTitle.className = 'card-title';
  detailTitle.textContent = 'D\u00c9TAIL';
  var detailContent = document.createElement('div');
  detailContent.id = pfx + '-graph-detail-content';
  detailPanel.appendChild(detailTitle);
  detailPanel.appendChild(detailContent);
  wrapper.appendChild(detailPanel);

  panel.textContent = '';
  panel.appendChild(wrapper);

  // Fetch graph data from API
  var r = isAdmin ? await apiFetch(apiUrl) : await fetch(apiUrl);
  if (!r || !r.ok) {
    graphContainer.textContent = 'Graphe non disponible \u2014 Neo4j non connect\u00e9';
    graphContainer.style.cssText += ';color:var(--text-muted);padding:40px;text-align:center';
    return;
  }
  var data = await r.json();

  statsEl.textContent = data.nodes.length + ' membres \u00b7 ' + data.edges.length + ' relations';

  if (!data.nodes.length) {
    graphContainer.textContent = 'Aucune donn\u00e9e dans le graphe. Les relations appara\u00eetront au fil des conversations.';
    graphContainer.style.cssText += ';color:var(--text-muted);padding:40px;text-align:center';
    return;
  }

  // Color map and French labels for edge types
  var edgeColors = {
    'voice': '#a855f7',
    'vocal': '#a855f7',
    'reply': '#3b82f6',
    'replied': '#3b82f6',
    'responds': '#3b82f6',
    'r\u00e9pondu': '#3b82f6',
    'mention': '#3b82f6',
    'mentioned': '#3b82f6',
    'mentionn\u00e9': '#3b82f6',
    'reaction': '#eab308',
    'reacted': '#eab308',
    'r\u00e9agi': '#eab308',
    'thread': '#6b7280',
    'game': '#22c55e',
    'played': '#22c55e',
    'jou\u00e9': '#22c55e',
    'knows': '#06b6d4',
    'friends': '#06b6d4',
    'related': '#06b6d4',
    'interacts': '#06b6d4',
    'talked': '#3b82f6',
    'discussed': '#3b82f6',
    'shared': '#eab308',
    'helped': '#22c55e',
    'likes': '#eab308',
    'dislikes': '#ef4444',
  };

  var edgeTranslations = {
    'relates_to': 'li\u00e9 \u00e0',
    'knows': 'conna\u00eet',
    'friends': 'amis',
    'friends_with': 'amis avec',
    'interacts': 'interagit',
    'interacts_with': 'interagit avec',
    'talked': 'a parl\u00e9',
    'talked_to': 'a parl\u00e9 \u00e0',
    'discussed': 'a discut\u00e9',
    'discussed_with': 'a discut\u00e9 avec',
    'replied': 'a r\u00e9pondu',
    'replied_to': 'a r\u00e9pondu \u00e0',
    'responds': 'r\u00e9pond',
    'responds_to': 'r\u00e9pond \u00e0',
    'mentioned': 'a mentionn\u00e9',
    'mention': 'mention',
    'reacted': 'a r\u00e9agi',
    'reaction': 'r\u00e9action',
    'voice': 'vocal',
    'played': 'a jou\u00e9',
    'played_with': 'a jou\u00e9 avec',
    'game': 'jeu',
    'shared': 'a partag\u00e9',
    'helped': 'a aid\u00e9',
    'likes': 'aime',
    'dislikes': 'n\'aime pas',
    'related': 'li\u00e9',
  };

  function translateEdgeType(type) {
    if (!type) return 'relation';
    var t = type.toLowerCase().replace(/_/g, '_');
    if (edgeTranslations[t]) return edgeTranslations[t];
    // Try without underscores
    var clean = t.replace(/_/g, ' ');
    for (var key in edgeTranslations) {
      if (clean.indexOf(key.replace(/_/g, ' ')) !== -1) return edgeTranslations[key];
    }
    return type;
  }

  function getEdgeColor(type) {
    if (!type) return '#06b6d4';
    var t = type.toLowerCase();
    for (var key in edgeColors) {
      if (t.indexOf(key) !== -1) return edgeColors[key];
    }
    return '#06b6d4';
  }

  // Build vis-network datasets
  var visNodes = new vis.DataSet(data.nodes.map(function(n) {
    return {
      id: n.id,
      label: n.name,
      title: n.summary || n.name,
      color: {
        background: 'rgba(6, 182, 212, 0.3)',
        border: '#06b6d4',
        highlight: { background: 'rgba(6, 182, 212, 0.6)', border: '#06b6d4' },
      },
      font: { color: '#fff', size: 14 },
      borderWidth: 2,
      shadow: { enabled: true, color: 'rgba(6, 182, 212, 0.3)', size: 10 },
    };
  }));

  var visEdges = new vis.DataSet(data.edges.map(function(e, i) {
    return {
      id: i,
      from: e.source,
      to: e.target,
      label: translateEdgeType(e.type),
      title: e.fact || '',
      color: { color: getEdgeColor(e.type), highlight: '#fff', opacity: 0.7 },
      font: { color: 'rgba(255,255,255,0.5)', size: 10, strokeWidth: 0 },
      width: 2,
      smooth: { type: 'continuous' },
    };
  }));

  var network = new vis.Network(graphContainer, { nodes: visNodes, edges: visEdges }, {
    physics: {
      solver: 'forceAtlas2Based',
      forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.01, springLength: 150 },
      stabilization: { iterations: 100 },
    },
    interaction: { hover: true, tooltipDelay: 200 },
    nodes: { shape: 'dot', size: 20 },
    edges: { arrows: { to: { enabled: true, scaleFactor: 0.5 } } },
    layout: { improvedLayout: true },
  });

  // Click handler for detail panel
  network.on('click', function(params) {
    if (params.nodes.length > 0) {
      var nodeId = params.nodes[0];
      var node = data.nodes.find(function(n) { return n.id === nodeId; });
      if (node) {
        var nodeEdges = data.edges.filter(function(e) { return e.source === nodeId || e.target === nodeId; });
        var nameEl = document.createElement('h3');
        nameEl.style.cssText = 'margin:0 0 8px;color:#06b6d4';
        nameEl.textContent = node.name;

        detailContent.textContent = '';
        detailContent.appendChild(nameEl);

        if (node.summary) {
          var summaryEl = document.createElement('p');
          summaryEl.style.cssText = 'color:var(--text-primary);margin:0 0 12px';
          summaryEl.textContent = node.summary;
          detailContent.appendChild(summaryEl);
        }

        if (nodeEdges.length) {
          var edgeList = document.createElement('div');
          edgeList.style.fontSize = '0.85rem';
          for (var ei = 0; ei < nodeEdges.length; ei++) {
            var edge = nodeEdges[ei];
            var other = edge.source === nodeId ? edge.target_name : edge.source_name;
            var color = getEdgeColor(edge.type);

            var row = document.createElement('div');
            row.style.cssText = 'padding:4px 0;border-bottom:1px solid var(--border)';

            var typeSpan = document.createElement('span');
            typeSpan.style.cssText = 'color:' + color + ';font-weight:600';
            typeSpan.textContent = translateEdgeType(edge.type);
            row.appendChild(typeSpan);

            var arrow = document.createTextNode(' \u2192 ' + (other || '?'));
            row.appendChild(arrow);

            if (edge.fact) {
              row.appendChild(document.createElement('br'));
              var factSpan = document.createElement('span');
              factSpan.style.cssText = 'color:var(--text-secondary);font-size:0.8rem';
              factSpan.textContent = edge.fact;
              row.appendChild(factSpan);
            }

            edgeList.appendChild(row);
          }
          detailContent.appendChild(edgeList);
        }

        detailPanel.style.display = 'block';
      }
    } else {
      detailPanel.style.display = 'none';
    }
  });
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
        <span style="color:var(--text-secondary);font-size:0.85rem">Basculer la visibilité de l'overlay OBS</span>
        <div class="overlay-switch" id="overlay-switch-tab" style="cursor:pointer" onclick="toggleOverlayFromTab()">
          <div class="overlay-switch-knob"></div>
        </div>
        <span id="overlay-status-label" style="font-size:0.78rem;color:var(--text-secondary)"></span>
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


// ── Actions Tab ──────────────────────────────────────────────────────────────

let _actionsSubTab = 'tasks';

function startActionSSE() {
  if (actionSSE) actionSSE.close();
  actionSSE = new EventSource('/api/admin/sse/actions');
  actionSSE.onmessage = function(e) {
    try {
      var evt = JSON.parse(e.data);
      if (evt.type && evt.task_id) {
        if (_actionsSubTab === 'tasks') loadActionTasks();
        if (_actionsSubTab === 'completed') loadCompletedTasks();
      }
    } catch (_) {}
  };
  actionSSE.onerror = function() {};
}

function stopActionSSE() {
  if (actionSSE) { actionSSE.close(); actionSSE = null; }
}

function renderActionsTab() {
  const el = document.getElementById('tab-admin-actions');
  if (!el) return;

  // Build sub-nav + content containers
  var subnavHtml = '<div class="actions-subnav">'
    + '<button class="actions-subnav-pill' + (_actionsSubTab === 'tasks' ? ' active' : '') + '" onclick="switchActionsSubTab(\'tasks\')">Tâches</button>'
    + '<button class="actions-subnav-pill' + (_actionsSubTab === 'completed' ? ' active' : '') + '" onclick="switchActionsSubTab(\'completed\')">Terminées</button>'
    + '<button class="actions-subnav-pill' + (_actionsSubTab === 'permissions' ? ' active' : '') + '" onclick="switchActionsSubTab(\'permissions\')">Permissions</button>'
    + '</div>';

  el.textContent = '';
  el.insertAdjacentHTML('beforeend', subnavHtml);

  var tasksDiv = document.createElement('div');
  tasksDiv.id = 'actions-tasks-content';
  tasksDiv.className = 'actions-subcontent' + (_actionsSubTab === 'tasks' ? ' active' : '');
  el.appendChild(tasksDiv);

  var completedDiv = document.createElement('div');
  completedDiv.id = 'actions-completed-content';
  completedDiv.className = 'actions-subcontent' + (_actionsSubTab === 'completed' ? ' active' : '');
  el.appendChild(completedDiv);

  var permsDiv = document.createElement('div');
  permsDiv.id = 'actions-perms-content';
  permsDiv.className = 'actions-subcontent' + (_actionsSubTab === 'permissions' ? ' active' : '');
  el.appendChild(permsDiv);

  if (_actionsSubTab === 'tasks') {
    loadActionTasks();
  } else if (_actionsSubTab === 'completed') {
    loadCompletedTasks();
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
  loading.style.cssText = 'color:var(--text-muted);text-align:center;padding:32px';
  loading.textContent = 'Chargement...';
  container.appendChild(loading);

  var r = await apiFetch('/api/actions/tasks');
  if (!r || !r.ok) {
    loading.textContent = 'Erreur de chargement';
    return;
  }
  var data = await r.json();
  var allTasks = data.tasks || [];
  // Only show active and paused tasks
  var tasks = allTasks.filter(function(t) { return t.status === 'active' || t.status === 'paused'; });

  container.textContent = '';

  if (tasks.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'color:var(--text-muted);text-align:center;padding:32px';
    empty.textContent = 'Aucune tâche en cours';
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

async function loadCompletedTasks() {
  var container = document.getElementById('actions-completed-content');
  if (!container) return;
  container.textContent = '';
  var loading = document.createElement('div');
  loading.style.cssText = 'color:var(--text-muted);text-align:center;padding:32px';
  loading.textContent = 'Chargement...';
  container.appendChild(loading);

  var r = await apiFetch('/api/actions/tasks');
  if (!r || !r.ok) {
    loading.textContent = 'Erreur de chargement';
    return;
  }
  var data = await r.json();
  var allTasks = data.tasks || [];
  var tasks = allTasks.filter(function(t) {
    return t.status === 'completed' || t.status === 'cancelled' || t.status === 'missed';
  });

  container.textContent = '';

  if (tasks.length === 0) {
    var empty = document.createElement('div');
    empty.style.cssText = 'color:var(--text-muted);text-align:center;padding:32px';
    empty.textContent = 'Aucune tâche terminée';
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

var TWITCH_ROLES = ['everyone', 'subscriber', 'vip', 'moderator', 'admin'];
var _discordGuildRoles = []; // [{id, name, roles: [{id, name, color}]}]

async function loadDiscordRoles() {
  var r = await apiFetch('/api/actions/discord-roles');
  if (!r || !r.ok) return;
  var data = await r.json();
  _discordGuildRoles = data.guilds || [];
}

function _buildPermRow(p) {
  var actionType = p.action_type;
  var enabled = p.enabled !== false && p.enabled !== 0;
  var discordRoles = p.discord_roles || {};

  var container = document.createElement('div');
  container.className = 'action-perm-row';

  // ── Header: name + enabled + twitch ──
  var header = document.createElement('div');
  header.className = 'action-perm-header';

  var nameSpan = document.createElement('span');
  nameSpan.className = 'action-perm-name';
  nameSpan.textContent = actionType;
  header.appendChild(nameSpan);

  // Enabled toggle
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
  header.appendChild(toggleLabel);

  // Twitch dropdown
  var twitchWrap = document.createElement('div');
  twitchWrap.className = 'action-perm-twitch';
  var twitchLabel = document.createElement('span');
  twitchLabel.className = 'action-perm-platform-label';
  twitchLabel.textContent = 'Twitch';
  twitchWrap.appendChild(twitchLabel);
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
  twitchWrap.appendChild(twitchSelect);
  header.appendChild(twitchWrap);

  container.appendChild(header);

  // ── Discord guilds section ──
  _discordGuildRoles.forEach(function(guild) {
    var guildSection = document.createElement('div');
    guildSection.className = 'action-perm-guild';

    var guildLabel = document.createElement('div');
    guildLabel.className = 'action-perm-guild-label';
    guildLabel.textContent = guild.name;
    guildSection.appendChild(guildLabel);

    var selectedRoles = (discordRoles[guild.id] || []).map(function(r) { return r.role_id; });

    var chipsDiv = document.createElement('div');
    chipsDiv.className = 'action-role-chips';

    var addSelect = document.createElement('select');
    addSelect.className = 'neo-select action-perm-add-role';

    function renderChips() {
      chipsDiv.textContent = '';
      selectedRoles.forEach(function(rid) {
        var roleInfo = guild.roles.find(function(r) { return r.id === rid; });
        if (!roleInfo) return;
        var chip = document.createElement('span');
        chip.className = 'action-role-chip';
        var dot = document.createElement('span');
        dot.className = 'action-role-dot';
        dot.style.backgroundColor = roleInfo.color;
        chip.appendChild(dot);
        chip.appendChild(document.createTextNode(roleInfo.name));
        var removeBtn = document.createElement('button');
        removeBtn.className = 'action-role-chip-remove';
        removeBtn.textContent = '\u00d7';
        removeBtn.addEventListener('click', function() {
          selectedRoles = selectedRoles.filter(function(r) { return r !== rid; });
          saveDiscordPerm(actionType, guild.id, selectedRoles);
          renderChips();
          renderDropdown();
        });
        chip.appendChild(removeBtn);
        chipsDiv.appendChild(chip);
      });
    }

    function renderDropdown() {
      addSelect.textContent = '';
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = '+ Ajouter un r\u00f4le';
      placeholder.disabled = true;
      placeholder.selected = true;
      addSelect.appendChild(placeholder);
      guild.roles.forEach(function(role) {
        if (selectedRoles.indexOf(role.id) !== -1) return;
        var opt = document.createElement('option');
        opt.value = role.id;
        opt.textContent = role.name;
        addSelect.appendChild(opt);
      });
    }

    addSelect.addEventListener('change', function() {
      if (!this.value) return;
      selectedRoles.push(this.value);
      saveDiscordPerm(actionType, guild.id, selectedRoles);
      renderChips();
      renderDropdown();
    });

    renderChips();
    renderDropdown();

    guildSection.appendChild(chipsDiv);
    guildSection.appendChild(addSelect);
    container.appendChild(guildSection);
  });

  return container;
}

async function saveDiscordPerm(actionType, guildId, roleIds) {
  var r = await apiFetch('/api/actions/permissions/' + encodeURIComponent(actionType) + '/discord', {
    method: 'PUT',
    body: JSON.stringify({ guild_id: guildId, role_ids: roleIds }),
  });
  if (!r || !r.ok) { toast('Erreur mise \u00e0 jour permission Discord', 'error'); return; }
  toast('Permission Discord mise \u00e0 jour', 'success');
}

async function loadActionPermissions() {
  var container = document.getElementById('actions-perms-content');
  if (!container) return;
  container.textContent = '';
  var loading = document.createElement('div');
  loading.style.cssText = 'color:var(--text-muted);text-align:center;padding:32px';
  loading.textContent = 'Chargement...';
  container.appendChild(loading);

  await loadDiscordRoles();
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
    empty.style.cssText = 'color:var(--text-muted);text-align:center;padding:32px';
    empty.textContent = 'Aucune permission configur\u00e9e';
    container.appendChild(empty);
    return;
  }

  var list = document.createElement('div');
  list.className = 'action-perms-list';
  perms.forEach(function(p) {
    list.appendChild(_buildPermRow(p));
  });
  container.appendChild(list);
}

async function updateActionPerm(actionType, field, value) {
  var body = {};
  body[field] = value;
  var r = await apiFetch('/api/actions/permissions/' + encodeURIComponent(actionType), {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (!r || !r.ok) { toast('Erreur mise \u00e0 jour permission', 'error'); return; }
  toast('Permission mise \u00e0 jour', 'success');
}


async function generateInvite() {
  try {
    var resp = await apiFetch('/api/admin/setup/invite', { method: 'POST' });
    var data = await resp.json();
    var url = data.url || (window.location.origin + '/setup/' + data.token);
    await navigator.clipboard.writeText(url);
    toast('Lien copié : ' + url, 'success');
    loadInvites();
  } catch(e) { toast('Erreur : ' + e.message, 'error'); }
}

async function copyInviteLink(token) {
  var url = window.location.origin + '/setup/' + token;
  await navigator.clipboard.writeText(url);
  toast('Lien copié !', 'success');
}

async function revokeInvite(token) {
  if (!confirm('Révoquer ce lien ?')) return;
  var r = await apiFetch('/api/admin/setup/invite/' + token, { method: 'DELETE' });
  if (r && r.ok) { toast('Lien révoqué', 'success'); } else { toast('Erreur révocation', 'error'); }
  loadInvites();
}

// ── Prompts & Persona Management ─────────────────────────────────────────────

var _promptsData = null;        // { persona: {}, system_prompts: {} }
var _promptsSection = 'persona'; // 'persona' | 'system'
var _promptsFile = null;

async function renderPromptsTab() {
  var el = document.getElementById('tab-admin-prompts');
  if (!el) return;
  el.innerHTML = '<div style="padding:24px;color:var(--text-muted)">Chargement...</div>';

  await _loadPromptsModels();

  await _loadPromptsData();
  _renderPromptsUI(el);
}

async function _loadPromptsData() {
  var r = await apiFetch('/api/admin/prompts');
  _promptsData = (r && r.ok) ? await r.json() : { persona: {}, system_prompts: {} };
  var files = _promptsSection === 'persona'
    ? Object.keys(_promptsData.persona)
    : Object.keys(_promptsData.system_prompts);
  if (!_promptsFile || !files.includes(_promptsFile)) {
    _promptsFile = files[0] || null;
  }
}

function _renderPromptsUI(el) {
  var personaFiles = Object.keys(_promptsData.persona);
  var systemFiles = Object.keys(_promptsData.system_prompts);
  var currentFiles = _promptsSection === 'persona' ? personaFiles : systemFiles;
  var content = _promptsFile
    ? (_promptsSection === 'persona' ? _promptsData.persona[_promptsFile] : _promptsData.system_prompts[_promptsFile])
    : '';

  // Liste de fichiers
  var fileList = currentFiles.map(function(f) {
    return '<div class="prompt-file-item' + (f === _promptsFile ? ' active' : '') + '" onclick="selectPromptFile(\'' + f + '\')">' + f.replace('.md','') + '</div>';
  }).join('');

  el.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%;gap:0">
      <!-- Toolbar -->
      <div style="display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--border);flex-wrap:wrap">
        <div class="card-title" style="margin:0;flex:0 0 auto">PROMPTS</div>
        <div class="mem-subnav" style="margin-bottom:0;margin-left:auto">
          <button class="mem-subnav-pill ${_promptsSection==='persona'?'active':''}" onclick="switchPromptsSection('persona')">Persona</button>
          <button class="mem-subnav-pill ${_promptsSection==='system'?'active':''}" onclick="switchPromptsSection('system')">Système</button>
        </div>
      </div>
      <!-- Body -->
      <div style="display:flex;flex:1;min-height:0;overflow:hidden">
        <!-- File list -->
        <div style="width:190px;flex-shrink:0;border-right:1px solid var(--border);overflow-y:auto;padding:8px">
          ${fileList || '<div style="padding:12px;font-size:12px;color:var(--text-muted)">Aucun fichier</div>'}
        </div>
        <!-- Editor -->
        <div style="flex:1;display:flex;flex-direction:column;min-width:0;padding:12px 16px;gap:8px">
          ${_promptsFile ? `
            <div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0">
              <span style="font-size:13px;font-weight:600;color:var(--text-secondary)">${_promptsFile}</span>
              <button class="btn-primary" onclick="savePromptFile()" style="font-size:12px;padding:6px 14px">💾 Sauvegarder</button>
            </div>
            <textarea id="prompt-editor" style="flex:1;background:var(--bg-canvas);border:1px solid var(--border);border-radius:10px;color:var(--text-primary);padding:14px;font-size:13px;font-family:monospace;resize:vertical;line-height:1.6;outline:none;min-height:calc(100vh - 310px);width:100%;box-sizing:border-box" spellcheck="false">${escapeHtml(content)}</textarea>
            <div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0;min-height:22px">
              <div id="prompt-token-info" style="display:flex;gap:16px;font-size:11px;color:var(--text-muted)"></div>
              <div id="prompt-save-status" style="font-size:12px"></div>
            </div>
          ` : '<div style="color:var(--text-muted);font-size:13px;padding-top:40px;text-align:center">Sélectionne un fichier</div>'}
        </div>
      </div>
    </div>`;

  // Compteur de tokens live
  var editor = document.getElementById('prompt-editor');
  if (editor) {
    _updatePromptTokenInfo(editor.value);
    editor.addEventListener('input', function() { _updatePromptTokenInfo(editor.value); });
  }

  // Styles inline pour les items de fichier
  document.querySelectorAll('.prompt-file-item').forEach(function(item) {
    item.style.cssText = 'padding:8px 12px;border-radius:8px;font-size:12px;cursor:pointer;color:var(--text-secondary);transition:all .15s;margin-bottom:2px';
    if (item.classList.contains('active')) {
      item.style.background = 'rgba(6,182,212,0.15)';
      item.style.color = 'rgb(6,182,212)';
      item.style.borderLeft = '2px solid rgb(6,182,212)';
    }
    item.addEventListener('mouseenter', function() {
      if (!item.classList.contains('active')) item.style.background = 'var(--bg-surface)';
    });
    item.addEventListener('mouseleave', function() {
      if (!item.classList.contains('active')) item.style.background = '';
    });
  });
}

function escapeHtml(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Prix input par 1M tokens (source : pages tarifaires officielles)
var _MODEL_PRICE_TABLE = {
  // OpenAI
  'gpt-4o':              2.50,
  'gpt-4o-mini':         0.15,
  'gpt-4.1':             2.00,
  'gpt-4.1-mini':        0.40,
  'gpt-4.1-nano':        0.10,
  'gpt-5':               5.00,
  'gpt-5.1':             5.00,
  'gpt-5.1-mini':        0.40,
  'gpt-5-nano':          0.10,
  'o1':                 15.00,
  'o1-mini':             3.00,
  'o3':                 10.00,
  'o3-mini':             1.10,
  'o4-mini':             1.10,
  // Anthropic
  'claude-opus-4':      15.00,
  'claude-opus-4-5':    15.00,
  'claude-opus-4-6':    15.00,
  'claude-sonnet-4':     3.00,
  'claude-sonnet-4-5':   3.00,
  'claude-sonnet-4-6':   3.00,
  'claude-haiku-4':      0.80,
  'claude-haiku-4-5':    0.80,
};

var _promptsModels = []; // [{ label, usd }] — peuplé depuis la config

function _priceForModel(modelId) {
  if (!modelId) return null;
  var m = modelId.toLowerCase();
  // Correspondance exacte d'abord
  if (_MODEL_PRICE_TABLE[m] !== undefined) return _MODEL_PRICE_TABLE[m];
  // Correspondance partielle (préfixe le plus long)
  var best = null, bestLen = 0;
  Object.keys(_MODEL_PRICE_TABLE).forEach(function(k) {
    if (m.startsWith(k) && k.length > bestLen) { best = _MODEL_PRICE_TABLE[k]; bestLen = k.length; }
  });
  return best;
}

async function _loadPromptsModels() {
  var r = await apiFetch('/api/admin/config');
  if (!r || !r.ok) return;
  var cfg = await r.json();
  var seen = {};
  _promptsModels = [];
  [cfg.llm && cfg.llm.primary, cfg.llm && cfg.llm.secondary].forEach(function(role, i) {
    if (!role || !role.model) return;
    var key = role.model;
    if (seen[key]) return;
    seen[key] = true;
    var price = _priceForModel(role.model);
    var label = (i === 0 ? 'primary' : 'secondary') + ' (' + role.model + ')';
    _promptsModels.push({ label: label, model: role.model, usd: price });
  });
}

function _updatePromptTokenInfo(text) {
  var el = document.getElementById('prompt-token-info');
  if (!el) return;
  var tokens = Math.round((text || '').length / 4);
  var parts = ['<span>' + tokens.toLocaleString() + ' tokens</span>'];
  _promptsModels.forEach(function(p) {
    var costStr;
    if (p.usd === null) {
      costStr = '<strong style="color:var(--text-muted)">prix inconnu</strong>';
    } else {
      var cost = (tokens / 1_000_000) * p.usd;
      var costFmt = cost < 0.0001 ? ('< $0.0001') : ('$' + cost.toFixed(4));
      costStr = '<strong style="color:var(--text-secondary)">' + costFmt + '</strong>';
    }
    parts.push('<span>' + p.label + ' : ' + costStr + '/appel</span>');
  });
  el.innerHTML = parts.join('<span style="opacity:.3"> | </span>');
}

function selectPromptFile(filename) {
  _promptsFile = filename;
  _renderPromptsUI(document.getElementById('tab-admin-prompts'));
}

async function switchPromptsSection(section) {
  _promptsSection = section;
  _promptsFile = null;
  _renderPromptsUI(document.getElementById('tab-admin-prompts'));
}

async function savePromptFile() {
  var editor = document.getElementById('prompt-editor');
  var status = document.getElementById('prompt-save-status');
  if (!editor || !_promptsFile) return;
  var content = editor.value;
  status.textContent = 'Sauvegarde...';
  status.style.color = 'rgba(255,255,255,0.4)';

  var type = _promptsSection === 'persona' ? 'persona' : 'system';
  var url = '/api/admin/prompts/' + type + '/' + _promptsFile;
  var r = await apiFetch(url, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ content }) });
  if (r && r.ok) {
    // Mettre à jour le cache local
    if (_promptsSection === 'persona') _promptsData.persona[_promptsFile] = content;
    else _promptsData.system_prompts[_promptsFile] = content;
    status.textContent = '✓ Sauvegardé';
    status.style.color = 'rgb(34,197,94)';
    setTimeout(function() { if (status) status.textContent = ''; }, 3000);
  } else {
    status.textContent = '✗ Erreur lors de la sauvegarde';
    status.style.color = 'rgb(239,68,68)';
  }
}
