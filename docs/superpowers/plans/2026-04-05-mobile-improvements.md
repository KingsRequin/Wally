# Mobile Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une vraie bottom nav mobile (6 onglets, 4 directs + sheet "Plus") et améliorer le graphe communauté sur mobile (DPR fix, touch pan, pinch zoom, tap tooltip, boutons de contrôle).

**Architecture:** Vanilla JS/CSS SPA, pas de framework. La bottom-nav est ajoutée en HTML dans `index.html` et pilotée par `app.js` via `location.hash` (même routing existant). Le graphe canvas dans `community.js` reçoit le support touch et le fix DPR sans modifier son architecture force-directed.

**Tech Stack:** HTML5, CSS3, Vanilla JS ES modules, Canvas 2D API

---

## Fichiers modifiés

| Fichier | Rôle |
|---|---|
| `public-ui/index.html` | Ajout bottom-nav + sheet "Plus" |
| `public-ui/style.css` | Styles bottom-nav, sheet overlay, graph-controls, padding mobile |
| `public-ui/app.js` | Sync bottom-nav avec router hash, ouverture/fermeture sheet |
| `public-ui/tabs/community.js` | DPR fix, touch pan, pinch zoom, tap tooltip, boutons +/−/⌖, hint adaptatif |

Pas de framework de test disponible pour le frontend vanilla — chaque tâche inclut une vérification manuelle dans le navigateur.

---

## Task 1 : HTML — bottom-nav + sheet "Plus"

**Files:**
- Modify: `public-ui/index.html`

- [ ] **Step 1 : Ajouter la bottom-nav et la sheet dans index.html**

Insérer entre `</nav>` (fin de la tab-nav existante, ligne 39) et `<main id="tab-content">` :

```html
    <nav class="bottom-nav" id="bottom-nav">
      <button class="bnav-btn active" data-tab="status">
        <span class="bnav-icon">&#9679;</span>
        <span class="bnav-label">Statut</span>
      </button>
      <button class="bnav-btn" data-tab="chat">
        <span class="bnav-icon">&#9678;</span>
        <span class="bnav-label">Chat</span>
      </button>
      <button class="bnav-btn" data-tab="gallery">
        <span class="bnav-icon">&#9647;</span>
        <span class="bnav-label">Galerie</span>
      </button>
      <button class="bnav-btn" data-tab="journal">
        <span class="bnav-icon">&#9672;</span>
        <span class="bnav-label">Journal</span>
      </button>
      <button class="bnav-btn bnav-more-btn" id="bnav-more-btn">
        <span class="bnav-icon">&#xB7;&#xB7;&#xB7;</span>
        <span class="bnav-label">Plus</span>
      </button>
    </nav>

    <div class="bnav-sheet-overlay" id="bnav-sheet-overlay"></div>
    <div class="bnav-sheet" id="bnav-sheet">
      <div class="bnav-sheet-handle"></div>
      <button class="bnav-sheet-item" data-tab="community">
        <span class="bnav-sheet-icon">&#9673;</span> Communauté
      </button>
      <button class="bnav-sheet-item" data-tab="about">
        <span class="bnav-sheet-icon">&#9671;</span> À propos
      </button>
    </div>
```

- [ ] **Step 2 : Vérification**

Ouvrir en desktop → rien ne change (bottom-nav masquée par CSS à venir).

- [ ] **Step 3 : Commit**

```bash
git add public-ui/index.html
git commit -m "feat(mobile): add bottom-nav and sheet HTML"
```

---

## Task 2 : CSS — bottom-nav, sheet, ajustements

**Files:**
- Modify: `public-ui/style.css`

- [ ] **Step 1 : Ajouter les styles à la fin du fichier (après la ligne 688)**

