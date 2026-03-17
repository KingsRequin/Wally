# Dashboard — Glassmorphism Redesign

**Date:** 2026-03-17
**Status:** Approved
**Scope:** `bot/dashboard/static/style.css`, `bot/dashboard/static/index.html`, `bot/dashboard/static/app.js`

---

## Contexte

Refonte visuelle complète du dashboard : abandon du neo-brutalism pastel au profit d'un style glassmorphism sombre avec accent cyan `#00D4FF`. Changements purement frontend — aucun backend modifié.

---

## 1. Variables CSS — Nouveau token set

Remplacer intégralement le bloc `:root` actuel :

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

**Supprimées** : `--card-pink`, `--card-teal`, `--card-yellow`, `--card-aqua`, `--card-mint`, `--shadow-btn` (remplacé), `--c-anger/joy/curiosity/sadness/boredom` anciens.

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

Remplacer les règles `.card` et `.card-*` :

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

**Supprimer** les classes `.card-pink`, `.card-teal`, `.card-yellow`, `.card-aqua`, `.card-mint` du CSS et de `index.html` (retirer ces classes des divs du bento).

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

Les icônes (⏱ 📡 💬) sont ajoutées directement dans le texte des `.card-title` dans `index.html`.

---

## 5. Jauges d'émotions

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

Dans `app.js`, `buildGauges()` — ajouter un préfixe emoji par émotion :

```js
const EMOTION_EMOJIS = {
  anger: '😤', joy: '😊', sadness: '😢', curiosity: '🤔', boredom: '😴',
};
```

Le label affiche `${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}`.

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

---

## 7. Badges Twitch

```css
/* Pulse offline */
@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255,77,77,0.7); }
  50%       { box-shadow: 0 0 0 6px rgba(255,77,77,0); }
}
.stream-offline-badge .dot {
  animation: pulse-red 2s ease-in-out infinite;
}

/* Scale online */
@keyframes scale-green {
  0%, 100% { transform: scale(1); }
  50%       { transform: scale(1.15); }
}
.stream-live-badge .dot {
  animation: scale-green 1.5s ease-in-out infinite;
}
```

Le dot est un `<span class="dot">` ajouté dans `loadStreamStatus()` en JS.

---

## 8. Graphe canvas — Area chart + tooltip

### `drawEmotionGraph()` — modifications dans `app.js`

**Area chart avec gradient :**
Pour chaque émotion, après le tracé de la ligne :
```js
// Gradient fill sous la courbe
const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + gH);
grad.addColorStop(0, hexToRgba(EMOTION_COLORS[e], 0.3));
grad.addColorStop(1, hexToRgba(EMOTION_COLORS[e], 0.03));
ctx.fillStyle = grad;
// Fermer le path vers le bas
ctx.lineTo(lastX, PAD.top + gH);
ctx.lineTo(firstX, PAD.top + gH);
ctx.closePath();
ctx.fill();
```

Helper `hexToRgba(hex, alpha)` — convertit `#RRGGBB` → `rgba(r,g,b,alpha)`.

**Grille :**
```js
// 4 lignes horizontales à 25/50/75/100%
ctx.strokeStyle = 'rgba(255,255,255,0.08)';
ctx.lineWidth = 1;
```

**Tooltip au hover :**
- Ajouter un `mousemove` listener sur le canvas dans `DOMContentLoaded`
- Sur mousemove : trouver le point historique le plus proche par interpolation temporelle
- Dessiner un tooltip glassmorphism (fond `rgba(11,11,20,0.85)`, border `rgba(0,212,255,0.3)`, `border-radius: 8px`) avec les 5 valeurs d'émotions
- Utiliser `requestAnimationFrame` pour throttler les redraws
- Cacher le tooltip au `mouseleave`

Le listener stocke les données `history` dans une variable de module `_graphHistory` pour y accéder depuis le handler.

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

## 10. Nettoyage des overrides dark-mode devenus obsolètes

Supprimer les blocs suivants de `style.css` (devenus sans objet) :
- `.card:not(.card-pink)...card-title` / `.card-value`
- `.graph-container .card-title`
- `.card-pink .gauge-val`, `.card-teal .gauge-val`… (tous les overrides colorés)
- `.card-pink .emotion-label`… etc.

---

## Fichiers modifiés

| Fichier | Changements |
|---|---|
| `style.css` | Nouveau `:root`, glassmorphism `.card`, nouvelle typo, nouvelles jauges, tabs, badges Twitch, animations, nettoyage overrides |
| `index.html` | Import Inter, icônes dans card-title, suppression classes card-*, ajout classe `.bento-card-anim` |
| `app.js` | `EMOTION_EMOJIS`, `EMOTION_COLORS` mis à jour, `buildGauges` avec emojis, `drawEmotionGraph` area+gradient+grille+tooltip, `_graphHistory` module var, mousemove listener |

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
- Vérifier le graph : fond sombre, area fills, légende, tooltip au hover
- Vérifier badge BIENTÔT shimmer, tab actif cyan
- Vérifier badges Twitch animés (pulse offline, scale online)
- Vérifier fade-in au chargement (stagger visible)
- Vérifier mode admin inchangé visuellement
