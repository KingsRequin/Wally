# Dashboard Redesign — Neo-Brutalism Warm Pastel — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesigner le dashboard Wally de dark neo-brutalism vers un style light cream + pastel colorblock, sans changer l'architecture ni les routes backend.

**Architecture:** Modification de 3 fichiers statiques uniquement — `style.css` (réécriture complète), `index.html` (ajout de classes couleur sur les cards), `app.js` (mise à jour des couleurs inline dans les templates JS et du canvas). Aucun backend touché.

**Tech Stack:** CSS3 custom properties, Vanilla JS, HTML5 canvas (graph émotions existant)

**Spec:** `docs/superpowers/specs/2026-03-17-dashboard-redesign-design.md`

---

## Chunk 1: Réécriture CSS complète

### Task 1: Mettre à jour les variables CSS (`:root`)

**Files:**
- Modify: `bot/dashboard/static/style.css` (lines 1–25)

- [ ] **Step 1: Remplacer le bloc `:root` et le commentaire d'en-tête**

> ⚠️ Remplacer uniquement les lignes 1–25 (du commentaire jusqu'au `}` fermant de `:root`). La règle `* { box-sizing: border-box; margin: 0; padding: 0; }` qui suit immédiatement doit être **conservée**.

```css
/* Light Neo-Brutalism — Wally Dashboard
   Règles fondamentales :
   - Bordures épaisses 2.5px solid #111
   - Ombres dures sans flou : box-shadow 4px 4px 0px #111
   - Zéro dégradé, zéro flou
   - Border-radius : 14px (cards/header), 10px (buttons), 8px (inputs), 4px (gauges)
*/

:root {
  --bg: #fafaf8;
  --bg-alt: #f0ede8;
  --card: #ffffff;
  --border: #111111;
  --shadow: 4px 4px 0px #111111;
  --shadow-sm: 2px 2px 0px #111111;
  --text: #111111;
  --text-muted: #666666;
  --font: 'Courier New', Courier, monospace;
  --radius: 14px;       /* cards, header, modal, log stream */
  --radius-sm: 8px;     /* inputs, selects, mode toggle, memory items */
  --radius-btn: 10px;   /* buttons */
  --radius-tab: 6px;    /* badges pill */
  --radius-xs: 4px;     /* gauge tracks */

  /* Emotion colors */
  --c-anger:    #e63946;
  --c-joy:      #ffd60a;
  --c-curiosity:#2dc653;
  --c-sadness:  #0096c7;
  --c-boredom:  #9ca3af;

  /* Card accent colors */
  --card-pink:   #ff6b9d;
  --card-teal:   #4ecdc4;
  --card-yellow: #ffe66d;
  --card-aqua:   #a8edea;
  --card-mint:   #b7f5c8;

  /* Status */
  --c-online:  #16a34a;
  --c-offline: #dc2626;
}
```

- [ ] **Step 2: Mettre à jour `body`**

```css
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  min-height: 100vh;
}
```

- [ ] **Step 3: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): update CSS variables to light cream palette"
```

---

### Task 2: Header et mode toggle

**Files:**
- Modify: `bot/dashboard/static/style.css` (section header)

- [ ] **Step 1: Remplacer la section `/* ── Header ──` jusqu'à la fin du `.mode-btn:hover`**

```css
/* ── Header ──────────────────────────────────────────────────────────────── */

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 3px solid var(--border);
  box-shadow: 0 2px 0 var(--border);
  background: var(--card);
  position: sticky;
  top: 0;
  z-index: 100;
}

.logo {
  font-size: 1.4rem;
  font-weight: 900;
  letter-spacing: 4px;
  color: var(--text);
}

.logo .logo-accent { color: var(--card-pink); }

.mode-toggle {
  display: flex;
}

.mode-btn {
  padding: 6px 16px;
  border: 2.5px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.1s, transform 0.1s;
}