```css
/* ── Bottom Nav (mobile) ── */
.bottom-nav {
  display: none;
}

@media (max-width: 768px) {
  /* Masquer la tab-nav desktop */
  .tab-nav { display: none; }

  /* Afficher la bottom-nav */
  .bottom-nav {
    display: flex;
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: 62px;
    background: rgba(10, 10, 15, 0.85);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    z-index: 100;
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }

  /* Espace pour ne pas masquer le contenu */
  .app-shell {
    padding-bottom: 74px;
  }

  .bnav-btn {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    background: transparent;
    border: none;
    cursor: pointer;
    color: rgba(255, 255, 255, 0.35);
    transition: color 0.2s;
    padding: 0;
    min-width: 0;
  }
  .bnav-btn:hover,
  .bnav-btn.active { color: var(--accent); }

  .bnav-icon {
    font-size: 1.05rem;
    line-height: 1;
  }
  .bnav-label {
    font-size: 0.62rem;
    font-weight: 500;
    white-space: nowrap;
  }

  /* Sheet overlay */
  .bnav-sheet-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    z-index: 98;
  }
  .bnav-sheet-overlay.open { display: block; }

  /* Sheet */
  .bnav-sheet {
    position: fixed;
    bottom: 62px;
    left: 0; right: 0;
    background: rgba(15, 15, 22, 0.97);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom: none;
    border-radius: 16px 16px 0 0;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    z-index: 99;
    padding: 8px 0 12px;
    transform: translateY(100%);
    transition: transform 0.25s cubic-bezier(0.32, 0.72, 0, 1);
  }
  .bnav-sheet.open { transform: translateY(0); }

  .bnav-sheet-handle {
    width: 36px; height: 4px;
    background: rgba(255, 255, 255, 0.15);
    border-radius: 2px;
    margin: 0 auto 12px;
  }

  .bnav-sheet-item {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 14px 24px;
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.75);
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    text-align: left;
    transition: background 0.15s, color 0.15s;
  }
  .bnav-sheet-item:hover { background: rgba(255,255,255,0.05); color: var(--accent); }
  .bnav-sheet-item.active { color: var(--accent); }

  .bnav-sheet-icon { font-size: 1rem; }
}

/* ── Graph control buttons ── */
.graph-controls {
  position: absolute;
  bottom: 12px;
  right: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  z-index: 5;
}
.graph-ctrl-btn {
  width: 34px;
  height: 34px;
  background: rgba(15, 15, 22, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.65);
  font-size: 1.1rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(8px);
  transition: background 0.15s, color 0.15s;
  line-height: 1;
  user-select: none;
}
.graph-ctrl-btn:hover { background: rgba(6,182,212,0.15); color: var(--accent); }
```

- [ ] **Step 2 : Vérifier sur mobile (DevTools viewport 390px)**

- Bottom-nav visible en bas, tab-nav desktop masquée
- Contenu pas masqué par la barre

- [ ] **Step 3 : Commit**

```bash
git add public-ui/style.css
git commit -m "feat(mobile): bottom-nav, sheet CSS + graph control button styles"
```

---

## Task 3 : JS — router bottom-nav + sheet

**Files:**
- Modify: `public-ui/app.js`

- [ ] **Step 1 : Ajouter `syncNav()` et `closeSheet()` avant `route()`**

Dans `app.js`, avant la fonction `route()` (ligne 62), insérer :

```js
function syncNav(tabName) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.bnav-btn[data-tab]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.bnav-sheet-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  const sheetTabs = ['community', 'about'];
  const moreBtn = document.getElementById('bnav-more-btn');
  if (moreBtn) moreBtn.classList.toggle('active', sheetTabs.includes(tabName));
}

function closeSheet() {
  document.getElementById('bnav-sheet')?.classList.remove('open');
  document.getElementById('bnav-sheet-overlay')?.classList.remove('open');
}
```

- [ ] **Step 2 : Modifier `route()` pour utiliser `syncNav` et `closeSheet`**

Remplacer le contenu de la fonction `route()` existante (lignes 62–83) par :

```js
function route() {
  const hash = location.hash.slice(1) || 'status';
  const tabName = TABS[hash] ? hash : 'status';

  if (currentTab && TABS[currentTab]?.unmount) {
    TABS[currentTab].unmount();
  }

  syncNav(tabName);
  closeSheet();

  const content = document.getElementById('tab-content');
  content.style.animation = 'none';
  content.offsetHeight;
  content.style.animation = '';

  TABS[tabName].mount(content);
  currentTab = tabName;
}
```

