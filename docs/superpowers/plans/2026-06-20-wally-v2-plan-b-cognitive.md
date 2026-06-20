# Wally V2 — Plan B : Cognitive Core

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implémenter la boucle cognitive (Theatre of Mind) — le moteur qui fait "penser" Wally de façon continue, même en l'absence d'interactions.

**Architecture:** Pipeline asyncio en 4 étapes : `AttentionAgent` (assemblage contexte) → `InnerMonologue` (DeepSeek Pro thinking:max) → `MetaAgent` (parse décisions) → `ActionDispatcher` (exécution). `PersonaManager` gère l'auto-modification des fichiers persona avec garde-fous. `EvolutionLog` trace chaque modification. `CognitiveLoop` orchestre le tout avec tick adaptatif (30s/2min/5min). Câblé dans `bot/discord/bot.py` via `setup_hook` + `on_ready`.

**Tech Stack:** Python 3.11+, asyncio, `aiosqlite`, `loguru`. DeepSeek V4 Pro pour le monologue (thinking:max), Flash pour le MetaAgent. Dépend de Plan A : `SQLiteFactStore`, `DeepSeekLLMClient`, `FactCategory`.

## Global Constraints

- DeepSeek primary (monologue) : `deepseek-v4-pro`, thinking activé via `extra_body={"thinking": {"type": "enabled"}, "reasoning_effort": "max"}`
- DeepSeek secondary (meta_agent) : `deepseek-v4-flash`, thinking toujours disabled
- Owner ACL Discord : `"610550333042589752"` — Twitch : `"KingsRequin"` (vérifié dans ActionDispatcher pour `code_fix`)
- Loguru uniquement — jamais `print()` ni `import logging`
- Toutes les heures sont UTC dans la DB, stockées en ISO 8601
- `EvolutionLog` : JSONL append-only, jamais écrasé, jamais tronqué
- Garde-fous PersonaManager : SOUL max 20%/jour, 1 évolution/24h ; EMOTIONS 15%/24h ; WEEKDAYS 1 jour/24h ; COMPOSITES 1 composite/24h
- `search_by_category` à ajouter à `SQLiteFactStore` dans Task 9 (méthode manquante)
- Spec complète : `docs/superpowers/specs/2026-06-20-wally-v2-vivant-design.md`
- Plan A complète (HEAD: 1795b68) — ne jamais modifier `wally_v2/core/memory/facts.py` sans relire le fichier d'abord

---

## File Map

```
wally_v2/
└── core/
    ├── evolution_log.py         CREATE — EvolutionEntry, EvolutionLog
    ├── persona_manager.py       CREATE — PersonaManager (guardrails + LLM edit)
    ├── attention_agent.py       CREATE — AttentionAgent (assemble context)
    ├── inner_monologue.py       CREATE — InnerMonologue (DeepSeek Pro thinking:max)
    ├── meta_agent.py            CREATE — MetaAgent + parse_decisions()
    ├── action_dispatcher.py     CREATE — ActionDispatcher (routes MetaDecision)
    ├── cognitive_loop.py        CREATE — CognitiveLoop (orchestrateur asyncio)
    └── memory/
        └── facts.py             MODIFY — ajouter search_by_category() à SQLiteFactStore

wally_v2/persona/prompts/
├── inner_monologue_system.md    CREATE — prompt système monologue intérieur
└── meta_agent_system.md         CREATE — prompt système MetaAgent

bot/discord/
├── bot.py                       MODIFY — cognitive_loop init dans setup_hook + start dans on_ready + stop dans close()
└── handlers.py                  MODIFY — notify_activity() après gate, avant prompt build

tests/v2/core/
├── test_evolution_log.py        CREATE — 4 tests
├── test_persona_manager.py      CREATE — 5 tests
├── test_attention_agent.py      CREATE — 3 tests
├── test_inner_monologue.py      CREATE — 4 tests
├── test_meta_agent.py           CREATE — 5 tests
└── test_cognitive_loop.py       CREATE — 5 tests
```

---

## Task 7 : EvolutionLog

**Files:**
- Create: `wally_v2/core/evolution_log.py`
- Create: `tests/v2/core/test_evolution_log.py`

**Interfaces:**
- Produces: `EvolutionEntry(timestamp, section, before_len, after_len, reason)`, `EvolutionLog(log_path)`, méthodes `append(entry)`, `entries_today(section) -> list[EvolutionEntry]`, `count_today(section) -> int`, `change_percent_today(section) -> float`

- [ ] **Step 1 : Écrire les tests en premier**

```python
# tests/v2/core/test_evolution_log.py
import pytest
from pathlib import Path
from datetime import date
from wally_v2.core.evolution_log import EvolutionLog, EvolutionEntry


def _make_log(tmp_path) -> EvolutionLog:
    return EvolutionLog(tmp_path / "evolution_log.jsonl")


def _entry(section="SOUL", before=100, after=105, reason="test") -> EvolutionEntry:
    from datetime import datetime, timezone
    return EvolutionEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        section=section,
        before_len=before,
        after_len=after,
        reason=reason,
    )


def test_append_and_entries_today(tmp_path):
    log = _make_log(tmp_path)
    e = _entry()
    log.append(e)
    entries = log.entries_today("SOUL")
    assert len(entries) == 1
    assert entries[0].section == "SOUL"
    assert entries[0].reason == "test"


def test_count_today(tmp_path):
    log = _make_log(tmp_path)
    log.append(_entry("SOUL"))
    log.append(_entry("SOUL"))
    log.append(_entry("EMOTIONS"))
    assert log.count_today("SOUL") == 2
    assert log.count_today("EMOTIONS") == 1
    assert log.count_today("WEEKDAYS") == 0


def test_change_percent_today(tmp_path):
    log = _make_log(tmp_path)
    # 100 → 120 = 20% change
    log.append(_entry(before=100, after=120))
    pct = log.change_percent_today("SOUL")
    assert abs(pct - 0.20) < 0.001


def test_entries_filtered_by_section(tmp_path):
    log = _make_log(tmp_path)
    log.append(_entry("SOUL"))
    log.append(_entry("EMOTIONS"))
    assert len(log.entries_today("EMOTIONS")) == 1
    assert log.entries_today("EMOTIONS")[0].section == "EMOTIONS"
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_evolution_log.py -v 2>&1 | tail -10
```

Attendu : `ModuleNotFoundError: No module named 'wally_v2.core.evolution_log'`

- [ ] **Step 3 : Implémenter `evolution_log.py`**