.mode-btn:first-child { border-radius: var(--radius-sm) 0 0 var(--radius-sm); border-right-width: 1.5px; }
.mode-btn:last-child  { border-radius: 0 var(--radius-sm) var(--radius-sm) 0; border-left-width: 1.5px; }

.mode-btn.active {
  background: var(--border);
  color: var(--bg);
  box-shadow: none;
}

.mode-btn:hover:not(.active) {
  box-shadow: none;
  transform: translate(2px, 2px);
}
```

- [ ] **Step 2: Mettre à jour le HTML — logo avec classe accent**

Dans `bot/dashboard/static/index.html`, remplacer :
```html
<div class="logo">WALLY</div>
```
par :
```html
<div class="logo">W<span class="logo-accent">A</span>LLY 🤖</div>
```

- [ ] **Step 3: Commit**

```bash
git add bot/dashboard/static/style.css bot/dashboard/static/index.html
git commit -m "style(dashboard): restyle header and mode toggle — light bg, pill toggle"
```

---

### Task 3: Tab navigation

**Files:**
- Modify: `bot/dashboard/static/style.css` (section tabs)

- [ ] **Step 1: Remplacer la section `/* ── Tab navigation ──`**

```css
/* ── Tab navigation ──────────────────────────────────────────────────────── */

nav.tabs {
  display: flex;
  border-bottom: 3px solid var(--border);
  overflow-x: auto;
  scrollbar-width: none;
  background: var(--bg);
}

nav.tabs::-webkit-scrollbar { display: none; }

.tab-btn {
  padding: 10px 18px;
  border: none;
  border-right: 1px solid #ddd;
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.8rem;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.1s, color 0.1s;
}

.tab-btn.active {
  background: var(--border);
  color: var(--bg);
}

.tab-btn:hover:not(.active) {
  background: #eee;
  color: var(--text);
}

.tab-btn.disabled {
  color: #bbb;
  cursor: not-allowed;
}
```

- [ ] **Step 2: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): restyle tab navigation — dark active, light hover"
```

---

### Task 4: Cards — base + classes couleur

**Files:**
- Modify: `bot/dashboard/static/style.css` (section cards)

- [ ] **Step 1: Remplacer la section `/* ── Cards ──`**

```css
/* ── Cards ───────────────────────────────────────────────────────────────── */

.card {
  background: var(--card);
  border: 2.5px solid var(--border);
  box-shadow: var(--shadow);
  border-radius: var(--radius);
  padding: 16px;
  margin-bottom: 16px;
}

/* Carte colorée : surcharge uniquement le background */
.card-pink   { background: var(--card-pink); }
.card-teal   { background: var(--card-teal); }
.card-yellow { background: var(--card-yellow); }
.card-aqua   { background: var(--card-aqua); }
.card-mint   { background: var(--card-mint); }

.card-title {
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 2px;
  color: rgba(0, 0, 0, 0.5);
  text-transform: uppercase;
  margin-bottom: 10px;
}

.card-value {
  font-size: 1.8rem;
  font-weight: 900;
  color: var(--text);
}

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }

@media (max-width: 600px) {
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
}
```

- [ ] **Step 2: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): add card color utility classes (pink/teal/yellow/aqua/mint)"
```

---

### Task 5: Status dots, gauges émotions, sliders

**Files:**
- Modify: `bot/dashboard/static/style.css` (sections dots + gauges)

- [ ] **Step 1: Remplacer les sections status dots + gauges + sliders + emotion summary**

```css
/* ── Status dots ─────────────────────────────────────────────────────────── */

.status-dot {
  display: inline-block;
  width: 10px; height: 10px;
  border-radius: 50%;
  margin-right: 8px;
}

.status-dot.online  { background: var(--c-online); box-shadow: 0 0 6px var(--c-online); }
.status-dot.offline { background: var(--c-offline); }

/* ── Emotion gauges ──────────────────────────────────────────────────────── */

.emotion-row {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  gap: 10px;
}

.emotion-label {
  width: 80px;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 1px;
  flex-shrink: 0;
}

