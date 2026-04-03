// public-ui/tabs/community.js
// Force-directed social graph — pure canvas, no external libs

let _container = null;
let _canvas    = null;
let _tooltip   = null;
let _rafId     = null;
let _mounted   = false;

const PLATFORM_COLORS = { discord: '#5865f2', twitch: '#9146ff' };
const DEFAULT_COLOR   = '#06b6d4';
const MIN_RADIUS      = 6;
const MAX_RADIUS      = 20;
const MAX_TICKS       = 500;
const REPULSION       = 3000;
const ATTRACTION      = 0.03;
const DAMPING         = 0.85;
const CENTER_FORCE    = 0.008;

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

function nodeRadius(count, minCount, maxCount) {
  if (maxCount === minCount) return (MIN_RADIUS + MAX_RADIUS) / 2;
  const t = (count - minCount) / (maxCount - minCount);
  return MIN_RADIUS + t * (MAX_RADIUS - MIN_RADIUS);
}

function buildGraph(data) {
  const nodes = (data.nodes || []).map(n => ({ ...n }));
  const edges = (data.edges || []);
  return { nodes, edges };
}

function initPositions(nodes, width, height) {
  nodes.forEach(n => {
    n.x  = Math.random() * (width  - 80) + 40;
    n.y  = Math.random() * (height - 80) + 40;
    n.vx = 0;
    n.vy = 0;
  });
}

function tick(nodes, edges, width, height) {
  const cx = width  / 2;
  const cy = height / 2;

  // Reset forces
  nodes.forEach(n => { n.fx = 0; n.fy = 0; });

  // Repulsion (Coulomb) — O(n²)
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist2 = dx * dx + dy * dy + 0.01;
      const force = REPULSION / dist2;
      const dist  = Math.sqrt(dist2);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.fx -= fx; a.fy -= fy;
      b.fx += fx; b.fy += fy;
    }
  }

  // Attraction (spring) along edges
  edges.forEach(e => {
    const a = nodes.find(n => n.id === e.source);
    const b = nodes.find(n => n.id === e.target);
    if (!a || !b) return;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
    const force = ATTRACTION * dist * (e.weight || 1);
    const fx = (dx / dist) * force;
    const fy = (dy / dist) * force;
    a.fx += fx; a.fy += fy;
    b.fx -= fx; b.fy -= fy;
  });

  // Centering force
  nodes.forEach(n => {
    n.fx += (cx - n.x) * CENTER_FORCE;
    n.fy += (cy - n.y) * CENTER_FORCE;
  });

  // Integrate
  nodes.forEach(n => {
    n.vx = (n.vx + n.fx) * DAMPING;
    n.vy = (n.vy + n.fy) * DAMPING;
    n.x  = clamp(n.x + n.vx, MAX_RADIUS, width  - MAX_RADIUS);
    n.y  = clamp(n.y + n.vy, MAX_RADIUS, height - MAX_RADIUS);
  });
}

function drawFrame(ctx, nodes, edges, radii, width, height) {
  ctx.clearRect(0, 0, width, height);

  // Draw edges
  edges.forEach(e => {
    const a = nodes.find(n => n.id === e.source);
    const b = nodes.find(n => n.id === e.target);
    if (!a || !b) return;
    const w = clamp((e.weight || 1) * 0.5, 0.5, 4);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth   = w;
    ctx.stroke();
  });

  // Draw nodes
  nodes.forEach(n => {
    const r     = radii.get(n.id);
    const color = PLATFORM_COLORS[n.platform] || DEFAULT_COLOR;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fillStyle = color + 'cc'; // 80% opacity
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.stroke();
  });
}

function hitTest(nodes, radii, mx, my) {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const r = radii.get(n.id);
    const dx = mx - n.x, dy = my - n.y;
    if (dx * dx + dy * dy <= r * r) return n;
  }
  return null;
}

function positionTooltip(tooltip, mx, my, canvasRect) {
  const offsetX = 14, offsetY = -10;
  let left = mx + offsetX;
  let top  = my + offsetY;
  // keep within viewport
  const tw = tooltip.offsetWidth  || 160;
  const th = tooltip.offsetHeight || 40;
  if (left + tw > canvasRect.right  - canvasRect.left) left = mx - tw - offsetX;
  if (top  + th > canvasRect.bottom - canvasRect.top)  top  = my - th - 4;
  tooltip.style.left = left + 'px';
  tooltip.style.top  = top  + 'px';
}