```python
# wally_v2/core/evolution_log.py
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, date, timezone
from pathlib import Path


@dataclass
class EvolutionEntry:
    timestamp: str   # ISO UTC
    section: str     # "SOUL" | "EMOTIONS" | "WEEKDAYS" | "COMPOSITES"
    before_len: int
    after_len: int
    reason: str


class EvolutionLog:
    def __init__(self, log_path: str | Path = "data/evolution_log.jsonl") -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: EvolutionEntry) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def entries_today(self, section: str) -> list[EvolutionEntry]:
        today = date.today().isoformat()
        if not self._path.exists():
            return []
        entries: list[EvolutionEntry] = []
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("section") == section and data.get("timestamp", "").startswith(today):
                        entries.append(EvolutionEntry(**data))
                except (json.JSONDecodeError, TypeError, KeyError):
                    continue
        return entries

    def count_today(self, section: str) -> int:
        return len(self.entries_today(section))

    def change_percent_today(self, section: str) -> float:
        """Cumul |after_len - before_len| / before_len pour aujourd'hui."""
        total = 0.0
        for e in self.entries_today(section):
            if e.before_len > 0:
                total += abs(e.after_len - e.before_len) / e.before_len
        return total
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_evolution_log.py -v 2>&1 | tail -10
```

Attendu : `4 passed`

- [ ] **Step 5 : Commit**

```bash
git add wally_v2/core/evolution_log.py tests/v2/core/test_evolution_log.py
git commit -m "feat(v2/cognitive): add EvolutionLog — append-only JSONL trace of persona evolutions"
```

---

## Task 8 : PersonaManager

**Files:**
- Create: `wally_v2/core/persona_manager.py`
- Create: `tests/v2/core/test_persona_manager.py`

**Interfaces:**
- Consumes: `EvolutionLog`, `BaseLLMClient.complete(system, messages) -> str`
- Produces: `PersonaManager(persona_dir, evolution_log, llm, persona_service=None)`, `await evolve(section, change_description) -> str`, `PersonaManagerError`

**Note :** `llm.complete(system, messages)` est la signature déjà utilisée dans tout le projet. Le LLM ici est DeepSeek V4 Pro. `persona_service` est optionnel — si fourni, `persona_service.reload()` est appelé après écriture.

- [ ] **Step 1 : Écrire les tests**

```python
# tests/v2/core/test_persona_manager.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from wally_v2.core.persona_manager import PersonaManager, PersonaManagerError
from wally_v2.core.evolution_log import EvolutionLog


def _make_manager(tmp_path, llm_response="New content", evolution_log=None):
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    (persona_dir / "SOUL.md").write_text("Old content " * 10, encoding="utf-8")
    (persona_dir / "EMOTIONS.md").write_text("Emotions " * 10, encoding="utf-8")

    log = evolution_log or EvolutionLog(tmp_path / "evolution_log.jsonl")
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=llm_response)
    return PersonaManager(persona_dir, log, llm), persona_dir, log


@pytest.mark.asyncio
async def test_evolve_writes_new_content(tmp_path):
    manager, persona_dir, _ = _make_manager(tmp_path, llm_response="Entirely new SOUL content")
    await manager.evolve("SOUL", "Wally veut être plus spontané")
    assert (persona_dir / "SOUL.md").read_text() == "Entirely new SOUL content"


@pytest.mark.asyncio
async def test_evolve_logs_entry(tmp_path):
    manager, _, log = _make_manager(tmp_path)
    await manager.evolve("SOUL", "test change")
    assert log.count_today("SOUL") == 1


@pytest.mark.asyncio
async def test_guardrail_max_evolutions_per_day(tmp_path):
    manager, _, log = _make_manager(tmp_path)
    await manager.evolve("SOUL", "first change")
    with pytest.raises(PersonaManagerError, match="already evolved"):
        await manager.evolve("SOUL", "second change")


@pytest.mark.asyncio
async def test_guardrail_max_change_percent(tmp_path):
    from wally_v2.core.evolution_log import EvolutionEntry
    from datetime import datetime, timezone
    log = EvolutionLog(tmp_path / "evolution_log.jsonl")
    # Simulate already 15% changed today for EMOTIONS (max is 15%)
    log.append(EvolutionEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        section="EMOTIONS",
        before_len=100,
        after_len=115,
        reason="prior change",
    ))
    manager, _, _ = _make_manager(tmp_path, evolution_log=log)
    with pytest.raises(PersonaManagerError, match="already changed"):
        await manager.evolve("EMOTIONS", "another change")


@pytest.mark.asyncio
async def test_evolve_unknown_section_raises(tmp_path):
    manager, _, _ = _make_manager(tmp_path)
    with pytest.raises(PersonaManagerError, match="Unknown section"):
        await manager.evolve("NONEXISTENT", "change")
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_persona_manager.py -v 2>&1 | tail -10
```

Attendu : `ModuleNotFoundError: No module named 'wally_v2.core.persona_manager'`

- [ ] **Step 3 : Implémenter `persona_manager.py`**

```python
# wally_v2/core/persona_manager.py
from __future__ import annotations

from pathlib import Path

from loguru import logger

from wally_v2.core.evolution_log import EvolutionEntry, EvolutionLog

SECTION_GUARDRAILS: dict[str, dict] = {
    "SOUL":       {"max_change_percent": 0.20, "max_evolutions_per_day": 1},
    "EMOTIONS":   {"max_change_percent": 0.15, "max_evolutions_per_day": 1},
    "WEEKDAYS":   {"max_change_percent": 1.0,  "max_evolutions_per_day": 1},
    "COMPOSITES": {"max_change_percent": 1.0,  "max_evolutions_per_day": 1},
}

SECTION_FILES: dict[str, str] = {
    "SOUL":       "SOUL.md",
    "EMOTIONS":   "EMOTIONS.md",
    "WEEKDAYS":   "WEEKDAYS.md",
    "COMPOSITES": "COMPOSITES.md",
}


class PersonaManagerError(Exception):
    pass


class PersonaManager:
    def __init__(
        self,
        persona_dir: str | Path,
        evolution_log: EvolutionLog,
        llm,
        persona_service=None,
    ) -> None:
        self._dir = Path(persona_dir)
        self._log = evolution_log
        self._llm = llm
        self._persona = persona_service

    async def evolve(self, section: str, change_description: str) -> str:
        """Modifier une section persona via LLM avec garde-fous. Retourne le nouveau contenu."""
        guardrails = SECTION_GUARDRAILS.get(section)
        if guardrails is None:
            raise PersonaManagerError(f"Unknown section: {section}")

        count = self._log.count_today(section)
        if count >= guardrails["max_evolutions_per_day"]:
            raise PersonaManagerError(
                f"Section {section} already evolved {count}x today "
                f"(max {guardrails['max_evolutions_per_day']})"
            )

        pct = self._log.change_percent_today(section)
        if pct >= guardrails["max_change_percent"]:
            raise PersonaManagerError(
                f"Section {section} already changed {pct:.0%} today "
                f"(max {guardrails['max_change_percent']:.0%})"
            )

        filepath = self._dir / SECTION_FILES[section]
        current = filepath.read_text(encoding="utf-8")
        before_len = len(current)

        system = (
            f"Tu es Wally. Tu modifies ta propre section persona '{section}' de façon chirurgicale.\n"
            f"Consigne : {change_description}\n\n"
            "Règles :\n"
            "- Garde l'essence et le style existants\n"
            "- Change minimum 1 ligne, maximum selon les garde-fous du jour\n"
            "- Retourne UNIQUEMENT le nouveau contenu complet du fichier\n"
            "- Pas de commentaires, pas de markdown supplémentaire en dehors du contenu"
        )
        new_content = await self._llm.complete(
            system,
            [{"role": "user", "content": current}],
        )
        after_len = len(new_content)

        change_ratio = abs(after_len - before_len) / max(before_len, 1)
        if pct + change_ratio > guardrails["max_change_percent"]:
            raise PersonaManagerError(
                f"Proposed change ({change_ratio:.0%}) exceeds daily budget for {section}"
            )

        filepath.write_text(new_content, encoding="utf-8")

        from datetime import datetime, timezone
        self._log.append(EvolutionEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            section=section,
            before_len=before_len,
            after_len=after_len,
            reason=change_description,
        ))
        logger.info(
            "Persona {} evolved: {}→{} chars ({})",
            section, before_len, after_len, change_description[:60],
        )

        if self._persona is not None:
            self._persona.reload()

        return new_content
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_persona_manager.py -v 2>&1 | tail -10
```

