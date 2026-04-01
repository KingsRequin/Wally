# Dashboard Organic Emotions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose mood, fatigue, and secondary emotions in the existing Status tab dashboard with real-time monitoring via SSE enrichment and client-side natural-language summaries.

**Architecture:** Extend the existing SSE and REST emotion endpoints to include `mood`, `fatigue`, and `secondaries` fields, then render them in `index.html`/`app.js`/`style.css` without touching the 5 primary emotion gauges or any other tab. Secondary emotion markers on the history graph are computed client-side from existing primary snapshots — no schema change.

**Tech Stack:** FastAPI (Python, SSE), Vanilla JS, Canvas API (existing graph), CSS glassmorphism

---

## File Structure

| File | Change |
|---|---|
| `bot/dashboard/routes/sse.py` | Enrich SSE `/api/public/sse/emotions` payload with mood, fatigue, secondaries |
| `bot/dashboard/routes/emotions.py` | Enrich GET `/api/public/emotions` response identically |
| `bot/dashboard/static/index.html` | Add `#mood-fatigue-line` + `#emotional-state-block` HTML after `#gauges-public` |
| `bot/dashboard/static/style.css` | Add styles for new elements |
| `bot/dashboard/static/app.js` | Parse new SSE fields; add `updateMoodFatigueLine()`, `updateEmotionalStateBlock()`; extend graph with secondary markers + legend entries |

---

## Task 1: Enrich SSE and REST API

**Files:**
- Modify: `bot/dashboard/routes/sse.py:84-100`
- Modify: `bot/dashboard/routes/emotions.py:15-17`
- Test: `tests/test_dashboard_emotion_api.py` (new)

### Context

`EmotionEngine` already has `get_mood()`, `get_fatigue()`, and `get_secondary_emotions()`. The SSE endpoint at line 88 currently does `json.dumps(state.emotion.get_state())` — we need to enrich this dict. The REST endpoint at line 17 does the same thing.

The enriched payload format (per spec §5):
```json
{
  "anger": 0.65, "joy": 0.30, "sadness": 0.05, "curiosity": 0.50, "boredom": 0.45,
  "mood": {"anger": 0.40, "joy": 0.10, "sadness": 0.02, "curiosity": 0.55, "boredom": 0.15},
  "fatigue": {"anger": 0.43},
  "secondaries": [["frustration", 0.45]]
}
```

- `mood`: always present, all 5 values
- `fatigue`: only emotions with fatigue > 0 (empty dict `{}` if none)
- `secondaries`: only active secondaries as `[name, intensity]` pairs (empty list `[]` if none)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_emotion_api.py
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from bot.dashboard.routes.emotions import public_router

@pytest.fixture
def app_with_emotion():
    app = FastAPI()
    app.include_router(public_router, prefix="/api/public")
    mock_emotion = MagicMock()
    mock_emotion.get_state.return_value = {
        "anger": 0.65, "joy": 0.30, "sadness": 0.05, "curiosity": 0.50, "boredom": 0.45
    }
    mock_emotion.get_mood.return_value = {
        "anger": 0.40, "joy": 0.10, "sadness": 0.02, "curiosity": 0.55, "boredom": 0.15
    }
    mock_emotion.get_fatigue.return_value = {"anger": 0.43}
    mock_emotion.get_secondary_emotions.return_value = [("frustration", 0.45)]
    app.state.wally = MagicMock()
    app.state.wally.emotion = mock_emotion
    return TestClient(app)

def test_get_emotions_includes_mood_fatigue_secondaries(app_with_emotion):
    r = app_with_emotion.get("/api/public/emotions")
    assert r.status_code == 200
    data = r.json()
    assert "mood" in data
    assert data["mood"]["anger"] == pytest.approx(0.40)
    assert "fatigue" in data
    assert data["fatigue"]["anger"] == pytest.approx(0.43)
    assert "secondaries" in data
    assert data["secondaries"] == [["frustration", 0.45]]

