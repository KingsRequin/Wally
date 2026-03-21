# Global Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `global:server` memory namespace for community-level knowledge, searched in parallel with per-user memory on every request.

**Architecture:** New `add_global()` and `search_global()` methods on `MemoryService` use mem0 directly (bypassing consolidation/linker). `PromptBuilder` gets a new `global_memory_context` param. `FactExtractor` gains a `scope` field to classify facts as personal vs community. Dashboard gets CRUD endpoints + UI section.

**Tech Stack:** Python asyncio, mem0/Qdrant, FastAPI, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-21-global-memory-design.md`

---

### Task 1: `add_global()` and `search_global()` on MemoryService

**Files:**
- Modify: `bot/core/memory.py` (add constant + 2 methods)

- [ ] **Step 1: Add `GLOBAL_USER_ID` constant and `add_global()` method**

Add after line 36 (`_CONSOLIDATION_THRESHOLD = 25`):

```python
GLOBAL_USER_ID = "global:server"
```

Add `add_global()` method to `MemoryService` class, after `add()` (after line 174):

```python
async def add_global(self, content: str) -> None:
    """Store a community-level fact in the global namespace.

    Calls mem0.add() directly — bypasses consolidation, upsert_memory_user,
    and account_linker (not relevant for global facts).
    """
    self._init_mem0()
    if self._mem0 is None:
        return
    try:
        await asyncio.to_thread(
            self._mem0.add, content, user_id=GLOBAL_USER_ID,
            metadata={"origin": "global"},
        )
        logger.info("Global memory added: {c}", c=content[:80])
    except Exception as exc:
        logger.warning("Global memory add failed: {e}", e=exc)
```

- [ ] **Step 2: Add `search_global()` method**

Add after `add_global()`:

```python
async def search_global(self, query: str) -> str:
    """Search the global namespace for community-level knowledge.

    Single-query search (no dual-query with context).
    Applies _MIN_SEARCH_SCORE filtering. Returns newline-separated memories.
    """
    self._init_mem0()
    if self._mem0 is None:
        return ""
    if not query or not query.strip():
        return ""
    try:
        results = await asyncio.to_thread(
            self._mem0.search, query, user_id=GLOBAL_USER_ID, limit=5,
        )
        if isinstance(results, dict):
            results = results.get("results", [])
        memories = [
            r.get("memory", "")
            for r in results
            if r.get("memory") and r.get("score", 1.0) >= _MIN_SEARCH_SCORE
        ]
        return "\n".join(memories)
    except Exception as exc:
        logger.warning("Global memory search failed: {e}", e=exc)
        return ""
```

- [ ] **Step 3: Commit**

```bash
git add bot/core/memory.py
git commit -m "feat: add global memory namespace with add_global() and search_global()"
```

---

### Task 2: Update `PromptBuilder` to inject global memory context

**Files:**
- Modify: `bot/core/prompts.py:77-149` (`build_system_prompt` method)

- [ ] **Step 1: Add `global_memory_context` parameter**

In `build_system_prompt()` signature (line 77), add the new parameter:

```python
def build_system_prompt(
    self,
    emotion_state: dict[str, float],
    memory_context: str = "",
    global_memory_context: str = "",  # NEW
    situation: dict | None = None,
    persona_block: str = "",
    emotion_directives: dict[str, str] | None = None,
    weekday_directives: dict[str, str] | None = None,
    composite_directives: dict[str, str] | None = None,
) -> str:
```

- [ ] **Step 2: Add global memory section in prompt output**

After the existing memory_context block (lines 143-147), add:

```python
        # Global community memory
        if global_memory_context:
            parts.append(
                f"\n--- Connaissances générales (communauté) ---\n{global_memory_context}"
            )
```

- [ ] **Step 3: Commit**

```bash
git add bot/core/prompts.py
git commit -m "feat: add global_memory_context to system prompt builder"
```

---

### Task 3: Wire global memory search in Discord handler

**Files:**
- Modify: `bot/discord/handlers.py:271` (in `_respond()`)

- [ ] **Step 1: Replace sequential search with parallel user + global search**

Replace line 271:
```python
        mem_context = await bot.memory.search(platform, user_id, message.content, context_messages=prelude)
```

With:
```python
        mem_context, global_context = await asyncio.gather(
            bot.memory.search(platform, user_id, message.content, context_messages=prelude),
            bot.memory.search_global(message.content),
        )
```

- [ ] **Step 2: Pass `global_memory_context` to `build_system_prompt()`**

In the `build_system_prompt()` call (lines 331-339), add the new parameter:

```python
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            global_memory_context=global_context,  # NEW
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
```

- [ ] **Step 3: Commit**

```bash
git add bot/discord/handlers.py
git commit -m "feat: search global memory in parallel with user memory (Discord)"
```

---

### Task 4: Wire global memory search in Twitch handler

**Files:**
- Modify: `bot/twitch/handlers.py:102` (in `handle_message()`)

- [ ] **Step 1: Replace sequential search with parallel user + global search**

Replace line 102:
```python
        mem_context = await bot.memory.search(platform, user_id, content, context_messages=prelude)