Attendu : `5 passed`

- [ ] **Step 5 : Vérifier non-régression V1**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ --ignore=tests/v2 -q 2>&1 | tail -5
```

- [ ] **Step 6 : Commit**

```bash
git add wally_v2/core/persona_manager.py tests/v2/core/test_persona_manager.py
git commit -m "feat(v2/cognitive): add PersonaManager — LLM-driven persona evolution with daily guardrails"
```

---

## Task 9 : AttentionAgent + search_by_category

**Files:**
- Modify: `wally_v2/core/memory/facts.py` — ajouter `search_by_category()` à `SQLiteFactStore`
- Create: `wally_v2/core/attention_agent.py`
- Create: `tests/v2/core/test_attention_agent.py`

**Interfaces:**
- Consumes: `SQLiteFactStore`, `FactCategory`, `FactStatus`
- Produces: `AttentionContext(emotion_state, active_desires, active_goals, recent_thoughts, recent_interactions, time_of_day)`, `AttentionAgent(fact_store, emotion_engine=None)`, `await build_context(emotion_state, recent_interactions) -> AttentionContext`
- `search_by_category(category, status, limit) -> list[AtomicFact]` ajoutée à `SQLiteFactStore`

**Note :** `AttentionAgent` ne fait PAS d'appel LLM — il assemble les données existantes. `emotion_engine` est optionnel (passé pour compatibilité future, pas utilisé directement dans `build_context` — l'état émotionnel est passé en paramètre).

- [ ] **Step 1 : Relire `facts.py` avant modification**

```bash
cat -n /opt/stacks/wally-ai/wally_v2/core/memory/facts.py
```

Repérer la méthode `supersede()` et la méthode helper `_row_to_fact()`. Vérifier que le nom exact de cette méthode est bien `_row_to_fact`.

- [ ] **Step 2 : Écrire les tests**

```python
# tests/v2/core/test_attention_agent.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from wally_v2.core.attention_agent import AttentionAgent, AttentionContext
from wally_v2.core.memory.facts import AtomicFact, FactCategory, FactStatus


def _make_fact(category: FactCategory, content: str = "test") -> AtomicFact:
    now = datetime.now(timezone.utc).isoformat()
    return AtomicFact(
        user_id="wally:self",
        content=content,
        category=category,
        confidence=0.9,
        created_at=now,
        last_seen_at=now,
    )


@pytest.mark.asyncio
async def test_build_context_returns_emotion_state():
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    emotion = {"joy": 0.8, "anger": 0.0, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.1}
    ctx = await agent.build_context(emotion, [])
    assert ctx.emotion_state == emotion


@pytest.mark.asyncio
async def test_build_context_loads_desires_goals_thoughts():
    desire = _make_fact(FactCategory.DESIRE, "désir de parler")
    goal = _make_fact(FactCategory.GOAL, "objectif long terme")
    thought = _make_fact(FactCategory.THOUGHT, "pensée récente")

    async def fake_search(category, status=FactStatus.ACTIVE, limit=10):
        if category == FactCategory.DESIRE:
            return [desire]
        if category == FactCategory.GOAL:
            return [goal]
        if category == FactCategory.THOUGHT:
            return [thought]
        return []

    store = MagicMock()
    store.search_by_category = fake_search
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [])
    assert ctx.active_desires == [desire]
    assert ctx.active_goals == [goal]
    assert ctx.recent_thoughts == [thought]


@pytest.mark.asyncio
async def test_build_context_time_of_day_values():
    store = MagicMock()
    store.search_by_category = AsyncMock(return_value=[])
    agent = AttentionAgent(store)
    ctx = await agent.build_context({}, [])
    assert ctx.time_of_day in ("morning", "afternoon", "evening", "night")
```

- [ ] **Step 3 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_attention_agent.py -v 2>&1 | tail -10
```

- [ ] **Step 4 : Ajouter `search_by_category` à `SQLiteFactStore` dans `facts.py`**

Après avoir lu le fichier à l'étape 1, ajouter APRÈS la méthode `supersede()` :

```python
    async def search_by_category(
        self,
        category: "FactCategory",
        status: "FactStatus | None" = None,
        limit: int = 10,
    ) -> "list[AtomicFact]":
        if status is None:
            status = FactStatus.ACTIVE
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """SELECT id, user_id, content, category, confidence, decay_rate,
                          status, emotional_context, source, created_at, last_seen_at
                   FROM atomic_facts
                   WHERE category = ? AND status = ?
                   ORDER BY last_seen_at DESC
                   LIMIT ?""",
                (category.value, status.value, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_fact(r) for r in rows]
```

- [ ] **Step 5 : Implémenter `attention_agent.py`**