.gauge-track {
  flex: 1;
  height: 10px;
  background: rgba(0, 0, 0, 0.12);
  border: 1.5px solid rgba(0, 0, 0, 0.15);
  border-radius: var(--radius-xs);
  position: relative;
  overflow: hidden;
}

.gauge-fill {
  height: 100%;
  width: 0%;
  border-radius: calc(var(--radius-xs) - 1px);
  transition: width 1s ease;
}

.gauge-fill.anger    { background: var(--c-anger); }
.gauge-fill.joy      { background: var(--c-joy); }
.gauge-fill.curiosity{ background: var(--c-curiosity); }
.gauge-fill.sadness  { background: var(--c-sadness); }
.gauge-fill.boredom  { background: var(--c-boredom); }

.gauge-val {
  width: 38px;
  text-align: right;
  font-size: 0.8rem;
  font-weight: 700;
  flex-shrink: 0;
  color: var(--text);
}

/* ── Editable sliders (admin) ────────────────────────────────────────────── */

.emotion-slider {
  flex: 1;
  accent-color: var(--border);
  cursor: pointer;
}

/* ── Emotion summary ─────────────────────────────────────────────────────── */

.emotion-summary {
  font-size: 0.9rem;
  color: rgba(0, 0, 0, 0.55);
  font-style: italic;
  margin-top: 12px;
  min-height: 1.4em;
}
```

- [ ] **Step 2: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): restyle status dots and emotion gauges — light bg, 10px height"
```

---

### Task 6: Graph container, boutons, inputs

**Files:**
- Modify: `bot/dashboard/static/style.css` (sections graph + buttons + inputs)

- [ ] **Step 1: Remplacer la section `/* ── Canvas graph ──`**

```css
/* ── Canvas graph ────────────────────────────────────────────────────────── */

.graph-container {
  border: 2.5px solid var(--border);
  box-shadow: var(--shadow);
  border-radius: var(--radius);
  background: var(--card);
  padding: 4px;
  margin-top: 16px;
}

#emotionCanvas { display: block; width: 100%; }
```

- [ ] **Step 2: Remplacer la section `/* ── Buttons ──`**

```css
/* ── Buttons ─────────────────────────────────────────────────────────────── */

.btn {
  padding: 8px 18px;
  border: 2.5px solid var(--border);
  border-radius: var(--radius-btn);
  background: var(--card);
  color: var(--text);
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.85rem;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.1s, transform 0.1s;
}

.btn:hover {
  box-shadow: none;
  transform: translate(3px, 3px);
}

.btn:active { box-shadow: none; transform: translate(4px, 4px); }

.btn.active {
  background: var(--border);
  color: var(--bg);
  box-shadow: none;
}

.btn-danger  { background: #fee2e2; border-color: var(--c-offline);  color: var(--c-offline); }
.btn-success { background: var(--card-mint); }
.btn-info    { background: var(--card-aqua); }
```

- [ ] **Step 3: Remplacer la section `/* ── Inputs & Selects ──`**

```css
/* ── Inputs & Selects ────────────────────────────────────────────────────── */

.field-group { margin-bottom: 14px; }

.field-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 4px;
}

input[type="text"], input[type="number"], input[type="password"], select, textarea {
  width: 100%;
  padding: 7px 10px;
  background: var(--card);
  border: 2px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-family: var(--font);
  font-size: 0.9rem;
  box-shadow: var(--shadow-sm);
  outline: none;
}

input[type="range"] {
  accent-color: var(--border);
  width: 100%;
}
```

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): restyle graph, buttons, inputs — rounded, light bg"
```

---

### Task 7: Stream badges, logs, config, modal, toasts

**Files:**
- Modify: `bot/dashboard/static/style.css` (sections stream + logs + config + modal + toasts)

- [ ] **Step 1: Remplacer la section `/* ── Stream card ──`**

```css
/* ── Stream card ─────────────────────────────────────────────────────────── */

