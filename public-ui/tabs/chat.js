// public-ui/tabs/chat.js
import { emotions, onEmotionUpdate } from '../app.js';

let _ws = null;
let _container = null;
let _unsubEmo = null;

const EMO_COLORS = { anger:'#ef4444', joy:'#eab308', curiosity:'#22c55e', sadness:'#3b82f6', boredom:'#a855f7' };
const EMO_LABELS = { anger:'Colère', joy:'Joie', curiosity:'Curiosité', sadness:'Tristesse', boredom:'Ennui' };

function getAvatarUrl(emo) {
  const order = ['anger','joy','curiosity','sadness','boredom'];
  let domEmo = 'curiosity', domVal = 0;
  for (const name of order) {
    if ((emo[name] || 0) > domVal) { domVal = emo[name]; domEmo = name; }
  }
  if (domVal < 0.2) domEmo = 'curiosity';
  const tier = domVal >= 0.7 ? 'high' : domVal >= 0.4 ? 'mid' : 'low';
  return `/static/avatar/emotions/${domEmo}/${tier}.gif`;
}

function getToken() {
  return localStorage.getItem('discord_jwt') || null;
}

function buildLoginGate() {
  const wrap = document.createElement('div');
  wrap.className = 'chat-login glass';
  wrap.style.padding = '40px';

  const img = document.createElement('img');
  img.className = 'chat-login-avatar';
  img.src = getAvatarUrl(emotions);
  img.alt = 'Wally';
  wrap.appendChild(img);

  const title = document.createElement('div');
  title.style.cssText = 'font-size:1.1rem;font-weight:700;';
  title.textContent = 'Parler à Wally';
  wrap.appendChild(title);

  const sub = document.createElement('div');
  sub.style.cssText = 'font-size:0.82rem;color:rgba(255,255,255,0.4);max-width:280px;';
  sub.textContent = 'Connecte-toi avec Discord pour accéder au chat.';
  wrap.appendChild(sub);

  const btn = document.createElement('a');
  btn.className = 'discord-btn';
  btn.href = '/api/chat/auth/login';

  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('width', '20');
  svg.setAttribute('height', '20');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'currentColor');
  const path = document.createElementNS(svgNS, 'path');
  path.setAttribute('d', 'M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z');
  svg.appendChild(path);
  btn.appendChild(svg);
  btn.appendChild(document.createTextNode('Continuer avec Discord'));
  wrap.appendChild(btn);

  return wrap;
}

