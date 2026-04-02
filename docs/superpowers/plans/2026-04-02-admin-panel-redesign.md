# Admin Panel Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refaire le panel admin en dark mode sobre (GitHub Dark), supprimer toute la partie publique intégrée.

**Architecture:** 3 fichiers modifiés (`index.html`, `style.css`, `app.js`), aucun changement backend. On supprime tout le code public (tabs, nav, naker.io, mode toggle) et on restyled le reste avec la palette GitHub Dark (#0d1117 / #161b22 / #30363d).

**Tech Stack:** HTML, CSS (custom properties + Tailwind CDN), vanilla JS, FastAPI (inchangé)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `bot/dashboard/static/index.html` | Modify | Supprimer HTML public, naker, mode toggle. Garder structure admin-only. |
| `bot/dashboard/static/style.css` | Rewrite | Nouvelle palette GitHub Dark, layout admin-only, supprimer glassmorphism. |
| `bot/dashboard/static/app.js` | Modify | Supprimer fonctions publiques (~45), mode toggle, naker init. Garder fonctions admin (~130) + shared (~25). |

---

### Task 1: Nettoyer `index.html` — supprimer le HTML public

**Files:**
- Modify: `bot/dashboard/static/index.html`

- [ ] **Step 1: Supprimer le script de détection mobile (lignes 17-33)**

Remove the entire `<script>` block that adds `is-mobile` class:

```html
<!-- REMOVE THIS ENTIRE BLOCK -->
<script>
// Detect mobile: touch + small screen OR mobile user agent
(function() {
  var mobileUA = ...
  ...
})();
</script>
```

- [ ] **Step 2: Supprimer naker.io background (lignes 37-52)**

Remove `<div id="naker-bg">`, `<canvas id="naker-blurred">`, and the entire naker script:

```html
<!-- REMOVE ALL THREE ELEMENTS -->
<div id="naker-bg"></div>
<canvas id="naker-blurred" aria-hidden="true"></canvas>
<script>
if (window.matchMedia('(min-width: 769px)').matches && !('ontouchstart' in window)) {
  ...naker viewer.js...
}
</script>
```

- [ ] **Step 3: Supprimer la nav publique du sidebar (lignes 91-116)**

Remove the entire `<nav class="sidebar-nav" id="nav-public">` block containing Status, Chat, Galerie, Info, Roadmap, Réseau links.

- [ ] **Step 4: Supprimer le divider et le mode toggle (lignes 118, 121-124, 153-158)**

Remove:
- `<div class="sidebar-divider" id="sidebar-divider">`
- The "Retour" back button (`mobile-back-btn`) inside `nav-admin`
- `<div class="sidebar-spacer">`
- `<button class="sidebar-mode-btn" id="sidebar-mode-toggle">`

- [ ] **Step 5: Rendre la nav admin visible par défaut**

Change `nav-admin` from `style="display:none"` to always visible:

```html
<nav class="sidebar-nav" id="nav-admin">
  <!-- Remove mobile-back-btn, keep the 6 admin items as-is -->
  <a class="sidebar-item active" data-tab="admin-parametres" ...>
```

Note: add `active` class to the first admin tab (Paramètres) by default.

- [ ] **Step 6: Supprimer les tabs publiques du main content**

Remove these `<div class="tab-content">` blocks:
- `tab-status` (lignes 165-238) — status widgets, gauges, emotion graph
- `tab-roadmap` (lignes 241-243)
- `tab-chat` (ligne 290)
- `tab-gallery` (lignes 293-307)
- `tab-journal-detail` (ligne 287)
- `tab-graph` (ligne 310)

- [ ] **Step 7: Supprimer les tabs orphelines/legacy**

Remove these unused tab containers:
- `tab-admin-config` (ligne 246-248)
- `tab-admin-logs` (ligne 251)
- `tab-memory` (ligne 254)
- `tab-global-memory` (ligne 257)
- `tab-admin-memory-dash` (ligne 266)
- `tab-admin-instances` (ligne 275)
- `tab-admin-twitch` (ligne 278)
- `tab-admin-overlay` (lignes 313-315)

- [ ] **Step 8: Supprimer le script layout/tab-style en bas de page (lignes 340-349)**

Remove:
```html
<script>
  // Applique les variants de layout et tab-style depuis les CSS vars du thème
  (function() { ... })();
</script>
```

- [ ] **Step 9: Vérifier le résultat**

Le `index.html` final doit contenir uniquement :
- `<head>` avec Tailwind CDN, Inter font, style.css, theme.css, app.js
- Control bar (`#control-bar`)
- Sidebar avec logo "W" + 6 items admin (Params, Mémoire, Couts, Actions, Prompts, Système)
- 6 tab content divs : `tab-admin-parametres`, `tab-admin-memoire`, `tab-admin-costs`, `tab-admin-actions`, `tab-admin-prompts`, `tab-admin-systeme`
- Auth modal
- Toast container

- [ ] **Step 10: Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "refactor(dashboard): strip public HTML from admin panel"
```

---

### Task 2: Réécrire `style.css` — palette GitHub Dark

**Files:**
- Rewrite: `bot/dashboard/static/style.css`

- [ ] **Step 1: Écrire les CSS custom properties et le reset global**

```css
/* Wally Admin Panel — GitHub Dark Theme */

:root {
  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'Courier New', Courier, monospace;

  /* Canvas */
  --bg-canvas:     #0d1117;
  --bg-surface:    #161b22;
  --bg-overlay:    #1c2128;
  --border:        #30363d;
  --border-accent: #3d444d;

  /* Text */
  --text-primary:   #e6edf3;
  --text-secondary: #7d8590;
  --text-muted:     #484f58;

  /* Accent */
  --accent:       #58a6ff;
  --accent-hover: #79c0ff;

  /* Status */
  --success: #3fb950;
  --danger:  #f85149;
  --warning: #d29e0b;

  /* Emotions */
  --c-anger:    #f85149;
  --c-joy:      #d29e0b;
  --c-curiosity:#3fb950;
  --c-sadness:  #58a6ff;
  --c-boredom:  #a371f7;

  --c-online:  #3fb950;
  --c-offline: #f85149;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-family: var(--font);
  min-height: 100vh;
  overflow: hidden;
}
```

- [ ] **Step 2: Écrire le layout principal (app-wrapper, sidebar, main-content)**

```css
/* ── App Layout ───────────────────────────────────────────────── */

.app-wrapper {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main-content {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
  min-width: 0;
}

/* ── Sidebar ──────────────────────────────────────────────────── */

.sidebar {
  width: 200px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 16px 0;
  border-right: 1px solid var(--border);
  background: var(--bg-surface);
  flex-shrink: 0;
  overflow-y: auto;
  scrollbar-width: none;
}
.sidebar::-webkit-scrollbar { display: none; }

.sidebar-logo {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--text-primary);
  padding: 8px 20px 20px;
  letter-spacing: -1px;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  color: var(--text-secondary);
  text-decoration: none;
  border-radius: 6px;
  transition: background 0.15s, color 0.15s;
  cursor: pointer;
  font-size: 13px;
}

.sidebar-item svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.sidebar-item span {
  font-size: 13px;
  font-weight: 500;
}

.sidebar-item:hover {
  background: var(--bg-overlay);
  color: var(--text-primary);
}

.sidebar-item.active {
  background: rgba(88, 166, 255, 0.1);
  color: var(--text-primary);
}

.sidebar-spacer { flex: 1; }
```

- [ ] **Step 3: Écrire les styles du control bar**

```css
/* ── Control Bar ──────────────────────────────────────────────── */

.control-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 20px;
  font-size: 12px;
  color: var(--text-secondary);
}

