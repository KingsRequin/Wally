// public-ui/tabs/community.js — arcade
// Force-directed social graph — pure canvas, no external libs

let _container = null;
let _canvas    = null;
let _tooltip   = null;
let _rafId     = null;
let _mounted   = false;

// Viewport transform
let _scale    = 1;
let _offsetX  = 0;
let _offsetY  = 0;
let _dragging   = false;
let _dragStartX = 0;
let _dragStartY = 0;
let _dragOffX   = 0;
let _dragOffY   = 0;

// Global mouse handlers (attached to window for pan)
let _boundMouseMove = null;
let _boundMouseUp   = null;
let _lastPinchDist  = null;

const DEFAULT_COLOR  = '#06b6d4';
const MIN_RADIUS     = 8;
const MAX_RADIUS     = 22;

// Edge type detection from French signal fact text
const EDGE_COLORS = {
  vocal:    '#818cf8',  // indigo  — vocal sessions
  game:     '#22c55e',  // green   — playing together
  reply:    '#06b6d4',  // cyan    — replies
  mention:  '#eab308',  // yellow  — mentions
  reaction: '#f472b6',  // pink    — reactions
  thread:   '#f97316',  // orange  — threads
  default:  'rgba(255,255,255,0.22)',
};

function detectEdgeType(facts) {
  const text = (facts || []).join(' ').toLowerCase();
  if (text.includes('vocal'))                         return 'vocal';
  if (text.includes('joué') || text.includes('jeu')) return 'game';
  if (text.includes('répondu'))                       return 'reply';
  if (text.includes('mentionné'))                     return 'mention';
  if (text.includes('réagi') || text.includes('réaction')) return 'reaction';
  if (text.includes('thread'))                        return 'thread';
  return 'default';
}
const MAX_TICKS      = 400;
const REPULSION      = 8000;
const ATTRACTION     = 0.018;
const DAMPING        = 0.70;
const CENTER_FORCE   = 0.010;
const IDEAL_DIST     = 120;

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

function nodeColor(n) {
  const labels = n.labels || [];
  if (labels.includes('User') || labels.includes('Person')) return '#5865f2';
  if (labels.includes('Community')) return '#9146ff';
  return DEFAULT_COLOR;
}

function nodeRadius(degree, minDeg, maxDeg) {
  if (maxDeg === minDeg) return (MIN_RADIUS + MAX_RADIUS) / 2;
  const t = (degree - minDeg) / (maxDeg - minDeg);
  return MIN_RADIUS + t * (MAX_RADIUS - MIN_RADIUS);
}

function tick(nodes, edges, W, H) {
  const cx = W / 2, cy = H / 2;
  nodes.forEach(n => { n.fx = 0; n.fy = 0; });

  // Répulsion Coulomb
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const dist2 = dx * dx + dy * dy + 1;
      const force = REPULSION / dist2;
      const dist  = Math.sqrt(dist2);
      const fx = (dx / dist) * force, fy = (dy / dist) * force;
      a.fx -= fx; a.fy -= fy;
      b.fx += fx; b.fy += fy;
    }
  }

  // Attraction ressort avec distance idéale
  edges.forEach(e => {
    const a = e._a, b = e._b;
    if (!a || !b) return;
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) + 1;
    const displacement = dist - IDEAL_DIST;
    const force = ATTRACTION * displacement;
    const fx = (dx / dist) * force, fy = (dy / dist) * force;
    a.fx += fx; a.fy += fy;
    b.fx -= fx; b.fy -= fy;
  });

  // Force de centrage
  nodes.forEach(n => {
    n.fx += (cx - n.x) * CENTER_FORCE;
    n.fy += (cy - n.y) * CENTER_FORCE;
  });

  // Intégration
  nodes.forEach(n => {
    n.vx = (n.vx + n.fx) * DAMPING;
    n.vy = (n.vy + n.fy) * DAMPING;
    const nx = n.x + n.vx;
    const ny = n.y + n.vy;
    // Annuler la vélocité si on touche un bord (évite le rebond)
    if (nx < n.r + 2 || nx > W - n.r - 2) n.vx = 0;
    if (ny < n.r + 2 || ny > H - n.r - 2) n.vy = 0;
    n.x = clamp(nx, n.r + 2, W - n.r - 2);
    n.y = clamp(ny, n.r + 2, H - n.r - 2);
  });
}