.stream-live-badge {
  display: inline-block;
  padding: 2px 10px;
  background: var(--card-pink);
  color: var(--text);
  font-weight: 900;
  font-size: 0.75rem;
  letter-spacing: 2px;
  border: 2px solid var(--border);
  border-radius: var(--radius-tab);
  margin-bottom: 8px;
}

.stream-offline-badge {
  display: inline-block;
  padding: 2px 10px;
  background: #eee;
  color: var(--text-muted);
  font-weight: 900;
  font-size: 0.75rem;
  letter-spacing: 2px;
  border: 2px solid #999;
  border-radius: var(--radius-tab);
  margin-bottom: 8px;
}
```

- [ ] **Step 2: Remplacer la section `/* ── Logs ──`**

```css
/* ── Logs ────────────────────────────────────────────────────────────────── */

.log-controls { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }

.log-stream {
  background: var(--card);
  border: 2.5px solid var(--border);
  box-shadow: var(--shadow);
  border-radius: var(--radius);
  height: 400px;
  overflow-y: auto;
  padding: 10px;
  font-size: 0.78rem;
  line-height: 1.5;
}

.log-entry { margin-bottom: 2px; }
.log-entry.INFO    { color: #555; }
.log-entry.WARNING { color: #b45309; font-weight: 700; }
.log-entry.ERROR   { color: var(--c-offline); font-weight: 700; }
.log-entry.hidden  { display: none; }
```

- [ ] **Step 3: Remplacer la section `/* ── Config sections ──`**

```css
/* ── Config sections ─────────────────────────────────────────────────────── */

.config-section { margin-bottom: 24px; }

.config-section-title {
  font-size: 0.75rem;
  font-weight: 900;
  letter-spacing: 3px;
  color: var(--text);
  text-transform: uppercase;
  border-bottom: 2px solid var(--border);
  padding-bottom: 4px;
  margin-bottom: 14px;
}
```

- [ ] **Step 4: Remplacer la section `/* ── Auth modal ──`**

```css
/* ── Auth modal ──────────────────────────────────────────────────────────── */

.modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 1000;
  align-items: center;
  justify-content: center;
}

.modal-overlay.visible { display: flex; }

.modal {
  background: var(--card);
  border: 2.5px solid var(--border);
  box-shadow: 8px 8px 0px var(--border);
  border-radius: var(--radius);
  padding: 24px;
  width: 340px;
  max-width: 90vw;
}

.modal h2 {
  font-size: 1.1rem;
  font-weight: 900;
  letter-spacing: 2px;
  margin-bottom: 16px;
  color: var(--text);
}
```

- [ ] **Step 5: Remplacer la section `/* ── Toasts ──`**

```css
/* ── Toasts ──────────────────────────────────────────────────────────────── */

#toast-container {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  padding: 10px 16px;
  border: 2.5px solid var(--border);
  border-radius: var(--radius-btn);
  box-shadow: var(--shadow);
  font-weight: 700;
  font-size: 0.85rem;
  animation: toast-in 0.15s ease;
  max-width: 320px;
  color: var(--text);
}