.control-bar-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-bar-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
}

.control-bar-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--danger);
}
.control-bar-dot.online { background: var(--success); }

.control-bar-label { font-size: 12px; }

.control-bar-btn {
  background: var(--bg-overlay);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 11px;
  cursor: pointer;
  font-family: var(--font);
  transition: background 0.15s, color 0.15s;
}
.control-bar-btn:hover {
  background: var(--border);
  color: var(--text-primary);
}
.control-bar-btn.restart { color: var(--warning); }
.control-bar-btn.update { color: var(--success); }
```

- [ ] **Step 4: Écrire les styles des cards et composants communs**

```css
/* ── Cards ────────────────────────────────────────────────────── */

.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}

.card-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.card-sublabel {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.card-value {
  font-size: 1.8rem;
  font-weight: 700;
}

/* ── Tab Content ──────────────────────────────────────────────── */

.tab-content { display: none; }
.tab-content.active { display: block; }

/* ── Buttons ──────────────────────────────────────────────────── */

.btn, .neo-btn {
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg-overlay);
  color: var(--text-primary);
  font-family: var(--font);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.btn:hover, .neo-btn:hover {
  background: var(--border);
  border-color: var(--border-accent);
}
.btn-success, .btn.btn-success {
  background: var(--success);
  border-color: var(--success);
  color: #fff;
}
.btn-success:hover {
  background: #2ea043;
}
.btn-danger, .btn.btn-danger {
  background: transparent;
  border-color: var(--danger);
  color: var(--danger);
}
.btn-danger:hover {
  background: rgba(248, 81, 73, 0.15);
}

/* ── Inputs ───────────────────────────────────────────────────── */

.neo-input, input[type="text"], input[type="password"], input[type="number"], input[type="email"],
textarea, select, .neo-select {
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  padding: 8px 12px;
  font-family: var(--font);
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
}
.neo-input:focus, input:focus, textarea:focus, select:focus {
  border-color: var(--accent);
}

::placeholder { color: var(--text-muted); }

/* ── Status Dots ──────────────────────────────────────────────── */

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.status-dot.online  { background: var(--c-online); }
.status-dot.offline { background: var(--c-offline); }
```

- [ ] **Step 5: Écrire les styles du modal d'authentification**

```css
/* ── Auth Modal ───────────────────────────────────────────────── */

.modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 100;
  align-items: center;
  justify-content: center;
}
.modal-overlay.visible { display: flex; }

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  min-width: 340px;
  max-width: 90vw;
}