function drawFrame(ctx, nodes, edges, W, H, selectedNode) {
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  ctx.save();
  ctx.translate(_offsetX + W / 2, _offsetY + H / 2);
  ctx.scale(_scale, _scale);
  ctx.translate(-W / 2, -H / 2);

  // Pré-calcul : arêtes connectées au nœud sélectionné
  const connectedEdges = selectedNode
    ? new Set(edges.filter(e => e._a === selectedNode || e._b === selectedNode))
    : null;
  const connectedNodes = selectedNode
    ? new Set(
        edges
          .filter(e => e._a === selectedNode || e._b === selectedNode)
          .flatMap(e => [e._a, e._b])
      )
    : null;

  // Arêtes
  edges.forEach(e => {
    const a = e._a, b = e._b;
    if (!a || !b) return;

    const isConnected = !connectedEdges || connectedEdges.has(e);
    const baseColor   = EDGE_COLORS[e._type || 'default'];
    const alpha       = isConnected ? 1 : 0.08;

    const w = Math.min(1 + (e.weight || 1) * 0.5, 5);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = isConnected ? baseColor : 'rgba(255,255,255,0.22)';
    ctx.lineWidth   = isConnected && connectedEdges ? w + 1 : w;
    ctx.stroke();
    ctx.globalAlpha = 1;

    // Poids au milieu de l'arête si > 1 et visible
    if (isConnected && (e.weight || 1) > 1) {
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      ctx.font = '9px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillStyle = 'rgba(255,255,255,0.4)';
      ctx.fillText(String(e.weight), mx, my - 3);
    }
  });

  // Nœuds + labels
  ctx.font = '11px Inter, sans-serif';
  ctx.textAlign = 'center';
  nodes.forEach(n => {
    const isSel      = n === selectedNode;
    const isDimmed   = connectedNodes && !connectedNodes.has(n);
    const color      = n.color;

    ctx.globalAlpha = isDimmed ? 0.2 : 1;

    // Halo pour le nœud sélectionné
    if (isSel) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + 6, 0, Math.PI * 2);
      ctx.strokeStyle = color;
      ctx.lineWidth   = 2;
      ctx.globalAlpha = 0.4;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // Cercle
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
    ctx.fillStyle = isSel ? color + 'ee' : color + 'bb';
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth   = isSel ? 2.5 : 1.5;
    ctx.stroke();

    // Label
    const label = n.name || n.id;
    const labelY = n.y + n.r + 14;
    ctx.font = isSel ? 'bold 11px Inter, sans-serif' : '11px Inter, sans-serif';
    ctx.textAlign = 'center';
    const metrics = ctx.measureText(label);
    const lw = metrics.width + 8;
    const lh = 14;

    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    ctx.beginPath();
    if (ctx.roundRect) {
      ctx.roundRect(n.x - lw / 2, labelY - lh + 2, lw, lh, 3);
    } else {
      ctx.rect(n.x - lw / 2, labelY - lh + 2, lw, lh);
    }
    ctx.fill();

    ctx.fillStyle = isDimmed ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.85)';
    ctx.fillText(label, n.x, labelY);

    ctx.globalAlpha = 1;
  });

  ctx.restore();
}

function screenToWorld(mx, my, W, H) {
  return {
    x: (mx - _offsetX - W / 2) / _scale + W / 2,
    y: (my - _offsetY - H / 2) / _scale + H / 2,
  };
}

function hitTestNode(nodes, mx, my, W, H) {
  const { x, y } = screenToWorld(mx, my, W, H);
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const dx = x - n.x, dy = y - n.y;
    if (dx * dx + dy * dy <= n.r * n.r) return n;
  }
  return null;
}

