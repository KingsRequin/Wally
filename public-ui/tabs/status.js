// public-ui/tabs/status.js
import { emotions, onEmotionUpdate } from '../app.js';

let _pollInterval = null;
let _container = null;
let _unsubEmo = null;

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

function renderStatus(el, status, stream) {
  el.textContent = '';

  const grid = document.createElement('div');
  grid.className = 'status-grid';

  // Card: Connexions
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

  // Card: Messages
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

  // Card: Humeur
  const cardEmo = document.createElement('div');
  cardEmo.className = 'card';
  cardEmo.style.gridColumn = 'span 2';
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

  // Card: Stream
  if (stream) {
    const cardStream = document.createElement('div');
    cardStream.className = 'card';
    const streamLabel = document.createElement('div');
    streamLabel.className = 'card-label';
    streamLabel.textContent = 'Stream Azrael';
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

      const game = document.createElement('div');
      game.className = 'card-sub';
      game.textContent = stream.game || '';
      cardStream.appendChild(game);

      const title = document.createElement('div');
      title.style.cssText = 'font-size:0.78rem;color:rgba(255,255,255,0.5);margin-top:4px;';
      title.textContent = stream.title || '';
      cardStream.appendChild(title);

      const viewers = document.createElement('div');
      viewers.className = 'card-value';
      viewers.style.marginTop = '8px';
      viewers.textContent = (stream.viewer_count || 0).toLocaleString('fr');
      const viewersSub = document.createElement('span');
      viewersSub.style.cssText = 'font-size:0.7rem;font-weight:400;color:rgba(255,255,255,0.4);margin-left:6px;';
      viewersSub.textContent = 'spectateurs';
      viewers.appendChild(viewersSub);
      cardStream.appendChild(viewers);
    } else {
      const offline = document.createElement('div');
      offline.className = 'card-sub';
      offline.textContent = 'Hors ligne';
      cardStream.appendChild(offline);
    }
    grid.appendChild(cardStream);
  }

  el.appendChild(grid);
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
  _container = el;
  fetchAndRender();
  _pollInterval = setInterval(fetchAndRender, 30000);

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
  _pollInterval = null;
  _container = null;
  if (_unsubEmo) { _unsubEmo(); _unsubEmo = null; }
}
