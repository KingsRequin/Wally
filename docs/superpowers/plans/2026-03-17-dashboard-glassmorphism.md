# Dashboard Glassmorphism Redesign — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le thème neo-brutalism pastel par un design glassmorphism sombre accent cyan `#00D4FF`.

**Architecture:** Changements purement frontend (3 fichiers). Aucun backend modifié. Chaque tâche est indépendante et committée séparément pour faciliter le rollback.

**Tech Stack:** CSS3 (backdrop-filter, CSS custom properties, @keyframes), HTML5, Vanilla JS (Canvas 2D API, EventSource), Google Fonts (Inter)

**Spec:** `docs/superpowers/specs/2026-03-17-dashboard-glassmorphism-design.md`

**Vérification visuelle:** `http://<host-ip>:8080/` (ou `docker compose up` depuis `/opt/stacks/wally-ai`)

---

## Fichiers modifiés

| Fichier | Rôle |
|---|---|
| `bot/dashboard/static/style.css` | Thème, layout, animations |
| `bot/dashboard/static/index.html` | Structure HTML, imports |
| `bot/dashboard/static/app.js` | Logique JS, canvas, SSE |

---

## Task 1 : CSS — `:root`, glassmorphism card, typographie

**Files:**
- Modify: `bot/dashboard/static/style.css:1-190`

### Contexte
Remplacer intégralement le bloc `:root` et les règles `.card`, `.card-title`, `.card-value`. Supprimer les 5 règles `.card-pink/teal/yellow/aqua/mint`.

- [ ] **Step 1 : Remplacer le bloc `:root` (lignes 1-43)**

Remplacer le contenu entier du bloc `:root { … }` par :

```css
/* Glassmorphism dark — Wally Dashboard */

:root {
  /* Base */
  --bg: #0b0b14;
  --bg-alt: #0f0f1c;
  --card: rgba(255, 255, 255, 0.05);
  --card-border: rgba(255, 255, 255, 0.08);

  /* Accent */
  --accent: #00D4FF;
  --accent-glow: rgba(0, 212, 255, 0.35);
  --accent-soft: rgba(0, 212, 255, 0.15);

  /* Texte */
  --text: #ffffff;
  --text-muted: rgba(255, 255, 255, 0.5);

  /* Ombres */
  --shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
  --shadow-sm: 0 2px 12px rgba(0, 0, 0, 0.2);
  --shadow-btn: 0 2px 8px rgba(0, 0, 0, 0.3);

  /* Bordures/radius */
  --border: rgba(255, 255, 255, 0.08);
  --radius: 16px;
  --radius-sm: 10px;
  --radius-btn: 10px;
  --radius-tab: 6px;
  --radius-xs: 4px;

  /* Polices */
  --font: 'Courier New', Courier, monospace;
  --font-ui: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

  /* Émotions */
  --c-anger:    #FF4D4D;
  --c-joy:      #FFD700;
  --c-curiosity:#00E5A0;
  --c-sadness:  #4DA6FF;
  --c-boredom:  #AAAAAA;

  /* Status */
  --c-online:  #00E5A0;
  --c-offline: #FF4D4D;
}
```

- [ ] **Step 2 : Remplacer la règle `.card` (lignes 161-168)**

Remplacer `.card { … }` par :

```css
.card {
  background: var(--card);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 20px;
  margin-bottom: 16px;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
```

- [ ] **Step 3 : Supprimer les 5 règles `.card-pink/teal/yellow/aqua/mint` (lignes 170-175)**

Supprimer complètement ce bloc :
```css
/* Carte colorée : background + texte sombre (pastels clairs sur dark theme) */
.card-pink   { background: var(--card-pink);   color: #111; }
.card-teal   { background: var(--card-teal);   color: #111; }
.card-yellow { background: var(--card-yellow); color: #111; }
.card-aqua   { background: var(--card-aqua);   color: #111; }
.card-mint   { background: var(--card-mint);   color: #111; }
```

- [ ] **Step 4 : Remplacer `.card-title` et `.card-value` (lignes 177-190)**

Remplacer les deux règles par :

