# Design : Améliorations mobile public-ui

**Date** : 2026-04-05  
**Scope** : `public-ui/index.html`, `public-ui/style.css`, `public-ui/app.js`, `public-ui/tabs/community.js`

---

## Contexte

Le site public (`public-ui/`) est une SPA vanilla JS avec 6 onglets (Statut, Chat, Galerie, Journal, Communauté, À propos). Sur mobile, deux problèmes majeurs :

1. **Navigation** : les boutons se replient en grille 3×2/2×3 via CSS flex-wrap — pas un vrai menu mobile.
2. **Graphe communauté** : canvas pur sans support touch (pas de pinch-to-zoom, pas de pan tactile), et rendu flou sur écrans haute densité (devicePixelRatio non pris en compte).

---

## Décisions

- **Menu mobile** : Bottom Nav (style app native)
- **Graphe mobile** : canvas conservé, touch complet (pinch + pan), boutons de contrôle flottants, fix DPR

---

## 1. Bottom Navigation mobile

### Comportement

- Breakpoint : `≤ 768px`
- Sur desktop : la `tab-nav` horizontale actuelle reste inchangée
- Sur mobile : la `tab-nav` est masquée (`display: none`) et remplacée par une `bottom-nav` fixée en bas de l'écran

### Structure HTML

Ajouter dans `index.html` après la `tab-nav` existante :

```html
<nav class="bottom-nav" id="bottom-nav">
  <!-- 4 tabs directs -->
  <button class="bnav-btn active" data-tab="status">
    <span class="bnav-icon">●</span>
    <span class="bnav-label">Statut</span>
  </button>
  <button class="bnav-btn" data-tab="chat">
    <span class="bnav-icon">◎</span>
    <span class="bnav-label">Chat</span>
  </button>
  <button class="bnav-btn" data-tab="gallery">
    <span class="bnav-icon">◫</span>
    <span class="bnav-label">Galerie</span>
  </button>
  <button class="bnav-btn" data-tab="journal">
    <span class="bnav-icon">◈</span>
    <span class="bnav-label">Journal</span>
  </button>
  <!-- bouton "Plus" -->
  <button class="bnav-btn bnav-more" id="bnav-more-btn">
    <span class="bnav-icon">···</span>
    <span class="bnav-label">Plus</span>
  </button>
</nav>

<!-- Sheet "Plus" -->
<div class="bnav-sheet-overlay" id="bnav-sheet-overlay"></div>
<div class="bnav-sheet" id="bnav-sheet">
  <div class="bnav-sheet-handle"></div>
  <button class="bnav-sheet-item" data-tab="community">
    <span class="bnav-sheet-icon">◉</span> Communauté
  </button>
  <button class="bnav-sheet-item" data-tab="about">
    <span class="bnav-sheet-icon">◇</span> À propos
  </button>
</div>
```

### CSS

- `bottom-nav` : `position: fixed; bottom: 0; left: 0; right: 0; height: 60px` — glassmorphism (`backdrop-filter: blur(20px)`, `rgba(255,255,255,0.04)`, border-top)
- `bnav-btn` : flex colonne, icône + label, `flex: 1`, état actif avec couleur accent
- `app-shell` : ajouter `padding-bottom: 72px` sur mobile pour éviter que le contenu passe derrière la barre
- Sheet : `position: fixed; bottom: 60px`, slide-up animé, overlay sombre pour fermer

### JS (`app.js`)

- Les `bnav-btn[data-tab]` utilisent le même handler que les `tab-btn` existants
- Le bouton "Plus" toggle la sheet (classe `open` sur `.bnav-sheet`)
- Clic sur l'overlay ou un item de la sheet ferme la sheet
- Synchronisation : quand un onglet devient actif (via desktop ou URL), les deux navs se synchronisent

---

## 2. Graphe communauté — mobile & qualité

### 2a. Fix devicePixelRatio (flou)

Dans `community.js`, la fonction `resizeCanvas()` doit tenir compte du DPR :

```js
function resizeCanvas() {
  const dpr  = window.devicePixelRatio || 1;
  const rect = wrap.getBoundingClientRect();
  const W    = Math.max(rect.width  || 700, 320);
  const H    = Math.max(rect.height || 500, 340) - 90;

  _canvas.width  = W * dpr;
  _canvas.height = H * dpr;
  _canvas.style.width  = W + 'px';
  _canvas.style.height = H + 'px';

  const ctx = _canvas.getContext('2d');
  ctx.scale(dpr, dpr);  // appelé une seule fois après resize

  return { W, H, dpr };
}
```

Le `drawFrame` et la simulation opèrent toujours en coordonnées CSS (W×H logiques) — seule la résolution physique change.