export function mount(el) {
  _container = el;
  _mounted   = true;
  el.textContent = '';

  const wrap = document.createElement('div');
  wrap.className = 'community-wrap glass';

  const title = document.createElement('div');
  title.className = 'community-title';
  title.textContent = 'Communauté';
  wrap.appendChild(title);

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

  const { nodes, edges } = buildGraph(data);

  // Legend
  const legend = document.createElement('div');
  legend.className = 'community-legend';
  [['Discord', '#5865f2'], ['Twitch', '#9146ff']].forEach(([label, color]) => {
    const item = document.createElement('div');
    item.className = 'community-legend-item';
    const dot = document.createElement('span');
    dot.className = 'community-legend-dot';
    dot.style.background = color;
    const lbl = document.createElement('span');
    lbl.textContent = label;
    item.appendChild(dot);
    item.appendChild(lbl);
    legend.appendChild(item);
  });
  wrap.appendChild(legend);

  // Canvas
  _canvas = document.createElement('canvas');
  _canvas.className = 'community-canvas';
  wrap.appendChild(_canvas);

  // Tooltip
  _tooltip = document.createElement('div');
  _tooltip.className = 'community-tooltip';
  _tooltip.style.display = 'none';
  _tooltip.style.position = 'absolute';
  wrap.appendChild(_tooltip);

  // Precompute radii
  const counts = nodes.map(n => n.message_count || 0);
  const minC   = Math.min(...counts);
  const maxC   = Math.max(...counts);
  const radii  = new Map(nodes.map(n => [n.id, nodeRadius(n.message_count || 0, minC, maxC)]));

  // Size canvas to container
  function resizeCanvas() {
    const rect = wrap.getBoundingClientRect();
    const W = Math.max(rect.width  || 600, 300);
    const H = Math.max(rect.height || 400, 300) - 80; // subtract legend+title
    _canvas.width  = W;
    _canvas.height = H;
    return { W, H };
  }

  let { W, H } = resizeCanvas();
  initPositions(nodes, W, H);

  const ctx = _canvas.getContext('2d');
  let tickCount = 0;
  let frozen    = false;

  function animate() {
    if (!_mounted) return;
    if (!frozen) {
      tick(nodes, edges, W, H);
      tickCount++;
      if (tickCount >= MAX_TICKS) frozen = true;
    }
    drawFrame(ctx, nodes, edges, radii, W, H);
    _rafId = requestAnimationFrame(animate);
  }

  animate();

  // Hover tooltip via mousemove on canvas
  _canvas.addEventListener('mousemove', (e) => {
    const rect = _canvas.getBoundingClientRect();
    const mx   = e.clientX - rect.left;
    const my   = e.clientY - rect.top;
    const hit  = hitTest(nodes, radii, mx, my);
    if (hit) {
      _tooltip.textContent = '';
      const namePart = document.createElement('strong');
      namePart.textContent = hit.label || hit.id;
      _tooltip.appendChild(namePart);
      _tooltip.appendChild(document.createTextNode(' — ' + (hit.message_count || 0) + ' msg'));
      _tooltip.style.display = 'block';
      positionTooltip(_tooltip, mx, my, { left: 0, top: 0, right: W, bottom: H });
      _canvas.style.cursor = 'pointer';
    } else {
      _tooltip.style.display = 'none';
      _canvas.style.cursor = 'default';
    }
  });

  _canvas.addEventListener('mouseleave', () => {
    _tooltip.style.display = 'none';
    _canvas.style.cursor = 'default';
  });

  // Click on node to unfreeze (allow re-simulation)
  _canvas.addEventListener('click', (e) => {
    const rect = _canvas.getBoundingClientRect();
    const mx   = e.clientX - rect.left;
    const my   = e.clientY - rect.top;
    const hit  = hitTest(nodes, radii, mx, my);
    if (hit) {
      // Nudge the node to kick it free
      hit.vx += (Math.random() - 0.5) * 20;
      hit.vy += (Math.random() - 0.5) * 20;
      frozen    = false;
      tickCount = 0;
    }
  });

  // Resize handler
  window.addEventListener('resize', () => {
    const dims = resizeCanvas();
    W = dims.W; H = dims.H;
    frozen    = false;
    tickCount = 0;
  });
}

export function unmount() {
  _mounted = false;
  if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
  _canvas  = null;
  _tooltip = null;
  _container = null;
}