def test_get_emotions_empty_fatigue_returns_empty_dict(app_with_emotion):
    app_with_emotion.app.state.wally.emotion.get_fatigue.return_value = {}
    r = app_with_emotion.get("/api/public/emotions")
    assert r.json()["fatigue"] == {}

def test_get_emotions_no_active_secondaries_returns_empty_list(app_with_emotion):
    app_with_emotion.app.state.wally.emotion.get_secondary_emotions.return_value = []
    r = app_with_emotion.get("/api/public/emotions")
    assert r.json()["secondaries"] == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/test_dashboard_emotion_api.py -v
```
Expected: FAIL — `assert "mood" in data` fails

- [ ] **Step 3: Add `_enrich_emotions()` helper and update both endpoints in `emotions.py`**

Add helper function after the imports block, before the first route:

```python
def _enrich_emotions(emotion_engine) -> dict:
    """Return get_state() enriched with mood, fatigue (>0 only), and active secondaries."""
    data = emotion_engine.get_state()
    data["mood"] = emotion_engine.get_mood()
    data["fatigue"] = {k: v for k, v in emotion_engine.get_fatigue().items() if v > 0}
    data["secondaries"] = [list(pair) for pair in emotion_engine.get_secondary_emotions()]
    return data
```

Then replace `get_emotions_public` and `get_emotions_admin` bodies:

```python
@public_router.get("/emotions")
async def get_emotions_public(request: Request) -> dict:
    return _enrich_emotions(request.app.state.wally.emotion)


@admin_router.get("/emotions")
async def get_emotions_admin(request: Request) -> dict:
    return _enrich_emotions(request.app.state.wally.emotion)
```

- [ ] **Step 4: Update SSE endpoint in `sse.py`**

Replace the `data = json.dumps(state.emotion.get_state())` line inside the `generate()` coroutine of `sse_emotions`:

```python
    async def generate():
        try:
            tick = 0
            while True:
                state_data = state.emotion.get_state()
                state_data["mood"] = state.emotion.get_mood()
                state_data["fatigue"] = {
                    k: v for k, v in state.emotion.get_fatigue().items() if v > 0
                }
                state_data["secondaries"] = [
                    list(pair) for pair in state.emotion.get_secondary_emotions()
                ]
                data = json.dumps(state_data)
                yield f"data: {data}\n\n"
                await asyncio.sleep(5)
                tick += 1
                if tick % 3 == 0:  # keepalive toutes les 15s
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_dashboard_emotion_api.py -v
```
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_dashboard_emotion_api.py bot/dashboard/routes/emotions.py bot/dashboard/routes/sse.py
git commit -m "feat(dashboard): enrich emotion API with mood, fatigue, secondaries"
```

---

## Task 2: Add HTML structure for new UI elements

**Files:**
- Modify: `bot/dashboard/static/index.html:195-196`

### Context

The current structure in `index.html` around line 194–197:
```html
<div class="card-title">HUMEUR EN DIRECT</div>
<div id="gauges-public" role="group" aria-label="Emotions actuelles"></div>
<div class="emotion-summary" id="emotion-summary" aria-live="polite">—</div>
```

We need to insert two new elements after `#gauges-public`:
1. `#mood-fatigue-line` — hidden by default, populated by JS
2. `#emotional-state-block` — glassmorphism card, hidden by default

The existing `#emotion-summary` is hidden — replaced by the new block.

- [ ] **Step 1: Add the new HTML elements after `#gauges-public`**

In `bot/dashboard/static/index.html`, replace:

```html
          <div id="gauges-public" role="group" aria-label="Emotions actuelles"></div>
          <div class="emotion-summary" id="emotion-summary" aria-live="polite">—</div>
```

With:

```html
          <div id="gauges-public" role="group" aria-label="Emotions actuelles"></div>
          <div id="mood-fatigue-line" style="display:none;"></div>
          <div id="emotional-state-block" class="emotional-state-card" style="display:none;" aria-live="polite">
            <span class="card-sublabel">ÉTAT ÉMOTIONNEL</span>
            <p id="emotional-state-text"></p>
          </div>
          <div class="emotion-summary" id="emotion-summary" aria-live="polite" style="display:none;">—</div>
```

