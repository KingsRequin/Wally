# Dashboard Dark Mode — Design Spec

**Date:** 2026-03-17
**Scope:** `bot/dashboard/static/style.css` uniquement

---

## Objectif

Convertir le dashboard Wally en dark mode permanent en conservant l'esthétique Neo-Brutalism
(bordures épaisses, ombres dures, zéro dégradé) et les cartes colorées.

---

## Palette — Catppuccin Mocha

### Variables `:root` à remplacer

| Variable | Valeur actuelle | Nouvelle valeur | Rôle |
|---|---|---|---|
| `--bg` | `#fafaf8` | `#1e1e2e` | Fond principal |
| `--bg-alt` | `#f0ede8` | `#181825` | Fond alternatif (inputs, log stream) |
| `--card` | `#ffffff` | `#313244` | Fond des cartes neutres |
| `--border` | `#111111` | `#cdd6f4` | Bordures et ombres (lavande) |
| `--shadow` | `4px 4px 0px #111111` | `4px 4px 0px #cdd6f4` | Ombre dure principale |
| `--shadow-sm` | `2px 2px 0px #111111` | `2px 2px 0px #cdd6f4` | Ombre dure petite |
| `--shadow-btn` | `3px 3px 0px #111111` | `3px 3px 0px #cdd6f4` | Ombre dure boutons |
| `--text` | `#111111` | `#cdd6f4` | Texte principal |
| `--text-muted` | `#666666` | `#6c7086` | Texte secondaire |

### Couleurs des cartes — Catppuccin pastel

| Variable | Valeur actuelle | Nouvelle valeur |
|---|---|---|
| `--card-pink` | `#ff6b9d` | `#f38ba8` |
| `--card-teal` | `#4ecdc4` | `#94e2d5` |
| `--card-yellow` | `#ffe66d` | `#f9e2af` |
| `--card-aqua` | `#a8edea` | `#89dceb` |
| `--card-mint` | `#b7f5c8` | `#a6e3a1` |

### Couleurs des émotions — Catppuccin

| Variable | Valeur actuelle | Nouvelle valeur |
|---|---|---|
| `--c-anger` | `#e63946` | `#f38ba8` |
| `--c-joy` | `#ffd60a` | `#f9e2af` |
| `--c-curiosity` | `#2dc653` | `#a6e3a1` |
| `--c-sadness` | `#0096c7` | `#89b4fa` |
| `--c-boredom` | `#9ca3af` | `#585b70` |
| `--c-online` | `#16a34a` | `#a6e3a1` |
| `--c-offline` | `#dc2626` | `#f38ba8` |

---

## Corrections des couleurs hardcodées

Ces couleurs sont inscrites en dur dans le CSS (hors variables) et doivent être mises à jour :

| Sélecteur | Propriété | Valeur actuelle | Nouvelle valeur |
|---|---|---|---|
| `.tab-btn` | `border-right` | `1px solid #ddd` | `1px solid rgba(205,214,244,0.15)` |
| `.tab-btn:hover:not(.active)` | `background` | `#eee` | `#313244` |
| `.tab-btn.disabled` | `color` | `#bbb` | `#45475a` |
| `.gauge-track` | `background` | `rgba(0,0,0,0.12)` | `rgba(255,255,255,0.08)` |
| `.gauge-track` | `border` | `1.5px solid rgba(0,0,0,0.15)` | `1.5px solid rgba(255,255,255,0.12)` |
| `.emotion-summary` | `color` | `rgba(0,0,0,0.55)` | `rgba(205,214,244,0.6)` |
| `.btn-danger` | `background` | `#fee2e2` | `#3d1522` |
| `.stream-offline-badge` | `background` | `#eee` | `#313244` |
| `.stream-offline-badge` | `border-color` | `#999` | `#45475a` |
| `.log-entry.INFO` | `color` | `#555` | `#a6adc8` |
| `.log-entry.WARNING` | `color` | `#b45309` | `#f9e2af` |
| `.toast.error` | `background` | `#fee2e2` | `#3d1522` |

---

## Règles additionnelles

### Titres de cartes sur fond sombre

`.card-title` est en `rgba(0,0,0,0.5)` — lisible sur les cartes colorées (pastels clairs).
Pour les cartes neutres (`--card` = `#313244`), ajouter :

```css
.card:not(.card-pink):not(.card-teal):not(.card-yellow):not(.card-aqua):not(.card-mint) .card-title {
  color: rgba(205,214,244,0.55);
}
```

De même pour `.card-value` et `.graph-container .card-title`.

### Valeurs des jauges sur fond sombre

`.gauge-val` est en `var(--text)`. Sur cartes colorées (jaune), surcharger en `#111`.
Sur cartes neutres, `var(--text)` = `#cdd6f4` est correct.

### Input background

`input`, `select`, `textarea` : changer `background: var(--card)` → `background: var(--bg-alt)`
pour un léger contraste avec les cartes.

---

## Contraintes

- **Aucun changement HTML ni JS** — modifications CSS uniquement
- **Dark mode permanent** — pas de toggle, pas de media query `prefers-color-scheme`
- **Style Neo-Brutalism conservé** — ombres dures, bordures épaisses, zéro border-radius supplémentaire
- **Cartes colorées** : texte en `#111` sur fond pastel (contraste suffisant), texte clair sur fond sombre
