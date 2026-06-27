// public-ui/tabs/status.js — arcade
import { emotions, onEmotionUpdate, connectCognitiveSSE } from '../app.js';

let _pollInterval    = null;
let _historyInterval = null;
let _historyData     = null;
let _container       = null;
let _unsubEmo        = null;
let _cognitiveES     = null;
let _feedEvents      = [];
let _historyBefore   = null;   // plus petit id chargé → pagination scroll-up
let _loadingMore     = false;

const EMO_COLORS = {
  anger: '#ef4444', joy: '#eab308', curiosity: '#22c55e',
  sadness: '#3b82f6', boredom: '#a855f7'
};
const EMO_LABELS = {
  anger: 'COLÈRE', joy: 'JOIE', curiosity: 'CURIOSITÉ',
  sadness: 'TRISTESSE', boredom: 'ENNUI'
};
// Métadonnées par type d'event : couleur, icône, libellé court lisible.
const FEED_META = {
  THINK:  { color: '#ffd400', icon: '💭', label: 'pense' },
  SPEAK:  { color: '#43e0ff', icon: '🗣', label: 'parle' },
  ACT:    { color: '#7CFC52', icon: '⚙', label: 'agit' },
  REACT:  { color: '#7CFC52', icon: '😶', label: 'réagit' },
  DM:     { color: '#43e0ff', icon: '✉', label: 'DM' },
  DM_SUPPRESSED: { color: '#6f6597', icon: '🤐', label: 'DM retenu' },
  DECIDE: { color: '#bf94ff', icon: '🎯', label: 'décide' },
  ATTN:   { color: '#ff3b6b', icon: '👁', label: 'remarque' },
  EVOLVE: { color: '#ff8a3b', icon: '🧬', label: 'évolue' },
  SLEEP:  { color: '#6f6597', icon: '😴', label: 'somnole' },
};
function feedMeta(type) {
  return FEED_META[type] || { color: '#fff', icon: '•', label: (type || '').toLowerCase() };
}

