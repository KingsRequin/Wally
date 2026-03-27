# Organic Emotion System — Design Spec

**Date**: 2026-03-27
**Objective**: Transform Wally's emotion system from a reactive mechanical model into a multi-layered organic system with mood inertia, per-user emotional memory, emergent secondary emotions, emotional fatigue, circadian rhythm, and spontaneous inner life.

**Guiding principle**: Naturalness and immersion. Emotions should feel like they belong to a living entity, not a state machine.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Layer 1 — Mood Layer](#2-layer-1--mood-layer)
3. [Layer 2 — Emotional Memory Per User](#3-layer-2--emotional-memory-per-user)
4. [Layer 3a — Emergent Secondary Emotions](#4-layer-3a--emergent-secondary-emotions)
5. [Layer 3b — Emotional Fatigue](#5-layer-3b--emotional-fatigue)
6. [Layer 3c — Circadian Rhythm](#6-layer-3c--circadian-rhythm)
7. [Layer 3d — Spontaneous Internal Events](#7-layer-3d--spontaneous-internal-events)
8. [Layer 3e — Fluid Directive Transitions](#8-layer-3e--fluid-directive-transitions)
9. [Delta Processing Pipeline](#9-delta-processing-pipeline)
10. [Configuration](#10-configuration)
11. [Database Changes](#11-database-changes)
12. [Files Impacted](#12-files-impacted)
13. [What Does NOT Change](#13-what-does-not-change)

---

## 1. Architecture Overview

```
+--------------------------------------------------+
|              PROMPT INJECTION                      |
|  Mood (baseline) + Emotion (modulation)            |
|  + Emergent secondaries + Fluid transitions        |
+--------------------------------------------------+
|              LAYER 3 — INNER LIFE                  |
|  Circadian rhythm . Spontaneous events             |
|  Post-peak fatigue . Fluid transitions             |
+--------------------------------------------------+
|              LAYER 2 — EMOTIONAL MEMORY            |
|  Per-user affinity . Priming . Amplification       |
|  Habituation (diminishing returns)                 |
+--------------------------------------------------+
|              LAYER 1 — MOOD                        |
|  EMA of emotions . Slow decay (lambda=0.1/h)      |
|  Biases emotional reactivity                       |
+--------------------------------------------------+
|              LAYER 0 — EXISTING                    |
|  5 primary emotions . Exponential decay            |
|  Suppression/Competition . NRCLex + LLM            |
|  Inertia . Trust amplification                     |
+--------------------------------------------------+
```

Each layer builds on the previous. Implementation order follows the layer numbers (0 is already done).

---

## 2. Layer 1 — Mood Layer

### Concept

Two distinct emotional levels, like a human:

| | **Emotions** (existing) | **Mood** (new) |
|---|---|---|
| Speed | Reactive (seconds) | Slow (hours) |
| Cause | Messages, events | Emotion accumulation |
| Decay | Fast lambda (1.5-3.0/h) | Very slow (lambda=0.1/h) |
| Prompt role | Tone modulation | Baseline tone |

### Mechanics

- **Same 5 dimensions** as emotions: anger, joy, sadness, curiosity, boredom
- **EMA update** every decay tick (60s):
  ```
  mood[e] = alpha * emotion[e] + (1 - alpha) * mood[e]
  ```
  - `alpha` configurable (~0.02) — mood takes ~50 ticks / ~1h to react significantly
- **Bidirectional influence** — mood biases emotional reactivity:
  - Matching mood amplifies deltas: `delta *= (1 + mood[e] * bias_factor)`
  - Opposing mood increases inertia resistance (via existing inertia_factor, amplified)
  - `bias_factor` configurable (~0.3)
- **Mood decay**: exponential, very slow (lambda=0.1/h) — returns to neutral baseline over ~10h

### Prompt Injection

The mood determines the **base register**. The emotion **modulates** it:
- Joyful mood + anger emotion -> irritated sarcasm (not cold rage)
- Sad mood + joy emotion -> melancholic smile (not euphoria)
- Creates emergent tonal combinations without writing every case

### Persistence

- Saved to DB alongside emotion state (new columns in emotion snapshots or dedicated row)
- Restored on boot — mood does NOT reset on restart

---

## 3. Layer 2 — Emotional Memory Per User

### Concept

Wally develops **emotional coloring** toward each person based on interaction history. Like seeing someone's name and already feeling something before reading their message.

### Data Structure

New table `emotional_memory`:

| Field | Type | Description |
|---|---|---|
| user_id | str | Raw ID (not prefixed) |
| platform | str | discord / twitch |
| emotion | str | anger, joy, sadness, curiosity, boredom |
| affinity | float [-1.0, 1.0] | Accumulated emotional coloring |
| interaction_count | int | Number of interactions that influenced this emotion |
| last_updated | datetime | Last update timestamp |

**Affinity** is not an emotion itself — it's a **directional bias**:
- `+0.8 joy` -> Wally is predisposed to joy with this person
- `-0.5 anger` -> this person calms Wally (rare for him to get angry with them)
- `+0.6 anger` -> Wally starts on edge as soon as he sees their name

### Update Mechanics

After each `process_message()`:
```
affinity[e] = clamp(affinity[e] + learning_rate * delta[e], -1.0, 1.0)
```
- `learning_rate` configurable (~0.05) — slow learning
- Only non-zero deltas modify affinity
- `interaction_count` incremented — serves as confidence weight

### Influence on Emotions

When processing a message, **before** applying deltas:

1. Load user affinity (LRU cache in memory, invalidated on update)
2. **Emotional priming**: positive affinities add a micro-delta at processing start
   - `pre_delta[e] = affinity[e] * priming_factor` (priming_factor ~0.05)
   - Wally already "feels" something when seeing the username
3. **Delta amplification**: deltas in the same direction as affinity are amplified
   - `effective_delta = delta * (1 + affinity[e] * amplification_factor)` (amplification ~0.3)

### Habituation (Diminishing Returns)

Repeated stimuli lose impact:

- Per-user tracker: `recent_emotions: dict[user_id, deque[tuple[emotion, timestamp]]]`
- Same dominant emotion triggered >3 times in 10 minutes by same user:
  - `delta *= habituation_decay` (0.5 -> 0.25 -> 0.125...)
  - Reset after 30 minutes without similar stimulus
- **Exception**: anger does NOT habituate (consistent with spam detection behavior)

### Prompt Impact

Affinity injected in the existing `--- Relation ---` context block:
- `"Wally ressent une familiarite joyeuse avec {user}"` if joy affinity > 0.5
- `"Wally est sur ses gardes avec {user}"` if anger affinity > 0.4
- Natural phrasing, not mechanical — sentences, not numbers

### Affinity Decay

- Very slow: lambda = 0.01/day (impressions persist for weeks)
- Applied on load if `last_updated` is stale:
  ```
  days_elapsed = (now - last_updated).total_seconds() / 86400
  stability = min(1.0, interaction_count / 50)  # 50 interactions = fully stable
  effective_lambda = decay_lambda * (1 - stability * 0.8)  # stable affinities decay 80% slower
  affinity *= exp(-effective_lambda * days_elapsed)
  ```
- Low interaction_count -> volatile affinity (full decay rate); high count (50+) -> stable affinity (20% of decay rate)

---

## 4. Layer 3a — Emergent Secondary Emotions

### Concept

Secondary emotions are NOT stored — they **emerge** from primary emotion combinations. Frustration is not a distinct state; it's what you feel when you're angry AND bored.

### Palette

| Secondary | Formula | Activation Threshold | Behavioral Directive |
|---|---|---|---|
| **Frustration** | anger x boredom | both >= 0.3 | Impatient, snappy, sighs, "mais c'est pas possible" |
| **Nostalgia** | joy x sadness | both >= 0.3 | Bittersweet, "c'etait bien quand meme...", past references |
| **Pride** | joy x curiosity | both >= 0.4 | Self-satisfied, "j'le savais", shows expertise |
| **Anxiety** | sadness x curiosity | both >= 0.3 | Worried questions, catastrophizing, "et si..." |
| **Contempt** | anger x boredom (high) | anger >= 0.4, boredom >= 0.5 | Condescending, "pfff", "c'est tout ?", detached but acerbic |
| **Wonder** | curiosity x joy (high) | both >= 0.5 | Pure enthusiasm, drops cynicism, "non mais REGARDE ca" |

### Mechanics

**Intensity calculation**:
```
intensity = min(primary_a, primary_b)
```
The weakest link determines intensity. No new state to manage, no separate decay.

**Detection** via new method `get_secondary_emotions()`:
- Returns list of `(name, intensity)` sorted by intensity
- Only emotions above activation threshold are returned

### Prompt Priority

Secondary emotions **replace** the current composite system (`COMPOSITES.md`):

1. Check active secondary emotions (threshold met)
2. If a secondary is active with intensity >= 0.4 -> use its directive
3. Multiple active -> take the most intense
4. Else -> fallback to atomic directives (low/mid/high) as today

### Directives

New file `bot/persona/SECONDARIES.md`, same format as `EMOTIONS.md`, with 3 tiers (low/mid/high) per secondary emotion.

### Mood Interaction

Mood lowers secondary thresholds for matching emotions:
- Sad mood -> nostalgia threshold lowered to 0.2
- Angry mood -> frustration and contempt thresholds lowered
- Creates naturally themed "emotional days"

---

## 5. Layer 3b — Emotional Fatigue

### Concept

After an intense emotional peak, reactivity drops temporarily — like a human drained after a big argument or laughing fit.

### Mechanics

- When an emotion exceeds `peak_threshold` (0.7) -> fatigue counter triggers
- `fatigue[e]`: float 0.0-1.0, starts at the peak intensity value
- During fatigue, incoming deltas for that emotion are dampened:
  ```
  effective_delta *= (1 - fatigue[e] * fatigue_dampening)
  ```
  - `fatigue_dampening` ~0.7 -> at fatigue=1.0, deltas reduced by 70%
- **Fatigue decay**: linear, configurable (~0.1/hour -> full recovery in ~10h)
- **No cross-fatigue**: anger fatigue does NOT affect joy

### Special Cases

- **Boredom**: no fatigue (structurally different — linear rise, not peaks)
- **Narrative effect**: Wally can't stay perpetually enraged. After a big clash, he becomes emotionally flat on anger for a few hours. Forces natural emotional variety.

### Persistence

- Saved to DB alongside emotion state
- Restored on boot

---

## 6. Layer 3c — Circadian Rhythm

### Concept

Emotional sensitivity varies by time of day. Timezone: `Europe/Paris`.

| Period | Hours | Effect |
|---|---|---|
| **Night** | 00h-06h | anger +30%, curiosity -20%, shorter responses |
| **Morning** | 06h-12h | curiosity +20%, joy +10%, "fresh mode" |
| **Afternoon** | 12h-18h | Neutral baseline (no modifiers) |
| **Evening** | 18h-00h | sadness +15%, nostalgia facilitated, more intimate tone |

### Implementation

- Dictionary of multipliers per emotion per period
- Applied as coefficient on incoming deltas: `delta *= circadian_mult[period][emotion]`
- **Smooth transitions** between periods: linear interpolation over 30 minutes at boundaries
- Configurable in `config.yaml` under `emotions.circadian` — can be disabled (all mults = 1.0)

### Narrative Effect

Wally is grumpier at night, more open in the morning, more melancholic in the evening. A regular user would notice the pattern without being told.

---

## 7. Layer 3d — Spontaneous Internal Events

### Concept

Wally has micro mood shifts without external stimulus — he "thinks" even when nobody is talking.

### Mechanics

- In the decay loop (every 60s), probability of **micro-event**: ~2% per tick (~1 event per hour average)
- Weighted event pool:

| Event | Weight | Effect |
|---|---|---|
| Wandering thought | 30% | curiosity +0.05 |
| Pleasant memory | 20% | joy +0.05 |
| Unpleasant memory | 10% | sadness +0.05 or anger +0.03 |
| Existential ennui | 25% | boredom +0.08 |
| Creative spark | 15% | curiosity +0.08, boredom -0.1 |

### Mood Modulation

The mood biases event probabilities:
- Sad mood -> unpleasant memories 2x more probable
- Curious mood -> wandering thoughts and creative sparks favored
- Joyful mood -> pleasant memories favored

### Constraints

- Events are **silent** — no log or message to users. They manifest only through subtle tone shifts.
- Max delta per spontaneous event: `max_spontaneous_delta` (~0.1) — never a major swing without external cause.

### Narrative Effect

Between conversations, Wally's emotional state has shifted slightly. He doesn't restart from the same point. "Tiens, t'as l'air de meilleure humeur aujourd'hui" becomes possible.

---

## 8. Layer 3e — Fluid Directive Transitions

### Concept

Instead of discrete low/mid/high tiers (0.2/0.4/0.7), continuous interpolation at boundaries.

### Mechanics

- Transition zones: +/-0.05 around each threshold
- Between 0.35 and 0.45: the prompt blends low and mid directives
  - Format: `"{emotion} a {value:.0%} — {directive_low} mais tendance vers {directive_mid}"`
- Outside transition zones: pure tier directive (as today)
- Secondary emotions keep their threshold logic (already combinations)

### Narrative Effect

No sudden "mode switch." Anger rises gradually in tone, like a real human. Regulars sense the build-up before the peak.

---

## 9. Delta Processing Pipeline

Complete order of operations when a message is received:

```
Message received
  |
  +-- 1. Circadian rhythm      -> delta *= circadian_mult
  +-- 2. Affinity priming      -> micro-delta added (priming)
  +-- 3. Mood bias             -> delta *= (1 + mood[e] * bias_factor)
  +-- 4. Inertia (existing)    -> delta *= (1 - opposite * inertia)
  +-- 5. Affinity amplification -> delta *= (1 + affinity[e] * amp_factor)
  +-- 6. Habituation           -> delta *= habituation_decay if repetitive
  +-- 7. Fatigue               -> delta *= (1 - fatigue[e] * dampening)
  +-- 8. apply_delta (existing) -> clamp, suppression, state update
  |
  +-- Post: update affinity, update habituation tracker
```

Steps 1-7 are new modifiers applied before the existing `apply_delta()` logic. The existing suppression, competition, and clamping remain unchanged within step 8.

---

## 10. Configuration

All new config under `emotions:` in `config.yaml`:

```yaml
emotions:
  mood:
    alpha: 0.02              # EMA speed (~1h to react significantly)
    decay_lambda: 0.1        # return to neutral in ~10h
    bias_factor: 0.3         # mood influence on deltas

  fatigue:
    dampening: 0.7           # max delta reduction during fatigue
    recovery_rate: 0.1       # recovery per hour (linear)

  habituation:
    threshold_count: 3       # triggers before attenuation
    window_seconds: 600      # 10-minute window
    decay_factor: 0.5        # each repetition halves the delta
    reset_seconds: 1800      # reset after 30 min
    exempt: ["anger"]        # no habituation for these

  memory:
    learning_rate: 0.05
    priming_factor: 0.05
    amplification_factor: 0.3
    decay_lambda_per_day: 0.01

  circadian:
    enabled: true
    timezone: "Europe/Paris"
    periods:
      night:     { hours: [0, 6],   anger: 1.3, joy: 1.0, sadness: 1.0, curiosity: 0.8, boredom: 1.1 }
      morning:   { hours: [6, 12],  anger: 0.9, joy: 1.1, sadness: 0.9, curiosity: 1.2, boredom: 0.9 }
      afternoon: { hours: [12, 18], anger: 1.0, joy: 1.0, sadness: 1.0, curiosity: 1.0, boredom: 1.0 }
      evening:   { hours: [18, 24], anger: 1.0, joy: 1.0, sadness: 1.15, curiosity: 1.0, boredom: 1.0 }
    transition_minutes: 30

  spontaneous:
    probability_per_tick: 0.02
    max_delta: 0.1
    events:
      wandering_thought: { weight: 30, effects: { curiosity: 0.05 } }
      pleasant_memory:   { weight: 20, effects: { joy: 0.05 } }
      unpleasant_memory: { weight: 10, effects: { sadness: 0.05 } }
      existential_ennui: { weight: 25, effects: { boredom: 0.08 } }
      creative_spark:    { weight: 15, effects: { curiosity: 0.08, boredom: -0.1 } }

  secondaries:
    frustration: { a: anger,     b: boredom,   threshold: 0.3 }
    nostalgia:   { a: joy,       b: sadness,   threshold: 0.3 }
    pride:       { a: joy,       b: curiosity,  threshold: 0.4 }
    anxiety:     { a: sadness,   b: curiosity,  threshold: 0.3 }
    contempt:    { a: anger,     b: boredom,   threshold: [0.4, 0.5] }
    wonder:      { a: curiosity, b: joy,        threshold: 0.5 }
```

---

## 11. Database Changes

### New table: `emotional_memory`

```sql
CREATE TABLE IF NOT EXISTS emotional_memory (
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    emotion TEXT NOT NULL,
    affinity REAL NOT NULL DEFAULT 0.0,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL,
    PRIMARY KEY (user_id, platform, emotion)
);
```

### Extended emotion persistence

Add mood and fatigue state to the existing emotion save/load mechanism:
- Option A: new columns in existing snapshot table
- Option B: separate `emotion_mood` and `emotion_fatigue` rows in a key-value store

Decision: **Option A** — add `mood_anger`, `mood_joy`, `mood_sadness`, `mood_curiosity`, `mood_boredom`, `fatigue_anger`, `fatigue_joy`, `fatigue_sadness`, `fatigue_curiosity`, `fatigue_boredom` columns. Simpler queries, single read on boot.

---

## 12. Files Impacted

| File | Change |
|---|---|
| `bot/core/emotion.py` | Mood state, fatigue, habituation, circadian, spontaneous events, secondary emotions, full delta pipeline |
| `bot/core/prompts.py` | Mood injection, secondary emotion directives, fluid transitions |
| `bot/persona/SECONDARIES.md` | **New** — behavioral directives for 6 secondary emotions (3 tiers each) |
| `bot/persona/COMPOSITES.md` | **Removed** — replaced by SECONDARIES.md |
| `bot/db/database.py` | New `emotional_memory` table, mood/fatigue columns in snapshots |
| `config.yaml` | New sections: mood, fatigue, habituation, memory, circadian, spontaneous, secondaries |
| `bot/config.py` | New dataclasses for all config sections |
| Tests | New test files for each layer + update existing emotion tests |

---

## 13. What Does NOT Change

- The 5 primary emotions and their core mechanics (decay, suppression, competition)
- NRCLex + LLM analysis pipeline
- Trust score and timeout system
- Persona prompt format (SOUL/IDENTITY/VOICE)
- DI architecture (EmotionEngine injected the same way)
- Memory system (Qdrant, context window)
- Dashboard (can be extended later to show mood/secondaries)