function buildChatLayout(user) {
  const layout = document.createElement('div');
  layout.className = 'chat-layout';

  // ── Colonne Wally ──
  const wallyCol = document.createElement('div');
  wallyCol.className = 'chat-wally-col';

  const avatar = document.createElement('img');
  avatar.className = 'wally-avatar';
  avatar.src = getAvatarUrl(emotions);
  avatar.alt = 'Wally';
  avatar.id = 'chat-wally-avatar';
  wallyCol.appendChild(avatar);

  const emoLabel = document.createElement('div');
  emoLabel.className = 'wally-emotion-label';
  emoLabel.id = 'chat-wally-emo-label';
  const domEmo = Object.entries(emotions).sort((a,b) => b[1]-a[1])[0][0];
  emoLabel.textContent = EMO_LABELS[domEmo] || domEmo;
  wallyCol.appendChild(emoLabel);

  const onlineLine = document.createElement('div');
  onlineLine.className = 'wally-online';
  const onlineDot = document.createElement('span');
  onlineDot.className = 'dot dot-on';
  onlineLine.appendChild(onlineDot);
  onlineLine.appendChild(document.createTextNode('En ligne'));
  wallyCol.appendChild(onlineLine);

  const miniBars = document.createElement('div');
  miniBars.className = 'emo-bars';
  miniBars.id = 'chat-emo-bars';
  miniBars.style.width = '100%';
  miniBars.style.marginTop = '8px';
  Object.entries(emotions).forEach(([name, val]) => {
    const row = document.createElement('div');
    row.className = 'emo-row';
    const lbl = document.createElement('span');
    lbl.className = 'emo-name';
    lbl.style.fontSize = '0.65rem';
    lbl.textContent = EMO_LABELS[name];
    row.appendChild(lbl);
    const track = document.createElement('div');
    track.className = 'emo-track';
    const fill = document.createElement('div');
    fill.className = 'emo-fill';
    fill.style.width = (val * 100).toFixed(1) + '%';
    fill.style.background = EMO_COLORS[name];
    track.appendChild(fill);
    row.appendChild(track);
    miniBars.appendChild(row);
  });
  wallyCol.appendChild(miniBars);

  layout.appendChild(wallyCol);

  // ── Colonne messages ──
  const msgCol = document.createElement('div');
  msgCol.className = 'chat-messages-col';

  const userBar = document.createElement('div');
  userBar.className = 'chat-user-bar';
  const userAvatar = document.createElement('img');
  userAvatar.className = 'chat-user-avatar';
  userAvatar.src = user.avatar_url || '/static/default_avatar.png';
  userAvatar.alt = user.username;
  userBar.appendChild(userAvatar);
  const userName = document.createElement('div');
  userName.className = 'chat-user-name';
  userName.textContent = user.username;
  userBar.appendChild(userName);
  const logoutBtn = document.createElement('button');
  logoutBtn.className = 'chat-logout';
  logoutBtn.textContent = 'Déconnexion';
  logoutBtn.addEventListener('click', () => {
    localStorage.removeItem('discord_jwt');
    mount(_container);
  });
  userBar.appendChild(logoutBtn);
  msgCol.appendChild(userBar);

  const msgList = document.createElement('div');
  msgList.className = 'messages-list';
  msgList.id = 'chat-messages';
  msgCol.appendChild(msgList);

  const inputRow = document.createElement('div');
  inputRow.className = 'chat-input-row';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'chat-input';
  input.id = 'chat-input';
  input.placeholder = 'Écrire à Wally…';
  const sendBtn = document.createElement('button');
  sendBtn.className = 'chat-send';
  sendBtn.textContent = 'Envoyer';
  inputRow.appendChild(input);
  inputRow.appendChild(sendBtn);
  msgCol.appendChild(inputRow);
  layout.appendChild(msgCol);

  // ── Colonne mémoire ──
  const memCol = document.createElement('div');
  memCol.className = 'memory-col';
  memCol.id = 'chat-memory-col';
  const memLoading = document.createElement('div');
  memLoading.className = 'empty-state';
  memLoading.textContent = 'Chargement…';
  memCol.appendChild(memLoading);
  layout.appendChild(memCol);

  // ── WebSocket ──
  const token = getToken();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _ws = new WebSocket(`${proto}://${location.host}/ws/chat?token=${token}`);

  _ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'typing') {
        showTyping(msgList);
      } else if (data.type === 'message') {
        removeTyping(msgList);
        addBubble(msgList, data.content, 'bot');
      }
    } catch (_) {}
  };

  function sendMessage() {
    const text = input.value.trim();
    if (!text || _ws.readyState !== WebSocket.OPEN) return;
    addBubble(msgList, text, 'user');
    _ws.send(JSON.stringify({ type: 'message', content: text }));
    input.value = '';
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });

  // Load memory sidebar
  fetch('/api/public/memory/me', {
    headers: { 'Authorization': 'Bearer ' + token }
  })
    .then(r => r.ok ? r.json() : null)
    .then(data => renderMemorySidebar(memCol, data))
    .catch(() => renderMemorySidebar(memCol, null));

  return layout;
}

function addBubble(list, text, who) {
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-' + who;
  bubble.textContent = text;
  list.appendChild(bubble);
  list.scrollTop = list.scrollHeight;
}

let _typingEl = null;
function showTyping(list) {
  if (_typingEl) return;
  _typingEl = document.createElement('div');
  _typingEl.className = 'bubble bubble-bot typing-indicator';
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement('span');
    dot.className = 'typing-dot';
    _typingEl.appendChild(dot);
  }
  list.appendChild(_typingEl);
  list.scrollTop = list.scrollHeight;
}
function removeTyping(list) {
  if (_typingEl) { list.removeChild(_typingEl); _typingEl = null; }
}