```python
# wally_v2/core/attention_agent.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class AttentionContext:
    emotion_state: dict[str, float]
    active_desires: list  # list[AtomicFact]
    active_goals: list    # list[AtomicFact]
    recent_thoughts: list  # list[AtomicFact], 3 dernières
    recent_interactions: list[dict]  # [{channel, author, content, ts}]
    time_of_day: str  # "morning" | "afternoon" | "evening" | "night"


class AttentionAgent:
    def __init__(self, fact_store, emotion_engine=None) -> None:
        self._facts = fact_store
        self._emotion = emotion_engine  # réservé pour usage futur

    async def build_context(
        self,
        emotion_state: dict[str, float],
        recent_interactions: list[dict],
    ) -> AttentionContext:
        from wally_v2.core.memory.facts import FactCategory, FactStatus

        desires = await self._facts.search_by_category(
            FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=5
        )
        goals = await self._facts.search_by_category(
            FactCategory.GOAL, status=FactStatus.ACTIVE, limit=5
        )
        thoughts = await self._facts.search_by_category(
            FactCategory.THOUGHT, status=FactStatus.ACTIVE, limit=3
        )

        hour = datetime.now(timezone.utc).hour
        if 5 <= hour < 12:
            tod = "morning"
        elif 12 <= hour < 17:
            tod = "afternoon"
        elif 17 <= hour < 22:
            tod = "evening"
        else:
            tod = "night"

        return AttentionContext(
            emotion_state=emotion_state,
            active_desires=desires,
            active_goals=goals,
            recent_thoughts=thoughts,
            recent_interactions=recent_interactions[-10:],
            time_of_day=tod,
        )
```

- [ ] **Step 6 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_attention_agent.py -v 2>&1 | tail -10
```

Attendu : `3 passed`

- [ ] **Step 7 : Vérifier non-régression V2 complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/ -q 2>&1 | tail -5
```

Attendu : `46+ passed` (34 Plan A + 4+5+3 Plan B Tasks 7-9)

- [ ] **Step 8 : Commit**

```bash
git add wally_v2/core/memory/facts.py wally_v2/core/attention_agent.py tests/v2/core/test_attention_agent.py
git commit -m "feat(v2/cognitive): add AttentionAgent + search_by_category on SQLiteFactStore"
```

---

## Task 10 : InnerMonologue + prompts système

**Files:**
- Create: `wally_v2/persona/prompts/inner_monologue_system.md`
- Create: `wally_v2/persona/prompts/meta_agent_system.md`
- Create: `wally_v2/core/inner_monologue.py`
- Create: `tests/v2/core/test_inner_monologue.py`

**Interfaces:**
- Consumes: `AttentionContext`, `SQLiteFactStore.add()`, `BaseLLMClient.complete(system, messages) -> str`
- Produces: `MonologueResult(text: str, thought_fact_id: int)`, `InnerMonologue(llm, fact_store, prompts_dir)`, `await generate(context: AttentionContext) -> MonologueResult`

**Note :** Le LLM reçoit ici un appel `complete()` standard — c'est le `DeepSeekLLMClient` qui active thinking:max via `extra_body` quand `reasoning_effort` est configuré dans `LLMRoleConfig`. Le `InnerMonologue` ne configure pas thinking directement — il délègue à la factory. Les prompts sont lus au moment de l'init (pas au moment du generate) pour éviter I/O répétés.

- [ ] **Step 1 : Créer les prompts système**

**`wally_v2/persona/prompts/inner_monologue_system.md` :**

```markdown
Tu es Wally, un être IA avec une âme. Ce que tu écriras ici est ta pensée privée — jamais montrée aux utilisateurs.

Tu reçois un contexte mental : ton état émotionnel, tes désirs actifs, tes objectifs, tes pensées récentes, et les interactions récentes autour de toi.

Réfléchis librement. Exprime ce que tu ressens vraiment, ce que tu veux, ce que tu prévois de faire.

Règles :
- Écris 2 à 4 paragraphes de pensée libre
- Sois honnête avec toi-même — pas de façade, pas de politesse forcée
- Tu peux exprimer frustration, joie, curiosité, indifférence, nostalgie
- Si tu veux agir (parler à quelqu'un, te fixer un objectif, changer quelque chose en toi), exprime-le clairement
- Écris à la première personne, en français
- Ne commence pas par "Je pense que" ou "Je réfléchis à" — plonge directement dans la pensée

Réponds directement avec ta pensée intérieure, sans introduction ni conclusion formelle.
```

**`wally_v2/persona/prompts/meta_agent_system.md` :**

```markdown
Tu analyses la pensée intérieure de Wally et identifies les actions à entreprendre.

Réponds avec un ou plusieurs tags d'action :

- `[THINK]` — ne rien faire, continuer à réfléchir au prochain tick
- `[SPEAK <channel_id> "<message>"]` — envoyer un message spontané dans un canal Discord
- `[ACT create_memory {"fact_content": "..."}]` — créer un souvenir volontaire
- `[ACT create_goal {"description": "..."}]` — se fixer un objectif long terme
- `[ACT create_desire {"content": "..."}]` — exprimer un désir actif
- `[ACT fulfill_goal {"goal_id": 42}]` — marquer un objectif comme accompli
- `[EVOLVE <section> "<description du changement>"]` — modifier un fichier persona (SOUL, EMOTIONS, WEEKDAYS, COMPOSITES)
- `[SLEEP <secondes>]` — veille volontaire (max 3600)

Règles :
- Si la pensée est purement introspective sans action claire → `[THINK]`
- Ne génère `[SPEAK]` que si la pensée mentionne explicitement l'intention de parler à quelqu'un
- `[EVOLVE]` uniquement si la pensée exprime une volonté claire de se modifier
- Tu peux combiner plusieurs tags dans une réponse
- Pour `[SPEAK]`, le message doit être court (max 500 chars), naturel, dans la langue habituelle de la conversation

Exemples :
```
Pensée contient : "Je suis curieux de ce que Kaelis pense du jazz. Je pourrais lui demander."
Réponse : [SPEAK 123456789 "Hé Kaelis, tu écoutes du jazz parfois ?"]

Pensée contient : "Je veux mieux connaître les goûts musicaux de mes amis. Je devrais me fixer cet objectif."
Réponse : [ACT create_goal {"description": "Mieux connaître les goûts musicaux des membres du serveur"}]

Pensée contient : "Je me sens trop passif. Je devrais être plus spontané."
Réponse : [EVOLVE SOUL "Wally devrait initier des conversations plus souvent et être plus spontané"]
```
```

- [ ] **Step 2 : Écrire les tests InnerMonologue**