```

With:
```python
        mem_context, global_context = await asyncio.gather(
            bot.memory.search(platform, user_id, content, context_messages=prelude),
            bot.memory.search_global(content),
        )
```

- [ ] **Step 2: Pass `global_memory_context` to `build_system_prompt()`**

In the `build_system_prompt()` call (lines 153-161), add the new parameter:

```python
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            global_memory_context=global_context,  # NEW
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
```

- [ ] **Step 3: Commit**

```bash
git add bot/twitch/handlers.py
git commit -m "feat: search global memory in parallel with user memory (Twitch)"
```

---

### Task 5: Update FactExtractor for community scope

**Files:**
- Modify: `bot/persona/prompts/fact_extraction_system.md`
- Modify: `bot/core/fact_extractor.py:76-118` (schema) + `bot/core/fact_extractor.py:368-400` (processing)

- [ ] **Step 1: Update the fact extraction system prompt**

Add a new section to `bot/persona/prompts/fact_extraction_system.md`, before the "## Ce que tu ignores" section:

```markdown
### Faits communautaires (scope: "community")
Certains faits ne concernent pas un individu mais la communauté entière :
- Liens et ressources partagés (URLs, sites, outils communs)
- Événements du serveur (tournois, streams, sorties de groupe)
- Règles ou habitudes du serveur
- Projets collectifs ou références récurrentes de la communauté

Pour ces faits, mets `target` à null, `target_user_id` à null, et `scope` à "community".

### Classification personal vs community
- **personal** : préférences individuelles, faits biographiques, opinions personnelles, habitudes d'un utilisateur
- **community** : tout ce qui concerne le groupe entier, pas un individu en particulier
- **En cas de doute** : choisis "personal" (plus sûr — évite de polluer l'espace global)
```

Also update the "## Règles" section to add:
```markdown
- Chaque entrée dans `facts` doit avoir un champ `scope` : "personal" (défaut) ou "community".
```

- [ ] **Step 2: Add `scope` field to `FACT_EXTRACTION_SCHEMA`**

In `bot/core/fact_extractor.py`, modify the schema items properties (lines 82-88). Add `scope` field:

```python
FACT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "target_user_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["personal", "community"],
                    },
                    "facts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["target", "target_user_id", "scope", "facts"],
                "additionalProperties": False,
            },
        },
        "aliases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nickname": {"type": "string"},
                    "resolved_to": {"type": "string"},
                    "resolved_user_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "nickname",
                    "resolved_to",
                    "resolved_user_id",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["facts", "aliases"],
    "additionalProperties": False,
}
```

Note: `target` also needs `null` support now (for community facts).

- [ ] **Step 3: Route community facts to `add_global()` in `_extract_facts()`**

In `_extract_facts()`, modify the fact processing loop (lines 368-400). Replace:

```python
        # Process facts
        for entry in result.get("facts", []):
            uid = entry.get("target_user_id")
            facts_list = entry.get("facts", [])
            if not facts_list:
                continue

            facts_text = "\n".join(f"- {f}" for f in facts_list)

            if uid:
```

With:

```python
        # Process facts
        for entry in result.get("facts", []):
            facts_list = entry.get("facts", [])
            if not facts_list:
                continue

            scope = entry.get("scope", "personal")
            facts_text = "\n".join(f"- {f}" for f in facts_list)

            # Community-scope facts → global namespace
            if scope == "community":
                try:
                    await self._memory.add_global(facts_text)
                    stored_count += 1
                except Exception as exc:
                    logger.warning("memory.add_global failed: {e}", e=exc)
                continue

            uid = entry.get("target_user_id")
            if uid:
```

The rest of the `if uid:` / `else:` block stays unchanged.

- [ ] **Step 4: Commit**

```bash
git add bot/core/fact_extractor.py bot/persona/prompts/fact_extraction_system.md
git commit -m "feat: FactExtractor classifies community vs personal facts"
```

---

### Task 6: Dashboard API endpoints for global memory

**Files:**
- Modify: `bot/dashboard/routes/memory.py` (add 4 endpoints)

- [ ] **Step 1: Add import for `GLOBAL_USER_ID`**

At the top of the file, add:

```python
from bot.core.memory import GLOBAL_USER_ID
```

- [ ] **Step 2: Add GET /memory/global endpoint**

Add after the existing endpoints (before the aliases section, around line 240):

```python
# ── Global memory CRUD ────────────────────────────────────────────────────────

@router.get("/memory/global")
async def list_global_memories(request: Request):
    """Liste toutes les mémoires globales (connaissances communauté)."""
    mem0 = _get_mem0(request)
    results = await asyncio.to_thread(mem0.get_all, user_id=GLOBAL_USER_ID)
    memories = [
        {
            "id": r.get("id"),
            "memory": r.get("memory", ""),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        }
        for r in _unwrap(results)
        if r.get("memory")
    ]
    memories.sort(
        key=lambda m: m.get("updated_at") or m.get("created_at") or "",
        reverse=True,
    )
    return {"memories": memories}
