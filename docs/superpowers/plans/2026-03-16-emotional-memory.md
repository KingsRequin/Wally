# Emotional Memory Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à Wally un état émotionnel persistant, un historique émotionnel horodaté, des souvenirs colorés par l'émotion, un journal avec arc narratif, et un affichage en pourcentage.

**Architecture:** Deux nouvelles tables SQLite (`emotion_state`, `emotion_history`) alimentent `EmotionEngine` (persistence debouncée, snapshots horaires) et `DailyJournal` (arc narratif). `memory.add()` reçoit un tag émotionnel optionnel produit par `build_emotion_tag()` dans `emotion.py`. L'affichage des valeurs passe de float à pourcentage dans les commandes Discord.

**Tech Stack:** aiosqlite, asyncio (debounce via `create_task`), zoneinfo (Europe/Paris), pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-16-emotional-memory-design.md`

---

## Chunk 1: Base de données — tables et helpers

### Task 1: Tables `emotion_state` et `emotion_history` + helpers load/save

**Files:**
- Modify: `bot/db/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1.1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_database.py` :

```python
@pytest.mark.asyncio
async def test_emotion_tables_created(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    names = {row["name"] for row in tables}
    assert "emotion_state" in names
    assert "emotion_history" in names
    await db.close()


@pytest.mark.asyncio
async def test_save_and_load_emotion_state(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    state = {"anger": 0.3, "joy": 0.7, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.1}
    await db.save_emotion_state(state)
    loaded = await db.load_emotion_state()
    for emotion, value in state.items():
        assert abs(loaded[emotion] - value) < 0.001
    await db.close()


@pytest.mark.asyncio
async def test_load_emotion_state_returns_empty_dict_when_no_data(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    loaded = await db.load_emotion_state()
    assert loaded == {}
    await db.close()


@pytest.mark.asyncio
async def test_save_emotion_state_is_idempotent(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    state = {"anger": 0.2, "joy": 0.6, "sadness": 0.0, "curiosity": 0.4, "boredom": 0.0}
    await db.save_emotion_state(state)
    state2 = {"anger": 0.9, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    await db.save_emotion_state(state2)
    loaded = await db.load_emotion_state()
    assert abs(loaded["anger"] - 0.9) < 0.001
    assert abs(loaded["joy"] - 0.1) < 0.001
    await db.close()
```

- [ ] **Step 1.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py::test_emotion_tables_created tests/test_database.py::test_save_and_load_emotion_state tests/test_database.py::test_load_emotion_state_returns_empty_dict_when_no_data tests/test_database.py::test_save_emotion_state_is_idempotent -v
```

Attendu : `FAILED` — `AttributeError: 'Database' object has no attribute 'save_emotion_state'`

- [ ] **Step 1.3: Ajouter les tables dans `SCHEMA` et implémenter les helpers**

Dans `bot/db/database.py`, ajouter dans la constante `SCHEMA` (après la table `trust_scores`, avant le `"""`):

```python
CREATE TABLE IF NOT EXISTS emotion_state (
    emotion    TEXT PRIMARY KEY,
    value      REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS emotion_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at REAL NOT NULL,
    anger       REAL NOT NULL DEFAULT 0.0,
    joy         REAL NOT NULL DEFAULT 0.0,
    sadness     REAL NOT NULL DEFAULT 0.0,
    curiosity   REAL NOT NULL DEFAULT 0.0,
    boredom     REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_emotion_history_ts ON emotion_history(snapshot_at);
```

Puis ajouter à la fin de la classe `Database`, après `update_trust_score` :

```python
# ── Emotion persistence ───────────────────────────────────────────────────

async def load_emotion_state(self) -> dict[str, float]:
    rows = await self.fetch_all("SELECT emotion, value FROM emotion_state")
    return {row["emotion"]: float(row["value"]) for row in rows}

async def save_emotion_state(self, state: dict[str, float]) -> None:
    now = time.time()
    for emotion, value in state.items():
        await self.execute(
            "INSERT INTO emotion_state (emotion, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(emotion) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (emotion, value, now),
        )
```

- [ ] **Step 1.4: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py::test_emotion_tables_created tests/test_database.py::test_save_and_load_emotion_state tests/test_database.py::test_load_emotion_state_returns_empty_dict_when_no_data tests/test_database.py::test_save_emotion_state_is_idempotent -v
```

Attendu : `4 passed`

- [ ] **Step 1.5: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/db/database.py tests/test_database.py && git commit -m "feat: add emotion_state table + load/save helpers"
```

---

### Task 2: Helpers `insert_emotion_snapshot`, `get_today_emotion_snapshots`, `cleanup_old_emotion_history`

**Files:**
- Modify: `bot/db/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 2.1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_database.py` :

```python
@pytest.mark.asyncio
async def test_insert_and_get_today_snapshots(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    state = {"anger": 0.2, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    await db.insert_emotion_snapshot(state)
    await db.insert_emotion_snapshot(state)
    snapshots = await db.get_today_emotion_snapshots()
    assert len(snapshots) == 2
    assert abs(snapshots[0]["joy"] - 0.5) < 0.001
    await db.close()


@pytest.mark.asyncio
async def test_get_today_snapshots_returns_empty_list_when_none(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    snapshots = await db.get_today_emotion_snapshots()
    assert snapshots == []
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_removes_old_snapshots(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    # Insert an 8-day-old snapshot directly via raw SQL
    old_ts = time.time() - 8 * 86400
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.0, 0.0, 0.0, 0.0, 0.0)",
        (old_ts,),
    )
    # Insert a recent one
    await db.insert_emotion_snapshot(
        {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    await db.cleanup_old_emotion_history(days=7)
    rows = await db.fetch_all("SELECT * FROM emotion_history")
    assert len(rows) == 1  # seul le récent reste
    await db.close()
```

- [ ] **Step 2.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py::test_insert_and_get_today_snapshots tests/test_database.py::test_get_today_snapshots_returns_empty_list_when_none tests/test_database.py::test_cleanup_removes_old_snapshots -v
```

Attendu : `FAILED`

- [ ] **Step 2.3: Implémenter les 3 helpers**

Ajouter après `save_emotion_state` dans `bot/db/database.py` :

```python
async def insert_emotion_snapshot(self, state: dict[str, float]) -> None:
    await self.execute(
        "INSERT INTO emotion_history "
        "(snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            time.time(),
            state.get("anger", 0.0),
            state.get("joy", 0.0),
            state.get("sadness", 0.0),
            state.get("curiosity", 0.0),
            state.get("boredom", 0.0),
        ),
    )

async def get_today_emotion_snapshots(self) -> list[dict]:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Paris")
    midnight = datetime.now(_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    rows = await self.fetch_all(
        "SELECT * FROM emotion_history WHERE snapshot_at >= ? ORDER BY snapshot_at ASC",
        (midnight,),
    )
    return [dict(row) for row in rows]

async def cleanup_old_emotion_history(self, days: int = 7) -> None:
    cutoff = time.time() - days * 86400
    await self.execute(
        "DELETE FROM emotion_history WHERE snapshot_at < ?",
        (cutoff,),
    )
```

- [ ] **Step 2.4: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_database.py -v
```

Attendu : tous les tests DB passent (11+)

- [ ] **Step 2.5: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/db/database.py tests/test_database.py && git commit -m "feat: add emotion_history table + snapshot/query/cleanup helpers"
```

---

## Chunk 2: EmotionEngine — persistence et build_emotion_tag

### Task 3: Fonction module-level `build_emotion_tag()`

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion.py`

- [ ] **Step 3.1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_emotion.py` :

```python
# ── build_emotion_tag ─────────────────────────────────────────────────────────

def test_build_emotion_tag_with_dominant_emotions():
    from bot.core.emotion import build_emotion_tag
    state = {"anger": 0.0, "joy": 0.7, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0}
    tag = build_emotion_tag(state)
    assert "joy" in tag
    assert "curiosity" in tag
    assert tag.startswith("Wally:")


def test_build_emotion_tag_returns_empty_when_none_dominant():
    from bot.core.emotion import build_emotion_tag
    state = {"anger": 0.2, "joy": 0.3, "sadness": 0.0, "curiosity": 0.1, "boredom": 0.0}
    tag = build_emotion_tag(state)
    assert tag == ""


def test_build_emotion_tag_threshold_boundary():
    from bot.core.emotion import build_emotion_tag
    # Exactement au seuil : 0.4 → inclus
    state = {"anger": 0.4, "joy": 0.39, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    tag = build_emotion_tag(state)
    assert "anger" in tag
    assert "joy" not in tag
```

- [ ] **Step 3.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion.py::test_build_emotion_tag_with_dominant_emotions tests/test_emotion.py::test_build_emotion_tag_returns_empty_when_none_dominant tests/test_emotion.py::test_build_emotion_tag_threshold_boundary -v
```

Attendu : `FAILED` — `ImportError: cannot import name 'build_emotion_tag'`

- [ ] **Step 3.3: Implémenter `build_emotion_tag()`**

Dans `bot/core/emotion.py`, ajouter **avant** la classe `EmotionEngine` (après les constantes, à la fin de la section des variables globales) :

```python
def build_emotion_tag(emotion_state: dict[str, float]) -> str:
    """Construit un tag textuel à partir des émotions dominantes (≥ 0.4).

    Retourne "" si aucune émotion n'est dominante.
    Exemple : "Wally: joy, curiosity"
    """
    dominant = [e for e, v in emotion_state.items() if v >= 0.4]
    if not dominant:
        return ""
    return "Wally: " + ", ".join(dominant)
```

- [ ] **Step 3.4: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion.py::test_build_emotion_tag_with_dominant_emotions tests/test_emotion.py::test_build_emotion_tag_returns_empty_when_none_dominant tests/test_emotion.py::test_build_emotion_tag_threshold_boundary -v
```

Attendu : `3 passed`

- [ ] **Step 3.5: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/emotion.py tests/test_emotion.py && git commit -m "feat: add build_emotion_tag() module-level helper"
```

---

### Task 4: `EmotionEngine` — attributs `db`, `_dirty`, `_save_task`, `_ticks` + `load_state()`

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion.py`

- [ ] **Step 4.1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_emotion.py` :

```python
# ── Persistence ───────────────────────────────────────────────────────────────

def test_engine_persistence_attrs_initialized():
    engine = EmotionEngine(make_config())
    assert engine._ticks == 0
    assert engine._dirty is False
    assert engine._save_task is None
    assert engine._db is None


def test_engine_accepts_db_param():
    from unittest.mock import MagicMock
    db = MagicMock()
    engine = EmotionEngine(make_config(), db=db)
    assert engine._db is db


@pytest.mark.asyncio
async def test_load_state_no_db_does_not_raise():
    engine = EmotionEngine(make_config())
    await engine.load_state()  # db is None — should be a no-op
    assert all(v == 0.0 for v in engine.get_state().values())


@pytest.mark.asyncio
async def test_load_state_restores_persisted_values(tmp_path):
    from bot.db.database import Database
    db = await Database.create(str(tmp_path / "test.db"))
    # Sauvegarder un état en DB
    await db.save_emotion_state(
        {"anger": 0.3, "joy": 0.8, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0}
    )
    # Créer un engine et charger
    engine = EmotionEngine(make_config(), db=db)
    assert engine.get_state()["joy"] == 0.0  # avant load_state
    await engine.load_state()
    assert abs(engine.get_state()["joy"] - 0.8) < 0.001
    assert abs(engine.get_state()["anger"] - 0.3) < 0.001
    await db.close()


@pytest.mark.asyncio
async def test_load_state_clamps_values(tmp_path):
    from bot.db.database import Database
    db = await Database.create(str(tmp_path / "test.db"))
    # Insérer une valeur hors plage directement
    await db.execute(
        "INSERT INTO emotion_state (emotion, value, updated_at) VALUES ('joy', 1.5, 0)",
    )
    engine = EmotionEngine(make_config(), db=db)
    await engine.load_state()
    assert engine.get_state()["joy"] == 1.0  # clampé
    await db.close()
```

- [ ] **Step 4.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion.py::test_engine_persistence_attrs_initialized tests/test_emotion.py::test_engine_accepts_db_param tests/test_emotion.py::test_load_state_no_db_does_not_raise tests/test_emotion.py::test_load_state_restores_persisted_values tests/test_emotion.py::test_load_state_clamps_values -v
```

Attendu : `FAILED`

- [ ] **Step 4.3: Modifier `EmotionEngine.__init__` et ajouter `load_state()`**

Dans `bot/core/emotion.py`, modifier `__init__` :

```python
def __init__(self, config: "Config", db=None):
    self._config = config
    self._state: dict[str, float] = {e: 0.0 for e in EMOTIONS}
    self._last_decay: float = time.time()
    self._decay_task: asyncio.Task | None = None
    self._openai = None
    self._learned_words: dict[str, list[tuple[str, float]]] = {e: [] for e in EMOTIONS}
    self._learned_lock = asyncio.Lock()
    # Persistence
    self._db = db
    self._dirty: bool = False
    self._save_task: asyncio.Task | None = None
    self._ticks: int = 0
    self._load_learned_words()
```

Ajouter la méthode `load_state()` dans la section "State access" :

```python
async def load_state(self) -> None:
    """Charge l'état émotionnel depuis la DB. No-op si db est None."""
    if self._db is None:
        return
    try:
        loaded = await self._db.load_emotion_state()
        for emotion, value in loaded.items():
            if emotion in self._state:
                self._state[emotion] = max(0.0, min(1.0, value))
        logger.info("Emotion state loaded from DB: {s}", s=self._state)
    except Exception as exc:
        logger.warning("Failed to load emotion state: {e}", e=exc)
```

- [ ] **Step 4.4: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion.py -v
```

Attendu : tous les tests emotion passent

- [ ] **Step 4.5: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/emotion.py tests/test_emotion.py && git commit -m "feat: add db param, persistence attrs and load_state() to EmotionEngine"
```

---

### Task 5: Sauvegarde debouncée et snapshot horaire dans `_decay_loop()`

**Files:**
- Modify: `bot/core/emotion.py`
- Test: `tests/test_emotion.py`

- [ ] **Step 5.1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_emotion.py` :

```python
@pytest.mark.asyncio
async def test_apply_delta_marks_dirty_when_db_set(tmp_path):
    from bot.db.database import Database
    db = await Database.create(str(tmp_path / "test.db"))
    engine = EmotionEngine(make_config(), db=db)
    assert engine._dirty is False
    engine.apply_delta("joy", 0.5)
    assert engine._dirty is True
    await db.close()


def test_apply_delta_does_not_create_task_without_db():
    """Sans DB, apply_delta ne doit pas tenter asyncio.create_task."""
    engine = EmotionEngine(make_config())
    engine.apply_delta("joy", 0.5)  # should not raise
    assert engine._save_task is None


@pytest.mark.asyncio
async def test_delayed_save_persists_state(tmp_path):
    from bot.db.database import Database
    from unittest.mock import patch, AsyncMock as AM
    db = await Database.create(str(tmp_path / "test.db"))
    engine = EmotionEngine(make_config(), db=db)
    engine._state["joy"] = 0.6
    engine._dirty = True
    # Appeler _delayed_save directement en patchant asyncio.sleep pour ne pas attendre 5s
    with patch("bot.core.emotion.asyncio.sleep", AM(return_value=None)):
        await engine._delayed_save()
    assert engine._dirty is False  # doit être remis à False après sauvegarde réussie
    loaded = await db.load_emotion_state()
    assert abs(loaded["joy"] - 0.6) < 0.001
    await db.close()


@pytest.mark.asyncio
async def test_delayed_save_keeps_dirty_on_error(tmp_path):
    from bot.db.database import Database
    from unittest.mock import patch, AsyncMock as AM, MagicMock
    db = await Database.create(str(tmp_path / "test.db"))
    engine = EmotionEngine(make_config(), db=db)
    engine._dirty = True
    # Simuler une erreur de sauvegarde
    with patch("bot.core.emotion.asyncio.sleep", AM(return_value=None)):
        with patch.object(db, "save_emotion_state", AM(side_effect=Exception("DB error"))):
            await engine._delayed_save()
    assert engine._dirty is True  # doit rester True en cas d'erreur
    await db.close()


@pytest.mark.asyncio
async def test_snapshot_inserted_on_60th_tick(tmp_path):
    """Vérifie que _decay_loop() insère un snapshot à chaque 60e tick."""
    import asyncio as aio
    from bot.db.database import Database
    from unittest.mock import patch
    db = await Database.create(str(tmp_path / "test.db"))
    engine = EmotionEngine(make_config(), db=db)
    engine._state["curiosity"] = 0.4
    engine._ticks = 59  # prochain tick = 60 → snapshot attendu

    call_count = 0

    async def fake_sleep(_):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise aio.CancelledError()  # arrête la boucle après 1 itération

    with patch("bot.core.emotion.asyncio.sleep", fake_sleep):
        task = aio.create_task(engine._decay_loop())
        try:
            await task
        except aio.CancelledError:
            pass

    snapshots = await db.get_today_emotion_snapshots()
    assert len(snapshots) == 1  # le 60e tick a bien déclenché l'insert
    await db.close()
```

- [ ] **Step 5.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion.py::test_apply_delta_marks_dirty_when_db_set tests/test_emotion.py::test_apply_delta_does_not_create_task_without_db tests/test_emotion.py::test_delayed_save_persists_state tests/test_emotion.py::test_delayed_save_keeps_dirty_on_error tests/test_emotion.py::test_snapshot_inserted_on_60th_tick -v
```

Attendu : `FAILED`

- [ ] **Step 5.3: Implémenter la persistence debouncée**

Dans `bot/core/emotion.py`, modifier `apply_delta()` et `set_emotion()` pour marquer `_dirty` et appeler `_schedule_save()` :

```python
def apply_delta(self, emotion: str, delta: float) -> None:
    if emotion not in self._state:
        return
    self._state[emotion] = max(0.0, min(1.0, self._state[emotion] + delta))
    self._dirty = True
    self._schedule_save()

def set_emotion(self, emotion: str, value: float) -> None:
    if emotion in self._state:
        self._state[emotion] = max(0.0, min(1.0, value))
        self._dirty = True
        self._schedule_save()
```

Ajouter les méthodes `_schedule_save()` et `_delayed_save()` dans la section "State access" :

```python
def _schedule_save(self) -> None:
    """Debounce : annule la tâche en cours et en planifie une nouvelle dans 5s."""
    if self._db is None:
        return
    if self._save_task and not self._save_task.done():
        self._save_task.cancel()
    self._save_task = asyncio.create_task(self._delayed_save())

async def _delayed_save(self) -> None:
    await asyncio.sleep(5)
    if self._db and self._dirty:
        try:
            await self._db.save_emotion_state(self._state)
            self._dirty = False
        except Exception as exc:
            logger.warning("Failed to persist emotion state: {e}", e=exc)
            # _dirty reste True → retry au prochain apply_delta
```

Modifier `_decay_loop()` pour persister l'état après decay et insérer un snapshot toutes les heures :

```python
async def _decay_loop(self) -> None:
    while True:
        await asyncio.sleep(60)
        self._apply_decay()
        self._dirty = True
        self._schedule_save()
        logger.debug("Emotion decay applied: {state}", state=self._state)
        self._ticks += 1
        if self._ticks % 60 == 0 and self._db:
            try:
                await self._db.insert_emotion_snapshot(self._state)
            except Exception as exc:
                logger.warning("Failed to insert emotion snapshot: {e}", e=exc)
```

- [ ] **Step 5.4: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_emotion.py -v
```

Attendu : tous les tests emotion passent

- [ ] **Step 5.5: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/emotion.py tests/test_emotion.py && git commit -m "feat: debounced persistence and hourly snapshot in EmotionEngine"
```

---

## Chunk 3: Mémoire taguée émotionnellement

### Task 6: Paramètre `emotion_context` sur `memory.add()`

**Files:**
- Modify: `bot/core/memory.py`
- Test: `tests/test_prompts.py` (ou nouveau fichier `tests/test_memory_tag.py`)

- [ ] **Step 6.1: Écrire le test qui échoue**

Créer `tests/test_memory_tag.py` :

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_memory_config():
    config = MagicMock()
    config.bot.context_window_size = 20
    config.bot.prelude_window_size = 15
    config.bot.context_token_threshold = 3000
    return config


@pytest.mark.asyncio
async def test_memory_add_prefixes_emotion_tag():
    """Quand emotion_context est fourni, le contenu stocké est préfixé."""
    from bot.core.memory import MemoryService
    config = make_memory_config()
    memory = MemoryService(config)

    stored_content = []

    async def fake_add(content, user_id):
        stored_content.append(content)

    memory._init_mem0()
    memory._mem0 = MagicMock()
    memory._mem0.add = MagicMock(side_effect=lambda content, user_id: stored_content.append(content))

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        await memory.add("discord", "user1", "bonjour !", emotion_context="Wally: joy")

    assert len(stored_content) == 1
    assert stored_content[0].startswith("[Wally: joy]")
    assert "bonjour !" in stored_content[0]


@pytest.mark.asyncio
async def test_memory_add_no_tag_when_empty_context():
    """Quand emotion_context est vide, le contenu n'est pas modifié."""
    from bot.core.memory import MemoryService
    config = make_memory_config()
    memory = MemoryService(config)

    stored_content = []
    memory._init_mem0()
    memory._mem0 = MagicMock()
    memory._mem0.add = MagicMock(side_effect=lambda content, user_id: stored_content.append(content))

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        await memory.add("discord", "user1", "bonjour !", emotion_context="")

    assert len(stored_content) == 1
    assert stored_content[0] == "bonjour !"
```

- [ ] **Step 6.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_tag.py -v
```

Attendu : `FAILED` — `TypeError: add() got an unexpected keyword argument 'emotion_context'`

- [ ] **Step 6.3: Modifier `memory.add()`**

Dans `bot/core/memory.py`, modifier la signature de `add()` :

```python
async def add(self, platform: str, user_id: str, content: str,
              emotion_context: str = "") -> None:
    self._init_mem0()
    if self._mem0 is None:
        return
    try:
        uid = self._user_id(platform, user_id)
        full_content = f"[{emotion_context}] {content}" if emotion_context else content
        await asyncio.to_thread(self._mem0.add, full_content, user_id=uid)
        self._fire(self._maybe_consolidate(platform, user_id))
    except Exception as exc:
        logger.warning("mem0 add failed: {e}", e=exc)
```

- [ ] **Step 6.4: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_tag.py -v
```

Attendu : `2 passed`

- [ ] **Step 6.5: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/memory.py tests/test_memory_tag.py && git commit -m "feat: add emotion_context param to memory.add()"
```

---

### Task 7: Tag émotionnel dans les handlers Discord et Twitch

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `bot/twitch/handlers.py`
- Test: `tests/test_discord_handlers.py`, `tests/test_memory_tag.py`

- [ ] **Step 7.1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_memory_tag.py` :

```python
@pytest.mark.asyncio
async def test_discord_handler_passes_emotion_tag_to_memory(tmp_path):
    """Le handler Discord passe le tag émotionnel à memory.add()."""
    from unittest.mock import AsyncMock, MagicMock, patch, call
    import discord

    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.discord.allowed_channels = []
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.8, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.0}
    )
    bot.db.is_muted = AsyncMock(return_value=False)
    bot.db.is_welcomed = AsyncMock(return_value=True)
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.update_trust_score = AsyncMock()
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.openai.complete = AsyncMock(return_value="Réponse de Wally")
    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.memory.append_message = MagicMock()
    bot.memory.add = AsyncMock()
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.persona.build_prompt_block = MagicMock(return_value="")
    bot.persona.emotion_directives = {}
    bot.emotion.process_message = AsyncMock()

    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.author.id = 123
    message.author.display_name = "TestUser"
    message.content = "wally bonjour"
    message.channel.id = 999
    message.channel.typing = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
    )
    message.guild.id = 456
    message.guild.name = "TestServer"
    message.channel.name = "general"
    message.channel.__class__ = discord.TextChannel
    message.mentions = []
    message.add_reaction = AsyncMock()
    message.remove_reaction = AsyncMock()
    message.reply = AsyncMock()
    message.channel.send = AsyncMock()
    message.id = 1

    from bot.discord.handlers import handle_message
    await handle_message(bot, message)

    # Vérifier que memory.add a été appelé avec un emotion_context non vide
    assert bot.memory.add.called
    call_kwargs = bot.memory.add.call_args
    emotion_context = call_kwargs.kwargs.get("emotion_context", "")
    assert "joy" in emotion_context  # joy=0.8 ≥ 0.4 → dans le tag
```

- [ ] **Step 7.2: Vérifier que le test échoue**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_tag.py::test_discord_handler_passes_emotion_tag_to_memory -v
```

Attendu : `FAILED`

- [ ] **Step 7.3: Modifier `bot/discord/handlers.py`**

Ajouter l'import en tête du fichier :

```python
from bot.core.emotion import build_emotion_tag
```

Dans la fonction `_respond()`, remplacer les deux lignes `_fire()` existantes à la fin (avant le `except`) :

```python
tag = build_emotion_tag(bot.emotion.get_state())
_fire(bot.memory.add(platform, user_id, exchange, emotion_context=tag))
_fire(_post_process(bot, message.content, platform, user_id, guild_id, trust, context_messages))
```

- [ ] **Step 7.4: Modifier `bot/twitch/handlers.py`**

Ajouter l'import :

```python
from bot.core.emotion import build_emotion_tag
```

Dans `handle_message()`, remplacer les deux `_fire()` existants (lignes 87-88) :

```python
tag = build_emotion_tag(bot.emotion.get_state())
_fire(bot.memory.add(platform, user_id, exchange, emotion_context=tag))
_fire(_post_process(bot, content, platform, user_id, trust, context_msgs))
```

- [ ] **Step 7.5: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_memory_tag.py tests/test_discord_handlers.py -v
```

Attendu : tous passent

- [ ] **Step 7.6: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/discord/handlers.py bot/twitch/handlers.py tests/test_memory_tag.py && git commit -m "feat: pass emotion tag to memory.add() in Discord and Twitch handlers"
```

---

## Chunk 4: Journal avec arc émotionnel

### Task 8: Fonction `_build_emotion_arc()` dans `journal.py`

**Files:**
- Modify: `bot/core/journal.py`
- Test: `tests/test_journal.py`

- [ ] **Step 8.1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_journal.py` :

```python
# ── Arc émotionnel ────────────────────────────────────────────────────────────

def test_build_emotion_arc_returns_empty_with_less_than_2_snapshots():
    from bot.core.journal import _build_emotion_arc
    assert _build_emotion_arc([]) == ""
    assert _build_emotion_arc([{"snapshot_at": 0, "anger": 0.5, "joy": 0.0,
                                "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}]) == ""


def test_build_emotion_arc_formats_dominant_emotions():
    from bot.core.journal import _build_emotion_arc
    import time
    now = time.time()
    snapshots = [
        {"snapshot_at": now - 3600, "anger": 0.0, "joy": 0.75, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},
        {"snapshot_at": now, "anger": 0.0, "joy": 0.55, "sadness": 0.0,
         "curiosity": 0.35, "boredom": 0.0},
    ]
    arc = _build_emotion_arc(snapshots)
    assert "Arc émotionnel" in arc
    assert "pic de joy" in arc       # 0.75 → 75% ≥ 70% → "pic de"
    assert "joy montante" in arc     # 0.55 → 55% ≥ 50% → "montante"
    assert "curiosity légère" in arc # 0.35 → 35% ≥ 30% et < 50% → "légère"
    assert arc.count("\n") >= 1


def test_build_emotion_arc_omits_emotions_below_30_percent():
    from bot.core.journal import _build_emotion_arc
    import time
    now = time.time()
    snapshots = [
        {"snapshot_at": now - 3600, "anger": 0.1, "joy": 0.2, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},
        {"snapshot_at": now, "anger": 0.1, "joy": 0.2, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},
    ]
    arc = _build_emotion_arc(snapshots)
    # Tout < 30% → chaque ligne affiche "neutre"
    assert "neutre" in arc
    assert "anger" not in arc


def test_build_emotion_arc_labels():
    """Vérifie les 3 paliers de labels."""
    from bot.core.journal import _build_emotion_arc
    import time
    now = time.time()
    snapshots = [
        {"snapshot_at": now - 7200, "anger": 0.35, "joy": 0.0, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},  # 35% → légère
        {"snapshot_at": now - 3600, "anger": 0.0, "joy": 0.6, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},  # 60% → montante
        {"snapshot_at": now, "anger": 0.0, "joy": 0.0, "sadness": 0.8,
         "curiosity": 0.0, "boredom": 0.0},  # 80% → pic de
    ]
    arc = _build_emotion_arc(snapshots)
    assert "légère" in arc
    assert "montante" in arc
    assert "pic de" in arc
```

- [ ] **Step 8.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_build_emotion_arc_returns_empty_with_less_than_2_snapshots tests/test_journal.py::test_build_emotion_arc_formats_dominant_emotions tests/test_journal.py::test_build_emotion_arc_omits_emotions_below_30_percent tests/test_journal.py::test_build_emotion_arc_labels -v
```

Attendu : `FAILED` — `ImportError: cannot import name '_build_emotion_arc'`

- [ ] **Step 8.3: Implémenter `_build_emotion_arc()` dans `journal.py`**

Dans `bot/core/journal.py`, ajouter les imports nécessaires au début :

```python
from datetime import date, datetime  # ajouter datetime à l'import existant
from zoneinfo import ZoneInfo
```

Ajouter après la constante `_DISCORD_LIMIT` (avant la classe `DailyJournal`) :

```python
_TZ_JOURNAL = ZoneInfo("Europe/Paris")


def _build_emotion_arc(snapshots: list[dict]) -> str:
    """Construit l'arc émotionnel de la journée depuis les snapshots horaires.

    Retourne "" si moins de 2 snapshots (pas assez de données pour une narrative).
    """
    if len(snapshots) < 2:
        return ""
    lines = []
    for snap in snapshots:
        ts = datetime.fromtimestamp(snap["snapshot_at"], tz=_TZ_JOURNAL)
        parts = []
        for emotion in ["anger", "joy", "sadness", "curiosity", "boredom"]:
            pct = int(snap[emotion] * 100)
            if pct < 30:
                continue
            if pct >= 70:
                label = f"pic de {emotion} ({pct}%)"
            elif pct >= 50:
                label = f"{emotion} montante ({pct}%)"
            else:
                label = f"{emotion} légère ({pct}%)"
            parts.append(label)
        if parts:
            lines.append(f"{ts.strftime('%Hh%M')} — {', '.join(parts)}")
        else:
            lines.append(f"{ts.strftime('%Hh%M')} — neutre")
    return "Arc émotionnel de la journée :\n" + "\n".join(lines)
```

- [ ] **Step 8.4: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_build_emotion_arc_returns_empty_with_less_than_2_snapshots tests/test_journal.py::test_build_emotion_arc_formats_dominant_emotions tests/test_journal.py::test_build_emotion_arc_omits_emotions_below_30_percent tests/test_journal.py::test_build_emotion_arc_labels -v
```

Attendu : `4 passed`

- [ ] **Step 8.5: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/journal.py tests/test_journal.py && git commit -m "feat: add _build_emotion_arc() to journal.py"
```

---

### Task 9: `DailyJournal` reçoit `db`, arc injecté, `_JOURNAL_USER_TEMPLATE` remplacé

**Files:**
- Modify: `bot/core/journal.py`
- Test: `tests/test_journal.py`

- [ ] **Step 9.1: Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_journal.py` :

```python
@pytest.mark.asyncio
async def test_journal_backward_compat_no_db():
    """DailyJournal sans db continue de fonctionner (backward compat)."""
    config, openai, emotion, memory = make_deps()
    journal = DailyJournal(config, openai, emotion, memory)  # pas de db
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))
    await journal.generate_and_send()
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_journal_emotions_text_uses_percentage():
    """Le prompt du journal contient les émotions en pourcentage."""
    config, openai, emotion, memory = make_deps()
    # joy=0.5 → 50%
    emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    captured_prompt = []

    async def capture(system, messages, purpose=""):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    openai.complete_secondary = capture
    journal = DailyJournal(config, openai, emotion, memory)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))
    await journal.generate_and_send()

    assert len(captured_prompt) >= 1
    # Le dernier appel est le journal final
    final_prompt = captured_prompt[-1]
    assert "50%" in final_prompt
    assert "0.5" not in final_prompt  # pas de float brut


@pytest.mark.asyncio
async def test_journal_arc_injected_when_db_has_snapshots(tmp_path):
    """Quand la DB a ≥2 snapshots, l'arc est présent dans le prompt journal."""
    from bot.db.database import Database
    import time
    db = await Database.create(str(tmp_path / "test.db"))

    # Insérer 2 snapshots directement
    now = time.time()
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.0, 0.8, 0.0, 0.0, 0.0)",
        (now - 3600,),
    )
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.0, 0.5, 0.0, 0.0, 0.0)",
        (now,),
    )

    config, openai, emotion, memory = make_deps()
    captured_prompt = []

    async def capture(system, messages, purpose=""):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    openai.complete_secondary = capture
    journal = DailyJournal(config, openai, emotion, memory, db=db)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))
    await journal.generate_and_send()

    final_prompt = captured_prompt[-1]
    assert "Arc émotionnel" in final_prompt
    await db.close()


@pytest.mark.asyncio
async def test_journal_arc_absent_when_less_than_2_snapshots(tmp_path):
    """Avec 0 ou 1 snapshot, l'arc est absent du prompt (pas de ligne vide parasite)."""
    from bot.db.database import Database
    db = await Database.create(str(tmp_path / "test.db"))

    config, openai, emotion, memory = make_deps()
    captured_prompt = []

    async def capture(system, messages, purpose=""):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    openai.complete_secondary = capture
    journal = DailyJournal(config, openai, emotion, memory, db=db)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))
    await journal.generate_and_send()

    final_prompt = captured_prompt[-1]
    assert "Arc émotionnel" not in final_prompt
    await db.close()
```

- [ ] **Step 9.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_journal_backward_compat_no_db tests/test_journal.py::test_journal_emotions_text_uses_percentage tests/test_journal.py::test_journal_arc_injected_when_db_has_snapshots tests/test_journal.py::test_journal_arc_absent_when_less_than_2_snapshots -v
```

Attendu : `FAILED`

- [ ] **Step 9.3: Modifier `DailyJournal`**

Dans `bot/core/journal.py` :

1. **Supprimer** la constante `_JOURNAL_USER_TEMPLATE` (lignes 22-26 actuelles).

2. **Modifier** `__init__` pour accepter `db=None` :

```python
def __init__(
    self,
    config: "Config",
    openai: "OpenAIClient",
    emotion: "EmotionEngine",
    memory: "MemoryService",
    db=None,
):
    self._config = config
    self._openai = openai
    self._emotion = emotion
    self._memory = memory
    self._db = db
    self._send_cb: Optional[Callable[..., Any]] = None
```

3. **Modifier** `generate_and_send()` — remplacer la section qui construit `user_msg` (actuellement via `_JOURNAL_USER_TEMPLATE.format(...)`) par :

```python
async def generate_and_send(self) -> None:
    channel_id = self._config.bot.journal_channel_id
    if not channel_id:
        logger.warning("No journal_channel_id configured, skipping journal")
        return

    logger.info("Generating daily journal...")

    all_messages = self._memory.get_all_contexts()
    if all_messages:
        context_text = await self._build_context_text(all_messages)
    else:
        context_text = "Pas grand chose de notable aujourd'hui."

    # Récupération de l'arc émotionnel
    try:
        snapshots = await self._db.get_today_emotion_snapshots() if self._db else []
    except Exception as exc:
        logger.warning("Failed to get emotion snapshots for journal: {e}", e=exc)
        snapshots = []

    arc = _build_emotion_arc(snapshots)
    arc_section = f"\n{arc}\n" if arc else ""

    emotions = self._emotion.get_state()
    emotions_text = ", ".join(f"{k}: {int(v * 100)}%" for k, v in emotions.items())

    user_msg = (
        f"Voici un résumé de la journée :\n\n{context_text}"
        f"{arc_section}"
        f"\nTon état émotionnel actuel : {emotions_text}\n\n"
        f"Écris ton journal intime pour aujourd'hui."
    )

    journal_text = await self._openai.complete_secondary(
        _JOURNAL_SYSTEM,
        [{"role": "user", "content": user_msg}],
        purpose="daily_journal",
    )

    formatted = f"**Journal de Wally — {self._today()}**\n\n{journal_text}"
    if self._send_cb:
        for chunk in _split_for_discord(formatted):
            await self._send_cb(chunk)
        logger.info("Daily journal sent to channel {ch}", ch=channel_id)
    else:
        logger.warning("No send callback set for journal — generated but not sent")
```

- [ ] **Step 9.4: Vérifier que TOUS les tests journal passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py -v
```

Attendu : tous passent (anciens + nouveaux)

- [ ] **Step 9.5: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/journal.py tests/test_journal.py && git commit -m "feat: DailyJournal receives db, injects emotional arc into journal prompt"
```

---

## Chunk 5: Affichage en pourcentage + câblage `main.py`

### Task 10: Affichage en % dans `mood.py` et `setup.py`

**Files:**
- Modify: `bot/discord/commands/mood.py`
- Modify: `bot/discord/commands/setup.py`
- Test: `tests/test_discord_commands.py`

- [ ] **Step 10.1: Écrire les tests qui échouent**

Lire `tests/test_discord_commands.py` pour comprendre les mocks existants, puis ajouter à la fin :

```python
@pytest.mark.asyncio
async def test_mood_command_displays_percentage():
    """La commande /mood affiche les émotions en % et non en float."""
    from bot.discord.commands.mood import MoodCog
    from unittest.mock import AsyncMock, MagicMock

    bot = MagicMock()
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.73, "sadness": 0.0,
                      "curiosity": 0.0, "boredom": 0.0}
    )

    cog = MoodCog(bot)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.mood.callback(cog, interaction)

    call_kwargs = interaction.response.send_message.call_args
    embed = call_kwargs.kwargs.get("embed") or call_kwargs.args[0] if call_kwargs.args else None
    assert embed is not None
    # Chercher "73%" dans les champs de l'embed
    field_values = [f.value for f in embed.fields]
    assert any("73%" in v for v in field_values)
    assert not any("0.73" in v for v in field_values)


@pytest.mark.asyncio
async def test_setup_mood_tab_displays_percentage():
    """L'onglet Humeur du /setup affiche les émotions en %."""
    from bot.discord.commands.setup import SetupTabSelect
    from unittest.mock import AsyncMock, MagicMock

    bot = MagicMock()
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.65, "sadness": 0.0,
                      "curiosity": 0.0, "boredom": 0.0}
    )
    bot.config.bot.trigger_names = ["wally"]

    select = SetupTabSelect(bot)
    select.values = ["mood"]
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await select.callback(interaction)

    call_args = interaction.response.send_message.call_args
    content = call_args.args[0] if call_args.args else call_args.kwargs.get("content", "")
    assert "65%" in content
    assert "0.65" not in content
```

- [ ] **Step 10.2: Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_commands.py::test_mood_command_displays_percentage tests/test_discord_commands.py::test_setup_mood_tab_displays_percentage -v
```

Attendu : `FAILED`

- [ ] **Step 10.3: Modifier `mood.py`**

Dans `bot/discord/commands/mood.py`, changer la ligne de construction du `value` de l'embed :

```python
# Avant :
value=f"{bar} `{value:.2f}`",
# Après :
value=f"{bar} `{int(value * 100)}%`",
```

- [ ] **Step 10.4: Modifier `setup.py` — 4 occurrences**

Dans `bot/discord/commands/setup.py` :

1. **`EditEmotionModal.on_submit`** — la ligne `f"{self.emotion} mis à {v:.2f}"` → `f"{self.emotion} mis à {int(v * 100)}%"`

2. **`EmotionMinusButton.callback`** — `f"{self.emotion}: {v:.2f}"` → `f"{self.emotion}: {int(v * 100)}%"`

3. **`EmotionPlusButton.callback`** — `f"{self.emotion}: {v:.2f}"` → `f"{self.emotion}: {int(v * 100)}%"`

4. **`SetupTabSelect.callback` (branche `tab == "mood"`)** — `f"**{e}** : {v:.2f}"` → `f"**{e}** : {int(v * 100)}%"`

- [ ] **Step 10.5: Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_commands.py -v
```

Attendu : tous passent

- [ ] **Step 10.6: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/discord/commands/mood.py bot/discord/commands/setup.py tests/test_discord_commands.py && git commit -m "feat: display emotion values as percentage in mood and setup commands"
```

---

### Task 11: Câblage `main.py` — injection `db` dans `EmotionEngine` et `DailyJournal`

**Files:**
- Modify: `bot/main.py`

> Pas de nouveau test unitaire — `main.py` est du code de câblage ; les tests d'intégration seraient trop lourds. Vérification par lancement du bot (Step 11.3).

- [ ] **Step 11.1: Modifier la séquence de démarrage dans `main.py`**

Remplacer le bloc existant des lignes 62-82 (de `db_path = ...` jusqu'à `logger.info("DailyJournal initialized")`) par :

```python
db_path = os.getenv("DB_PATH", "data/wally.db")
db = await Database.create(db_path)
logger.info("Database ready at {path}", path=db_path)
await db.cleanup_old_emotion_history()
logger.info("Old emotion history cleaned up")

# ── Core services ─────────────────────────────────────────────────────────────
emotion = EmotionEngine(config, db=db)          # db injecté
await emotion.load_state()                      # charge l'état persisté
emotion.start_decay_task()                      # APRÈS load_state
logger.info("EmotionEngine started with decay task")

memory = MemoryService(config)
openai_client = OpenAIClient(config, db)
memory.set_openai_client(openai_client)
emotion.set_openai_client(openai_client)
logger.info("MemoryService and OpenAIClient initialized")

prompts = PromptBuilder()
language = LanguageDetector(config.bot.language_default)
persona = PersonaService()
logger.info("PromptBuilder, LanguageDetector, and PersonaService initialized")

journal = DailyJournal(config, openai_client, emotion, memory, db=db)  # db injecté
logger.info("DailyJournal initialized")
```

- [ ] **Step 11.2: Vérifier que la syntaxe est correcte**

```bash
cd /opt/stacks/wally-ai && python -c "import bot.main"
```

Attendu : pas d'erreur

- [ ] **Step 11.3: Lancer la suite de tests complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short
```

Attendu : tous les tests passent (110+)

- [ ] **Step 11.4: Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/main.py && git commit -m "feat: wire db into EmotionEngine and DailyJournal in main.py"
```

---

## Vérification finale

- [ ] **Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v
```

Attendu : tous les tests passent.

- [ ] **Vérifier qu'aucun import ne manque**

```bash
cd /opt/stacks/wally-ai && python -c "
from bot.core.emotion import EmotionEngine, build_emotion_tag
from bot.core.memory import MemoryService
from bot.core.journal import DailyJournal, _build_emotion_arc
from bot.db.database import Database
print('Tous les imports OK')
"
```

Attendu : `Tous les imports OK`