```css
.card-title {
  font-family: var(--font-ui);
  font-size: 0.65rem;
  font-weight: 500;
  letter-spacing: 0.15em;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 10px;
}

.card-value {
  font-size: 2.5rem;
  font-weight: 700;
  color: var(--accent);
  font-family: var(--font);
}
```

- [ ] **Step 5 : Vérification visuelle**

Ouvrir `http://<host-ip>:8080/` dans le navigateur.
Attendu :
- Fond de page très sombre (`#0b0b14`)
- Cartes translucides avec flou visible (glassmorphism)
- Valeurs UPTIME et MESSAGES en cyan `#00D4FF`
- Labels UPTIME etc. en grisé semi-transparent

- [ ] **Step 6 : Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): glassmorphism root vars, card, typography"
```

---

## Task 2 : CSS — Jauges, track, transition

**Files:**
- Modify: `bot/dashboard/static/style.css:260-281`

### Contexte
Mettre à jour les fills de jauge (couleur + glow), le track (fond sombre), la transition (1s → 0.6s). Supprimer les overrides de track sur cartes colorées.

- [ ] **Step 1 : Mettre à jour `.gauge-track` (lignes 250-258)**

Remplacer le bloc `.gauge-track { … }` par :

```css
.gauge-track {
  flex: 1;
  height: 10px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-xs);
  position: relative;
  overflow: hidden;
}
```

- [ ] **Step 2 : Mettre à jour `.gauge-fill` transition et les règles par émotion (lignes 260-271)**

Dans le bloc `.gauge-fill { … }` existant, mettre à jour uniquement la propriété `transition` de `1s` à `0.6s` (conserver `height: 100%`, `width: 0%`, `border-radius`). Puis remplacer les 5 règles `.gauge-fill.*` par :

```css
.gauge-fill.anger     { background: var(--c-anger);    box-shadow: 0 0 8px rgba(255, 77, 77, 0.53); }
.gauge-fill.joy       { background: var(--c-joy);      box-shadow: 0 0 8px rgba(255, 215, 0, 0.53); }
.gauge-fill.curiosity { background: var(--c-curiosity);box-shadow: 0 0 8px rgba(0, 229, 160, 0.53); }
.gauge-fill.sadness   { background: var(--c-sadness);  box-shadow: 0 0 8px rgba(77, 166, 255, 0.53); }
.gauge-fill.boredom   { background: var(--c-boredom);  box-shadow: none; }
```

- [ ] **Step 3 : Supprimer les overrides de track sur cartes colorées (lignes 273-281)**

Supprimer complètement ce bloc :
```css
/* Gauge track sur cartes pastels claires — fond sombre lisible */
.card-pink .gauge-track,
.card-teal .gauge-track,
.card-yellow .gauge-track,
.card-aqua .gauge-track,
.card-mint .gauge-track {
  background: rgba(0,0,0,0.12);
  border-color: rgba(0,0,0,0.15);
}
```

- [ ] **Step 4 : Mettre à jour `.emotion-summary` (lignes 302-308)**

Remplacer le bloc par :

```css
.emotion-summary {
  font-style: italic;
  text-align: center;
  opacity: 0.6;
  margin-top: 12px;
  min-height: 1.4em;
}
```

- [ ] **Step 5 : Vérification visuelle**

Ouvrir `http://<host-ip>:8080/`.
Attendu :
- Jauges : fills avec glow coloré (anger rouge, joy jaune, etc.)
- Track : fond sombre translucide, pas de fond blanc
- Transition plus rapide (0.6s au lieu de 1s)

