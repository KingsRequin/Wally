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

let currentMode = 'public';
let currentTab  = 'status';
let emotionSSE  = null;
let logSSE      = null;
var _twitchPendingRestart = false;
let actionSSE   = null;
let logFilter   = 'ALL';
let currentEmotions = {};
let currentGraphSince = null;
let _graphMeta  = null;
let _rafPending = false;
let hiddenEmotions = new Set(SECONDARY_LABELS); // secondaries hidden by default
let currentMood        = {};
let currentFatigue     = {};
let currentSecondaries = [];

// ── Tab sub-navigation state ──────────────────────────────────────
let _parametresSubTab = 'emotions';
let _systemeSubTab    = 'logs';
let _costsSubTab      = 'resume';

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

// ── Web Chat state ──────────────────────────────────────────────
let _chatWs = null;
let _chatUser = null;
let _chatTypingTimer = null;

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

  // Control bar
  showControlBar(mode === 'admin');
  if (mode === 'admin') {
    startControlBarPolling();
  } else {
    stopControlBarPolling();
  }

  const firstTab = restoreTab || (mode === 'public' ? 'status' : 'admin-parametres');
  showTab(firstTab);

  if (mode === 'admin') {
    // Ensure log-stream element exists (inside Système > Logs) before SSE starts
    renderSystemeTab();
    startLogSSE();
  } else {
    stopLogSSE();
  }
}

function showTab(tabId) {
  // Redirect legacy tab names to new consolidated tabs
  const _legacyRedirect = {
    'admin-config': 'admin-parametres',
    'admin-logs':   'admin-systeme',
    'admin-overlay': 'admin-systeme',
    'admin-instances': 'admin-systeme',
    'admin-twitch': 'admin-systeme',
  };
  if (_legacyRedirect[tabId]) {
    // Set the appropriate sub-tab before redirecting
    if (tabId === 'admin-logs') _systemeSubTab = 'logs';
    else if (tabId === 'admin-overlay') _systemeSubTab = 'overlay';
    else if (tabId === 'admin-instances') _systemeSubTab = 'instances';
    else if (tabId === 'admin-twitch') _systemeSubTab = 'twitch';
    tabId = _legacyRedirect[tabId];
  }

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
  if (tabId === 'admin-costs') renderCostsTab();
  if (tabId === 'admin-memory-dash') loadMemoryDashboard();
  if (tabId === 'admin-memoire') renderMemoireTab();
  if (tabId === 'admin-actions') { renderActionsTab(); startActionSSE(); } else { stopActionSSE(); }
  if (tabId === 'admin-prompts') renderPromptsTab();
  if (tabId === 'admin-instances') renderInstancesTab();
  if (tabId === 'admin-twitch') loadTwitchChannelsTab();
  if (tabId === 'admin-parametres') renderParametresTab();
  if (tabId === 'admin-systeme') renderSystemeTab();
  pollCostsBadge();
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
  updateFavicon(payload);
}

