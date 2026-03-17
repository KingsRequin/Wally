# Dashboard — Glassmorphism Redesign

**Date:** 2026-03-17
**Status:** Approved
**Scope:** `bot/dashboard/static/style.css`, `bot/dashboard/static/index.html`, `bot/dashboard/static/app.js`

---

## Contexte

Refonte visuelle complète du dashboard : abandon du neo-brutalism pastel au profit d'un style glassmorphism sombre avec accent cyan `#00D4FF`. Changements purement frontend — aucun backend modifié.

---

## 1. Variables CSS — Nouveau token set

Remplacer intégralement le bloc `:root` actuel. Les variables `--card-pink`, `--card-teal`, `--card-yellow`, `--card-aqua`, `--card-mint` sont supprimées. Les variables `--c-anger/joy/curiosity/sadness/boredom` sont mises à jour. `--shadow-btn` est conservé.

```css
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

  /* Émotions — nouvelles couleurs avec glow */
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

---

## 2. Import de police — Google Fonts

Ajouter dans `<head>` de `index.html`, avant le `<link rel="stylesheet">` :

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
```

---

## 3. Cartes — Glassmorphism

Remplacer les règles `.card` et supprimer toutes les règles `.card-pink`, `.card-teal`, `.card-yellow`, `.card-aqua`, `.card-mint` (voir section 10 pour la liste complète) :

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

Dans `index.html`, retirer les classes `card-pink`, `card-teal`, `card-yellow`, `card-aqua`, `card-mint` des six divs du bento.

---

## 4. Typographie — Hiérarchie visuelle

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

Mettre à jour les `.card-title` dans `index.html` en ajoutant une icône en préfixe :

| Carte | Nouveau texte |
|---|---|
| UPTIME | `⏱ UPTIME` |
| PLATEFORMES | `📡 PLATEFORMES` |
| MESSAGES TRAITÉS | `💬 MESSAGES TRAITÉS` |
| HUMEUR EN DIRECT | `🎭 HUMEUR EN DIRECT` |
| AZRAEL_TTV (stream card) | `📺 AZRAEL_TTV` |
| DERNIÈRES 24H (graph) | `📈 DERNIÈRES 24H` |

---

## 5. Jauges d'émotions

### Constante EMOTION_COLORS mise à jour dans `app.js`

Remplacer les valeurs actuelles de `EMOTION_COLORS` (qui sont `#e63946`, `#ffd60a`, etc.) par :

```js
const EMOTION_COLORS = {
  anger:    '#FF4D4D',
  joy:      '#FFD700',
  curiosity:'#00E5A0',
  sadness:  '#4DA6FF',
  boredom:  '#AAAAAA',
};
```

### Couleurs et glow des fills

```css
.gauge-fill.anger     { background: var(--c-anger);    box-shadow: 0 0 8px rgba(255, 77, 77, 0.53); }
.gauge-fill.joy       { background: var(--c-joy);      box-shadow: 0 0 8px rgba(255, 215, 0, 0.53); }
.gauge-fill.curiosity { background: var(--c-curiosity);box-shadow: 0 0 8px rgba(0, 229, 160, 0.53); }
.gauge-fill.sadness   { background: var(--c-sadness);  box-shadow: 0 0 8px rgba(77, 166, 255, 0.53); }
.gauge-fill.boredom   { background: var(--c-boredom);  box-shadow: none; }

.gauge-fill {
  transition: width 0.6s ease;
}
```

### Track

```css
.gauge-track {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-xs);
}
```

### Emoji dans les labels

Dans `app.js`, ajouter la constante `EMOTION_EMOJIS` (juste après `EMOTION_COLORS`) :

```js
const EMOTION_EMOJIS = {
  anger: '😤', joy: '😊', sadness: '😢', curiosity: '🤔', boredom: '😴',
};
```

Dans `buildGauges()`, modifier la ligne qui génère le label pour afficher `${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}`.

### Résumé textuel

```css
.emotion-summary {
  font-style: italic;
  text-align: center;
  opacity: 0.6;
  margin-top: 12px;
}
```

---

## 6. Navigation tabs

```css
/* Tab actif */
.tab-btn.active {
  color: var(--accent);
  border-bottom: 2px solid var(--accent);
  background: transparent;
}

/* Badge shimmer */
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
}
```

Remplacer intégralement la règle `.badge-soon` existante (qui utilise `background: var(--card-yellow)`) par ce bloc.

---

## 7. Badges Twitch

### CSS — remplacement complet des règles `.stream-live-badge` et `.stream-offline-badge`

```css
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

### JS — mise à jour de `loadStreamStatus()`

Modifier les deux blocs `innerHTML` pour inclure `<span class="dot"></span>` :

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

---

## 8. Graphe canvas — Area chart + tooltip

### Helper `hexToRgba`

Ajouter cette fonction dans `app.js` (juste avant `drawEmotionGraph`) :

```js
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
```

### Variables de module pour le tooltip

Ajouter en tête de module (à côté des autres `const` globaux) :

```js
let _graphMeta = null;  // { history, tMin, tRange, PAD, gW, gH, W, H }
let _rafPending = false;
```

### Remplacement complet de `drawEmotionGraph(history)`

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

### Tooltip au hover — listeners dans `DOMContentLoaded`

Ajouter après le `requestAnimationFrame(() => loadEmotionHistory())` initial :

```js
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

    // Fond glassmorphism
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

