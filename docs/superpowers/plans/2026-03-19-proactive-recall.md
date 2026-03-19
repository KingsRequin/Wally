# Recall proactif — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une 2e recherche mémoire parallèle basée sur le contexte conversationnel récent, pour retrouver des souvenirs pertinents même quand le message direct de l'utilisateur n'a pas de rapport sémantique.

**Architecture:** Étendre `MemoryService.search()` avec un paramètre optionnel `context_messages`. Quand fourni, deux recherches mem0 sont lancées en parallèle et les résultats dédupliqués. Les callers Discord et Twitch passent le prelude.

**Tech Stack:** Python 3.11+, pytest, asyncio, mem0

**Spec:** `docs/superpowers/specs/2026-03-19-proactive-recall-design.md`

---

### Task 1: Étendre `search()` dans memory.py + tests

**Files:**
- Modify: `bot/core/memory.py:246-278` (méthode `search`)
- Create: `tests/test_proactive_recall.py`

- [ ] **Step 1: Créer les tests**

Créer `tests/test_proactive_recall.py` :

```python
# tests/test_proactive_recall.py
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from bot.core.memory import MemoryService


def make_config():
    config = MagicMock()
    config.bot.context_window_size = 20
    config.bot.context_token_threshold = 3000
    config.bot.prelude_window_size = 15
    config.openai.secondary_model = "gpt-4o-mini"
    return config


def make_mem0_results(memories: list[str], scores: list[float] | None = None):
    """Helper to build mem0-style results."""
    if scores is None:
        scores = [0.8] * len(memories)
    return {"results": [
        {"memory": m, "score": s} for m, s in zip(memories, scores)
    ]}


@pytest.mark.asyncio
async def test_search_with_context_makes_two_queries():
    """Avec context_messages, mem0.search est appelé 2 fois."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["souvenir1"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    context = [
        {"author": "Alice", "content": "je parle de mon chat"},
        {"author": "Bob", "content": "il est mignon"},
    ]
    result = await svc.search("discord", "123", "il fait beau", context_messages=context)

    assert mock_mem0.search.call_count == 2


@pytest.mark.asyncio
async def test_search_with_context_deduplicates():
    """Les deux recherches retournent le même souvenir → dédupliqué."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["Alice a un chat"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    context = [{"author": "Alice", "content": "mon chat dort"}]
    result = await svc.search("discord", "123", "il fait beau", context_messages=context)

    # Le souvenir ne doit apparaître qu'une fois malgré 2 recherches
    assert result.count("Alice a un chat") == 1


@pytest.mark.asyncio
async def test_search_without_context_unchanged():
    """Sans context_messages, une seule recherche (comportement existant)."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["souvenir"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    result = await svc.search("discord", "123", "salut")

    assert mock_mem0.search.call_count == 1
    assert "souvenir" in result


@pytest.mark.asyncio
async def test_search_context_excludes_wally_messages():
    """Les messages de Wally ne sont pas inclus dans la query contextuelle."""
    svc = MemoryService(make_config())
    calls = []

    def capture_search(query, user_id, limit=5):
        calls.append(query)
        return make_mem0_results([])

    mock_mem0 = MagicMock()
    mock_mem0.search = capture_search
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    context = [
        {"author": "Alice", "content": "sujet intéressant"},
        {"author": "Wally", "content": "réponse de wally"},
        {"author": "Bob", "content": "je suis d'accord"},
    ]
    await svc.search("discord", "123", "question", context_messages=context)

    # 2 appels : query directe + query contextuelle
    assert len(calls) == 2
    context_query = calls[1]
    assert "réponse de wally" not in context_query
    assert "sujet intéressant" in context_query
    assert "je suis d'accord" in context_query


@pytest.mark.asyncio
async def test_search_context_empty_prelude_fallback():
    """Prelude vide → une seule recherche."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["souvenir"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    result = await svc.search("discord", "123", "question", context_messages=[])

    assert mock_mem0.search.call_count == 1


@pytest.mark.asyncio
async def test_search_context_only_wally_messages_fallback():
    """Prelude avec uniquement des messages de Wally → une seule recherche."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value=make_mem0_results(["souvenir"]))
    svc._mem0 = mock_mem0
    svc._mem0_init_attempted = True

    context = [
        {"author": "Wally", "content": "blabla"},
        {"author": "Wally", "content": "encore moi"},
    ]
    result = await svc.search("discord", "123", "question", context_messages=context)

    assert mock_mem0.search.call_count == 1
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `python3 -m pytest tests/test_proactive_recall.py -v`
Expected: Some FAILED (search() n'accepte pas context_messages)

- [ ] **Step 3: Implémenter la recherche contextuelle dans `search()`**

Dans `bot/core/memory.py`, remplacer la méthode `search` entière (lignes 246-278) par :

```python
    async def search(
        self, platform: str, user_id: str, query: str,
        context_messages: list[dict] | None = None,
    ) -> str:
        self._init_mem0()
        if self._mem0 is None:
            return ""
        if not query or not query.strip():
            return ""
        try:
            uid = self._user_id(platform, user_id)

            # Build context query from prelude (exclude Wally's messages)
            context_query = ""
            if context_messages:
                context_texts = [
                    m["content"] for m in context_messages[-5:]
                    if m.get("author", "").lower() != "wally"
                ]
                context_query = "\n".join(context_texts).strip()

            # Run searches (parallel if context available)
            if context_query and context_query != query.strip():
                direct_results, context_results = await asyncio.gather(
                    asyncio.to_thread(self._mem0.search, query, user_id=uid, limit=5),
                    asyncio.to_thread(self._mem0.search, context_query, user_id=uid, limit=5),
                )
            else:
                direct_results = await asyncio.to_thread(
                    self._mem0.search, query, user_id=uid, limit=5
                )
                context_results = None

            # Normalize mem0 response format
            if isinstance(direct_results, dict):
                direct_results = direct_results.get("results", [])
            if context_results is not None and isinstance(context_results, dict):
                context_results = context_results.get("results", [])

            # Merge and deduplicate by memory content, keeping best score
            seen: dict[str, float] = {}
            for r in (direct_results or []):
                mem = r.get("memory", "")
                score = r.get("score", 1.0)
                if mem and score >= _MIN_SEARCH_SCORE:
                    seen[mem] = max(seen.get(mem, 0.0), score)
            for r in (context_results or []):
                mem = r.get("memory", "")
                score = r.get("score", 1.0)
                if mem and score >= _MIN_SEARCH_SCORE:
                    seen[mem] = max(seen.get(mem, 0.0), score)

            if not seen:
                return ""

            # Sort by score descending
            sorted_memories = sorted(seen.items(), key=lambda x: x[1], reverse=True)
            return "\n".join(mem for mem, _ in sorted_memories)

        except Exception as exc:
            logger.warning("mem0 search failed: {e}", e=exc)
            return ""
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `python3 -m pytest tests/test_proactive_recall.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Lancer la suite complète**

Run: `python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add bot/core/memory.py tests/test_proactive_recall.py
git commit -m "feat(memory): add proactive contextual recall with parallel search"
```

---

### Task 2: Callers — passer le prelude comme context_messages

**Files:**
- Modify: `bot/discord/handlers.py:172`
- Modify: `bot/twitch/handlers.py:74`

- [ ] **Step 1: Modifier `bot/discord/handlers.py`**

Dans `_respond()`, remplacer :
```python
mem_context = await bot.memory.search(platform, user_id, message.content)
```
Par :
```python
mem_context = await bot.memory.search(platform, user_id, message.content, context_messages=prelude)
```

- [ ] **Step 2: Modifier `bot/twitch/handlers.py`**

Dans `handle_message()`, remplacer :
```python
mem_context = await bot.memory.search(platform, user_id, content)
```
Par :
```python
mem_context = await bot.memory.search(platform, user_id, content, context_messages=prelude)
```

- [ ] **Step 3: Lancer la suite de tests**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: ALL PASSED

- [ ] **Step 4: Commit**

```bash
git add bot/discord/handlers.py bot/twitch/handlers.py
git commit -m "feat: pass prelude as context_messages for proactive memory recall"
```