.toast.success { background: var(--card-mint); }
.toast.error   { background: #fee2e2; border-color: var(--c-offline); color: var(--c-offline); }

@keyframes toast-in {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Favicon SVG (dynamique) ─────────────────────────────────────────────── */
/* Le favicon est mis à jour via JS selon l'émotion dominante */
```

- [ ] **Step 6: Vérification visuelle — ouvrir le dashboard dans le navigateur**

Ouvrir `http://localhost:8080` et vérifier :
- Fond crème, bordures sombres
- Header blanc avec logo accentué
- Tabs avec actif noir
- Boutons arrondis
- Modal avec fond blanc et coins ronds
- Toasts verts/rouges pastels

- [ ] **Step 7: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): restyle stream badges, logs, config, modal, toasts"
```

---

## Chunk 2: HTML markup + JS updates

### Task 8: Appliquer les classes couleur dans index.html

**Files:**
- Modify: `bot/dashboard/static/index.html`

Les cards statiques dans le HTML doivent recevoir leurs classes couleur. Les cards rendues dynamiquement (config form, memory) sont gérées dans app.js (Task 9).

- [ ] **Step 1: Tab STATUS — card uptime + card plateformes**

Remplacer :
```html
<div class="grid-2">
  <div class="card">
    <div class="card-title">UPTIME</div>
    <div class="card-value" id="uptime">—</div>
  </div>
  <div class="card">
    <div class="card-title">PLATEFORMES</div>
```
par :
```html
<div class="grid-2">
  <div class="card card-pink">
    <div class="card-title">UPTIME</div>
    <div class="card-value" id="uptime">—</div>
  </div>
  <div class="card card-teal">
    <div class="card-title">PLATEFORMES</div>
```

- [ ] **Step 2: Tab EMOTIONS (public) — card humeur en direct**

Remplacer (contexte complet pour éviter toute ambiguïté) :
```html
  <div class="tab-content" id="tab-emotions">
    <div class="card">
      <div class="card-title">HUMEUR EN DIRECT</div>
```
par :
```html
  <div class="tab-content" id="tab-emotions">
    <div class="card card-yellow">
      <div class="card-title">HUMEUR EN DIRECT</div>
```

- [ ] **Step 3: Tab STATS — card messages traités**

Remplacer :
```html
  <div class="tab-content" id="tab-stats">
    <div class="grid-2">
      <div class="card">
        <div class="card-title">MESSAGES TRAITÉS</div>
```
par :
```html
  <div class="tab-content" id="tab-stats">
    <div class="grid-2">
      <div class="card card-mint">
        <div class="card-title">MESSAGES TRAITÉS</div>
```

- [ ] **Step 4: Tab STREAM — card stream**

Remplacer `<div class="card" id="stream-card">` par `<div class="card card-aqua" id="stream-card">`.

- [ ] **Step 5: Tab ADMIN EMOTIONS — card forcer une valeur**

Remplacer :
```html
  <div class="tab-content" id="tab-admin-emotions">
    <div class="card">
      <div class="card-title">FORCER UNE VALEUR</div>
```
par :
```html
  <div class="tab-content" id="tab-admin-emotions">
    <div class="card card-yellow">
      <div class="card-title">FORCER UNE VALEUR</div>
```

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "style(dashboard): apply card color classes in index.html"
```

---

### Task 9: Mettre à jour app.js — EMOTION_COLORS, canvas, templates inline

**Files:**
- Modify: `bot/dashboard/static/app.js`

- [ ] **Step 1: Mettre à jour `EMOTION_COLORS`**

Remplacer :
```js
const EMOTION_COLORS = {
  anger:    '#ff3333',
  joy:      '#ffdd00',
  curiosity:'#00ccff',
  sadness:  '#7777ff',
  boredom:  '#888888',
};
```
par :
```js
const EMOTION_COLORS = {
  anger:    '#e63946',
  joy:      '#ffd60a',
  curiosity:'#2dc653',
  sadness:  '#0096c7',
  boredom:  '#9ca3af',
};
```

- [ ] **Step 2: Mettre à jour `drawEmotionGraph` — canvas background**

Dans la fonction `drawEmotionGraph` **uniquement**, faire deux remplacements **scoped** (ne pas toucher les autres occurrences de `fillStyle` dans le fichier) :

Remplacer (fond du canvas — contexte : ligne juste après `canvas.height = 140;`) :
```js
  ctx.fillStyle = '#111';
  ctx.fillRect(0, 0, W, 140);
```
par :
```js
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, W, 140);
```

Remplacer (labels temporels — contexte : ligne juste après le `for (const e of EMOTIONS)` loop) :
```js
  ctx.fillStyle = '#666';
  ctx.font = '10px monospace';
```
par :
```js
  ctx.fillStyle = '#888';
  ctx.font = '10px monospace';
```

- [ ] **Step 3: Mettre à jour les inline styles du template mémoire dans `renderMemoryTab`**

Dans la fonction `renderMemoryTab`, faire 5 remplacements dans le template littéral :

**3a. Barre de recherche container (dark border) :**
```js
    <div style="padding:12px 16px;border-bottom:2px solid #333;display:flex;gap:10px;align-items:center">
```
→
```js
    <div style="padding:12px 16px;border-bottom:2px solid #eee;display:flex;gap:10px;align-items:center">
```

**3b. Input de recherche (dark styles) :**
```js
             style="flex:1;max-width:320px;padding:7px 10px;background:var(--bg);border:3px solid var(--border);color:var(--text);font-family:var(--font);font-size:0.9rem;box-shadow:2px 2px 0px #fff;outline:none;border-radius:0">
```
→
```js
             style="flex:1;max-width:320px;padding:7px 10px;background:var(--card);border:2px solid var(--border);color:var(--text);font-family:var(--font);font-size:0.9rem;box-shadow:var(--shadow-sm);outline:none;border-radius:var(--radius-sm)">
```

**3c. Sidebar container (dark right border) :**
```js
      <div style="width:220px;border-right:2px solid #333;display:flex;flex-direction:column">
```
→
```js
      <div style="width:220px;border-right:2px solid #eee;display:flex;flex-direction:column">
```

**3d. User filter header (dark bottom border) :**
```js
        <div style="padding:10px 12px;border-bottom:1px solid #333">
```
→
```js
        <div style="padding:10px 12px;border-bottom:1px solid #eee">
```

**3e. Input de filtre users (dark styles) :**
```js
                 style="width:100%;padding:7px 10px;background:var(--bg);border:3px solid var(--border);color:var(--text);font-family:var(--font);font-size:0.8rem;outline:none;border-radius:0">
```
→
```js
                 style="width:100%;padding:7px 10px;background:var(--card);border:2px solid var(--border);color:var(--text);font-family:var(--font);font-size:0.8rem;outline:none;border-radius:var(--radius-sm)">
```

- [ ] **Step 4: Mettre à jour les inline styles des items utilisateur dans `loadMemoryUsers`**

Dans la fonction `loadMemoryUsers`, remplacer le template des items user (lignes 592–593 — attention aux indentations exactes) :

```js
         style="padding:7px 10px;background:#1a1a1a;border:2px solid ${selected ? '#00ccff' : '#555'};
                margin-bottom:4px;cursor:pointer;color:${selected ? '#00ccff' : 'var(--text)'}">
```
par :
```js
         style="padding:7px 10px;background:${selected ? 'var(--card-yellow)' : 'var(--card)'};border:2px solid ${selected ? 'var(--border)' : '#ddd'};border-radius:var(--radius-sm);box-shadow:${selected ? 'var(--shadow-sm)' : 'none'};margin-bottom:4px;cursor:pointer;color:var(--text)">
```

Dans `selectMemUser`, remplacer la mise à jour visuelle inline (**supprimer `el.style.color` est intentionnel** — la couleur est désormais `var(--text)` fixe dans le template ci-dessus) :
```js
    el.style.borderColor = selected ? '#00ccff' : '#555';
    el.style.color = selected ? '#00ccff' : 'var(--text)';
```
par :
```js
    el.style.background = selected ? 'var(--card-yellow)' : 'var(--card)';
    el.style.borderColor = selected ? 'var(--border)' : '#ddd';
    el.style.boxShadow = selected ? 'var(--shadow-sm)' : 'none';
```

Remplacer également dans `loadMemoryUsers` la variable `trustColor` qui utilise des couleurs dark hardcodées :
```js
    const trustColor = u.trust_score >= 0.7 ? '#00ccff' : u.trust_score <= 0.3 ? '#ff3333' : '#aaaaaa';
```
par :
```js
    const trustColor = u.trust_score >= 0.7 ? 'var(--c-curiosity)' : u.trust_score <= 0.3 ? 'var(--c-offline)' : 'var(--text-muted)';
```

- [ ] **Step 5: Mettre à jour `renderMemories` — cards de souvenirs**

Dans la fonction `renderMemories`, remplacer le style de chaque entrée mémoire :
```js
style="background:#1a1a1a;border:2px solid #333;padding:10px 12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-start"
```
par :
```js
style="background:var(--card);border:1.5px solid #ddd;border-radius:var(--radius-sm);padding:10px 12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-start"
```

Et le header de la section détail :
```js
style="padding:10px 16px;border-bottom:1px solid #333;display:flex;justify-content:space-between;align-items:center"
```
par :
```js
style="padding:10px 16px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center"
```

- [ ] **Step 6: Mettre à jour `searchMemories` — cards résultats**

Remplacer :
```js
style="background:#1a1a1a;border:2px solid #333;padding:10px 12px;margin-bottom:8px"
```
par :
```js
style="background:var(--card);border:1.5px solid #ddd;border-radius:var(--radius-sm);padding:10px 12px;margin-bottom:8px"
```

Et dans le header résultats :
```js
style="padding:10px 16px;border-bottom:1px solid #333"
```
par :
```js
style="padding:10px 16px;border-bottom:1px solid #eee"
```

- [ ] **Step 7: Mettre à jour `renderConfigForm` — labels des lambdas d'émotion**

Les cards config utilisent déjà `.card` et `.config-section-title` — aucun style inline dark à corriger sur ces éléments.

En revanche, les labels de décroissance émotions utilisent une couleur fallback dark :
```js
          <label class="field-label" style="color:${EMOTION_COLORS[name] || '#fff'}">${name.toUpperCase()} λ</label>
```
Remplacer `'#fff'` par `'var(--text-muted)'` :
```js
          <label class="field-label" style="color:${EMOTION_COLORS[name] || 'var(--text-muted)'}">${name.toUpperCase()} λ</label>
```

- [ ] **Step 8: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "style(dashboard): update EMOTION_COLORS, canvas bg, memory tab inline styles"
```

---

### Task 10: Vérification visuelle complète

**Files:** Aucun (vérification uniquement)

- [ ] **Step 1: Ouvrir le dashboard en mode public**

URL : `http://localhost:8080`

Vérifier tab par tab :
- **STATUT** : card rose (uptime), card teal (plateformes), dots online verts
- **HUMEUR** : card jaune avec jauges colorées, summary en italique gris, graph sur fond blanc
- **STREAM** : card aqua, badge LIVE rose ou badge OFFLINE gris
- **STATS** : card menthe avec compteur messages

- [ ] **Step 2: Passer en mode admin (token requis)**

Vérifier :
- **CONFIG** : cards blanches, titres de section avec bordure sombre (pas jaune)
- **HUMEUR** : card jaune avec sliders
- **LOGS** : fond blanc, WARNING en amber, ERROR en rouge
- **MÉMOIRE** : sidebar avec items cards, sélection jaune, souvenirs en cards blanches

- [ ] **Step 3: Vérifier les interactions**

- Toast succès → fond vert menthe, texte noir
- Toast erreur → fond rose pâle, texte rouge
- Modal auth → fond blanc, coins arrondis
- Boutons hover → `translate(2px, 2px)` préservé
- Graph canvas → lignes colorées sur fond blanc

- [ ] **Step 4: Commit final**

```bash
git add bot/dashboard/static/
git commit -m "style(dashboard): dashboard redesign complete — warm pastel neo-brutalism"
```

---

## Résumé des fichiers modifiés

| Fichier | Type de changement |
|---|---|
| `bot/dashboard/static/style.css` | Réécriture complète (variables, tous les composants) |
| `bot/dashboard/static/index.html` | Ajout classes couleur sur 5 cards statiques + logo |
| `bot/dashboard/static/app.js` | EMOTION_COLORS, canvas fillStyle, inline styles mémoire |

**Aucun fichier backend touché.**