function hitTestEdge(edges, mx, my, W, H) {
  const { x, y } = screenToWorld(mx, my, W, H);
  const THRESH = 8 / _scale;
  for (let i = edges.length - 1; i >= 0; i--) {
    const e = edges[i];
    const a = e._a, b = e._b;
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const len2 = dx * dx + dy * dy + 1;
    const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / len2));
    const px = a.x + t * dx - x;
    const py = a.y + t * dy - y;
    if (px * px + py * py <= THRESH * THRESH) return e;
  }
  return null;
}

function buildNodeTooltip(node) {
  const frag = document.createDocumentFragment();
  const nameEl = document.createElement('div');
  nameEl.style.cssText = 'font-weight:600;';
  nameEl.textContent = node.name;
  frag.appendChild(nameEl);
  if (node.summary) {
    const s = node.summary.length > 120 ? node.summary.slice(0, 120) + '…' : node.summary;
    const sumEl = document.createElement('div');
    sumEl.style.cssText = 'font-size:0.7rem;color:rgba(255,255,255,0.5);margin-top:3px;line-height:1.4;';
    sumEl.textContent = s;
    frag.appendChild(sumEl);
  }
  return frag;
}

function buildEdgeTooltip(edge) {
  const frag = document.createDocumentFragment();
  const sn = edge.source_name || (edge._a && edge._a.name) || '';
  const tn = edge.target_name || (edge._b && edge._b.name) || '';
  const nameEl = document.createElement('strong');
  nameEl.style.fontSize = '0.75rem';
  nameEl.textContent = sn + ' → ' + tn;
  frag.appendChild(nameEl);

  const countEl = document.createElement('div');
  countEl.style.cssText = 'font-size:0.68rem;color:rgba(255,255,255,0.4);margin-top:2px;';
  const w = edge.weight || 1;
  countEl.textContent = w + ' relation' + (w > 1 ? 's' : '');
  frag.appendChild(countEl);

  const facts = (edge.facts || []).slice(0, 3);
  facts.forEach(f => {
    const row = document.createElement('div');
    row.style.cssText = 'font-size:0.68rem;color:rgba(255,255,255,0.6);line-height:1.4;margin-top:4px;padding-top:4px;border-top:1px solid rgba(255,255,255,0.08);';
    row.textContent = f.length > 90 ? f.slice(0, 90) + '…' : f;
    frag.appendChild(row);
  });
  return frag;
}