.modal h2 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-primary);
}

.field-group { margin-bottom: 12px; }

.field-label {
  display: block;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
```

- [ ] **Step 6: Écrire les styles des toasts**

```css
/* ── Toast ─────────────────────────────────────────────────────── */

#toast-container {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.toast {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 13px;
  color: var(--text-primary);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  animation: toastIn 0.2s ease-out;
}
.toast.success { border-left: 3px solid var(--success); }
.toast.error   { border-left: 3px solid var(--danger); }
.toast.fade-out { opacity: 0; transition: opacity 0.3s; }

@keyframes toastIn {
  from { transform: translateY(10px); opacity: 0; }
  to   { transform: translateY(0); opacity: 1; }
}
```

- [ ] **Step 7: Écrire les styles des admin tabs — Émotions (gauges, sliders)**

```css
/* ── Emotion Gauges ───────────────────────────────────────────── */

.gauges {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.gauge {
  flex: 1;
  min-width: 100px;
}

.gauge-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
}

.gauge-bar {
  height: 6px;
  background: var(--bg-canvas);
  border-radius: 3px;
  overflow: hidden;
}

.gauge-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.5s ease;
}

/* ── Emotion Sliders (admin) ──────────────────────────────────── */

.emotion-slider-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.emotion-slider-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.emotion-slider-row label {
  width: 80px;
  font-size: 12px;
  color: var(--text-secondary);
  text-transform: uppercase;
}

