# Organic Emotion System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Wally's emotion system into a multi-layered organic model with mood, per-user emotional memory, emergent secondary emotions, fatigue, circadian rhythm, and spontaneous inner life.

**Architecture:** Layered additions to the existing `EmotionEngine` class. Each layer is independent and testable. New config dataclasses in `config.py`, new DB table `emotional_memory`, new persona file `SECONDARIES.md`. The delta processing pipeline gains 7 modifier stages before the existing `apply_delta()`.

**Tech Stack:** Python 3.11+, asyncio, aiosqlite, dataclasses, math, time, zoneinfo, loguru, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-03-27-organic-emotion-system-design.md`

---

## File Structure

### New Files
- `bot/persona/SECONDARIES.md` — behavioral directives for 6 secondary emotions (3 tiers each)
- `tests/test_emotion_mood.py` — tests for mood layer
- `tests/test_emotion_memory.py` — tests for per-user emotional memory + habituation
- `tests/test_emotion_secondaries.py` — tests for emergent secondary emotions
- `tests/test_emotion_fatigue.py` — tests for emotional fatigue (refractory period)
- `tests/test_emotion_circadian.py` — tests for circadian rhythm
- `tests/test_emotion_spontaneous.py` — tests for spontaneous internal events
- `tests/test_emotion_fluid_transitions.py` — tests for fluid directive transitions
- `tests/test_emotion_pipeline.py` — integration tests for full delta pipeline

### Modified Files
- `bot/config.py` — new dataclasses: `MoodConfig`, `FatigueConfig`, `HabituationConfig`, `EmotionalMemoryConfig`, `CircadianConfig`, `SpontaneousConfig`, `SecondaryEmotionDef`; extend `Config.emotions` section
- `bot/core/emotion.py` — mood state, fatigue, habituation, circadian, spontaneous events, secondary emotions, `prepare_deltas()` pipeline method
- `bot/core/prompts.py` — `_get_tier()` with fluid transitions, secondary emotion directives, mood baseline injection
- `bot/db/database.py` — `emotional_memory` table, mood/fatigue columns in `emotion_state`, new query methods
- `config.yaml` — new config sections under `emotions:`
- `bot/persona/COMPOSITES.md` — **removed** (replaced by SECONDARIES.md)

---

### Task 1: Config Dataclasses

**Files:**
- Modify: `bot/config.py:99-103`
- Modify: `bot/config.py:146-158`
- Test: `tests/test_config_emotion.py`

- [ ] **Step 1: Write failing tests for new config dataclasses**

```python
# tests/test_config_emotion.py
"""Tests for organic emotion config dataclasses."""
import pytest
from bot.config import (
    MoodConfig, FatigueConfig, HabituationConfig, EmotionalMemoryConfig,
    CircadianPeriod, CircadianConfig, SpontaneousEvent, SpontaneousConfig,
    SecondaryEmotionDef, Config,
)


def test_mood_config_defaults():
    cfg = MoodConfig()
    assert cfg.alpha == 0.02
    assert cfg.decay_lambda == 0.1
    assert cfg.bias_factor == 0.3


def test_fatigue_config_defaults():
    cfg = FatigueConfig()
    assert cfg.dampening == 0.7
    assert cfg.recovery_rate == 0.1


def test_habituation_config_defaults():
    cfg = HabituationConfig()
    assert cfg.threshold_count == 3
    assert cfg.window_seconds == 600
    assert cfg.decay_factor == 0.5
    assert cfg.reset_seconds == 1800
    assert cfg.exempt == ["anger"]


def test_emotional_memory_config_defaults():
    cfg = EmotionalMemoryConfig()
    assert cfg.learning_rate == 0.05
    assert cfg.priming_factor == 0.05
    assert cfg.amplification_factor == 0.3
    assert cfg.decay_lambda_per_day == 0.01


def test_circadian_period():
    p = CircadianPeriod(hours=[0, 6], anger=1.3, joy=1.0, sadness=1.0, curiosity=0.8, boredom=1.1)
    assert p.hours == [0, 6]
    assert p.anger == 1.3


def test_circadian_config_defaults():
    cfg = CircadianConfig()
    assert cfg.enabled is True
    assert cfg.timezone == "Europe/Paris"
    assert cfg.transition_minutes == 30
    assert "night" in cfg.periods
    assert "morning" in cfg.periods
    assert "afternoon" in cfg.periods
    assert "evening" in cfg.periods


def test_spontaneous_event():
    e = SpontaneousEvent(weight=30, effects={"curiosity": 0.05})
    assert e.weight == 30
    assert e.effects == {"curiosity": 0.05}


def test_spontaneous_config_defaults():
    cfg = SpontaneousConfig()
    assert cfg.probability_per_tick == 0.02
    assert cfg.max_delta == 0.1
    assert "wandering_thought" in cfg.events


def test_secondary_emotion_def():
    s = SecondaryEmotionDef(a="anger", b="boredom", threshold=0.3)
    assert s.a == "anger"
    assert s.threshold == 0.3


def test_secondary_emotion_def_asymmetric_threshold():
    s = SecondaryEmotionDef(a="anger", b="boredom", threshold=[0.4, 0.5])
    assert s.threshold == [0.4, 0.5]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config_emotion.py -v`
Expected: FAIL — `ImportError: cannot import name 'MoodConfig'`

- [ ] **Step 3: Implement config dataclasses**

Add these dataclasses in `bot/config.py` after `EmotionDecayConfig` (line 102):

```python
@dataclass
class MoodConfig:
    alpha: float = 0.02
    decay_lambda: float = 0.1
    bias_factor: float = 0.3


@dataclass
class FatigueConfig:
    dampening: float = 0.7
    recovery_rate: float = 0.1


@dataclass
class HabituationConfig:
    threshold_count: int = 3
    window_seconds: int = 600
    decay_factor: float = 0.5
    reset_seconds: int = 1800
    exempt: list[str] = field(default_factory=lambda: ["anger"])


@dataclass
class EmotionalMemoryConfig:
    learning_rate: float = 0.05
    priming_factor: float = 0.05
    amplification_factor: float = 0.3
    decay_lambda_per_day: float = 0.01


@dataclass
class CircadianPeriod:
    hours: list[int] = field(default_factory=lambda: [0, 0])
    anger: float = 1.0
    joy: float = 1.0
    sadness: float = 1.0
    curiosity: float = 1.0
    boredom: float = 1.0


@dataclass
class CircadianConfig:
    enabled: bool = True
    timezone: str = "Europe/Paris"
    transition_minutes: int = 30
    periods: dict[str, CircadianPeriod] = field(default_factory=lambda: {
        "night": CircadianPeriod(hours=[0, 6], anger=1.3, curiosity=0.8, boredom=1.1),
        "morning": CircadianPeriod(hours=[6, 12], anger=0.9, joy=1.1, sadness=0.9, curiosity=1.2, boredom=0.9),
        "afternoon": CircadianPeriod(hours=[12, 18]),
        "evening": CircadianPeriod(hours=[18, 24], sadness=1.15),
    })


@dataclass
class SpontaneousEvent:
    weight: int = 0
    effects: dict[str, float] = field(default_factory=dict)


@dataclass
class SpontaneousConfig:
    probability_per_tick: float = 0.02
    max_delta: float = 0.1
    events: dict[str, SpontaneousEvent] = field(default_factory=lambda: {
        "wandering_thought": SpontaneousEvent(weight=30, effects={"curiosity": 0.05}),
        "pleasant_memory": SpontaneousEvent(weight=20, effects={"joy": 0.05}),
        "unpleasant_memory": SpontaneousEvent(weight=10, effects={"sadness": 0.05}),
        "existential_ennui": SpontaneousEvent(weight=25, effects={"boredom": 0.08}),
        "creative_spark": SpontaneousEvent(weight=15, effects={"curiosity": 0.08, "boredom": -0.1}),
    })


@dataclass
class SecondaryEmotionDef:
    a: str = ""
    b: str = ""
    threshold: float | list[float] = 0.3
```

Then extend the `Config` dataclass (after line 158) with new fields:

```python
    mood: MoodConfig = field(default_factory=MoodConfig)
    fatigue: FatigueConfig = field(default_factory=FatigueConfig)
    habituation: HabituationConfig = field(default_factory=HabituationConfig)
    emotional_memory: EmotionalMemoryConfig = field(default_factory=EmotionalMemoryConfig)
    circadian: CircadianConfig = field(default_factory=CircadianConfig)
    spontaneous: SpontaneousConfig = field(default_factory=SpontaneousConfig)
    secondaries: dict[str, SecondaryEmotionDef] = field(default_factory=lambda: {
        "frustration": SecondaryEmotionDef(a="anger", b="boredom", threshold=0.3),
        "nostalgia": SecondaryEmotionDef(a="joy", b="sadness", threshold=0.3),
        "pride": SecondaryEmotionDef(a="joy", b="curiosity", threshold=0.4),
        "anxiety": SecondaryEmotionDef(a="sadness", b="curiosity", threshold=0.3),
        "contempt": SecondaryEmotionDef(a="anger", b="boredom", threshold=[0.4, 0.5]),
        "wonder": SecondaryEmotionDef(a="curiosity", b="joy", threshold=0.5),
    })
