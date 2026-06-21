# Code Cleanup & Restructuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nettoyer le code mort, supprimer le dossier `bot/v2/` en le remplaçant par `bot/intelligence/`, et déplacer les fichiers LLM-dépendants de `bot/core/` vers `bot/intelligence/` pour un codebase propre et maintenable.

**Architecture:** Deux espaces de nommage clairs après restructuration : `bot/core/` pour les primitives sans LLM (config, DB, émotion, LLM-client lui-même) et `bot/intelligence/` pour tout ce qui raisonne via LLM (boucle cognitive, agents, mémoire sémantique, persona, prompts, actions, journal, fact_extractor). Les adaptateurs `discord/`, `twitch/` et `dashboard/` ne bougent pas.

**Tech Stack:** Python 3.11, aiosqlite, loguru, pytest

## Global Constraints

- Toujours utiliser `git mv` pour les déplacements de fichiers (préserve l'historique)
- Ne jamais toucher `bot/discord/`, `bot/twitch/`, `bot/dashboard/`, `bot/db/` (sauf ajout de `schema_v2.py`)
- `bot/core/` résiduel après restructuration : `llm/`, `emotion.py`, `language.py`, `update_checker.py`, `reaction_tracker.py`, `notifications.py`, `web_search.py`, `account_linker.py`, `apex_api.py`
- Après chaque passe, la suite de tests complète doit être verte : `pytest tests/ -x -q`
- Un commit par passe

---

## Task 1 : Passe 1 — Dead code

**Files:**
- Delete: `bot/core/openai_client.py`
- Delete: `scripts/migrate_mem0_to_qdrant.py`
- Modify: `tests/test_web_search.py` (corriger l'import du shim)
- Verify stale string: `tests/test_dashboard_logs.py` (string littéral à vérifier)

**Interfaces:**
- Produit : rien de nouveau, retire du code mort

- [ ] **Step 1 : Lire les fichiers concernés**

```bash
head -15 /opt/stacks/wally-ai/tests/test_web_search.py
grep -n "openai_client" /opt/stacks/wally-ai/tests/test_dashboard_logs.py
```

- [ ] **Step 2 : Corriger l'import dans test_web_search.py**

Remplacer dans `tests/test_web_search.py` :
```python
# AVANT
from bot.core.openai_client import OpenAIClient, FALLBACK_RESPONSE
```
```python
# APRÈS
from bot.core.llm.openai_client import OpenAILLMClient as OpenAIClient
from bot.core.llm.base import FALLBACK_RESPONSE
```

- [ ] **Step 3 : Supprimer les fichiers dead**

```bash
cd /opt/stacks/wally-ai
git rm bot/core/openai_client.py
git rm scripts/migrate_mem0_to_qdrant.py
```

- [ ] **Step 4 : Vérifier qu'aucun autre fichier n'importe le shim**

```bash
grep -rn "from bot\.core\.openai_client\|from core\.openai_client" /opt/stacks/wally-ai/ --include="*.py" | grep -v "__pycache__"
```

Résultat attendu : aucune ligne (0 résultats).

- [ ] **Step 5 : Lancer les tests ciblés**

```bash
cd /opt/stacks/wally-ai && pytest tests/test_web_search.py tests/test_dashboard_logs.py -v
```

Attendu : tous verts.

- [ ] **Step 6 : Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai && pytest tests/ -x -q
```

Attendu : même baseline qu'avant (1010 verts, 2 échecs préexistants non liés).

- [ ] **Step 7 : Commit**

```bash
cd /opt/stacks/wally-ai
git add tests/test_web_search.py
git commit -m "refactor: remove dead openai_client shim and mem0 migration script"
```

---

## Task 2 : Passe 2 — Renommer bot/v2/ → bot/intelligence/

**Files:**
- Create dir: `bot/intelligence/` et `bot/intelligence/memory/`
- git mv: tous les fichiers de `bot/v2/core/` → `bot/intelligence/`
- git mv: `bot/v2/core/memory/` → `bot/intelligence/memory/`
- git mv: `bot/v2/db/schema_v2.py` → `bot/db/schema_v2.py`
- Create: `bot/intelligence/__init__.py` et `bot/intelligence/memory/__init__.py`
- git mv: `tests/v2/` → `tests/intelligence/`
- Modify (sed): tous les fichiers `.py` du projet pour substituer les chemins d'import

**Interfaces:**
- Consomme : le contenu de `bot/v2/`
- Produit : `bot/intelligence/` avec les mêmes fichiers, imports mis à jour

- [ ] **Step 1 : Créer les __init__.py**

```bash
touch /opt/stacks/wally-ai/bot/intelligence/__init__.py
touch /opt/stacks/wally-ai/bot/intelligence/memory/__init__.py
```

- [ ] **Step 2 : Déplacer les fichiers de v2/core/ → intelligence/**

```bash
cd /opt/stacks/wally-ai
git mv bot/v2/core/action_dispatcher.py   bot/intelligence/action_dispatcher.py
git mv bot/v2/core/attention_agent.py     bot/intelligence/attention_agent.py
git mv bot/v2/core/channels.py            bot/intelligence/channels.py
git mv bot/v2/core/cognitive_feed.py      bot/intelligence/cognitive_feed.py
git mv bot/v2/core/cognitive_loop.py      bot/intelligence/cognitive_loop.py
git mv bot/v2/core/emotional_drive.py     bot/intelligence/emotional_drive.py
git mv bot/v2/core/evolution_log.py       bot/intelligence/evolution_log.py
git mv bot/v2/core/gate.py                bot/intelligence/gate.py
git mv bot/v2/core/host_bridge.py         bot/intelligence/host_bridge.py
git mv bot/v2/core/inner_monologue.py     bot/intelligence/inner_monologue.py
git mv bot/v2/core/meta_agent.py          bot/intelligence/meta_agent.py
git mv bot/v2/core/persona_manager.py     bot/intelligence/persona_manager.py
git mv bot/v2/core/reasoning_agent.py     bot/intelligence/reasoning_agent.py
git mv bot/v2/core/self_fix.py            bot/intelligence/self_fix.py
git mv bot/v2/core/self_upgrade.py        bot/intelligence/self_upgrade.py
```

- [ ] **Step 3 : Déplacer le sous-dossier memory/**

```bash
cd /opt/stacks/wally-ai
git mv bot/v2/core/memory/facts.py       bot/intelligence/memory/facts.py
git mv bot/v2/core/memory/ingest.py      bot/intelligence/memory/ingest.py
git mv bot/v2/core/memory/retrieval.py   bot/intelligence/memory/retrieval.py
git mv bot/v2/core/memory/vocab.py       bot/intelligence/memory/vocab.py
```

- [ ] **Step 4 : Déplacer schema_v2.py dans bot/db/**

```bash
cd /opt/stacks/wally-ai
git mv bot/v2/db/schema_v2.py bot/db/schema_v2.py
```

- [ ] **Step 5 : Supprimer les répertoires v2/ désormais vides**

```bash
cd /opt/stacks/wally-ai
git rm bot/v2/core/memory/__init__.py bot/v2/core/__init__.py bot/v2/db/__init__.py bot/v2/__init__.py 2>/dev/null || true
rmdir -p bot/v2/core/memory bot/v2/core bot/v2/db bot/v2 2>/dev/null || true
```

- [ ] **Step 6 : Déplacer les tests v2/ → tests/intelligence/**

```bash
cd /opt/stacks/wally-ai
git mv tests/v2 tests/intelligence
```

- [ ] **Step 7 : Substitution des imports — bot.v2.core.* → bot.intelligence.***

```bash
cd /opt/stacks/wally-ai
find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.v2\.core\./from bot.intelligence./g'
find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/import bot\.v2\.core\./import bot.intelligence./g'
```

- [ ] **Step 8 : Substitution des imports — bot.v2.db.schema_v2 → bot.db.schema_v2**

```bash
cd /opt/stacks/wally-ai
find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.v2\.db\.schema_v2/from bot.db.schema_v2/g'
find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/import bot\.v2\.db\.schema_v2/import bot.db.schema_v2/g'
```

- [ ] **Step 9 : Vérifier qu'aucune référence à bot.v2 ne subsiste**

```bash
grep -rn "bot\.v2\|from bot\.v2\|import bot\.v2" /opt/stacks/wally-ai/ --include="*.py" | grep -v "__pycache__"
```

Résultat attendu : aucune ligne.

- [ ] **Step 10 : Lancer les tests**

```bash
cd /opt/stacks/wally-ai && pytest tests/ -x -q
```

Attendu : même baseline qu'avant.

- [ ] **Step 11 : Commit**

```bash
cd /opt/stacks/wally-ai
git add -A
git commit -m "refactor: rename bot/v2/ → bot/intelligence/ (passe 2)"
```

---

## Task 3 : Passe 3 — Déplacer les fichiers LLM-dépendants de core/ → intelligence/

**Files:**
- git mv: `bot/core/fact_extractor.py` → `bot/intelligence/fact_extractor.py`
- git mv: `bot/core/journal.py` → `bot/intelligence/journal.py`
- git mv: `bot/core/persona.py` → `bot/intelligence/persona.py`
- git mv: `bot/core/prompts.py` → `bot/intelligence/prompts.py`
- git mv: `bot/core/memory.py` → `bot/intelligence/memory/service.py`
- git mv: `bot/core/actions/` → `bot/intelligence/actions/`
- Modify (sed): tous les fichiers `.py` du projet pour substituer les chemins d'import
- Modify: `bot/intelligence/actions/__init__.py` (chemins internes)

**Interfaces:**
- Consomme : résultat de la Passe 2 (`bot/intelligence/` existe déjà)
- Produit : `bot/core/` ne contient plus que des primitives sans LLM

- [ ] **Step 1 : Déplacer les fichiers unitaires**

```bash
cd /opt/stacks/wally-ai
git mv bot/core/fact_extractor.py bot/intelligence/fact_extractor.py
git mv bot/core/journal.py        bot/intelligence/journal.py
git mv bot/core/persona.py        bot/intelligence/persona.py
git mv bot/core/prompts.py        bot/intelligence/prompts.py
git mv bot/core/memory.py         bot/intelligence/memory/service.py
```

- [ ] **Step 2 : Déplacer le dossier actions/**

```bash
cd /opt/stacks/wally-ai
git mv bot/core/actions/executor.py   bot/intelligence/actions/executor.py
git mv bot/core/actions/registry.py   bot/intelligence/actions/registry.py
git mv bot/core/actions/scheduler.py  bot/intelligence/actions/scheduler.py
git mv bot/core/actions/service.py    bot/intelligence/actions/service.py
git mv bot/core/actions/__init__.py   bot/intelligence/actions/__init__.py
rmdir bot/core/actions 2>/dev/null || true
```

- [ ] **Step 3 : Corriger bot/intelligence/actions/__init__.py**

```bash
cat /opt/stacks/wally-ai/bot/intelligence/actions/__init__.py
```

Remplacer les imports internes stale :
```bash
cd /opt/stacks/wally-ai
sed -i 's/from bot\.core\.actions\./from bot.intelligence.actions./g' \
  bot/intelligence/actions/__init__.py
```

- [ ] **Step 4 : Substitution — bot.core.memory → bot.intelligence.memory.service**

`memory.py` s'appelle maintenant `service.py` dans `intelligence/memory/`.

```bash
cd /opt/stacks/wally-ai
find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.core\.memory import/from bot.intelligence.memory.service import/g'
```

- [ ] **Step 5 : Substitutions — autres fichiers déplacés**

```bash
cd /opt/stacks/wally-ai
find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.core\.persona\b/from bot.intelligence.persona/g'

find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.core\.prompts\b/from bot.intelligence.prompts/g'

find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.core\.fact_extractor\b/from bot.intelligence.fact_extractor/g'

find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.core\.journal\b/from bot.intelligence.journal/g'

find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.core\.actions import/from bot.intelligence.actions import/g'

find . -name "*.py" -not -path "./__pycache__/*" -not -path "./.git/*" | \
  xargs sed -i 's/from bot\.core\.actions\./from bot.intelligence.actions./g'
```

- [ ] **Step 6 : Vérifier les références résiduelles aux fichiers déplacés**

```bash
grep -rn \
  "bot\.core\.memory\b\|bot\.core\.persona\b\|bot\.core\.prompts\b\|bot\.core\.fact_extractor\b\|bot\.core\.journal\b\|bot\.core\.actions\b" \
  /opt/stacks/wally-ai/ --include="*.py" | grep -v "__pycache__"
```

Résultat attendu : aucune ligne.

- [ ] **Step 7 : Vérifier le contenu résiduel de core/**

```bash
ls /opt/stacks/wally-ai/bot/core/
```

Attendu : `__init__.py  llm/  emotion.py  language.py  update_checker.py  reaction_tracker.py  notifications.py  web_search.py  account_linker.py  apex_api.py`

- [ ] **Step 8 : Lancer les tests**

```bash
cd /opt/stacks/wally-ai && pytest tests/ -x -q
```

Attendu : même baseline qu'avant.

- [ ] **Step 9 : Commit**

```bash
cd /opt/stacks/wally-ai
git add -A
git commit -m "refactor: migrate LLM-dependent files from core/ to intelligence/ (passe 3)"
```

---

## Task 4 : Passe 4 — Mettre à jour la documentation

**Files:**
- Modify: `CLAUDE.md` (section Directory Structure + supprimer mentions fichiers disparus)
- Modify: `README.md` (références à la structure du projet)

**Interfaces:**
- Consomme : état final du codebase après Passes 1-3
- Produit : documentation cohérente avec la nouvelle structure

- [ ] **Step 1 : Identifier les sections à corriger dans CLAUDE.md**

```bash
grep -n "sessions\.py\|memory_store\.py\|bot/v2\|core/memory\|core/persona\|core/prompts\|core/fact_extractor\|core/journal\|core/actions\|Directory Structure" \
  /opt/stacks/wally-ai/CLAUDE.md | head -40
```

- [ ] **Step 2 : Remplacer la section Directory Structure dans CLAUDE.md**

Remplacer l'intégralité du bloc entre les marqueurs ` ```\nbot/` et la fermeture ` ``` ` par :

```
bot/
├── main.py              # Entry point, DI wiring, asyncio.gather()
├── bootstrap.py         # Service construction, DI injection
├── config.py            # Config singleton, hot-reload, config.save()
├── core/                # Primitives sans LLM
│   ├── llm/             # Couche LLM (base, deepseek, openai_client pour images, factory)
│   ├── emotion.py       # Global emotion state, decay, NRCLex analysis
│   ├── language.py      # langdetect wrapper with fallback
│   ├── reaction_tracker.py
│   ├── update_checker.py
│   ├── notifications.py
│   ├── web_search.py
│   ├── account_linker.py
│   └── apex_api.py
├── intelligence/        # Tout ce qui raisonne via LLM
│   ├── memory/          # Mémoire sémantique (FTS5/SQLite)
│   │   ├── service.py   # MemoryService: sliding context window, search, consolidation
│   │   ├── facts.py     # SQLiteFactStore: faits S-P-O, AtomicFact
│   │   ├── ingest.py    # MemoryIngest: dédup live, réconciliation 2 étages
│   │   ├── retrieval.py # MemoryRetrieval: retrieval Generative-Agents
│   │   └── vocab.py     # Vocabulaire fermé de prédicats
│   ├── actions/         # ActionService: tâches planifiées via tool calling
│   │   ├── registry.py
│   │   ├── scheduler.py
│   │   ├── executor.py
│   │   └── service.py
│   ├── cognitive_loop.py   # Boucle cognitive (tick, idle, ATTN/THINK/DECIDE/SPEAK)
│   ├── cognitive_feed.py   # CognitiveFeed: fan-out SSE
│   ├── reasoning_agent.py  # ReasoningAgent: génération de réponses
│   ├── attention_agent.py  # AttentionAgent: scoring d'attention
│   ├── action_dispatcher.py
│   ├── gate.py             # ResponseGate: décision de répondre
│   ├── channels.py         # ChannelDirectory
│   ├── emotional_drive.py
│   ├── evolution_log.py
│   ├── inner_monologue.py
│   ├── meta_agent.py
│   ├── persona_manager.py
│   ├── persona.py          # PersonaService: chargement SOUL/IDENTITY/VOICE/EMOTIONS
│   ├── prompts.py          # PromptBuilder, load_prompt(), emotion directives
│   ├── fact_extractor.py   # FactExtractor: extraction de faits mémorables
│   ├── journal.py          # DailyJournal: journal quotidien (apscheduler)
│   ├── self_fix.py
│   ├── self_upgrade.py
│   └── host_bridge.py
├── discord/
│   ├── bot.py
│   ├── handlers.py
│   └── commands/
├── persona/             # Fichiers persona Markdown + prompts/
├── twitch/
│   ├── bot.py
│   ├── events/
│   └── handlers.py
└── db/
    ├── database.py      # aiosqlite: schema init + query helpers
    ├── schema_v2.py     # DDL tables intelligence (atomic_facts, thoughts...)
    └── mixins/
```

- [ ] **Step 3 : Supprimer les mentions de fichiers disparus dans CLAUDE.md**

Retirer toute ligne mentionnant `sessions.py`, `memory_store.py`, `core/openai_client.py` (le shim).
Mettre à jour les imports d'exemple dans la section `## Memory System` :
- `from bot.v2.core.memory.*` → `from bot.intelligence.memory.*`
- `from bot.core.memory import MemoryService` → `from bot.intelligence.memory.service import MemoryService`

- [ ] **Step 4 : Identifier les sections à corriger dans README.md**

```bash
grep -n "v2\|core/\|architecture\|structure\|intelligence" /opt/stacks/wally-ai/README.md | head -30
```

- [ ] **Step 5 : Mettre à jour README.md**

Remplacer toute référence à `bot/v2/` par `bot/intelligence/`, et toute référence aux anciens chemins (`bot/core/persona`, `bot/core/prompts`, etc.) par leurs nouveaux emplacements dans `bot/intelligence/`.

- [ ] **Step 6 : Lancer les tests une dernière fois**

```bash
cd /opt/stacks/wally-ai && pytest tests/ -x -q
```

Attendu : même baseline qu'avant.

- [ ] **Step 7 : Commit final**

```bash
cd /opt/stacks/wally-ai
git add CLAUDE.md README.md
git commit -m "docs: update CLAUDE.md and README.md for new intelligence/ structure"
```

---

## Self-Review

**Couverture spec :**
- ✅ Passe 1 : dead code (shim openai_client.py + migrate script) → Task 1
- ✅ Passe 2 : v2/ → intelligence/ (git mv + sed) → Task 2
- ✅ Passe 3 : core/ LLM files → intelligence/ (git mv + sed) → Task 3
- ✅ Passe 4 : CLAUDE.md + README.md → Task 4

**Placeholders :** aucun TBD ni TODO.

**Cohérence des types :** `MemoryService` vient de `bot.intelligence.memory.service` après déplacement, `PromptBuilder` de `bot.intelligence.prompts`, `PersonaService` de `bot.intelligence.persona` — cohérent dans tous les steps.

**Risques connus :**
- Les imports internes dans les fichiers déplacés (ex: `fact_extractor.py` importe `from bot.core.prompts`) sont couverts par les sed de la Passe 3
- `tests/test_dashboard_logs.py` contient `"bot.core.openai_client:55"` comme string littéral dans un test de parsing de log — ce n'est pas un import, la string sera stale mais le test continuera de passer