- [ ] **Step 6 : Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): glassmorphism gauge fills with glow, dark track"
```

---

## Task 3 : CSS — Tabs, badge shimmer, Twitch badges animés

**Files:**
- Modify: `bot/dashboard/static/style.css:135-209` (tabs + badge), `style.css:389-413` (stream badges)

### Contexte
Tab actif en cyan, badge BIENTÔT shimmer, Twitch badges glassmorphism avec `.dot` animé.

- [ ] **Step 1 : Mettre à jour `.tab-btn.active` (lignes 135-138)**

Remplacer le bloc `.tab-btn.active { … }` par :

```css
.tab-btn.active {
  color: var(--accent);
  border-bottom: 2px solid var(--accent);
  background: transparent;
}
```

- [ ] **Step 2 : Remplacer `.badge-soon` et ajouter l'animation shimmer (lignes 201-209)**

Remplacer le bloc `.badge-soon { … }` par :

```css
@keyframes shimmer {
  0%   { background-position: -200% center; }
  100% { background-position:  200% center; }
}
.badge-soon {
  background: linear-gradient(90deg, rgba(0,212,255,0.2) 25%, rgba(0,212,255,0.5) 50%, rgba(0,212,255,0.2) 75%);
  background-size: 200% auto;
  animation: shimmer 2s linear infinite;
  border: 1px solid rgba(0,212,255,0.4);
  color: var(--accent);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.6rem;
  font-weight: 700;
  vertical-align: middle;
}
```

- [ ] **Step 3 : Remplacer `.stream-live-badge` et `.stream-offline-badge` (lignes 389-413)**

Remplacer les deux blocs par :

```css
/* ── Stream card ─────────────────────────────────────────────────────────── */

.stream-live-badge,
.stream-offline-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  font-weight: 900;
  font-size: 0.75rem;
  letter-spacing: 2px;
  border-radius: var(--radius-tab);
  margin-bottom: 8px;
}
.stream-live-badge {
  background: rgba(0, 229, 160, 0.15);
  color: var(--c-online);
  border: 1px solid rgba(0, 229, 160, 0.4);
}
.stream-offline-badge {
  background: rgba(255, 77, 77, 0.15);
  color: var(--c-offline);
  border: 1px solid rgba(255, 77, 77, 0.4);
}

/* Dot indicator */
.stream-live-badge .dot,
.stream-offline-badge .dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.stream-live-badge .dot  { background: var(--c-online); }
.stream-offline-badge .dot { background: var(--c-offline); }

/* Animations */
@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255,77,77,0.7); }
  50%       { box-shadow: 0 0 0 6px rgba(255,77,77,0); }
}
.stream-offline-badge .dot {
  animation: pulse-red 2s ease-in-out infinite;
}

@keyframes scale-green {
  0%, 100% { transform: scale(1); }
  50%       { transform: scale(1.15); }
}
.stream-live-badge .dot {
  animation: scale-green 1.5s ease-in-out infinite;
}
```

- [ ] **Step 4 : Vérification visuelle**

Ouvrir `http://<host-ip>:8080/`.
Attendu :
- Tab actif "📊 STATUT" : texte cyan, soulignement cyan, pas de fond blanc
- Badge "BIENTÔT" : animation shimmer cyan visible
- Carte AZRAEL_TTV : badge LIVE vert ou OFFLINE rouge translucide (remplace le rose)

