// app.js — Wally Public UI Starter
// Appelle uniquement /api/public/* (aucune authentification requise)

var EMOTION_COLORS = {
  anger:    'var(--anger)',
  joy:      'var(--joy)',
  curiosity:'var(--curiosity)',
  sadness:  'var(--sadness)',
  boredom:  'var(--boredom)',
};
var EMOTION_LABELS = {
  anger:'Colère', joy:'Joie', curiosity:'Curiosité', sadness:'Tristesse', boredom:'Ennui',
};

// ── Utilitaires DOM ───────────────────────────────────────────────────────────

function setText(id, val) {
  var el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setClass(id, cls) {
  var el = document.getElementById(id);
  if (el) el.className = cls;
}

function el(tag, cls, text) {
  var e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// ── Status ────────────────────────────────────────────────────────────────────

async function loadStatus() {
  try {
    var r = await fetch('/api/public/status');
    if (!r.ok) return;
    var d = await r.json();

    var online = d.discord_online || d.twitch_online;
    setClass('dot-discord', 'dot ' + (d.discord_online ? 'online' : 'offline'));
    setClass('dot-twitch',  'dot ' + (d.twitch_online  ? 'online' : 'offline'));
    setText('lbl-discord', d.discord_online ? 'Discord' : 'Discord (hors ligne)');
    setText('lbl-twitch',  d.twitch_online  ? 'Twitch'  : 'Twitch (hors ligne)');

    if (d.uptime_seconds != null) setText('uptime', formatUptime(d.uptime_seconds));

    var hs = document.getElementById('header-status');
    if (hs) {
      hs.textContent = online ? 'En ligne' : 'Hors ligne';
      hs.style.color  = online ? 'var(--curiosity)' : 'var(--text-muted)';
    }
  } catch (_) {}
}

function formatUptime(s) {
  var h = Math.floor(s / 3600);
  var m = Math.floor((s % 3600) / 60);
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm';
}

// ── Stream Twitch ─────────────────────────────────────────────────────────────

async function loadStream() {
  try {
    var r = await fetch('/api/public/twitch/stream');
    if (!r.ok) return;
    var d = await r.json();
    var container = document.getElementById('stream-content');
    if (!container) return;

    container.textContent = '';
    if (d.stream_live) {
      container.appendChild(el('div', 'stream-game',    d.game_name  || ''));
      container.appendChild(el('div', 'stream-title',   d.title      || ''));
      container.appendChild(el('div', 'stream-viewers', (d.viewer_count || 0) + ' spectateurs'));
    } else {
      container.appendChild(el('span', 'stream-offline', 'Hors ligne'));
    }
  } catch (_) {}
}

// ── Emotions (SSE + fallback polling) ─────────────────────────────────────────

function initEmotions() {
  var container = document.getElementById('emotions-container');
  if (!container) return;

  Object.keys(EMOTION_COLORS).forEach(function(name) {
    var row     = el('div', 'emotion-row');
    var label   = el('span', 'emotion-name', EMOTION_LABELS[name]);
    var barBg   = el('div', 'emotion-bar-bg');
    var fill    = el('div', 'emotion-bar-fill');
    var pctSpan = el('span', 'emotion-pct', '0%');

    fill.id             = 'bar-' + name;
    pctSpan.id          = 'pct-' + name;
    fill.style.width      = '0%';
    fill.style.background = EMOTION_COLORS[name];

    barBg.appendChild(fill);
    row.appendChild(label);
    row.appendChild(barBg);
    row.appendChild(pctSpan);
    container.appendChild(row);
  });

  var sse = new EventSource('/api/public/sse/emotions');
  sse.addEventListener('emotion_update', function(e) {
    try { updateBars(JSON.parse(e.data)); } catch (_) {}
  });
  sse.onerror = function() {
    sse.close();
    setTimeout(pollEmotions, 5000);
  };
}

async function pollEmotions() {
  try {
    var r = await fetch('/api/public/emotions/history');
    if (r.ok) {
      var data = await r.json();
      if (data.length) updateBars(data[data.length - 1]);
    }
  } catch (_) {}
  setTimeout(pollEmotions, 10000);
}

function updateBars(state) {
  Object.keys(EMOTION_COLORS).forEach(function(name) {
    var val  = state[name] || 0;
    var pct  = Math.round(val * 100);
    var fill = document.getElementById('bar-' + name);
    var span = document.getElementById('pct-' + name);
    if (fill) fill.style.width = pct + '%';
    if (span) span.textContent = pct + '%';
  });

  var dominant = Object.keys(EMOTION_COLORS).reduce(function(a, b) {
    return (state[a] || 0) >= (state[b] || 0) ? a : b;
  });
  var stateEl = document.getElementById('emotion-state');
  if (stateEl) {
    if ((state[dominant] || 0) > 0.3) {
      stateEl.style.display = 'block';
      stateEl.textContent   = 'Émotion dominante : ' + EMOTION_LABELS[dominant];
    } else {
      stateEl.style.display = 'none';
    }
  }
}

// ── Galerie ───────────────────────────────────────────────────────────────────

async function loadGallery() {
  try {
    var r = await fetch('/api/public/gallery?limit=6&sort=date');
    if (!r.ok) return;
    var data   = await r.json();
    var images = data.images || data;
    if (!images || !images.length) return;

    var card = document.getElementById('gallery-card');
    var grid = document.getElementById('gallery-grid');
    if (!card || !grid) return;

    card.style.display = 'block';
    grid.textContent   = '';

    images.slice(0, 6).forEach(function(img) {
      var thumb = el('div', 'gallery-thumb');
      var image = document.createElement('img');
      image.src     = '/api/public/gallery/' + img.id + '/image';
      image.alt     = img.prompt || '';
      image.loading = 'lazy';
      image.addEventListener('click', (function(src, caption) {
        return function() { openModal(src, caption); };
      })(image.src, img.prompt || ''));
      thumb.appendChild(image);
      grid.appendChild(thumb);
    });
  } catch (_) {}
}

function openModal(src, caption) {
  var bg  = document.getElementById('modal-bg');
  var img = document.getElementById('modal-img');
  var cap = document.getElementById('modal-caption');
  if (!bg || !img) return;
  img.src = src;
  if (cap) cap.textContent = caption;
  bg.classList.add('open');
}

function closeModal() {
  var bg = document.getElementById('modal-bg');
  if (bg) bg.classList.remove('open');
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
  loadStatus();
  initEmotions();
  loadStream();
  loadGallery();

  var bg      = document.getElementById('modal-bg');
  var closeBtn = document.getElementById('modal-close');
  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  if (bg) bg.addEventListener('click', function(e) {
    if (e.target === bg) closeModal();
  });

  setInterval(loadStatus, 30000);
  setInterval(loadStream, 30000);
});