function positionTooltip(tooltip, wrap, clientX, clientY) {
  tooltip.style.display = 'block';
  const wRect = wrap.getBoundingClientRect();
  const tw = 240, th = tooltip.offsetHeight || 80;
  let left = clientX - wRect.left + 14;
  let top  = clientY - wRect.top  - 12;
  if (left + tw > wRect.width)  left = clientX - wRect.left - tw - 14;
  if (top  + th > wRect.height) top  = clientY - wRect.top  - th - 4;
  tooltip.style.left = left + 'px';
  tooltip.style.top  = top  + 'px';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

function buildHeader() {
  const head = document.createElement('div');
  const eyebrow = document.createElement('div');
  eyebrow.className = 'arc-eyebrow';
  eyebrow.textContent = 'LES GENS · WALLY';
  const h2 = document.createElement('h2');
  h2.className = 'arc-h2';
  h2.textContent = 'COMMUNAUTÉ';
  const sub = document.createElement('div');
  sub.className = 'arc-sub';
  sub.textContent = 'qui parle à wally, et ce qu\'il pense d\'eux.';
  head.appendChild(eyebrow); head.appendChild(h2); head.appendChild(sub);
  return head;
}

function buildTopCards() {
  const grid = document.createElement('div');
  grid.className = 'arc-grid';
  grid.style.gridTemplateColumns = 'repeat(auto-fit,minmax(260px,1fr))';
  grid.style.marginBottom = '18px';

  const chan = document.createElement('div');
  chan.className = 'arc-card';
  const chanLbl = document.createElement('div');
  chanLbl.className = 'arc-stat-label';
  chanLbl.style.cssText = 'font-size:11px;color:var(--yellow);';
  chanLbl.textContent = 'LA CHAÎNE';
  const chanVal = document.createElement('div');
  chanVal.style.cssText = 'font-size:24px;color:var(--cyan);margin-top:12px;';
  chanVal.textContent = 'twitch.tv/Azrael_TTV';
  chan.appendChild(chanLbl); chan.appendChild(chanVal);
  grid.appendChild(chan);

  const wake = document.createElement('div');
  wake.className = 'arc-card';
  const wakeLbl = document.createElement('div');
  wakeLbl.className = 'arc-stat-label';
  wakeLbl.style.cssText = 'font-size:11px;color:var(--yellow);';
  wakeLbl.textContent = 'POUR LE RÉVEILLER';
  const wakeVal = document.createElement('div');
  wakeVal.style.cssText = 'font-size:24px;color:var(--pink);margin-top:12px;';
  wakeVal.textContent = '@WallyTeBully';
  const wakeSub = document.createElement('div');
  wakeSub.style.cssText = 'font-size:18px;color:var(--muted);margin-top:6px;';
  wakeSub.textContent = 'mentionne-le dans le chat, il finira par répondre.';
  wake.appendChild(wakeLbl); wake.appendChild(wakeVal); wake.appendChild(wakeSub);
  grid.appendChild(wake);

  return grid;
}

async function loadRanking(host) {
  let ranking = [];
  try {
    ranking = (await (await fetch('/api/public/community/ranking')).json()).ranking || [];
  } catch (_) {}
  if (!ranking.length) {
    host.innerHTML = '<div class="empty-state">Pas encore de classement.</div>';
    return;
  }
  host.innerHTML = ranking.map((r, i) => {
    const isMax = r.score === 'MAX';
    const rk = isMax ? '∞' : '#' + (i + 1);
    const rkCol = isMax ? 'var(--pink)' : (i === 0 ? 'var(--yellow)' : 'var(--muted)');
    const nameCol = isMax ? 'var(--yellow)' : 'var(--text)';
    const scoreCol = isMax ? 'var(--pink)' : 'var(--cyan)';
    return `<div class="feed-row" style="font-size:22px;align-items:center">
      <span style="color:${rkCol};width:46px;flex:none">${escapeHtml(rk)}</span>
      <span style="flex:1;color:${nameCol}">${escapeHtml(r.name)}</span>
      <span style="color:var(--muted);flex:none">${escapeHtml(r.trait)}</span>
      <span style="color:${scoreCol};width:80px;text-align:right;flex:none">${escapeHtml(r.score)}</span>
    </div>`;
  }).join('');
}

function buildRankingCard() {
  const card = document.createElement('div');
  card.className = 'arc-card';
  card.style.marginBottom = '18px';
  const title = document.createElement('div');
  title.className = 'arc-stat-label';
  title.style.cssText = 'font-size:11px;color:var(--yellow);margin-bottom:14px;';
  title.textContent = 'CLASSEMENT DES VIEWERS';
  card.appendChild(title);
  const list = document.createElement('div');
  list.innerHTML = '<div class="empty-state">Chargement…</div>';
  card.appendChild(list);
  loadRanking(list);
  return card;
}

export function mount(el) {
  _container = el;
  _mounted   = true;
  _scale     = 1;
  _offsetX   = 0;
  _offsetY   = 0;
  el.textContent = '';

  el.appendChild(buildHeader());
  el.appendChild(buildTopCards());
  el.appendChild(buildRankingCard());

  const wrap = document.createElement('div');
  wrap.className = 'community-wrap arc-card';

  const titleEl = document.createElement('div');
  titleEl.className = 'arc-stat-label';
  titleEl.style.cssText = 'font-size:11px;color:var(--yellow);';
  titleEl.textContent = 'GRAPHE SOCIAL';
  wrap.appendChild(titleEl);

  const loading = document.createElement('div');
  loading.className = 'empty-state';
  loading.textContent = 'Chargement du graphe…';
  wrap.appendChild(loading);

  el.appendChild(wrap);

  fetch('/api/public/social-graph/data')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!_mounted) return;
      wrap.removeChild(loading);
      _renderGraph(wrap, data);
    })
    .catch(() => {
      if (!_mounted) return;
      loading.textContent = 'Impossible de charger les données.';
    });
}

