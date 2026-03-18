# Dashboard Redesign — Neo-Brutalism Warm Pastel

**Date:** 2026-03-17
**Status:** Approved
**Scope:** `bot/dashboard/static/style.css`, `bot/dashboard/static/index.html`, `bot/dashboard/static/app.js`

---

## Context

The Wally dashboard currently uses a dark neo-brutalism style (black background, white 3px borders, hard white shadows, zero border-radius, Courier New font). The redesign keeps the neo-brutalism DNA — thick borders, hard drop shadows, bold monospace typography — but shifts the aesthetic to be warmer and more inviting: light cream background, vivid pastel cards per section, dark (#111) borders and shadows, 14px border-radius.

No backend changes are needed. All changes are in the three static files.

---

## Design Decisions

### 1. Background & Base

| Property | Old | New |
|---|---|---|
| Body background | `#0f0f0f` | `#fafaf8` (cream) |
| Card background | `#1a1a1a` | Per-card accent color |
| Header background | `#0f0f0f` | `#ffffff` |
| Text color | `#ffffff` | `#111111` |
| Muted text | `#aaaaaa` | `#666666` |

### 2. Neo-Brutalism Parameters (unchanged)

- **Borders:** `2.5px solid #111` (was 3px solid #fff)
- **Hard shadows:** `4px 4px 0 #111` (was 4px 4px 0 #fff)
- **Font:** `'Courier New', monospace` — preserved entirely
- **Letter spacing, uppercase labels** — preserved

### 3. Border Radius

- Cards, header, modals, log stream: **`14px`**
- Buttons: **`10px`**
- Mode toggle: **`8px`** (pill split)
- Tab bar active indicator: **`6px`**
- Gauge tracks: **`4px`**
- Inputs/selects: **`8px`**

### 4. Color Palette — Colorblock Pop

Each card has a dedicated background color matching its semantic role:

| Card | Color | Hex |
|---|---|---|
| Uptime / primary metric | Rose framboise | `#ff6b9d` |
| Plateformes / connexions | Turquoise | `#4ecdc4` |
| Humeur / émotions | Jaune soleil | `#ffe66d` |
| Stream / Twitch | Aqua | `#a8edea` |
| Stats / messages | Menthe | `#b7f5c8` |
| Config sections | Blanc | `#ffffff` (use `var(--card)` — the generic white card variable) |
| Mémoire selected | Jaune soleil | `#ffe66d` |
| Succès / positif | Menthe | `#b7f5c8` |
| Danger / erreur | Rose pâle | `#fee2e2` |

Emotion gauge fill colors (unchanged functionally, adjusted for light bg):

| Emotion | Color |
|---|---|
| anger | `#e63946` |
| joy | `#ffd60a` |
| curiosity | `#2dc653` |
| sadness | `#0096c7` |
| boredom | `#9ca3af` |

### 5. CSS Variables — New Token Set

```css
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
  --radius-tab: 6px;    /* stream/stream-offline badges; one-off tab indicators */
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

### 6. Component Changes

**Header**
- White background, bottom border `3px solid #111`, box-shadow `0 2px 0 #111`
- Logo: `WALLY` with accent letter (e.g. `A`) in `--card-pink`, adds `🤖` emoji
- Mode toggle: pill-shaped, active = `background:#111; color:#fafaf8`

**Tab bar**
- Background `#fafaf8`, bottom border `3px solid #111`
- Active tab: `background:#111; color:#fafaf8; border-radius: 0` — the tab element itself has no rounding (it fills the full tab bar height flush with the bottom border)
- The `--radius-tab: 6px` from Section 3 is used on stream badges and similar pill labels, not on the tab active element
- Hover: `background:#eee`

**Cards**
- `border: 2.5px solid #111; border-radius: 14px; box-shadow: 4px 4px 0 #111`
- Background set via `.card-pink`, `.card-teal`, `.card-yellow`, `.card-aqua`, `.card-mint` utility classes
- Card title (label): `font-size: 0.52rem; letter-spacing: 2px; color: rgba(0,0,0,0.5)`
- Card value: `font-size: 1.8rem; font-weight: 900; color: #111`

**Emotion Gauges**
- Track background: `rgba(0,0,0,0.12)` with `border: 1.5px solid rgba(0,0,0,0.15); border-radius: 4px`
- Fill: vivid emotion colors (see table above), `border-radius: 3px`
- Height reduced to `10px` (was `18px` — slimmer but clearer on light bg)

**Buttons**
- Default: `background:#fff; border: 2.5px solid #111; border-radius: 10px; box-shadow: 3px 3px 0 #111`
- `.btn-success` → `background: var(--card-mint)`
- `.btn-danger` → `background: #fee2e2; border-color: #dc2626; color: #dc2626`
- `.btn-info` → `background: var(--card-aqua)`
- Hover: `box-shadow: none; transform: translate(3px, 3px)` — preserved

**Inputs & Selects**
- `background: #fff; border: 2px solid #111; border-radius: 8px; box-shadow: 2px 2px 0 #111`
- Focus: `border-color: #111` (unchanged, already sharp)

**Log Stream**
- Background: `#ffffff` (was `#000`)
- Text colors: INFO `#555`, WARNING `#b45309` (amber), ERROR `#dc2626`
- Border/shadow: same dark neo-brut style

**Toasts**
- `.toast.success` → `background: var(--card-mint); color: #111; border-color: #111`
- `.toast.error` → `background: #fee2e2; color: #dc2626; border-color: #dc2626`

**Auth Modal**
- Background: `#fff`; border + shadow dark style with `--radius`
- Overlay: `rgba(0,0,0,0.6)`

**Graph Container**
- Background: `#fff`; border + shadow dark; `border-radius: 14px`
- Canvas background: `#fff` (was `#111`)

**Memory Tab**
- Sidebar: `border-right: 2px solid #eee`; user items as cards with `border-radius: 8px`
- Selected user item: `background: var(--card-yellow); border: 2px solid #111; box-shadow: 2px 2px 0 #111`
- Memory entries: white cards with `border: 1.5px solid #ddd; border-radius: 8px`
- Delete button: red `✕` text (no background)

**Stream badges**
- LIVE: `background: var(--card-pink); border: 2px solid #111; border-radius: 6px`
- OFFLINE: `background: #eee; border: 2px solid #999; border-radius: 6px`

---

## Additional Improvements

Beyond the color/radius reskin, the following UX improvements are included:

1. **Card color coding** — each card type has a semantic color so scanning is instant
2. **Graph canvas on white** — emotion lines on `#fff` background with vivid colors (no `#111` dark canvas)
3. **Log stream on white** — dramatically more readable; color-coded by log level (amber/red/grey)
4. **Memory entry cards** — styled consistently with the rest of the dashboard
5. **Logo accent** — first unique letter gets `--card-pink` color, small emoji for warmth
6. **Gauge height** — adjusted to `10px` for better proportion on light background
7. **Emotion summary text** — `color: rgba(0,0,0,0.55)` instead of muted grey
8. **Config section titles** — dark border-bottom on white bg (was yellow on dark)

---

## File Scope

| File | Changes |
|---|---|
| `bot/dashboard/static/style.css` | Full rewrite of CSS variables and all component styles |
| `bot/dashboard/static/index.html` | Add color utility classes to card elements; update emotion/stream/memory markup minimally |
| `bot/dashboard/static/app.js` | Update `EMOTION_COLORS` hex values to match the new palette table (e.g. joy `#ffdd00` → `#ffd60a`, anger `#ff3333` → `#e63946`, etc.); update inline styles in JS-rendered HTML (memory tab, config form, stream card, canvas `fillStyle`) |

---

## Non-Goals

- No layout changes (grid, tab structure, sidebar vs. top-nav remain identical)
- No new features or backend routes
- No font change (Courier New preserved throughout)
- No mobile-specific breakpoint redesign beyond what already exists

---

## Testing

- Visual review in browser at `http://localhost:8080` (dashboard port)
- Check all 4 public tabs: STATUT, HUMEUR, STREAM, STATS
- Check all 4 admin tabs: CONFIG, HUMEUR, LOGS, MÉMOIRE
- Verify auth modal renders correctly on light background
- Verify toast messages (success/error) are readable
- Verify emotion gauges update correctly via SSE
- Verify graph canvas renders on white background (canvas `fillStyle` must be `#fff`, not `#111`)
- Verify `EMOTION_COLORS` in `app.js` produces correct line colors on the canvas graph