---

## 9. Animations de chargement

```css
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.bento-card-anim {
  animation: fadeIn 0.4s ease forwards;
  opacity: 0;
}
```

Dans `index.html`, ajouter la classe `.bento-card-anim` à chaque card du bento. Dans `style.css`, stagger via `nth-child` :

```css
.bento-grid > *:nth-child(1) { animation-delay: 0.0s; }
.bento-grid > *:nth-child(2) { animation-delay: 0.1s; }
.bento-grid > *:nth-child(3) { animation-delay: 0.2s; }
.bento-grid > *:nth-child(4) { animation-delay: 0.3s; }
.bento-grid > *:nth-child(5) { animation-delay: 0.4s; }
.bento-grid > *:nth-child(6) { animation-delay: 0.5s; }
```

---

## 10. Nettoyage — liste exhaustive des sélecteurs à modifier/supprimer

### Dans le bloc `:root`

Supprimer les 5 variables : `--card-pink`, `--card-teal`, `--card-yellow`, `--card-aqua`, `--card-mint`.

### Règles à supprimer entièrement

| Sélecteur(s) | Action |
|---|---|
| `.card-pink { background: var(--card-pink); color: #111; }` | Supprimer |
| `.card-teal { background: var(--card-teal); color: #111; }` | Supprimer |
| `.card-yellow { background: var(--card-yellow); color: #111; }` | Supprimer |
| `.card-aqua { background: var(--card-aqua); color: #111; }` | Supprimer |
| `.card-mint { background: var(--card-mint); color: #111; }` | Supprimer |
| `.card-pink .gauge-track, .card-teal .gauge-track, .card-yellow .gauge-track, .card-aqua .gauge-track, .card-mint .gauge-track { … }` | Supprimer |
| `.card:not(.card-pink):not(.card-teal):not(.card-yellow):not(.card-aqua):not(.card-mint) .card-title { … }` | Supprimer |
| `.card:not(.card-pink):not(.card-teal):not(.card-yellow):not(.card-aqua):not(.card-mint) .card-value { … }` | Supprimer |
| `.graph-container .card-title { color: rgba(205,214,244,0.55); }` | Supprimer |
| `.card-pink .gauge-val, .card-teal .gauge-val, … .card-mint .gauge-val { color: #111; }` | Supprimer |
| `.card-pink .emotion-label, .card-teal .emotion-label, … .card-mint .emotion-label { color: #111; }` | Supprimer |
| `.card-pink .emotion-summary, .card-teal .emotion-summary, … .card-mint .emotion-summary { color: rgba(0,0,0,0.55); }` | Supprimer |

### Règles à mettre à jour

| Sélecteur | Propriété modifiée |
|---|---|
| `.logo .logo-accent` | `color: var(--card-pink)` → `color: var(--accent)` |
| `.badge-soon` | Remplacer entièrement par le bloc de la section 6 |
| `.stream-live-badge` | Remplacer entièrement par le bloc de la section 7 |
| `.stream-offline-badge` | Remplacer entièrement par le bloc de la section 7 |
| `.btn-success` | `background: var(--card-mint)` → `background: rgba(0,229,160,0.15); color: var(--c-online); border-color: var(--c-online);` |
| `.btn-info` | `background: var(--card-aqua)` → `background: rgba(0,212,255,0.15); color: var(--accent); border-color: var(--accent);` |
| `.toast.success` | `background: var(--card-mint)` → `background: rgba(0,229,160,0.15); border-color: var(--c-online);` |

---

## Fichiers modifiés

| Fichier | Changements |
|---|---|
| `style.css` | Nouveau `:root`, glassmorphism `.card`, nouvelle typo, nouvelles jauges, tabs shimmer, badges Twitch glassmorphism + animations, animations fadeIn stagger, nettoyage complet overrides |
| `index.html` | Import Inter, icônes dans card-title (6 cartes), suppression classes `card-*`, ajout classe `.bento-card-anim` |
| `app.js` | `EMOTION_COLORS` mis à jour, `EMOTION_EMOJIS` ajouté, `buildGauges` avec emojis, `hexToRgba` helper, `_graphMeta`/`_rafPending` vars, `drawEmotionGraph` réécriture complète (area+gradient+grille+bg sombre), mousemove/mouseleave listeners + tooltip, `loadStreamStatus` innerHTML avec `.dot` span |

---

## Non-objectifs

- Pas de changement backend
- Pas de modification du mode admin (onglets admin conservent leur style existant à l'identique)
- Pas de responsive redesign au-delà du breakpoint 600px existant

---

## Tests

- Vérifier les 6 cartes bento en glassmorphism (fond translucide, blur)
- Vérifier que les valeurs (uptime, messages) s'affichent en `#00D4FF`
- Vérifier les jauges : glow sur fills, track sombre, emojis sur labels
- Vérifier le graph : fond `#0f0f1c`, area fills dégradés, grille, légende, tooltip au hover avec les 5 valeurs
- Vérifier badge BIENTÔT shimmer, tab actif cyan
- Vérifier badges Twitch animés (pulse offline, scale online) avec `.dot` span
- Vérifier fade-in au chargement (stagger 6 cards)
- Vérifier mode admin inchangé visuellement
