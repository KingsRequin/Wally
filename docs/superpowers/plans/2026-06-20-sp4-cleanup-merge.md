# SP4 — Cleanup + Merge wally_v2 → bot/v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Supprimer le code mort accumulé par SP1-SP2, puis fusionner le package `wally_v2/` dans `bot/v2/` pour une arbo unique cohérente.

**Architecture:** Deux temps. (A) Nettoyage dead-code (sûr, isolé). (B) Renommage de package atomique `wally_v2` → `bot.v2` : transform uniforme des imports + refs Path + Dockerfile, vérifié par grep exhaustif.

**Tech Stack:** Python 3.12, pytest, Docker.

## Global Constraints

- python = `python3`. loguru only.
- Le renommage de package est ATOMIQUE : tout `wally_v2` → `bot.v2` en une tâche, pas de demi-état.
- `GLOBAL_USER_ID` (bot/core/memory.py:26) est ENCORE utilisé par `bot/db/mixins/memory.py:189` → NE PAS le supprimer sans nettoyer aussi ce consommateur. Vérifier avant suppression.
- NO SEMANTIC SEARCH : grep séparé pour chaque symbole/chemin.
- Après chaque tâche : suite ciblée + (tâche B) rebuild + démarrage.
- Base SP4 : HEAD courant (7b6c422).

---

### Task A1: Supprimer le dead-code dépendances mémoire

**Files:**
- Modify: `bot/discord/handlers.py` (retirer `_memory_check_cooldowns`)
- Modify: `bot/core/prompts.py` (retirer param `global_memory_context`)
- Modify: `bot/core/memory.py` + `bot/db/mixins/memory.py` (GLOBAL_USER_ID : voir ci-dessous)

- [ ] **Step 1: `_memory_check_cooldowns`** — dans `bot/discord/handlers.py`, supprimer la ligne `_memory_check_cooldowns: dict[str, float] = {}` (≈169) après avoir confirmé par grep qu'elle n'est plus lue/écrite : `grep -n "_memory_check_cooldowns" bot/discord/handlers.py` → seule la déclaration.