.emotion-slider-row input[type="range"] {
  flex: 1;
  -webkit-appearance: none;
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  outline: none;
}

.emotion-slider-row input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  cursor: pointer;
}

.emotion-slider-row .val {
  width: 36px;
  text-align: right;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
```

- [ ] **Step 8: Écrire les styles admin — Memory (grid, cards, modal, categories)**

```css
/* ── Memory Grid ──────────────────────────────────────────────── */

.mem-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.mem-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.mem-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.mem-card:hover { border-color: var(--border-accent); }

.mem-card .name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.mem-card .meta {
  font-size: 11px;
  color: var(--text-secondary);
}

.mem-card .count {
  font-size: 18px;
  font-weight: 600;
  color: var(--accent);
}

/* ── Memory Modal ──────────────────────────────────────────────── */

.mem-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
}

.mem-modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 90vw;
  max-width: 700px;
  max-height: 85vh;
  overflow-y: auto;
  padding: 24px;
}

.mem-modal h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 16px;
}

/* Memory Categories */
.mem-category-pill {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 500;
}
.mem-category-pill.FAIT { background: rgba(88,166,255,0.15); color: var(--accent); border: 1px solid rgba(88,166,255,0.3); }
.mem-category-pill.PREF { background: rgba(210,153,11,0.15); color: var(--warning); border: 1px solid rgba(210,153,11,0.3); }
.mem-category-pill.LANG { background: rgba(63,185,80,0.15); color: var(--success); border: 1px solid rgba(63,185,80,0.3); }
.mem-category-pill.REL  { background: rgba(163,113,247,0.15); color: #a371f7; border: 1px solid rgba(163,113,247,0.3); }

/* Memory Entry */
.mem-entry {
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--text-primary);
}
.mem-entry:last-child { border-bottom: none; }
.mem-entry .date {
  font-size: 11px;
  color: var(--text-muted);
}
.mem-entry .actions {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.mem-entry .actions button {
  font-size: 11px;
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 2px 4px;
}
.mem-entry .actions button:hover { color: var(--text-primary); }

/* ── Linked Accounts ──────────────────────────────────────────── */

.linked-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

/* ── Alias Pills ──────────────────────────────────────────────── */

.alias-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-overlay);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.alias-pill button {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}

/* ── Link Mode ────────────────────────────────────────────────── */

.link-mode-banner {
  background: rgba(88, 166, 255, 0.1);
  border: 1px solid rgba(88, 166, 255, 0.3);
  border-radius: 8px;
  padding: 10px 16px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--accent);
}

/* ── Pending Links ────────────────────────────────────────────── */