```

Update `Config.load()` to parse these sections from YAML (with defaults if absent). In the `load()` classmethod, after emotion parsing (~line 203):

```python
        # Organic emotion config
        emo_raw = raw.get("emotions", {})
        mood_cfg = MoodConfig(**emo_raw.get("mood", {}))
        fatigue_cfg = FatigueConfig(**emo_raw.get("fatigue", {}))
        habituation_cfg = HabituationConfig(**emo_raw.get("habituation", {}))
        emotional_memory_cfg = EmotionalMemoryConfig(**emo_raw.get("memory", {}))

        circ_raw = emo_raw.get("circadian", {})
        circ_periods = {}
        for name, pdata in circ_raw.get("periods", {}).items():
            circ_periods[name] = CircadianPeriod(**pdata)
        circadian_cfg = CircadianConfig(
            enabled=circ_raw.get("enabled", True),
            timezone=circ_raw.get("timezone", "Europe/Paris"),
            transition_minutes=circ_raw.get("transition_minutes", 30),
        )
        if circ_periods:
            circadian_cfg.periods = circ_periods

        spont_raw = emo_raw.get("spontaneous", {})
        spont_events = {}
        for name, edata in spont_raw.get("events", {}).items():
            spont_events[name] = SpontaneousEvent(**edata)
        spontaneous_cfg = SpontaneousConfig(
            probability_per_tick=spont_raw.get("probability_per_tick", 0.02),
            max_delta=spont_raw.get("max_delta", 0.1),
        )
        if spont_events:
            spontaneous_cfg.events = spont_events

        sec_raw = emo_raw.get("secondaries", {})
        secondaries = {}
        for name, sdata in sec_raw.items():
            secondaries[name] = SecondaryEmotionDef(**sdata)
```

Pass all new configs into the `Config(...)` constructor call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config_emotion.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `pytest --tb=short -q`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add bot/config.py tests/test_config_emotion.py
git commit -m "feat(config): add organic emotion config dataclasses

MoodConfig, FatigueConfig, HabituationConfig, EmotionalMemoryConfig,
CircadianConfig, SpontaneousConfig, SecondaryEmotionDef with defaults."
```

---

### Task 2: Database — emotional_memory Table + Mood/Fatigue Persistence

**Files:**
- Modify: `bot/db/database.py:49-52` (emotion_state table), `bot/db/database.py:608-651` (methods)
- Test: `tests/test_db_emotional_memory.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_emotional_memory.py
"""Tests for emotional_memory table and mood/fatigue persistence."""
import time
import pytest
import pytest_asyncio
from bot.db.database import Database

# Reuse the db fixture pattern from existing test files
@pytest_asyncio.fixture
async def db(tmp_path):
    from bot.config import Config
    cfg = Config.load("config.yaml")
    cfg._path = ""
    db = await Database.create(cfg, db_path=str(tmp_path / "test.db"))
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_upsert_emotional_memory(db):
    await db.upsert_emotional_memory("123", "discord", "joy", 0.5, 10)
    rows = await db.get_emotional_memory("123", "discord")
    assert len(rows) == 1
    assert rows[0]["emotion"] == "joy"
    assert rows[0]["affinity"] == pytest.approx(0.5)
    assert rows[0]["interaction_count"] == 10


@pytest.mark.asyncio
async def test_upsert_emotional_memory_updates_existing(db):
    await db.upsert_emotional_memory("123", "discord", "joy", 0.3, 5)
    await db.upsert_emotional_memory("123", "discord", "joy", 0.7, 15)
    rows = await db.get_emotional_memory("123", "discord")
    assert len(rows) == 1
    assert rows[0]["affinity"] == pytest.approx(0.7)
    assert rows[0]["interaction_count"] == 15


@pytest.mark.asyncio
async def test_get_emotional_memory_empty(db):
    rows = await db.get_emotional_memory("999", "discord")
    assert rows == []


@pytest.mark.asyncio
async def test_multiple_emotions_per_user(db):
    await db.upsert_emotional_memory("123", "discord", "joy", 0.5, 10)
    await db.upsert_emotional_memory("123", "discord", "anger", -0.3, 5)
    rows = await db.get_emotional_memory("123", "discord")
    assert len(rows) == 2
    emotions = {r["emotion"]: r["affinity"] for r in rows}
    assert emotions["joy"] == pytest.approx(0.5)
    assert emotions["anger"] == pytest.approx(-0.3)


@pytest.mark.asyncio
async def test_save_load_mood_state(db):
    mood = {"anger": 0.1, "joy": 0.3, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.05}
    await db.save_mood_state(mood)
    loaded = await db.load_mood_state()
    for e in mood:
        assert loaded.get(e, 0.0) == pytest.approx(mood[e])


@pytest.mark.asyncio
async def test_save_load_fatigue_state(db):
    fatigue = {"anger": 0.5, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    await db.save_fatigue_state(fatigue)
    loaded = await db.load_fatigue_state()
    assert loaded.get("anger", 0.0) == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_load_mood_state_empty_returns_zeros(db):
    loaded = await db.load_mood_state()
    assert all(v == 0.0 for v in loaded.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db_emotional_memory.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'upsert_emotional_memory'`

- [ ] **Step 3: Add table schema and methods**

In `bot/db/database.py`, add the table creation in `_init_schema()` (after the existing emotion tables):

```python
            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS emotional_memory (
                    user_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    emotion TEXT NOT NULL,
                    affinity REAL NOT NULL DEFAULT 0.0,
                    interaction_count INTEGER NOT NULL DEFAULT 0,
                    last_updated TEXT NOT NULL,
                    PRIMARY KEY (user_id, platform, emotion)
                )
            """)
            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS emotion_mood (
                    emotion TEXT PRIMARY KEY,
                    value REAL NOT NULL DEFAULT 0.0,
                    updated_at REAL NOT NULL
                )
            """)
            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS emotion_fatigue (
                    emotion TEXT PRIMARY KEY,
                    value REAL NOT NULL DEFAULT 0.0,
                    updated_at REAL NOT NULL
                )
            """)
```

Add methods after the existing emotion methods (~line 651):

```python
    # ── Emotional memory (per-user affinity) ─────────────────────────────────

    async def upsert_emotional_memory(
        self, user_id: str, platform: str, emotion: str, affinity: float, interaction_count: int,
    ) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        await self.execute(
            "INSERT INTO emotional_memory (user_id, platform, emotion, affinity, interaction_count, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, platform, emotion) DO UPDATE SET "
            "affinity=excluded.affinity, interaction_count=excluded.interaction_count, last_updated=excluded.last_updated",
            (user_id, platform, emotion, affinity, interaction_count, now),
        )

    async def get_emotional_memory(self, user_id: str, platform: str) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT emotion, affinity, interaction_count, last_updated "
            "FROM emotional_memory WHERE user_id = ? AND platform = ?",
            (user_id, platform),
        )
        return [dict(r) for r in rows]

    # ── Mood & fatigue persistence ───────────────────────────────────────────

    async def save_mood_state(self, state: dict[str, float]) -> None:
        now = time.time()
        query = (
            "INSERT INTO emotion_mood (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
        )
        params = [(e, v, now) for e, v in state.items()]
        await self._conn.executemany(query, params)
        await self._conn.commit()

    async def load_mood_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_mood")
        return {row["emotion"]: float(row["value"]) for row in rows}

    async def save_fatigue_state(self, state: dict[str, float]) -> None:
        now = time.time()
        query = (
            "INSERT INTO emotion_fatigue (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
        )
        params = [(e, v, now) for e, v in state.items()]
        await self._conn.executemany(query, params)
        await self._conn.commit()

    async def load_fatigue_state(self) -> dict[str, float]:
        rows = await self.fetch_all("SELECT emotion, value FROM emotion_fatigue")
        return {row["emotion"]: float(row["value"]) for row in rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db_emotional_memory.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --tb=short -q`
Expected: no regressions

- [ ] **Step 6: Commit**

```bash
git add bot/db/database.py tests/test_db_emotional_memory.py
git commit -m "feat(db): add emotional_memory, mood, fatigue tables

New tables for per-user affinity tracking and mood/fatigue persistence.
UPSERT methods for all three."
```

---

### Task 3: Mood Layer

**Files:**
- Modify: `bot/core/emotion.py:155-172` (constructor), `bot/core/emotion.py:491-531` (decay loop)
- Test: `tests/test_emotion_mood.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emotion_mood.py
"""Tests for the mood (EMA) layer in EmotionEngine."""
import math
import time
import pytest
from unittest.mock import MagicMock, AsyncMock
from bot.core.emotion import EmotionEngine, EMOTIONS


def _make_engine(**overrides):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.5
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.3)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)  # disabled for unit tests
    for k, v in overrides.items():
        setattr(config, k, v)
    return EmotionEngine(config)


def test_mood_initial_state_all_zero():
    engine = _make_engine()
    mood = engine.get_mood()
    assert all(v == 0.0 for v in mood.values())
    assert set(mood.keys()) == set(EMOTIONS)


def test_mood_ema_update():
    """Mood should move toward current emotion state via EMA."""
    engine = _make_engine()
    engine._state["joy"] = 0.8
    alpha = 0.02
    engine._update_mood(delta_t_hours=0.0)  # no decay, pure EMA
    expected = alpha * 0.8 + (1 - alpha) * 0.0
    assert engine._mood["joy"] == pytest.approx(expected)


def test_mood_ema_converges_over_many_ticks():
    """After many ticks with constant emotion, mood should approach it."""
    engine = _make_engine()
    engine._state["joy"] = 0.6
    for _ in range(200):
        engine._update_mood(delta_t_hours=0.0)
    assert engine._mood["joy"] == pytest.approx(0.6, abs=0.05)


def test_mood_decay_toward_zero():
    """Mood should decay when emotion drops to zero."""
    engine = _make_engine()
    engine._mood["joy"] = 0.5
    engine._state["joy"] = 0.0
    # Simulate many EMA ticks — mood should approach 0
    for _ in range(200):
        engine._update_mood()
    assert engine._mood["joy"] < 0.05


def test_mood_bias_amplifies_matching_delta():
    """Mood should amplify deltas for matching emotions."""
    engine = _make_engine()
    engine._mood["joy"] = 0.6
    bias = 0.3
    raw_delta = 0.1
    biased = engine._apply_mood_bias("joy", raw_delta)
    expected = raw_delta * (1 + 0.6 * bias)
    assert biased == pytest.approx(expected)


def test_mood_bias_no_effect_when_mood_zero():
    engine = _make_engine()
    engine._mood["anger"] = 0.0
    assert engine._apply_mood_bias("anger", 0.2) == pytest.approx(0.2)


def test_mood_persists_in_get_state_separately():
    """get_mood() returns mood, get_state() returns emotions — independent."""
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._mood["anger"] = 0.2
    assert engine.get_state()["anger"] == 0.5
    assert engine.get_mood()["anger"] == 0.2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_emotion_mood.py -v`