function updateEmotionSummary(emotions) {
  const dominant = EMOTIONS.filter(e => emotions[e] >= 0.4);
  const el = document.getElementById('emotion-summary');
  if (!el) return;
  if (dominant.length === 0) { el.textContent = 'Wally est dans un état neutre.'; return; }
  const names = { anger:'en colère', joy:'joyeux', sadness:'triste', curiosity:'curieux', boredom:'ennuyé' };
  el.textContent = `Wally est ${dominant.map(e => names[e]).join(' et ')}.`;
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

// ── Canvas helpers ────────────────────────────────────────────────────────────

function _canvasContentWidth(canvas) {
  const parent = canvas.parentElement;
  if (!parent) return canvas.offsetWidth || 800;
  const cs = getComputedStyle(parent);
  return Math.floor(parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) || 800;
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

  const primaryItems = EMOTIONS.map(e => {
    const hidden = hiddenEmotions.has(e);
    return `<div class="graph-legend-item ${hidden ? 'hidden-emotion' : ''}"
                 onclick="toggleEmotion('${e}')" title="Cliquer pour ${hidden ? 'afficher' : 'masquer'}">
      <span class="legend-line" style="background:${EMOTION_COLORS[e]}"></span>
      <span>${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
    </div>`;
  });

  const secondaryItems = SECONDARY_LABELS.map(name => {
    const hidden = hiddenEmotions.has(name);
    const color  = SECONDARY_COLORS[name];
    const label  = SECONDARY_LABELS_FR[name] || name;
    return `<div class="secondary-legend-item ${hidden ? 'hidden-emotion' : ''}"
                 onclick="toggleEmotion('${name}')" title="${hidden ? 'Afficher' : 'Masquer'} ${label}">
      <span class="secondary-legend-dash" style="color:${color}"></span>
      <span style="color:${color}">${label}</span>
    </div>`;
  });

  el.innerHTML = primaryItems.join('') + secondaryItems.join('');
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

function _computeSecondaryActivations(history) {
  const activations = [];
  for (let i = 1; i < history.length; i++) {
    const prev = history[i - 1];
    const curr = history[i];
    for (const [name, def] of Object.entries(SECONDARY_DEFS)) {
      let threshA, threshB;
      if (Array.isArray(def.threshold)) {
        threshA = def.threshold[0];
        threshB = def.threshold[1];
      } else {
        threshA = def.threshold;
        threshB = def.threshold;
      }
      const prevActive = (prev[def.a] ?? 0) >= threshA && (prev[def.b] ?? 0) >= threshB;
      const currActive = (curr[def.a] ?? 0) >= threshA && (curr[def.b] ?? 0) >= threshB;
      if (!prevActive && currActive) {
        activations.push({ name, index: i });
      }
    }
  }
  return activations;
}

function drawEmotionGraph(history) {
  const canvas = document.getElementById('emotionCanvas');
  if (!canvas || !history || history.length < 2) return;

  const W = _canvasContentWidth(canvas);
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

  // Secondary emotion activation markers (vertical dashed lines)
  const activations = _computeSecondaryActivations(history);
  for (const { name, index } of activations) {
    if (hiddenEmotions.has(name)) continue;
    const snap  = history[index];
    const x     = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
    const color = SECONDARY_COLORS[name];
    const label = SECONDARY_LABELS_FR[name] || name;

    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    ctx.moveTo(x, PAD.top);
    ctx.lineTo(x, PAD.top + gH);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.globalAlpha = 0.85;
    ctx.fillStyle   = color;
    ctx.font        = '9px Inter, sans-serif';
    ctx.textAlign   = 'left';
    const labelX = Math.min(x + 3, W - PAD.right - 60);
    ctx.fillText(label, labelX, PAD.top + 10);
    ctx.restore();
  }

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
          <label class="field-label" for="cfg-reasoning-effort">Niveau d'effort (reasoning) <span style="font-size:0.7rem;color:rgba(255,255,255,0.3)">OpenAI only</span></label>
          <select id="cfg-reasoning-effort">
            ${REASONING_EFFORTS.map(e => `<option value="${e}" ${e === cfg.openai.reasoning_effort ? 'selected' : ''}>${e.toUpperCase()}</option>`).join('')}
          </select>
        </div>
        <div class="field-group">
          <label class="field-label" for="cfg-text-verbosity">Verbosité des réponses <span style="font-size:0.7rem;color:rgba(255,255,255,0.3)">OpenAI only</span></label>
          <select id="cfg-text-verbosity">
            ${TEXT_VERBOSITIES.map(v => `<option value="${v}" ${v === cfg.openai.text_verbosity ? 'selected' : ''}>${v.toUpperCase()}</option>`).join('')}
          </select>
        </div>
      </div>
      <div id="claude-specific-settings" style="display:none">
        <div class="field-group">
          <label class="field-label" for="cfg-thinking-type">Réflexion (thinking) <span style="font-size:0.7rem;color:rgba(255,255,255,0.3)">Claude only</span></label>
          <select id="cfg-thinking-type" onchange="onThinkingTypeChange()">
            ${THINKING_TYPES.map(t => `<option value="${t}" ${t === (cfg.llm?.primary?.thinking_type || 'disabled') ? 'selected' : ''}>${t === 'disabled' ? 'DÉSACTIVÉ' : t === 'adaptive' ? 'ADAPTATIF' : 'ACTIVÉ (budget fixe)'}</option>`).join('')}
          </select>
        </div>
        <div id="thinking-effort-group" class="field-group" style="display:none">
          <label class="field-label" for="cfg-thinking-effort">Niveau d'effort thinking</label>
          <select id="cfg-thinking-effort">
            ${THINKING_EFFORTS.map(e => `<option value="${e}" ${e === (cfg.llm?.primary?.thinking_effort || 'medium') ? 'selected' : ''}>${e.toUpperCase()}</option>`).join('')}
          </select>
          <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">LOW = rapide · MEDIUM = équilibré · HIGH = défaut, pense souvent · MAX = max (Opus 4.6 only)</p>
        </div>
        <div id="thinking-budget-group" class="field-group" style="display:none">
          <label class="field-label" for="cfg-thinking-budget">Budget tokens thinking</label>
          <input type="number" id="cfg-thinking-budget" min="1000" max="128000" step="1000" value="${cfg.llm?.primary?.thinking_budget_tokens || 10000}">
          <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Doit être inférieur à max_tokens. 10k = standard, 50k+ = problèmes complexes</p>
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
        <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Nombre de messages avant déclenchement</p>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-window">Fenêtre (secondes)</label>
        <input type="number" id="cfg-spam-window" min="30" max="600" value="${(cfg.discord.spam_detection || {}).window_seconds || 120}">
        <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Période de temps pour compter les messages</p>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-mute">Durée mute (minutes)</label>
        <input type="number" id="cfg-spam-mute" min="1" max="60" value="${(cfg.discord.spam_detection || {}).mute_minutes || 5}">
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-anger">Delta colère par message muté</label>
        <input type="number" id="cfg-spam-anger" min="0.01" max="0.2" step="0.01" value="${(cfg.discord.spam_detection || {}).spam_anger_delta || 0.05}">
        <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Augmentation de la colère quand un utilisateur muté continue de parler</p>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-spam-exempt">Channels exemptés (IDs séparés par virgule)</label>
        <input type="text" id="cfg-spam-exempt" value="${((cfg.discord.spam_detection || {}).exempt_channels || []).join(', ')}">
        <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Ces salons ignorent la détection de spam</p>
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
    + (aliases.length === 0 ? '<span style="color:rgba(255,255,255,0.35);font-size:0.8rem">Aucun alias</span>' : '')
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
    ? '<span style="color:rgba(255,255,255,0.35);font-size:0.8rem">Aucun alias</span>'
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

// ── Admin costs ────────────────────────────────────────────────────────────────

let currentCostRange = '7d';
let _costGraphMeta = null;
let _costRafPending = false;
let _costsLogsPage = 1;

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

  // Detail tab sections
  _costsLogsPage = 1;
  loadCostsByFeature(days);
  loadCostPrices();
  loadCostLogs(1);
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

const FEATURE_COLORS = ['#06b6d4','#eab308','#22c55e','#ef4444','#a855f7','#f97316','#3b82f6','#ec4899'];

function drawFeaturePie(data) {
  const canvas = document.getElementById('featurePieCanvas');
  if (!canvas) return;

  const W = _canvasContentWidth(canvas);
  const H = 200;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  ctx.fillStyle = 'transparent';
  ctx.clearRect(0, 0, W, H);

  if (!data || data.length === 0) {
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Aucune donnée', W / 2, H / 2);
    return;
  }

  const total = data.reduce(function(s, d) { return s + d.cost; }, 0);
  if (total <= 0) return;

  const cx = W / 2;
  const cy = H / 2;
  const radius = Math.min(cx, cy) - 10;

  let startAngle = -Math.PI / 2;
  data.forEach(function(item, i) {
    const slice = (item.cost / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, startAngle, startAngle + slice);
    ctx.closePath();
    ctx.fillStyle = FEATURE_COLORS[i % FEATURE_COLORS.length];
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.3)';
    ctx.lineWidth = 1;
    ctx.stroke();
    startAngle += slice;
  });

  // Legend in feature-bars div
  const barsEl = document.getElementById('feature-bars');
  if (!barsEl) return;
  while (barsEl.firstChild) barsEl.removeChild(barsEl.firstChild);

  data.forEach(function(item, i) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:0.82rem;';

    const swatch = document.createElement('span');
    swatch.style.cssText = 'display:inline-block;width:12px;height:12px;border-radius:3px;flex-shrink:0;background:' + FEATURE_COLORS[i % FEATURE_COLORS.length] + ';';

    const name = document.createElement('span');
    name.style.cssText = 'flex:1;color:rgba(255,255,255,0.85);';
    name.textContent = item.feature || 'autre';

    const cost = document.createElement('span');
    cost.style.cssText = 'font-family:var(--font-mono);color:#FFD700;';
    cost.textContent = '$' + item.cost.toFixed(4);

    const pct = document.createElement('span');
    pct.style.cssText = 'color:rgba(255,255,255,0.4);min-width:42px;text-align:right;';
    pct.textContent = (item.pct !== undefined ? item.pct.toFixed(1) : (item.cost / total * 100).toFixed(1)) + '%';

    row.appendChild(swatch);
    row.appendChild(name);
    row.appendChild(cost);
    row.appendChild(pct);
    barsEl.appendChild(row);
  });
}

async function loadCostsByFeature(days) {
  const r = await apiFetch('/api/admin/costs/by-feature?days=' + days);
  if (!r || !r.ok) return;
  const data = await r.json();
  requestAnimationFrame(() => drawFeaturePie(data));
}

async function loadCostPrices() {
  const r = await apiFetch('/api/admin/costs/prices');
  if (!r || !r.ok) return;
  const prices = await r.json();

  const tableEl = document.getElementById('cost-prices-table');
  if (!tableEl) return;
  while (tableEl.firstChild) tableEl.removeChild(tableEl.firstChild);

  const thead = document.createElement('thead');
  const hrow = document.createElement('tr');
  ['Modèle', 'Input / 1k tokens', 'Output / 1k tokens'].forEach(function(label) {
    const th = document.createElement('th');
    th.textContent = label;
    th.style.cssText = 'padding:6px 10px;text-align:left;color:rgba(255,255,255,0.45);font-size:0.75rem;font-weight:600;border-bottom:1px solid rgba(255,255,255,0.08);white-space:nowrap;';
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  tableEl.appendChild(thead);

  const tbody = document.createElement('tbody');
  const models = Object.keys(prices).sort();
  models.forEach(function(model) {
    const info = prices[model];
    const tr = document.createElement('tr');
    tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.04);';

    const tdModel = document.createElement('td');
    tdModel.textContent = model;
    tdModel.style.cssText = 'padding:6px 10px;font-size:0.8rem;color:rgba(255,255,255,0.8);font-family:var(--font-mono);';

    const tdIn = document.createElement('td');
    tdIn.textContent = info.input_per_1k !== undefined ? '$' + info.input_per_1k.toFixed(6) : '—';
    tdIn.style.cssText = 'padding:6px 10px;font-size:0.8rem;color:#06b6d4;font-family:var(--font-mono);';

    const tdOut = document.createElement('td');
    tdOut.textContent = info.output_per_1k !== undefined ? '$' + info.output_per_1k.toFixed(6) : '—';
    tdOut.style.cssText = 'padding:6px 10px;font-size:0.8rem;color:#eab308;font-family:var(--font-mono);';

    tr.appendChild(tdModel);
    tr.appendChild(tdIn);
    tr.appendChild(tdOut);
    tbody.appendChild(tr);
  });
  tableEl.appendChild(tbody);
}

async function loadCostLogs(page) {
  _costsLogsPage = page || 1;
  const days = { '7d': 7, '30d': 30, '90d': 90 }[currentCostRange] || 7;
  const r = await apiFetch('/api/admin/costs/logs?days=' + days + '&page=' + _costsLogsPage + '&limit=50');
  if (!r || !r.ok) return;
  const data = await r.json();

  const tableEl = document.getElementById('cost-logs-table');
  if (!tableEl) return;
  while (tableEl.firstChild) tableEl.removeChild(tableEl.firstChild);

  const thead = document.createElement('thead');
  const hrow = document.createElement('tr');
  ['Date/Heure', 'Modèle', 'Tokens In', 'Tokens Out', 'Coût', 'Purpose', 'Utilisateur'].forEach(function(label) {
    const th = document.createElement('th');
    th.textContent = label;
    th.style.cssText = 'padding:6px 10px;text-align:left;color:rgba(255,255,255,0.45);font-size:0.75rem;font-weight:600;border-bottom:1px solid rgba(255,255,255,0.08);white-space:nowrap;';
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  tableEl.appendChild(thead);

  const tbody = document.createElement('tbody');
  (data.logs || []).forEach(function(log) {
    const tr = document.createElement('tr');
    tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.04);';

    function cell(text, extraStyle) {
      const td = document.createElement('td');
      td.textContent = text !== null && text !== undefined ? String(text) : '—';
      td.style.cssText = 'padding:5px 10px;font-size:0.78rem;' + (extraStyle || 'color:rgba(255,255,255,0.75);');
      return td;
    }

    const dt = log.datetime ? log.datetime.replace('T', ' ').slice(0, 19) : '—';
    tr.appendChild(cell(dt, 'color:rgba(255,255,255,0.45);font-family:var(--font-mono);white-space:nowrap;'));
    tr.appendChild(cell(log.model, 'color:rgba(255,255,255,0.75);font-family:var(--font-mono);'));
    tr.appendChild(cell(log.input_tokens !== undefined ? log.input_tokens.toLocaleString() : '—', 'color:#06b6d4;text-align:right;font-family:var(--font-mono);'));
    tr.appendChild(cell(log.output_tokens !== undefined ? log.output_tokens.toLocaleString() : '—', 'color:#eab308;text-align:right;font-family:var(--font-mono);'));
    tr.appendChild(cell(log.cost_usd !== undefined ? '$' + log.cost_usd.toFixed(6) : '—', 'color:#FFD700;font-family:var(--font-mono);'));
    tr.appendChild(cell(log.purpose, 'color:rgba(255,255,255,0.6);'));
    tr.appendChild(cell(log.username || '—', 'color:rgba(255,255,255,0.5);'));
    tbody.appendChild(tr);
  });
  tableEl.appendChild(tbody);

  // Pagination
  const paginEl = document.getElementById('cost-logs-pagination');
  if (!paginEl) return;
  while (paginEl.firstChild) paginEl.removeChild(paginEl.firstChild);

  const total = data.total || 0;
  const limit = data.limit || 50;
  const currentPage = data.page || 1;
  const totalPages = Math.ceil(total / limit);

  if (totalPages <= 1) return;

  const from = Math.min((currentPage - 1) * limit + 1, total);
  const to = Math.min(currentPage * limit, total);

  const paginWrap = document.createElement('div');
  paginWrap.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:16px;padding:12px 0;font-size:0.82rem;';

  const prevBtn = document.createElement('button');
  prevBtn.textContent = 'Précédent';
  prevBtn.className = 'btn-secondary';
  prevBtn.style.cssText = 'padding:4px 12px;font-size:0.78rem;';
  prevBtn.disabled = currentPage <= 1;
  prevBtn.onclick = function() { loadCostLogs(currentPage - 1); };

  const info = document.createElement('span');
  info.style.cssText = 'color:rgba(255,255,255,0.45);';
  info.textContent = from + '–' + to + ' sur ' + total;

  const nextBtn = document.createElement('button');
  nextBtn.textContent = 'Suivant';
  nextBtn.className = 'btn-secondary';
  nextBtn.style.cssText = 'padding:4px 12px;font-size:0.78rem;';
  nextBtn.disabled = currentPage >= totalPages;
  nextBtn.onclick = function() { loadCostLogs(currentPage + 1); };

  paginWrap.appendChild(prevBtn);
  paginWrap.appendChild(info);
  paginWrap.appendChild(nextBtn);
  paginEl.appendChild(paginWrap);
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
        <button class="chat-session-back-today" id="chat-back-today" onclick="chatBackToToday()" style="display:none" title="Retour à aujourd'hui">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>
          Aujourd'hui
        </button>
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
  if (_chatWs) {
    _chatWs._intentionalClose = true;
    _chatWs.close();
    _chatWs = null;
  }
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

  _chatWs.onclose = function() {
    if (this._intentionalClose) return;
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
  const backBtn = document.getElementById('chat-back-today');

  if (dateStr === today) {
    // Back to live mode
    _chatViewingDate = null;
    if (label) label.textContent = "Aujourd'hui";
    if (inputBar) inputBar.style.display = '';
    if (backBtn) backBtn.style.display = 'none';
    // Reconnect WS to get today's messages
    chatConnectWs();
  } else {
    _chatViewingDate = dateStr;
    if (label) label.textContent = _formatSessionDate(dateStr);
    if (inputBar) inputBar.style.display = 'none'; // hide input for archived sessions
    if (backBtn) backBtn.style.display = '';
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

function chatBackToToday() {
  const today = new Date().toISOString().slice(0, 10);
  chatLoadDay(today);
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

  for (const emotion of EMOTIONS) {
    const value = emotions[emotion] ?? 0;
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
      <span id="decay-time-${name}" style="font-size:0.8rem;color:rgba(255,255,255,0.5);white-space:nowrap">100→0% en <strong style="color:#e2e8f0">${timeLabel}</strong></span>
    </div>`;
  }).join('');
  const boredomRise = cfg.emotions.boredom && cfg.emotions.boredom.boredom_rise_per_hour != null ? cfg.emotions.boredom.boredom_rise_per_hour : 1.2;
  const boredomH = boredomRise > 0 ? 1/boredomRise : Infinity;
  const boredomLabel = boredomH === Infinity ? '∞' : boredomH < 1 ? Math.round(boredomH*60)+' min' : Math.round(boredomH*10)/10+' h';
  lambdaCard.innerHTML = `
    <div class="config-section-title">DÉCROISSANCE ÉMOTIONS (λ)</div>
    <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:0 0 12px">λ = vitesse de décroissance par heure. Plus la valeur est élevée, plus l'émotion retombe vite. Boredom monte avec l'inactivité et n'utilise pas ce paramètre.</p>
    ${lambdaRows}
    <div style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.08)">
      <div style="display:flex;align-items:center;gap:12px">
        <label class="field-label" for="cfg-boredom-rise" style="color:${EMOTION_COLORS['boredom'] || 'var(--text-muted)'};min-width:100px">BOREDOM ↑/h</label>
        <input type="number" id="cfg-boredom-rise" min="0" max="10" step="0.1" value="${boredomRise}" style="width:90px" oninput="updateBoredomTime(this)">
        <span id="boredom-time-info" style="font-size:0.8rem;color:rgba(255,255,255,0.5);white-space:nowrap">0→100% en <strong style="color:#e2e8f0">${boredomLabel}</strong></span>
      </div>
      <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:8px 0 0">Vitesse de montée de l'ennui par heure d'inactivité. 1.2 = ennui max en ~50 min.</p>
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
      <p style="font-size:0.7rem;color:rgba(255,255,255,0.35);margin-top:4px">Alertes coûts et erreurs envoyées dans ce salon</p>
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
      <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Nombre de messages avant déclenchement</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-window">Fenêtre (secondes)</label>
      <input type="number" id="cfg-spam-window" min="30" max="600" value="${(cfg.discord.spam_detection || {}).window_seconds || 120}">
      <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Période de temps pour compter les messages</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-mute">Durée mute (minutes)</label>
      <input type="number" id="cfg-spam-mute" min="1" max="60" value="${(cfg.discord.spam_detection || {}).mute_minutes || 5}">
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-anger">Delta colère par message muté</label>
      <input type="number" id="cfg-spam-anger" min="0.01" max="0.2" step="0.01" value="${(cfg.discord.spam_detection || {}).spam_anger_delta || 0.05}">
      <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Augmentation de la colère quand un utilisateur muté continue de parler</p>
    </div>
    <div class="field-group">
      <label class="field-label" for="cfg-spam-exempt">Channels exemptés (IDs séparés par virgule)</label>
      <input type="text" id="cfg-spam-exempt" value="${((cfg.discord.spam_detection || {}).exempt_channels || []).join(', ')}">
      <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Ces salons ignorent la détection de spam</p>
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
        <label class="field-label" for="cfg-reasoning-effort">Niveau d'effort (reasoning) <span style="font-size:0.7rem;color:rgba(255,255,255,0.3)">OpenAI only</span></label>
        <select id="cfg-reasoning-effort">
          ${REASONING_EFFORTS.map(function(e) { return '<option value="' + e + '"' + (e === cfg.openai.reasoning_effort ? ' selected' : '') + '>' + e.toUpperCase() + '</option>'; }).join('')}
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="cfg-text-verbosity">Verbosité des réponses <span style="font-size:0.7rem;color:rgba(255,255,255,0.3)">OpenAI only</span></label>
        <select id="cfg-text-verbosity">
          ${TEXT_VERBOSITIES.map(function(v) { return '<option value="' + v + '"' + (v === cfg.openai.text_verbosity ? ' selected' : '') + '>' + v.toUpperCase() + '</option>'; }).join('')}
        </select>
      </div>
    </div>
    <div id="claude-specific-settings" style="display:none">
      <div class="field-group">
        <label class="field-label" for="cfg-thinking-type">Réflexion (thinking) <span style="font-size:0.7rem;color:rgba(255,255,255,0.3)">Claude only</span></label>
        <select id="cfg-thinking-type" onchange="onThinkingTypeChange()">
          ${THINKING_TYPES.map(function(t) { return '<option value="' + t + '"' + (t === (cfg.llm?.primary?.thinking_type || 'disabled') ? ' selected' : '') + '>' + (t === 'disabled' ? 'DÉSACTIVÉ' : t === 'adaptive' ? 'ADAPTATIF' : 'ACTIVÉ (budget fixe)') + '</option>'; }).join('')}
        </select>
      </div>
      <div id="thinking-effort-group" class="field-group" style="display:none">
        <label class="field-label" for="cfg-thinking-effort">Niveau d'effort thinking</label>
        <select id="cfg-thinking-effort">
          ${THINKING_EFFORTS.map(function(e) { return '<option value="' + e + '"' + (e === (cfg.llm?.primary?.thinking_effort || 'medium') ? ' selected' : '') + '>' + e.toUpperCase() + '</option>'; }).join('')}
        </select>
        <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">LOW = rapide · MEDIUM = équilibré · HIGH = défaut, pense souvent · MAX = max (Opus 4.6 only)</p>
      </div>
      <div id="thinking-budget-group" class="field-group" style="display:none">
        <label class="field-label" for="cfg-thinking-budget">Budget tokens thinking</label>
        <input type="number" id="cfg-thinking-budget" min="1000" max="128000" step="1000" value="${cfg.llm?.primary?.thinking_budget_tokens || 10000}">
        <p style="font-size:0.75rem;color:rgba(255,255,255,0.35);margin:4px 0 0">Doit être inférieur à max_tokens. 10k = standard, 50k+ = problèmes complexes</p>
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
        <button class="mem-subnav-pill" data-subtab="instances" onclick="switchSystemeSubTab('instances')" style="display:none">Instances</button>
      </div>
      <div class="mem-subnav-content active" id="systeme-sub-logs"></div>
      <div class="mem-subnav-content" id="systeme-sub-twitch"></div>
      <div class="mem-subnav-content" id="systeme-sub-overlay"></div>
      <div class="mem-subnav-content" id="systeme-sub-instances"></div>
    `;
    // Afficher le bouton Instances uniquement sur le bot principal
    apiFetch('/api/admin/config').then(async r => {
      if (!r || !r.ok) return;
      const data = await r.json();
      if (data.is_main) {
        const btn = el.querySelector('[data-subtab="instances"]');
        if (btn) btn.style.display = '';
      }
    });
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
  } else if (subtab === 'instances') {
    _renderSystemeInstances(panel);
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
    var statusText = connected ? (username || 'Connecte') : 'Non connecte';
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
    + '<hr style="border-color:rgba(255,255,255,0.08);margin:16px 0">'
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

function _renderSystemeInstances(panel) {
  if (!panel) return;
  // Delegate to renderInstancesTab — move content
  const instEl = document.getElementById('tab-admin-instances');
  if (panel.children.length === 0) {
    renderInstancesTab();
    if (instEl && instEl.children.length > 0) {
      while (instEl.firstChild) panel.appendChild(instEl.firstChild);
    }
  } else {
    // Refresh invites and instances
    loadInvites();
    loadInstances();
  }
}

// ── Costs Tab with sub-nav (Résumé · Détail) ─────────────────────────────────


function renderCostsTab() {
  const el = document.getElementById('tab-admin-costs');
  if (!el) return;

  if (!el.querySelector('.mem-subnav')) {
    el.innerHTML = `
      <div class="mem-subnav">
        <button class="mem-subnav-pill active" data-subtab="resume" onclick="switchCostsSubTab('resume')">Résumé</button>
        <button class="mem-subnav-pill" data-subtab="detail" onclick="switchCostsSubTab('detail')">Détail</button>
      </div>
      <div class="mem-subnav-content active" id="costs-sub-resume">
        <!-- KPI Row -->
        <div class="grid grid-cols-2 lg:grid-cols-5 gap-6 mb-6">
          <div class="card" id="kpi-month">
            <div class="card-title">MOIS EN COURS</div>
            <div class="card-value" id="cost-month-total">—</div>
            <div id="cost-month-change" style="color:rgba(255,255,255,0.45);font-size:0.75rem;margin-top:6px"></div>
          </div>
          <div class="card" id="kpi-forecast">
            <div class="card-title">PREVISION FIN MOIS</div>
            <div class="card-value" id="cost-forecast">—</div>
            <div id="cost-forecast-detail" style="color:rgba(255,255,255,0.45);font-size:0.75rem;margin-top:6px"></div>
          </div>
          <div class="card" id="kpi-today">
            <div class="card-title">AUJOURD'HUI</div>
            <div class="card-value" id="cost-today-total">—</div>
          </div>
          <div class="card" id="kpi-avg">
            <div class="card-title">COUT / MSG</div>
            <div class="card-value" id="cost-avg-msg">—</div>
          </div>
          <div class="card" id="kpi-threshold">
            <div class="card-title">SEUIL D'ALERTE</div>
            <div class="card-value" id="cost-threshold">—</div>
            <div id="cost-threshold-pct" style="color:rgba(255,255,255,0.45);font-size:0.75rem;margin-top:6px"></div>
          </div>
        </div>
        <!-- Cost Graph -->
        <div class="card mb-6">
          <div class="graph-header">
            <span class="graph-title" id="cost-graph-title">7 DERNIERS JOURS</span>
            <div class="graph-range-btns">
              <button class="cost-range-btn active" onclick="setCostRange('7d')" aria-label="7 derniers jours">7J</button>
              <button class="cost-range-btn" onclick="setCostRange('30d')" aria-label="30 derniers jours">30J</button>
              <button class="cost-range-btn" onclick="setCostRange('90d')" aria-label="90 derniers jours">90J</button>
            </div>
          </div>
          <canvas id="costCanvas" height="165" aria-label="Graphique des couts journaliers"></canvas>
          <div id="cost-graph-legend" style="display:flex;gap:16px;padding:6px 10px;font-size:0.72rem;color:rgba(255,255,255,0.45)">
            <span>&#9473; Periode courante</span>
            <span style="opacity:0.5">&#9477; Periode precedente</span>
          </div>
        </div>
      </div>
      <div class="mem-subnav-content" id="costs-sub-detail">
        <!-- Breakdowns -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div class="card">
            <div class="card-title">PAR MODELE</div>
            <div id="cost-by-model">—</div>
          </div>
          <div class="card">
            <div class="card-title">PAR PURPOSE</div>
            <div id="cost-by-purpose">—</div>
          </div>
          <div class="card">
            <div class="card-title">TOP UTILISATEURS</div>
            <div id="cost-top-users">—</div>
          </div>
        </div>
        <!-- Alert bar -->
        <div class="card" id="cost-alert-bar" style="margin-top:24px;display:none">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span id="cost-alert-text"></span>
            <span id="cost-alert-pct" style="color:rgba(255,255,255,0.45)"></span>
          </div>
        </div>
      </div>
    `;
  }

  // Inject new detail sections (par fonctionnalité, prix tokens, journal) if not yet built
  const detailEl = document.getElementById('costs-sub-detail');
  if (detailEl && !detailEl.querySelector('#feature-bars')) {
    // ── Section 1: Par fonctionnalité ──
    const sec1 = document.createElement('div');
    sec1.className = 'card';
    sec1.style.marginBottom = '24px';

    const title1 = document.createElement('div');
    title1.className = 'card-title';
    title1.textContent = 'PAR FONCTIONNALITÉ';
    sec1.appendChild(title1);

    const pieCanvas = document.createElement('canvas');
    pieCanvas.id = 'featurePieCanvas';
    pieCanvas.height = 200;
    pieCanvas.setAttribute('aria-label', 'Camembert des coûts par fonctionnalité');
    pieCanvas.style.cssText = 'display:block;width:100%;';
    sec1.appendChild(pieCanvas);

    const featureBars = document.createElement('div');
    featureBars.id = 'feature-bars';
    featureBars.style.cssText = 'margin-top:16px;';
    sec1.appendChild(featureBars);

    // ── Section 2: Prix des tokens ──
    const sec2 = document.createElement('div');
    sec2.className = 'card';
    sec2.style.marginBottom = '24px';

    const title2 = document.createElement('div');
    title2.className = 'card-title';
    title2.textContent = 'PRIX DES TOKENS';
    sec2.appendChild(title2);

    const pricesWrap = document.createElement('div');
    pricesWrap.style.cssText = 'overflow-x:auto;';
    const pricesTable = document.createElement('table');
    pricesTable.id = 'cost-prices-table';
    pricesTable.style.cssText = 'width:100%;border-collapse:collapse;';
    pricesWrap.appendChild(pricesTable);
    sec2.appendChild(pricesWrap);

    // ── Section 4: Journal des appels ──
    const sec4 = document.createElement('div');
    sec4.className = 'card';
    sec4.style.marginTop = '24px';

    const title4 = document.createElement('div');
    title4.className = 'card-title';
    title4.textContent = 'JOURNAL DES APPELS';
    sec4.appendChild(title4);

    const logsWrap = document.createElement('div');
    logsWrap.style.cssText = 'overflow-x:auto;';
    const logsTable = document.createElement('table');
    logsTable.id = 'cost-logs-table';
    logsTable.style.cssText = 'width:100%;border-collapse:collapse;';
    logsWrap.appendChild(logsTable);
    sec4.appendChild(logsWrap);

    const logsPagin = document.createElement('div');
    logsPagin.id = 'cost-logs-pagination';
    sec4.appendChild(logsPagin);

    // Insert sec1 and sec2 before the existing breakdowns grid
    const breakdownsGrid = detailEl.querySelector('.grid');
    detailEl.insertBefore(sec2, breakdownsGrid);
    detailEl.insertBefore(sec1, sec2);

    // Append sec4 (journal) after breakdowns grid, before alert bar
    const alertBar = document.getElementById('cost-alert-bar');
    if (alertBar) {
      detailEl.insertBefore(sec4, alertBar);
    } else {
      detailEl.appendChild(sec4);
    }
  }

  switchCostsSubTab(_costsSubTab);
  loadCosts();
}

function switchCostsSubTab(subtab) {
  _costsSubTab = subtab;
  const el = document.getElementById('tab-admin-costs');
  if (!el) return;
  el.querySelectorAll('.mem-subnav-pill').forEach(function(p) {
    p.classList.toggle('active', p.dataset.subtab === subtab);
  });
  el.querySelectorAll('.mem-subnav-content').forEach(function(c) { c.classList.remove('active'); });
  const panel = document.getElementById('costs-sub-' + subtab);
  if (panel) panel.classList.add('active');
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
        <button class="mem-subnav-pill" data-subtab="notes" onclick="switchMemoireSubTab('notes')">Notes persistantes</button>
      </div>
      <div class="mem-subnav-content active" id="memoire-sub-users"></div>
      <div class="mem-subnav-content" id="memoire-sub-global"></div>
      <div class="mem-subnav-content" id="memoire-sub-dashboard"></div>
      <div class="mem-subnav-content" id="memoire-sub-notes"></div>
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
  } else if (subtab === 'notes') {
    if (panel) loadNotesTab(panel);
  }
}


// ── Persistent notes tab ─────────────────────────────────────────────────────

async function loadNotesTab(panel) {
  if (!panel) return;
  panel.innerHTML = '<p style="color:rgba(255,255,255,0.45);padding:16px">Chargement...</p>';

  const r = await apiFetch('/api/admin/notes');
  if (!r || !r.ok) { panel.textContent = 'Erreur de chargement'; return; }
  const data = await r.json();
  const notes = data.notes || [];

  const addFormId = 'notes-add-form';
  let html = '<div class="card mb-4">';
  html += '<div class="card-title">AJOUTER UNE NOTE</div>';
  html += '<div style="display:flex;flex-direction:column;gap:8px" id="' + addFormId + '">';
  html += '<input id="note-new-title" class="input" placeholder="Titre" style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:8px 12px;color:#fff" />';
  html += '<textarea id="note-new-content" class="input" rows="3" placeholder="Contenu" style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:8px 12px;color:#fff;resize:vertical"></textarea>';
  html += '<button class="btn btn-sm" onclick="saveNewNote()">Enregistrer</button>';
  html += '</div></div>';

  if (notes.length === 0) {
    html += '<p style="color:rgba(255,255,255,0.45);padding:8px">Aucune note persistante</p>';
  } else {
    html += '<div class="card"><div class="card-title">NOTES (' + notes.length + ')</div><div id="notes-list">';
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
    + '<span style="color:rgba(255,255,255,0.35);font-size:11px">' + date + '</span>'
    + '</div>'
    + '<div id="note-content-' + id + '" style="color:rgba(255,255,255,0.7);font-size:13px;white-space:pre-wrap">' + content + '</div>'
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
          <p>Avec le temps, chaque émotion <strong>retombe naturellement vers zéro</strong>, comme un humain qui se calme. La vitesse de retombée est différente pour chaque émotion — la colère s'apaise en quelques heures, la tristesse persiste plus longtemps. L'<strong>ennui</strong> est spécial : il monte linéairement quand personne n'interagit avec Wally.</p>
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
              <p class="jd-tech-note"><strong>Décroissance exponentielle</strong> : un λ élevé = retombée rapide. Δt est mesuré en <strong>heures</strong>. Un task en arrière-plan applique cette décroissance toutes les 60 secondes. L'ennui monte linéairement pendant l'inactivité (configurable via <code>boredom_rise_per_hour</code>).</p>
              <p class="jd-tech-note"><strong>Trust score et colère</strong> : quand le trust score est bas (&lt;0.3), les deltas de colère sont amplifiés. Un nouvel utilisateur (trust=0.0) provoquera une réaction de colère plus forte qu'un habitué (trust=0.8). C'est un mécanisme de protection naturel.</p>
              <p class="jd-tech-note"><strong>Suppression bidirectionnelle</strong> : quand une émotion monte, elle érode partiellement ses contraires. Joie → colère (×0.8), joie → tristesse (×0.8), colère → joie (×0.4). De plus, à chaque tick de decay, si colère et joie coexistent, elles s'érodent mutuellement en continu (compétition, K=0.05). Colère et ennui peuvent coexister — c'est intentionnel.</p>
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
          <p><strong>Alias et mentions tierces</strong> — Wally sait que "melio" et "Meliodas" sont la même personne grâce à une table d'alias (<code>user_aliases</code>). Quand il détecte un pseudo connu dans la conversation (même s'il n'est pas l'auteur du message), il charge automatiquement ses souvenirs et les injecte dans le contexte. Si le pseudo est inconnu mais ressemble à quelqu'un qu'il connaît (via correspondance floue à 75%), il note discrètement la ressemblance. Les alias sont extraits automatiquement par le FactExtractor ou ajoutés manuellement depuis le dashboard (modal utilisateur > section "Alias connus").</p>
          <p><strong>La mémoire globale</strong> — des connaissances partagées par toute la communauté : liens importants, événements du serveur, ressources communes. Contrairement à la mémoire individuelle, ces faits sont consultés <strong>pour chaque requête</strong>, peu importe qui pose la question. Les administrateurs peuvent gérer ces connaissances via l'onglet « Mémoire » du dashboard, et le FactExtractor les détecte aussi automatiquement dans les conversations.</p>
          <p><strong>Maintenance automatique</strong> — Wally ne se contente pas de stocker des souvenirs, il les entretient. Chaque nouveau souvenir est évalué pour sa complétude : si une information est vague ou incomplète (une date sans mois, un lieu non précisé), Wally note une question à poser et la glisse naturellement dans une prochaine conversation. Chaque soir, 30 minutes avant son journal, il fait le tri : il supprime les faits périmés, reformule les vagues, et identifie de nouvelles questions. Maximum 1 question par conversation, maximum 3 tentatives — Wally insiste, mais pas trop.</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — Qdrant, embeddings, trust score</summary>
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
              <p class="jd-tech-note"><strong>QdrantMemoryStore</strong> gère l'accès direct à <strong>Qdrant</strong> (base vectorielle auto-hébergée) : embedding via OpenAI <code>text-embedding-3-small</code>, stockage avec payloads structurés (texte, catégorie, date, source), et recherche par similarité avec filtrage natif.</p>
              <p class="jd-tech-note"><strong>Trust score</strong> : chaque utilisateur a un score de confiance (0.0 → 1.0) qui évolue avec le temps. +0.01 par interaction positive, -0.05 pour les comportements toxiques. Le score part à 0.0 — la confiance se mérite.</p>
              <p class="jd-tech-note"><strong>Sliding window</strong> : la mémoire courte garde les N derniers messages. Quand le nombre de tokens dépasse un seuil, les messages les plus anciens sont résumés par un modèle secondaire et remplacés par un bloc résumé.</p>
              <p class="jd-tech-note"><strong>Memory scoring</strong> : chaque <code>memory.add()</code> déclenche un appel LLM secondaire (<code>_evaluate</code>) qui évalue la complétude du souvenir. Les questions générées sont stockées dans <code>memory_questions</code> et injectées dans le prompt (max 1 par conversation, max 3 tentatives). Si le nouveau souvenir répond à une question existante, elle est automatiquement résolue. Les questions épuisées (3 tentatives) sont re-proposées après 24h via le champ <code>last_attempt_at</code>.</p>
              <p class="jd-tech-note"><strong>Nettoyage quotidien</strong> : cron 30min avant le journal (<code>run_memory_cleanup</code>). Passe en revue les souvenirs des 20 utilisateurs les plus actifs, identifie les faits périmés/vagues via LLM, et applique suppressions + reformulations via le store Qdrant directement.</p>
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
          <p>Si Wally a visité des chaînes Twitch invitées dans la journée, il les mentionne dans son journal comme des <strong>petits voyages</strong> : nom de la chaîne, durée de la visite, ambiance et moments notables, rédigés à la première personne.</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — DailyJournal et sources de données</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/journal.py — DailyJournal</div>
              <pre><code># Sources de données (ordre de priorité / fallback) :
# 1. daily_log (SQLite) — tous les messages du jour, survit aux redémarrages
# 2. Discord channel history — fallback API si daily_log vide
# 3. RAM context windows — buffers mémoire de la session en cours
# 4. Qdrant memory — faits stockés en mémoire longue

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
# - Un graphe Matplotlib (PNG) des émotions du jour
# - Les visites Twitch du jour (twitch_visits_block) :
#   chaque visite = résumé LLM carnet de voyage (channel, durée, ambiance)</code></pre>
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
          <p>Wally peut <strong>générer des images</strong> via la commande <code>/imagine</code> sur Discord ou dans le chat web. Pendant la génération, un <strong>GIF de chargement</strong> aléatoire s'affiche avec des phrases rotatives toutes les 5 secondes. Le modèle secondaire génère ensuite un <strong>titre court et créatif</strong>, et l'image finale remplace l'embed de chargement.</p>
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
                <span>EmotionEngine · MemoryService · OpenAIClient · PersonaService · ActionService · Config</span>
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

      <!-- Section 8: ActionService -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: #06b6d4">8</span>
          <h3>Actions planifiées</h3>
        </div>
        <div class="jd-body">
          <p>Wally peut <strong>créer ses propres tâches planifiées</strong> quand on lui demande. « Rappelle-moi d'acheter du pain à 18h », « ping-moi toutes les 30 minutes pour boire de l'eau » — il comprend la demande, crée la tâche, et l'exécute au moment voulu.</p>
          <p>Il dispose de <strong>3 outils</strong> via tool calling :</p>
          <ul style="margin:0.5rem 0;padding-left:1.5rem;color:rgba(255,255,255,0.7)">
            <li><strong>create_action_task</strong> — créer un rappel ponctuel, récurrent ou cron</li>
            <li><strong>cancel_action_task</strong> — annuler par ID ou en langage naturel (« arrête le rappel du pain »)</li>
            <li><strong>list_action_tasks</strong> — lister ses tâches actives</li>
          </ul>
          <p>Les rappels ponctuels et récurrents ont des <strong>permissions séparées</strong> — on peut autoriser les rappels simples pour tout le monde mais réserver les récurrents aux modérateurs. Côté Discord, les permissions utilisent les <strong>vrais rôles du serveur</strong> (multi-sélection par guilde). Côté Twitch, la hiérarchie fixe (everyone → subscriber → vip → moderator → admin) est conservée. Tout est configurable depuis l'onglet <strong>Actions</strong> du dashboard.</p>
          <p>Quand un rappel se déclenche, <strong>Wally le formule avec sa personnalité</strong> et son humeur du moment — le message passe par le pipeline complet (persona, émotions, directives). Les tâches <strong>survivent aux redémarrages</strong> et les changements sont visibles <strong>en temps réel</strong> sur le dashboard via SSE.</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — architecture interne</summary>
            <div class="jd-code-block">
              <p class="jd-tech-note"><strong>4 services</strong> : <code>ActionRegistry</code> (catalogue + ACL), <code>ActionScheduler</code> (persistence + apscheduler), <code>ActionExecutor</code> (routing + livraison), <code>ActionService</code> (façade LLM).</p>
              <p class="jd-tech-note"><strong>Scheduler partagé</strong> : un seul <code>AsyncIOScheduler</code> pour le journal quotidien ET les tâches planifiées — pas de conflit.</p>
              <p class="jd-tech-note"><strong>Sécurité</strong> : max 10 tâches par utilisateur, intervalle minimum 5 minutes, pas d'escalade de privilèges, isolation (un user ne voit que ses tâches).</p>
              <p class="jd-tech-note"><strong>Auto-pause</strong> : après 3 échecs consécutifs, une tâche récurrente est mise en pause automatiquement avec le motif d'erreur visible dans le dashboard.</p>
              <p class="jd-tech-note"><strong>Permissions Discord</strong> : table <code>action_permissions_discord</code> avec clé composite <code>(action_type, guild_id, role_id)</code>. Cache in-memory dans <code>ActionRegistry._discord_perms</code>. Endpoint <code>/api/actions/discord-roles</code> expose les rôles depuis le cache gateway de discord.py.</p>
              <p class="jd-tech-note"><strong>SSE actions</strong> : <code>/api/admin/sse/actions</code> — fan-out par queue, événements broadcast depuis <code>ActionScheduler</code> via callback <code>on_change</code>.</p>
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
  loading.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
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
    empty.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
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
  loading.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
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
    empty.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
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
  loading.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
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
    empty.style.cssText = 'color:rgba(255,255,255,0.4);text-align:center;padding:32px';
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

// ── Instances tab ─────────────────────────────────────────────────────────────

function _makeGlassCard(withBottomMargin) {
  var card = document.createElement('div');
  card.style.cssText = 'background:rgba(255,255,255,0.03);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:1rem;box-shadow:0 4px 6px rgba(0,0,0,0.1)' + (withBottomMargin ? ';margin-bottom:12px' : '');
  return card;
}

function renderInstancesTab() {
  var el = document.getElementById('tab-admin-instances');
  if (!el) return;
  el.textContent = '';

  var header = document.createElement('div');
  header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:16px';
  var h3 = document.createElement('h3');
  h3.style.cssText = 'margin:0;font-size:1.1rem;font-weight:700;color:#e2e8f0';
  h3.textContent = 'Instances';
  var btnGroup = document.createElement('div');
  btnGroup.style.cssText = 'display:flex;gap:8px;align-items:center';
  var notifyAllBtn = document.createElement('button');
  notifyAllBtn.className = 'btn btn-sm';
  notifyAllBtn.style.cssText = 'color:rgba(6,182,212,0.9)';
  notifyAllBtn.textContent = '🔔 Notifier tout';
  notifyAllBtn.onclick = notifyAllInstancesUpdate;
  var genBtn = document.createElement('button');
  genBtn.className = 'btn btn-sm';
  genBtn.textContent = '+ Générer un lien';
  genBtn.onclick = generateInvite;
  btnGroup.appendChild(notifyAllBtn);
  btnGroup.appendChild(genBtn);
  header.appendChild(h3);
  header.appendChild(btnGroup);
  el.appendChild(header);

  var invCard = _makeGlassCard(true);
  var invTitle = document.createElement('div');
  invTitle.style.cssText = 'font-size:0.8rem;font-weight:600;color:rgba(255,255,255,0.6);margin-bottom:10px';
  invTitle.textContent = "Liens d'invitation";
  var invList = document.createElement('div');
  invList.id = 'invites-list';
  invList.style.cssText = 'font-size:0.82rem;color:rgba(255,255,255,0.45)';
  invList.textContent = 'Chargement...';
  invCard.appendChild(invTitle);
  invCard.appendChild(invList);
  el.appendChild(invCard);

  var instCard = _makeGlassCard(false);
  var instHeader = document.createElement('div');
  instHeader.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:10px';
  var instTitle = document.createElement('div');
  instTitle.style.cssText = 'font-size:0.8rem;font-weight:600;color:rgba(255,255,255,0.6)';
  instTitle.textContent = 'Instances actives';
  var publishAllBtn = document.createElement('button');
  publishAllBtn.className = 'btn btn-sm';
  publishAllBtn.textContent = '📤 Publier à tous';
  publishAllBtn.style.cssText = 'font-size:11px;padding:4px 10px;color:rgba(251,191,36,0.9)';
  publishAllBtn.onclick = async function() {
    var r = await apiFetch('/api/admin/setup/instances/publish-all-updates', { method: 'POST' });
    if (r && r.ok) { toast('Update publiée pour toutes les instances', 'success'); setTimeout(loadInstances, 500); }
    else { var d = r ? await r.json() : {}; toast('Erreur : ' + (d.detail || '?'), 'error'); }
  };
  instHeader.appendChild(instTitle);
  instHeader.appendChild(publishAllBtn);
  var instList = document.createElement('div');
  instList.id = 'instances-list';
  instList.style.cssText = 'font-size:0.82rem;color:rgba(255,255,255,0.45)';
  instList.textContent = 'Chargement...';
  var wizardLink = document.createElement('a');
  wizardLink.href = '/setup/preview';
  wizardLink.target = '_blank';
  wizardLink.rel = 'noopener noreferrer';
  wizardLink.style.cssText = 'display:inline-block;margin-top:10px;font-size:0.75rem;color:#06b6d4;text-decoration:underline;cursor:pointer';
  wizardLink.textContent = 'Ouvrir le wizard en mode test';
  instCard.appendChild(instHeader);
  instCard.appendChild(instList);
  instCard.appendChild(wizardLink);
  el.appendChild(instCard);

  loadInvites();
  loadInstances();
}

async function loadInvites() {
  try {
    var resp = await apiFetch('/api/admin/setup/invites');
    var data = await resp.json();
    var el = document.getElementById('invites-list');
    if (!el) return;
    el.textContent = '';
    if (!data.invites || data.invites.length === 0) {
      el.textContent = 'Aucun lien généré';
      return;
    }
    var statusColors = { pending: '#06b6d4', used: '#22c55e', expired: 'rgba(239,68,68,0.6)', revoked: 'rgba(255,255,255,0.2)' };
    data.invites.forEach(function(inv) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05)';
      var left = document.createElement('div');
      var tokenSpan = document.createElement('span');
      tokenSpan.style.cssText = 'font-family:monospace;font-size:12px;color:rgba(255,255,255,0.6)';
      tokenSpan.textContent = inv.token;
      var statusSpan = document.createElement('span');
      statusSpan.style.cssText = 'margin-left:8px;font-size:12px;color:' + (statusColors[inv.status] || 'rgba(255,255,255,0.4)');
      statusSpan.textContent = inv.status;
      left.appendChild(tokenSpan);
      left.appendChild(statusSpan);
      if (inv.slug) {
        var slugSpan = document.createElement('span');
        slugSpan.style.cssText = 'margin-left:8px;font-size:12px;color:rgba(255,255,255,0.3)';
        slugSpan.textContent = '\u2192 ' + inv.slug;
        left.appendChild(slugSpan);
      }
      row.appendChild(left);
      if (inv.status === 'pending') {
        var btnGroup = document.createElement('div');
        btnGroup.style.cssText = 'display:flex;gap:6px';
        var copyBtn = document.createElement('button');
        copyBtn.className = 'btn btn-sm';
        copyBtn.title = 'Copier le lien';
        copyBtn.textContent = '\uD83D\uDCCB';
        copyBtn.onclick = (function(t) { return function() { copyInviteLink(t); }; })(inv.token_full || inv.token);
        var revokeBtn = document.createElement('button');
        revokeBtn.className = 'btn btn-sm btn-danger';
        revokeBtn.textContent = 'Révoquer';
        revokeBtn.onclick = (function(t) { return function() { revokeInvite(t); }; })(inv.token_full || inv.token);
        btnGroup.appendChild(copyBtn);
        btnGroup.appendChild(revokeBtn);
        row.appendChild(btnGroup);
      }
      el.appendChild(row);
    });
  } catch(e) { console.error('loadInvites', e); }
}

async function loadInstances() {
  try {
    var resp = await apiFetch('/api/admin/setup/instances');
    var data = await resp.json();
    var el = document.getElementById('instances-list');
    if (!el) return;
    el.textContent = '';
    if (!data.instances || data.instances.length === 0) {
      el.textContent = 'Aucune instance créée';
      return;
    }
    for (var i = 0; i < data.instances.length; i++) {
      var inst = data.instances[i];
      var running = inst.docker_status === 'running';

      // Charger la config de notification
      var cfg = {};
      try {
        var cr = await apiFetch('/api/admin/setup/instances/' + inst.slug + '/update-config');
        if (cr && cr.ok) cfg = await cr.json();
      } catch(e) {}

      var card = document.createElement('div');
      card.style.cssText = 'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:14px;margin-bottom:10px';

      // Ligne principale
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:10px';
      var left = document.createElement('div');
      var nameSpan = document.createElement('span');
      nameSpan.style.cssText = 'font-weight:600;color:rgba(255,255,255,0.85)';
      nameSpan.textContent = inst.slug;
      var statusSpan = document.createElement('span');
      statusSpan.style.cssText = 'margin-left:8px;font-size:12px;color:' + (running ? '#22c55e' : 'rgba(239,68,68,0.7)');
      statusSpan.textContent = '\u25CF ' + inst.docker_status;
      var portSpan = document.createElement('span');
      portSpan.style.cssText = 'margin-left:8px;font-size:12px;color:rgba(255,255,255,0.3)';
      portSpan.textContent = ':' + inst.port;
      var instVersionSpan = document.createElement('span');
      instVersionSpan.style.cssText = 'margin-left:10px;font-size:11px;color:rgba(255,255,255,0.2);font-family:monospace';
      instVersionSpan.textContent = '…';
      if (running) {
        fetch('http://' + window.location.hostname + ':' + inst.port + '/api/public/status')
          .then(function(r) { return r.ok ? r.json() : null; })
          .then(function(d) {
            if (!d || !d.git_hash || d.git_hash === 'unknown') { instVersionSpan.textContent = ''; return; }
            instVersionSpan.textContent = 'build ' + d.git_hash + ' · ' + _formatBuildDate(d.build_date);
          })
          .catch(function() { instVersionSpan.textContent = ''; });
      } else {
        instVersionSpan.textContent = '';
      }
      left.appendChild(nameSpan);
      left.appendChild(statusSpan);
      left.appendChild(portSpan);
      left.appendChild(instVersionSpan);
      row.appendChild(left);

      var btnGroup = document.createElement('div');
      btnGroup.style.cssText = 'display:flex;gap:6px';
      var toggleBtn = document.createElement('button');
      toggleBtn.className = 'btn btn-sm';
      if (running) {
        toggleBtn.style.color = 'rgba(239,68,68,0.8)';
        toggleBtn.textContent = 'Stop';
        toggleBtn.onclick = (function(s) { return function() { instanceAction(s, 'stop'); }; })(inst.slug);
      } else {
        toggleBtn.style.color = 'rgba(34,197,94,0.8)';
        toggleBtn.textContent = 'Start';
        toggleBtn.onclick = (function(s) { return function() { instanceAction(s, 'start'); }; })(inst.slug);
      }
      btnGroup.appendChild(toggleBtn);
      row.appendChild(btnGroup);
      card.appendChild(row);

      // Canal de notification + boutons update
      var updateRow = document.createElement('div');
      updateRow.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap';
      var chanInput = document.createElement('input');
      chanInput.type = 'text';
      chanInput.placeholder = 'ID du salon Discord';
      chanInput.value = cfg.notify_channel_id || '';
      chanInput.style.cssText = 'flex:1;min-width:150px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:rgba(255,255,255,0.85);padding:5px 9px;font-size:12px;font-family:monospace;outline:none';
      chanInput.dataset.slug = inst.slug;

      var saveBtn = document.createElement('button');
      saveBtn.className = 'btn btn-sm';
      saveBtn.textContent = 'Enregistrer';
      saveBtn.style.cssText = 'font-size:11px;padding:4px 10px';
      saveBtn.onclick = (function(input, s) {
        return async function() {
          var r = await apiFetch('/api/admin/setup/instances/' + s + '/update-config', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ notify_channel_id: input.value.trim() })
          });
          if (r && r.ok) toast('Canal enregistré', 'success');
          else toast('Erreur', 'error');
        };
      })(chanInput, inst.slug);

      var notifyBtn = document.createElement('button');
      notifyBtn.className = 'btn btn-sm';
      notifyBtn.textContent = '🔔 Notifier';
      notifyBtn.style.cssText = 'font-size:11px;padding:4px 10px;color:rgba(6,182,212,0.9)';
      notifyBtn.onclick = (function(s) {
        return async function() {
          var r = await apiFetch('/api/admin/setup/instances/' + s + '/notify-update', { method: 'POST' });
          if (r && r.ok) toast('Notification envoyée à ' + s, 'success');
          else { var d = r ? await r.json() : {}; toast('Erreur : ' + (d.detail || '?'), 'error'); }
        };
      })(inst.slug);

      updateRow.appendChild(chanInput);
      updateRow.appendChild(saveBtn);
      updateRow.appendChild(notifyBtn);

      if (inst.update_available) {
        var cancelUpdateBtn = document.createElement('button');
        cancelUpdateBtn.className = 'btn btn-sm';
        cancelUpdateBtn.textContent = '✓ Publiée — Annuler';
        cancelUpdateBtn.style.cssText = 'font-size:11px;padding:4px 10px;color:rgba(34,197,94,0.9)';
        cancelUpdateBtn.onclick = (function(s) {
          return async function() {
            var r = await apiFetch('/api/admin/setup/instances/' + s + '/publish-update', { method: 'DELETE' });
            if (r && r.ok) { toast('Update annulée pour ' + s, 'success'); setTimeout(loadInstances, 500); }
            else { var d = r ? await r.json() : {}; toast('Erreur : ' + (d.detail || '?'), 'error'); }
          };
        })(inst.slug);
        updateRow.appendChild(cancelUpdateBtn);
      } else {
        var publishBtn = document.createElement('button');
        publishBtn.className = 'btn btn-sm';
        publishBtn.textContent = '📤 Publier update';
        publishBtn.style.cssText = 'font-size:11px;padding:4px 10px;color:rgba(251,191,36,0.9)';
        publishBtn.onclick = (function(s) {
          return async function() {
            var r = await apiFetch('/api/admin/setup/instances/' + s + '/publish-update', { method: 'POST' });
            if (r && r.ok) { toast('Update publiée pour ' + s, 'success'); setTimeout(loadInstances, 500); }
            else { var d = r ? await r.json() : {}; toast('Erreur : ' + (d.detail || '?'), 'error'); }
          };
        })(inst.slug);
        updateRow.appendChild(publishBtn);
      }
      card.appendChild(updateRow);
      el.appendChild(card);
    }
  } catch(e) { console.error('loadInstances', e); }
}

async function notifyAllInstancesUpdate() {
  var r = await apiFetch('/api/admin/setup/notify-all-updates', { method: 'POST' });
  if (!r || !r.ok) { toast('Erreur lors de la notification', 'error'); return; }
  var data = await r.json();
  var ok = data.results.filter(function(x) { return x.ok; }).length;
  var fail = data.results.length - ok;
  toast(ok + ' notification(s) envoyée(s)' + (fail ? ', ' + fail + ' erreur(s)' : ''), fail ? 'error' : 'success');
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

async function instanceAction(slug, action) {
  var r = await apiFetch('/api/admin/setup/instances/' + slug + '/' + action, { method: 'POST' });
  if (r && r.ok) {
    toast('Instance ' + slug + ' : ' + action, 'success');
  } else {
    toast('Erreur action ' + action, 'error');
  }
  setTimeout(loadInstances, 1500);
}

// ── Prompts & Persona Management ─────────────────────────────────────────────

var _promptsData = null;        // { persona: {}, system_prompts: {} }
var _promptsInstance = 'main';  // 'main' | slug
var _promptsSection = 'persona'; // 'persona' | 'system'
var _promptsFile = null;
var _promptsInstances = [];

async function renderPromptsTab() {
  var el = document.getElementById('tab-admin-prompts');
  if (!el) return;
  el.innerHTML = '<div style="padding:24px;color:rgba(255,255,255,0.4)">Chargement...</div>';

  // Charger instances + config modèles en parallèle
  var [ri] = await Promise.all([
    apiFetch('/api/admin/setup/instances'),
    _loadPromptsModels(),
  ]);
  _promptsInstances = (ri && ri.ok) ? (await ri.json()).instances || [] : [];

  await _loadPromptsData();
  _renderPromptsUI(el);
}

async function _loadPromptsData() {
  if (_promptsInstance === 'main') {
    var r = await apiFetch('/api/admin/prompts');
    _promptsData = (r && r.ok) ? await r.json() : { persona: {}, system_prompts: {} };
  } else {
    var r2 = await apiFetch('/api/admin/setup/instances/' + _promptsInstance + '/persona');
    var personaData = (r2 && r2.ok) ? (await r2.json()).persona : {};
    _promptsData = { persona: personaData, system_prompts: {} };
  }
  // Sélectionner le premier fichier si aucun sélectionné ou si fichier invalide
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

  // Sélecteur de bot
  var instanceOpts = '<option value="main">Bot principal</option>';
  _promptsInstances.forEach(function(inst) {
    instanceOpts += '<option value="' + inst.slug + '"' + (_promptsInstance === inst.slug ? ' selected' : '') + '>' + inst.slug + '</option>';
  });

  // Liste de fichiers
  var fileList = currentFiles.map(function(f) {
    return '<div class="prompt-file-item' + (f === _promptsFile ? ' active' : '') + '" onclick="selectPromptFile(\'' + f + '\')">' + f.replace('.md','') + '</div>';
  }).join('');

  el.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%;gap:0">
      <!-- Toolbar -->
      <div style="display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid rgba(255,255,255,0.07);flex-wrap:wrap">
        <div class="card-title" style="margin:0;flex:0 0 auto">PROMPTS</div>
        <select onchange="switchPromptsInstance(this.value)" style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;color:rgba(255,255,255,0.87);padding:5px 10px;font-size:13px">
          ${instanceOpts}
        </select>
        <div class="mem-subnav" style="margin-bottom:0;margin-left:auto">
          <button class="mem-subnav-pill ${_promptsSection==='persona'?'active':''}" onclick="switchPromptsSection('persona')">Persona</button>
          ${_promptsInstance === 'main' ? '<button class="mem-subnav-pill ' + (_promptsSection==='system'?'active':'') + '" onclick="switchPromptsSection(\'system\')">Système</button>' : ''}
        </div>
      </div>
      <!-- Body -->
      <div style="display:flex;flex:1;min-height:0;overflow:hidden">
        <!-- File list -->
        <div style="width:190px;flex-shrink:0;border-right:1px solid rgba(255,255,255,0.07);overflow-y:auto;padding:8px">
          ${fileList || '<div style="padding:12px;font-size:12px;color:rgba(255,255,255,0.3)">Aucun fichier</div>'}
        </div>
        <!-- Editor -->
        <div style="flex:1;display:flex;flex-direction:column;min-width:0;padding:12px 16px;gap:8px">
          ${_promptsFile ? `
            <div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0">
              <span style="font-size:13px;font-weight:600;color:rgba(255,255,255,0.6)">${_promptsFile}</span>
              <button class="btn-primary" onclick="savePromptFile()" style="font-size:12px;padding:6px 14px">💾 Sauvegarder</button>
            </div>
            <textarea id="prompt-editor" style="flex:1;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;color:rgba(255,255,255,0.87);padding:14px;font-size:13px;font-family:monospace;resize:vertical;line-height:1.6;outline:none;min-height:calc(100vh - 310px);width:100%;box-sizing:border-box" spellcheck="false">${escapeHtml(content)}</textarea>
            <div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0;min-height:22px">
              <div id="prompt-token-info" style="display:flex;gap:16px;font-size:11px;color:rgba(255,255,255,0.35)"></div>
              <div id="prompt-save-status" style="font-size:12px"></div>
            </div>
          ` : '<div style="color:rgba(255,255,255,0.3);font-size:13px;padding-top:40px;text-align:center">Sélectionne un fichier</div>'}
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
    item.style.cssText = 'padding:8px 12px;border-radius:8px;font-size:12px;cursor:pointer;color:rgba(255,255,255,0.6);transition:all .15s;margin-bottom:2px';
    if (item.classList.contains('active')) {
      item.style.background = 'rgba(6,182,212,0.15)';
      item.style.color = 'rgb(6,182,212)';
      item.style.borderLeft = '2px solid rgb(6,182,212)';
    }
    item.addEventListener('mouseenter', function() {
      if (!item.classList.contains('active')) item.style.background = 'rgba(255,255,255,0.05)';
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
      costStr = '<strong style="color:rgba(255,255,255,0.4)">prix inconnu</strong>';
    } else {
      var cost = (tokens / 1_000_000) * p.usd;
      var costFmt = cost < 0.0001 ? ('< $0.0001') : ('$' + cost.toFixed(4));
      costStr = '<strong style="color:rgba(255,255,255,0.55)">' + costFmt + '</strong>';
    }
    parts.push('<span>' + p.label + ' : ' + costStr + '/appel</span>');
  });
  el.innerHTML = parts.join('<span style="opacity:.3"> | </span>');
}

function selectPromptFile(filename) {
  _promptsFile = filename;
  _renderPromptsUI(document.getElementById('tab-admin-prompts'));
}

async function switchPromptsInstance(val) {
  _promptsInstance = val;
  _promptsSection = 'persona';
  _promptsFile = null;
  await _loadPromptsData();
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

  var url, r;
  if (_promptsInstance === 'main') {
    var type = _promptsSection === 'persona' ? 'persona' : 'system';
    url = '/api/admin/prompts/' + type + '/' + _promptsFile;
  } else {
    url = '/api/admin/setup/instances/' + _promptsInstance + '/persona/' + _promptsFile;
  }

  r = await apiFetch(url, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ content }) });
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
