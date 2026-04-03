// public-ui/tabs/chat.js
import { emotions, onEmotionUpdate } from '../app.js';
import { renderMarkdown } from '../markdown.js';

let _ws          = null;
let _container   = null;
let _unsubEmo    = null;
let _mounted     = false;
let _retryDelay  = 1000;
let _retryTimer  = null;

// ── Date navigation state ──
let _currentDate = null;   // null = today (live WS mode)
let _msgListRef  = null;
let _inputRef    = null;
let _sendBtnRef  = null;
let _dateDisplayRef = null;
let _nextBtnRef  = null;
let _autocompleteDropdown = null;

const DATE_MIN = new Date('2026-03-01');

const IMAGINE_SUGGESTIONS = [
  'un paysage cyberpunk sous la pluie',
  'portrait impressionniste de Wally',
  'ville futuriste vue du ciel, style anime',
  'forêt enchantée la nuit, bioluminescence',
  'chat robot dans un café parisien',
];

function todayStr() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

function formatDateFR(dateStr) {
  const [y, m, day] = dateStr.split('-').map(Number);
  return new Date(y, m - 1, day).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
}

function isToday(dateStr) {
  return dateStr === todayStr();
}

function prevDay(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() - 1);
  return dt.toISOString().slice(0, 10);
}

function nextDay(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + 1);
  return dt.toISOString().slice(0, 10);
}

function isAtMin(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  return dt <= DATE_MIN;
}

const EMO_COLORS = { anger:'#ef4444', joy:'#eab308', curiosity:'#22c55e', sadness:'#3b82f6', boredom:'#a855f7' };
const EMO_LABELS = { anger:'Colère', joy:'Joie', curiosity:'Curiosité', sadness:'Tristesse', boredom:'Ennui' };

function getAvatarUrl(emo) {
  let domEmo = 'curiosity', domVal = 0;
  for (const name of ['anger','joy','curiosity','sadness','boredom']) {
    if ((emo[name] || 0) > domVal) { domVal = emo[name]; domEmo = name; }
  }
  if (domVal < 0.2) domEmo = 'curiosity';
  const tier = domVal >= 0.7 ? 'high' : domVal >= 0.4 ? 'mid' : 'low';
  return `/static/avatar/emotions/${domEmo}/${tier}.gif`;
}

function getToken() {
  return localStorage.getItem('discord_jwt') || null;
}

// ── Indicateur de connexion WS ──
function setWsStatus(online) {
  const dot   = document.getElementById('chat-ws-dot');
  const label = document.getElementById('chat-ws-label');
  if (dot)   dot.className = 'dot ' + (online ? 'dot-on' : 'dot-off');
  if (label) label.textContent = online ? 'En ligne' : 'Reconnexion…';
}