- [ ] **Step 2: Verify HTML parses without errors**

```bash
python -c "from html.parser import HTMLParser; p = HTMLParser(); p.feed(open('bot/dashboard/static/index.html').read()); print('HTML OK')"
```
Expected: `HTML OK`

- [ ] **Step 3: Commit**

```bash
git add bot/dashboard/static/index.html
git commit -m "feat(dashboard): add mood-fatigue-line + emotional-state-block HTML"
```

---

## Task 3: Add CSS styles for new elements

**Files:**
- Modify: `bot/dashboard/static/style.css` (append at end)

### Context

The dashboard uses glassmorphism: `rgba(255,255,255,0.03-0.05)` backgrounds, `1px solid rgba(255,255,255,0.08)` borders, `border-radius: 12px`. All new elements must follow this system. Emotion colors: anger `#ef4444`, joy `#eab308`, curiosity `#22c55e`, sadness `#3b82f6`, boredom `#a855f7`.

- [ ] **Step 1: Append styles at end of `style.css`**

```css
/* ── Organic Emotions — Mood/Fatigue Line ───────────────────────── */

#mood-fatigue-line {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 10px;
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 12px;
}

#mood-fatigue-line .mf-label {
  font-size: 11px;
  letter-spacing: 0.5px;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase;
}

#mood-fatigue-line .mf-value {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  margin-left: 6px;
}

#mood-fatigue-line .mf-separator {
  color: rgba(255, 255, 255, 0.25);
  margin: 0 8px;
}

/* ── Organic Emotions — Emotional State Block ───────────────────── */

.emotional-state-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 12px 16px;
  margin-top: 10px;
}

.card-sublabel {
  display: block;
  font-size: 11px;
  letter-spacing: 0.5px;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase;
  margin-bottom: 6px;
}

.emotional-state-card p {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.7);
  font-style: italic;
  margin: 0;
  line-height: 1.5;
}

/* ── Organic Emotions — Secondary Markers in Graph ─────────────── */

.secondary-legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.55);
  padding: 3px 6px;
  border-radius: 6px;
  transition: background 0.15s;
}

.secondary-legend-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.secondary-legend-item.hidden-emotion {
  opacity: 0.4;
}

.secondary-legend-dash {
  width: 16px;
  height: 2px;
  border-top: 2px dashed currentColor;
  display: inline-block;
}
```

- [ ] **Step 2: Verify CSS brace balance**

```bash
python -c "
import sys
css = open('bot/dashboard/static/style.css').read()
opens = css.count('{')
closes = css.count('}')
if opens != closes:
    print(f'MISMATCH: {opens} open vs {closes} close braces')
    sys.exit(1)
print('CSS braces OK')
"
```
Expected: `CSS braces OK`

- [ ] **Step 3: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "feat(dashboard): add CSS for mood-fatigue-line, emotional-state-block, secondary legend"
```

---

## Task 4: JS — Parse new SSE data, render mood/fatigue line and emotional state block

**Files:**
- Modify: `bot/dashboard/static/app.js`

### Context

Current SSE handler (line 436–438 of app.js):
```js
emotionSSE.onmessage = (e) => {
  try { updateEmotionGauges(JSON.parse(e.data)); } catch {}
};
```

After Task 1, the SSE payload now includes `mood`, `fatigue`, `secondaries` in addition to the 5 primary emotions. The `updateEmotionGauges` function stores the payload in `currentEmotions` and renders gauges. We extend it to also extract and store the new fields, then call two new rendering functions.

`updateEmotionSummary()` (line 417–424) is the old summary function — it remains in the code (not deleted) but its call is removed from `updateEmotionGauges`. The `#emotion-summary` element was hidden in Task 2.

### French label maps (per spec §2 and §3)

