# SP2 — Mémoire V2 Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire de la mémoire V2 (`SQLiteFactStore` + `QdrantEmbeddingStore`) le backend long-terme unique, derrière la façade `MemoryService` (qui conserve sa fenêtre de contexte), et supprimer `QdrantMemoryStore`.

**Architecture:** `MemoryService` garde la fenêtre de contexte conversationnel (RAM) verbatim, mais ses méthodes long-terme (`add`/`search`/`get_all`/`delete_user_memories`/`reset_all`) délèguent à `MemoryRetrieval`/`SQLiteFactStore`. Embeddings via OpenAI `text-embedding-3-small` (fonction partagée). Mémoire reset (aucune migration). Méthodes V1 cassées (global/relationships/top_match/consolidation/questions) supprimées et leurs appelants neutralisés.

**Tech Stack:** Python 3.12, asyncio, aiosqlite, qdrant-client, openai SDK (embeddings), pytest.

## Global Constraints

- Pas de migration de données. Mémoire long-terme repart vide. Collection Qdrant V2 = `wally_v2_facts` (ou `QDRANT_COLLECTION_NAME` env si défini).
- `MemoryService` RESTE la façade. La fenêtre de contexte (`append_message`/`get_context`/`append_prelude`/`get_prelude`/`get_all_contexts`/`get_context_summarized_if_needed`) est préservée VERBATIM.
- Embeddings = OpenAI `text-embedding-3-small`, 1536 dims, cache LRU + `db.log_cost(purpose="embedding")`.
- Convention API : `add/search/get_all/delete_user_memories` reçoivent le RAW user_id ; le namespace `platform:user_id` est construit en interne.
- `bot/core/memory_store.py` supprimé. Property `memory.store` supprimée.
- loguru only. python = `python3`.
- NO SEMANTIC SEARCH : pour chaque symbole retiré, grep séparé (appels, imports, littéraux, tests, mocks).
- Suite V2 : `python3 -m pytest tests/v2/ -q`. Suite ciblée mémoire : `python3 -m pytest tests/test_memory*.py tests/v2/core/memory/ -q`.

---

### Task 1: Fonction d'embedding partagée

**Files:**
- Create: `bot/core/embeddings.py`
- Test: `tests/test_embeddings.py`

