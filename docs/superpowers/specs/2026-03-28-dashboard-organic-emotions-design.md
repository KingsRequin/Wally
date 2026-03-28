# Dashboard Organic Emotions — Design Spec

**Date**: 2026-03-28
**Objective**: Expose the organic emotion system (mood, fatigue, secondary emotions) in the existing dashboard Status tab, providing real-time monitoring and natural-language state summaries.

**Guiding principle**: Minimal visual footprint. The new data enriches the existing UI without cluttering it — text summaries over new charts, contextual information over raw numbers.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Mood + Fatigue Line](#2-mood--fatigue-line)
3. [Emotional State Block](#3-emotional-state-block)
4. [Secondary Emotion Markers on Graph](#4-secondary-emotion-markers-on-graph)
5. [API Changes](#5-api-changes)
6. [Frontend Implementation](#6-frontend-implementation)
7. [Files Impacted](#7-files-impacted)
8. [What Does NOT Change](#8-what-does-not-change)

---

## 1. Overview

Three additions to the Status tab:

```
+-----------------------------------------------+
|  HUMEUR EN DIRECT (existing gauges)            |
|  😤 ANGER    ████████████░░░░░░░  0.65         |
|  😊 JOY      █████░░░░░░░░░░░░░  0.30         |
|  😢 SADNESS  █░░░░░░░░░░░░░░░░░  0.05         |
|  🤔 CURIOSITY████████░░░░░░░░░░  0.50         |
|  😴 BOREDOM  ███████░░░░░░░░░░░  0.45         |
|  ─────────────────────────────────────         |
|  HUMEUR DE FOND irritable, curieux | FATIGUE   | ← NEW: mood/fatigue line
|  colère en récupération (43%)                  |
+-----------------------------------------------+
|  ÉTAT ÉMOTIONNEL                               | ← NEW: natural language block
|  "Wally est frustré et sur ses gardes.         |
|   Sa colère est en récupération après un pic." |
+-----------------------------------------------+
|  GRAPH (existing canvas)                       |
|  ┊ frustration   ┊ nostalgie  ┊               | ← NEW: secondary markers
|  ───────────────────────────────────           |
+-----------------------------------------------+
```

---

## 2. Mood + Fatigue Line

### Position

Directly under the 5 primary emotion gauges, separated by a thin `rgba(255,255,255,0.06)` border-top.

### Content

```
HUMEUR DE FOND  {mood_labels}  |  FATIGUE  {fatigue_label}
```

- **Mood labels**: Top 1-2 mood dimensions >= 0.2, as French adjectives:
  - anger → "irritable", joy → "joyeux", sadness → "mélancolique", curiosity → "curieux", boredom → "apathique"
- **Fatigue label**: `"{émotion_fr} en récupération ({pct}%)"` for each fatigue > 0
  - emotion_fr: anger → "colère", joy → "joie", sadness → "tristesse", curiosity → "curiosité", boredom → (never fatigued)
- **Separator**: `|` character with `rgba(255,255,255,0.25)` color

### Visibility Rules

- If no mood >= 0.2 AND no fatigue > 0: entire line is hidden (`display: none`)
- If mood present but no fatigue: show only mood part, no separator
- If fatigue present but no mood >= 0.2: show only fatigue part

### Styling

- Labels ("HUMEUR DE FOND", "FATIGUE"): `font-size: 11px; letter-spacing: 0.5px; color: rgba(255,255,255,0.4); text-transform: uppercase`
- Values: `font-size: 12px; color: rgba(255,255,255,0.7)`
- Fatigue values: colored with the emotion's color at 70% opacity (e.g., anger fatigue → `rgba(239,68,68,0.7)`)

---

## 3. Emotional State Block

### Position

New glassmorphism card below the mood/fatigue line, inside the existing "HUMEUR EN DIRECT" card or as a separate small card directly after.

### Content

A single natural-language sentence describing Wally's current emotional state, generated client-side in JavaScript.

### Generation Logic (JS)

Priority-ordered rules — first matching rule produces the sentence:

1. **Secondary emotion active (intensity >= 0.4)**:
   - `"Wally est {secondary_adj}."`
   - If fatigue also active: `"Wally est {secondary_adj}. Sa {emotion_fr} est en récupération après un pic."`
   - If mood dissonance (dominant mood ≠ dominant emotion): append `" Fond {mood_adj} malgré tout."`

2. **Fatigue active but no secondary**:
   - `"Wally est dans un état normal. Sa {emotion_fr} est en récupération."`

3. **Mood dissonance (dominant mood ≠ dominant emotion, both >= 0.3)**:
   - `"Wally est {emotion_adj} en surface mais {mood_adj} en profondeur."`

4. **Default**:
   - `"Wally est dans un état neutre."` (or hidden entirely if nothing interesting)

### French Labels

Secondary emotions:
| Key | Adjective |
|---|---|
| frustration | frustré |
| nostalgia | nostalgique |
| pride | fier de lui |
| anxiety | anxieux |
| contempt | méprisant |
| wonder | émerveillé |

Mood adjectives (same as mood line):
| Emotion | Adjective |
|---|---|
| anger | irritable |
| joy | joyeux |
| sadness | mélancolique |
| curiosity | curieux |
| boredom | apathique |

### Styling

- Card: `background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 12px 16px`
- Label "ÉTAT ÉMOTIONNEL": same uppercase style as other card headers
- Sentence: `font-size: 13px; color: rgba(255,255,255,0.7); font-style: italic`
- Hidden when sentence is "neutral" and nothing interesting to report

---

## 4. Secondary Emotion Markers on Graph

### Concept

Vertical dashed lines on the existing emotion history Canvas graph when secondary emotions activate.

### Data Source

The emotion history API must include secondary emotion activation events. Two approaches:

**Chosen approach**: Compute secondaries from stored primary snapshots at query time. Since secondaries are derived from primaries (`intensity = min(a, b)` when both above threshold), we can recompute them from the existing `emotion_history` table without storing them separately. This avoids schema changes.

### Rendering

- **Vertical dashed line** at the snapshot timestamp where a secondary activates (crosses threshold)
- **Color per secondary**:
  - frustration: `#f97316` (orange), nostalgia: `#ec4899` (pink), pride: `#f59e0b` (amber), anxiety: `#8b5cf6` (violet), contempt: `#6b7280` (gray), wonder: `#14b8a6` (teal)
- **Label**: small text at top of the line with the secondary name (rotated 90deg or horizontal if space)
- **Legend integration**: add secondary emotions to the existing legend with toggle capability (same `hiddenEmotions` Set pattern)
- **Default state**: secondary markers hidden by default in legend — user clicks to show them

### Activation Detection

For each pair of consecutive snapshots, if a secondary was not active at t0 but is active at t1, draw a marker at t1. "Active" means both primaries >= threshold per the config.

---

## 5. API Changes

### SSE `/api/public/sse/emotions` (sse.py)

Extend the existing payload from:
```json
{"anger": 0.65, "joy": 0.30, "sadness": 0.05, "curiosity": 0.50, "boredom": 0.45}
```

To:
```json
{
  "anger": 0.65, "joy": 0.30, "sadness": 0.05, "curiosity": 0.50, "boredom": 0.45,
  "mood": {"anger": 0.40, "joy": 0.10, "sadness": 0.02, "curiosity": 0.55, "boredom": 0.15},
  "fatigue": {"anger": 0.43},
  "secondaries": [["frustration", 0.45]]
}
```

- `mood`: all 5 values (always present)
- `fatigue`: only emotions with fatigue > 0 (empty dict `{}` if none)
- `secondaries`: only active secondaries as `[name, intensity]` pairs (empty list `[]` if none)

Source:
- `mood` from `emotion.get_mood()`
- `fatigue` from `emotion.get_fatigue()`, filtered to > 0
- `secondaries` from `emotion.get_secondary_emotions()`

### GET `/api/public/emotions` (emotions.py)

Same enrichment as SSE payload.

### GET `/api/public/emotions/history` (emotions.py)

No change to response format. Secondaries are computed client-side from the primary emotion data in each snapshot.

---

## 6. Frontend Implementation

### index.html

Add inside the `gauges-public` div (after the gauge rows):

```html
<div id="mood-fatigue-line" style="display:none;">
  <!-- Populated by JS -->
</div>
<div id="emotional-state-block" class="glass-card" style="display:none;">
  <span class="card-label">ÉTAT ÉMOTIONNEL</span>
  <p id="emotional-state-text"></p>
</div>
```

### app.js

1. **Update `emotionSSE.onmessage`**: parse `mood`, `fatigue`, `secondaries` from payload
2. **New function `updateMoodFatigueLine(mood, fatigue)`**: builds the text line
3. **New function `updateEmotionalStateBlock(emotions, mood, fatigue, secondaries)`**: generates the natural-language sentence
4. **Modify `drawEmotionChart()`**: add secondary marker rendering pass after primary lines
5. **New constants**: `SECONDARY_COLORS`, `SECONDARY_LABELS_FR`, `MOOD_LABELS_FR`, `FATIGUE_LABELS_FR`

### style.css

Minimal additions:
- `#mood-fatigue-line` styling
- `#emotional-state-block` styling
- `.secondary-marker` for graph markers
- `.secondary-legend-item` for legend entries

---

## 7. Files Impacted

| File | Change |
|---|---|
| `bot/dashboard/routes/sse.py` | Enrich SSE payload with mood, fatigue, secondaries |
| `bot/dashboard/routes/emotions.py` | Enrich GET `/api/public/emotions` response |
| `bot/dashboard/static/index.html` | Add mood/fatigue line + emotional state block HTML |
| `bot/dashboard/static/app.js` | Parse new data, generate text, render graph markers |
| `bot/dashboard/static/style.css` | Styles for new elements |

---

## 8. What Does NOT Change

- The 5 primary emotion gauges (same visual, same behavior)
- The admin emotion sliders and config
- The graph time range selector (1H, 24H, 7J, 30J)
- The avatar system
- The emotion history DB schema (`emotion_history` table unchanged)
- Other dashboard tabs (Memory, Costs, Actions, etc.)
