// public-ui/tabs/status.js — arcade
import { emotions, onEmotionUpdate, connectCognitiveSSE } from '../app.js';

let _pollInterval    = null;
let _historyInterval = null;
let _historyData     = null;
let _container       = null;
let _unsubEmo        = null;
let _cognitiveES     = null;
let _feedEvents      = [];

const EMO_COLORS = {
  anger: '#ef4444', joy: '#eab308', curiosity: '#22c55e',
  sadness: '#3b82f6', boredom: '#a855f7'
};
const EMO_LABELS = {
  anger: 'COLÈRE', joy: 'JOIE', curiosity: 'CURIOSITÉ',
  sadness: 'TRISTESSE', boredom: 'ENNUI'
};
const TAGC = {
  THINK: '#ffd400', SPEAK: '#43e0ff', ACT: '#7CFC52',
  DECIDE: '#bf94ff', ATTN: '#ff3b6b', EVOLVE: '#ff8a3b', SLEEP: '#6f6597'
};

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
  if (e.type === 'SPEAK') return '→ ' + (e.detail || '');
  if (e.type === 'ATTN') return (e.target || '—') + ' : ' + (e.content_snippet || '');
  if (e.type === 'DECIDE') return (e.actions || []).join(' · ');
  if (e.type === 'ACT') return e.detail || '';
  if (e.type === 'EVOLVE') return 'persona → ' + (e.detail || '');
  return e.detail || e.text || '';
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
  Object.entries(emotions).forEach(([name, value]) => target.appendChild(buildEmoRow(name, value)));
}

function renderFeed(listEl) {
  listEl.textContent = '';
  if (!_feedEvents.length) {
    const empty = document.createElement('div');
    empty.className = 'feed-text';
    empty.style.color = 'var(--muted)';
    empty.textContent = 'en attente de pensées…';
    listEl.appendChild(empty);
    return;
  }
  _feedEvents.slice(0, 12).forEach((e) => {
    const row = document.createElement('div');
    row.className = 'feed-row';
    const t = document.createElement('span');
    t.className = 'feed-time';
    t.textContent = e._t || '';
    const tag = document.createElement('span');
    tag.className = 'feed-tag';
    tag.style.color = TAGC[e.type] || '#fff';
    tag.textContent = e.type;
    const txt = document.createElement('span');
    txt.className = 'feed-text';
    txt.textContent = feedText(e);
    row.appendChild(t); row.appendChild(tag); row.appendChild(txt);
    listEl.appendChild(row);
  });
}

function pushFeedEvent(e) {
  const d = new Date();
  e._t = d.toLocaleTimeString('fr-FR');
  _feedEvents.unshift(e);
  if (_feedEvents.length > 30) _feedEvents.pop();
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

  const cols = document.createElement('div');
  cols.className = 'arc-grid';
  cols.style.cssText = 'grid-template-columns:repeat(auto-fit,minmax(300px,1fr));margin-top:18px;';

  const feedCard = document.createElement('div');
  feedCard.className = 'arc-card';
  const feedHead = document.createElement('div');
  feedHead.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;';
  const feedTitle = document.createElement('div');
  feedTitle.className = 'arc-stat-label';
  feedTitle.style.cssText = 'font-size:11px;color:var(--yellow);';
  feedTitle.textContent = 'ACTIVITÉ EN DIRECT';
  const live = document.createElement('span');
  live.style.cssText = 'font-size:20px;color:var(--green);';
  live.textContent = '● live';
  feedHead.appendChild(feedTitle); feedHead.appendChild(live);
  feedCard.appendChild(feedHead);
  const feedList = document.createElement('div');
  feedList.id = 'cog-feed-list';
  feedCard.appendChild(feedList);
  cols.appendChild(feedCard);
  renderFeed(feedList);

  const right = document.createElement('div');
  right.style.cssText = 'display:flex;flex-direction:column;gap:18px;';

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
  svcWrap.appendChild(svcPill('Qdrant', true));
  svcWrap.appendChild(svcPill('Neo4j', true));
  svcCard.appendChild(svcWrap);
  right.appendChild(svcCard);

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
  right.appendChild(emoCard);

  cols.appendChild(right);
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
  const [statusRes, streamRes] = await Promise.all([
    fetch('/api/public/status').then((r) => r.json()).catch(() => ({})),
    fetch('/api/public/twitch/stream').then((r) => r.json()).catch(() => null),
  ]);
  renderStatus(_container, statusRes, streamRes);
}

async function seedFeed() {
  try {
    const data = await (await fetch('/api/public/cognitive/state')).json();
    const evts = (data.events || []).slice(-12).reverse();
    _feedEvents = evts.map((e) => ({ ...e, _t: '' }));
    const listEl = document.getElementById('cog-feed-list');
    if (listEl) renderFeed(listEl);
  } catch (_) {}
}

export function mount(el) {
  clearInterval(_pollInterval);
  clearInterval(_historyInterval);
  _container = el;
  _feedEvents = [];

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
