# Global Memory Design

**Date:** 2026-03-21
**Status:** Approved

## Problem

Wally's long-term memory is strictly per-user (`discord:{user_id}` / `twitch:{user_id}`).
When a user asks "c'est quoi le lien de la fresque?", Wally searches only that user's
memories and finds nothing — the link was never stored as a personal fact about them.

Community-level knowledge (shared links, server rules, events, recurring topics) has
no storage mechanism and is lost.

## Solution

Add a `global:server` namespace in mem0/Qdrant for community knowledge. This namespace
is searched **in parallel** with the user namespace on every request. Facts are stored
there via:

1. **Manual entry** through the dashboard (CRUD)
2. **Automatic extraction** by the existing FactExtractor, which learns to classify
   facts as `personal` or `community`

## Architecture

### Constants

```python
# bot/core/memory.py
GLOBAL_USER_ID = "global:server"
```

### New Methods — `MemoryService`

```python
async def add_global(self, content: str) -> None:
    """Store a community-level fact in the global namespace."""
    # Delegates to self.add() with platform="global", user_id="server"

async def search_global(self, query: str) -> str:
    """Search global namespace. Returns newline-separated memories."""
    # Same logic as search() but with user_id=GLOBAL_USER_ID
    # No context_messages needed (global facts aren't conversation-dependent)
```

### Modified — `FactExtractor`

The structured extraction prompt gains a `scope` field per fact:

```json
{
  "facts": [
    {
      "target": "username",
      "target_user_id": "discord:123",
      "scope": "personal",
      "facts": ["aime le jazz"]
    },
    {
      "target": null,
      "target_user_id": null,
      "scope": "community",
      "facts": ["le lien de la fresque est https://example.com/fresque"]
    }
  ]
}
```

Facts with `scope: "community"` are stored via `memory.add_global()`.
Facts with `scope: "personal"` follow the existing path via `memory.add()`.

### Modified — `PromptBuilder.build_system_prompt()`

New parameter: `global_memory_context: str = ""`

Prompt structure:

```
...existing prompt sections...

--- Ce que tu sais de cet utilisateur ---
{memory_context}

--- Connaissances generales (communaute) ---
{global_memory_context}
```

The global section only appears when `global_memory_context` is non-empty.

### Modified — Discord `_respond()` / Twitch handler

```python
# Parallel search: user + global
mem_context, global_context = await asyncio.gather(
    bot.memory.search(platform, user_id, message.content, context_messages=prelude),
    bot.memory.search_global(message.content),
)

system_prompt = bot.prompts.build_system_prompt(
    ...,
    memory_context=mem_context,
    global_memory_context=global_context,
)
```

### New Dashboard Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/memory/global` | GET | List all global memories |
| `/memory/global` | POST | Add a global memory |
| `/memory/global/{memory_id}` | PUT | Edit a global memory |
| `/memory/global/{memory_id}` | DELETE | Delete a global memory |

### Dashboard UI

A "Memoire globale" section in the memory tab:
- List of all global facts with edit/delete buttons
- Text input + "Ajouter" button to add new facts
- Same styling as existing user memory management

## Data Flow

```
Message arrives
    |
    +---> memory.search(platform, user_id, query)     --> user memories
    |                                                       |
    +---> memory.search_global(query)                  --> global memories
                                                            |
    build_system_prompt(                                    |
        memory_context=user,           <--------------------+
        global_memory_context=global,
    )
```

## Automatic Extraction Flow

```
FactExtractor._extract_facts()
    |
    +-- scope: "personal"   --> memory.add(platform, user_id, ...)
    |
    +-- scope: "community"  --> memory.add_global(...)
        (links, server info, events, rules, shared resources)
```

## What Does NOT Change

- Memory consolidation (per-user only; global memories are curated, not auto-consolidated)
- Alias system
- Trust/love scores
- `/wally memory` Discord command
- Context window / prelude system
- Existing `search()` method signature and behavior

## Files Modified

| File | Change |
|------|--------|
| `bot/core/memory.py` | Add `GLOBAL_USER_ID`, `add_global()`, `search_global()` |
| `bot/core/fact_extractor.py` | Add `scope` field to extraction schema + routing |
| `bot/core/prompts.py` | Add `global_memory_context` param to `build_system_prompt()` |
| `bot/discord/handlers.py` | Parallel search user+global in `_respond()` |
| `bot/twitch/handlers.py` | Same parallel search |
| `bot/dashboard/routes/memory.py` | 4 new global memory endpoints |
| `bot/dashboard/static/app.js` | Global memory UI section |
| `bot/dashboard/static/index.html` | Global memory tab/section markup |

## Edge Cases

- **Qdrant unavailable:** `search_global()` returns empty string, same graceful degradation as `search()`
- **Duplicate global facts:** mem0's deduplication handles this (same as per-user)
- **FactExtractor ambiguity:** When unsure if a fact is personal or community, default to personal (safer — avoids polluting global namespace)