```
Mood adjectives: anger→irritable, joy→joyeux, sadness→mélancolique, curiosity→curieux, boredom→apathique
Fatigue labels:  anger→colère, joy→joie, sadness→tristesse, curiosity→curiosité, boredom→ennui
Fatigue colors:  anger→rgba(239,68,68,0.7), joy→rgba(234,179,8,0.7), sadness→rgba(59,130,246,0.7),
                 curiosity→rgba(34,197,94,0.7), boredom→rgba(168,85,247,0.7)
Secondary adjectives: frustration→frustré, nostalgia→nostalgique, pride→fier de lui,
                      anxiety→anxieux, contempt→méprisant, wonder→émerveillé
```

- [ ] **Step 1: Add new state variables and constants after `let hiddenEmotions = new Set();` (line 47)**

Add immediately after `let hiddenEmotions = new Set();`:

```js
let currentMood        = {};
let currentFatigue     = {};
let currentSecondaries = [];

const MOOD_ADJ_FR = {
  anger: 'irritable', joy: 'joyeux', sadness: 'mélancolique',
  curiosity: 'curieux', boredom: 'apathique',
};
const FATIGUE_LABEL_FR = {
  anger: 'colère', joy: 'joie', sadness: 'tristesse', curiosity: 'curiosité', boredom: 'ennui',
};
const FATIGUE_COLORS = {
  anger:    'rgba(239,68,68,0.7)',
  joy:      'rgba(234,179,8,0.7)',
  sadness:  'rgba(59,130,246,0.7)',
  curiosity:'rgba(34,197,94,0.7)',
  boredom:  'rgba(168,85,247,0.7)',
};
const SECONDARY_ADJ_FR = {
  frustration: 'frustré',
  nostalgia:   'nostalgique',
  pride:       'fier de lui',
  anxiety:     'anxieux',
  contempt:    'méprisant',
  wonder:      'émerveillé',
};
```

- [ ] **Step 2: Replace `updateEmotionGauges` to extract new fields (lines 398–415)**

```js
function updateEmotionGauges(payload) {
  // Extract organic emotion fields
  currentMood        = payload.mood        || {};
  currentFatigue     = payload.fatigue     || {};
  currentSecondaries = payload.secondaries || [];

  currentEmotions = payload;
  for (const e of EMOTIONS) {
    const v = payload[e] ?? 0;
    const fill = document.getElementById(`fill-${e}`);
    if (fill) {
      fill.style.width = `${(v * 100).toFixed(1)}%`;
      const track = fill.parentElement;
      if (track) track.setAttribute('aria-valuenow', v.toFixed(2));
    }
    const slider = document.getElementById(`slider-${e}`);
    if (slider) slider.value = v;
    const val = document.getElementById(`val-${e}`);
    if (val) val.textContent = v.toFixed(2);
  }
  updateMoodFatigueLine(currentMood, currentFatigue);
  updateEmotionalStateBlock(payload, currentMood, currentFatigue, currentSecondaries);
  updateFavicon(payload);
}
```

Note: `updateEmotionSummary` call is removed (the function itself stays, the `#emotion-summary` div is hidden via HTML).

- [ ] **Step 3: Add `updateMoodFatigueLine()` after `updateEmotionSummary` function**

```js
function updateMoodFatigueLine(mood, fatigue) {
  const el = document.getElementById('mood-fatigue-line');
  if (!el) return;

  const moodEntries = EMOTIONS
    .filter(e => (mood[e] ?? 0) >= 0.2)
    .sort((a, b) => (mood[b] ?? 0) - (mood[a] ?? 0))
    .slice(0, 2);

  const fatigueEntries = Object.entries(fatigue).filter(([, v]) => v > 0);

  if (moodEntries.length === 0 && fatigueEntries.length === 0) {
    el.style.display = 'none';
    return;
  }

  // Build HTML from internal constants only — no user input
  const parts = [];

  if (moodEntries.length > 0) {
    const labels = moodEntries.map(e => MOOD_ADJ_FR[e] || e).join(', ');
    parts.push(
      '<span class="mf-label">Humeur de fond</span>',
      `<span class="mf-value">${labels}</span>`
    );
  }

  if (fatigueEntries.length > 0) {
    if (moodEntries.length > 0) parts.push('<span class="mf-separator">|</span>');
    parts.push('<span class="mf-label">Fatigue</span>');
    for (const [emotion, v] of fatigueEntries) {
      const label = FATIGUE_LABEL_FR[emotion] || emotion;
      const pct   = Math.round(v * 100);
      const color = FATIGUE_COLORS[emotion] || 'rgba(255,255,255,0.7)';
      parts.push(
        `<span class="mf-value" style="color:${color};margin-left:6px">${label} en récupération (${pct}%)</span>`
      );
    }
  }

  el.innerHTML = parts.join('');
  el.style.display = 'flex';
}
```