- [ ] **Step 3 : Remplacer le bloc "Nav button clicks" (lignes 86–90) par la version bottom-nav**

Remplacer :

```js
// Nav button clicks
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    location.hash = btn.dataset.tab;
  });
});
```

Par :

```js
// Desktop nav clicks
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => { location.hash = btn.dataset.tab; });
});

// Mobile bottom-nav clicks
document.querySelectorAll('.bnav-btn[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => { location.hash = btn.dataset.tab; });
});

// Sheet items clicks
document.querySelectorAll('.bnav-sheet-item').forEach(btn => {
  btn.addEventListener('click', () => { location.hash = btn.dataset.tab; });
});

// "Plus" button — toggle sheet
const _moreBtn = document.getElementById('bnav-more-btn');
const _sheet   = document.getElementById('bnav-sheet');
const _sheetOverlay = document.getElementById('bnav-sheet-overlay');
if (_moreBtn && _sheet) {
  _moreBtn.addEventListener('click', () => {
    const isOpen = _sheet.classList.contains('open');
    if (isOpen) {
      closeSheet();
    } else {
      _sheet.classList.add('open');
      _sheetOverlay?.classList.add('open');
    }
  });
}
if (_sheetOverlay) {
  _sheetOverlay.addEventListener('click', closeSheet);
}
```

- [ ] **Step 4 : Vérifier en mobile DevTools (390px)**

- Tap Statut/Chat/Galerie/Journal → onglet change, bouton actif en cyan
- Tap "Plus" → sheet slide-up
- Tap Communauté → onglet change, sheet se ferme, "Plus" reste en surbrillance
- Tap overlay → sheet se ferme
- Desktop → routing normal, bottom-nav invisible

- [ ] **Step 5 : Commit**

```bash
git add public-ui/app.js
git commit -m "feat(mobile): wire bottom-nav router and sheet toggle"
```

---

## Task 4 : Graphe — fix DPR (anti-flou)

**Files:**
- Modify: `public-ui/tabs/community.js`

- [ ] **Step 1 : Remplacer la fonction `resizeCanvas()` (ligne ~362)**

Localiser :
```js
  function resizeCanvas() {
    const rect = wrap.getBoundingClientRect();
    const W = Math.max(rect.width  || 700, 320);
    const H = Math.max(rect.height || 500, 340) - 90;
    _canvas.width  = W;
    _canvas.height = H;
    return { W, H };
  }
```

Remplacer par :

```js
  function resizeCanvas() {
    const dpr  = window.devicePixelRatio || 1;
    const rect = wrap.getBoundingClientRect();
    const W    = Math.max(rect.width  || 700, 320);
    const H    = Math.max(rect.height || 500, 340) - 90;

    _canvas.width  = Math.round(W * dpr);
    _canvas.height = Math.round(H * dpr);
    _canvas.style.width  = W + 'px';
    _canvas.style.height = H + 'px';

    const ctx = _canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    return { W, H };
  }
```

> `ctx.setTransform(dpr, 0, 0, dpr, 0, 0)` réinitialise la matrice et applique le scale DPR. `drawFrame` opère en coordonnées CSS (W×H logiques) via `ctx.save/restore` — aucun changement dans `drawFrame` nécessaire.

- [ ] **Step 2 : Vérifier sur mobile (vrai téléphone ou DevTools device mode)**

Canvas net, non pixelisé. Zoom/pan fonctionnels.

- [ ] **Step 3 : Commit**

```bash
git add public-ui/tabs/community.js
git commit -m "fix(graph): apply devicePixelRatio for crisp canvas on HiDPI screens"
```

---

## Task 5 : Graphe — touch pan + pinch zoom + tap tooltip

**Files:**
- Modify: `public-ui/tabs/community.js`

