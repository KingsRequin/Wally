# User Model — Portrait dialectique nocturne — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une passe nocturne régénère un portrait en prose, évolutif et dialectique, par personne active du jour (à partir de ses faits actifs ET révolus + trust/love), injecté au system prompt quand Wally lui parle.

**Architecture:** Un nouveau `UserModeler` sélectionne les `user_id` dont des faits ont bougé aujourd'hui, rassemble pour chacun ses faits actifs + superseded + trust/love, et génère un portrait LLM stocké dans une table `user_profiles`. Job greffé sur le scheduler du `DailyJournal` (à côté du `MemoryConsolidator`). Le portrait est lu et injecté via un nouveau paramètre `person_context` de `build_system_prompt`, en plus de la recherche sémantique existante.

**Tech Stack:** Python asyncio, aiosqlite/SQLite, apscheduler (cron), DeepSeek `complete_structured`, loguru.

## Global Constraints

- Logging : **loguru uniquement** (`from loguru import logger`), jamais `print`/`import logging`.
- Tout I/O async ; aucun appel bloquant.
- Toute la passe est **non-fatale** : `try/except` log WARNING et continue (une personne qui échoue n'arrête pas les autres ; un échec LLM = portrait non mis à jour).
- LLM = `secondary_llm` via `complete_structured(system_prompt, messages, schema, schema_name=..., purpose=...)`.
- `db.get_trust_score(platform, user_id)` / `db.get_love_score(platform, user_id, decay_lambda)` attendent le **user_id BRUT** (sans préfixe). Les faits sont stockés en `user_id` **préfixé** (`"discord:123"`) → splitter `prefix:raw` avant d'appeler trust/love.
- Colonnes temps en **ISO UTC naïf** (`datetime.utcnow().isoformat()`), comparaison lexicographique.
- `session_analyses`/tables V2 vivent dans `schema_v2.py` ; tests V2 appellent `create_v2_tables(db_path)` après `Database.create()` (helper `_make_db`).
- Commentaires en français, style du code environnant.

---

### Task 1 : Table `user_profiles`

**Files:**
- Modify: `bot/db/schema_v2.py` (constante `_SCHEMA_SQL`)
- Test: `tests/test_user_profiles_schema.py` (créer)

**Interfaces:**
- Consumes: `create_v2_tables(db_path)` (existant).
- Produces: table `user_profiles(user_id PK, portrait, updated_at)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_user_profiles_schema.py
import pytest
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables


@pytest.mark.asyncio
async def test_user_profiles_table_exists(tmp_path):
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    rows = await db.fetch_all("PRAGMA table_info(user_profiles)")
    cols = {r["name"] for r in rows}
    assert {"user_id", "portrait", "updated_at"} <= cols
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_user_profiles_schema.py -q`
Expected: FAIL (table absente).

- [ ] **Step 3: Write minimal implementation**

Dans `bot/db/schema_v2.py`, ajouter à `_SCHEMA_SQL` (à la suite des autres `CREATE TABLE`) :
```sql
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id    TEXT PRIMARY KEY,
    portrait   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_user_profiles_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/db/schema_v2.py tests/test_user_profiles_schema.py
git commit -m "feat(memory): table user_profiles (portrait par personne)"
```

---

### Task 2 : Helpers DB (profils + sélection des faits)

**Files:**
- Modify: `bot/db/mixins/memory.py` (classe `MemoryMixin`)
- Test: `tests/test_user_profiles_db.py` (créer)

**Interfaces:**
- Consumes: `self.execute`, `self.fetch_all`, `self.fetch_one`.
- Produces :
  - `upsert_user_profile(user_id: str, portrait: str) -> None`
  - `get_user_profile(user_id: str) -> str | None`
  - `get_users_with_recent_facts(since_iso: str) -> list[str]`
  - `get_active_facts_for_user(user_id: str, limit: int = 50) -> list[dict]` → `[{"content": str, "category": str}]`
  - `get_superseded_facts_for_user(user_id: str, limit: int = 20) -> list[dict]` → `[{"content": str, "category": str}]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_user_profiles_db.py
import pytest
from datetime import datetime, timedelta
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables


async def _make_db(tmp_path):
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    return db


async def _add_fact(db, user_id, content, status="active", category="FAIT", when=None):
    ts = (when or datetime.utcnow()).isoformat()
    await db.execute(
        "INSERT INTO atomic_facts (user_id, content, category, importance, support_count, "
        "confidence, status, source, created_at, last_seen_at, decay_rate) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, content, category, 0.5, 1, 0.9, status, "test", ts, ts, 0.005),
    )


@pytest.mark.asyncio
async def test_profile_upsert_and_get(tmp_path):
    db = await _make_db(tmp_path)
    await db.upsert_user_profile("discord:1", "Portrait v1")
    assert await db.get_user_profile("discord:1") == "Portrait v1"
    await db.upsert_user_profile("discord:1", "Portrait v2")
    assert await db.get_user_profile("discord:1") == "Portrait v2"
    assert await db.get_user_profile("discord:999") is None
    await db.close()


@pytest.mark.asyncio
async def test_users_with_recent_facts(tmp_path):
    db = await _make_db(tmp_path)
    await _add_fact(db, "discord:1", "récent")
    await _add_fact(db, "discord:2", "vieux", when=datetime.utcnow() - timedelta(days=10))
    since = (datetime.utcnow() - timedelta(days=1)).isoformat()
    users = await db.get_users_with_recent_facts(since)
    assert "discord:1" in users
    assert "discord:2" not in users
    await db.close()


@pytest.mark.asyncio
async def test_active_and_superseded_split(tmp_path):
    db = await _make_db(tmp_path)
    await _add_fact(db, "discord:1", "aime la stratégie", status="active")
    await _add_fact(db, "discord:1", "détestait le solo", status="superseded")
    active = await db.get_active_facts_for_user("discord:1")
    superseded = await db.get_superseded_facts_for_user("discord:1")
    assert [f["content"] for f in active] == ["aime la stratégie"]
    assert [f["content"] for f in superseded] == ["détestait le solo"]
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_user_profiles_db.py -q`
Expected: FAIL (`AttributeError: upsert_user_profile`).

- [ ] **Step 3: Write minimal implementation**

Dans `bot/db/mixins/memory.py`, ajouter à `MemoryMixin` (importe `from datetime import datetime` en tête si absent) :
```python
    async def upsert_user_profile(self, user_id: str, portrait: str) -> None:
        """Écrit/remplace le portrait d'une personne (1 par user_id)."""
        await self.execute(
            "INSERT INTO user_profiles(user_id, portrait, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "portrait=excluded.portrait, updated_at=excluded.updated_at",
            (user_id, portrait, datetime.utcnow().isoformat()),
        )

    async def get_user_profile(self, user_id: str) -> str | None:
        row = await self.fetch_one(
            "SELECT portrait FROM user_profiles WHERE user_id=?", (user_id,)
        )
        return row["portrait"] if row else None

    async def get_users_with_recent_facts(self, since_iso: str) -> list[str]:
        """user_id distincts dont un fait actif a bougé depuis since_iso."""
        rows = await self.fetch_all(
            "SELECT DISTINCT user_id FROM atomic_facts "
            "WHERE status='active' AND (last_seen_at >= ? OR created_at >= ?)",
            (since_iso, since_iso),
        )
        return [r["user_id"] for r in rows]

    async def get_active_facts_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT content, category FROM atomic_facts "
            "WHERE user_id=? AND status='active' AND confidence >= 0.3 "
            "ORDER BY importance DESC, last_seen_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [{"content": r["content"], "category": r["category"]} for r in rows]

    async def get_superseded_facts_for_user(self, user_id: str, limit: int = 20) -> list[dict]:
        rows = await self.fetch_all(
            "SELECT content, category FROM atomic_facts "
            "WHERE user_id=? AND status='superseded' "
            "ORDER BY last_seen_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [{"content": r["content"], "category": r["category"]} for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_user_profiles_db.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -q`
Expected: tous verts.

- [ ] **Step 6: Commit**

```bash
git add bot/db/mixins/memory.py tests/test_user_profiles_db.py
git commit -m "feat(memory): helpers DB portrait + sélection faits actifs/révolus"
```

---

### Task 3 : `UserModeler` + prompt

**Files:**
- Create: `bot/intelligence/memory/user_modeler.py`
- Create: `bot/persona/prompts/user_portrait.md`
- Test: `tests/test_user_modeler.py` (créer)

**Interfaces:**
- Consumes (depuis `db`) : `get_users_with_recent_facts`, `get_active_facts_for_user`, `get_superseded_facts_for_user`, `get_trust_score(platform, raw_id)`, `get_love_score(platform, raw_id, decay_lambda)`, `upsert_user_profile` ; `llm_secondary.complete_structured`.
- Produces: `UserModeler(db, llm_secondary)` avec `async refresh_profiles(since: str | None = None) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_user_modeler.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.memory.user_modeler import UserModeler


def _make(users, active_by_user):
    db = MagicMock()
    db.get_users_with_recent_facts = AsyncMock(return_value=users)
    db.get_active_facts_for_user = AsyncMock(side_effect=lambda uid, **k: active_by_user.get(uid, []))
    db.get_superseded_facts_for_user = AsyncMock(return_value=[{"content": "détestait le solo", "category": "PREF"}])
    db.get_trust_score = AsyncMock(return_value=0.5)
    db.get_love_score = AsyncMock(return_value=0.2)
    db.upsert_user_profile = AsyncMock()
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"portrait": "portrait test"})
    return UserModeler(db, llm), db, llm


@pytest.mark.asyncio
async def test_no_users_is_noop():
    c, db, llm = _make([], {})
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    db.upsert_user_profile.assert_not_awaited()
    llm.complete_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_without_active_facts_skipped():
    c, db, llm = _make(["discord:1"], {"discord:1": []})
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    db.upsert_user_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_portrait_generated_with_dialectic_material():
    active = {"discord:1": [{"content": "aime la stratégie", "category": "PREF"}]}
    c, db, llm = _make(["discord:1"], active)
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    # trust/love appelés avec l'id BRUT (sans préfixe)
    db.get_trust_score.assert_awaited_with("discord", "1")
    # la matière dialectique (faits révolus) est passée au LLM
    payload = llm.complete_structured.await_args.args[1][0]["content"]
    assert "aime la stratégie" in payload
    assert "détestait le solo" in payload
    db.upsert_user_profile.assert_awaited_once_with("discord:1", "portrait test")


@pytest.mark.asyncio
async def test_users_isolated_on_error():
    active = {"discord:1": [{"content": "f1", "category": "FAIT"}],
              "discord:2": [{"content": "f2", "category": "FAIT"}]}
    c, db, llm = _make(["discord:1", "discord:2"], active)
    async def boom(prompt, messages, schema, **k):
        if "f1" in messages[0]["content"]:
            raise RuntimeError("LLM down for user 1")
        return {"portrait": "ok"}
    llm.complete_structured.side_effect = boom
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    upserted = [call.args[0] for call in db.upsert_user_profile.await_args_list]
    assert "discord:2" in upserted and "discord:1" not in upserted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_user_modeler.py -q`
Expected: FAIL (`ModuleNotFoundError: bot.intelligence.memory.user_modeler`).

- [ ] **Step 3: Write minimal implementation**

`bot/persona/prompts/user_portrait.md` :
```markdown
Tu es la mémoire de {{BOT_NAME}}. On te donne ce que tu sais d'une personne : ses traits actuels, ce qu'elle disait avant (révolu), et ta relation avec elle.

Écris un portrait court (3 à 5 phrases, en français), du point de vue de {{BOT_NAME}} : qui elle est, ce qui compte pour elle, son tempérament. Si ses traits ont évolué ou se contredisent, dis-le en toutes lettres (« passionné de stratégie, même s'il a viré vers le solo récemment »). Écris comme une impression qu'on se fait de quelqu'un, pas une fiche. Pas de liste.
```

`bot/intelligence/memory/user_modeler.py` :
```python
# bot/intelligence/memory/user_modeler.py
"""Modélisation des personnes : portrait en prose, évolutif et dialectique.

Chaque nuit, pour les personnes dont des faits ont bougé dans la journée,
régénère un portrait à partir de leurs faits actifs ET révolus (superseded)
+ trust/love, stocké dans user_profiles et réinjecté au prompt.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger

from bot.intelligence.prompts import load_prompt

if TYPE_CHECKING:
    pass

_PORTRAIT_PROMPT = load_prompt("user_portrait")

_PORTRAIT_SCHEMA = {
    "type": "object",
    "properties": {
        "portrait": {
            "type": "string",
            "description": "Portrait 3-5 phrases de la personne, intégrant son évolution.",
        }
    },
    "required": ["portrait"],
}


class UserModeler:
    def __init__(self, db, llm_secondary):
        self._db = db
        self._llm = llm_secondary

    async def refresh_profiles(self, since: str | None = None) -> None:
        """Régénère le portrait des personnes actives depuis `since` (ISO UTC)."""
        if self._db is None:
            return
        if since is None:
            since = (datetime.utcnow() - timedelta(days=1)).isoformat()
        try:
            user_ids = await self._db.get_users_with_recent_facts(since)
        except Exception as e:  # noqa: BLE001 — non-fatal
            logger.warning("UserModeler : sélection des personnes échouée : {e}", e=e)
            return
        if not user_ids:
            logger.debug("UserModeler : aucune personne active à modéliser")
            return
        done = 0
        for user_id in user_ids:
            try:
                if await self._refresh_one(user_id):
                    done += 1
            except Exception as e:  # noqa: BLE001 — une personne ne casse pas les autres
                logger.warning("UserModeler : portrait de {u} échoué : {e}", u=user_id, e=e)
        logger.info("UserModeler : {n} portrait(s) régénéré(s)", n=done)

    async def _refresh_one(self, user_id: str) -> bool:
        active = await self._db.get_active_facts_for_user(user_id)
        if not active:
            return False
        superseded = await self._db.get_superseded_facts_for_user(user_id)
        platform, raw_id = user_id.split(":", 1) if ":" in user_id else ("discord", user_id)
        trust = await self._db.get_trust_score(platform, raw_id)
        love = await self._db.get_love_score(platform, raw_id)
        portrait = await self._build_portrait(active, superseded, trust, love)
        if not portrait:
            return False
        await self._db.upsert_user_profile(user_id, portrait)
        return True

    async def _build_portrait(self, active, superseded, trust, love) -> str | None:
        present = "\n".join(f"- {f['content']}" for f in active)
        past = "\n".join(f"- {f['content']}" for f in superseded) or "(rien)"
        payload = (
            f"Traits actuels :\n{present}\n\n"
            f"Ce qu'elle disait avant (révolu) :\n{past}\n\n"
            f"Confiance : {trust:.2f}/1.0 | Affection : {love:.2f}/1.0"
        )
        try:
            result = await self._llm.complete_structured(
                _PORTRAIT_PROMPT,
                [{"role": "user", "content": payload}],
                _PORTRAIT_SCHEMA,
                schema_name="user_portrait",
                purpose="user_model",
            )
        except Exception as e:  # noqa: BLE001 — non-fatal
            logger.warning("UserModeler : génération LLM échouée : {e}", e=e)
            return None
        return (result.get("portrait") or "").strip() or None
```

Note : `get_love_score` accepte un `decay_lambda` optionnel (défaut 0.1) — on s'appuie sur le défaut ici.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_user_modeler.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/memory/user_modeler.py bot/persona/prompts/user_portrait.md tests/test_user_modeler.py
git commit -m "feat(memory): UserModeler — portrait dialectique par personne"
```

---

### Task 4 : Planifier sur le scheduler du journal

**Files:**
- Modify: `bot/intelligence/journal.py` (`__init__`, `set_user_modeler`, `start`)
- Test: `tests/test_journal_user_model.py` (créer)

**Interfaces:**
- Consumes: `UserModeler.refresh_profiles` (Task 3).
- Produces: `DailyJournal.set_user_modeler(user_modeler) -> None` ; job `id="user_model_refresh"` dans `start()` quand un user_modeler est présent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_journal_user_model.py
from unittest.mock import MagicMock
from bot.intelligence.journal import DailyJournal


def _journal():
    config = MagicMock()
    config.bot.journal_time = "21:00"
    return DailyJournal(config, MagicMock(), MagicMock(), MagicMock(), MagicMock(), db=MagicMock())


def test_set_user_modeler_then_start_registers_job():
    j = _journal()
    j.set_user_modeler(MagicMock())
    sched = MagicMock()
    j.start(scheduler=sched)
    ids = {c.kwargs.get("id") for c in sched.add_job.call_args_list}
    assert "user_model_refresh" in ids


def test_start_without_user_modeler_has_no_job():
    j = _journal()
    sched = MagicMock()
    j.start(scheduler=sched)
    ids = {c.kwargs.get("id") for c in sched.add_job.call_args_list}
    assert "user_model_refresh" not in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_journal_user_model.py -q`
Expected: FAIL (`AttributeError: set_user_modeler`).

- [ ] **Step 3: Write minimal implementation**

Dans `bot/intelligence/journal.py` :
1. Dans `__init__`, après `self._consolidator = None`, ajouter :
```python
        self._user_modeler = None
```
2. Près de `set_consolidator`, ajouter :
```python
    def set_user_modeler(self, user_modeler) -> None:
        """Injecte le UserModeler lancé par le cron nocturne."""
        self._user_modeler = user_modeler
```
3. Dans `start`, juste après le bloc `if self._consolidator is not None:` (et avant `if owns_scheduler: self._scheduler.start()`), ajouter :
```python
        if self._user_modeler is not None:
            self._scheduler.add_job(
                self._user_modeler.refresh_profiles,
                "cron",
                hour=hour,
                minute=minute,
                id="user_model_refresh",
                replace_existing=True,
            )
            logger.info("Modélisation des personnes planifiée à {t}", t=time_str)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_journal_user_model.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/journal.py tests/test_journal_user_model.py
git commit -m "feat(memory): planifie la modélisation des personnes (scheduler journal)"
```

---

### Task 5 : Câblage bootstrap

**Files:**
- Modify: `bot/bootstrap.py` (après la construction du `MemoryConsolidator`, ~ligne 191)

**Interfaces:**
- Consumes: `UserModeler(db, secondary_llm)` (Task 3) ; `journal.set_user_modeler` (Task 4).

- [ ] **Step 1: Write the implementation** (intégration — vérifiée par la suite + démarrage)

Dans `bot/bootstrap.py`, juste après `logger.info("MemoryConsolidator initialized")` :
```python
    # ── Modélisation des personnes (user model) ───────────────────────────────
    from bot.intelligence.memory.user_modeler import UserModeler
    user_modeler = UserModeler(db, secondary_llm)
    journal.set_user_modeler(user_modeler)
    logger.info("UserModeler initialized")
```

- [ ] **Step 2: Run the full suite**

Run: `python3 -m pytest -q`
Expected: tous verts.

- [ ] **Step 3: Smoke import**

Run: `python3 -c "import bot.bootstrap; import bot.intelligence.memory.user_modeler; print('imports OK')"`
Expected: `imports OK`.

- [ ] **Step 4: Commit**

```bash
git add bot/bootstrap.py
git commit -m "feat(memory): câble UserModeler dans le bootstrap"
```

---

### Task 6 : Injection du portrait au prompt (Discord + Twitch)

**Files:**
- Modify: `bot/intelligence/prompts.py` (`build_system_prompt` : nouveau param + assemblage)
- Modify: `bot/discord/handlers.py` (récupère le portrait + passe le param)
- Modify: `bot/twitch/handlers.py` (idem)
- Test: `tests/test_person_context_prompt.py` (créer)

**Interfaces:**
- Consumes: `db.get_user_profile(user_id)` (Task 2).
- Produces: param `person_context: str = ""` sur `build_system_prompt`, rendu en bloc `--- Qui est cette personne ---`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_person_context_prompt.py
from bot.intelligence.prompts import PromptBuilder


def _builder():
    # PromptBuilder() sans argument (cf. tests/test_weekday_awareness.py) ; build_system_prompt prend tout en kwargs.
    return PromptBuilder()


def test_person_context_rendered_when_present():
    out = _builder().build_system_prompt(
        emotion_state={}, person_context="Azrael, stratège invétéré."
    )
    assert "--- Qui est cette personne ---" in out
    assert "Azrael, stratège invétéré." in out


def test_person_context_absent_when_empty():
    out = _builder().build_system_prompt(emotion_state={})
    assert "Qui est cette personne" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_person_context_prompt.py -q`
Expected: FAIL (`TypeError: unexpected keyword argument 'person_context'`).

- [ ] **Step 3: Write minimal implementation**

Dans `bot/intelligence/prompts.py`, méthode `build_system_prompt` :
1. Ajouter le paramètre (à côté de `relationship_context: str = ""`) :
```python
        person_context: str = "",
```
2. Dans l'assemblage des `dynamic_parts`, juste avant le bloc `--- Relation ---`, ajouter :
```python
        # Portrait de la personne (user model)
        if person_context:
            dynamic_parts.append(f"\n--- Qui est cette personne ---\n{person_context}")
```

Dans `bot/discord/handlers.py`, là où `relationship_context` est préparé puis passé à `build_system_prompt` (~lignes 1281-1317) :
```python
    # Portrait de la personne (user model) — non-fatal
    person_context = ""
    try:
        person_context = await bot.db.get_user_profile(f"{platform}:{user_id}") or ""
    except Exception:
        pass
```
puis ajouter `person_context=person_context,` dans l'appel `bot.prompts.build_system_prompt(...)`.

Dans `bot/twitch/handlers.py`, au même endroit que le `relationship_context` Twitch, ajouter le même bloc (`f"{platform}:{user_id}"` avec `platform="twitch"`) et passer `person_context=person_context` à `build_system_prompt`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_person_context_prompt.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -q`
Expected: tous verts (handlers Discord + Twitch OK).

- [ ] **Step 6: Commit**

```bash
git add bot/intelligence/prompts.py bot/discord/handlers.py bot/twitch/handlers.py tests/test_person_context_prompt.py
git commit -m "feat(memory): injecte le portrait au prompt (bloc Qui est cette personne)"
```

---

## Self-Review

**Spec coverage :**
- Table `user_profiles` → Task 1. ✓
- Helpers profils + sélection émergente (`get_users_with_recent_facts`) + faits actifs/révolus → Task 2. ✓
- `UserModeler` nocturne, dialectique (active + superseded + trust/love), non-fatal → Task 3. ✓
- Prompt `user_portrait.md` → Task 3. ✓
- Scheduling job `user_model_refresh` → Task 4. ✓
- Bootstrap wiring → Task 5. ✓
- Injection « Qui est cette personne », s'ajoute (recherche sémantique inchangée), Discord + Twitch → Task 6. ✓
- Non-fatal partout → try/except dans Tasks 3 & 6. ✓

**Note de couverture (spec §3 dialectique) :** on lit les faits `superseded` via une requête dédiée (`get_superseded_facts_for_user`) plutôt que via `fact_relations` (qui relie ancien→nouveau). Le contenu des faits révolus suffit au LLM pour percevoir l'évolution ; `fact_relations` reste non lu (acceptable — le spec disait « au minimum, le contenu des superseded suffit »).

**Placeholder scan :** aucun. `PromptBuilder()` se construit sans argument (vérifié : `tests/test_weekday_awareness.py`).

**Type consistency :** `upsert_user_profile(user_id, portrait)` / `get_user_profile(user_id)` / `get_users_with_recent_facts(since_iso)` / `get_active_facts_for_user` / `get_superseded_facts_for_user` cohérents entre Task 2 (def), Task 3 (appels) et Task 6 (`get_user_profile`). `refresh_profiles(since=None)` cohérent Task 3/4. `person_context` cohérent Task 6 (def prompts + appels handlers). Le split `prefix:raw` pour trust/love est explicite dans Task 3 et testé.