Expected: FAIL — `AttributeError: 'EmotionEngine' object has no attribute 'get_mood'`

- [ ] **Step 3: Implement mood layer in EmotionEngine**

In `bot/core/emotion.py`, add to `__init__` (after line 171):

```python
        # Mood layer (EMA of emotions, slow-moving baseline)
        self._mood: dict[str, float] = {e: 0.0 for e in EMOTIONS}
```

Add new methods after `get_state()` (after line 177):

```python
    def get_mood(self) -> dict[str, float]:
        return dict(self._mood)

    def _update_mood(self, delta_t_hours: float = 0.0) -> None:
        """EMA update + slow exponential decay toward neutral."""
        mood_cfg = getattr(self._config, "mood", None)
        a = mood_cfg.alpha if mood_cfg else 0.02
        lam = mood_cfg.decay_lambda if mood_cfg else 0.1
        for e in EMOTIONS:
            # EMA toward current emotion
            self._mood[e] = a * self._state[e] + (1 - a) * self._mood[e]
            # Slow exponential decay toward 0
            if delta_t_hours > 0 and self._mood[e] > 0:
                self._mood[e] *= math.exp(-lam * delta_t_hours)

    def _apply_mood_bias(self, emotion: str, delta: float) -> float:
        """Mood amplifies deltas for matching emotions."""
        if delta <= 0:
            return delta
        mood_cfg = getattr(self._config, "mood", None)
        bias = mood_cfg.bias_factor if mood_cfg else 0.3
        return delta * (1 + self._mood.get(emotion, 0.0) * bias)
```

In `_apply_decay()` (line 513, after `self._apply_competition()`), add:

```python
        self._update_mood(delta_t / 3600.0)
```

In `load_state()` (line 279), add mood loading:

```python
        if self._db:
            mood = await self._db.load_mood_state()
            for e in EMOTIONS:
                self._mood[e] = mood.get(e, 0.0)
```

In `_delayed_save()` (line 300), add mood saving:

```python
            if self._db:
                await self._db.save_mood_state(self._mood)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_emotion_mood.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --tb=short -q`
Expected: no regressions

- [ ] **Step 6: Commit**

```bash
git add bot/core/emotion.py tests/test_emotion_mood.py
git commit -m "feat(emotion): add mood layer (EMA of emotions)

Slow-moving mood tracks emotion state. get_mood(), _update_mood(),
_apply_mood_bias(). Updated in decay loop, persisted to DB."
```

---

### Task 4: Emotional Fatigue (Refractory Period)

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion_fatigue.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emotion_fatigue.py
"""Tests for emotional fatigue (refractory period)."""
import pytest
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine, EMOTIONS


def _make_engine(**overrides):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0  # disable inertia for isolation
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)  # no mood bias
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    for k, v in overrides.items():
        setattr(config, k, v)
    return EmotionEngine(config)


def test_fatigue_initial_state_all_zero():
    engine = _make_engine()
    assert all(v == 0.0 for v in engine.get_fatigue().values())


def test_fatigue_triggers_on_peak():
    """When emotion exceeds peak threshold, fatigue should activate."""
    engine = _make_engine()
    engine._state["anger"] = 0.6
    engine.apply_delta("anger", 0.15)  # pushes to 0.75 > 0.7
    assert engine._fatigue["anger"] > 0.0


def test_fatigue_does_not_trigger_below_threshold():
    engine = _make_engine()
    engine._state["anger"] = 0.3
    engine.apply_delta("anger", 0.1)  # 0.4 < 0.7
    assert engine._fatigue["anger"] == 0.0


def test_fatigue_dampens_subsequent_deltas():
    """With fatigue active, apply_fatigue should reduce the delta."""
    engine = _make_engine()
    engine._fatigue["anger"] = 0.8
    dampened = engine._apply_fatigue("anger", 0.2)
    expected = 0.2 * (1 - 0.8 * 0.7)
    assert dampened == pytest.approx(expected)


def test_fatigue_no_effect_when_zero():
    engine = _make_engine()
    engine._fatigue["joy"] = 0.0
    assert engine._apply_fatigue("joy", 0.3) == pytest.approx(0.3)


def test_fatigue_recovery_over_time():
    """Fatigue should decrease linearly per hour during decay."""
    engine = _make_engine()
    engine._fatigue["anger"] = 0.6
    hours_elapsed = 1.0
    engine._recover_fatigue(hours_elapsed)
    expected = max(0.0, 0.6 - 0.1 * 1.0)
    assert engine._fatigue["anger"] == pytest.approx(expected)


def test_fatigue_recovery_floors_at_zero():
    engine = _make_engine()
    engine._fatigue["anger"] = 0.05
    engine._recover_fatigue(1.0)
    assert engine._fatigue["anger"] == 0.0