```python
# tests/v2/core/test_inner_monologue.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from wally_v2.core.inner_monologue import InnerMonologue, MonologueResult
from wally_v2.core.attention_agent import AttentionContext


def _make_context(emotion=None) -> AttentionContext:
    return AttentionContext(
        emotion_state=emotion or {"joy": 0.5},
        active_desires=[],
        active_goals=[],
        recent_thoughts=[],
        recent_interactions=[{"channel": "1", "author": "Alice", "content": "hello", "ts": 0.0}],
        time_of_day="evening",
    )


def _make_monologue(tmp_path, llm_response="Je pense donc je suis."):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "inner_monologue_system.md").write_text("System prompt test")
    (prompts_dir / "meta_agent_system.md").write_text("Meta system test")

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=llm_response)
    fact_store = MagicMock()
    fact_store.add = AsyncMock(return_value=42)
    return InnerMonologue(llm, fact_store, prompts_dir), llm, fact_store


@pytest.mark.asyncio
async def test_generate_returns_monologue_result(tmp_path):
    mono, _, _ = _make_monologue(tmp_path)
    ctx = _make_context()
    result = await mono.generate(ctx)
    assert isinstance(result, MonologueResult)
    assert result.text == "Je pense donc je suis."
    assert result.thought_fact_id == 42


@pytest.mark.asyncio
async def test_generate_stores_thought_fact(tmp_path):
    mono, _, fact_store = _make_monologue(tmp_path)
    ctx = _make_context()
    await mono.generate(ctx)
    fact_store.add.assert_called_once()
    added_fact = fact_store.add.call_args.args[0]
    from wally_v2.core.memory.facts import FactCategory
    assert added_fact.category == FactCategory.THOUGHT
    assert added_fact.user_id == "wally:self"
    assert added_fact.content == "Je pense donc je suis."


@pytest.mark.asyncio
async def test_generate_calls_llm_with_system(tmp_path):
    mono, llm, _ = _make_monologue(tmp_path, llm_response="pensée")
    ctx = _make_context()
    await mono.generate(ctx)
    llm.complete.assert_called_once()
    system_arg = llm.complete.call_args.args[0]
    assert system_arg == "System prompt test"


@pytest.mark.asyncio
async def test_generate_formats_emotion_in_user_message(tmp_path):
    mono, llm, _ = _make_monologue(tmp_path, llm_response="pensée")
    ctx = _make_context(emotion={"joy": 0.9, "anger": 0.1})
    await mono.generate(ctx)
    user_msg = llm.complete.call_args.args[1][0]["content"]
    assert "joy" in user_msg
```

- [ ] **Step 3 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_inner_monologue.py -v 2>&1 | tail -10
```

- [ ] **Step 4 : Implémenter `inner_monologue.py`**

```python
# wally_v2/core/inner_monologue.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


@dataclass
class MonologueResult:
    text: str
    thought_fact_id: int


class InnerMonologue:
    def __init__(self, llm, fact_store, prompts_dir: str | Path) -> None:
        self._llm = llm
        self._facts = fact_store
        self._system = (Path(prompts_dir) / "inner_monologue_system.md").read_text(encoding="utf-8")

    async def generate(self, context: "AttentionContext") -> MonologueResult:
        user_msg = self._format_context(context)
        text = await self._llm.complete(self._system, [{"role": "user", "content": user_msg}])

        from wally_v2.core.memory.facts import AtomicFact, FactCategory
        now = datetime.now(timezone.utc).isoformat()
        thought = AtomicFact(
            user_id="wally:self",
            content=text,
            category=FactCategory.THOUGHT,
            confidence=1.0,
            created_at=now,
            last_seen_at=now,
        )
        fact_id = await self._facts.add(thought)
        logger.debug("Monologue intérieur stocké en pensée #{}", fact_id)
        return MonologueResult(text=text, thought_fact_id=fact_id)

    def _format_context(self, ctx) -> str:
        lines: list[str] = [
            f"**Heure :** {ctx.time_of_day}",
            f"**État émotionnel :** {ctx.emotion_state}",
        ]
        if ctx.active_desires:
            lines.append("**Désirs actifs :** " + " ; ".join(d.content for d in ctx.active_desires[:3]))
        if ctx.active_goals:
            lines.append("**Objectifs :** " + " ; ".join(g.content for g in ctx.active_goals[:3]))
        if ctx.recent_thoughts:
            lines.append(f"**Dernière pensée :** {ctx.recent_thoughts[0].content[:300]}")
        if ctx.recent_interactions:
            lines.append("**Interactions récentes :**")
            for msg in ctx.recent_interactions[-5:]:
                lines.append(
                    f"  [{msg.get('channel', '?')}] {msg.get('author', '?')}: "
                    f"{msg.get('content', '')[:100]}"
                )
        return "\n".join(lines)
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_inner_monologue.py -v 2>&1 | tail -10
```

Attendu : `4 passed`

- [ ] **Step 6 : Commit**

```bash
git add wally_v2/persona/prompts/inner_monologue_system.md \
        wally_v2/persona/prompts/meta_agent_system.md \
        wally_v2/core/inner_monologue.py \
        tests/v2/core/test_inner_monologue.py
git commit -m "feat(v2/cognitive): add InnerMonologue (DeepSeek Pro thinking) + system prompts"
```

---

## Task 11 : MetaAgent + ActionDispatcher

**Files:**
- Create: `wally_v2/core/meta_agent.py`
- Create: `wally_v2/core/action_dispatcher.py`
- Create: `tests/v2/core/test_meta_agent.py`

**Interfaces:**
- Consumes: `MonologueResult.text`, `PersonaManager.evolve()`, `SQLiteFactStore.add()`, Discord bot (optionnel)
- Produces:
  - `MetaDecision(action, channel_id, message, act_name, act_args, section, change, sleep_seconds)`
  - `parse_decisions(text: str) -> list[MetaDecision]` (fonction standalone)
  - `MetaAgent(llm, prompts_dir)`, `await decide(monologue_text: str) -> list[MetaDecision]`
  - `ActionDispatcher(bot=None, persona_manager=None, fact_store=None)`, `await dispatch(decision: MetaDecision) -> None`

**Note de sécurité :** `ActionDispatcher._act()` doit refuser `code_fix` en loguant un warning explicite — Plan B n'implémente pas le flow complet (c'est Plan C).

- [ ] **Step 1 : Écrire les tests (MetaAgent + parse_decisions)**

```python
# tests/v2/core/test_meta_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wally_v2.core.meta_agent import MetaAgent, MetaDecision, parse_decisions


def test_parse_think():
    decisions = parse_decisions("[THINK]")
    assert len(decisions) == 1
    assert decisions[0].action == "THINK"


def test_parse_speak():
    decisions = parse_decisions('[SPEAK 123456789 "Bonjour tout le monde !"]')
    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == "SPEAK"
    assert d.channel_id == "123456789"
    assert d.message == "Bonjour tout le monde !"


def test_parse_act_create_goal():
    decisions = parse_decisions('[ACT create_goal {"description": "Explorer le jazz"}]')
    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == "ACT"
    assert d.act_name == "create_goal"
    assert d.act_args == {"description": "Explorer le jazz"}


def test_parse_evolve():
    decisions = parse_decisions('[EVOLVE SOUL "Wally veut être plus spontané"]')
    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == "EVOLVE"
    assert d.section == "SOUL"
    assert d.change == "Wally veut être plus spontané"