- [ ] **Step 1 : Ajouter la variable `_lastPinchDist` en haut du fichier**

Après la ligne `let _boundMouseUp   = null;` (ligne 17), ajouter :

```js
let _lastPinchDist = null;
```

- [ ] **Step 2 : Ajouter les event listeners touch dans `_renderGraph`**

Localiser le commentaire `// Clic sur nœud → nudge` (ligne ~479) et insérer avant lui les blocs suivants. Note : `canvasCoords` et `hitTestNode` sont déjà définis dans le même scope.

```js
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
```

- [ ] **Step 3 : Vérifier sur mobile (DevTools touch simulation)**

- 1 doigt glissé → graphe se déplace
- 2 doigts écartés/rapprochés → zoom centré entre les doigts
- Tap sur un nœud → tooltip 3s

- [ ] **Step 4 : Commit**

```bash
git add public-ui/tabs/community.js
git commit -m "feat(graph): touch pan, pinch zoom, tap tooltip on mobile"
```

---

## Task 6 : Graphe — boutons de contrôle + hint adaptatif

**Files:**
- Modify: `public-ui/tabs/community.js`

- [ ] **Step 1 : Ajouter les boutons de contrôle après `wrap.appendChild(_canvas)`**

Localiser la ligne `wrap.appendChild(_canvas);` (dans `_renderGraph`, vers la ligne 355) et ajouter après :

```js
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
```

- [ ] **Step 2 : Brancher les boutons dans le bloc `requestAnimationFrame`**

Après la ligne `_canvas.style.cursor = 'grab';` (dans le callback `requestAnimationFrame`), ajouter :

```js
    btnIn.addEventListener('click', () => {
      _scale = clamp(_scale * 1.2, 0.15, 6);
      frozen = false; tickCount = 0;
    });
    btnOut.addEventListener('click', () => {
      _scale = clamp(_scale / 1.2, 0.15, 6);
      frozen = false; tickCount = 0;
    });
    btnReset.addEventListener('click', () => {
      _scale = 1; _offsetX = 0; _offsetY = 0;
      frozen = false; tickCount = 0;
    });
```

- [ ] **Step 3 : Remplacer le hint statique par un hint adaptatif**

Localiser :

```js
  hint.textContent = '🖱 molette = zoom · glisser = déplacer';
```

Remplacer par :

```js
  hint.textContent = ('ontouchstart' in window)
    ? '\uD83D\uDC46 pincer = zoom \xB7 glisser = d\xE9placer'
    : '\uD83D\uDDB1\uFE0F molette = zoom \xB7 glisser = d\xE9placer';
```

- [ ] **Step 4 : Vérifier**

- Boutons +/−/⌖ visibles en bas à droite du canvas
- \+ agrandit, − réduit, ⌖ recentre
- Hint adaptatif selon device

- [ ] **Step 5 : Commit**

```bash
git add public-ui/tabs/community.js
git commit -m "feat(graph): zoom control buttons and adaptive hint"
```

---

## Task 7 : Vérification finale cross-device

- [ ] **Step 1 : Desktop Chrome (1280px)**
  - Tab-nav horizontale visible, bottom-nav absente
  - Graphe net, molette zoom, drag pan, tooltip hover fonctionnels

- [ ] **Step 2 : Mobile Chrome DevTools (390px × 844px)**
  - Bottom-nav visible, 4 onglets + "Plus"
  - Tap "Plus" → sheet slide-up avec Communauté + À propos
  - Graphe net (non pixelisé), touch pan 1 doigt, pinch zoom 2 doigts, tap nœud → tooltip 3s

- [ ] **Step 3 : Vérifier que `community-wrap` a bien `position: relative`**

Dans `style.css`, la règle `.community-wrap` doit contenir `position: relative`. Si ce n'est pas le cas, l'ajouter (nécessaire pour le positionnement absolu des boutons `.graph-controls`).

- [ ] **Step 4 : Commit final si ajustements**

```bash
git add -p
git commit -m "fix(mobile): post-review adjustments"
```