> **Attention** : `ctx.scale(dpr, dpr)` doit être appelé après chaque `clearRect` ou encapsulé dans `drawFrame` via `ctx.save/restore`.

### 2b. Support touch (pinch + pan)

Ajouter les handlers touch dans `_renderGraph` :

**Touch pan** :
```js
let _touchPanId = null;
canvas.addEventListener('touchstart', e => {
  if (e.touches.length === 1) {
    _dragging   = true;
    _dragStartX = e.touches[0].clientX;
    _dragStartY = e.touches[0].clientY;
    _dragOffX   = _offsetX;
    _dragOffY   = _offsetY;
    _touchPanId = e.touches[0].identifier;
  }
}, { passive: true });

canvas.addEventListener('touchmove', e => {
  e.preventDefault();
  if (e.touches.length === 1 && _dragging) {
    _offsetX = _dragOffX + (e.touches[0].clientX - _dragStartX);
    _offsetY = _dragOffY + (e.touches[0].clientY - _dragStartY);
  } else if (e.touches.length === 2) {
    // pinch handled separately
  }
}, { passive: false });

canvas.addEventListener('touchend', () => {
  _dragging = false;
});
```

**Pinch zoom** :
```js
let _lastPinchDist = null;
canvas.addEventListener('touchmove', e => {
  if (e.touches.length !== 2) return;
  const dx   = e.touches[0].clientX - e.touches[1].clientX;
  const dy   = e.touches[0].clientY - e.touches[1].clientY;
  const dist = Math.sqrt(dx*dx + dy*dy);
  if (_lastPinchDist !== null) {
    const factor   = dist / _lastPinchDist;
    const newScale = clamp(_scale * factor, 0.15, 6);
    // zoom centré entre les deux doigts
    const mx = (e.touches[0].clientX + e.touches[1].clientX) / 2;
    const my = (e.touches[0].clientY + e.touches[1].clientY) / 2;
    const [cmx, cmy] = canvasCoords({ clientX: mx, clientY: my });
    const sf = newScale / _scale;
    _offsetX = cmx - W/2 - sf * (cmx - W/2 - _offsetX);
    _offsetY = cmy - H/2 - sf * (cmy - H/2 - _offsetY);
    _scale   = newScale;
  }
  _lastPinchDist = dist;
}, { passive: false });

canvas.addEventListener('touchend', () => { _lastPinchDist = null; });
```

**Tap sur nœud** (remplace le hover) :
```js
canvas.addEventListener('touchstart', e => {
  if (e.touches.length !== 1) return;
  const [mx, my] = canvasCoords(e.touches[0]);
  const hit = hitTestNode(nodes, mx, my, W, H);
  if (hit) {
    _tooltip.textContent = '';
    _tooltip.appendChild(buildNodeTooltip(hit));
    positionTooltip(_tooltip, wrap, e.touches[0].clientX, e.touches[0].clientY);
    setTimeout(() => { _tooltip.style.display = 'none'; }, 3000);
  }
}, { passive: true });
```

### 2c. Boutons de contrôle flottants

Ajouter 3 boutons en overlay sur le canvas (coin bas-droite) :

```html
<div class="graph-controls">
  <button class="graph-ctrl-btn" id="graph-zoom-in">+</button>
  <button class="graph-ctrl-btn" id="graph-zoom-out">−</button>
  <button class="graph-ctrl-btn" id="graph-reset">⌖</button>
</div>
```

CSS : `position: absolute; bottom: 12px; right: 12px; display: flex; flex-direction: column; gap: 6px`

Chaque bouton modifie `_scale` / `_offsetX` / `_offsetY` avec la même logique que la molette.

### 2d. Hint adaptatif

Remplacer le hint statique `🖱 molette = zoom · glisser = déplacer` par une détection au rendu :

```js
hint.textContent = ('ontouchstart' in window)
  ? '👆 pincer = zoom · glisser = déplacer'
  : '🖱 molette = zoom · glisser = déplacer';
```

---

## Fichiers modifiés

| Fichier | Changements |
|---|---|
| `public-ui/index.html` | + bottom-nav HTML, + sheet HTML |
| `public-ui/style.css` | + styles bottom-nav, sheet, overlay, graph-controls ; responsive adjustments |
| `public-ui/app.js` | + sync bottom-nav, + handler sheet open/close |
| `public-ui/tabs/community.js` | fix DPR, touch pan, pinch zoom, tap tooltip, boutons contrôle, hint adaptatif |

---

## Non-inclus dans ce scope

- Swipe entre onglets (geste horizontal sur le contenu)
- Animations de transition entre onglets sur mobile
- Version liste du graphe en fallback