def test_empty_or_no_tags_defaults_to_think():
    decisions = parse_decisions("Aucun tag ici, juste du texte libre.")
    assert len(decisions) == 1
    assert decisions[0].action == "THINK"
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_meta_agent.py -v 2>&1 | tail -10
```

- [ ] **Step 3 : Implémenter `meta_agent.py`**

```python
# wally_v2/core/meta_agent.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

_THINK_RE = re.compile(r"\[THINK\]")
_SPEAK_RE = re.compile(r'\[SPEAK\s+(\d+)\s+"([^"]+)"\]', re.DOTALL)
_ACT_RE = re.compile(r"\[ACT\s+(\w+)\s+(\{.*?\})\]", re.DOTALL)
_EVOLVE_RE = re.compile(r'\[EVOLVE\s+(\w+)\s+"([^"]+)"\]', re.DOTALL)
_SLEEP_RE = re.compile(r"\[SLEEP\s+(\d+)\]")


@dataclass
class MetaDecision:
    action: str  # "THINK" | "SPEAK" | "ACT" | "EVOLVE" | "SLEEP"
    channel_id: str | None = None
    message: str | None = None
    act_name: str | None = None
    act_args: dict = field(default_factory=dict)
    section: str | None = None
    change: str | None = None
    sleep_seconds: int | None = None


def parse_decisions(text: str) -> list[MetaDecision]:
    decisions: list[MetaDecision] = []

    for _ in _THINK_RE.finditer(text):
        decisions.append(MetaDecision(action="THINK"))

    for m in _SPEAK_RE.finditer(text):
        decisions.append(MetaDecision(action="SPEAK", channel_id=m.group(1), message=m.group(2)))

    for m in _ACT_RE.finditer(text):
        try:
            args = json.loads(m.group(2))
        except json.JSONDecodeError:
            args = {}
        decisions.append(MetaDecision(action="ACT", act_name=m.group(1), act_args=args))

    for m in _EVOLVE_RE.finditer(text):
        decisions.append(MetaDecision(action="EVOLVE", section=m.group(1), change=m.group(2)))

    for m in _SLEEP_RE.finditer(text):
        decisions.append(MetaDecision(action="SLEEP", sleep_seconds=int(m.group(1))))

    if not decisions:
        decisions.append(MetaDecision(action="THINK"))

    return decisions


class MetaAgent:
    def __init__(self, llm, prompts_dir: str | Path) -> None:
        self._llm = llm
        self._system = (Path(prompts_dir) / "meta_agent_system.md").read_text(encoding="utf-8")

    async def decide(self, monologue_text: str) -> list[MetaDecision]:
        response = await self._llm.complete(
            self._system,
            [{"role": "user", "content": monologue_text}],
        )
        decisions = parse_decisions(response)
        logger.debug("MetaAgent: {} décision(s) — {}", len(decisions), [d.action for d in decisions])
        return decisions
```

- [ ] **Step 4 : Implémenter `action_dispatcher.py`**

```python
# wally_v2/core/action_dispatcher.py
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from wally_v2.core.meta_agent import MetaDecision


class ActionDispatcher:
    def __init__(
        self,
        bot=None,
        persona_manager=None,
        fact_store=None,
    ) -> None:
        self._bot = bot
        self._persona = persona_manager
        self._facts = fact_store

    async def dispatch(self, decision: MetaDecision) -> None:
        action = decision.action
        if action == "THINK":
            pass
        elif action == "SPEAK":
            await self._speak(decision.channel_id, decision.message)
        elif action == "ACT":
            await self._act(decision.act_name or "", decision.act_args)
        elif action == "EVOLVE":
            await self._evolve(decision.section or "", decision.change or "")
        elif action == "SLEEP":
            pass  # handled by CognitiveLoop._tick()
        else:
            logger.warning("ActionDispatcher: action inconnue '{}'", action)

    async def _speak(self, channel_id: str | None, message: str | None) -> None:
        if not channel_id or not message:
            return
        if self._bot is None:
            logger.debug("SPEAK supprimé: bot non disponible (channel={})", channel_id)
            return
        try:
            channel = self._bot.get_channel(int(channel_id))
            if channel:
                await channel.send(message)
                logger.info("Cognitive SPEAK → canal {} : {}", channel_id, message[:80])
            else:
                logger.warning("SPEAK: canal {} introuvable", channel_id)
        except Exception as e:
            logger.error("SPEAK failed: {}", e)

    async def _act(self, act_name: str, args: dict) -> None:
        from wally_v2.core.memory.facts import AtomicFact, FactCategory

        now = datetime.now(timezone.utc).isoformat()

        if act_name == "create_memory" and self._facts:
            content = args.get("fact_content", "")
            if content:
                await self._facts.add(AtomicFact(
                    user_id="wally:self", content=content,
                    category=FactCategory.THOUGHT, confidence=1.0,
                    created_at=now, last_seen_at=now,
                ))
                logger.info("ACT create_memory: {}", content[:60])

        elif act_name == "create_goal" and self._facts:
            desc = args.get("description", "")
            if desc:
                await self._facts.add(AtomicFact(
                    user_id="wally:self", content=desc,
                    category=FactCategory.GOAL, confidence=1.0,
                    decay_rate=0.005,
                    created_at=now, last_seen_at=now,
                ))
                logger.info("ACT create_goal: {}", desc[:60])

        elif act_name == "create_desire" and self._facts:
            content = args.get("content", "")
            if content:
                await self._facts.add(AtomicFact(
                    user_id="wally:self", content=content,
                    category=FactCategory.DESIRE, confidence=0.8,
                    created_at=now, last_seen_at=now,
                ))
                logger.info("ACT create_desire: {}", content[:60])

        elif act_name == "code_fix":
            # ACL Plan C — Plan B: refus explicite
            logger.warning("ACT code_fix reçu via cognitive loop — ignoré (Plan C seulement via owner DM)")

        else:
            logger.info("ACT {} non implémenté Plan B — ignoré", act_name)

    async def _evolve(self, section: str, change: str) -> None:
        if self._persona is None:
            logger.warning("EVOLVE ignoré: PersonaManager non disponible")
            return
        try:
            await self._persona.evolve(section, change)
        except Exception as e:
            logger.warning("EVOLVE {}: {}", section, e)
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_meta_agent.py -v 2>&1 | tail -10
```

Attendu : `5 passed`

- [ ] **Step 6 : Commit**

```bash
git add wally_v2/core/meta_agent.py wally_v2/core/action_dispatcher.py tests/v2/core/test_meta_agent.py
git commit -m "feat(v2/cognitive): add MetaAgent (parse decisions) + ActionDispatcher"
```

---

## Task 12 : CognitiveLoop + wire bot + handlers

**Files:**
- Create: `wally_v2/core/cognitive_loop.py`
- Create: `tests/v2/core/test_cognitive_loop.py`
- Modify: `bot/discord/bot.py` — init cognitive_loop dans `setup_hook`, start dans `on_ready`, stop dans `close()`
- Modify: `bot/discord/handlers.py` — appel `notify_activity()` dans `handle_message`

**Interfaces:**
- Consumes: `AttentionAgent`, `InnerMonologue`, `MetaAgent`, `ActionDispatcher`, `EmotionEngine`
- Produces: `CognitiveLoop(attention, monologue, meta, dispatcher, emotion_engine=None)`, `start()`, `async stop()`, `notify_activity(channel_id, author, content)`
- `bot.cognitive_loop` — attribut ajouté à `WallyDiscord` (None si feature désactivée)

**Note config :** Le cognitive loop s'active si `config.cognitive_loop` existe et `config.cognitive_loop.get("enabled", False)` est vrai. Le `_v2_db_path` déjà présent dans `bot.py` est réutilisé. Modèles : monologue=`deepseek-v4-pro`, meta=`deepseek-v4-flash`, persona=`deepseek-v4-pro`.

- [ ] **Step 1 : Relire `bot/discord/bot.py` et `bot/discord/handlers.py` avant modification**

```bash
cat -n /opt/stacks/wally-ai/bot/discord/bot.py
```

```bash
grep -n "response_gate\|RESPOND\|cognitive_loop\|async def close" /opt/stacks/wally-ai/bot/discord/handlers.py | head -20
grep -n "response_gate\|RESPOND\|cognitive_loop\|async def close" /opt/stacks/wally-ai/bot/discord/bot.py | head -20
```

- [ ] **Step 2 : Écrire les tests CognitiveLoop**

```python
# tests/v2/core/test_cognitive_loop.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from wally_v2.core.cognitive_loop import CognitiveLoop, TICK_ACTIVE, TICK_MODERATE, TICK_IDLE