- [ ] **Step 5 : Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): cyan tab, shimmer badge, glassmorphism Twitch badges"
```

---

## Task 4 : CSS — Animations fadeIn, graph-container, cleanup overrides

**Files:**
- Modify: `bot/dashboard/static/style.css`

### Contexte
Ajouter les animations d'entrée staggerées, mettre à jour `.graph-container` et les règles admin résiduelles, supprimer tous les blocs d'overrides dark-mode.

- [ ] **Step 1 : Ajouter fadeIn + bento-card-anim + stagger (après la règle `.bento-grid`)**

Ajouter juste après le bloc `.bento-grid { … }` existant (ligne ~199) :

```css
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.bento-card-anim {
  animation: fadeIn 0.4s ease forwards;
  opacity: 0;
}
.bento-grid > *:nth-child(1) { animation-delay: 0.0s; }
.bento-grid > *:nth-child(2) { animation-delay: 0.1s; }
.bento-grid > *:nth-child(3) { animation-delay: 0.2s; }
.bento-grid > *:nth-child(4) { animation-delay: 0.3s; }
.bento-grid > *:nth-child(5) { animation-delay: 0.4s; }
.bento-grid > *:nth-child(6) { animation-delay: 0.5s; }
```

- [ ] **Step 2 : Mettre à jour `.graph-container` (ligne ~313)**

Dans la règle `.graph-container { … }`, changer :
```css
border: 2.5px solid var(--border);
```
→
```css
border: 1px solid var(--card-border);
```
(Laisser `box-shadow`, `border-radius`, `background`, `padding` inchangés.)

- [ ] **Step 3 : Mettre à jour `.logo .logo-accent` (ligne ~76)**

Changer :
```css
.logo .logo-accent { color: var(--card-pink); }
```
→
```css
.logo .logo-accent { color: var(--accent); }
```

- [ ] **Step 4 : Mettre à jour `.btn-success` et `.btn-info` (lignes ~352-353)**

Remplacer :
```css
.btn-success { background: var(--card-mint); }
.btn-info    { background: var(--card-aqua); }
```
par :
```css
.btn-success { background: rgba(0,229,160,0.15); color: var(--c-online);  border-color: var(--c-online); }
.btn-info    { background: rgba(0,212,255,0.15); color: var(--accent);    border-color: var(--accent); }
```

- [ ] **Step 5 : Mettre à jour `.toast.success` (ligne ~508)**

Remplacer :
```css
.toast.success { background: var(--card-mint); }
```
par :
```css
.toast.success { background: rgba(0,229,160,0.15); border-color: var(--c-online); }
```

- [ ] **Step 6 : Supprimer le bloc "Dark mode overrides" entier**

Ce bloc commence à la ligne 519 (commentaire `/* ── Dark mode overrides : texte sur cartes colorées */`) et s'étend jusqu'à **la fin du fichier** (ligne 561 — c'est le dernier bloc du fichier, rien ne suit).

Supprimer tout ce bloc (lignes 519-561) :
```css
/* ── Dark mode overrides : texte sur cartes colorées ─────────────────────── */