function formatUptime(seconds) {
  if (!seconds) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}j ${String(h).padStart(2, '0')}h`;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function feedText(e) {
  if (e.type === 'THINK') return e.text || '';
  if (e.type === 'SPEAK') return (e.channel ? '#' + e.channel + ' ' : '→ ') + (e.detail || '');
  if (e.type === 'REACT') return e.detail || ('a réagi ' + (e.emoji || ''));
  if (e.type === 'DM') return '→ ' + (e.target || 'créateur') + ' : ' + (e.message || '');
  if (e.type === 'DM_SUPPRESSED') return 'DM retenu (' + (e.reason || '') + ') : ' + (e.message || '');
  if (e.type === 'ATTN') return (e.target || '—') + ' : ' + (e.content_snippet || '');
  if (e.type === 'DECIDE') return (e.actions || []).join(' · ');
  if (e.type === 'ACT') return e.detail || '';
  if (e.type === 'EVOLVE') return 'persona → ' + (e.detail || '');
  return e.detail || e.text || e.message || '';
}
// Texte complet (dépliage) si présent et différent du snippet rendu.
function feedFull(e) {
  const full = e.full;
  return (full && full !== (e.detail || '') && full !== feedText(e)) ? full : null;
}
function feedSig(e) {
  return (e.type || '') + '|' + (e.text || e.detail || e.message || e.content_snippet || '');
}

function statCard(label, value, color) {
  const c = document.createElement('div');
  c.className = 'arc-card';
  const l = document.createElement('div');
  l.className = 'arc-stat-label';
  l.style.color = color;
  l.textContent = label;
  const v = document.createElement('div');
  v.className = 'arc-stat-value';
  v.textContent = value;
  c.appendChild(l); c.appendChild(v);
  return c;
}

function buildEmoRow(name, value) {
  const row = document.createElement('div');
  row.className = 'emo-row';
  const label = document.createElement('div');
  label.className = 'emo-label';
  label.style.color = EMO_COLORS[name];
  label.textContent = EMO_LABELS[name];
  row.appendChild(label);
  const track = document.createElement('div');
  track.className = 'emo-track';
  const on = Math.round((value || 0) * 10);
  for (let i = 0; i < 10; i++) {
    const cell = document.createElement('span');
    cell.className = 'emo-cell' + (i < on ? ' on' : '');
    if (i < on) cell.style.background = EMO_COLORS[name];
    track.appendChild(cell);
  }
  row.appendChild(track);
  return row;
}

function renderEmoBars(target) {
  target.textContent = '';
  // N'afficher que les 5 émotions primaires — le flux SSE ajoute aussi
  // mood/fatigue/secondaries dans `emotions`, qui créeraient des barres vides.
  Object.keys(EMO_LABELS).forEach((name) => target.appendChild(buildEmoRow(name, emotions[name])));
}

function renderFeed(listEl) {
  // Auto-scroll : coller au bas si l'utilisateur n'a pas remonté, ou si c'est
  // le premier rendu (scrollTop=0 → pas encore scrollé = on veut voir le bas).
  // Capture AVANT le clear car textContent='' remet scrollTop à 0.
  const savedScrollTop = listEl.scrollTop;
  const atBottom = !savedScrollTop || listEl.scrollHeight - savedScrollTop - listEl.clientHeight < 40;
  listEl.textContent = '';
  if (!_feedEvents.length) {
    const empty = document.createElement('div');
    empty.className = 'feed-text';
    empty.style.color = 'var(--muted)';
    empty.textContent = 'en attente de pensées…';
    listEl.appendChild(empty);
    return;
  }
  // Plus ancien en haut, plus récent en bas (style terminal). On affiche tout
  // l'historique chargé (capé à 200 lignes pour la perf), pas seulement 12.
  _feedEvents.slice(0, 200).reverse().forEach((e) => {
    const meta = feedMeta(e.type);
    const row = document.createElement('div');
    row.className = 'feed-row';
    const t = document.createElement('span');
    t.className = 'feed-time';
    t.textContent = e._t || '';
    const tag = document.createElement('span');
    tag.className = 'feed-tag';
    tag.style.color = meta.color;
    tag.textContent = meta.icon + ' ' + meta.label;
    const txt = document.createElement('span');
    txt.className = 'feed-text';
    const full = feedFull(e);
    txt.textContent = (e._expanded && full) ? full : feedText(e);
    if (full) {
      row.style.cursor = 'pointer';
      row.title = 'cliquer pour ' + (e._expanded ? 'replier' : 'déplier');
      if (!e._expanded) txt.textContent += ' …';
      row.addEventListener('click', () => { e._expanded = !e._expanded; renderFeed(listEl); });
    }
    row.appendChild(t); row.appendChild(tag); row.appendChild(txt);
    listEl.appendChild(row);
  });
  if (atBottom) listEl.scrollTop = listEl.scrollHeight;
  else listEl.scrollTop = savedScrollTop;
}

function pushFeedEvent(e) {
  // Dédup : le SSE rejoue le buffer récent au branchement, qui recoupe
  // l'historique déjà chargé → on ignore un event identique aux 40 plus récents.
  const sig = feedSig(e);
  for (let i = 0; i < Math.min(_feedEvents.length, 40); i++) {
    if (feedSig(_feedEvents[i]) === sig) return;
  }
  const d = new Date();
  e._t = d.toLocaleTimeString('fr-FR');
  _feedEvents.unshift(e);
  if (_feedEvents.length > 300) _feedEvents.length = 300;
  const listEl = document.getElementById('cog-feed-list');
  if (listEl) renderFeed(listEl);
}

function drawHistoryChart(canvas, history) {
  if (!history || history.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth || 600;
  const H = canvas.clientHeight || 140;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const PAD = { top: 12, right: 12, bottom: 24, left: 8 };
  const cW = W - PAD.left - PAD.right, cH = H - PAD.top - PAD.bottom;
  const emos = ['anger', 'joy', 'curiosity', 'sadness', 'boredom'];
  const n = history.length;
  const tMin = history[0].snapshot_at, tMax = history[n - 1].snapshot_at;
  const xOf = (i) => PAD.left + (i / (n - 1)) * cW;
  const yOf = (v) => PAD.top + cH - v * cH;
  ctx.strokeStyle = 'rgba(124,77,255,0.12)'; ctx.lineWidth = 1;
  for (let v = 0; v <= 1; v += 0.25) { ctx.beginPath(); ctx.moveTo(PAD.left, yOf(v)); ctx.lineTo(PAD.left + cW, yOf(v)); ctx.stroke(); }
  emos.forEach((emo) => {
    ctx.beginPath(); ctx.lineWidth = 1.5; ctx.strokeStyle = EMO_COLORS[emo]; ctx.globalAlpha = 0.85;
    history.forEach((snap, i) => { const x = xOf(i), y = yOf(snap[emo] || 0); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
  ctx.fillStyle = 'rgba(255,232,194,0.4)'; ctx.font = '12px VT323, monospace'; ctx.textAlign = 'center';
  [tMin, (tMin + tMax) / 2, tMax].forEach((t) => {
    const x = PAD.left + ((t - tMin) / (tMax - tMin)) * cW;
    const d = new Date(t * 1000);
    ctx.fillText(d.getHours() + 'h' + String(d.getMinutes()).padStart(2, '0'), x, H - 4);
  });
}

async function fetchHistory() {
  try {
    const r = await fetch('/api/public/emotions/history?since=' + Math.floor(Date.now() / 1000 - 86400));
    const data = await r.json();
    _historyData = (data.history || []).filter((s) => s.snapshot_at);
    const canvas = document.getElementById('status-emo-history-canvas');
    if (canvas && _historyData.length >= 2) drawHistoryChart(canvas, _historyData);
  } catch (_) {}
}

function _goalSection(title, items, emptyMsg) {
  const wrap = document.createElement('div');
  wrap.style.marginBottom = '14px';
  const h = document.createElement('div');
  h.className = 'arc-stat-label';
  h.style.cssText = 'font-size:11px;color:var(--yellow);margin-bottom:6px;';
  h.textContent = title;
  wrap.appendChild(h);
  if (!items || !items.length) {
    const e = document.createElement('div');
    e.className = 'feed-text';
    e.style.color = 'var(--muted)';
    e.textContent = emptyMsg;
    wrap.appendChild(e);
  } else {
    items.forEach((it) => {
      const d = document.createElement('div');
      d.className = 'feed-text';
      d.style.marginBottom = '4px';
      d.textContent = '• ' + it;
      wrap.appendChild(d);
    });
  }
  return wrap;
}

async function openGoalModal() {
  let data = { goals: [], preoccupation: null, desires: [] };
  try { data = await (await fetch('/api/public/cognitive/goal')).json(); } catch (_) {}

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(10,4,26,0.82);z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px;';
  const card = document.createElement('div');
  card.className = 'arc-card';
  card.style.cssText = 'max-width:520px;width:100%;max-height:80vh;overflow-y:auto;';
  const head = document.createElement('div');
  head.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;';
  const title = document.createElement('div');
  title.className = 'arc-stat-label';
  title.style.cssText = 'font-size:13px;color:var(--cyan);';
  title.textContent = '🎯 DANS LA TÊTE DE WALLY';
  const close = document.createElement('span');
  close.style.cssText = 'cursor:pointer;font-size:22px;color:var(--pink);';
  close.textContent = '✕';
  head.appendChild(title); head.appendChild(close);
  card.appendChild(head);
  card.appendChild(_goalSection('SON BUT', data.goals, 'il vagabonde, aucun but fixé.'));
  card.appendChild(_goalSection('SA PRÉOCCUPATION', data.preoccupation ? [data.preoccupation] : [], 'rien ne le préoccupe là.'));
  card.appendChild(_goalSection('CE QUI LE TRAVAILLE', data.desires, 'aucun désir actif.'));
  overlay.appendChild(card);

  const remove = () => { overlay.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') remove(); };
  overlay.addEventListener('click', (e) => { if (e.target === overlay) remove(); });
  close.addEventListener('click', remove);
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
}

function svcPill(label, on, warn) {
  const s = document.createElement('span');
  s.className = 'arc-pill' + (on ? '' : (warn ? ' warn' : ' off'));
  const dot = document.createElement('span');
  dot.textContent = '●';
  dot.style.color = on ? 'var(--green)' : (warn ? 'var(--yellow)' : 'var(--pink)');
  s.appendChild(dot);
  s.appendChild(document.createTextNode(' ' + label));
  return s;
}

function renderStatus(el, status, stream) {
  el.textContent = '';

  const head = document.createElement('div');
  const eyebrow = document.createElement('div');
  eyebrow.className = 'arc-eyebrow';
  eyebrow.textContent = 'PANNEAU DE CONTRÔLE · WALLY';
  const h2 = document.createElement('h2');
  h2.className = 'arc-h2';
  h2.textContent = 'STATUT';
  const sub = document.createElement('div');
  sub.className = 'arc-sub';
  sub.textContent = "bonjour. wally tourne, tout va bien. (pour l'instant.)";
  head.appendChild(eyebrow); head.appendChild(h2); head.appendChild(sub);
  el.appendChild(head);

  const stats = document.createElement('div');
  stats.className = 'arc-grid';
  stats.style.gridTemplateColumns = 'repeat(auto-fit,minmax(180px,1fr))';
  const rt = status.avg_response_ms;
  const rtTxt = (rt === null || rt === undefined) ? '—' : (rt / 1000).toFixed(1) + 's';
  const viewers = stream && stream.live ? (stream.viewers || stream.viewer_count || 0).toLocaleString('fr') : '—';
  stats.appendChild(statCard('MESSAGES TRAITÉS', (status.total_messages || 0).toLocaleString('fr'), 'var(--cyan)'));
  stats.appendChild(statCard('VIEWERS (LIVE)', viewers, 'var(--pink)'));
  stats.appendChild(statCard('TEMPS DE RÉPONSE', rtTxt, 'var(--yellow)'));
  stats.appendChild(statCard('UPTIME', formatUptime(status.uptime_seconds), 'var(--green)'));
  el.appendChild(stats);

  // ACTIVITÉ EN DIRECT — pleine largeur
  const feedCard = document.createElement('div');
  feedCard.className = 'arc-card';
  feedCard.style.marginTop = '18px';
  const feedHead = document.createElement('div');
  feedHead.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;';
  const feedTitle = document.createElement('div');
  feedTitle.className = 'arc-stat-label';
  feedTitle.style.cssText = 'font-size:11px;color:var(--yellow);';
  feedTitle.textContent = 'ACTIVITÉ EN DIRECT';
  const headRight = document.createElement('div');
  headRight.style.cssText = 'display:flex;align-items:center;gap:14px;';
  const goalBtn = document.createElement('button');
  goalBtn.className = 'arc-pill';
  goalBtn.style.cssText = 'cursor:pointer;font-family:inherit;';
  goalBtn.textContent = '🎯 son but';
  goalBtn.addEventListener('click', openGoalModal);
  const live = document.createElement('span');
  live.style.cssText = 'font-size:20px;color:var(--green);';
  live.textContent = '● live';
  headRight.appendChild(goalBtn); headRight.appendChild(live);
  feedHead.appendChild(feedTitle); feedHead.appendChild(headRight);
  feedCard.appendChild(feedHead);
  const feedList = document.createElement('div');
  feedList.id = 'cog-feed-list';
  feedList.style.cssText = 'height:340px;max-height:340px;overflow-y:auto;';
  feedList.addEventListener('scroll', onFeedScroll);   // scroll-up → historique
  feedCard.appendChild(feedList);
  el.appendChild(feedCard);
  renderFeed(feedList);

  // PERSONNALITÉ + SERVICES — même ligne
  const cols = document.createElement('div');
  cols.className = 'arc-grid';
  cols.style.cssText = 'grid-template-columns:repeat(auto-fit,minmax(300px,1fr));margin-top:18px;align-items:start;';

  const emoCard = document.createElement('div');
  emoCard.className = 'arc-card';
  const emoTitle = document.createElement('div');
  emoTitle.className = 'arc-stat-label';
  emoTitle.style.cssText = 'font-size:11px;color:var(--yellow);margin-bottom:16px;';
  emoTitle.textContent = 'PERSONNALITÉ';
  emoCard.appendChild(emoTitle);
  const bars = document.createElement('div');
  bars.id = 'status-emo-bars';
  renderEmoBars(bars);
  emoCard.appendChild(bars);
  cols.appendChild(emoCard);

  const svcCard = document.createElement('div');
  svcCard.className = 'arc-card';
  const svcTitle = document.createElement('div');
  svcTitle.className = 'arc-stat-label';
  svcTitle.style.cssText = 'font-size:11px;color:var(--yellow);margin-bottom:14px;';
  svcTitle.textContent = 'SERVICES';
  svcCard.appendChild(svcTitle);
  const svcWrap = document.createElement('div');
  svcWrap.style.cssText = 'display:flex;flex-wrap:wrap;gap:10px;';
  svcWrap.appendChild(svcPill('DeepSeek', true));
  svcWrap.appendChild(svcPill('Discord', !!status.discord_online, true));
  svcWrap.appendChild(svcPill('Twitch', !!status.twitch_online, true));
  svcWrap.appendChild(svcPill('Mémoire FTS5', true));
  svcCard.appendChild(svcWrap);
  cols.appendChild(svcCard);

  el.appendChild(cols);

  const histCard = document.createElement('div');
  histCard.className = 'arc-card';
  histCard.style.marginTop = '18px';
  const histTitle = document.createElement('div');
  histTitle.className = 'arc-stat-label';
  histTitle.style.cssText = 'font-size:11px;color:var(--yellow);';
  histTitle.textContent = 'HISTORIQUE DES ÉMOTIONS — 24H';
  histCard.appendChild(histTitle);
  const canvas = document.createElement('canvas');
  canvas.id = 'status-emo-history-canvas';
  canvas.style.cssText = 'width:100%;height:140px;display:block;margin-top:10px;';
  histCard.appendChild(canvas);
  el.appendChild(histCard);

  if (_historyData && _historyData.length >= 2) setTimeout(() => drawHistoryChart(canvas, _historyData), 0);
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => { if (_historyData && _historyData.length >= 2) drawHistoryChart(canvas, _historyData); });
    ro.observe(canvas);
  }
}

async function fetchAndRender() {
  if (!_container) return;
  // Capture scroll state before DOM rebuild (renderStatus wipes el.textContent).
  const prevList = document.getElementById('cog-feed-list');
  const wasAtBottom = !prevList
    || !prevList.scrollTop
    || prevList.scrollHeight - prevList.scrollTop - prevList.clientHeight < 40;
  const prevScroll = prevList ? prevList.scrollTop : 0;

  const [statusRes, streamRes] = await Promise.all([
    fetch('/api/public/status').then((r) => r.json()).catch(() => ({})),
    fetch('/api/public/twitch/stream').then((r) => r.json()).catch(() => null),
  ]);
  renderStatus(_container, statusRes, streamRes);

  // Restore scroll after layout (new element is in DOM only after renderStatus returns).
  requestAnimationFrame(() => {
    const listEl = document.getElementById('cog-feed-list');
    if (!listEl) return;
    listEl.scrollTop = wasAtBottom ? listEl.scrollHeight : prevScroll;
  });
}

async function seedFeed() {
  // Amorce avec l'historique PERSISTANT (avec id → pagination scroll-up + full),
  // du plus récent au plus ancien. Le SSE live prend ensuite le relais.
  try {
    const data = await (await fetch('/api/public/cognitive/history?limit=40')).json();
    const evts = (data.events || []);   // déjà décroissants (récent → ancien)
    _feedEvents = evts.map((e) => ({ ...e, _t: e.ts ? new Date(e.ts * 1000).toLocaleTimeString('fr-FR') : '' }));
    _historyBefore = (data.next_before !== undefined) ? data.next_before : null;
    const listEl = document.getElementById('cog-feed-list');
    if (listEl) renderFeed(listEl);
  } catch (_) {}
}

async function loadMoreHistory(listEl) {
  if (_loadingMore || _historyBefore === null || _historyBefore === undefined) return;
  _loadingMore = true;
  try {
    const data = await (await fetch('/api/public/cognitive/history?limit=40&before=' + _historyBefore)).json();
    const evts = (data.events || []);
    if (evts.length) {
      const prevH = listEl.scrollHeight;
      // events décroissants → les plus anciens vont en queue de _feedEvents.
      evts.forEach((e) => _feedEvents.push({ ...e, _t: e.ts ? new Date(e.ts * 1000).toLocaleTimeString('fr-FR') : '' }));
      _historyBefore = (data.next_before !== undefined) ? data.next_before : null;
      renderFeed(listEl);
      // Compense l'ajout en haut pour ne pas faire sauter la vue.
      listEl.scrollTop += (listEl.scrollHeight - prevH);
    } else {
      _historyBefore = null;
    }
  } catch (_) {} finally { _loadingMore = false; }
}

function onFeedScroll(ev) {
  const listEl = ev.currentTarget;
  if (listEl.scrollTop < 40) loadMoreHistory(listEl);
}

export function mount(el) {
  clearInterval(_pollInterval);
  clearInterval(_historyInterval);
  _container = el;
  _feedEvents = [];
  _historyBefore = null;
  _loadingMore = false;

  fetchAndRender();
  fetchHistory();
  seedFeed();
  _cognitiveES = connectCognitiveSSE(pushFeedEvent);

  _pollInterval = setInterval(fetchAndRender, 30000);
  _historyInterval = setInterval(fetchHistory, 300000);

  _unsubEmo = onEmotionUpdate(() => {
    const barsEl = document.getElementById('status-emo-bars');
    if (barsEl) renderEmoBars(barsEl);
  });
}

export function unmount() {
  clearInterval(_pollInterval);
  clearInterval(_historyInterval);
  _pollInterval = null;
  _historyInterval = null;
  _historyData = null;
  _container = null;
  _feedEvents = [];
  if (_unsubEmo) { _unsubEmo(); _unsubEmo = null; }
  if (_cognitiveES) { _cognitiveES.close(); _cognitiveES = null; }
}