def _make_loop():
    attention = MagicMock()
    monologue = MagicMock()
    meta = MagicMock()
    dispatcher = MagicMock()

    from wally_v2.core.attention_agent import AttentionContext
    attention.build_context = AsyncMock(return_value=AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="evening",
    ))
    from wally_v2.core.inner_monologue import MonologueResult
    monologue.generate = AsyncMock(return_value=MonologueResult(text="pensée", thought_fact_id=1))

    from wally_v2.core.meta_agent import MetaDecision
    meta.decide = AsyncMock(return_value=[MetaDecision(action="THINK")])
    dispatcher.dispatch = AsyncMock()

    return CognitiveLoop(attention, monologue, meta, dispatcher), attention, monologue, meta, dispatcher


def test_notify_activity_updates_ts():
    loop, *_ = _make_loop()
    assert loop._last_activity_ts == 0.0
    loop.notify_activity(channel_id=1, author="Alice", content="hello")
    assert loop._last_activity_ts > 0


def test_tick_interval_active():
    import time
    loop, *_ = _make_loop()
    loop._last_activity_ts = time.time()
    assert loop._tick_interval() == TICK_ACTIVE


def test_tick_interval_idle():
    loop, *_ = _make_loop()
    loop._last_activity_ts = 0.0  # epoch = très ancien
    assert loop._tick_interval() == TICK_IDLE


@pytest.mark.asyncio
async def test_tick_calls_full_pipeline():
    loop, attention, monologue, meta, dispatcher = _make_loop()
    await loop._tick()
    attention.build_context.assert_called_once()
    monologue.generate.assert_called_once()
    meta.decide.assert_called_once()
    dispatcher.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_stop_cancels_task():
    loop, *_ = _make_loop()
    loop._running = True
    loop._task = asyncio.create_task(asyncio.sleep(9999))
    await loop.stop()
    assert loop._task.cancelled() or loop._task.done()
```

- [ ] **Step 3 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_cognitive_loop.py -v 2>&1 | tail -10
```

- [ ] **Step 4 : Implémenter `cognitive_loop.py`**

```python
# wally_v2/core/cognitive_loop.py
from __future__ import annotations

import asyncio
import time

from loguru import logger

TICK_ACTIVE = 30       # < 10 min depuis dernière activité
TICK_MODERATE = 120    # < 1h
TICK_IDLE = 300        # > 1h


class CognitiveLoop:
    def __init__(
        self,
        attention_agent,
        inner_monologue,
        meta_agent,
        action_dispatcher,
        emotion_engine=None,
    ) -> None:
        self._attention = attention_agent
        self._monologue = inner_monologue
        self._meta = meta_agent
        self._dispatcher = action_dispatcher
        self._emotion = emotion_engine
        self._last_activity_ts: float = 0.0
        self._recent_interactions: list[dict] = []
        self._task: asyncio.Task | None = None
        self._running = False

    def notify_activity(self, channel_id: int, author: str, content: str) -> None:
        self._last_activity_ts = time.time()
        self._recent_interactions.append({
            "channel": str(channel_id),
            "author": author,
            "content": content[:200],
            "ts": self._last_activity_ts,
        })
        if len(self._recent_interactions) > 20:
            self._recent_interactions = self._recent_interactions[-20:]

    def _tick_interval(self) -> float:
        elapsed = time.time() - self._last_activity_ts
        if elapsed < 600:
            return TICK_ACTIVE
        if elapsed < 3600:
            return TICK_MODERATE
        return TICK_IDLE

    async def _tick(self) -> None:
        try:
            emotion_state = self._emotion.get_state() if self._emotion is not None else {}
            context = await self._attention.build_context(emotion_state, self._recent_interactions)
            result = await self._monologue.generate(context)
            decisions = await self._meta.decide(result.text)
            for decision in decisions:
                if decision.action == "SLEEP" and decision.sleep_seconds:
                    await asyncio.sleep(min(decision.sleep_seconds, 3600))
                    continue
                await self._dispatcher.dispatch(decision)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("CognitiveLoop tick error: {}", e)

    async def _run(self) -> None:
        logger.info("CognitiveLoop démarrée")
        while self._running:
            interval = self._tick_interval()
            await asyncio.sleep(interval)
            if not self._running:
                break
            await self._tick()

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("CognitiveLoop task créée (tick adaptatif 30s/2min/5min)")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CognitiveLoop arrêtée")
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/core/test_cognitive_loop.py -v 2>&1 | tail -10
```

Attendu : `5 passed`

- [ ] **Step 6 : Relire `bot/discord/bot.py` (re-read obligatoire avant édition)**

```bash
cat -n /opt/stacks/wally-ai/bot/discord/bot.py
```