.pending-links-banner {
  background: rgba(210, 153, 11, 0.1);
  border: 1px solid rgba(210, 153, 11, 0.3);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
```

- [ ] **Step 9: Écrire les styles admin — Costs, Actions, Prompts, Logs**

```css
/* ── Costs ─────────────────────────────────────────────────────── */

.cost-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.cost-kpi {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
}

.cost-kpi .label {
  font-size: 10px;
  text-transform: uppercase;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
}

.cost-kpi .value {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin-top: 4px;
}

.cost-alert-bar {
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 12px;
}
.cost-alert-bar.ok      { background: rgba(63,185,80,0.1); color: var(--success); border: 1px solid rgba(63,185,80,0.3); }
.cost-alert-bar.warning { background: rgba(210,153,11,0.1); color: var(--warning); border: 1px solid rgba(210,153,11,0.3); }
.cost-alert-bar.critical { background: rgba(248,81,73,0.1); color: var(--danger); border: 1px solid rgba(248,81,73,0.3); }

/* ── Logs ──────────────────────────────────────────────────────── */

.log-stream {
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  max-height: 500px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
}

.log-entry { color: var(--text-secondary); }
.log-entry.WARNING { color: var(--warning); }
.log-entry.ERROR   { color: var(--danger); }

.log-filters {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}

.log-filter-btn {
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  font-family: var(--font);
}
.log-filter-btn.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

/* ── Actions Tab ──────────────────────────────────────────────── */

.actions-table {
  width: 100%;
  border-collapse: collapse;
}

.actions-table th, .actions-table td {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

.actions-table th {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
  font-weight: 600;
}

/* ── Prompts Editor ───────────────────────────────────────────── */

.prompt-editor-wrap {
  display: flex;
  gap: 12px;
  height: calc(100vh - 180px);
}

.prompt-file-list {
  width: 200px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow-y: auto;
  padding: 8px;
}

.prompt-file-item {
  padding: 6px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
}
.prompt-file-item:hover { background: var(--bg-overlay); }
.prompt-file-item.active { background: rgba(88,166,255,0.1); color: var(--text-primary); }

.prompt-editor {
  flex: 1;
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
  resize: none;
}

/* ── Overlay Toggle ───────────────────────────────────────────── */

.overlay-switch {
  position: relative;
  width: 44px;
  height: 24px;
  display: inline-block;
}

.overlay-switch input { opacity: 0; width: 0; height: 0; }

.overlay-switch .slider {
  position: absolute;
  inset: 0;
  background: var(--border);
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.2s;
}

.overlay-switch .slider::before {
  content: '';
  position: absolute;
  width: 18px;
  height: 18px;
  bottom: 3px;
  left: 3px;
  background: var(--text-primary);
  border-radius: 50%;
  transition: transform 0.2s;
}

.overlay-switch input:checked + .slider { background: var(--success); }
.overlay-switch input:checked + .slider::before { transform: translateX(20px); }
```

- [ ] **Step 10: Écrire les styles admin — Sub-navigation pills (Paramètres, Système, Mémoire, Coûts)**

```css
/* ── Sub-Navigation Pills ─────────────────────────────────────── */

.sub-nav {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}

.sub-nav-btn {
  padding: 6px 14px;
  border-radius: 6px 6px 0 0;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font);
  font-size: 13px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}
.sub-nav-btn:hover { color: var(--text-primary); }
.sub-nav-btn.active {
  color: var(--text-primary);
  background: var(--bg-surface);
  border-bottom: 2px solid var(--accent);
}
```

- [ ] **Step 11: Écrire les styles — Twitch Auth, Visitors, Graph, sidebar badge**

```css
/* ── Twitch Auth Panel ────────────────────────────────────────── */

.twitch-auth-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}

.twitch-auth-card .status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

/* ── Visitors Table ───────────────────────────────────────────── */

.visitors-table {
  width: 100%;
  border-collapse: collapse;
}

.visitors-table th, .visitors-table td {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

.visitors-table th {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--text-secondary);
}

/* ── Sidebar Badge ────────────────────────────────────────────── */

.sidebar-badge {
  font-size: 10px;
  background: var(--danger);
  color: #fff;
  padding: 1px 5px;
  border-radius: 8px;
  margin-left: auto;
}

/* ── Global Memory ────────────────────────────────────────────── */

.global-mem-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.global-mem-item {
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
}

/* ── Emotion Graph (admin costs canvas reuse) ─────────────────── */

canvas {
  width: 100%;
  display: block;
}

/* ── Graph Legend ──────────────────────────────────────────────── */

.graph-legend {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 8px;
  font-size: 11px;
}

.graph-legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: var(--text-secondary);
}

.graph-legend-item .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.graph-legend-item.hidden { opacity: 0.35; }

/* ── Emotional state ──────────────────────────────────────────── */

.emotional-state-card {
  margin-top: 12px;
  padding: 10px 14px;
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}

.emotion-summary {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}

/* ── Mood/Fatigue line ────────────────────────────────────────── */

#mood-fatigue-line {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 8px;
}
```

- [ ] **Step 12: Écrire les styles — Apparence tab, memory dashboard questions, empty states**

```css
/* ── Apparence (theme editor) ─────────────────────────────────── */

