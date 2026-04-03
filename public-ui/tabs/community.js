// public-ui/tabs/community.js
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

const DEFAULT_COLOR  = '#06b6d4';
const MIN_RADIUS     = 8;
const MAX_RADIUS     = 22;
const MAX_TICKS      = 800;
const REPULSION      = 14000;
const ATTRACTION     = 0.018;
const DAMPING        = 0.82;
const CENTER_FORCE   = 0.008;
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
    n.x = clamp(n.x + n.vx, n.r + 2, W - n.r - 2);
    n.y = clamp(n.y + n.vy, n.r + 2, H - n.r - 2);
  });
}

function drawFrame(ctx, nodes, edges, W, H) {
  ctx.clearRect(0, 0, W, H);

  ctx.save();
  ctx.translate(_offsetX + W / 2, _offsetY + H / 2);
  ctx.scale(_scale, _scale);
  ctx.translate(-W / 2, -H / 2);

  // Arêtes
  edges.forEach(e => {
    const a = e._a, b = e._b;
    if (!a || !b) return;
    const w = Math.min(1 + (e.weight || 1) * 0.5, 5);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = 'rgba(255,255,255,0.22)';
    ctx.lineWidth   = w;
    ctx.stroke();

    // Poids au milieu de l'arête si > 1
    if ((e.weight || 1) > 1) {
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
    const color = n.color;

    // Cercle
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
    ctx.fillStyle = color + 'bb';
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.stroke();

    // Label avec fond semi-transparent pour lisibilité
    const label = n.name || n.id;
    const labelY = n.y + n.r + 14;
    ctx.font = '11px Inter, sans-serif';
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

    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillText(label, n.x, labelY);
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
  const nameEl = document.createElement('strong');
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

export function mount(el) {
  _container = el;
  _mounted   = true;
  _scale     = 1;
  _offsetX   = 0;
  _offsetY   = 0;
  el.textContent = '';

  const wrap = document.createElement('div');
  wrap.className = 'community-wrap glass';

  const titleEl = document.createElement('div');
  titleEl.className = 'community-title';
  titleEl.textContent = 'Communauté';
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
    .map(e => ({ ...e, _a: nodeById.get(e.source), _b: nodeById.get(e.target) }))
    .filter(e => e._a && e._b);

  // Légende
  const legend = document.createElement('div');
  legend.className = 'community-legend';
  const legendEntries = [
    ['Entités', DEFAULT_COLOR],
    ['Utilisateurs', '#5865f2'],
  ];
  const hasUsers = nodes.some(n => (n.labels||[]).some(l => ['User','Person'].includes(l)));
  (hasUsers ? legendEntries : legendEntries.slice(0, 1)).forEach(([label, color]) => {
    const item = document.createElement('div');
    item.className = 'community-legend-item';
    const dot = document.createElement('span');
    dot.className = 'community-legend-dot';
    dot.style.background = color;
    item.appendChild(dot);
    item.appendChild(document.createTextNode(label));
    legend.appendChild(item);
  });
  const edgeNote = document.createElement('div');
  edgeNote.style.cssText = 'font-size:0.7rem;color:rgba(255,255,255,0.3);margin-left:auto;';
  edgeNote.textContent = nodes.length + ' nœuds · ' + edges.length + ' liens';
  legend.appendChild(edgeNote);
  const hint = document.createElement('div');
  hint.style.cssText = 'font-size:0.65rem;color:rgba(255,255,255,0.2);margin-left:8px;white-space:nowrap;';
  hint.textContent = '🖱 molette = zoom · glisser = déplacer';
  legend.appendChild(hint);
  wrap.appendChild(legend);

  _canvas = document.createElement('canvas');
  _canvas.className = 'community-canvas';
  wrap.appendChild(_canvas);

  _tooltip = document.createElement('div');
  _tooltip.className = 'community-tooltip';
  _tooltip.style.display = 'none';
  wrap.appendChild(_tooltip);

  function resizeCanvas() {
    const rect = wrap.getBoundingClientRect();
    const W = Math.max(rect.width  || 700, 320);
    const H = Math.max(rect.height || 500, 340) - 90;
    _canvas.width  = W;
    _canvas.height = H;
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

    function animate() {
      if (!_mounted) return;
      if (!frozen) {
        tick(nodes, edges, W, H);
        tickCount++;
        if (tickCount >= MAX_TICKS) frozen = true;
      }
      drawFrame(ctx, nodes, edges, W, H);
      _rafId = requestAnimationFrame(animate);
    }
    animate();

    function canvasCoords(e) {
      const rect = _canvas.getBoundingClientRect();
      return [
        (e.clientX - rect.left) * (_canvas.width  / rect.width),
        (e.clientY - rect.top)  * (_canvas.height / rect.height),
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

    // Clic sur nœud → nudge pour relancer la simulation
    _canvas.addEventListener('click', (e) => {
      if (_dragging) return;
      const [mx, my] = canvasCoords(e);
      const hit = hitTestNode(nodes, mx, my, W, H);
      if (hit) {
        hit.vx += (Math.random() - 0.5) * 30;
        hit.vy += (Math.random() - 0.5) * 30;
        frozen = false; tickCount = 0;
      }
    });

    _canvas.style.cursor = 'grab';

    const ro = window.ResizeObserver
      ? new ResizeObserver(() => {
          const dims = resizeCanvas();
          W = dims.W; H = dims.H;
          frozen = false; tickCount = 0;
        })
      : null;
    if (ro) ro.observe(wrap);
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