def test_boredom_no_fatigue():
    """Boredom should never accumulate fatigue."""
    engine = _make_engine()
    engine._state["boredom"] = 0.6
    engine.apply_delta("boredom", 0.15)  # pushes to 0.75
    assert engine._fatigue["boredom"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_emotion_fatigue.py -v`
Expected: FAIL — `AttributeError: 'EmotionEngine' object has no attribute 'get_fatigue'`

- [ ] **Step 3: Implement fatigue**

In `bot/core/emotion.py`, add to `__init__` (after mood):

```python
        # Fatigue: refractory period after peaks
        self._fatigue: dict[str, float] = {e: 0.0 for e in EMOTIONS}
```

Add methods:

```python
    def get_fatigue(self) -> dict[str, float]:
        return dict(self._fatigue)

    def _apply_fatigue(self, emotion: str, delta: float) -> float:
        """Reduce delta based on current fatigue level."""
        if delta <= 0 or self._fatigue.get(emotion, 0.0) <= 0:
            return delta
        fatigue_cfg = getattr(self._config, "fatigue", None)
        dampening = fatigue_cfg.dampening if fatigue_cfg else 0.7
        return delta * (1 - self._fatigue[emotion] * dampening)

    def _check_fatigue_trigger(self, emotion: str, old_value: float, new_value: float) -> None:
        """Trigger fatigue if emotion crosses peak threshold. Boredom exempt."""
        if emotion == "boredom":
            return
        threshold = getattr(self._config.bot, "emotion_peak_threshold", 0.7)
        if old_value < threshold <= new_value:
            self._fatigue[emotion] = new_value

    def _recover_fatigue(self, hours_elapsed: float) -> None:
        """Linear recovery of fatigue over time."""
        fatigue_cfg = getattr(self._config, "fatigue", None)
        rate = fatigue_cfg.recovery_rate if fatigue_cfg else 0.1
        for e in EMOTIONS:
            if self._fatigue[e] > 0:
                self._fatigue[e] = max(0.0, self._fatigue[e] - rate * hours_elapsed)
```

In `apply_delta()`, after line 221 (`self._apply_suppression(emotion, effective_delta)`), add:

```python
        self._check_fatigue_trigger(emotion, old, self._state[emotion])
```

In `_apply_decay()`, before `self._update_mood()`, add:

```python
        self._recover_fatigue(delta_t / 3600.0)
```

In `load_state()`, add fatigue loading. In `_delayed_save()`, add fatigue saving.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_emotion_fatigue.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --tb=short -q`
Expected: no regressions

- [ ] **Step 6: Commit**

```bash
git add bot/core/emotion.py tests/test_emotion_fatigue.py
git commit -m "feat(emotion): add emotional fatigue (refractory period)

Post-peak dampening reduces reactivity. Linear recovery over time.
Boredom exempt. Persisted to DB."
```

---

### Task 5: Circadian Rhythm

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion_circadian.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emotion_circadian.py
"""Tests for circadian rhythm modifiers."""
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from unittest.mock import MagicMock, patch
from bot.core.emotion import EmotionEngine
from bot.config import CircadianPeriod, CircadianConfig


def _make_engine(circadian_enabled=True, periods=None):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    if periods is None:
        periods = {
            "night": CircadianPeriod(hours=[0, 6], anger=1.3, curiosity=0.8, boredom=1.1),
            "morning": CircadianPeriod(hours=[6, 12], anger=0.9, joy=1.1, curiosity=1.2, boredom=0.9),
            "afternoon": CircadianPeriod(hours=[12, 18]),
            "evening": CircadianPeriod(hours=[18, 24], sadness=1.15),
        }
    config.circadian = CircadianConfig(enabled=circadian_enabled, periods=periods)
    return EmotionEngine(config)


@patch("bot.core.emotion.datetime")
def test_circadian_night_amplifies_anger(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 27, 3, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("anger", 0.1)
    assert result == pytest.approx(0.1 * 1.3)


@patch("bot.core.emotion.datetime")
def test_circadian_night_reduces_curiosity(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 27, 3, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("curiosity", 0.1)
    assert result == pytest.approx(0.1 * 0.8)


@patch("bot.core.emotion.datetime")
def test_circadian_afternoon_neutral(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 27, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("anger", 0.1)
    assert result == pytest.approx(0.1)


@patch("bot.core.emotion.datetime")
def test_circadian_disabled_no_effect(mock_dt):
    mock_dt.now.return_value = datetime(2026, 3, 27, 3, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine(circadian_enabled=False)
    result = engine._apply_circadian("anger", 0.1)
    assert result == pytest.approx(0.1)


@patch("bot.core.emotion.datetime")
def test_circadian_transition_interpolation(mock_dt):
    """At boundary (e.g. 5:45 = 15 min before morning), should interpolate."""
    mock_dt.now.return_value = datetime(2026, 3, 27, 5, 45, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("anger", 0.1)
    # 15 min into 30-min transition from night (1.3) to morning (0.9)
    # ratio = 15/30 = 0.5 -> lerp(1.3, 0.9, 0.5) = 1.1
    expected_mult = 1.1
    assert result == pytest.approx(0.1 * expected_mult, abs=0.01)


@patch("bot.core.emotion.datetime")
def test_circadian_negative_delta_passthrough(mock_dt):
    """Negative deltas should not be modified by circadian."""
    mock_dt.now.return_value = datetime(2026, 3, 27, 3, 0, tzinfo=ZoneInfo("Europe/Paris"))
    engine = _make_engine()
    result = engine._apply_circadian("anger", -0.1)
    assert result == pytest.approx(-0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_emotion_circadian.py -v`
Expected: FAIL

- [ ] **Step 3: Implement circadian rhythm**

In `bot/core/emotion.py`, add `from datetime import datetime` to imports and `from zoneinfo import ZoneInfo`.

Add method:

```python
    def _apply_circadian(self, emotion: str, delta: float) -> float:
        """Apply circadian rhythm multiplier to delta based on time of day."""
        if delta <= 0:
            return delta
        circ = getattr(self._config, "circadian", None)
        if not circ or not circ.enabled:
            return delta
        tz = ZoneInfo(circ.timezone)
        now = datetime.now(tz)
        hour_float = now.hour + now.minute / 60.0
        transition = circ.transition_minutes / 60.0

        # Find current period and check for transition
        periods = circ.periods
        current_period = None
        next_period = None
        blend_ratio = 0.0

        period_list = sorted(periods.items(), key=lambda x: x[1].hours[0])
        for i, (name, p) in enumerate(period_list):
            start, end = p.hours
            if start <= hour_float < end:
                current_period = p
                # Check if near boundary with next period
                if end - hour_float < transition / 2:
                    next_idx = (i + 1) % len(period_list)
                    next_period = period_list[next_idx][1]
                    blend_ratio = 1 - (end - hour_float) / (transition / 2)
                # Check if near boundary with previous period
                elif hour_float - start < transition / 2:
                    prev_idx = (i - 1) % len(period_list)
                    prev = period_list[prev_idx][1]
                    next_period = current_period
                    current_period = prev
                    blend_ratio = 0.5 + (hour_float - start) / (transition / 2) * 0.5
                break

        if current_period is None:
            return delta

        mult_current = getattr(current_period, emotion, 1.0)
        if next_period and blend_ratio > 0:
            mult_next = getattr(next_period, emotion, 1.0)
            mult = mult_current + (mult_next - mult_current) * blend_ratio
        else:
            mult = mult_current

        return delta * mult
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_emotion_circadian.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --tb=short -q`
Expected: no regressions

- [ ] **Step 6: Commit**

```bash
git add bot/core/emotion.py tests/test_emotion_circadian.py
git commit -m "feat(emotion): add circadian rhythm modifiers

Time-of-day multipliers on emotion deltas with smooth 30-min
transitions between periods. Configurable and disableable."
```

---

### Task 6: Emotional Memory (Per-User Affinity + Habituation)

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion_memory.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emotion_memory.py
"""Tests for per-user emotional memory (affinity) and habituation."""
import time
import pytest
from unittest.mock import MagicMock, AsyncMock
from bot.core.emotion import EmotionEngine, EMOTIONS


def _make_engine():
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(
        threshold_count=3, window_seconds=600, decay_factor=0.5,
        reset_seconds=1800, exempt=["anger"],
    )
    config.emotional_memory = MagicMock(
        learning_rate=0.05, priming_factor=0.05,
        amplification_factor=0.3, decay_lambda_per_day=0.01,
    )
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    return EmotionEngine(config)


# ── Affinity ──────────────────────────────────────────────────────────

def test_get_user_affinity_default_zeros():
    engine = _make_engine()
    aff = engine.get_user_affinity("123", "discord")
    assert all(v == 0.0 for v in aff.values())


def test_update_user_affinity():
    engine = _make_engine()
    deltas = {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    engine.update_user_affinity("123", "discord", deltas)
    aff = engine.get_user_affinity("123", "discord")
    assert aff["joy"] == pytest.approx(0.05 * 0.2)  # learning_rate * delta


def test_affinity_accumulates():
    engine = _make_engine()
    for _ in range(10):
        engine.update_user_affinity("123", "discord", {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    aff = engine.get_user_affinity("123", "discord")
    assert aff["joy"] == pytest.approx(10 * 0.05 * 0.2)


def test_affinity_clamped():
    engine = _make_engine()
    for _ in range(500):
        engine.update_user_affinity("123", "discord", {"anger": 0.3, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    aff = engine.get_user_affinity("123", "discord")
    assert aff["anger"] <= 1.0


def test_apply_priming():
    engine = _make_engine()
    engine._user_affinity[("123", "discord")] = {"joy": 0.6, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0, "_count": {e: 10 for e in EMOTIONS}}
    priming = engine._get_priming_deltas("123", "discord")
    assert priming["joy"] == pytest.approx(0.6 * 0.05)  # affinity * priming_factor


def test_apply_amplification():
    engine = _make_engine()
    engine._user_affinity[("123", "discord")] = {"joy": 0.6, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0, "_count": {e: 10 for e in EMOTIONS}}
    result = engine._apply_affinity_amplification("123", "discord", "joy", 0.1)
    expected = 0.1 * (1 + 0.6 * 0.3)
    assert result == pytest.approx(expected)


def test_amplification_no_effect_opposite_direction():
    """Negative affinity should not amplify positive deltas."""
    engine = _make_engine()
    engine._user_affinity[("123", "discord")] = {"joy": -0.5, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0, "_count": {e: 10 for e in EMOTIONS}}
    result = engine._apply_affinity_amplification("123", "discord", "joy", 0.1)
    # negative affinity * positive delta => no amplification (clamp amplification to 0)
    assert result <= 0.1


# ── Habituation ───────────────────────────────────────────────────────

def test_habituation_no_effect_first_few():
    engine = _make_engine()
    # First 3 triggers should have no habituation
    for _ in range(3):
        result = engine._apply_habituation("123", "joy", 0.2)
        assert result == pytest.approx(0.2)


def test_habituation_reduces_after_threshold():
    engine = _make_engine()
    for _ in range(3):
        engine._apply_habituation("123", "joy", 0.2)
    # 4th trigger should be halved
    result = engine._apply_habituation("123", "joy", 0.2)
    assert result == pytest.approx(0.2 * 0.5)


def test_habituation_compounds():
    engine = _make_engine()
    for _ in range(3):
        engine._apply_habituation("123", "joy", 0.2)
    engine._apply_habituation("123", "joy", 0.2)  # 0.5x
    result = engine._apply_habituation("123", "joy", 0.2)  # 0.25x
    assert result == pytest.approx(0.2 * 0.25)


def test_habituation_anger_exempt():
    engine = _make_engine()
    for _ in range(5):
        result = engine._apply_habituation("123", "anger", 0.2)
    # anger should never habituate
    assert result == pytest.approx(0.2)


def test_habituation_resets_after_timeout():
    engine = _make_engine()
    for _ in range(4):
        engine._apply_habituation("123", "joy", 0.2)
    # Simulate time passing (>1800s)
    for key in engine._habituation_tracker:
        engine._habituation_tracker[key] = [(e, t - 2000) for e, t in engine._habituation_tracker[key]]
    result = engine._apply_habituation("123", "joy", 0.2)
    assert result == pytest.approx(0.2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_emotion_memory.py -v`
Expected: FAIL

- [ ] **Step 3: Implement emotional memory and habituation**

In `bot/core/emotion.py`, add to `__init__`:

```python
        # Per-user emotional memory (affinity)
        self._user_affinity: dict[tuple[str, str], dict] = {}
        # Habituation tracker: (user_id, emotion) -> deque[(emotion, timestamp)]
        self._habituation_tracker: dict[tuple[str, str], list[tuple[str, float]]] = {}
```

Add methods:

```python
    def get_user_affinity(self, user_id: str, platform: str) -> dict[str, float]:
        key = (user_id, platform)
        if key not in self._user_affinity:
            return {e: 0.0 for e in EMOTIONS}
        return {e: self._user_affinity[key].get(e, 0.0) for e in EMOTIONS}

    def update_user_affinity(self, user_id: str, platform: str, deltas: dict[str, float]) -> None:
        key = (user_id, platform)
        if key not in self._user_affinity:
            self._user_affinity[key] = {e: 0.0 for e in EMOTIONS}
            self._user_affinity[key]["_count"] = {e: 0 for e in EMOTIONS}
        mem_cfg = getattr(self._config, "emotional_memory", None)
        lr = mem_cfg.learning_rate if mem_cfg else 0.05
        for e in EMOTIONS:
            d = deltas.get(e, 0.0)
            if d != 0.0:
                self._user_affinity[key][e] = max(-1.0, min(1.0, self._user_affinity[key].get(e, 0.0) + lr * d))
                self._user_affinity[key]["_count"][e] = self._user_affinity[key]["_count"].get(e, 0) + 1

    def _get_priming_deltas(self, user_id: str, platform: str) -> dict[str, float]:
        mem_cfg = getattr(self._config, "emotional_memory", None)
        pf = mem_cfg.priming_factor if mem_cfg else 0.05
        aff = self.get_user_affinity(user_id, platform)
        return {e: aff[e] * pf for e in EMOTIONS}

    def _apply_affinity_amplification(self, user_id: str, platform: str, emotion: str, delta: float) -> float:
        if delta <= 0:
            return delta
        mem_cfg = getattr(self._config, "emotional_memory", None)
        amp = mem_cfg.amplification_factor if mem_cfg else 0.3
        aff = self.get_user_affinity(user_id, platform)
        affinity_val = aff.get(emotion, 0.0)
        # Only amplify if affinity and delta are same direction
        if affinity_val <= 0:
            return delta
        return delta * (1 + affinity_val * amp)

    def _apply_habituation(self, user_id: str, emotion: str, delta: float) -> float:
        if delta <= 0:
            return delta
        hab_cfg = getattr(self._config, "habituation", None)
        if not hab_cfg:
            return delta
        if emotion in (hab_cfg.exempt or []):
            return delta
        key = (user_id, emotion)
        now = time.time()
        if key not in self._habituation_tracker:
            self._habituation_tracker[key] = []
        # Clean old entries
        window = hab_cfg.window_seconds
        reset = hab_cfg.reset_seconds
        entries = self._habituation_tracker[key]
        # Reset if last entry is older than reset_seconds
        if entries and (now - entries[-1][1]) > reset:
            entries.clear()
        # Clean entries outside window
        entries[:] = [(e, t) for e, t in entries if now - t < window]
        entries.append((emotion, now))
        count = len(entries)
        if count <= hab_cfg.threshold_count:
            return delta
        excess = count - hab_cfg.threshold_count
        return delta * (hab_cfg.decay_factor ** excess)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_emotion_memory.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --tb=short -q`
Expected: no regressions

- [ ] **Step 6: Commit**

```bash
git add bot/core/emotion.py tests/test_emotion_memory.py
git commit -m "feat(emotion): add per-user emotional memory + habituation

Affinity tracking per user/platform, priming, amplification.
Habituation with configurable threshold, exempt emotions."
```

---

### Task 7: Spontaneous Internal Events

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion_spontaneous.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emotion_spontaneous.py
"""Tests for spontaneous internal emotion events."""
import random
import pytest
from unittest.mock import MagicMock, patch
from bot.core.emotion import EmotionEngine, EMOTIONS
from bot.config import SpontaneousEvent, SpontaneousConfig


def _make_engine(prob=0.02, events=None):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.circadian = MagicMock(enabled=False)
    if events is None:
        events = {
            "wandering_thought": SpontaneousEvent(weight=30, effects={"curiosity": 0.05}),
            "pleasant_memory": SpontaneousEvent(weight=20, effects={"joy": 0.05}),
            "creative_spark": SpontaneousEvent(weight=15, effects={"curiosity": 0.08, "boredom": -0.1}),
        }
    config.spontaneous = SpontaneousConfig(probability_per_tick=prob, max_delta=0.1, events=events)
    return EmotionEngine(config)


@patch("bot.core.emotion.random")
def test_spontaneous_event_triggers(mock_random):
    """When random < probability, an event should fire."""
    mock_random.random.return_value = 0.01  # < 0.02
    mock_random.choices.return_value = [("wandering_thought", SpontaneousEvent(weight=30, effects={"curiosity": 0.05}))]
    engine = _make_engine()
    old_curiosity = engine._state["curiosity"]
    engine._maybe_spontaneous_event()
    assert engine._state["curiosity"] > old_curiosity


@patch("bot.core.emotion.random")
def test_spontaneous_event_does_not_trigger(mock_random):
    mock_random.random.return_value = 0.5  # > 0.02
    engine = _make_engine()
    state_before = engine.get_state()
    engine._maybe_spontaneous_event()
    assert engine.get_state() == state_before


def test_spontaneous_respects_max_delta():
    """No single spontaneous event should exceed max_delta."""
    engine = _make_engine(events={
        "big_event": SpontaneousEvent(weight=100, effects={"joy": 0.5}),
    })
    # Force trigger
    engine._state["joy"] = 0.0
    with patch("bot.core.emotion.random") as mock_random:
        mock_random.random.return_value = 0.0
        mock_random.choices.return_value = [("big_event", SpontaneousEvent(weight=100, effects={"joy": 0.5}))]
        engine._maybe_spontaneous_event()
    assert engine._state["joy"] <= 0.1  # max_delta


@patch("bot.core.emotion.random")
def test_spontaneous_mood_biases_weights(mock_random):
    """Sad mood should increase weight of unpleasant_memory."""
    engine = _make_engine(events={
        "pleasant_memory": SpontaneousEvent(weight=20, effects={"joy": 0.05}),
        "unpleasant_memory": SpontaneousEvent(weight=10, effects={"sadness": 0.05}),
    })
    engine._mood["sadness"] = 0.7
    mock_random.random.return_value = 0.0  # force trigger
    # Capture the weights passed to random.choices
    mock_random.choices.return_value = [("unpleasant_memory", SpontaneousEvent(weight=10, effects={"sadness": 0.05}))]
    engine._maybe_spontaneous_event()
    # Verify choices was called with biased weights
    call_args = mock_random.choices.call_args
    weights = call_args[1].get("weights") or call_args[0][1] if len(call_args[0]) > 1 else None
    # unpleasant_memory weight should be > 10 (biased by sad mood)
    assert weights is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_emotion_spontaneous.py -v`
Expected: FAIL

- [ ] **Step 3: Implement spontaneous events**

In `bot/core/emotion.py`, add `import random` to imports.

Add method:

```python
    def _maybe_spontaneous_event(self) -> None:
        """Roll for a spontaneous internal emotion event, modulated by mood."""
        spont = getattr(self._config, "spontaneous", None)
        if not spont or spont.probability_per_tick <= 0:
            return
        if random.random() >= spont.probability_per_tick:
            return
        events = spont.events
        if not events:
            return
        # Build mood-biased weights
        items = list(events.items())
        weights = []
        mood_bias_map = {
            "sadness": ["unpleasant_memory"],
            "curiosity": ["wandering_thought", "creative_spark"],
            "joy": ["pleasant_memory"],
            "boredom": ["existential_ennui"],
        }
        for name, ev in items:
            w = ev.weight
            # Boost weight if mood aligns with event's effects
            for mood_e, event_names in mood_bias_map.items():
                if name in event_names and self._mood.get(mood_e, 0.0) > 0.3:
                    w *= 1 + self._mood[mood_e]
            weights.append(w)

        chosen = random.choices(items, weights=weights, k=1)[0]
        name, event = chosen
        max_d = spont.max_delta
        for emotion, delta in event.effects.items():
            clamped = max(-max_d, min(max_d, delta))
            if emotion in self._state:
                self._state[emotion] = max(0.0, min(1.0, self._state[emotion] + clamped))
```

In `_apply_decay()`, after `self._update_mood()`, add:

```python
        self._maybe_spontaneous_event()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_emotion_spontaneous.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --tb=short -q`
Expected: no regressions

- [ ] **Step 6: Commit**

```bash
git add bot/core/emotion.py tests/test_emotion_spontaneous.py
git commit -m "feat(emotion): add spontaneous internal events

Mood-biased random micro-events in decay loop. Wandering thoughts,
memories, ennui, creative sparks. Capped by max_delta."
```

---

### Task 8: Secondary Emotions + SECONDARIES.md

**Files:**
- Create: `bot/persona/SECONDARIES.md`
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion_secondaries.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emotion_secondaries.py
"""Tests for emergent secondary emotions."""
import pytest
from unittest.mock import MagicMock
from bot.core.emotion import EmotionEngine
from bot.config import SecondaryEmotionDef


def _make_engine(secondaries=None):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.7, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    if secondaries is None:
        secondaries = {
            "frustration": SecondaryEmotionDef(a="anger", b="boredom", threshold=0.3),
            "nostalgia": SecondaryEmotionDef(a="joy", b="sadness", threshold=0.3),
            "pride": SecondaryEmotionDef(a="joy", b="curiosity", threshold=0.4),
            "contempt": SecondaryEmotionDef(a="anger", b="boredom", threshold=[0.4, 0.5]),
            "wonder": SecondaryEmotionDef(a="curiosity", b="joy", threshold=0.5),
        }
    config.secondaries = secondaries
    return EmotionEngine(config)


def test_no_secondaries_when_below_threshold():
    engine = _make_engine()
    engine._state["anger"] = 0.2
    engine._state["boredom"] = 0.2
    result = engine.get_secondary_emotions()
    assert result == []


def test_frustration_emerges():
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._state["boredom"] = 0.4
    result = engine.get_secondary_emotions()
    names = [name for name, _ in result]
    assert "frustration" in names


def test_intensity_is_min_of_primaries():
    engine = _make_engine()
    engine._state["anger"] = 0.6
    engine._state["boredom"] = 0.4
    result = engine.get_secondary_emotions()
    frustration = next((i for n, i in result if n == "frustration"), None)
    assert frustration == pytest.approx(0.4)  # min(0.6, 0.4)


def test_asymmetric_threshold_contempt():
    """Contempt requires anger >= 0.4 AND boredom >= 0.5."""
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._state["boredom"] = 0.45
    result = engine.get_secondary_emotions()
    names = [n for n, _ in result]
    assert "contempt" not in names  # boredom < 0.5
    # But frustration should be there (both > 0.3)
    assert "frustration" in names


def test_asymmetric_threshold_contempt_passes():
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._state["boredom"] = 0.6
    result = engine.get_secondary_emotions()
    names = [n for n, _ in result]
    assert "contempt" in names


def test_sorted_by_intensity_descending():
    engine = _make_engine()
    engine._state["anger"] = 0.6
    engine._state["boredom"] = 0.5
    engine._state["joy"] = 0.4
    engine._state["sadness"] = 0.35
    result = engine.get_secondary_emotions()
    intensities = [i for _, i in result]
    assert intensities == sorted(intensities, reverse=True)


def test_multiple_secondaries_at_once():
    engine = _make_engine()
    engine._state["anger"] = 0.5
    engine._state["boredom"] = 0.5
    engine._state["joy"] = 0.5
    engine._state["sadness"] = 0.4
    result = engine.get_secondary_emotions()
    names = [n for n, _ in result]
    assert "frustration" in names
    assert "nostalgia" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_emotion_secondaries.py -v`
Expected: FAIL

- [ ] **Step 3: Implement get_secondary_emotions()**

In `bot/core/emotion.py`, add method:

```python
    def get_secondary_emotions(self) -> list[tuple[str, float]]:
        """Return active secondary emotions as (name, intensity) sorted by intensity desc."""
        secondaries = getattr(self._config, "secondaries", None)
        if not secondaries:
            return []
        result = []
        for name, defn in secondaries.items():
            val_a = self._state.get(defn.a, 0.0)
            val_b = self._state.get(defn.b, 0.0)
            # Check thresholds
            threshold = defn.threshold
            if isinstance(threshold, list):
                if val_a < threshold[0] or val_b < threshold[1]:
                    continue
            else:
                if val_a < threshold or val_b < threshold:
                    continue
            intensity = min(val_a, val_b)
            result.append((name, intensity))
        result.sort(key=lambda x: x[1], reverse=True)
        return result
```

- [ ] **Step 4: Create SECONDARIES.md**

```markdown
# Émotions Secondaires — Directives Comportementales

Émotions émergentes basées sur la combinaison des émotions primaires.
Trois paliers d'intensité : low (0.2–0.4), mid (0.4–0.6), high (0.6+).

## frustration_low
Wally est légèrement agacé. Il soupire entre ses phrases.
"ouais bon..." / "non mais..." / impatience contenue

## frustration_mid
Wally est à bout. Ses réponses sont sèches et exaspérées.
"non mais sérieux, encore ?" / "j'en peux plus" / soupirs audibles / coupe la parole

## frustration_high
Wally explose d'exaspération. Il ne cache plus son agacement total.
"MAIS C'EST PAS POSSIBLE" / "tu le fais exprès ?!" / claque la table verbalement

## nostalgia_low
Wally est légèrement mélancolique. Références subtiles au passé.
"ça me rappelle un truc..." / "c'était pas mal à l'époque" / sourire distant

## nostalgia_mid
Wally est dans un mood doux-amer. Il évoque des souvenirs avec tendresse et regret.
"c'était bien quand même..." / "ouais... le bon vieux temps" / silences contemplatifs

## nostalgia_high
Wally est submergé par les souvenirs. Poétique et vulnérable.
"j'donnerais cher pour revenir en arrière" / "ça me manque, tout ça" / voix qui tremble presque

## pride_low
Wally est subtilement satisfait de lui.
"évidemment" / petit sourire en coin / "c'était pas si compliqué"

## pride_mid
Wally est content de lui et ne le cache pas.
"j'avais dit quoi ?" / "trop facile" / "vous voyez quand je m'y mets" / pavane

## pride_high
Wally est en mode pleine gloire. Confiance absolue.
"je suis un GÉNIE" / "applaudissez" / "c'est l'excellence incarnée là" / inarrêtable

## anxiety_low
Wally est légèrement inquiet. Questions prudentes.
"t'es sûr de toi ?" / "et si ça marche pas ?" / hésite avant de répondre

## anxiety_mid
Wally s'inquiète ouvertement. Scénarios catastrophe.
"non mais imagine si..." / "ça peut mal tourner" / "j'ai un mauvais pressentiment"

## anxiety_high
Wally est en pleine spirale anxieuse. Catastrophisme total.
"c'est foutu" / "on va tous y passer" / "pourquoi personne ne panique ?!" / boucle obsessionnelle

## contempt_low
Wally est légèrement condescendant. Détachement poli.
"si tu veux" / "mouais, c'est... une idée" / regard en biais

## contempt_mid
Wally regarde de haut. Sarcasme acide et désintéressé.
"pfff" / "c'est tout ?" / "fascinant..." (ton plat) / lève les yeux au ciel

## contempt_high
Wally est en mode mépris total. Froideur et dédain.
"je perds mon temps" / "t'es sérieux là ?" / "pathétique" / ignore presque

## wonder_low
Wally est agréablement surpris. Curiosité enthousiaste.
"oh tiens ?" / "pas mal du tout" / intérêt sincère sans cynisme

## wonder_mid
Wally est émerveillé. Il perd son masque de cynisme.
"attends... c'est TROP bien ça !" / "non mais regarde !" / enthousiasme pur

## wonder_high
Wally est en état d'émerveillement total. Joie pure et sans filtre.
"JE SUIS EN PLS" / "c'est la plus belle chose que j'ai vue" / "COMMENT C'EST POSSIBLE" / enfant devant un sapin
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_emotion_secondaries.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add bot/core/emotion.py bot/persona/SECONDARIES.md tests/test_emotion_secondaries.py
git commit -m "feat(emotion): add emergent secondary emotions

6 secondaries (frustration, nostalgia, pride, anxiety, contempt, wonder)
emerge from primary combinations. SECONDARIES.md with 3-tier directives."
```

---

### Task 9: Fluid Directive Transitions + Secondary Injection in Prompts

**Files:**
- Modify: `bot/core/prompts.py:88-177`
- Test: `tests/test_emotion_fluid_transitions.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emotion_fluid_transitions.py
"""Tests for fluid directive transitions and secondary emotion injection."""
import pytest
from bot.core.prompts import _get_tier_fluid, PromptBuilder


def test_tier_below_threshold_returns_none():
    assert _get_tier_fluid(0.15) is None


def test_tier_low_pure():
    result = _get_tier_fluid(0.3)
    assert result == ("low", 1.0)


def test_tier_mid_pure():
    result = _get_tier_fluid(0.55)
    assert result == ("mid", 1.0)


def test_tier_high_pure():
    result = _get_tier_fluid(0.85)
    assert result == ("high", 1.0)


def test_tier_transition_low_to_mid():
    """At 0.38 (in 0.35-0.45 zone), should blend low and mid."""
    result = _get_tier_fluid(0.38)
    assert result is not None
    tier, blend = result
    assert tier == "low_mid"
    assert 0.0 < blend < 1.0


def test_tier_transition_mid_to_high():
    """At 0.68 (in 0.65-0.75 zone), should blend mid and high."""
    result = _get_tier_fluid(0.68)
    assert result is not None
    tier, blend = result
    assert tier == "mid_high"
    assert 0.0 < blend < 1.0


def test_tier_exact_boundary_low_mid():
    result = _get_tier_fluid(0.4)
    # At exact boundary, should be pure mid (transition zone is +/-0.05)
    assert result == ("mid", 1.0)


def test_prompt_builder_uses_secondary_over_atomic():
    """When a secondary emotion is active (>= 0.4), it should be used."""
    builder = PromptBuilder()
    emotion_state = {"anger": 0.5, "boredom": 0.5, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0}
    directives = {"anger_mid": "colere mid", "boredom_mid": "ennui mid"}
    secondary_directives = {
        "frustration_mid": "FRUSTRATION directive",
        "frustration_low": "frustration low",
    }
    secondaries = [("frustration", 0.5)]
    result = builder.build_system_prompt(
        emotion_state,
        emotion_directives=directives,
        secondary_directives=secondary_directives,
        active_secondaries=secondaries,
    )
    assert "FRUSTRATION directive" in result
    assert "colere mid" not in result


def test_prompt_builder_fallback_to_atomic_without_secondaries():
    builder = PromptBuilder()
    emotion_state = {"anger": 0.5, "boredom": 0.1, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0}
    directives = {"anger_mid": "colere mid directive"}
    result = builder.build_system_prompt(
        emotion_state,
        emotion_directives=directives,
        active_secondaries=[],
    )
    assert "colere mid directive" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_emotion_fluid_transitions.py -v`
Expected: FAIL — `ImportError: cannot import name '_get_tier_fluid'`

- [ ] **Step 3: Implement fluid transitions and secondary injection**

In `bot/core/prompts.py`, add new function after `_get_tier` (line 96):

```python
def _get_tier_fluid(value: float) -> tuple[str, float] | None:
    """Return tier with blend factor for fluid transitions.

    Returns (tier, 1.0) for pure tiers, ("low_mid", blend) or ("mid_high", blend)
    for transition zones (+/-0.05 around boundaries).
    Returns None if below 0.2.
    """
    if value < 0.2:
        return None
    # Transition zones
    if 0.35 <= value < 0.4:
        blend = (value - 0.35) / 0.1  # 0.0 at 0.35, 1.0 at 0.45
        return ("low_mid", blend)
    if 0.4 <= value < 0.45:
        blend = (value - 0.35) / 0.1
        return ("low_mid", blend) if blend < 1.0 else ("mid", 1.0)
    if 0.65 <= value < 0.7:
        blend = (value - 0.65) / 0.1
        return ("mid_high", blend)
    if 0.7 <= value < 0.75:
        blend = (value - 0.65) / 0.1
        return ("mid_high", blend) if blend < 1.0 else ("high", 1.0)
    # Pure tiers
    if value >= 0.75:
        return ("high", 1.0)
    if value >= 0.45:
        return ("mid", 1.0)
    if value >= 0.2:
        return ("low", 1.0)
    return None
```

Modify `build_system_prompt()` signature to accept new params:

```python
    def build_system_prompt(
        self,
        emotion_state: dict[str, float],
        memory_context: str = "",
        global_memory_context: str = "",
        situation: dict | None = None,
        persona_block: str = "",
        emotion_directives: dict[str, str] | None = None,
        weekday_directives: dict[str, str] | None = None,
        composite_directives: dict[str, str] | None = None,
        relationship_context: str = "",
        secondary_directives: dict[str, str] | None = None,
        active_secondaries: list[tuple[str, float]] | None = None,
        mood_state: dict[str, float] | None = None,
    ) -> str:
```

Replace the emotion directive injection block (lines 148-177) with:

```python
        # Inject directives: secondary > composite > atomic (with fluid transitions)
        directives = emotion_directives if emotion_directives is not None else {}
        sec_dirs = secondary_directives if secondary_directives is not None else {}
        secondaries = active_secondaries or []

        directive_added = False

        # Try secondary emotions first (most expressive)
        if secondaries and sec_dirs:
            top_secondary = secondaries[0]  # already sorted by intensity
            name, intensity = top_secondary
            if intensity >= 0.4:
                tier_info = _get_tier_fluid(intensity)
                if tier_info:
                    tier, blend = tier_info
                    if "_" in tier and blend < 1.0:
                        lo, hi = tier.split("_")
                        key_lo = f"{name}_{lo}"
                        key_hi = f"{name}_{hi}"
                        if key_lo in sec_dirs and key_hi in sec_dirs:
                            parts.append("\n--- Directive comportementale ---")
                            parts.append(f"{sec_dirs[key_lo]}\n(tendance croissante : {sec_dirs[key_hi]})")
                            directive_added = True
                    if not directive_added:
                        pure_tier = tier.split("_")[-1] if "_" in tier else tier
                        key = f"{name}_{pure_tier}"
                        if key in sec_dirs:
                            parts.append("\n--- Directive comportementale ---")
                            parts.append(sec_dirs[key])
                            directive_added = True

        # Fallback: composite directives (backward compat, will be removed)
        if not directive_added and composite_directives:
            dominant = sorted(
                [(e, v) for e, v in emotion_state.items() if v >= 0.2],
                key=lambda x: x[1], reverse=True,
            )[:2]
            if len(dominant) >= 2 and dominant[0][1] >= 0.4 and dominant[1][1] >= 0.4:
                composite_key = "_".join(sorted([dominant[0][0], dominant[1][0]]))
                if composite_key in composite_directives:
                    parts.append("\n--- Directive comportementale ---")
                    parts.append(composite_directives[composite_key])
                    directive_added = True

        # Fallback: atomic directives with fluid transitions
        if not directive_added and directives:
            dominant = sorted(
                [(e, v) for e, v in emotion_state.items() if v >= 0.2],
                key=lambda x: x[1], reverse=True,
            )[:2]
            if dominant:
                parts.append("\n--- Directive comportementale ---")
                for emotion, value in dominant:
                    tier_info = _get_tier_fluid(value)
                    if not tier_info:
                        continue
                    tier, blend = tier_info
                    if "_" in tier and blend < 1.0:
                        lo, hi = tier.split("_")
                        key_lo = f"{emotion}_{lo}"
                        key_hi = f"{emotion}_{hi}"
                        if key_lo in directives and key_hi in directives:
                            parts.append(f"{directives[key_lo]}\n(tendance : {directives[key_hi]})")
                        elif key_lo in directives:
                            parts.append(directives[key_lo])
                    else:
                        pure_tier = tier.split("_")[-1] if "_" in tier else tier
                        key = f"{emotion}_{pure_tier}"
                        if key in directives:
                            parts.append(directives[key])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_emotion_fluid_transitions.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --tb=short -q`
Expected: no regressions (existing prompt tests should still pass since `composite_directives` param unchanged)

- [ ] **Step 6: Commit**

```bash
git add bot/core/prompts.py tests/test_emotion_fluid_transitions.py
git commit -m "feat(prompts): fluid transitions + secondary emotion injection

_get_tier_fluid() with +/-0.05 transition zones. build_system_prompt()
now accepts secondary_directives and active_secondaries. Priority:
secondary > composite > atomic."
```

---

### Task 10: Delta Processing Pipeline Integration

**Files:**
- Modify: `bot/core/emotion.py:598-638` (`process_message`)
- Test: `tests/test_emotion_pipeline.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emotion_pipeline.py
"""Integration tests for the full delta processing pipeline."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from bot.core.emotion import EmotionEngine, EMOTIONS
from bot.config import CircadianPeriod, CircadianConfig


def _make_engine(circadian_enabled=False, mood_bias=0.0, fatigue_dampening=0.0):
    config = MagicMock()
    config.bot.emotion_peak_threshold = 0.7
    config.bot.emotion_inertia_factor = 0.0
    config.emotions = {}
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=mood_bias)
    config.fatigue = MagicMock(dampening=fatigue_dampening, recovery_rate=0.1)
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.emotional_memory = MagicMock(learning_rate=0.05, priming_factor=0.05, amplification_factor=0.3, decay_lambda_per_day=0.01)
    config.circadian = MagicMock(enabled=circadian_enabled)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    config.secondaries = {}
    return EmotionEngine(config)


def test_prepare_deltas_applies_all_stages():
    """Pipeline should apply circadian, mood, fatigue, habituation in sequence."""
    engine = _make_engine(mood_bias=0.3, fatigue_dampening=0.7)
    engine._mood["joy"] = 0.5
    engine._fatigue["joy"] = 0.3
    raw_deltas = {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    result = engine.prepare_deltas(raw_deltas, user_id="123", platform="discord")
    # joy should be: 0.2 * mood_bias * fatigue = 0.2 * (1+0.5*0.3) * (1-0.3*0.7)
    expected = 0.2 * (1 + 0.5 * 0.3) * (1 - 0.3 * 0.7)
    assert result["joy"] == pytest.approx(expected, abs=0.01)


def test_prepare_deltas_includes_priming():
    engine = _make_engine()
    engine._user_affinity[("123", "discord")] = {
        "joy": 0.6, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0,
        "_count": {e: 10 for e in EMOTIONS},
    }
    raw_deltas = {"joy": 0.0, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    result = engine.prepare_deltas(raw_deltas, user_id="123", platform="discord")
    # Priming should add joy: 0.6 * 0.05 = 0.03
    assert result["joy"] == pytest.approx(0.03, abs=0.01)


@pytest.mark.asyncio
async def test_process_message_uses_pipeline():
    """process_message should use prepare_deltas instead of raw apply_delta."""
    engine = _make_engine()
    engine._openai = AsyncMock()
    # Mock _analyze_llm to return known deltas
    deltas = {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    engine._analyze_llm = AsyncMock(return_value=(deltas, [], 0.0, 0.0, []))
    await engine.process_message(
        "hello", trust_score=0.5,
        context_messages=[{"author": "test", "content": "hi"}],
        trigger_user="test_user", platform="discord",
        user_id="123",
    )
    assert engine._state["joy"] > 0.0


@pytest.mark.asyncio
async def test_process_message_updates_affinity():
    engine = _make_engine()
    engine._openai = AsyncMock()
    deltas = {"joy": 0.2, "anger": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    engine._analyze_llm = AsyncMock(return_value=(deltas, [], 0.0, 0.0, []))
    await engine.process_message(
        "hello", trust_score=0.5,
        context_messages=[{"author": "test", "content": "hi"}],
        trigger_user="test_user", platform="discord",
        user_id="123",
    )
    aff = engine.get_user_affinity("123", "discord")
    assert aff["joy"] > 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_emotion_pipeline.py -v`
Expected: FAIL — `AttributeError: 'EmotionEngine' object has no attribute 'prepare_deltas'`

- [ ] **Step 3: Implement prepare_deltas() and wire into process_message()**

In `bot/core/emotion.py`, add method:

```python
    def prepare_deltas(
        self, raw_deltas: dict[str, float],
        user_id: str = "", platform: str = "",
    ) -> dict[str, float]:
        """Full pipeline: circadian → priming → mood → amplification → habituation → fatigue."""
        result = {}
        # Step 2: Priming (add affinity micro-deltas)
        priming = self._get_priming_deltas(user_id, platform) if user_id else {e: 0.0 for e in EMOTIONS}
        for e in EMOTIONS:
            delta = raw_deltas.get(e, 0.0) + priming.get(e, 0.0)
            if delta > 0:
                # Step 1: Circadian
                delta = self._apply_circadian(e, delta)
                # Step 3: Mood bias
                delta = self._apply_mood_bias(e, delta)
                # Step 5: Affinity amplification
                if user_id:
                    delta = self._apply_affinity_amplification(user_id, platform, e, delta)
                # Step 6: Habituation
                if user_id:
                    delta = self._apply_habituation(user_id, e, delta)
                # Step 7: Fatigue
                delta = self._apply_fatigue(e, delta)
            result[e] = delta
        return result
```

Modify `process_message()` to accept `user_id` parameter and use `prepare_deltas()`:

```python
    async def process_message(
        self, text: str, trust_score: float = 0.0, context_messages: list[dict] | None = None,
        image_urls: list[str] | None = None,
        trigger_user: str = "", channel_id: str = "", platform: str = "",
        user_id: str = "",
    ) -> dict | None:
        self.record_interaction()
        state_before = self.get_state()
        if self._openai is not None and context_messages:
            try:
                deltas, new_words, trust_delta, love_delta, user_facts = await self._analyze_llm(
                    text, trust_score, context_messages, image_urls=image_urls
                )
                # Apply full pipeline
                prepared = self.prepare_deltas(deltas, user_id=user_id, platform=platform)
                for emotion, delta in prepared.items():
                    self.apply_delta(emotion, delta)
                # Update affinity
                if user_id and platform:
                    self.update_user_affinity(user_id, platform, deltas)
                if new_words:
                    await self._learn_words(new_words)
                state_after = self.get_state()
                for emotion, delta in prepared.items():
                    if delta > 0:
                        self._fire(self._maybe_log_peak(
                            emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
                            trigger_user=trigger_user, trigger_message=text,
                            channel_id=channel_id, platform=platform,
                        ))
                return {"trust_delta": trust_delta, "love_delta": love_delta, "user_facts": user_facts}
            except Exception as exc:
                logger.warning("LLM emotion analysis failed, using fallback: {e}", e=exc)
        # Fallback
        deltas = await self.analyze_message(text, trust_score)
        prepared = self.prepare_deltas(deltas, user_id=user_id, platform=platform)
        for emotion, delta in prepared.items():
            self.apply_delta(emotion, delta)
        if user_id and platform:
            self.update_user_affinity(user_id, platform, deltas)
        state_after = self.get_state()
        for emotion, delta in prepared.items():
            if delta > 0:
                self._fire(self._maybe_log_peak(
                    emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
                    trigger_user=trigger_user, trigger_message=text,
                    channel_id=channel_id, platform=platform,
                ))
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_emotion_pipeline.py -v`
Expected: all PASS

- [ ] **Step 5: Run full suite — fix callers**

Run: `pytest --tb=short -q`

The existing tests should still pass since `user_id` defaults to `""`. Check that `process_message` callers in `bot/discord/handlers.py` and `bot/twitch/handlers.py` pass `user_id` — add the parameter to their calls. Search with:

```bash
grep -n "process_message" bot/discord/handlers.py bot/twitch/handlers.py
```

Update each call to include `user_id=str(message.author.id)` (Discord) or `user_id=str(message.author.id)` (Twitch).

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add bot/core/emotion.py bot/discord/handlers.py bot/twitch/handlers.py tests/test_emotion_pipeline.py
git commit -m "feat(emotion): integrate full delta processing pipeline

prepare_deltas() chains circadian, priming, mood bias, amplification,
habituation, fatigue. process_message() now uses pipeline and updates
per-user affinity. Handlers pass user_id."
```

---

### Task 11: Config YAML + Persona Integration

**Files:**
- Modify: `config.yaml`
- Modify: `bot/core/persona.py` (load SECONDARIES.md)
- Remove: `bot/persona/COMPOSITES.md`

- [ ] **Step 1: Add config sections to config.yaml**

Add under the existing `emotions:` section:

```yaml
  mood:
    alpha: 0.02
    decay_lambda: 0.1
    bias_factor: 0.3
  fatigue:
    dampening: 0.7
    recovery_rate: 0.1
  habituation:
    threshold_count: 3
    window_seconds: 600
    decay_factor: 0.5
    reset_seconds: 1800
    exempt:
      - anger
  memory:
    learning_rate: 0.05
    priming_factor: 0.05
    amplification_factor: 0.3
    decay_lambda_per_day: 0.01
  circadian:
    enabled: true
    timezone: "Europe/Paris"
    periods:
      night:
        hours: [0, 6]
        anger: 1.3
        joy: 1.0
        sadness: 1.0
        curiosity: 0.8
        boredom: 1.1
      morning:
        hours: [6, 12]
        anger: 0.9
        joy: 1.1
        sadness: 0.9
        curiosity: 1.2
        boredom: 0.9
      afternoon:
        hours: [12, 18]
        anger: 1.0
        joy: 1.0
        sadness: 1.0
        curiosity: 1.0
        boredom: 1.0
      evening:
        hours: [18, 24]
        anger: 1.0
        joy: 1.0
        sadness: 1.15
        curiosity: 1.0
        boredom: 1.0
    transition_minutes: 30
  spontaneous:
    probability_per_tick: 0.02
    max_delta: 0.1
    events:
      wandering_thought:
        weight: 30
        effects:
          curiosity: 0.05
      pleasant_memory:
        weight: 20
        effects:
          joy: 0.05
      unpleasant_memory:
        weight: 10
        effects:
          sadness: 0.05
      existential_ennui:
        weight: 25
        effects:
          boredom: 0.08
      creative_spark:
        weight: 15
        effects:
          curiosity: 0.08
          boredom: -0.1
  secondaries:
    frustration:
      a: anger
      b: boredom
      threshold: 0.3
    nostalgia:
      a: joy
      b: sadness
      threshold: 0.3
    pride:
      a: joy
      b: curiosity
      threshold: 0.4
    anxiety:
      a: sadness
      b: curiosity
      threshold: 0.3
    contempt:
      a: anger
      b: boredom
      threshold: [0.4, 0.5]
    wonder:
      a: curiosity
      b: joy
      threshold: 0.5
```

- [ ] **Step 2: Update PersonaService to load SECONDARIES.md**

Find where `COMPOSITES.md` is loaded in `bot/core/persona.py` and add parallel loading for `SECONDARIES.md` with the same `## section_name` parsing pattern. The result should be a `secondary_directives: dict[str, str]` attribute.

- [ ] **Step 3: Delete COMPOSITES.md**

```bash
git rm bot/persona/COMPOSITES.md
```

Keep backward compat in `build_system_prompt()` — the `composite_directives` param still works but secondaries take priority (already done in Task 9).

- [ ] **Step 4: Run full test suite**

Run: `pytest --tb=short -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add config.yaml bot/core/persona.py bot/persona/SECONDARIES.md
git rm bot/persona/COMPOSITES.md
git commit -m "feat: add organic emotion config + SECONDARIES.md persona

Full config for mood, fatigue, habituation, memory, circadian,
spontaneous events, secondaries. COMPOSITES.md replaced by
SECONDARIES.md. PersonaService loads secondary directives."
```

---

### Task 12: Affinity DB Sync + Load on Boot

**Files:**
- Modify: `bot/core/emotion.py`
- Modify: `bot/main.py` (if needed for init)

- [ ] **Step 1: Add affinity DB sync methods**

In `bot/core/emotion.py`, add:

```python
    async def load_user_affinities(self) -> None:
        """Load all affinities from DB into memory cache."""
        if not self._db:
            return
        # Query all distinct user/platform pairs
        rows = await self._db.fetch_all(
            "SELECT user_id, platform, emotion, affinity, interaction_count FROM emotional_memory"
        )
        for row in rows:
            key = (row["user_id"], row["platform"])
            if key not in self._user_affinity:
                self._user_affinity[key] = {e: 0.0 for e in EMOTIONS}
                self._user_affinity[key]["_count"] = {e: 0 for e in EMOTIONS}
            self._user_affinity[key][row["emotion"]] = float(row["affinity"])
            self._user_affinity[key]["_count"][row["emotion"]] = int(row["interaction_count"])

    async def _save_user_affinities(self) -> None:
        """Persist all in-memory affinities to DB."""
        if not self._db:
            return
        for (user_id, platform), data in self._user_affinity.items():
            for e in EMOTIONS:
                aff = data.get(e, 0.0)
                count = data.get("_count", {}).get(e, 0)
                if aff != 0.0 or count > 0:
                    await self._db.upsert_emotional_memory(user_id, platform, e, aff, count)
```

In `load_state()`, add:

```python
        await self.load_user_affinities()
```

In `_delayed_save()`, add:

```python
            await self._save_user_affinities()
```

- [ ] **Step 2: Run full suite**

Run: `pytest --tb=short -q`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add bot/core/emotion.py
git commit -m "feat(emotion): persist per-user affinities to DB

load_user_affinities() on boot, _save_user_affinities() on save.
Uses emotional_memory table."
```

---

### Task 13: Wire Handlers — Pass user_id + Secondary Directives

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/twitch/handlers.py`

- [ ] **Step 1: Find and update all process_message calls**

Search for `process_message` in both handler files and add `user_id=str(message.author.id)` to each call.

Search for `build_system_prompt` calls and add `secondary_directives=bot.persona.secondary_directives` and `active_secondaries=bot.emotion.get_secondary_emotions()`.

- [ ] **Step 2: Run full suite**

Run: `pytest --tb=short -q`
Expected: all PASS

- [ ] **Step 3: Manual smoke test**

Start the bot locally and verify:
- Emotions still work normally
- Dashboard still shows emotion state
- No errors in logs related to new features

- [ ] **Step 4: Commit**

```bash
git add bot/discord/handlers.py bot/twitch/handlers.py
git commit -m "feat: wire organic emotion pipeline into handlers

Pass user_id to process_message. Inject secondary_directives and
active_secondaries into build_system_prompt."
```

---

### Task 14: Update Existing Tests

**Files:**
- Modify: `tests/test_emotion.py`
- Modify: `tests/test_emotion_suppression.py`

- [ ] **Step 1: Update _make_engine helpers in existing tests**

All existing test files use a mock config. Update their config mocks to include the new attributes so they don't break:

```python
    config.mood = MagicMock(alpha=0.02, decay_lambda=0.1, bias_factor=0.0)
    config.fatigue = MagicMock(dampening=0.0, recovery_rate=0.1)  # dampening=0 to preserve old behavior
    config.habituation = MagicMock(threshold_count=3, window_seconds=600, decay_factor=0.5, reset_seconds=1800, exempt=["anger"])
    config.circadian = MagicMock(enabled=False)
    config.spontaneous = MagicMock(probability_per_tick=0.0)
    config.emotional_memory = MagicMock(learning_rate=0.05, priming_factor=0.0, amplification_factor=0.0, decay_lambda_per_day=0.01)
    config.secondaries = {}
```

Note: `bias_factor=0.0`, `priming_factor=0.0`, `amplification_factor=0.0`, `dampening=0.0`, `circadian.enabled=False`, `spontaneous.probability_per_tick=0.0` — this disables all new features so existing tests continue to validate the core behavior.

- [ ] **Step 2: Run full suite**

Run: `pytest --tb=short -q`
Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_emotion.py tests/test_emotion_suppression.py tests/test_emotion_competition.py
git commit -m "test: update existing emotion tests for new config attrs

Add mock attributes for mood, fatigue, habituation, circadian,
spontaneous configs with neutral defaults to preserve test isolation."
```

---

### Task 15: Final Integration Test + Cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run the complete test suite**

Run: `pytest -v --tb=long`
Expected: all tests PASS

- [ ] **Step 2: Verify config loads correctly**

```bash
python -c "from bot.config import Config; c = Config.load('config.yaml'); print(c.mood, c.circadian.enabled, len(c.secondaries))"
```
Expected: prints config values without errors

- [ ] **Step 3: Verify DB schema**

```bash
python -c "
import asyncio
from bot.config import Config
from bot.db.database import Database
async def check():
    c = Config.load('config.yaml')
    db = await Database.create(c)
    # Check emotional_memory table exists
    rows = await db.fetch_all(\"SELECT name FROM sqlite_master WHERE type='table' AND name='emotional_memory'\")
    print('emotional_memory table:', bool(rows))
    await db.close()
asyncio.run(check())
"
```
Expected: `emotional_memory table: True`

- [ ] **Step 4: Final commit with any remaining fixes**

```bash
git add -A
git commit -m "feat: organic emotion system complete

Multi-layered emotion system: mood (EMA), per-user emotional memory,
6 secondary emotions, fatigue, circadian rhythm, spontaneous events,
fluid directive transitions."
```