function _renderGraph(wrap, data) {
  if (!data || !data.nodes || data.nodes.length < 2) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Pas encore de données de communauté.';
    wrap.appendChild(empty);
    return;
  }

  const rawNodes = data.nodes || [];
  const rawEdges = data.edges || [];

  const degreeMap = new Map();
  rawNodes.forEach(n => degreeMap.set(n.id, 0));
  rawEdges.forEach(e => {
    degreeMap.set(e.source, (degreeMap.get(e.source) || 0) + 1);
    degreeMap.set(e.target, (degreeMap.get(e.target) || 0) + 1);
  });
  const degrees  = [...degreeMap.values()];
  const minDeg   = Math.min(...degrees);
  const maxDeg   = Math.max(...degrees);

  const nodes = rawNodes.map(n => ({
    ...n,
    x: 0, y: 0, vx: 0, vy: 0, fx: 0, fy: 0,
    r:     nodeRadius(degreeMap.get(n.id) || 0, minDeg, maxDeg),
    color: nodeColor(n),
    name:  n.name || n.id,
  }));

  const nodeById = new Map(nodes.map(n => [n.id, n]));

  const edges = rawEdges
    .map(e => ({
      ...e,
      _a: nodeById.get(e.source),
      _b: nodeById.get(e.target),
      _type: detectEdgeType(e.facts),
    }))
    .filter(e => e._a && e._b);

  // Légende — types d'arêtes présents uniquement
  const legend = document.createElement('div');
  legend.className = 'community-legend';

  const EDGE_TYPE_LABELS = {
    vocal:    'Vocal',
    game:     'Jeu',
    reply:    'Réponses',
    mention:  'Mentions',
    reaction: 'Réactions',
    thread:   'Threads',
  };
  const presentTypes = [...new Set(edges.map(e => e._type).filter(t => t !== 'default'))];
  presentTypes.forEach(t => {
    const item = document.createElement('div');
    item.className = 'community-legend-item';
    const dot = document.createElement('span');
    dot.className = 'community-legend-dot';
    dot.style.background = EDGE_COLORS[t];
    item.appendChild(dot);
    item.appendChild(document.createTextNode(EDGE_TYPE_LABELS[t] || t));
    legend.appendChild(item);
  });

  const edgeNote = document.createElement('div');
  edgeNote.style.cssText = 'font-size:0.7rem;color:rgba(255,255,255,0.3);margin-left:auto;';
  edgeNote.textContent = nodes.length + ' nœuds · ' + edges.length + ' liens';
  legend.appendChild(edgeNote);
  const hint = document.createElement('div');
  hint.style.cssText = 'font-size:0.65rem;color:rgba(255,255,255,0.2);margin-left:8px;white-space:nowrap;';
  hint.textContent = ('ontouchstart' in window)
    ? '👆 pincer = zoom \xB7 glisser = d\xE9placer'
    : '\uD83D\uDDB1\uFE0F molette = zoom \xB7 glisser = d\xE9placer';
  legend.appendChild(hint);
  wrap.appendChild(legend);

  _canvas = document.createElement('canvas');
  _canvas.className = 'community-canvas';
  wrap.appendChild(_canvas);

  // Boutons de contrôle flottants (+/−/reset)
  const controls  = document.createElement('div');
  controls.className = 'graph-controls';

  const btnIn    = document.createElement('button');
  btnIn.className  = 'graph-ctrl-btn';
  btnIn.title      = 'Zoom avant';
  btnIn.textContent = '+';

  const btnOut   = document.createElement('button');
  btnOut.className = 'graph-ctrl-btn';
  btnOut.title     = 'Zoom arrière';
  btnOut.textContent = '\u2212'; // −

  const btnReset = document.createElement('button');
  btnReset.className  = 'graph-ctrl-btn';
  btnReset.title      = 'Réinitialiser';
  btnReset.textContent = '\u2316'; // ⌖

  controls.appendChild(btnIn);
  controls.appendChild(btnOut);
  controls.appendChild(btnReset);
  wrap.appendChild(controls);

  _tooltip = document.createElement('div');
  _tooltip.className = 'community-tooltip';
  _tooltip.style.display = 'none';
  wrap.appendChild(_tooltip);

  function resizeCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const W   = Math.max(_canvas.clientWidth  || 700, 320);
    const H   = Math.max(_canvas.clientHeight || 360, 240);

    _canvas.width  = Math.round(W * dpr);
    _canvas.height = Math.round(H * dpr);
    // Ne pas toucher style.width/height — le flex CSS gère la taille affichée

    return { W, H };
  }

  requestAnimationFrame(() => {
    let { W, H } = resizeCanvas();

    // Positions initiales en cercle
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * Math.PI * 2;
      const r = Math.min(W, H) * 0.35;
      n.x = W / 2 + Math.cos(angle) * r;
      n.y = H / 2 + Math.sin(angle) * r;
    });

    const ctx = _canvas.getContext('2d');
    let tickCount = 0, frozen = false;
    let selectedNode = null;

    function animate() {
      if (!_mounted) return;
      if (!frozen) {
        tick(nodes, edges, W, H);
        tickCount++;
        if (tickCount >= MAX_TICKS) frozen = true;
      }
      drawFrame(ctx, nodes, edges, W, H, selectedNode);
      _rafId = requestAnimationFrame(animate);
    }
    animate();

    function canvasCoords(e) {
      const rect = _canvas.getBoundingClientRect();
      return [
        e.clientX - rect.left,
        e.clientY - rect.top,
      ];
    }

    // ── Zoom molette ──
    _canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const [mx, my] = canvasCoords(e);
      const factor   = e.deltaY < 0 ? 1.1 : 1 / 1.1;
      const newScale = clamp(_scale * factor, 0.15, 6);
      const sf       = newScale / _scale;
      // Zoom centré sur la position du curseur dans l'espace canvas
      _offsetX = mx - W / 2 - sf * (mx - W / 2 - _offsetX);
      _offsetY = my - H / 2 - sf * (my - H / 2 - _offsetY);
      _scale   = newScale;
    }, { passive: false });

    // ── Pan clic-glisser ──
    _canvas.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      const [mx, my] = canvasCoords(e);
      const hitNode  = hitTestNode(nodes, mx, my, W, H);
      if (!hitNode) {
        _dragging   = true;
        _dragStartX = e.clientX;
        _dragStartY = e.clientY;
        _dragOffX   = _offsetX;
        _dragOffY   = _offsetY;
        _canvas.style.cursor = 'grabbing';
      }
    });

    _boundMouseMove = (e) => {
      if (!_mounted) return;
      if (_dragging) {
        _offsetX = _dragOffX + (e.clientX - _dragStartX);
        _offsetY = _dragOffY + (e.clientY - _dragStartY);
        _tooltip.style.display = 'none';
        return;
      }
      if (!_canvas) return;
      const [mx, my] = canvasCoords(e);

      const hitNode = hitTestNode(nodes, mx, my, W, H);
      if (hitNode) {
        _tooltip.textContent = '';
        _tooltip.appendChild(buildNodeTooltip(hitNode));
        positionTooltip(_tooltip, wrap, e.clientX, e.clientY);
        _canvas.style.cursor = 'pointer';
        return;
      }
      const hitEdge = hitTestEdge(edges, mx, my, W, H);
      if (hitEdge) {
        _tooltip.textContent = '';
        _tooltip.appendChild(buildEdgeTooltip(hitEdge));
        positionTooltip(_tooltip, wrap, e.clientX, e.clientY);
        _canvas.style.cursor = 'default';
        return;
      }
      _tooltip.style.display = 'none';
      _canvas.style.cursor = _dragging ? 'grabbing' : 'grab';
    };

    _boundMouseUp = () => {
      if (_dragging) {
        _dragging = false;
        if (_canvas) _canvas.style.cursor = 'grab';
      }
    };

    window.addEventListener('mousemove', _boundMouseMove);
    window.addEventListener('mouseup',   _boundMouseUp);

    _canvas.addEventListener('mouseleave', () => {
      if (_tooltip) _tooltip.style.display = 'none';
    });

    // ── Touch pan (1 doigt) + tap nœud ──
    _canvas.addEventListener('touchstart', (e) => {
      if (e.touches.length === 1) {
        const touch = e.touches[0];
        const [mx, my] = canvasCoords(touch);
        const hit = hitTestNode(nodes, mx, my, W, H);
        if (hit) {
          _tooltip.textContent = '';
          _tooltip.appendChild(buildNodeTooltip(hit));
          positionTooltip(_tooltip, wrap, touch.clientX, touch.clientY);
          setTimeout(() => { if (_tooltip) _tooltip.style.display = 'none'; }, 3000);
          return;
        }
        _dragging   = true;
        _dragStartX = touch.clientX;
        _dragStartY = touch.clientY;
        _dragOffX   = _offsetX;
        _dragOffY   = _offsetY;
      }
    }, { passive: true });

    _canvas.addEventListener('touchmove', (e) => {
      e.preventDefault();
      if (e.touches.length === 1 && _dragging) {
        _offsetX = _dragOffX + (e.touches[0].clientX - _dragStartX);
        _offsetY = _dragOffY + (e.touches[0].clientY - _dragStartY);
        if (_tooltip) _tooltip.style.display = 'none';
      } else if (e.touches.length === 2) {
        _dragging = false;
        const dx   = e.touches[0].clientX - e.touches[1].clientX;
        const dy   = e.touches[0].clientY - e.touches[1].clientY;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (_lastPinchDist !== null) {
          const factor   = dist / _lastPinchDist;
          const newScale = clamp(_scale * factor, 0.15, 6);
          const midX     = (e.touches[0].clientX + e.touches[1].clientX) / 2;
          const midY     = (e.touches[0].clientY + e.touches[1].clientY) / 2;
          const [mx, my] = canvasCoords({ clientX: midX, clientY: midY });
          const sf       = newScale / _scale;
          _offsetX = mx - W / 2 - sf * (mx - W / 2 - _offsetX);
          _offsetY = my - H / 2 - sf * (my - H / 2 - _offsetY);
          _scale   = newScale;
        }
        _lastPinchDist = dist;
      }
    }, { passive: false });

    _canvas.addEventListener('touchend', () => {
      _dragging      = false;
      _lastPinchDist = null;
    });

    // Clic sur nœud → sélection (mise en valeur des arêtes) + nudge
    _canvas.addEventListener('click', (e) => {
      if (_dragging) return;
      const [mx, my] = canvasCoords(e);
      const hit = hitTestNode(nodes, mx, my, W, H);
      if (hit) {
        selectedNode = (selectedNode === hit) ? null : hit;  // toggle
        hit.vx += (Math.random() - 0.5) * 6;
        hit.vy += (Math.random() - 0.5) * 6;
        frozen = false; tickCount = Math.max(0, MAX_TICKS - 60);
      } else {
        selectedNode = null;  // clic dans le vide = désélection
      }
    });

    _canvas.style.cursor = 'grab';

    btnIn.addEventListener('click', () => {
      _scale = clamp(_scale * 1.2, 0.15, 6);
    });
    btnOut.addEventListener('click', () => {
      _scale = clamp(_scale / 1.2, 0.15, 6);
    });
    btnReset.addEventListener('click', () => {
      _scale = 1; _offsetX = 0; _offsetY = 0;
      selectedNode = null;
    });

    const ro = window.ResizeObserver
      ? new ResizeObserver(() => {
          const dims = resizeCanvas();
          W = dims.W; H = dims.H;
          // Reset vélocités pour éviter l'explosion après resize
          nodes.forEach(n => { n.vx = 0; n.vy = 0; });
          frozen = false;
          tickCount = Math.max(0, MAX_TICKS - 80);
        })
      : null;
    if (ro) ro.observe(_canvas);
  });
}

export function unmount() {
  _mounted = false;
  if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
  if (_boundMouseMove) window.removeEventListener('mousemove', _boundMouseMove);
  if (_boundMouseUp)   window.removeEventListener('mouseup',   _boundMouseUp);
  _boundMouseMove = null;
  _boundMouseUp   = null;
  _canvas    = null;
  _tooltip   = null;
  _container = null;
  _dragging  = false;
}