**Interfaces:**
- Produces: `async def make_embedding_fn(openai_client, db) -> Callable[[str], Awaitable[list[float]]]`. Le client exposé doit avoir `.embeddings.create(model=..., input=...)` (le SDK OpenAI brut accessible via l'image_client). Renvoie une coroutine `embed(text: str) -> list[float]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_embeddings.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.embeddings import make_embedding_fn


class _Resp:
    def __init__(self, vec):
        self.data = [MagicMock(embedding=vec)]


@pytest.mark.asyncio
async def test_embedding_caches_and_logs_cost():
    client = MagicMock()
    client.embeddings.create = AsyncMock(return_value=_Resp([0.1, 0.2, 0.3]))
    db = MagicMock()
    db.log_cost = AsyncMock()

    embed = await make_embedding_fn(client, db)
    v1 = await embed("hello")
    v2 = await embed("hello")  # cache hit

    assert v1 == [0.1, 0.2, 0.3]
    assert v2 == v1
    client.embeddings.create.assert_awaited_once()       # cache: une seule vraie requête
    db.log_cost.assert_awaited()                          # coût loggé
    assert db.log_cost.await_args.kwargs.get("purpose") == "embedding"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_embeddings.py -q`
Expected: FAIL — `bot.core.embeddings` n'existe pas.

- [ ] **Step 3: Implement `bot/core/embeddings.py`**

```python
# bot/core/embeddings.py
from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Awaitable, Callable

from loguru import logger

_EMBEDDING_MODEL = "text-embedding-3-small"
_CACHE_MAX = 1000


async def make_embedding_fn(openai_client, db) -> Callable[[str], Awaitable[list[float]]]:
    """Construit une fonction d'embedding OpenAI partagée (cache LRU + log coût).

    openai_client : objet exposant .embeddings.create(model=, input=) (SDK OpenAI brut).
    db            : Database avec log_cost(...).
    """
    cache: "OrderedDict[str, list[float]]" = OrderedDict()

    async def embed(text: str) -> list[float]:
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        try:
            resp = await openai_client.embeddings.create(model=_EMBEDDING_MODEL, input=text)
            vector = resp.data[0].embedding
        except Exception as e:
            logger.warning("Embedding failed: {e}", e=e)
            raise
        try:
            usage = getattr(resp, "usage", None)
            tokens = getattr(usage, "total_tokens", 0) if usage else 0
            await db.log_cost(
                model=_EMBEDDING_MODEL, input_tokens=tokens, output_tokens=0,
                cost_usd=0.0, purpose="embedding", user_id=None,
            )
        except Exception as e:
            logger.debug("Embedding cost log failed (non-fatal): {e}", e=e)
        cache[key] = vector
        if len(cache) > _CACHE_MAX:
            cache.popitem(last=False)
        return vector

    return embed
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_embeddings.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/core/embeddings.py tests/test_embeddings.py
git commit -m "feat(sp2): shared OpenAI embedding function with cache + cost log"
```

---

### Task 2: `SQLiteFactStore.delete_by_user` + `count_by_user`

**Files:**
- Modify: `wally_v2/core/memory/facts.py` (ajout 2 méthodes)
- Test: `tests/v2/core/memory/test_facts.py` (ajout 1 test)

**Interfaces:**
- Produces: `SQLiteFactStore.delete_by_user(user_id: str) -> int` (supprime les faits d'un user, retourne le compte) ; `SQLiteFactStore.count_by_user(user_id: str) -> int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/v2/core/memory/test_facts.py`:

```python
@pytest.mark.asyncio
async def test_delete_by_user_removes_only_that_user(tmp_path):
    from wally_v2.db.schema_v2 import create_v2_tables
    from wally_v2.core.memory.facts import SQLiteFactStore, AtomicFact, FactCategory
    db_path = str(tmp_path / "t.db")
    await create_v2_tables(db_path)
    store = SQLiteFactStore(db_path)
    await store.add(AtomicFact(user_id="discord:1", content="a", category=FactCategory.FAIT))
    await store.add(AtomicFact(user_id="discord:1", content="b", category=FactCategory.FAIT))
    await store.add(AtomicFact(user_id="discord:2", content="c", category=FactCategory.FAIT))

    deleted = await store.delete_by_user("discord:1")
    assert deleted == 2
    assert await store.count_by_user("discord:1") == 0
    assert await store.count_by_user("discord:2") == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/v2/core/memory/test_facts.py::test_delete_by_user_removes_only_that_user -q`
Expected: FAIL — méthodes absentes.

- [ ] **Step 3: Add the methods to `wally_v2/core/memory/facts.py`**

Insert into `SQLiteFactStore` (after `mark_seen`):

```python
    async def delete_by_user(self, user_id: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM atomic_facts WHERE user_id = ?", (user_id,)
            )
            await db.commit()
            return cursor.rowcount

    async def count_by_user(self, user_id: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM atomic_facts WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/v2/core/memory/test_facts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wally_v2/core/memory/facts.py tests/v2/core/memory/test_facts.py
git commit -m "feat(sp2): SQLiteFactStore delete_by_user + count_by_user"
```

---

### Task 3: Réécrire `MemoryService` en façade V2

**Files:**
- Modify: `bot/core/memory.py` (long-terme → V2 ; fenêtre de contexte préservée verbatim ; méthodes mortes supprimées)
- Test: `tests/test_memory_v2_facade.py` (nouveau)

**Interfaces:**
- Consumes: `bot.core.embeddings.make_embedding_fn` (Task 1), `wally_v2.core.memory.facts.{SQLiteFactStore, AtomicFact, FactCategory}`, `wally_v2.core.memory.retrieval.MemoryRetrieval`, `wally_v2.core.memory.store.QdrantEmbeddingStore` (+ `delete_by_user`/`count_by_user` de Task 2).
- Produces (signatures conservées) :
  - `set_db(db)`, `set_openai_client(client)` (déjà là), `set_embedding_backend(db_path, qdrant_url, collection, embedding_fn)` (nouveau setter qui construit les stores V2).
  - `async add(platform, user_id, content, category="FAIT", username=None, source="fact_extractor", **kw) -> None`
  - `async search(platform, user_id, query, limit=20, **kw) -> str`
  - `async get_all(platform, user_id) -> str`
  - `async delete_user_memories(platform, user_id) -> None`
  - `async reset_all() -> None`
  - `load_aliases/add_alias/remove_alias` : inchangés.
  - Fenêtre de contexte : inchangée.
- Supprimées : `add_global`, `search_global`, `search_relationships`, `search_top_match`, `get_pending_question_directive`, `_consolidate`, `_evaluate`, `_post_add_maintenance`, `_qdrant_search`, `_merge_contexts`, property `store`, l'ancien `_init_store` (version QdrantMemoryStore).

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_v2_facade.py`:

```python
import pytest

from bot.core.memory import MemoryService


@pytest.fixture
def mem(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from wally_v2.db.schema_v2 import create_v2_tables
    from wally_v2.core.memory.facts import SQLiteFactStore
    from wally_v2.core.memory.retrieval import MemoryRetrieval
    db_path = str(tmp_path / "wally.db")
    asyncio.get_event_loop().run_until_complete(create_v2_tables(db_path))
    svc = MemoryService(SimpleNamespace())

    class _StubQdrant:
        async def ensure_collection(self): pass
        async def upsert(self, **kw): pass
        async def search(self, **kw): return []  # force fallback get_by_user
    svc._facts = SQLiteFactStore(db_path)
    svc._retrieval = MemoryRetrieval(svc._facts, _StubQdrant())
    return svc


@pytest.mark.asyncio
async def test_add_and_search_roundtrip(mem):
    await mem.add("discord", "123", "aime les bouchons en plastique", category="PREF")
    out = await mem.search("discord", "123", "bouchons")
    assert "bouchon" in out.lower()


@pytest.mark.asyncio
async def test_add_namespaces_user_id(mem):
    await mem.add("discord", "999", "fait test")
    facts = await mem._facts.get_by_user("discord:999")
    assert len(facts) == 1
    assert facts[0].user_id == "discord:999"
```

> Note implémenteur : le test injecte `_facts`/`_retrieval` directement. `MemoryService.add/search/get_all` doivent utiliser ces attributs (pas de property `store`).

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_memory_v2_facade.py -q`
Expected: FAIL — `add`/`search` utilisent encore QdrantMemoryStore / attributs absents.

- [ ] **Step 3: Rewrite the long-term part of `bot/core/memory.py`**

Règles :
1. **Conserver VERBATIM** : tout le bloc fenêtre de contexte (`append_message`, `get_context`, `append_prelude`, `get_prelude`, `get_all_contexts`, `get_context_summarized_if_needed`, `_summarize_messages`) + aliases (`load_aliases`, `add_alias`, `remove_alias`) + `_user_id(platform, user_id)`.
2. **Supprimer** : `add_global`, `search_global`, `search_relationships`, `search_top_match`, `get_pending_question_directive`, `_consolidate`, `_evaluate`, `_post_add_maintenance`, `_qdrant_search`, `_merge_contexts`, property `store`, l'ancien `_init_store` + imports de `QdrantMemoryStore`/`MemoryRecord`.
3. **Ajouter** les attributs `self._facts = None`, `self._retrieval = None`, `self._db_path = None` dans `__init__`.
4. **Nouveau setter** :

```python
    def set_embedding_backend(self, db_path: str, qdrant_url: str, collection: str, embedding_fn) -> None:
        from wally_v2.core.memory.facts import SQLiteFactStore
        from wally_v2.core.memory.store import QdrantEmbeddingStore
        from wally_v2.core.memory.retrieval import MemoryRetrieval
        self._db_path = db_path
        self._facts = SQLiteFactStore(db_path)
        qdrant = QdrantEmbeddingStore(
            url=qdrant_url, collection_name=collection,
            embedding_fn=embedding_fn, vector_size=1536,
        )
        self._retrieval = MemoryRetrieval(self._facts, qdrant)
        logger.info("MemoryService backend V2 prêt (collection={})", collection)
```

5. **Nouvelles méthodes long-terme** :

```python
    async def add(self, platform: str, user_id: str, content: str,
                  category: str = "FAIT", username: str | None = None,
                  source: str = "fact_extractor", **_kw) -> None:
        if self._retrieval is None:
            logger.warning("MemoryService.add ignoré: backend V2 non initialisé")
            return
        from datetime import datetime, timezone
        from wally_v2.core.memory.facts import AtomicFact, FactCategory
        try:
            cat = FactCategory(category)
        except ValueError:
            cat = FactCategory.FAIT
        now = datetime.now(timezone.utc)
        await self._retrieval.add_fact(AtomicFact(
            user_id=self._user_id(platform, user_id),
            content=content, category=cat, confidence=1.0,
            source=source, created_at=now, last_seen_at=now,
        ))

    async def search(self, platform: str, user_id: str, query: str,
                     limit: int = 20, **_kw) -> str:
        if self._retrieval is None:
            return ""
        facts = await self._retrieval.search(query, self._user_id(platform, user_id), limit=limit)
        if not facts:
            return ""
        return "\n".join(f"- {f.content}" for f in facts)

    async def get_all(self, platform: str, user_id: str) -> str:
        if self._facts is None:
            return ""
        facts = await self._facts.get_by_user(self._user_id(platform, user_id))
        return "\n".join(f"- {f.content}" for f in facts)

    async def delete_user_memories(self, platform: str, user_id: str) -> None:
        if self._facts is None:
            return
        await self._facts.delete_by_user(self._user_id(platform, user_id))

    async def reset_all(self) -> None:
        if self._facts is None:
            return
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM atomic_facts")
            await db.commit()
```

> Garder `**_kw` pour absorber les anciens kwargs des appelants (`context_messages`, `username_hint`) sans casser.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_memory_v2_facade.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the context-window tests (must stay green)**

Run: `python3 -m pytest tests/test_memory_tag.py -q`
Expected: les tests de fenêtre de contexte passent (sauf ceux déjà rouges au base — voir ledger). Comparer au base si doute.

- [ ] **Step 6: Commit**

```bash
git add bot/core/memory.py tests/test_memory_v2_facade.py
git commit -m "refactor(sp2): MemoryService long-term backend → V2 facts, drop dead methods"
```

---

### Task 4: Wiring bootstrap + suppression `memory_store.py`

**Files:**
- Modify: `bot/bootstrap.py` (init backend V2 sur MemoryService)
- Modify: `bot/main.py:428` (sync compte mémoire → retrait)
- Delete: `bot/core/memory_store.py`

**Interfaces:**
- Consumes: `MemoryService.set_embedding_backend` (Task 3), `make_embedding_fn` (Task 1).

- [ ] **Step 1: Wire backend V2 in `bot/bootstrap.py`**

Après la création de `image_client` et `memory`, et avant `memory.set_openai_client(secondary_llm)`, ajouter :

```python
    import os as _os
    from bot.core.embeddings import make_embedding_fn
    _embed_fn = await make_embedding_fn(image_client._client, db)
    _collection = _os.getenv("QDRANT_COLLECTION_NAME", "wally_v2_facts")
    memory.set_embedding_backend(
        db_path=_os.getenv("DB_PATH", "data/wally.db"),
        qdrant_url=qdrant_url,
        collection=_collection,
        embedding_fn=_embed_fn,
    )
```

> `image_client._client` est l'AsyncOpenAI brut de `OpenAILLMClient`. Vérifier l'attribut exact (`_client`) dans `bot/core/llm/openai_client.py` ; si trop privé, exposer une property `raw_client` et l'utiliser.

- [ ] **Step 2: Fix `bot/main.py:428` (sync compte mémoire)**

Le bloc utilise `store = memory.store` pour compter les mémoires par user (dashboard mémoire V1). Lire le bloc autour de la ligne 428 et **retirer** la fonction `_sync_memory_counts` + son appel (mémoire reset, dashboard mémoire différé refonte). Vérifier qu'aucune autre référence à la fonction ne subsiste.

- [ ] **Step 3: Delete `memory_store.py`**

```bash
git rm bot/core/memory_store.py
```

- [ ] **Step 4: Grep résiduel**

```bash
grep -rn "QdrantMemoryStore\|memory_store\|\.memory\.store" --include="*.py" bot/ | grep -v __pycache__
```
Expected: zéro. Corriger tout résidu avant commit.

- [ ] **Step 5: Import sanity**

Run: `python3 -c "from bot.core.memory import MemoryService; import bot.bootstrap; print('ok')"`
Expected: `ok`, aucune ImportError.

- [ ] **Step 6: Commit**

```bash
git add bot/bootstrap.py bot/main.py
git rm bot/core/memory_store.py
git commit -m "refactor(sp2): wire V2 memory backend in bootstrap, delete QdrantMemoryStore"
```

---

### Task 5: Repoint consommateurs Discord

**Files:**
- Modify: `bot/discord/handlers.py` (retirer search_global, search_relationships, search_top_match ; garder add/search)

**Interfaces:** Consomme la nouvelle façade (add/search seulement).

- [ ] **Step 1: Retirer le rappel spontané mémoire (search_top_match)**

Dans `handlers.py` autour de la ligne 692, supprimer le bloc qui appelle `bot.memory.search_top_match(...)` et déclenche `_spontaneous_respond(..., recall_memory=...)`. Conserver la branche `trigger_type` (spontané non-mémoire) intacte.

- [ ] **Step 2: Retirer l'injection search_global**

Autour de la ligne 846-847, supprimer l'appel `bot.memory.search_global(...)` et la variable de contexte associée. `bot.memory.search(...)` (846) reste.

- [ ] **Step 3: Retirer search_relationships**

Autour de la ligne 877, supprimer le bloc `rel_context = await bot.memory.search_relationships(...)` et son injection. Les relations restent fournies par le `social_context` Graphiti (déjà présent).

- [ ] **Step 4: Grep Discord**

```bash
grep -n "search_global\|search_relationships\|search_top_match\|add_global" bot/discord/handlers.py
```
Expected: zéro.

- [ ] **Step 5: Import + tests handlers**

Run: `python3 -c "import bot.discord.handlers; print('ok')"` → `ok`.
Run: `python3 -m pytest tests/test_discord_handlers.py -q` → pas de NOUVELLE casse vs base (certains tests déjà rouges au base, cf ledger).

- [ ] **Step 6: Commit**

```bash
git add bot/discord/handlers.py
git commit -m "refactor(sp2): drop global/relationship/top_match memory in Discord handler"
```

---

### Task 6: Repoint Twitch + journal + dashboard + commandes

**Files:**
- Modify: `bot/twitch/handlers.py` (retirer search_global/relationships/top_match)
- Modify: `bot/core/journal.py` (retirer la consolidation via `store`)
- Modify: `bot/dashboard/routes/memory.py`, `bot/dashboard/routes/chat.py`, `bot/dashboard/routes/links.py` (retirer/neutraliser usages `memory.store`)

**Interfaces:** Façade add/search/get_all uniquement ; plus de `store`.

- [ ] **Step 1: Twitch handlers**

Dans `bot/twitch/handlers.py`, retirer les appels `search_top_match` (155), `search_global` (194), `search_relationships` (222) et leurs injections de contexte. Conserver `search` (193) et `add` (350, 460).

- [ ] **Step 2: Journal consolidation**

Dans `bot/core/journal.py` (≈309-375), le bloc utilise `self._memory.store.get_all/delete/upsert` pour consolider. Retirer ce bloc de consolidation (mémoire reset, plus de store). Si la génération du journal lit des mémoires ailleurs, remplacer par `await self._memory.get_all(platform, uid)` là où c'est trivial ; sinon retirer proprement la section et son appel.

- [ ] **Step 3: Dashboard routes**

`bot/dashboard/routes/memory.py`, `chat.py:337,519`, `links.py:55` utilisent `state.memory.store`. La property n'existe plus. Pour chaque route dépendant du CRUD store V1 : neutraliser (retourner `{"items": []}` ou HTTP 501 « mémoire en refonte ») — la refonte dashboard mémoire est tracée (#14/#15). Garder fonctionnels : `chat.py` search/add (236,414), `links.py` add_alias (53).

- [ ] **Step 4: Grep global résiduel**

```bash
grep -rn "\.memory\.store\|search_global\|search_relationships\|search_top_match\|add_global\|get_pending_question_directive" --include="*.py" bot/ | grep -v __pycache__
```
Expected: zéro.

- [ ] **Step 5: Import sanity**

Run: `python3 -c "import bot.twitch.handlers, bot.core.journal, bot.dashboard.routes.memory, bot.dashboard.routes.chat, bot.dashboard.routes.links; print('ok')"`
Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add bot/twitch/handlers.py bot/core/journal.py bot/dashboard/routes/memory.py bot/dashboard/routes/chat.py bot/dashboard/routes/links.py
git commit -m "refactor(sp2): repoint Twitch/journal/dashboard off V1 memory store"
```

---

### Task 7: Vérification d'intégration

**Files:** Aucun changement (vérif + correctifs résiduels éventuels).

- [ ] **Step 1: Grep global de tous les symboles retirés**

```bash
grep -rn "QdrantMemoryStore\|memory_store\|\.memory\.store\|search_global\|search_relationships\|search_top_match\|add_global\|get_pending_question_directive\|_consolidate\|_evaluate" --include="*.py" bot/ wally_v2/ | grep -v __pycache__
```
Expected: zéro.

- [ ] **Step 2: Suite ciblée**

Run: `python3 -m pytest tests/v2/ tests/test_memory_v2_facade.py tests/test_embeddings.py tests/test_memory_tag.py -q`
Expected: vert (hors tests déjà rouges au base — comparer si doute).

- [ ] **Step 3: Suite complète — comparer au base**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -3`
Expected: aucune NOUVELLE régression vs le base SP2. Les 14 fails + 16 errors pré-existants peuvent rester ; tout NOUVEL échec lié mémoire est un défaut à corriger.

- [ ] **Step 4: Rebuild + restart**

```bash
docker compose build wally && docker compose up -d --force-recreate wally
```

- [ ] **Step 5: Startup logs**

Run: `sleep 9 && docker logs wally-bot --since 40s 2>&1 | grep -iE "MemoryService|backend V2|collection|ERROR|Traceback|ImportError"`
Expected: `MemoryService backend V2 prêt (collection=wally_v2_facts)`, aucune ImportError/Traceback.

- [ ] **Step 6: Test fonctionnel mémoire**

Envoyer un message Discord contenant un fait mémorable dans un canal autorisé, puis :
```bash
docker exec wally-bot python3 -c "import asyncio; from wally_v2.core.memory.facts import SQLiteFactStore; print(asyncio.run(SQLiteFactStore('data/wally.db').count_by_user('discord:610550333042589752')))"
```
Expected: ≥ 0 sans erreur ; aucune exception mémoire dans les logs.

- [ ] **Step 7: Final commit (si correctifs)**

```bash
git add -A && git commit -m "refactor(sp2): integration cleanup"
```
Sinon, ignorer.

---

## Self-Review

**Spec coverage :**
- Embedding OpenAI partagé → Task 1 ✓
- delete/count fact store → Task 2 ✓
- MemoryService façade V2 + fenêtre contexte préservée + méthodes mortes supprimées → Task 3 ✓
- Suppression memory_store.py + wiring bootstrap → Task 4 ✓
- Repoint Discord → Task 5 ✓ ; Twitch/journal/dashboard → Task 6 ✓
- Grep + démarrage + test fonctionnel → Task 7 ✓
- Aliases conservés (Task 3 règle 1) ✓ ; collection wally_v2_facts (Task 4) ✓ ; 1536 dims (Task 3 setter) ✓

**Placeholder scan :** Task 6 Step 2/3 laissent un choix borné (retirer vs adapter) justifié (mémoire reset, dashboard différé) — acceptable, critère fourni.

**Type consistency :** `set_embedding_backend(db_path, qdrant_url, collection, embedding_fn)` cohérent Task 3↔4 ; `delete_by_user/count_by_user` cohérent Task 2↔3↔4 ; `make_embedding_fn(openai_client, db)` cohérent Task 1↔4.

**Risque connu :** `image_client._client` (Task 4 Step 1) — attribut privé du SDK OpenAI. Vérifier à l'implémentation ; exposer une property propre si besoin.