- [ ] **Step 2: `global_memory_context`** — dans `bot/core/prompts.py`, retirer le paramètre `global_memory_context` de `build_system_prompt` (signature ≈138) et son usage (≈262-264). Grep d'abord : `grep -rn "global_memory_context" bot/ | grep -v __pycache__` → confirmer qu'aucun appelant ne le passe (SP2 l'a retiré des call sites).

- [ ] **Step 3: `GLOBAL_USER_ID`** — grep `grep -rn "GLOBAL_USER_ID" bot/ wally_v2/ --include="*.py" | grep -v __pycache__`. Il est utilisé dans `bot/db/mixins/memory.py:189` (`if uid == GLOBAL_USER_ID`). Ce code (sync_memory_users) filtre l'ancien user global. Comme la mémoire globale est supprimée, retirer la branche `if uid == GLOBAL_USER_ID: continue/skip` dans db/mixins ET la constante dans memory.py. Si la branche db/mixins est plus complexe, la simplifier proprement. Si incertain, LAISSER la constante (inoffensive) et ne retirer que ce qui est sûr — documenter.

- [ ] **Step 4: Vérif + commit**

Run: `python3 -c "import bot.discord.handlers, bot.core.prompts, bot.core.memory, bot.db.mixins.memory; print('ok')"` → ok
Run: `python3 -m pytest tests/test_discord_handlers.py tests/test_memory_v2_facade.py -q` → pas de nouvelle casse.
```bash
git add -A && git commit -m "refactor(sp4): remove dead memory code (_memory_check_cooldowns, global_memory_context, GLOBAL_USER_ID)"
```

---

### Task A2: Nettoyer le champ `scope` mort + cost_usd embeddings

**Files:**
- Modify: `bot/core/fact_extractor.py` (retirer `scope` du schéma tool si totalement ignoré)
- Modify: `bot/core/embeddings.py` (calculer cost_usd réel ou documenter)

- [ ] **Step 1: champ `scope`** — dans `bot/core/fact_extractor.py` (≈161,181), le champ `scope` du schéma LLM n'est plus traité (branche community retirée en SP2). Le retirer du schéma + de tout prompt qui le mentionne. Grep `grep -n "scope" bot/core/fact_extractor.py` pour confirmer aucun usage runtime restant.

- [ ] **Step 2: cost_usd embeddings** — dans `bot/core/embeddings.py`, `cost_usd=0.0` est codé en dur. text-embedding-3-small = $0.02/1M tokens. Calculer : `cost_usd = (tokens / 1_000_000) * 0.02`. Garder le reste (purpose, cache).

- [ ] **Step 3: Vérif + commit**

Run: `python3 -m pytest tests/test_embeddings.py -q` (adapter le test si l'assertion cost change ; le test actuel ne vérifie pas cost_usd précis) → pass.
```bash
git add -A && git commit -m "refactor(sp4): drop dead scope field, compute real embedding cost"
```

---

### Task B1: Renommer le package wally_v2 → bot/v2 (ATOMIQUE)

**Files:** déplacement `wally_v2/` → `bot/v2/` + transform imports dans bot/ (4 fichiers) + tests/ (17 fichiers) + interne bot/v2/ (19 fichiers) + 2 Path refs + Dockerfile.

- [ ] **Step 1: Déplacer le package**

```bash
git mv wally_v2 bot/v2
```

- [ ] **Step 2: Transform tous les imports `wally_v2` → `bot.v2`**

Remplacer dans TOUT le repo (.py) les occurrences `wally_v2` (module) par `bot.v2` :
```bash
grep -rl "wally_v2" --include="*.py" bot/ tests/ | grep -v __pycache__ | xargs sed -i 's/wally_v2/bot.v2/g'
```
ATTENTION : ce sed transforme aussi d'éventuels chemins string `"wally_v2"` en `"bot.v2"` — INCORRECT pour les Path. Donc APRÈS le sed, corriger les refs Path (Step 3). Vérifier qu'aucune autre string littérale `wally_v2` non-import n'a été cassée (grep `bot.v2` dans des contextes Path/chemin).

- [ ] **Step 3: Corriger les refs Path dans `bot/discord/bot.py`**

Les 2 lignes (≈100,118) référençaient `Path(__file__).parent.parent.parent / "wally_v2" / "persona" / "prompts"`. Le sed a pu produire `"bot.v2"`. Les remplacer par le chemin correct vers le nouveau dossier : depuis `bot/discord/bot.py`, `Path(__file__).parent.parent / "v2" / "persona" / "prompts"` (`.parent.parent` = `bot/`, puis `v2/persona/prompts`). Vérifier que le dossier `bot/v2/persona/prompts/` existe bien après le git mv.

- [ ] **Step 4: Dockerfile**

Retirer la ligne `COPY wally_v2/ ./wally_v2/` (le package est maintenant sous `bot/`, déjà copié par `COPY bot/ ./bot/`).

- [ ] **Step 5: Grep exhaustif — zéro résidu**

```bash
grep -rn "wally_v2" --include="*.py" . | grep -v __pycache__       # → zéro
grep -rn "wally_v2" Dockerfile docker-compose.yml                  # → zéro
grep -rn "\"v2\"\|'v2'" bot/discord/bot.py                          # → confirmer Path refs correctes
```

- [ ] **Step 6: Imports + suite V2**

Run: `python3 -c "import bot.v2.core.gate, bot.v2.core.cognitive_loop, bot.v2.core.memory.facts, bot.v2.db.schema_v2; print('ok')"` → ok
Run: `python3 -c "import bot.bootstrap, bot.discord.bot, bot.core.memory; print('ok')"` → ok
Run: `python3 -m pytest tests/v2/ tests/test_memory_v2_facade.py tests/test_embeddings.py -q` → pass (même compte qu'avant le rename).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(sp4): merge wally_v2 package into bot/v2"
```

---

### Task B2: Vérification d'intégration finale

- [ ] **Step 1: Grep global**

```bash
grep -rn "wally_v2" . --include="*.py" | grep -v __pycache__ | grep -v "\.git"
grep -rn "wally_v2" Dockerfile docker-compose.yml
```
Expected: zéro partout.

- [ ] **Step 2: Suite complète — comparer au base SP4**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -3`
Expected: même profil qu'avant SP4 (3 fails + 16 errors pré-existants ; aucune NOUVELLE casse due au rename/cleanup).

- [ ] **Step 3: Rebuild + restart**

```bash
docker compose build wally && docker compose up -d --force-recreate wally
```

- [ ] **Step 4: Startup logs**

Run: `sleep 10 && docker logs wally-bot --since 40s 2>&1 | grep -iE "backend V2|ResponseGate|CognitiveLoop|ERROR|Traceback|ImportError|ready as"`
Expected: MemoryService backend V2 prêt, ResponseGate + CognitiveLoop up, bot ready, AUCUN ImportError (le rename de package est le risque #1 ici).

- [ ] **Step 5: Commit final si correctifs**

```bash
git add -A && git commit -m "refactor(sp4): final integration cleanup"
```

---

## Self-Review

**Spec coverage :** dead-code (A1+A2) ; merge package (B1) ; vérif (B2). ✓
**Risque #1 :** le rename casse les imports à l'exécution — couvert par B1 Step 6 (import sanity) + B2 Step 4 (startup). Le sed sur chemins string Path est le piège — couvert par B1 Step 3.
**Atomicité :** B1 fait tout le rename en une tâche/commit — pas de demi-état.