.theme-color-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.theme-color-row label {
  width: 120px;
  font-size: 13px;
  color: var(--text-secondary);
}

.theme-color-row input[type="color"] {
  width: 36px;
  height: 28px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: none;
  cursor: pointer;
}

/* ── Memory Dashboard / Questions ─────────────────────────────── */

.mem-question-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.mem-question-row:last-child { border-bottom: none; }

.mem-question-text {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
}

.mem-question-meta {
  font-size: 11px;
  color: var(--text-muted);
}

/* ── Empty State ──────────────────────────────────────────────── */

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-muted);
  font-size: 14px;
}

/* ── Scrollbar ────────────────────────────────────────────────── */

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-accent); }

/* ── Focus States ─────────────────────────────────────────────── */

*:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* ── Reduced Motion ───────────────────────────────────────────── */

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 13: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "refactor(dashboard): rewrite style.css with GitHub Dark theme"
```

---

### Task 3: Nettoyer `app.js` — supprimer le code public

**Files:**
- Modify: `bot/dashboard/static/app.js`

This is the largest task. We remove ~2800 lines of public-only code while keeping all admin and shared functions intact.

- [ ] **Step 1: Supprimer les state variables publiques et le mode toggle**

Remove/modify at the top of the file (lines 57-76):

```javascript
// REMOVE these:
let currentMode = 'public';     // line 58 — replace with just admin mode
// KEEP currentTab but change default:
let currentTab  = 'admin-parametres';

// REMOVE:
let _chatWs = null;             // line 106
let _chatUser = null;           // line 107
let _chatTypingTimer = null;    // line 108
```

- [ ] **Step 2: Supprimer `toggleMode()`, `_isMobileNav()`, et réécrire `switchMode()`**

Remove `toggleMode()` (line 268-270), `_isMobileNav()` (line 272-274), and replace `switchMode()` (lines 276-334) with a simpler version:

```javascript
function enterAdmin() {
  if (!getToken()) { showAuthModal(); return; }
  document.getElementById('nav-admin').style.display = 'flex';
  showControlBar(true);
  startControlBarPolling();
  renderSystemeTab();
  startLogSSE();
  showTab('admin-parametres');
}
```

- [ ] **Step 3: Simplifier `showTab()` — retirer les routes publiques**

In `showTab()` (lines 336-387), remove all public tab triggers:

```javascript
// REMOVE these lines:
if (tabId === 'status') { loadStreamStatus(); requestAnimationFrame(() => loadEmotionHistory(currentGraphSince)); }
if (tabId === 'roadmap') loadRoadmap();
if (tabId === 'chat') renderChatTab();
if (tabId === 'journal-detail') renderJournalDetailTab();
if (tabId === 'memory' && !document.getElementById('mem-grid')) renderMemoryTab();
if (tabId === 'global-memory') renderGlobalMemoryTab();
if (tabId === 'gallery') loadGallery(true);
if (tabId === 'graph') loadPublicGraph();