.card:not(.card-pink):not(.card-teal):not(.card-yellow):not(.card-aqua):not(.card-mint) .card-title { … }
.card:not(.card-pink):not(.card-teal):not(.card-yellow):not(.card-aqua):not(.card-mint) .card-value { … }
.graph-container .card-title { … }
.card-pink .gauge-val, .card-teal .gauge-val, … { color: #111; }
.card-pink .emotion-label, .card-teal .emotion-label, … { color: #111; }
.card-pink .emotion-summary, .card-teal .emotion-summary, … { color: rgba(0,0,0,0.55); }
```

- [ ] **Step 7 : Vérification visuelle**

Ouvrir `http://<host-ip>:8080/`.
Attendu :
- Cartes apparaissent en fondu avec décalage (stagger visible au rechargement)
- Le "A" de "WALLY" dans le header est cyan
- Boutons VALIDER/SYNC restent fonctionnels (verts/bleus glassmorphism)
- Toast "Accès admin accordé" est vert translucide (pas vert vif)

- [ ] **Step 8 : Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "style(dashboard): fadeIn stagger, graph-container border, cleanup overrides"
```

---

## Task 5 : HTML — Import Inter, icônes, suppression classes colorées

**Files:**
- Modify: `bot/dashboard/static/index.html`

### Contexte
Ajouter l'import Google Fonts Inter dans `<head>`, mettre à jour les 6 `.card-title` avec icônes, retirer toutes les classes `card-*` des divs, ajouter `bento-card-anim`.

- [ ] **Step 1 : Ajouter import Inter dans `<head>` (avant ligne 7)**

Ajouter ces 3 lignes juste avant `<link rel="stylesheet" href="/static/style.css">` :

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
```

- [ ] **Step 2 : Mettre à jour les 6 `.card-title` avec icônes**

| Ligne | Avant | Après |
|---|---|---|
| ~45 | `UPTIME` | `⏱ UPTIME` |
| ~50 | `PLATEFORMES` | `📡 PLATEFORMES` |
| ~62 | `MESSAGES TRAITÉS` | `💬 MESSAGES TRAITÉS` |
| ~69 | `HUMEUR EN DIRECT` | `🎭 HUMEUR EN DIRECT` |
| ~75 | `AZRAEL_TTV` | `📺 AZRAEL_TTV` |
| ~81 | `DERNIÈRES 24H` | `📈 DERNIÈRES 24H` |

- [ ] **Step 3 : Retirer les classes `card-*` des 5 divs bento et du div admin**

Modifier chaque div bento :

```html
<!-- Avant → Après (retirer uniquement la classe card-*) -->
<div class="card card-pink" ...>   → <div class="card" ...>
<div class="card card-teal" ...>   → <div class="card" ...>
<div class="card card-mint" ...>   → <div class="card" ...>
<div class="card card-yellow" ...> → <div class="card" ...>
<div class="card card-aqua" ...>   → <div class="card" ...>
```

Et le div admin emotions (ligne ~95) :
```html
<div class="card card-yellow">  →  <div class="card">
```

- [ ] **Step 4 : Ajouter la classe `bento-card-anim` aux 6 enfants du bento**

```html
<!-- 5 divs .card dans le bento : ajouter bento-card-anim -->
<div class="card bento-card-anim" style="grid-column: 1 / 2">   <!-- UPTIME -->
<div class="card bento-card-anim" style="grid-column: 2 / 3">   <!-- PLATEFORMES -->
<div class="card bento-card-anim" style="grid-column: 3 / 4">   <!-- MESSAGES -->
<div class="card bento-card-anim" style="grid-column: 1 / 3">   <!-- HUMEUR -->
<div class="card bento-card-anim" style="grid-column: 3 / 4" id="stream-card">   <!-- STREAM -->
<!-- graph-container : aussi bento-card-anim -->
<div class="graph-container bento-card-anim" style="grid-column: 1 / 4">
```

- [ ] **Step 5 : Vérification visuelle**

Ouvrir `http://<host-ip>:8080/`.
Attendu :
- Police Inter visible sur les labels `.card-title` (typographie sans-serif propre)
- Icônes ⏱ 📡 💬 🎭 📺 📈 devant chaque titre
- Toutes les cartes ont le même fond glassmorphism (plus de rose/teal/jaune)
- Stagger fade-in au rechargement (toutes les 6 cartes, y compris le graphe)

- [ ] **Step 6 : Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "style(dashboard): Inter font, card icons, remove colored card classes, bento-card-anim"
```

---

## Task 6 : JS — Constantes, emojis, buildGauges, loadStreamStatus, cleanup

**Files:**
- Modify: `bot/dashboard/static/app.js:10-20` (EMOTION_COLORS), `app.js:158-175` (buildGauges), `app.js:303-315` (loadStreamStatus), `app.js:620,643` (selectMemUser)

### Contexte
Mettre à jour les couleurs d'émotion, ajouter EMOTION_EMOJIS, ajouter les variables module `_graphMeta` / `_rafPending`, mettre à jour le texte des labels de gauges, le markup des badges Twitch, et les références `--card-yellow` dans l'onglet mémoire.

- [ ] **Step 1 : Remplacer `EMOTION_COLORS` (lignes 10-16)**

Remplacer le bloc `const EMOTION_COLORS = { … };` par :

```js
const EMOTION_COLORS = {
  anger:    '#FF4D4D',
  joy:      '#FFD700',
  curiosity:'#00E5A0',
  sadness:  '#4DA6FF',
  boredom:  '#AAAAAA',
};
```

- [ ] **Step 2 : Ajouter `EMOTION_EMOJIS` juste après `EMOTION_COLORS` (ligne ~16)**

Insérer après le bloc `EMOTION_COLORS` :

```js
const EMOTION_EMOJIS = {
  anger: '😤', joy: '😊', sadness: '😢', curiosity: '🤔', boredom: '😴',
};
```

- [ ] **Step 3 : Ajouter les variables module `_graphMeta` et `_rafPending` dans la section `// ── State`**

Dans le bloc `// ── State` (lignes ~22-29), ajouter après les `let` existants :

```js
let _graphMeta  = null;  // { history, tMin, tRange, PAD, gW, gH, W, H }
let _rafPending = false;
```

- [ ] **Step 4 : Mettre à jour le label dans `buildGauges()` (ligne ~165)**

Trouver cette ligne dans `buildGauges()` :
```js
<span class="emotion-label" style="color:${EMOTION_COLORS[e]}">${EMOTION_LABELS[e]}</span>
```
La remplacer par :
```js
<span class="emotion-label" style="color:${EMOTION_COLORS[e]}">${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
```

- [ ] **Step 5 : Mettre à jour `loadStreamStatus()` — innerHTML live et offline (lignes ~304-314)**

Remplacer le contenu de `el.innerHTML` dans les deux cas :

```js
// Cas live :
el.innerHTML = `
  <div class="stream-live-badge"><span class="dot"></span> LIVE</div>
  <div style="font-size:1.1rem;font-weight:700;margin-bottom:6px">${escHtml(d.title || '')}</div>
  <div style="color:var(--text-muted);margin-bottom:4px">${escHtml(d.category || '')}</div>
  <div style="font-size:1.5rem;font-weight:900;color:var(--c-curiosity)">${(d.viewers || 0).toLocaleString()} viewers</div>
`;

// Cas offline :
el.innerHTML = `
  <div class="stream-offline-badge"><span class="dot"></span> OFFLINE</div>
  ${d.started_at ? `<div style="color:var(--text-muted);margin-top:6px;font-size:0.85rem">Dernier stream : ${new Date(d.started_at).toLocaleString('fr')}</div>` : ''}
`;
```

- [ ] **Step 6 : Remplacer `var(--card-yellow)` + corriger les bordures (lignes ~620 et ~643-644)**

Dans `loadMemoryUsers()`, ligne ~620, remplacer :
```js
background:${selected ? 'var(--card-yellow)' : 'var(--card)'};border:2px solid ${selected ? 'var(--border)' : '#ddd'};
```
par :
```js
background:${selected ? 'var(--accent-soft)' : 'var(--card)'};border:1px solid ${selected ? 'var(--accent)' : 'var(--card-border)'};
```

Dans `selectMemUser()`, lignes ~643-644, remplacer :
```js
el.style.background  = selected ? 'var(--card-yellow)' : 'var(--card)';
el.style.borderColor = selected ? 'var(--border)' : '#ddd';
```
par :
```js
el.style.background  = selected ? 'var(--accent-soft)' : 'var(--card)';
el.style.borderColor = selected ? 'var(--accent)' : 'rgba(255,255,255,0.08)';
```

> Note : les autres `border:1.5px solid #ddd` dans `renderMemories` et `searchMemories` restent inchangés — l'onglet admin est hors scope per la spec.

- [ ] **Step 7 : Vérification visuelle**

Ouvrir `http://<host-ip>:8080/`.
Attendu :
- Jauges : labels avec emoji (😤 ANGER, 😊 JOY, etc.) et couleurs mises à jour
- Badge LIVE avec point vert animé, badge OFFLINE avec point rouge pulsé
- En mode admin → mémoire : utilisateur sélectionné surlignée en bleu translucide (pas jaune)

- [ ] **Step 8 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): EMOTION_COLORS updated, EMOTION_EMOJIS, dot badges, accent-soft selection"
```

---

## Task 7 : JS — `hexToRgba` + réécriture complète de `drawEmotionGraph`

**Files:**
- Modify: `bot/dashboard/static/app.js:220-293`

### Contexte
Ajouter le helper `hexToRgba`. Remplacer intégralement `drawEmotionGraph` par la nouvelle version : fond `#0f0f1c`, grille, ligne + area fill avec gradient, stockage dans `_graphMeta`.

- [ ] **Step 1 : Ajouter `hexToRgba` juste avant `drawEmotionGraph` (ligne ~228)**

Insérer avant `function drawEmotionGraph(history) {` :

```js
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
```

- [ ] **Step 2 : Remplacer intégralement `drawEmotionGraph` (lignes 229-293)**

Remplacer la fonction entière par :

```js
function drawEmotionGraph(history) {
  const canvas = document.getElementById('emotionCanvas');
  if (!canvas || !history || history.length < 2) return;

  const W = canvas.offsetWidth || 800;
  const H = 165;
  canvas.width  = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');

  // Fond sombre (--bg-alt)
  ctx.fillStyle = '#0f0f1c';
  ctx.fillRect(0, 0, W, H);

  const PAD = { top: 10, bottom: 40, left: 4, right: 4 };
  const gW = W - PAD.left - PAD.right;
  const gH = H - PAD.top - PAD.bottom;

  const tMin = history[0].snapshot_at;
  const tMax = history[history.length - 1].snapshot_at;
  const tRange = tMax - tMin || 1;

  // Stocker pour le tooltip
  _graphMeta = { history, tMin, tRange, PAD, gW, gH, W, H };

  // Grille — 4 lignes horizontales à 25/50/75/100%
  ctx.lineWidth = 1;
  for (let pct = 0.25; pct <= 1.0; pct += 0.25) {
    const y = PAD.top + (1 - pct) * gH;
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(W - PAD.right, y);
    ctx.stroke();
  }

  // Tracé ligne + area fill par émotion
  for (const e of EMOTIONS) {
    let firstX = 0, lastX = 0;

    // 1. Ligne (stroke)
    ctx.beginPath();
    ctx.strokeStyle = EMOTION_COLORS[e];
    ctx.lineWidth = 2;
    ctx.globalAlpha = 0.85;
    history.forEach((snap, i) => {
      const x = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
      const y = PAD.top  + (1 - (snap[e] ?? 0)) * gH;
      if (i === 0) { ctx.moveTo(x, y); firstX = x; }
      else ctx.lineTo(x, y);
      lastX = x;
    });
    ctx.stroke();

    // 2. Area fill (path séparé, gradient du haut vers le bas)
    ctx.beginPath();
    ctx.globalAlpha = 1;
    history.forEach((snap, i) => {
      const x = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
      const y = PAD.top  + (1 - (snap[e] ?? 0)) * gH;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.lineTo(lastX,  PAD.top + gH);
    ctx.lineTo(firstX, PAD.top + gH);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + gH);
    grad.addColorStop(0, hexToRgba(EMOTION_COLORS[e], 0.25));
    grad.addColorStop(1, hexToRgba(EMOTION_COLORS[e], 0.02));
    ctx.fillStyle = grad;
    ctx.fill();
  }

  ctx.globalAlpha = 1;

  // Axe temporel
  ctx.fillStyle = 'rgba(255,255,255,0.4)';
  ctx.font = '10px monospace';
  ctx.textAlign = 'left';
  const label0 = new Date(tMin * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' });
  const labelN = new Date(tMax * 1000).toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' });
  ctx.fillText(label0, PAD.left, H - 26);
  ctx.textAlign = 'right';
  ctx.fillText(labelN, W - PAD.right, H - 26);

  // Légende des émotions
  ctx.font = '9px monospace';
  const itemW = gW / EMOTIONS.length;
  EMOTIONS.forEach((e, i) => {
    const x = PAD.left + i * itemW;
    const ly = H - 10;
    ctx.strokeStyle = EMOTION_COLORS[e];
    ctx.lineWidth = 2;
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.moveTo(x, ly);
    ctx.lineTo(x + 14, ly);
    ctx.stroke();
    ctx.fillStyle = EMOTION_COLORS[e];
    ctx.textAlign = 'left';
    ctx.fillText(EMOTION_LABELS[e], x + 18, ly + 3);
  });
}
```

- [ ] **Step 3 : Vérification visuelle**

Ouvrir `http://<host-ip>:8080/`.
Attendu :
- Graphe : fond `#0f0f1c` (très sombre), pas de fond gris/blanc
- Grille : 4 lignes horizontales légères visibles
- Courbes avec area fill en dégradé (opaque en haut → transparent en bas)
- Légende en bas avec les nouvelles couleurs

- [ ] **Step 4 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): drawEmotionGraph rewrite — dark bg, grid, area fills, hexToRgba"
```

---

## Task 8 : JS — Tooltip au hover sur le graphe

**Files:**
- Modify: `bot/dashboard/static/app.js:539-559` (DOMContentLoaded)

### Contexte
Ajouter les listeners `mousemove` et `mouseleave` sur le canvas pour afficher un tooltip glassmorphism avec les 5 valeurs d'émotions au snapshot le plus proche. Utiliser `requestAnimationFrame` pour throttler les redraws.

- [ ] **Step 1 : Ajouter les listeners dans `DOMContentLoaded` (après ligne ~555)**

Dans le bloc `document.addEventListener('DOMContentLoaded', async () => { … })`, ajouter juste après `requestAnimationFrame(() => loadEmotionHistory())` :

```js
  // ── Tooltip hover sur le graphe ─────────────────────────────────────────
  const emotionCanvas = document.getElementById('emotionCanvas');
  emotionCanvas.addEventListener('mousemove', (ev) => {
    if (!_graphMeta || _rafPending) return;
    _rafPending = true;
    requestAnimationFrame(() => {
      _rafPending = false;
      const { history, tMin, tRange, PAD, gW, gH, W, H } = _graphMeta;
      const rect = emotionCanvas.getBoundingClientRect();
      const mouseX = ev.clientX - rect.left;

      // Trouver le snapshot dont la position X canvas est la plus proche du curseur
      let nearest = null, minDist = Infinity;
      for (const snap of history) {
        const sx = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
        const dist = Math.abs(sx - mouseX);
        if (dist < minDist) { minDist = dist; nearest = snap; }
      }

      // Redessiner le graphe complet, puis superposer le tooltip
      drawEmotionGraph(history);
      if (!nearest) return;

      const ctx = emotionCanvas.getContext('2d');
      const tw = 140;
      const th = 12 + EMOTIONS.length * 16 + 8;
      const tx = Math.min(mouseX + 12, W - tw - 4);
      const ty = 8;

      // Fond glassmorphism — roundRect dispo Chrome 99+ / Firefox 112+ / Safari 15.4+
      ctx.fillStyle = 'rgba(11,11,20,0.85)';
      ctx.strokeStyle = 'rgba(0,212,255,0.3)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(tx, ty, tw, th, 8);
      ctx.fill();
      ctx.stroke();

      // Valeurs d'émotions
      ctx.textAlign = 'left';
      ctx.font = '10px monospace';
      EMOTIONS.forEach((e, i) => {
        ctx.fillStyle = EMOTION_COLORS[e];
        ctx.fillText(
          `${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}: ${(nearest[e] ?? 0).toFixed(2)}`,
          tx + 8, ty + 16 + i * 16
        );
      });
    });
  });
  emotionCanvas.addEventListener('mouseleave', () => {
    if (_graphMeta) drawEmotionGraph(_graphMeta.history);
  });