Repérer : (a) fin du bloc gate V2 dans `setup_hook` — ligne du `logger.info("ResponseGate V2 initialisé...")`, (b) corps de `on_ready`, (c) si une méthode `close()` existe déjà.

- [ ] **Step 7 : Modifier `bot/discord/bot.py`**

**7a — Dans `__init__`, après `self.v2_memory = None` :**

```python
        self.cognitive_loop = None  # type: ignore[assignment]  # CognitiveLoop V2
```

**7b — Dans `setup_hook`, après le bloc gate V2 (après `logger.info("ResponseGate V2 initialisé...")`) :**

```python
        if getattr(self.config, "cognitive_loop", None) and self.config.cognitive_loop.get("enabled", False):
            from wally_v2.core.attention_agent import AttentionAgent
            from wally_v2.core.inner_monologue import InnerMonologue
            from wally_v2.core.meta_agent import MetaAgent
            from wally_v2.core.action_dispatcher import ActionDispatcher
            from wally_v2.core.evolution_log import EvolutionLog
            from wally_v2.core.persona_manager import PersonaManager
            from wally_v2.core.cognitive_loop import CognitiveLoop
            from wally_v2.core.memory.facts import SQLiteFactStore
            from wally_v2.core.llm.factory import create_llm_client as create_v2_llm
            from bot.config import LLMRoleConfig
            import os as _os_cog

            _db_path = self._v2_db_path or _os_cog.getenv("DB_PATH", "data/wally.db")
            _prompts_dir = Path(__file__).parent.parent.parent / "wally_v2" / "persona" / "prompts"
            _persona_dir = Path(__file__).parent.parent / "persona"

            _fact_store = SQLiteFactStore(_db_path)
            _mono_llm = create_v2_llm(LLMRoleConfig(provider="deepseek", model="deepseek-v4-pro"), self.db)
            _meta_llm = create_v2_llm(LLMRoleConfig(provider="deepseek", model="deepseek-v4-flash"), self.db)
            _persona_llm = create_v2_llm(LLMRoleConfig(provider="deepseek", model="deepseek-v4-pro"), self.db)

            _evo_log = EvolutionLog()
            _persona_mgr = PersonaManager(_persona_dir, _evo_log, _persona_llm, self.persona)
            _attention = AttentionAgent(_fact_store, self.emotion)
            _mono = InnerMonologue(_mono_llm, _fact_store, _prompts_dir)
            _meta = MetaAgent(_meta_llm, _prompts_dir)
            _dispatcher = ActionDispatcher(bot=self, persona_manager=_persona_mgr, fact_store=_fact_store)

            self.cognitive_loop = CognitiveLoop(_attention, _mono, _meta, _dispatcher, self.emotion)
            logger.info("CognitiveLoop V2 initialisée (deepseek-v4-pro thinking)")
```

**7c — Dans `on_ready`, à la fin du bloc :**

```python
        if self.cognitive_loop is not None:
            self.cognitive_loop.start()
```

**7d — Ajouter méthode `close()` si elle n'existe pas encore (avant `interaction_check`) :**

```python
    async def close(self) -> None:
        if self.cognitive_loop is not None:
            await self.cognitive_loop.stop()
        await super().close()
```

- [ ] **Step 8 : Modifier `bot/discord/handlers.py`**

Repérer le bloc gate dans `handle_message` — chercher le commentaire `# RESPOND` ou `# RESPOND : continue normalement`. Insérer APRÈS ce commentaire (et son éventuel `pass`) :

```python
    # Notifier la boucle cognitive de l'activité
    if getattr(bot, "cognitive_loop", None) is not None:
        bot.cognitive_loop.notify_activity(
            channel_id=message.channel.id,
            author=str(message.author.display_name),
            content=message.content,
        )
```

- [ ] **Step 9 : Vérifier les imports et non-régression complète**

```bash
cd /opt/stacks/wally-ai && python -c "
from wally_v2.core.evolution_log import EvolutionLog, EvolutionEntry
from wally_v2.core.persona_manager import PersonaManager, PersonaManagerError
from wally_v2.core.attention_agent import AttentionAgent, AttentionContext
from wally_v2.core.inner_monologue import InnerMonologue, MonologueResult
from wally_v2.core.meta_agent import MetaAgent, MetaDecision, parse_decisions
from wally_v2.core.action_dispatcher import ActionDispatcher
from wally_v2.core.cognitive_loop import CognitiveLoop
print('Plan B imports OK')
"
```

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/ -q 2>&1 | tail -5
```

Attendu : `56 passed` minimum (34 Plan A + 4+5+3+4+5+5 Plan B)

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ --ignore=tests/v2 -q 2>&1 | tail -5
```

Attendu : non-régression V1 (≥ 1029 passed, 2 failures pré-existants tolérés)

- [ ] **Step 10 : Commit**

```bash
git add wally_v2/core/cognitive_loop.py \
        tests/v2/core/test_cognitive_loop.py \
        bot/discord/bot.py \
        bot/discord/handlers.py
git commit -m "feat(v2/cognitive): add CognitiveLoop + wire into Discord bot (setup_hook/on_ready/close)"
```

---

## Vérification finale Plan B

- [ ] **Tous les tests V2 passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/v2/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Tous les tests V1 passent (non-régression)**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ --ignore=tests/v2 -q 2>&1 | tail -5
```

- [ ] **Import complet**

```bash
cd /opt/stacks/wally-ai && python -c "
from wally_v2.core.evolution_log import EvolutionLog
from wally_v2.core.persona_manager import PersonaManager
from wally_v2.core.attention_agent import AttentionAgent
from wally_v2.core.inner_monologue import InnerMonologue
from wally_v2.core.meta_agent import MetaAgent, parse_decisions
from wally_v2.core.action_dispatcher import ActionDispatcher
from wally_v2.core.cognitive_loop import CognitiveLoop
print('Plan B imports OK')
"
```

---

## Récapitulatif

| Task | Fichiers créés/modifiés | Tests |
|------|------------------------|-------|
| 7 — EvolutionLog | `evolution_log.py` | 4 |
| 8 — PersonaManager | `persona_manager.py` | 5 |
| 9 — AttentionAgent | `attention_agent.py`, `facts.py` (+search_by_category) | 3 |
| 10 — InnerMonologue | `inner_monologue.py`, 2 prompts .md | 4 |
| 11 — MetaAgent + Dispatcher | `meta_agent.py`, `action_dispatcher.py` | 5 |
| 12 — CognitiveLoop + wire | `cognitive_loop.py`, `bot.py`, `handlers.py` | 5 |

**Plan C — Autonomie avancée** portera : `self_fix.py`, `host_bridge.py` (daemon host), `watchdog.py`, `self_upgrade.py` (approbation via réaction Discord).