// REMOVE legacy redirects for public tabs
```

Also simplify the hash to just `location.hash = tabId;` (no mode prefix).

- [ ] **Step 4: Supprimer les fonctions du tab Status (lignes 467-498, 996-1015)**

Remove `loadStatus()` and `loadStreamStatus()`.

- [ ] **Step 5: Supprimer les fonctions du graph d'émotions publiques**

Remove these functions (keep `buildGauges`, `hexToRgba`, `updateEmotionGauges`, `updateMoodFatigueLine`, `updateEmotionalStateBlock` which are used by admin Paramètres tab):

```
// REMOVE:
updateEmotionSummary()        — line 555-562
updateFavicon()               — line 664-669
startEmotionSSE()             — line 671-678
loadEmotionHistory()          — line 691-710
showGraphEmpty()              — line 712-730
setGraphRange()               — line 732-752
renderEmotionAverages()       — line 754-767
buildEmotionLegend()          — line 771-796
toggleEmotion()               — line 798-803
_computeSecondaryActivations()— line 812-834
drawEmotionGraph()            — line 836-992
```

- [ ] **Step 6: Supprimer `initNakerBlur()` et le code naker dans DOMContentLoaded**

Remove `initNakerBlur()` (lines 1733-1760).

- [ ] **Step 7: Réécrire le `DOMContentLoaded` handler**

Replace the current handler (lines 1762-1926) with a simplified admin-only init:

```javascript
document.addEventListener('DOMContentLoaded', async () => {
  // Check if already authenticated
  if (getToken()) {
    enterAdmin();
  } else {
    showAuthModal();
  }
});
```

Remove: naker init, public gauges build, loadStatus polling, emotion SSE, stream status, graph range, tooltip handlers for emotion/cost canvas (keep cost canvas tooltip — it's admin), overlay status poll.

Keep: cost canvas tooltip handler (move inside `renderCostsTab` or keep if canvas exists), hash restore for admin tabs.

- [ ] **Step 8: Supprimer les fonctions Chat (lignes 3514-4067)**

Remove all chat functions:
- `getChatJwt`, `getChatRefresh`, `setChatTokens`, `clearChatTokens`, `chatCheckAuth`
- `renderChatTab`, `chatLogout`, `chatConnectWs`, `chatAppendMessage`, `chatAppendSystem`
- `chatScrollBottom`, `chatShowTyping`, `chatHideTyping`, `chatSend`
- `chatBuildHeroEmotions`, `chatUpdateHeroEmotions`, `chatToggleSessionPanel`
- `chatLoadSessions`, `_formatSessionDate`, `chatLoadDay`, `chatBackToToday`
- `chatLoadMyMemories`, `chatOpenMemoryPanel`, `chatCloseMemoryPanel`, `_renderMemoryPanelBody`
- `chatStartAvatarUpdates`, `chatUpdateAvatar`

- [ ] **Step 9: Supprimer les fonctions Roadmap (lignes 2810-2874)**

Remove `loadRoadmap()` and `renderRoadmap()`.

- [ ] **Step 10: Supprimer les fonctions Gallery (lignes ~6327+)**

Remove `loadGallery()`, `loadMoreGallery()`, `voteGallery()`, `openGalleryModal()`, and all gallery-related functions.

- [ ] **Step 11: Supprimer les fonctions Journal Detail (lignes ~5899+)**

Remove `renderJournalDetailTab()` and related helpers.

- [ ] **Step 12: Supprimer les fonctions Public Graph (lignes ~5607+)**

Remove `loadPublicGraph()` and related graph rendering functions.

- [ ] **Step 13: Supprimer `submitToken()` redirect vers public**

In `submitToken()` (line 397-411), after successful auth, call `enterAdmin()` instead of `switchMode('admin')`. Also remove `hideAuthModal()` call if it redirects to public mode in the cancel button.

- [ ] **Step 14: Mettre à jour les couleurs d'émotions dans les constantes**

Update `EMOTION_COLORS` (lines 9-16) to match the new palette:

```javascript
const EMOTION_COLORS = {
  anger:    '#f85149',
  joy:      '#d29e0b',
  curiosity:'#3fb950',
  sadness:  '#58a6ff',
  boredom:  '#a371f7',
};
```

- [ ] **Step 15: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "refactor(dashboard): remove public code from app.js, admin-only"
```

---

### Task 4: Mettre à jour `index.html` — nouveau layout sidebar

**Files:**
- Modify: `bot/dashboard/static/index.html`

- [ ] **Step 1: Réécrire le sidebar avec le nouveau style (icônes + texte horizontal)**

Le sidebar passe de 80px (icônes empilées) à 200px (icônes + texte côte à côte). Réécrire le bloc `<aside class="sidebar">` :