```

- [ ] **Step 2 : Vérification visuelle**

Ouvrir `http://<host-ip>:8080/`, survoler le graphe avec la souris.
Attendu :
- Un tooltip glassmorphism apparaît (fond sombre, bordure cyan)
- Affiche les 5 valeurs d'émotions avec emojis et couleurs par émotion
- Tooltip se repositionne au survol, disparaît au mouseout
- Aucune erreur console

- [ ] **Step 3 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): canvas tooltip on hover — glassmorphism overlay with emotion values"
```

---

## Vérification finale

- [ ] Recharger `http://<host-ip>:8080/` et vérifier les 8 points de la checklist du spec :
  1. 6 cartes bento glassmorphism (fond translucide, blur)
  2. Valeurs uptime et messages en `#00D4FF`
  3. Jauges : glow sur fills, track sombre, emojis sur labels
  4. Graphe : fond `#0f0f1c`, area fills, grille, légende, tooltip au hover
  5. Badge BIENTÔT shimmer, tab actif cyan
  6. Badges Twitch animés (pulse offline, scale online)
  7. Fade-in stagger au chargement (6 cards)
  8. Mode admin inchangé visuellement (config, logs, mémoire fonctionnels)

- [ ] Vérifier la console navigateur (F12) : aucune erreur JavaScript

- [ ] Si des problèmes visuels subsistent, consulter la spec : `docs/superpowers/specs/2026-03-17-dashboard-glassmorphism-design.md`
