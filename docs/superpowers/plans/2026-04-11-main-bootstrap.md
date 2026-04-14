# main.py → bootstrap.py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extraire la logique de création des services core de `bot/main.py` vers `bot/bootstrap.py`, rendant `main()` plus lisible et les services plus testables.

**Architecture:** `bot/bootstrap.py` exporte un dataclass `CoreServices` + `async def build_core_services(config, db, qdrant_url)`. `main()` appelle `build_core_services()` puis câble les adapters. Zéro changement d'interface pour les appelants externes.

**Tech Stack:** Python, asyncio, aiosqlite, loguru

---

## File Map

| Fichier | Action |
|---|---|
| `bot/bootstrap.py` | Créer — `CoreServices` dataclass + `build_core_services()` |
| `bot/main.py` | Modifier — `main()` délègue à `build_core_services()` |

---

### Task 1 : Créer `bot/bootstrap.py`

**Files:**
- Create: `bot/bootstrap.py`

La fonction `build_core_services()` extrait les lignes ~64–168 de `main()` : config déjà passée en paramètre, DB déjà passée en paramètre. Elle initialise et retourne un `CoreServices` contenant tous les services core (sans les adapters Discord/Twitch ni les handlers d'actions).

- [ ] **Step 1 : Lire main.py lignes 48–170 pour prendre le code exact**

```bash
sed -n '48,170p' /opt/stacks/wally-ai/bot/main.py
```

- [ ] **Step 2 : Créer `bot/bootstrap.py`**

```python
# bot/bootstrap.py
"""
Wiring des services core — partagé par main.py et les tests d'intégration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.graph import GraphService
    from bot.core.llm.base import BaseLLMClient
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.core.journal import DailyJournal
    from bot.core.persona import PersonaService
    from bot.core.web_search import WebSearchService
    from bot.core.apex_api import ApexLegendsService
    from bot.core.actions import ActionRegistry, ActionScheduler, ActionExecutor, ActionService
    from bot.core.fact_extractor import FactExtractor
    from bot.core.reaction_tracker import ReactionTracker
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


@dataclass
class CoreServices:
    config: "Config"
    db: "Database"
    emotion: "EmotionEngine"
    memory: "MemoryService"
    graph: "GraphService"
    primary_llm: "BaseLLMClient"
    secondary_llm: "BaseLLMClient"
    image_client: "OpenAILLMClient"
    prompts: "PromptBuilder"
    language: "LanguageDetector"
    persona: "PersonaService"
    journal: "DailyJournal"
    action_registry: "ActionRegistry"
    action_executor: "ActionExecutor"
    action_scheduler: "ActionScheduler"
    action_service: "ActionService"
    fact_extractor: "FactExtractor"
    reaction_tracker: "ReactionTracker"
    web_search: "WebSearchService"
    apex_api: "ApexLegendsService"
    shared_scheduler: "AsyncIOScheduler"


async def build_core_services(config: "Config", db: "Database", qdrant_url: str) -> CoreServices:
    """Instancie tous les services core et retourne un CoreServices câblé."""
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.graph import GraphService
    from bot.core.llm import create_llm_client
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.core.journal import DailyJournal
    from bot.core.persona import PersonaService
    from bot.core.web_search import WebSearchService
    from bot.core.apex_api import ApexLegendsService
    from bot.core.actions import ActionRegistry, ActionScheduler, ActionExecutor, ActionService
    from bot.core.fact_extractor import FactExtractor
    from bot.core.reaction_tracker import ReactionTracker
    from bot.dashboard.routes.sse import broadcast_action_event
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    # ── EmotionEngine ─────────────────────────────────────────────────────────
    emotion = EmotionEngine(config, db=db)
    await emotion.load_state()
    emotion.start_decay_task()
    logger.info("EmotionEngine started with decay task")

    # ── MemoryService + GraphService ──────────────────────────────────────────
    memory = MemoryService(config)
    graph = GraphService(config)
    await graph.initialize()

    # ── LLM clients ───────────────────────────────────────────────────────────
    primary_llm = create_llm_client(config.llm.primary, db)
    secondary_llm = create_llm_client(config.llm.secondary, db)
    image_client = OpenAILLMClient(model=config.llm.primary.model, db=db)
    logger.info("LLM clients created — primary: {p}, secondary: {s}",
                p=type(primary_llm).__name__, s=type(secondary_llm).__name__)

    memory.set_openai_client(secondary_llm)
    memory.set_db(db)
    memory.set_graph(graph)
    await memory.load_aliases(db)
    emotion.set_openai_client(secondary_llm)
    logger.info("MemoryService and LLM clients initialized")

    # ── Optional services ─────────────────────────────────────────────────────
    web_search = WebSearchService(config, db)
    if web_search.available:
        logger.info("WebSearchService initialized (Tavily)")
    else:
        logger.warning("WebSearchService disabled — TAVILY_API_KEY missing or tavily-python not installed")

    apex_api = ApexLegendsService()
    if apex_api.available:
        logger.info("ApexLegendsService initialized")
    else:
        logger.warning("ApexLegendsService disabled — APEX_API_KEY missing")

    # ── Prompts, language, persona ────────────────────────────────────────────
    prompts = PromptBuilder()
    language = LanguageDetector(config.bot.language_default)
    persona = PersonaService()
    logger.info("PromptBuilder, LanguageDetector, and PersonaService initialized")

    # ── Journal ───────────────────────────────────────────────────────────────
    journal = DailyJournal(config, primary_llm, secondary_llm, emotion, memory, db=db)
    logger.info("DailyJournal initialized")

    # ── Shared scheduler + Action services ────────────────────────────────────
    shared_scheduler = AsyncIOScheduler()

    action_registry = ActionRegistry(db)
    await action_registry.load_permissions()

    action_executor = ActionExecutor(action_registry)
    action_scheduler = ActionScheduler(
        db, action_executor, shared_scheduler, on_change=broadcast_action_event
    )
    action_service = ActionService(action_registry, action_scheduler, db)
    logger.info("ActionService initialized")

    # ── FactExtractor + ReactionTracker ───────────────────────────────────────
    fact_extractor = FactExtractor(config, memory, secondary_llm, db=db, graph=graph)
    await fact_extractor.restore_buffers()
    logger.info("FactExtractor initialized")

    reaction_tracker = ReactionTracker(emotion, db)
    logger.info("ReactionTracker initialized")

    return CoreServices(
        config=config,
        db=db,
        emotion=emotion,
        memory=memory,
        graph=graph,
        primary_llm=primary_llm,
        secondary_llm=secondary_llm,
        image_client=image_client,
        prompts=prompts,
        language=language,
        persona=persona,
        journal=journal,
        action_registry=action_registry,
        action_executor=action_executor,
        action_scheduler=action_scheduler,
        action_service=action_service,
        fact_extractor=fact_extractor,
        reaction_tracker=reaction_tracker,
        web_search=web_search,
        apex_api=apex_api,
        shared_scheduler=shared_scheduler,
    )
```

- [ ] **Step 3 : Vérifier que le module s'importe**

```bash
cd /opt/stacks/wally-ai && python3 -c "from bot.bootstrap import CoreServices, build_core_services; print('OK')"
```

Attendu : `OK`

---

### Task 2 : Adapter `main()` pour utiliser `build_core_services()`

**Files:**
- Modify: `bot/main.py`

- [ ] **Step 1 : Lire main.py en entier pour avoir l'état exact**

```bash
cat -n /opt/stacks/wally-ai/bot/main.py
```

- [ ] **Step 2 : Remplacer le bloc core services dans `main()`**

Dans `main()`, remplacer tout le bloc depuis `# ── Core services ───` (ligne ~88) jusqu'à `logger.info("ReactionTracker initialized")` (ligne ~168) par :

```python
    from bot.bootstrap import build_core_services
    from bot.core.tracing import init_tracing, shutdown_tracing

    # ── Tracing ──────────────────────────────────────────────────────────────
    init_tracing()

    # ── Core services ─────────────────────────────────────────────────────────
    svc = await build_core_services(config, db, qdrant_url)
    emotion       = svc.emotion
    memory        = svc.memory
    graph         = svc.graph
    primary_llm   = svc.primary_llm
    secondary_llm = svc.secondary_llm
    image_client  = svc.image_client
    prompts       = svc.prompts
    language      = svc.language
    persona       = svc.persona
    journal       = svc.journal
    action_registry   = svc.action_registry
    action_executor   = svc.action_executor
    action_scheduler  = svc.action_scheduler
    action_service    = svc.action_service
    fact_extractor    = svc.fact_extractor
    reaction_tracker  = svc.reaction_tracker
    web_search        = svc.web_search
    apex_api          = svc.apex_api
    shared_scheduler  = svc.shared_scheduler
```

Supprimer aussi l'import `from bot.core.tracing import init_tracing, shutdown_tracing` qui était juste avant (il est maintenant dans le bloc ci-dessus).

Le reste de `main()` (adapter Discord/Twitch, action handlers, dashboard) reste inchangé.

- [ ] **Step 3 : Vérifier l'import de main.py**

```bash
cd /opt/stacks/wally-ai && python3 -c "import bot.main; print('OK')"
```

Attendu : `OK`

- [ ] **Step 4 : Vérifier que les tests existants passent toujours**

```bash
cd /opt/stacks/wally-ai && python3 -m pytest tests/ -x -q --ignore=tests/test_dashboard_costs.py 2>&1 | tail -5
```

Attendu : tous verts (au moins 1000 passed).

- [ ] **Step 5 : Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/bootstrap.py bot/main.py
git commit -m "refactor(main): extract build_core_services() to bootstrap.py"
```
