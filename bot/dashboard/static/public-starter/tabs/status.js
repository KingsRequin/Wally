// public-ui/tabs/status.js
import { emotions, onEmotionUpdate } from '../app.js';

let _pollInterval   = null;
let _historyInterval = null;
let _historyData    = null;   // cache — ne refetch pas à chaque render
let _container      = null;
let _unsubEmo       = null;

const EMO_COLORS = {
  anger: '#ef4444', joy: '#eab308', curiosity: '#22c55e',
  sadness: '#3b82f6', boredom: '#a855f7'
};
const EMO_LABELS = {
  anger: 'Colère', joy: 'Joie', curiosity: 'Curiosité',
  sadness: 'Tristesse', boredom: 'Ennui'
};

function formatUptime(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function dominant(emo) {
  return Object.entries(emo).sort((a, b) => b[1] - a[1])[0][0];
}

function buildEmoBar(name, value) {
  const row = document.createElement('div');
  row.className = 'emo-row';
  const label = document.createElement('span');
  label.className = 'emo-name';
  label.textContent = EMO_LABELS[name];
  row.appendChild(label);
  const track = document.createElement('div');
  track.className = 'emo-track';
  const fill = document.createElement('div');
  fill.className = 'emo-fill';
  fill.style.width = (value * 100).toFixed(1) + '%';
  fill.style.background = EMO_COLORS[name];
  track.appendChild(fill);
  row.appendChild(track);
  const pct = document.createElement('span');
  pct.className = 'emo-pct';
  pct.textContent = Math.round(value * 100) + '%';
  row.appendChild(pct);
  return { row, fill, pct };
}

// ── Sparkline chart ──
function drawHistoryChart(canvas, history) {
  if (!history || history.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth || 600;
  const H = canvas.clientHeight || 120;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const PAD = { top: 12, right: 12, bottom: 24, left: 8 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top - PAD.bottom;
  const emos = ['anger', 'joy', 'curiosity', 'sadness', 'boredom'];
  const n = history.length;
  const tMin = history[0].snapshot_at;
  const tMax = history[n - 1].snapshot_at;

  function xOf(i) { return PAD.left + (i / (n - 1)) * cW; }
  function yOf(v) { return PAD.top + cH - v * cH; }

  // Grid lines
  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 1;
  for (let v = 0; v <= 1; v += 0.25) {
    ctx.beginPath();
    ctx.moveTo(PAD.left, yOf(v));
    ctx.lineTo(PAD.left + cW, yOf(v));
    ctx.stroke();
  }

  // Emotion lines
  emos.forEach(emo => {
    ctx.beginPath();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = EMO_COLORS[emo];
    ctx.globalAlpha = 0.85;
    history.forEach((snap, i) => {
      const x = xOf(i);
      const y = yOf(snap[emo] || 0);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
  ctx.globalAlpha = 1;

  // Time labels
  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.font = '10px Inter, sans-serif';
  ctx.textAlign = 'center';
  [tMin, (tMin + tMax) / 2, tMax].forEach(t => {
    const x = PAD.left + ((t - tMin) / (tMax - tMin)) * cW;
    const d = new Date(t * 1000);
    ctx.fillText(d.getHours() + 'h' + String(d.getMinutes()).padStart(2, '0'), x, H - 4);
  });
}

// ── Fetch history (séparé du poll status) ──
async function fetchHistory() {
  try {
    const r = await fetch('/api/public/emotions/history?since=' + Math.floor(Date.now() / 1000 - 86400));
    const data = await r.json();
    _historyData = (data.history || []).filter(s => s.snapshot_at);
    const canvas = document.getElementById('status-emo-history-canvas');
    if (canvas && _historyData.length >= 2) drawHistoryChart(canvas, _historyData);
  } catch (_) {}
}

function renderStatus(el, status, stream) {
  el.textContent = '';

  const grid = document.createElement('div');
  grid.className = 'status-grid';

  // ── Card: Connexions ──
  const cardConn = document.createElement('div');
  cardConn.className = 'card';
  const connLabel = document.createElement('div');
  connLabel.className = 'card-label';
  connLabel.textContent = 'Connexions';
  cardConn.appendChild(connLabel);

  const discordLine = document.createElement('div');
  discordLine.style.marginBottom = '6px';
  const discordDot = document.createElement('span');
  discordDot.className = 'dot ' + (status.discord_online ? 'dot-on' : 'dot-off');
  discordLine.appendChild(discordDot);
  discordLine.appendChild(document.createTextNode('Discord'));
  cardConn.appendChild(discordLine);

  const twitchLine = document.createElement('div');
  const twitchDot = document.createElement('span');
  twitchDot.className = 'dot ' + (status.twitch_online ? 'dot-on' : 'dot-off');
  twitchLine.appendChild(twitchDot);
  twitchLine.appendChild(document.createTextNode('Twitch'));
  cardConn.appendChild(twitchLine);

  const uptimeLine = document.createElement('div');
  uptimeLine.className = 'card-sub';
  uptimeLine.style.marginTop = '10px';
  uptimeLine.textContent = 'Uptime : ' + formatUptime(status.uptime_seconds);
  cardConn.appendChild(uptimeLine);

  grid.appendChild(cardConn);

  // ── Card: Messages ──
  const cardMsg = document.createElement('div');
  cardMsg.className = 'card';
  const msgLabel = document.createElement('div');
  msgLabel.className = 'card-label';
  msgLabel.textContent = 'Messages traités';
  cardMsg.appendChild(msgLabel);
  const msgVal = document.createElement('div');
  msgVal.className = 'card-value';
  msgVal.textContent = (status.total_messages || 0).toLocaleString('fr');
  cardMsg.appendChild(msgVal);
  const msgSub = document.createElement('div');
  msgSub.className = 'card-sub';
  msgSub.textContent = 'Discord : ' + (status.messages_discord || 0) + ' · Twitch : ' + (status.messages_twitch || 0) + ' · Web : ' + (status.messages_web || 0);
  cardMsg.appendChild(msgSub);
  grid.appendChild(cardMsg);

  // ── Card: Humeur (full width) ──
  const cardEmo = document.createElement('div');
  cardEmo.className = 'card status-card-fullwidth';
  const emoLabel = document.createElement('div');
  emoLabel.className = 'card-label';
  emoLabel.textContent = 'Humeur en direct';
  cardEmo.appendChild(emoLabel);

  const domEmo = document.createElement('div');
  domEmo.style.cssText = 'font-size:0.85rem;font-weight:600;margin-bottom:12px;';
  const domName = dominant(emotions);
  domEmo.style.color = EMO_COLORS[domName];
  domEmo.textContent = EMO_LABELS[domName];
  cardEmo.appendChild(domEmo);

  const bars = document.createElement('div');
  bars.className = 'emo-bars';
  bars.id = 'status-emo-bars';
  Object.entries(emotions).forEach(([name, value]) => {
    const { row } = buildEmoBar(name, value);
    bars.appendChild(row);
  });
  cardEmo.appendChild(bars);
  grid.appendChild(cardEmo);

  // ── Card: Stream ──
  if (stream) {
    const cardStream = document.createElement('div');
    cardStream.className = 'card';

    const streamLabel = document.createElement('div');
    streamLabel.className = 'card-label';
    streamLabel.textContent = 'Stream';
    cardStream.appendChild(streamLabel);

    if (stream.live) {
      const liveDot = document.createElement('div');
      liveDot.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px;';
      const dot = document.createElement('span');
      dot.className = 'dot dot-on';
      liveDot.appendChild(dot);
      const liveText = document.createElement('span');
      liveText.style.cssText = 'font-size:0.78rem;font-weight:600;color:#22c55e;';
      liveText.textContent = 'En direct';
      liveDot.appendChild(liveText);
      cardStream.appendChild(liveDot);

      if (stream.category || stream.game) {
        const game = document.createElement('div');
        game.className = 'card-sub';
        game.textContent = stream.category || stream.game;
        cardStream.appendChild(game);
      }

      if (stream.title) {
        const title = document.createElement('div');
        title.style.cssText = 'font-size:0.78rem;color:rgba(255,255,255,0.5);margin-top:4px;line-height:1.4;';
        title.textContent = stream.title;
        cardStream.appendChild(title);
      }

      const viewers = document.createElement('div');
      viewers.className = 'card-value';
      viewers.style.marginTop = '8px';
      viewers.textContent = (stream.viewers || stream.viewer_count || 0).toLocaleString('fr');
      const viewersSub = document.createElement('span');
      viewersSub.style.cssText = 'font-size:0.7rem;font-weight:400;color:rgba(255,255,255,0.4);margin-left:6px;';
      viewersSub.textContent = 'spectateurs';
      viewers.appendChild(viewersSub);
      cardStream.appendChild(viewers);

      if (stream.started_at) {
        const dur = Math.floor((Date.now() / 1000) - stream.started_at);
        const durLine = document.createElement('div');
        durLine.className = 'card-sub';
        durLine.style.marginTop = '4px';
        durLine.textContent = 'En live depuis ' + formatUptime(dur);
        cardStream.appendChild(durLine);
      }
    } else {
      const offline = document.createElement('div');
      offline.className = 'card-sub';
      offline.textContent = 'Hors ligne';
      cardStream.appendChild(offline);
    }

    const channelLogin = status.twitch_channel || '';
    if (channelLogin) {
      const btn = document.createElement('a');
      btn.href = 'https://twitch.tv/' + channelLogin;
      btn.target = '_blank';
      btn.rel = 'noopener noreferrer';
      btn.className = 'stream-link-btn';
      const sv = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      sv.setAttribute('width', '14'); sv.setAttribute('height', '14');
      sv.setAttribute('viewBox', '0 0 24 24'); sv.setAttribute('fill', 'currentColor');
      const sp = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      sp.setAttribute('d', 'M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z');
      sv.appendChild(sp);
      btn.appendChild(sv);
      btn.appendChild(document.createTextNode('Voir la chaîne'));
      cardStream.appendChild(btn);
    }

    grid.appendChild(cardStream);
  }

  el.appendChild(grid);

  // ── Card: Historique des émotions ──
  const cardHist = document.createElement('div');
  cardHist.className = 'card status-card-fullwidth';
  cardHist.style.marginTop = '0';
  const histLabel = document.createElement('div');
  histLabel.className = 'card-label';
  histLabel.textContent = 'Historique des émotions — 24h';
  cardHist.appendChild(histLabel);

  const canvas = document.createElement('canvas');
  canvas.id = 'status-emo-history-canvas';
  canvas.style.cssText = 'width:100%;height:140px;display:block;';
  cardHist.appendChild(canvas);

  // Légende HTML (pas sur le canvas)
  const legRow = document.createElement('div');
  legRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:12px;margin-top:10px;';
  ['anger', 'joy', 'curiosity', 'sadness', 'boredom'].forEach(emo => {
    const item = document.createElement('div');
    item.style.cssText = 'display:flex;align-items:center;gap:5px;font-size:0.7rem;color:rgba(255,255,255,0.55);';
    const swatch = document.createElement('span');
    swatch.style.cssText = `display:inline-block;width:20px;height:2px;background:${EMO_COLORS[emo]};border-radius:2px;`;
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(EMO_LABELS[emo]));
    legRow.appendChild(item);
  });
  cardHist.appendChild(legRow);
  grid.appendChild(cardHist);

  // Dessin immédiat depuis le cache si disponible
  if (_historyData && _historyData.length >= 2) {
    setTimeout(() => drawHistoryChart(canvas, _historyData), 0);
  }

  // Redimensionnement automatique
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => {
      if (_historyData && _historyData.length >= 2) drawHistoryChart(canvas, _historyData);
    });
    ro.observe(canvas);
  }
}

async function fetchAndRender() {
  if (!_container) return;
  const [statusRes, streamRes] = await Promise.all([
    fetch('/api/public/status').then(r => r.json()).catch(() => ({})),
    fetch('/api/public/twitch/stream').then(r => r.json()).catch(() => null),
  ]);
  renderStatus(_container, statusRes, streamRes);
}

export function mount(el) {
  clearInterval(_pollInterval);
  clearInterval(_historyInterval);
  _container = el;

  fetchAndRender();
  fetchHistory();

  _pollInterval    = setInterval(fetchAndRender, 30000);
  _historyInterval = setInterval(fetchHistory, 300000); // toutes les 5 min

  _unsubEmo = onEmotionUpdate((emo) => {
    const barsEl = document.getElementById('status-emo-bars');
    if (!barsEl) return;
    barsEl.textContent = '';
    Object.entries(emo).forEach(([name, value]) => {
      const { row } = buildEmoBar(name, value);
      barsEl.appendChild(row);
    });
  });
}

export function unmount() {
  clearInterval(_pollInterval);
  clearInterval(_historyInterval);
  _pollInterval    = null;
  _historyInterval = null;
  _historyData     = null;
  _container       = null;
  if (_unsubEmo) { _unsubEmo(); _unsubEmo = null; }
}