- [ ] **Step 4: Add `updateEmotionalStateBlock()` after `updateMoodFatigueLine`**

```js
function updateEmotionalStateBlock(emotions, mood, fatigue, secondaries) {
  const el     = document.getElementById('emotional-state-block');
  const textEl = document.getElementById('emotional-state-text');
  if (!el || !textEl) return;

  const fatigueActive     = Object.values(fatigue).some(v => v > 0);
  const activeSecondaries = secondaries.filter(([, intensity]) => intensity >= 0.4);

  const dominantEmotion = EMOTIONS.reduce((a, b) =>
    (emotions[a] ?? 0) > (emotions[b] ?? 0) ? a : b);
  const dominantMood = EMOTIONS.reduce((a, b) =>
    (mood[a] ?? 0) > (mood[b] ?? 0) ? a : b);
  const hasMoodDissonance = dominantMood !== dominantEmotion
    && (emotions[dominantEmotion] ?? 0) >= 0.3
    && (mood[dominantMood] ?? 0) >= 0.3;

  let sentence = '';

  // Rule 1: Secondary emotion active (intensity >= 0.4)
  if (activeSecondaries.length > 0) {
    const [secName] = activeSecondaries[0];
    const secAdj = SECONDARY_ADJ_FR[secName] || secName;
    sentence = `Wally est ${secAdj}.`;
    if (fatigueActive) {
      const firstFatigueEmotion = Object.keys(fatigue).find(k => fatigue[k] > 0);
      const fatigueLabel = firstFatigueEmotion ? (FATIGUE_LABEL_FR[firstFatigueEmotion] || firstFatigueEmotion) : '';
      if (fatigueLabel) sentence += ` Sa ${fatigueLabel} est en récupération après un pic.`;
    }
    if (hasMoodDissonance) {
      const moodAdj = MOOD_ADJ_FR[dominantMood] || dominantMood;
      sentence += ` Fond ${moodAdj} malgré tout.`;
    }
  }
  // Rule 2: Fatigue active but no secondary
  else if (fatigueActive) {
    const firstFatigueEmotion = Object.keys(fatigue).find(k => fatigue[k] > 0);
    const fatigueLabel = firstFatigueEmotion ? (FATIGUE_LABEL_FR[firstFatigueEmotion] || firstFatigueEmotion) : '';
    sentence = `Wally est dans un état normal.${fatigueLabel ? ` Sa ${fatigueLabel} est en récupération.` : ''}`;
  }
  // Rule 3: Mood dissonance
  else if (hasMoodDissonance) {
    const emotAdj = MOOD_ADJ_FR[dominantEmotion] || dominantEmotion;
    const moodAdj = MOOD_ADJ_FR[dominantMood]    || dominantMood;
    sentence = `Wally est ${emotAdj} en surface mais ${moodAdj} en profondeur.`;
  }
  // Rule 4: Nothing interesting — hide
  else {
    el.style.display = 'none';
    return;
  }

  textEl.textContent = sentence; // textContent — safe, no XSS risk
  el.style.display = 'block';
}
```

- [ ] **Step 5: Run JS syntax check**

