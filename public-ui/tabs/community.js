// public-ui/tabs/community.js
// Force-directed social graph — pure canvas, no external libs

let _container = null;
let _canvas    = null;
let _tooltip   = null;
let _rafId     = null;
let _mounted   = false;

// API retourne des nœuds Graphiti/Neo4j : { id, name, summary, labels:["Entity"|...] }
// et des arêtes : { source, target, type, fact, source_name, target_name }

const DEFAULT_COLOR  = '#06b6d4';
const MIN_RADIUS     = 8;
const MAX_RADIUS     = 22;
const MAX_TICKS      = 600;
const REPULSION      = 4000;
const ATTRACTION     = 0.025;
const DAMPING        = 0.82;
const CENTER_FORCE   = 0.01;

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

// Couleur par type de nœud (labels Graphiti)
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

  // Attraction ressort sur les arêtes
  edges.forEach(e => {
    const a = e._a, b = e._b;
    if (!a || !b) return;
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) + 1;
    const force = ATTRACTION * dist;
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

  // Arêtes
  edges.forEach(e => {
    const a = e._a, b = e._b;
    if (!a || !b) return;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = 'rgba(255,255,255,0.22)';
    ctx.lineWidth   = 1.5;
    ctx.stroke();
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
    // Label
    ctx.fillStyle = 'rgba(255,255,255,0.8)';
    ctx.fillText(n.name || n.id, n.x, n.y + n.r + 13);
  });
}

function hitTest(nodes, mx, my) {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const dx = mx - n.x, dy = my - n.y;
    if (dx * dx + dy * dy <= n.r * n.r) return n;
  }
  return null;
}

export function mount(el) {
  _container = el;
  _mounted   = true;
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

  // Degré de chaque nœud (nombre d'arêtes connectées) → radius
  const degreeMap = new Map();
  rawNodes.forEach(n => degreeMap.set(n.id, 0));
  rawEdges.forEach(e => {
    degreeMap.set(e.source, (degreeMap.get(e.source) || 0) + 1);
    degreeMap.set(e.target, (degreeMap.get(e.target) || 0) + 1);
  });
  const degrees  = [...degreeMap.values()];
  const minDeg   = Math.min(...degrees);
  const maxDeg   = Math.max(...degrees);

  // Construire les nœuds enrichis
  const nodes = rawNodes.map(n => ({
    ...n,
    x: 0, y: 0, vx: 0, vy: 0, fx: 0, fy: 0,
    r:     nodeRadius(degreeMap.get(n.id) || 0, minDeg, maxDeg),
    color: nodeColor(n),
    name:  n.name || n.id,
  }));

  // Map id → node pour résolution rapide des arêtes
  const nodeById = new Map(nodes.map(n => [n.id, n]));

  // Construire les arêtes avec références résolues
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
  // n'afficher que les types présents
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
  wrap.appendChild(legend);

  // Canvas
  _canvas = document.createElement('canvas');
  _canvas.className = 'community-canvas';
  wrap.appendChild(_canvas);

  // Tooltip
  _tooltip = document.createElement('div');
  _tooltip.className = 'community-tooltip';
  _tooltip.style.display = 'none';
  wrap.appendChild(_tooltip);

  // Taille canvas
  function resizeCanvas() {
    const rect = wrap.getBoundingClientRect();
    const W = Math.max(rect.width  || 700, 320);
    const H = Math.max(rect.height || 500, 340) - 90;
    _canvas.width  = W;
    _canvas.height = H;
    return { W, H };
  }

  // Laisser le layout se stabiliser avant de lire les dimensions
  requestAnimationFrame(() => {
    let { W, H } = resizeCanvas();

    // Positions initiales en cercle pour éviter l'entassement au départ
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * Math.PI * 2;
      const r = Math.min(W, H) * 0.3;
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

    // Hover tooltip
    _canvas.addEventListener('mousemove', (e) => {
      const rect = _canvas.getBoundingClientRect();
      const scaleX = _canvas.width  / rect.width;
      const scaleY = _canvas.height / rect.height;
      const mx = (e.clientX - rect.left) * scaleX;
      const my = (e.clientY - rect.top)  * scaleY;
      const hit = hitTest(nodes, mx, my);
      if (hit) {
        _tooltip.textContent = '';
        const name = document.createElement('strong');
        name.textContent = hit.name;
        _tooltip.appendChild(name);
        if (hit.summary) {
          const sum = document.createElement('div');
          sum.style.cssText = 'font-size:0.7rem;color:rgba(255,255,255,0.5);margin-top:3px;max-width:220px;line-height:1.4;white-space:pre-wrap;';
          // Tronquer le résumé si trop long
          sum.textContent = hit.summary.length > 120 ? hit.summary.slice(0, 120) + '…' : hit.summary;
          _tooltip.appendChild(sum);
        }
        _tooltip.style.display = 'block';
        // Position relative au wrap
        const wRect = wrap.getBoundingClientRect();
        let left = e.clientX - wRect.left + 12;
        let top  = e.clientY - wRect.top  - 10;
        const tw = 220, th = 60;
        if (left + tw > wRect.width)  left = e.clientX - wRect.left - tw - 12;
        if (top  + th > wRect.height) top  = e.clientY - wRect.top  - th - 4;
        _tooltip.style.left = left + 'px';
        _tooltip.style.top  = top  + 'px';
        _canvas.style.cursor = 'pointer';
      } else {
        _tooltip.style.display = 'none';
        _canvas.style.cursor = 'default';
      }
    });

    _canvas.addEventListener('mouseleave', () => {
      _tooltip.style.display = 'none';
    });

    // Clic → nudge pour relancer la simulation
    _canvas.addEventListener('click', (e) => {
      const rect = _canvas.getBoundingClientRect();
      const scaleX = _canvas.width  / rect.width;
      const scaleY = _canvas.height / rect.height;
      const mx = (e.clientX - rect.left) * scaleX;
      const my = (e.clientY - rect.top)  * scaleY;
      const hit = hitTest(nodes, mx, my);
      if (hit) {
        hit.vx += (Math.random() - 0.5) * 30;
        hit.vy += (Math.random() - 0.5) * 30;
        frozen = false; tickCount = 0;
      }
    });

    // Resize
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
  _canvas  = null;
  _tooltip = null;
  _container = null;
}