// ── Bulle de message ──
function addBubble(list, text, who) {
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-' + who;
  if (who === 'bot') {
    renderMarkdown(text, bubble);
  } else {
    bubble.textContent = text;
  }
  list.appendChild(bubble);
  list.scrollTop = list.scrollHeight;
  return bubble;
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

// ── Connexion WebSocket avec reconnexion automatique ──
function connectWs(msgList, token) {
  if (!_mounted) return;

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _ws = new WebSocket(`${proto}://${location.host}/ws/chat?token=${token}`);

  _ws.onopen = () => {
    _retryDelay = 1000; // reset backoff
    setWsStatus(true);
  };

  _ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);

      if (data.type === 'history') {
        // Restaure les messages du jour
        const msgs = data.messages || [];
        msgs.forEach(msg => addBubble(msgList, msg.content, msg.is_wally ? 'bot' : 'user'));
        msgList.scrollTop = msgList.scrollHeight;

      } else if (data.type === 'typing') {
        showTyping(msgList);

      } else if (data.type === 'message') {
        removeTyping(msgList);
        // Ignore l'écho du message utilisateur (déjà affiché localement)
        if (data.is_wally !== false) {
          addBubble(msgList, data.content, 'bot');
        }

      } else if (data.type === 'image_generating') {
        removeTyping(msgList);
        const placeholder = document.createElement('div');
        placeholder.className = 'bubble bubble-bot';
        placeholder.id = 'img-' + data.id;
        placeholder.style.cssText = 'color:rgba(255,255,255,0.4);font-style:italic;font-size:0.82rem;';
        placeholder.textContent = '🎨 Génération en cours…';
        msgList.appendChild(placeholder);
        msgList.scrollTop = msgList.scrollHeight;

      } else if (data.type === 'image_result') {
        removeTyping(msgList);
        let el = document.getElementById('img-' + data.id);
        if (!el) {
          el = document.createElement('div');
          el.className = 'bubble bubble-bot';
          msgList.appendChild(el);
        }
        el.id = '';
        el.style.cssText = '';
        el.textContent = '';
        if (data.title) {
          const titleEl = document.createElement('div');
          titleEl.style.cssText = 'font-size:0.75rem;color:rgba(255,255,255,0.45);margin-bottom:6px;';
          titleEl.textContent = data.title;
          el.appendChild(titleEl);
        }
        const img = document.createElement('img');
        img.src = data.image_url;
        img.alt = data.title || 'Image générée';
        img.style.cssText = 'max-width:100%;border-radius:8px;display:block;cursor:pointer;';
        img.loading = 'lazy';
        el.appendChild(img);
        msgList.scrollTop = msgList.scrollHeight;

      } else if (data.type === 'image_cancelled') {
        const el = document.getElementById('img-' + data.id);
        if (el) {
          el.id = '';
          el.style.cssText = '';
          el.textContent = '⚠️ ' + (data.error || 'Génération annulée');
        }

      } else if (data.type === 'system') {
        const el = document.createElement('div');
        el.className = 'bubble bubble-system';
        el.textContent = data.content;
        msgList.appendChild(el);
        msgList.scrollTop = msgList.scrollHeight;
      }
    } catch (_) {}
  };

  _ws.onclose = () => {
    if (!_mounted) return;
    setWsStatus(false);
    // Reconnexion exponentielle (1s → 2s → 4s → … → 30s max)
    _retryTimer = setTimeout(() => {
      _retryDelay = Math.min(_retryDelay * 2, 30000);
      connectWs(msgList, token);
    }, _retryDelay);
  };
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
  svg.setAttribute('width', '20'); svg.setAttribute('height', '20');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'currentColor');
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
  onlineDot.id = 'chat-ws-dot';
  onlineLine.appendChild(onlineDot);
  const onlineLabel = document.createElement('span');
  onlineLabel.id = 'chat-ws-label';
  onlineLabel.textContent = 'En ligne';
  onlineLine.appendChild(onlineLabel);
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

  // ── Date navigation bar ──
  const dateBar = document.createElement('div');
  dateBar.className = 'chat-date-bar';

  const prevBtn = document.createElement('button');
  prevBtn.className = 'chat-date-btn';
  prevBtn.textContent = '‹ Préc.';
  dateBar.appendChild(prevBtn);

  const dateDisplay = document.createElement('span');
  dateDisplay.className = 'chat-date-label';
  dateDisplay.textContent = formatDateFR(todayStr());
  _dateDisplayRef = dateDisplay;
  dateBar.appendChild(dateDisplay);

  const nextBtn = document.createElement('button');
  nextBtn.className = 'chat-date-btn';
  nextBtn.textContent = 'Suiv. ›';
  nextBtn.disabled = true; // today — no next
  _nextBtnRef = nextBtn;
  dateBar.appendChild(nextBtn);

  msgCol.appendChild(dateBar);
  msgCol.appendChild(msgList);

  // ── Input row wrapper (for autocomplete positioning) ──
  const inputWrap = document.createElement('div');
  inputWrap.className = 'chat-input-wrap';

  const inputRow = document.createElement('div');
  inputRow.className = 'chat-input-row';

  // 🎨 Imagine button
  const imagineBtn = document.createElement('button');
  imagineBtn.className = 'chat-imagine-btn';
  imagineBtn.title = 'Générer une image';
  imagineBtn.textContent = '🎨';
  inputRow.appendChild(imagineBtn);

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
  inputWrap.appendChild(inputRow);
  msgCol.appendChild(inputWrap);
  layout.appendChild(msgCol);

  _inputRef   = input;
  _sendBtnRef = sendBtn;

  // ── Colonne mémoire ──
  const memCol = document.createElement('div');
  memCol.className = 'memory-col';
  memCol.id = 'chat-memory-col';
  const memLoading = document.createElement('div');
  memLoading.className = 'empty-state';
  memLoading.textContent = 'Chargement…';
  memCol.appendChild(memLoading);
  layout.appendChild(memCol);

  // ── Autocomplete dropdown ──
  function buildAutocomplete() {
    const dd = document.createElement('div');
    dd.className = 'imagine-autocomplete';
    dd.style.display = 'none';
    IMAGINE_SUGGESTIONS.forEach(sug => {
      const item = document.createElement('div');
      item.className = 'imagine-suggestion';
      item.textContent = sug;
      item.addEventListener('mousedown', (e) => {
        e.preventDefault(); // don't blur input
        input.value = '/imagine ' + sug;
        hideAutocomplete();
        input.focus();
      });
      dd.appendChild(item);
    });
    inputWrap.appendChild(dd);
    _autocompleteDropdown = dd;
    return dd;
  }

  const autocomplete = buildAutocomplete();

  function showAutocomplete() {
    autocomplete.style.display = 'block';
  }
  function hideAutocomplete() {
    autocomplete.style.display = 'none';
  }

  input.addEventListener('input', () => {
    if (input.value.startsWith('/imagine ')) {
      showAutocomplete();
    } else {
      hideAutocomplete();
    }
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { hideAutocomplete(); return; }
    if (e.key === 'Enter') { hideAutocomplete(); sendMessage(); }
  });

  document.addEventListener('click', (e) => {
    if (!inputWrap.contains(e.target)) hideAutocomplete();
  }, { capture: false });

  // 🎨 imagine button
  imagineBtn.addEventListener('click', () => {
    if (!input.value.startsWith('/imagine ')) {
      input.value = '/imagine ';
    }
    input.focus();
    showAutocomplete();
  });

  // ── Envoi de message ──
  function sendMessage() {
    const text = input.value.trim();
    if (!text || !_ws || _ws.readyState !== WebSocket.OPEN) return;
    if (_currentDate !== null) return; // lecture seule — historique passé
    addBubble(msgList, text, 'user');
    _ws.send(JSON.stringify({ type: 'message', content: text }));
    input.value = '';
  }
  sendBtn.addEventListener('click', sendMessage);

  // ── Date navigation ──
  function setLiveMode() {
    _currentDate = null;
    _dateDisplayRef.textContent = formatDateFR(todayStr());
    _nextBtnRef.disabled = true;
    prevBtn.disabled = false;
    input.disabled   = false;
    sendBtn.disabled = false;
    input.placeholder = 'Écrire à Wally…';
    // Re-show WS indicator
    const wsLabel = document.getElementById('chat-ws-label');
    if (wsLabel) wsLabel.parentElement.style.visibility = '';
    // Clear history messages and reconnect WS so it sends history
    msgList.textContent = '';
    if (_ws) { _ws.onclose = null; _ws.close(); _ws = null; }
    connectWs(msgList, getToken());
  }

  function setHistoryMode(dateStr) {
    _currentDate = dateStr;
    _dateDisplayRef.textContent = formatDateFR(dateStr);
    _nextBtnRef.disabled = isToday(nextDay(dateStr));
    prevBtn.disabled = isAtMin(dateStr);
    input.disabled   = true;
    sendBtn.disabled = true;
    input.placeholder = 'Lecture seule — historique du ' + formatDateFR(dateStr);
    // Hide WS indicator (not meaningful in history mode)
    const wsLabel = document.getElementById('chat-ws-label');
    if (wsLabel) wsLabel.parentElement.style.visibility = 'hidden';
    loadHistory(dateStr);
  }

  function loadHistory(dateStr) {
    const token = getToken();
    msgList.textContent = '';
    const loadingMsg = document.createElement('div');
    loadingMsg.className = 'bubble bubble-system';
    loadingMsg.textContent = 'Chargement de l\'historique…';
    msgList.appendChild(loadingMsg);

    fetch('/api/chat/history/' + dateStr, { headers: { 'Authorization': 'Bearer ' + token } })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        msgList.textContent = '';
        const msgs = (data && data.messages) ? data.messages : [];
        if (!msgs.length) {
          const empty = document.createElement('div');
          empty.className = 'bubble bubble-system';
          empty.textContent = 'Aucun message ce jour-là.';
          msgList.appendChild(empty);
        } else {
          msgs.forEach(msg => addBubble(msgList, msg.content, msg.is_wally ? 'bot' : 'user'));
        }
      })
      .catch(() => {
        msgList.textContent = '';
        const errEl = document.createElement('div');
        errEl.className = 'bubble bubble-system';
        errEl.textContent = 'Impossible de charger l\'historique.';
        msgList.appendChild(errEl);
      });
  }

  prevBtn.addEventListener('click', () => {
    const from = _currentDate || todayStr();
    const p = prevDay(from);
    if (isAtMin(p)) { prevBtn.disabled = true; }
    setHistoryMode(p);
  });

  nextBtn.addEventListener('click', () => {
    if (!_nextBtnRef || _nextBtnRef.disabled) return;
    const n = nextDay(_currentDate);
    if (isToday(n)) {
      // Restore input placeholder
      input.placeholder = 'Écrire à Wally…';
      setLiveMode();
    } else {
      setHistoryMode(n);
    }
  });

  // ── WebSocket ──
  const token = getToken();
  setWsStatus(false); // commence en "connexion…" jusqu'à onopen
  connectWs(msgList, token);

  // ── Sidebar mémoire ──
  fetch('/api/public/memory/me', { headers: { 'Authorization': 'Bearer ' + token } })
    .then(r => r.ok ? r.json() : null)
    .then(data => renderMemorySidebar(memCol, data))
    .catch(() => renderMemorySidebar(memCol, null));

  return layout;
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

  const relTitle = document.createElement('div');
  relTitle.className = 'memory-section-title';
  relTitle.textContent = 'Relation';
  col.appendChild(relTitle);

  [['Confiance', data.relation?.trust], ['Affinité', data.relation?.love]].forEach(([label, val]) => {
    const row = document.createElement('div');
    row.className = 'relation-score';
    const lbl = document.createElement('span');
    lbl.className = 'score-label';
    lbl.textContent = label;
    const v = document.createElement('span');
    v.className = 'score-value';
    v.textContent = Math.round((val || 0) * 100) + '%';
    row.appendChild(lbl);
    row.appendChild(v);
    col.appendChild(row);
  });

  [['Faits', data.facts], ['Préférences', data.preferences]].forEach(([title, items]) => {
    if (!items || !items.length) return;
    const t = document.createElement('div');
    t.className = 'memory-section-title';
    t.textContent = title;
    col.appendChild(t);
    items.slice(0, 8).forEach(text => {
      const item = document.createElement('div');
      item.className = 'memory-item';
      item.textContent = text;
      col.appendChild(item);
    });
  });
}

export function mount(el) {
  _container = el;
  _mounted   = true;
  el.textContent = '';

  // Échange OAuth
  const urlParams = new URLSearchParams(location.search);
  const oauthCode = urlParams.get('chat_code');
  if (oauthCode) {
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

  // Décode JWT (sans vérification — le serveur valide)
  let user = { username: 'Utilisateur', avatar_url: '' };
  try {
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(b64));
    user.username  = payload.username || payload.sub || 'Utilisateur';
    user.avatar_url = payload.avatar_url || '';
  } catch (_) {}

  el.appendChild(buildChatLayout(user));

  // Mises à jour live avatar/émotions
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
  _mounted    = false;
  _currentDate = null;
  _msgListRef  = null;
  _inputRef    = null;
  _sendBtnRef  = null;
  _dateDisplayRef = null;
  _nextBtnRef  = null;
  _autocompleteDropdown = null;
  clearTimeout(_retryTimer);
  _retryTimer  = null;
  _retryDelay  = 1000;
  if (_ws) { _ws.onclose = null; _ws.close(); _ws = null; }
  _container = null;
  if (_unsubEmo) { _unsubEmo(); _unsubEmo = null; }
}