```bash
node --check bot/dashboard/static/app.js && echo "JS syntax OK"
```
Expected: `JS syntax OK`

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): render mood-fatigue line + emotional state block from SSE"
```

---

## Task 5: JS — Secondary emotion markers on history graph

**Files:**
- Modify: `bot/dashboard/static/app.js`

### Context

`drawEmotionGraph(history)` renders primary emotion lines on Canvas. `history` is an array of `{snapshot_at, anger, joy, sadness, curiosity, boredom}`. Secondaries are derived client-side.

`buildEmotionLegend()` renders legend items using `hiddenEmotions` Set. Secondary entries are added to the legend and hidden by default.

Secondary definitions (thresholds match `config.yaml` defaults):
```
frustration = anger × boredom   (both >= 0.4)
nostalgia   = joy × sadness      (both >= 0.35)
pride       = joy × curiosity    (both >= 0.5)
anxiety     = sadness × boredom  (both >= 0.45)
contempt    = anger × curiosity  (both >= 0.5)
wonder      = curiosity × joy    (both >= 0.45)
```

Colors per spec §4:
```
frustration:#f97316  nostalgia:#ec4899  pride:#f59e0b
anxiety:#8b5cf6      contempt:#6b7280   wonder:#14b8a6
```

- [ ] **Step 1: Add secondary constants after `const EMOTIONS = [...]` (near line 23)**

```js
const SECONDARY_COLORS = {
  frustration: '#f97316',
  nostalgia:   '#ec4899',
  pride:       '#f59e0b',
  anxiety:     '#8b5cf6',
  contempt:    '#6b7280',
  wonder:      '#14b8a6',
};
const SECONDARY_LABELS = ['frustration', 'nostalgia', 'pride', 'anxiety', 'contempt', 'wonder'];
const SECONDARY_LABELS_FR = {
  frustration: 'frustration', nostalgia: 'nostalgie',   pride:    'fierté',
  anxiety:     'anxiété',     contempt:  'mépris',       wonder:   'émerveillement',
};
const SECONDARY_DEFS = {
  frustration: { a: 'anger',     b: 'boredom',    threshold: 0.4  },
  nostalgia:   { a: 'joy',       b: 'sadness',    threshold: 0.35 },
  pride:       { a: 'joy',       b: 'curiosity',  threshold: 0.5  },
  anxiety:     { a: 'sadness',   b: 'boredom',    threshold: 0.45 },
  contempt:    { a: 'anger',     b: 'curiosity',  threshold: 0.5  },
  wonder:      { a: 'curiosity', b: 'joy',        threshold: 0.45 },
};
```

- [ ] **Step 2: Change `hiddenEmotions` init to include all secondaries hidden by default**

Replace:
```js
let hiddenEmotions = new Set(); // for interactive legend
```
With:
```js
let hiddenEmotions = new Set(SECONDARY_LABELS); // secondaries hidden by default
```

Note: `SECONDARY_LABELS` const is defined in Step 1 above. It must be placed before `hiddenEmotions` in the file. Since `SECONDARY_LABELS` is near line 23 and `hiddenEmotions` is near line 47, the order is correct.

- [ ] **Step 3: Add `_computeSecondaryActivations(history)` helper before `drawEmotionGraph`**

```js
function _computeSecondaryActivations(history) {
  const activations = [];
  for (let i = 1; i < history.length; i++) {
    const prev = history[i - 1];
    const curr = history[i];
    for (const [name, def] of Object.entries(SECONDARY_DEFS)) {
      const prevActive = (prev[def.a] ?? 0) >= def.threshold && (prev[def.b] ?? 0) >= def.threshold;
      const currActive = (curr[def.a] ?? 0) >= def.threshold && (curr[def.b] ?? 0) >= def.threshold;
      if (!prevActive && currActive) {
        activations.push({ name, index: i });
      }
    }
  }
  return activations;
}
```

- [ ] **Step 4: Add secondary marker rendering inside `drawEmotionGraph` after the `ctx.globalAlpha = 1;` line that closes the emotion area fill loop (around line 668)**

Add after `ctx.globalAlpha = 1;`:

```js
  // Secondary emotion activation markers (vertical dashed lines)
  const activations = _computeSecondaryActivations(history);
  for (const { name, index } of activations) {
    if (hiddenEmotions.has(name)) continue;
    const snap  = history[index];
    const x     = PAD.left + ((snap.snapshot_at - tMin) / tRange) * gW;
    const color = SECONDARY_COLORS[name];
    const label = SECONDARY_LABELS_FR[name] || name;

    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    ctx.moveTo(x, PAD.top);
    ctx.lineTo(x, PAD.top + gH);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.globalAlpha = 0.85;
    ctx.fillStyle   = color;
    ctx.font        = '9px Inter, sans-serif';
    ctx.textAlign   = 'left';
    const labelX = Math.min(x + 3, W - PAD.right - 60);
    ctx.fillText(label, labelX, PAD.top + 10);
    ctx.restore();
  }