```html
<aside class="sidebar" id="sidebar">
  <div class="sidebar-logo">W <span style="color:var(--text-muted);font-size:12px;font-weight:400;margin-left:6px;">Admin</span></div>

  <nav class="sidebar-nav" id="nav-admin">
    <a class="sidebar-item active" data-tab="admin-parametres" onclick="showTab('admin-parametres')" href="javascript:void(0)">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
      <span>Paramètres</span>
    </a>
    <a class="sidebar-item" data-tab="admin-memoire" onclick="showTab('admin-memoire')" href="javascript:void(0)">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"/></svg>
      <span>Mémoire</span>
      <span id="links-badge" class="sidebar-badge" style="display:none">0</span>
    </a>
    <a class="sidebar-item" data-tab="admin-costs" onclick="showTab('admin-costs')" href="javascript:void(0)">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
      <span>Coûts</span>
      <span id="costs-badge" class="sidebar-badge" style="display:none">!</span>
    </a>
    <a class="sidebar-item" data-tab="admin-actions" onclick="showTab('admin-actions')" href="javascript:void(0)">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
      <span>Actions</span>
    </a>
    <a class="sidebar-item" data-tab="admin-prompts" onclick="showTab('admin-prompts')" href="javascript:void(0)">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
      <span>Prompts</span>
    </a>
    <a class="sidebar-item" data-tab="admin-systeme" onclick="showTab('admin-systeme')" href="javascript:void(0)">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
      <span>Système</span>
    </a>
  </nav>

  <div class="sidebar-spacer"></div>
</aside>
```

- [ ] **Step 2: Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "refactor(dashboard): update sidebar to 200px icon+text layout"
```

---

### Task 5: Test et validation manuelle

**Files:** None (testing only)

- [ ] **Step 1: Vérifier que le container build**

```bash
cd /opt/stacks/wally-ai && docker compose build wally
```

Expected: Build succeeds.

- [ ] **Step 2: Redémarrer le container**

```bash
cd /opt/stacks/wally-ai && docker compose up -d wally
```

- [ ] **Step 3: Vérifier la route `/admin`**

```bash
curl -s http://localhost:8080/admin | head -20
```

Expected: HTML sans naker.io, sans nav-public, avec les 6 items admin dans le sidebar.

- [ ] **Step 4: Vérifier que le public-ui fonctionne toujours**

```bash
curl -s http://localhost:8080/ | head -5
```

Expected: le contenu de `public-ui/index.html` (pas `index.html` admin).

- [ ] **Step 5: Vérifier le CSS**

```bash
curl -s http://localhost:8080/static/style.css | head -30
```

Expected: nouvelles CSS variables GitHub Dark (`--bg-canvas: #0d1117`, etc.).

- [ ] **Step 6: Vérifier les onglets admin dans le JS**

```bash
curl -s http://localhost:8080/static/app.js | grep -c "renderChatTab\|loadRoadmap\|loadGallery\|loadPublicGraph\|initNakerBlur"
```

Expected: `0` (toutes ces fonctions supprimées).

- [ ] **Step 7: Vérifier que les fonctions admin sont présentes**

```bash
curl -s http://localhost:8080/static/app.js | grep -c "renderParametresTab\|renderSystemeTab\|renderCostsTab\|renderMemoireTab\|renderActionsTab\|renderPromptsTab"
```

Expected: `6` ou plus (toutes les fonctions admin présentes).

- [ ] **Step 8: Commit final (si ajustements)**

```bash
git add -A && git commit -m "fix(dashboard): post-refonte adjustments"
```

---

## Execution Order

Tasks 1 → 4 sont séquentielles (chaque fichier dépend du précédent pour la cohérence). Task 5 est la validation finale.

Le CSS (Task 2) peut être écrit en parallèle de Task 1 car il n'y a pas de dépendance directe, mais le test final nécessite les 3 fichiers à jour.