function renderMemorySidebar(col, data) {
  col.textContent = '';

  if (!data) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Mémoire indisponible';
    col.appendChild(empty);
    return;
  }

  // Relation
  const relTitle = document.createElement('div');
  relTitle.className = 'memory-section-title';
  relTitle.textContent = 'Relation';
  col.appendChild(relTitle);

  const trustRow = document.createElement('div');
  trustRow.className = 'relation-score';
  const tLabel = document.createElement('span');
  tLabel.className = 'score-label';
  tLabel.textContent = 'Confiance';
  const tVal = document.createElement('span');
  tVal.className = 'score-value';
  tVal.textContent = Math.round((data.relation?.trust || 0) * 100) + '%';
  trustRow.appendChild(tLabel);
  trustRow.appendChild(tVal);
  col.appendChild(trustRow);

  const loveRow = document.createElement('div');
  loveRow.className = 'relation-score';
  const lLabel = document.createElement('span');
  lLabel.className = 'score-label';
  lLabel.textContent = 'Affinité';
  const lVal = document.createElement('span');
  lVal.className = 'score-value';
  lVal.textContent = Math.round((data.relation?.love || 0) * 100) + '%';
  loveRow.appendChild(lLabel);
  loveRow.appendChild(lVal);
  col.appendChild(loveRow);

  // Facts
  if (data.facts && data.facts.length > 0) {
    const factsTitle = document.createElement('div');
    factsTitle.className = 'memory-section-title';
    factsTitle.textContent = 'Faits';
    col.appendChild(factsTitle);
    data.facts.slice(0, 8).forEach(text => {
      const item = document.createElement('div');
      item.className = 'memory-item';
      item.textContent = text;
      col.appendChild(item);
    });
  }

  // Prefs
  if (data.preferences && data.preferences.length > 0) {
    const prefsTitle = document.createElement('div');
    prefsTitle.className = 'memory-section-title';
    prefsTitle.textContent = 'Préférences';
    col.appendChild(prefsTitle);
    data.preferences.slice(0, 8).forEach(text => {
      const item = document.createElement('div');
      item.className = 'memory-item';
      item.textContent = text;
      col.appendChild(item);
    });
  }
}

export function mount(el) {
  _container = el;
  el.textContent = '';

  // Handle OAuth callback: exchange code for JWT
  const urlParams = new URLSearchParams(location.search);
  const oauthCode = urlParams.get('chat_code');
  if (oauthCode) {
    // Clean up URL
    history.replaceState({}, '', location.pathname + location.hash);
    fetch('/api/chat/auth/exchange?code=' + encodeURIComponent(oauthCode))
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.jwt) {
          localStorage.setItem('discord_jwt', data.jwt);
          if (data.refresh_token) localStorage.setItem('discord_refresh', data.refresh_token);
        }
        mount(el);
      })
      .catch(() => mount(el));
    el.textContent = '';
    const loading = document.createElement('div');
    loading.className = 'empty-state';
    loading.textContent = 'Connexion en cours…';
    el.appendChild(loading);
    return;
  }

  const token = getToken();
  if (!token) {
    el.appendChild(buildLoginGate());
    return;
  }

  // Decode JWT to get user info (basic, no verify — server validates)
  let user = { username: 'Utilisateur', avatar_url: '' };
  try {
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(b64));
    user.username = payload.username || payload.sub || 'Utilisateur';
    user.avatar_url = payload.avatar_url || '';
  } catch (_) {}

  el.appendChild(buildChatLayout(user));

  // Live avatar updates
  _unsubEmo = onEmotionUpdate((emo) => {
    const avatarEl = document.getElementById('chat-wally-avatar');
    if (avatarEl) avatarEl.src = getAvatarUrl(emo);

    const barsEl = document.getElementById('chat-emo-bars');
    if (barsEl) {
      barsEl.textContent = '';
      Object.entries(emo).forEach(([name, val]) => {
        const row = document.createElement('div');
        row.className = 'emo-row';
        const lbl = document.createElement('span');
        lbl.className = 'emo-name';
        lbl.style.fontSize = '0.65rem';
        lbl.textContent = EMO_LABELS[name];
        row.appendChild(lbl);
        const track = document.createElement('div');
        track.className = 'emo-track';
        const fill = document.createElement('div');
        fill.className = 'emo-fill';
        fill.style.width = (val * 100).toFixed(1) + '%';
        fill.style.background = EMO_COLORS[name];
        track.appendChild(fill);
        row.appendChild(track);
        barsEl.appendChild(row);
      });
    }

    const emoLabelEl = document.getElementById('chat-wally-emo-label');
    if (emoLabelEl) {
      const dom = Object.entries(emo).sort((a,b) => b[1]-a[1])[0][0];
      emoLabelEl.textContent = EMO_LABELS[dom] || dom;
    }
  });
}

export function unmount() {
  if (_ws) { _ws.close(); _ws = null; }
  _container = null;
  if (_unsubEmo) { _unsubEmo(); _unsubEmo = null; }
}