```

- [ ] **Step 5: Replace `buildEmotionLegend` to include secondary entries**

```js
function buildEmotionLegend() {
  const el = document.getElementById('emotion-graph-legend');
  if (!el) return;

  const primaryItems = EMOTIONS.map(e => {
    const hidden = hiddenEmotions.has(e);
    return `<div class="graph-legend-item ${hidden ? 'hidden-emotion' : ''}"
                 onclick="toggleEmotion('${e}')" title="Cliquer pour ${hidden ? 'afficher' : 'masquer'}">
      <span class="legend-line" style="background:${EMOTION_COLORS[e]}"></span>
      <span>${EMOTION_EMOJIS[e]} ${EMOTION_LABELS[e]}</span>
    </div>`;
  });

  const secondaryItems = SECONDARY_LABELS.map(name => {
    const hidden = hiddenEmotions.has(name);
    const color  = SECONDARY_COLORS[name];
    const label  = SECONDARY_LABELS_FR[name] || name;
    return `<div class="secondary-legend-item ${hidden ? 'hidden-emotion' : ''}"
                 onclick="toggleEmotion('${name}')" title="${hidden ? 'Afficher' : 'Masquer'} ${label}">
      <span class="secondary-legend-dash" style="color:${color}"></span>
      <span style="color:${color}">${label}</span>
    </div>`;
  });

  el.innerHTML = primaryItems.join('') + secondaryItems.join('');
}
```

Note: all values in the template literals come from internal constants (EMOTION_COLORS, SECONDARY_COLORS, etc.) — no user-supplied data is interpolated.

- [ ] **Step 6: Run JS syntax check**

```bash
node --check bot/dashboard/static/app.js && echo "JS syntax OK"
```
Expected: `JS syntax OK`

- [ ] **Step 7: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): secondary emotion markers on graph + legend"
```

---

## Self-Review Against Spec

**§2 Mood + Fatigue Line:** Task 1 (API), Task 2 (HTML `#mood-fatigue-line`), Task 3 (CSS), Task 4 (`updateMoodFatigueLine`). Visibility rules handled. French adjectives correct. Fatigue format `colère en récupération (43%)` with emotion color at 70% opacity. Labels uppercase, small text.

**§3 Emotional State Block:** Task 2 (HTML `#emotional-state-block`), Task 3 (`.emotional-state-card` CSS), Task 4 (`updateEmotionalStateBlock`). All 4 priority rules implemented. French secondary adjectives and mood adjectives match spec tables. Hidden when nothing interesting. `textContent` used for sentence (safe). `#emotion-summary` hidden via HTML.

**§4 Secondary Emotion Markers:** Task 5. Dashed vertical lines, correct colors per spec §4, label at top. Default hidden (all added to `hiddenEmotions` on init via `new Set(SECONDARY_LABELS)`). Toggle via existing `toggleEmotion` pattern. `buildEmotionLegend` extended with secondary `.secondary-legend-item` entries.

**§5 API Changes:** Task 1. Both SSE and GET `/api/public/emotions` enriched. `mood` always present (all 5), `fatigue` filtered to >0, `secondaries` as `[name, intensity]` pairs. History endpoint unchanged.

**§6 Frontend:** New constants added at module top. `updateEmotionGauges` extended. Three new functions added. Graph rendering extended.

**§7 Files Impacted:** All 5 files covered.

**§8 What Does NOT Change:** Primary gauges untouched (same HTML/CSS/JS). Admin sliders untouched. Graph time selector untouched. Avatar untouched. `emotion_history` schema unchanged.