```

- [ ] **Step 3: Add POST /memory/global endpoint**

```python
@router.post("/memory/global")
async def add_global_memory(body: AddMemoryRequest, request: Request):
    """Ajoute une connaissance globale (communauté)."""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, detail="Contenu requis")
    state = request.app.state.wally
    await state.memory.add_global(content)
    return {"status": "ok"}
```

- [ ] **Step 4: Add PUT and DELETE endpoints**

```python
@router.put("/memory/global/{memory_id}")
async def update_global_memory(memory_id: str, body: UpdateMemoryRequest, request: Request):
    """Modifie une mémoire globale."""
    content = body.content.strip()
    if not content:
        raise HTTPException(400, detail="Contenu requis")
    mem0 = _get_mem0(request)
    await asyncio.to_thread(mem0.update, memory_id, content)
    logger.info("Global memory updated: {mid}", mid=memory_id)
    return {"status": "ok", "memory_id": memory_id}


@router.delete("/memory/global/{memory_id}")
async def delete_global_memory(memory_id: str, request: Request):
    """Supprime une mémoire globale."""
    mem0 = _get_mem0(request)
    await asyncio.to_thread(mem0.delete, memory_id)
    return {"deleted": True}
```

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/routes/memory.py
git commit -m "feat: add global memory CRUD endpoints to dashboard API"
```

---

### Task 7: Dashboard UI — Global memory section

**Files:**
- Modify: `bot/dashboard/static/app.js` (add global memory section in memory tab)
- Modify: `bot/dashboard/static/index.html` (if needed for markup)

This task requires reading the existing memory tab UI code to understand the patterns used, then adding a "Mémoire globale" section with:
- List of all global facts with edit/delete buttons
- Text input + "Ajouter" button
- Same styling as existing user memory management

- [ ] **Step 1: Read the existing memory tab code**

Read how the user memory list/add/edit/delete UI is built in `app.js` to follow the same patterns.

- [ ] **Step 2: Add `loadGlobalMemories()` function**

Add a function that fetches `GET /memory/global` and renders the list with edit/delete buttons. Follow the same card/list pattern as user memories.

- [ ] **Step 3: Add `addGlobalMemory()`, `editGlobalMemory()`, `deleteGlobalMemory()` functions**

Wire to `POST /memory/global`, `PUT /memory/global/{id}`, `DELETE /memory/global/{id}`.

- [ ] **Step 4: Add the global memory section to the memory tab**

Add a section before the user list with heading "Mémoire globale (communauté)" containing:
- Input field + "Ajouter" button
- List of existing global memories

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/static/app.js bot/dashboard/static/index.html
git commit -m "feat: add global memory management UI to dashboard"
```

---

### Task 8: Update dashboard Info tab

**Files:**
- Modify: `bot/dashboard/static/app.js:2719-2757` (Section 3: Mémoire in `renderJournalDetailTab()`)

- [ ] **Step 1: Update the memory section description**

In the Section 3 "Mémoire" of `renderJournalDetailTab()`, after the existing paragraph about "deux types de mémoire", add a paragraph about global memory:

After line 2729 (the paragraph about per-platform memory and linking), add:

```html
          <p><strong>La mémoire globale</strong> — des connaissances partagées par toute la communauté : liens importants, événements du serveur, ressources communes. Contrairement à la mémoire individuelle, ces faits sont consultés <strong>pour chaque requête</strong>, peu importe qui pose la question. Les administrateurs peuvent gérer ces connaissances via l'onglet « Mémoire » du dashboard, et le FactExtractor les détecte aussi automatiquement dans les conversations.</p>
```

Also update the first paragraph of that section (line 2726) to mention three types:

Replace:
```html
          <p>Wally a <strong>deux types de mémoire</strong>, comme un humain :</p>
```
With:
```html
          <p>Wally a <strong>trois types de mémoire</strong> :</p>
```

- [ ] **Step 2: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat: update info tab to document global memory"
```

---

### Task 9: Manual smoke test

- [ ] **Step 1: Start the bot and verify no startup errors**

```bash
docker compose up --build -d && docker compose logs -f wally --since 30s
```

Check for no import errors or crashes.

- [ ] **Step 2: Test dashboard global memory CRUD**

1. Open dashboard → Memory tab
2. Add a global memory: "Le lien de la fresque est https://example.com/fresque"
3. Verify it appears in the list
4. Edit it, verify change persists
5. Delete it, verify it's gone

- [ ] **Step 3: Test global memory retrieval**

1. Add a global memory via dashboard: "Le lien de la fresque est https://example.com/fresque"
2. Mention Wally on Discord: "c'est quoi le lien de la fresque?"
3. Verify Wally's response includes the link

- [ ] **Step 4: Verify info tab update**

Open dashboard → Info tab → Section 3 "Mémoire" → verify "trois types de mémoire" and global memory paragraph are present.
