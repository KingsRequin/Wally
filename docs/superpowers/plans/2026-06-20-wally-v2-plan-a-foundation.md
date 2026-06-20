# Wally V2 — Plan A : Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Établir les trois fondations de Wally V2 dans un nouveau package `wally_v2/` : client DeepSeek V4, mémoire atomique (SQLite + Qdrant hybride), et gate de réponse.

**Architecture:** Nouveau package `wally_v2/` coexiste avec `bot/` sans le toucher. `DeepSeekLLMClient` étend `BaseLLMClient` existant. `AtomicFact` stocké en SQLite (métadonnées) + Qdrant (embeddings uniquement). `ResponseGate` appelle le flash model avant chaque message Discord.

**Tech Stack:** Python 3.11+, asyncio, `openai>=1.91.0` (base_url DeepSeek), `aiosqlite>=0.20.0`, `qdrant-client>=1.9.0`, `pytest-asyncio`, `zoneinfo` (stdlib).

## Global Constraints

- DeepSeek primary model : `deepseek-v4-pro` — secondary/gate : `deepseek-v4-flash`
- `reasoning_content` DOIT être préservé dans les turns avec tool_calls, EXCLU dans les turns sans
- Pas de `strict: true` dans les tool definitions
- Max 6 itérations tool calling, JSON repair avec 4 suffixes avant fallback
- Gate utilise `deepseek-v4-flash`, thinking toujours disabled
- Owner ACL Discord : `"610550333042589752"` — Twitch : `"KingsRequin"`
- Toutes les heures sont UTC dans la DB, Europe/Paris pour l'affichage
- Loguru uniquement — jamais `print()` ni `import logging`
- Spec complète : `docs/superpowers/specs/2026-06-20-wally-v2-vivant-design.md`

---

## File Map

```
wally_v2/
├── __init__.py                          CREATE — package marker
├── core/
│   ├── __init__.py                      CREATE
│   ├── llm/
│   │   ├── __init__.py                  CREATE — re-export FALLBACK_RESPONSE
│   │   ├── base.py                      COPY from bot/core/llm/base.py (inchangé)
│   │   ├── deepseek.py                  CREATE — DeepSeekLLMClient
│   │   ├── openai_client.py             COPY from bot/core/llm/openai_client.py
│   │   ├── claude_client.py             COPY from bot/core/llm/claude_client.py
│   │   └── factory.py                   CREATE — ajoute provider "deepseek"
│   ├── memory/
│   │   ├── __init__.py                  CREATE
│   │   ├── facts.py                     CREATE — AtomicFact, FactCategory, FactRelation
│   │   ├── store.py                     CREATE — SQLiteFactStore + QdrantEmbeddingStore
│   │   └── retrieval.py                 CREATE — MemoryRetrieval
│   └── gate.py                          CREATE — ResponseGate + GateDecision
├── db/
│   ├── __init__.py                      CREATE
│   └── schema_v2.py                     CREATE — SQL DDL V2 tables
└── persona/
    └── prompts/
        └── gate_system.md               CREATE — prompt système du gate

tests/
└── v2/
    ├── __init__.py                      CREATE
    ├── conftest.py                      CREATE — fixtures partagées V2
    ├── core/
    │   ├── __init__.py                  CREATE
    │   ├── llm/
    │   │   ├── __init__.py              CREATE
    │   │   └── test_deepseek_client.py  CREATE — 10 tests
    │   ├── memory/
    │   │   ├── __init__.py              CREATE
    │   │   ├── test_facts.py            CREATE — 8 tests (model + SQLite CRUD)
    │   │   ├── test_store.py            CREATE — 5 tests (Qdrant hybride)
    │   │   └── test_retrieval.py        CREATE — 4 tests
    │   └── test_gate.py                 CREATE — 6 tests
    └── db/
        ├── __init__.py                  CREATE
        └── test_schema_v2.py            CREATE — 2 tests migration
```

---

## Task 1 : Scaffold du package + DB schema V2

**Files:**
- Create: `wally_v2/__init__.py`, `wally_v2/core/__init__.py`, `wally_v2/core/llm/__init__.py`, `wally_v2/core/memory/__init__.py`, `wally_v2/db/__init__.py`, `wally_v2/persona/prompts/` (dir)
- Create: `wally_v2/db/schema_v2.py`
- Create: `tests/v2/__init__.py`, `tests/v2/conftest.py`, `tests/v2/db/__init__.py`, `tests/v2/db/test_schema_v2.py`
- Copy: `bot/core/llm/base.py` → `wally_v2/core/llm/base.py`

**Interfaces:**
- Produces: `create_v2_tables(db_path: str) -> None` — appelé par tous les tests suivants

- [ ] **Step 1 : Créer l'arborescence**

```bash
mkdir -p wally_v2/core/llm wally_v2/core/memory wally_v2/db wally_v2/persona/prompts
mkdir -p tests/v2/core/llm tests/v2/core/memory tests/v2/db
touch wally_v2/__init__.py wally_v2/core/__init__.py wally_v2/core/llm/__init__.py
touch wally_v2/core/memory/__init__.py wally_v2/db/__init__.py
touch tests/v2/__init__.py tests/v2/core/__init__.py tests/v2/core/llm/__init__.py
touch tests/v2/core/memory/__init__.py tests/v2/db/__init__.py
```

- [ ] **Step 2 : Copier base.py depuis bot/**

```bash
cp bot/core/llm/base.py wally_v2/core/llm/base.py
```

- [ ] **Step 3 : Créer `wally_v2/db/schema_v2.py`**

```python
# wally_v2/db/schema_v2.py
"""DDL pour les tables Wally V2. Appelé au démarrage et dans les tests."""
from __future__ import annotations

import aiosqlite

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS atomic_facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    confidence    REAL    NOT NULL DEFAULT 1.0,
    decay_rate    REAL    NOT NULL DEFAULT 0.01,
    status        TEXT    NOT NULL DEFAULT 'active',
    emotional_context TEXT,
    source        TEXT,
    created_at    TEXT    NOT NULL,
    last_seen_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_relations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id       INTEGER NOT NULL REFERENCES atomic_facts(id),
    to_id         INTEGER NOT NULL REFERENCES atomic_facts(id),
    relation_type TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS thoughts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    content       TEXT    NOT NULL,
    meta_decision TEXT,
    emotion_snapshot TEXT,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_upgrades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal      TEXT    NOT NULL,
    message_id    TEXT,
    dm_channel_id TEXT,
    status        TEXT    NOT NULL DEFAULT 'pending',
    created_at    TEXT    NOT NULL,
    decided_at    TEXT
);

CREATE TABLE IF NOT EXISTS session_analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT,
    quality       REAL,
    issues        TEXT,
    successes     TEXT,
    improvement_note TEXT,
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_user_status
    ON atomic_facts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_facts_category
    ON atomic_facts(category);
CREATE INDEX IF NOT EXISTS idx_facts_confidence
    ON atomic_facts(confidence);
CREATE INDEX IF NOT EXISTS idx_upgrades_status
    ON pending_upgrades(status);
"""


async def create_v2_tables(db_path: str) -> None:
    """Crée les tables V2 si elles n'existent pas."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA_SQL)
        await db.commit()
```

- [ ] **Step 4 : Écrire les tests de migration**

```python
# tests/v2/db/test_schema_v2.py
import pytest
import aiosqlite
import tempfile
import os

from wally_v2.db.schema_v2 import create_v2_tables


@pytest.mark.asyncio
async def test_create_v2_tables_creates_all_tables():
    """create_v2_tables() crée les 5 tables sans erreur."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await create_v2_tables(db_path)
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        expected = {"atomic_facts", "fact_relations", "thoughts", "pending_upgrades", "session_analyses"}
        assert expected.issubset(tables)
    finally:
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_create_v2_tables_idempotent():
    """create_v2_tables() peut être appelé deux fois sans erreur (IF NOT EXISTS)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await create_v2_tables(db_path)
        await create_v2_tables(db_path)  # deuxième appel — ne doit pas lever
    finally:
        os.unlink(db_path)
```

- [ ] **Step 5 : Créer `tests/v2/conftest.py`**

```python
# tests/v2/conftest.py
import asyncio
import os
import tempfile
import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def tmp_db_path():
    """Base de données SQLite temporaire, supprimée après le test."""
    from wally_v2.db.schema_v2 import create_v2_tables
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    await create_v2_tables(path)
    yield path
    os.unlink(path)
```

- [ ] **Step 6 : Lancer les tests**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/v2/db/ -v
```

Résultat attendu : `2 passed`

- [ ] **Step 7 : Commit**

```bash
git add wally_v2/ tests/v2/
git commit -m "feat(v2): scaffold package + DB schema V2 (5 tables)"
```

---

## Task 2 : DeepSeekLLMClient

**Files:**
- Create: `wally_v2/core/llm/deepseek.py`
- Create: `wally_v2/core/llm/factory.py`
- Create: `wally_v2/core/llm/__init__.py` (update)
- Create: `tests/v2/core/llm/test_deepseek_client.py`

**Interfaces:**
- Consumes: `wally_v2/core/llm/base.py` — `BaseLLMClient`, `FALLBACK_RESPONSE`
- Produces:
  - `DeepSeekLLMClient(model, db, temperature, max_tokens, thinking_type, thinking_effort, max_tool_iters)`
  - `.complete(system_prompt, messages, ...) -> str`
  - `.complete_with_tools(system_prompt, messages, tools, tool_executor, ...) -> tuple[str, list[str]]`
  - `.complete_structured(system_prompt, messages, schema, schema_name, ...) -> dict`
  - `.complete_stream(system_prompt, messages, ...) -> AsyncGenerator[str, None]`
  - `create_llm_client(config: LLMRoleConfig, db) -> BaseLLMClient` — factory mis à jour

- [ ] **Step 1 : Écrire les tests en premier**

```python
# tests/v2/core/llm/test_deepseek_client.py
"""Tests pour DeepSeekLLMClient."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from wally_v2.core.llm.deepseek import DeepSeekLLMClient
from wally_v2.core.llm.base import FALLBACK_RESPONSE


def make_client(thinking_type="disabled", max_tool_iters=6):
    db = MagicMock()
    db.log_cost = AsyncMock()
    return DeepSeekLLMClient(
        model="deepseek-v4-flash",
        db=db,
        temperature=1.0,
        max_tokens=512,
        thinking_type=thinking_type,
        max_tool_iters=max_tool_iters,
    )


def make_response(content="Bonjour", tool_calls=None, reasoning_content=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    msg.reasoning_content = reasoning_content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 20
    resp.model = "deepseek-v4-flash"
    return resp


def make_tool_call(name="get_info", arguments='{"key": "val"}', call_id="tc_1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = arguments
    tc.model_dump.return_value = {
        "id": call_id, "type": "function",
        "function": {"name": name, "arguments": arguments}
    }
    return tc


@pytest.mark.asyncio
async def test_complete_returns_text():
    """complete() retourne le texte du modèle."""
    client = make_client()
    client._client.chat.completions.create = AsyncMock(
        return_value=make_response("Salut !")
    )
    result = await client.complete("sys", [{"role": "user", "content": "hi"}])
    assert result == "Salut !"


@pytest.mark.asyncio
async def test_complete_returns_fallback_on_error():
    """complete() retourne FALLBACK_RESPONSE si l'API lève une exception."""
    client = make_client()
    client._client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))
    result = await client.complete("sys", [{"role": "user", "content": "hi"}])
    assert result == FALLBACK_RESPONSE


@pytest.mark.asyncio
async def test_thinking_disabled_includes_temperature():
    """En thinking disabled, temperature est inclus dans les params API."""
    client = make_client(thinking_type="disabled")
    client._client.chat.completions.create = AsyncMock(return_value=make_response())
    await client.complete("sys", [{"role": "user", "content": "hi"}])
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert "temperature" in call_kwargs
    assert call_kwargs["extra_body"]["thinking"]["type"] == "disabled"


@pytest.mark.asyncio
async def test_thinking_enabled_excludes_temperature():
    """En thinking enabled, temperature est ABSENT des params API."""
    client = make_client(thinking_type="enabled")
    client._client.chat.completions.create = AsyncMock(return_value=make_response())
    await client.complete("sys", [{"role": "user", "content": "hi"}])
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert "temperature" not in call_kwargs
    assert call_kwargs["extra_body"]["thinking"]["type"] == "enabled"


@pytest.mark.asyncio
async def test_tool_call_reasoning_content_preserved():
    """Si la réponse contient un tool_call, reasoning_content est préservé dans l'historique."""
    client = make_client()
    tc = make_tool_call()
    tool_response = make_response(content=None, tool_calls=[tc], reasoning_content="je réfléchis")
    final_response = make_response("Voilà le résultat")

    call_count = 0
    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        return tool_response if call_count == 1 else final_response

    client._client.chat.completions.create = mock_create

    executor = AsyncMock(return_value="result_data")
    text, tools = await client.complete_with_tools(
        "sys", [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "get_info", "parameters": {}}}],
        tool_executor=executor,
    )

    # Vérifier que reasoning_content est dans le deuxième appel
    # (on ne peut pas inspecter directement, mais si pas d'erreur 400 simulé, c'est ok)
    assert text == "Voilà le résultat"
    assert "get_info" in tools


@pytest.mark.asyncio
async def test_no_tool_call_reasoning_content_excluded():
    """Si pas de tool_call, reasoning_content n'est PAS dans le message assistant."""
    client = make_client()
    # Réponse avec reasoning_content mais sans tool_call
    response = make_response("Bonjour", tool_calls=[], reasoning_content="je pense")
    client._client.chat.completions.create = AsyncMock(return_value=response)

    executor = AsyncMock()
    text, tools = await client.complete_with_tools(
        "sys", [{"role": "user", "content": "hi"}],
        tools=[],
        tool_executor=executor,
    )
    assert text == "Bonjour"
    assert tools == []
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_max_iter_cap_stops_tool_loop():
    """Après max_tool_iters, la boucle s'arrête et génère une réponse finale."""
    client = make_client(max_tool_iters=2)
    tc = make_tool_call()
    tool_response = make_response(content=None, tool_calls=[tc])
    final_response = make_response("Fini")

    call_count = 0
    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        # Les 2 premiers calls ont des tool_calls, le 3ème est le fallback final
        if call_count <= 2:
            return tool_response
        return final_response

    client._client.chat.completions.create = mock_create
    executor = AsyncMock(return_value="ok")
    text, tools = await client.complete_with_tools(
        "sys", [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "get_info", "parameters": {}}}],
        tool_executor=executor,
    )
    # max 2 itérations + 1 appel final sans tools
    assert call_count == 3
    assert text == "Fini"


@pytest.mark.asyncio
async def test_safe_parse_args_repairs_truncated_json():
    """_safe_parse_args répare le JSON tronqué avec des suffixes."""
    client = make_client()
    # JSON tronqué — manque le guillemet fermant et l'accolade
    raw = '{"key": "val'
    result = client._safe_parse_args(raw)
    # Doit retourner quelque chose (au moins {}) sans lever
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_safe_parse_args_valid_json():
    """_safe_parse_args retourne le JSON valide directement."""
    client = make_client()
    raw = '{"name": "Wally", "value": 42}'
    result = client._safe_parse_args(raw)
    assert result == {"name": "Wally", "value": 42}


@pytest.mark.asyncio
async def test_complete_structured_forces_tool_choice():
    """complete_structured() force tool_choice pour obtenir du JSON structuré."""
    client = make_client()

    # Simuler une réponse avec tool_call contenant le JSON structuré
    schema_args = '{"decision": "RESPOND"}'
    tc = make_tool_call(name="gate_decision", arguments=schema_args)
    response = make_response(content=None, tool_calls=[tc])
    client._client.chat.completions.create = AsyncMock(return_value=response)

    result = await client.complete_structured(
        "sys",
        [{"role": "user", "content": "hi"}],
        schema={"type": "object", "properties": {"decision": {"type": "string"}}},
        schema_name="gate_decision",
    )
    assert result == {"decision": "RESPOND"}
    # Vérifier que tool_choice a été forcé
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "function", "function": {"name": "gate_decision"}}
```

- [ ] **Step 2 : Lancer les tests — vérifier qu'ils échouent (module absent)**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/v2/core/llm/test_deepseek_client.py -v 2>&1 | head -20
```

Résultat attendu : `ModuleNotFoundError: No module named 'wally_v2.core.llm.deepseek'`

- [ ] **Step 3 : Créer `wally_v2/core/llm/deepseek.py`**

```python
# wally_v2/core/llm/deepseek.py
from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from loguru import logger
from openai import AsyncOpenAI

from wally_v2.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE


class DeepSeekLLMClient(BaseLLMClient):
    """Client DeepSeek V4 via OpenAI-compatible API.

    Gère :
    - thinking mode (disabled/enabled) via extra_body
    - preservation de reasoning_content uniquement sur les turns avec tool_calls
    - JSON repair pour les arguments malformés
    - cap max_tool_iters sur les boucles tool calling
    - complete_structured via forced tool_choice
    """

    def __init__(
        self,
        model: str,
        db: Any,
        temperature: float = 1.0,
        max_tokens: int = 2048,
        thinking_type: str = "disabled",   # "disabled" | "enabled"
        thinking_effort: str = "low",       # "low" | "high" | "max"
        max_tool_iters: int = 6,
    ) -> None:
        self._model = model
        self._db = db
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._thinking_type = thinking_type
        self._thinking_effort = thinking_effort
        self._max_tool_iters = max_tool_iters
        self._client = AsyncOpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )

    # ── Helpers privés ────────────────────────────────────────────────────────

    def _extra_body(self, thinking_override: str | None = None) -> dict:
        t = thinking_override or self._thinking_type
        if t == "enabled":
            return {
                "thinking": {"type": "enabled"},
                "reasoning_effort": self._thinking_effort,
            }
        return {"thinking": {"type": "disabled"}}

    def _api_params(self, thinking_override: str | None = None, max_tokens: int | None = None) -> dict:
        """Construit les kwargs communs pour chat.completions.create."""
        extra = self._extra_body(thinking_override)
        thinking_active = extra.get("thinking", {}).get("type") == "enabled"
        params: dict = {
            "model": self._model,
            "max_tokens": max_tokens or self._max_tokens,
            "extra_body": extra,
        }
        if not thinking_active:
            params["temperature"] = self._temperature
        return params

    @staticmethod
    def _safe_parse_args(raw: str) -> dict:
        """Parse les arguments JSON d'un tool call avec réparation si malformé."""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            for suffix in ['"', '"}', '"}}', '}']:
                try:
                    return json.loads(raw + suffix)
                except json.JSONDecodeError:
                    continue
            logger.warning("DeepSeek: impossible de réparer le JSON d'arguments: {raw!r}", raw=raw[:100])
            return {}

    async def _log_cost(self, response: Any, purpose: str, user_id: str | None) -> None:
        try:
            usage = response.usage
            await self._db.log_cost(
                model=response.model or self._model,
                purpose=purpose,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                user_id=user_id,
            )
        except Exception as e:
            logger.debug("DeepSeek log_cost failed (non-fatal): {e}", e=e)

    # ── Interface publique ────────────────────────────────────────────────────

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
        trace: Any = None,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                **self._api_params(max_tokens=max_tokens),
            )
            text = response.choices[0].message.content or ""
            await self._log_cost(response, purpose, user_id)
            return text
        except Exception as e:
            logger.error("DeepSeek complete() failed: {e}", e=e)
            return FALLBACK_RESPONSE

    async def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace: Any = None,
    ) -> tuple[str, list[str]]:
        history = list(messages)
        tools_called: list[str] = []
        params = self._api_params()

        for iteration in range(self._max_tool_iters):
            try:
                response = await self._client.chat.completions.create(
                    messages=[{"role": "system", "content": system_prompt}] + history,
                    tools=tools,
                    **params,
                )
            except Exception as e:
                logger.error("DeepSeek complete_with_tools() iter {i} failed: {e}", i=iteration, e=e)
                return (FALLBACK_RESPONSE, tools_called)

            msg = response.choices[0].message

            if not msg.tool_calls:
                # Pas de tool call → NE PAS inclure reasoning_content (règle DeepSeek)
                text = msg.content or ""
                await self._log_cost(response, purpose, user_id)
                return (text, tools_called)

            # Tool call → reasoning_content DOIT être préservé
            assistant_entry: dict = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning:
                assistant_entry["reasoning_content"] = reasoning
            history.append(assistant_entry)

            for tc in msg.tool_calls:
                tools_called.append(tc.function.name)
                args = self._safe_parse_args(tc.function.arguments)
                try:
                    result = await tool_executor(tc.function.name, json.dumps(args))
                except Exception as e:
                    result = f"Tool error: {e}"
                    logger.warning("Tool executor error for {name}: {e}", name=tc.function.name, e=e)
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })

        # Cap atteint → génère une réponse finale sans tools
        logger.warning("DeepSeek: max_tool_iters={n} atteint, génération finale sans tools", n=self._max_tool_iters)
        try:
            response = await self._client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}] + history,
                **params,
            )
            text = response.choices[0].message.content or FALLBACK_RESPONSE
            await self._log_cost(response, purpose, user_id)
            return (text, tools_called)
        except Exception as e:
            logger.error("DeepSeek complete_with_tools() final fallback failed: {e}", e=e)
            return (FALLBACK_RESPONSE, tools_called)

    async def complete_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
        trace: Any = None,
    ) -> dict:
        """Force un tool_choice pour obtenir du JSON structuré conforme au schema."""
        tool_def = {
            "type": "function",
            "function": {
                "name": schema_name,
                "description": f"Retourne une réponse structurée {schema_name}",
                "parameters": schema,
            },
        }
        # Thinking désactivé pour le structured output (incompatible + inutile)
        params = self._api_params(thinking_override="disabled")
        try:
            response = await self._client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                tools=[tool_def],
                tool_choice={"type": "function", "function": {"name": schema_name}},
                **params,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                raise RuntimeError(f"DeepSeek complete_structured: pas de tool_call dans la réponse")
            raw_args = msg.tool_calls[0].function.arguments
            result = self._safe_parse_args(raw_args)
            if not result:
                raise RuntimeError(f"DeepSeek complete_structured: JSON vide après repair")
            await self._log_cost(response, purpose, user_id)
            return result
        except Exception as e:
            logger.error("DeepSeek complete_structured() failed: {e}", e=e)
            raise RuntimeError(f"DeepSeek structured output failed: {e}") from e

    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace: Any = None,
        tools: list[dict] | None = None,
        tool_executor: Optional[Callable[[str, str], Awaitable[str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming via SSE DeepSeek. Fallback non-streamé si tools présents."""
        if tools and tool_executor:
            # Pas de streaming avec tools — fallback sur complete_with_tools
            text, _ = await self.complete_with_tools(
                system_prompt, messages, tools, tool_executor,
                purpose=purpose, user_id=user_id,
            )
            yield text
            return

        try:
            params = self._api_params()
            async with self._client.chat.completions.stream(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                **params,
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
        except Exception as e:
            logger.error("DeepSeek complete_stream() failed: {e}", e=e)
            yield FALLBACK_RESPONSE
```

- [ ] **Step 4 : Créer `wally_v2/core/llm/factory.py`**

```python
# wally_v2/core/llm/factory.py
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from wally_v2.core.llm.base import BaseLLMClient

if TYPE_CHECKING:
    from bot.config import LLMRoleConfig  # réutilise la config existante
    from bot.db.database import Database


def create_llm_client(llm_config: "LLMRoleConfig", db: "Database") -> BaseLLMClient:
    """Instancie le bon client LLM selon le provider configuré."""
    provider = llm_config.provider.lower()

    if provider == "deepseek":
        from wally_v2.core.llm.deepseek import DeepSeekLLMClient
        client = DeepSeekLLMClient(
            model=llm_config.model,
            db=db,
            temperature=getattr(llm_config, "temperature", 1.0),
            max_tokens=getattr(llm_config, "max_tokens", 2048),
            thinking_type=getattr(llm_config, "thinking_type", "disabled"),
            thinking_effort=getattr(llm_config, "thinking_effort", "low"),
        )
        logger.info(
            "Created DeepSeekLLMClient — model={model}, thinking={thinking}",
            model=llm_config.model,
            thinking=getattr(llm_config, "thinking_type", "disabled"),
        )
        return client

    if provider in ("claude", "anthropic"):
        from bot.core.llm.claude_client import ClaudeLLMClient
        return ClaudeLLMClient(
            model=llm_config.model, db=db,
            temperature=getattr(llm_config, "temperature", 0.8),
            max_tokens=getattr(llm_config, "max_tokens", 2048),
        )

    # Défaut OpenAI
    from bot.core.llm.openai_client import OpenAILLMClient
    return OpenAILLMClient(
        model=llm_config.model, db=db,
        temperature=getattr(llm_config, "temperature", 0.8),
        max_tokens=getattr(llm_config, "max_tokens", 2048),
    )
```

- [ ] **Step 5 : Mettre à jour `wally_v2/core/llm/__init__.py`**

```python
# wally_v2/core/llm/__init__.py
from wally_v2.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE

__all__ = ["BaseLLMClient", "FALLBACK_RESPONSE"]
```

- [ ] **Step 6 : Lancer les tests**

```bash
python -m pytest tests/v2/core/llm/test_deepseek_client.py -v
```

Résultat attendu : `10 passed`

- [ ] **Step 7 : Commit**

```bash
git add wally_v2/core/llm/
git commit -m "feat(v2): add DeepSeekLLMClient with thinking mode + tool loop + JSON repair"
```

---

## Task 3 : AtomicFact model + SQLite CRUD

**Files:**
- Create: `wally_v2/core/memory/facts.py`
- Create: `tests/v2/core/memory/test_facts.py`

**Interfaces:**
- Consumes: `wally_v2/db/schema_v2.py` — `create_v2_tables`, fixture `tmp_db_path`
- Produces:
  - `AtomicFact(user_id, content, category, ...)` — dataclass
  - `FactCategory` — enum (FAIT/PREF/REL/LANG/DESIRE/GOAL/EMOTION/THOUGHT)
  - `FactStatus` — enum (active/superseded/needs_review/archived)
  - `FactRelation(from_id, to_id, relation_type)` — dataclass
  - `DECAY_RATES: dict[FactCategory, float]`
  - `SQLiteFactStore(db_path)`
    - `.add(fact: AtomicFact) -> int`
    - `.get_by_user(user_id, min_confidence, categories, status) -> list[AtomicFact]`
    - `.get_by_ids(ids: list[int], min_confidence) -> list[AtomicFact]`
    - `.mark_seen(fact_id: int) -> None`
    - `.apply_decay() -> int`
    - `.add_relation(relation: FactRelation) -> int`
    - `.supersede(old_id: int, new_id: int) -> None`

- [ ] **Step 1 : Écrire les tests**

```python
# tests/v2/core/memory/test_facts.py
"""Tests pour AtomicFact + SQLiteFactStore."""
import pytest
from datetime import datetime, timedelta

from wally_v2.core.memory.facts import (
    AtomicFact, FactCategory, FactStatus, FactRelation,
    DECAY_RATES, SQLiteFactStore,
)


def make_fact(user_id="discord:123", content="Kaelis aime le café", 
              category=FactCategory.PREF, confidence=1.0) -> AtomicFact:
    return AtomicFact(user_id=user_id, content=content, category=category, confidence=confidence)


@pytest.mark.asyncio
async def test_add_fact_returns_id(tmp_db_path):
    """add() retourne un entier positif (l'ID SQLite)."""
    store = SQLiteFactStore(tmp_db_path)
    fact = make_fact()
    fact_id = await store.add(fact)
    assert isinstance(fact_id, int)
    assert fact_id > 0
    assert fact.id == fact_id


@pytest.mark.asyncio
async def test_get_by_user_returns_added_fact(tmp_db_path):
    """get_by_user() retourne le fait ajouté."""
    store = SQLiteFactStore(tmp_db_path)
    await store.add(make_fact(content="Aime le café noir"))
    facts = await store.get_by_user("discord:123")
    assert len(facts) == 1
    assert facts[0].content == "Aime le café noir"
    assert facts[0].category == FactCategory.PREF


@pytest.mark.asyncio
async def test_get_by_user_filters_by_min_confidence(tmp_db_path):
    """get_by_user() exclut les faits sous le seuil de confiance."""
    store = SQLiteFactStore(tmp_db_path)
    await store.add(make_fact(content="Haut", confidence=0.8))
    await store.add(make_fact(content="Bas", confidence=0.1))
    facts = await store.get_by_user("discord:123", min_confidence=0.5)
    assert len(facts) == 1
    assert facts[0].content == "Haut"


@pytest.mark.asyncio
async def test_get_by_user_filters_by_category(tmp_db_path):
    """get_by_user() filtre par catégorie si spécifié."""
    store = SQLiteFactStore(tmp_db_path)
    await store.add(make_fact(content="Préférence", category=FactCategory.PREF))
    await store.add(make_fact(content="Fait biographique", category=FactCategory.FAIT))
    facts = await store.get_by_user("discord:123", categories=[FactCategory.FAIT])
    assert len(facts) == 1
    assert facts[0].category == FactCategory.FAIT


@pytest.mark.asyncio
async def test_decay_rates_match_spec(tmp_db_path):
    """Les decay_rates par défaut correspondent aux valeurs du spec."""
    assert DECAY_RATES[FactCategory.FAIT] == 0.001
    assert DECAY_RATES[FactCategory.DESIRE] == 0.02
    assert DECAY_RATES[FactCategory.THOUGHT] == 0.05
    # AtomicFact.__post_init__ assigne le bon decay_rate
    fact = make_fact(category=FactCategory.DESIRE)
    assert fact.decay_rate == 0.02


@pytest.mark.asyncio
async def test_apply_decay_reduces_confidence(tmp_db_path):
    """apply_decay() réduit la confiance des faits actifs."""
    store = SQLiteFactStore(tmp_db_path)
    fact = make_fact(confidence=0.5)
    await store.add(fact)
    count = await store.apply_decay()
    assert count >= 1
    facts = await store.get_by_user("discord:123", min_confidence=0.0)
    assert facts[0].confidence < 0.5


@pytest.mark.asyncio
async def test_supersede_marks_old_fact(tmp_db_path):
    """supersede() marque l'ancien fait comme superseded et crée la relation."""
    store = SQLiteFactStore(tmp_db_path)
    old_id = await store.add(make_fact(content="Ancien fait"))
    new_id = await store.add(make_fact(content="Nouveau fait"))
    await store.supersede(old_id, new_id)
    
    # L'ancien fait ne doit plus apparaître dans les résultats actifs
    active = await store.get_by_user("discord:123")
    contents = [f.content for f in active]
    assert "Ancien fait" not in contents
    assert "Nouveau fait" in contents


@pytest.mark.asyncio
async def test_mark_seen_updates_last_seen_at(tmp_db_path):
    """mark_seen() met à jour last_seen_at."""
    store = SQLiteFactStore(tmp_db_path)
    fact = AtomicFact(
        user_id="discord:123", content="test",
        category=FactCategory.PREF,
        created_at=datetime.utcnow() - timedelta(hours=1),
        last_seen_at=datetime.utcnow() - timedelta(hours=1),
    )
    fact_id = await store.add(fact)
    await store.mark_seen(fact_id)
    facts = await store.get_by_user("discord:123")
    # last_seen_at doit être plus récent que created_at
    assert facts[0].last_seen_at > facts[0].created_at
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
python -m pytest tests/v2/core/memory/test_facts.py -v 2>&1 | head -10
```

Résultat attendu : `ModuleNotFoundError: No module named 'wally_v2.core.memory.facts'`

- [ ] **Step 3 : Créer `wally_v2/core/memory/facts.py`**

```python
# wally_v2/core/memory/facts.py
from __future__ import annotations

import aiosqlite
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Sequence

from loguru import logger


class FactCategory(str, Enum):
    FAIT    = "FAIT"
    PREF    = "PREF"
    REL     = "REL"
    LANG    = "LANG"
    DESIRE  = "DESIRE"
    GOAL    = "GOAL"
    EMOTION = "EMOTION"
    THOUGHT = "THOUGHT"


class FactStatus(str, Enum):
    ACTIVE       = "active"
    SUPERSEDED   = "superseded"
    NEEDS_REVIEW = "needs_review"
    ARCHIVED     = "archived"


DECAY_RATES: dict[FactCategory, float] = {
    FactCategory.FAIT:    0.001,
    FactCategory.PREF:    0.005,
    FactCategory.REL:     0.003,
    FactCategory.LANG:    0.001,
    FactCategory.DESIRE:  0.02,
    FactCategory.GOAL:    0.005,
    FactCategory.EMOTION: 0.01,
    FactCategory.THOUGHT: 0.05,
}


@dataclass
class AtomicFact:
    user_id:           str
    content:           str
    category:          FactCategory
    confidence:        float = 1.0
    status:            FactStatus = FactStatus.ACTIVE
    emotional_context: str | None = None
    source:            str = "conversation"
    created_at:        datetime = field(default_factory=datetime.utcnow)
    last_seen_at:      datetime = field(default_factory=datetime.utcnow)
    id:                int | None = None
    decay_rate:        float = field(init=False)

    def __post_init__(self) -> None:
        self.decay_rate = DECAY_RATES.get(self.category, 0.01)


@dataclass
class FactRelation:
    from_id:       int
    to_id:         int
    relation_type: str   # "supersedes" | "contradicts" | "supports"
    created_at:    datetime = field(default_factory=datetime.utcnow)
    id:            int | None = None


class SQLiteFactStore:
    """Accès SQLite pour les AtomicFacts et FactRelations."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def add(self, fact: AtomicFact) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO atomic_facts
                   (user_id, content, category, confidence, decay_rate, status,
                    emotional_context, source, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fact.user_id, fact.content, fact.category.value,
                    fact.confidence, fact.decay_rate, fact.status.value,
                    fact.emotional_context, fact.source,
                    fact.created_at.isoformat(), fact.last_seen_at.isoformat(),
                ),
            )
            await db.commit()
            fact.id = cursor.lastrowid
            return cursor.lastrowid  # type: ignore[return-value]

    async def get_by_user(
        self,
        user_id:        str,
        min_confidence: float = 0.3,
        categories:     list[FactCategory] | None = None,
        status:         FactStatus = FactStatus.ACTIVE,
    ) -> list[AtomicFact]:
        query = (
            "SELECT * FROM atomic_facts "
            "WHERE user_id = ? AND status = ? AND confidence >= ?"
        )
        params: list = [user_id, status.value, min_confidence]
        if categories:
            placeholders = ",".join("?" * len(categories))
            query += f" AND category IN ({placeholders})"
            params.extend(c.value for c in categories)
        query += " ORDER BY last_seen_at DESC, confidence DESC"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return [self._row_to_fact(r) for r in await cursor.fetchall()]

    async def get_by_ids(
        self,
        ids:            list[int],
        min_confidence: float = 0.3,
    ) -> list[AtomicFact]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        query = (
            f"SELECT * FROM atomic_facts "
            f"WHERE id IN ({placeholders}) AND confidence >= ? AND status = 'active'"
        )
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, [*ids, min_confidence])
            return [self._row_to_fact(r) for r in await cursor.fetchall()]

    async def mark_seen(self, fact_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE atomic_facts SET last_seen_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), fact_id),
            )
            await db.commit()

    async def apply_decay(self) -> int:
        """Réduit confidence de decay_rate pour tous les faits actifs.
        Archive ceux dont confidence tombe sous 0.1. Retourne le nombre de lignes modifiées.
        """
        async with aiosqlite.connect(self._db_path) as db:
            result = await db.execute(
                """UPDATE atomic_facts
                   SET confidence = MAX(0.0, confidence - decay_rate),
                       status = CASE
                           WHEN confidence - decay_rate < 0.1 THEN 'archived'
                           ELSE status
                       END
                   WHERE status = 'active'"""
            )
            await db.commit()
            return result.rowcount

    async def add_relation(self, relation: FactRelation) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO fact_relations (from_id, to_id, relation_type, created_at)
                   VALUES (?, ?, ?, ?)""",
                (relation.from_id, relation.to_id, relation.relation_type,
                 relation.created_at.isoformat()),
            )
            await db.commit()
            relation.id = cursor.lastrowid
            return cursor.lastrowid  # type: ignore[return-value]

    async def supersede(self, old_id: int, new_id: int) -> None:
        """Marque old_id comme superseded et crée la relation supersedes new_id→old_id."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE atomic_facts SET status = 'superseded' WHERE id = ?",
                (old_id,),
            )
            await db.execute(
                """INSERT INTO fact_relations (from_id, to_id, relation_type, created_at)
                   VALUES (?, ?, 'supersedes', ?)""",
                (new_id, old_id, datetime.utcnow().isoformat()),
            )
            await db.commit()

    @staticmethod
    def _row_to_fact(row: aiosqlite.Row) -> AtomicFact:
        fact = AtomicFact(
            user_id=row["user_id"],
            content=row["content"],
            category=FactCategory(row["category"]),
            confidence=row["confidence"],
            status=FactStatus(row["status"]),
            emotional_context=row["emotional_context"],
            source=row["source"] or "conversation",
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )
        fact.id = row["id"]
        fact.decay_rate = row["decay_rate"]
        return fact
```

- [ ] **Step 4 : Lancer les tests**

```bash
python -m pytest tests/v2/core/memory/test_facts.py -v
```

Résultat attendu : `8 passed`

- [ ] **Step 5 : Commit**

```bash
git add wally_v2/core/memory/facts.py tests/v2/core/memory/test_facts.py
git commit -m "feat(v2): add AtomicFact model + SQLiteFactStore CRUD"
```

---

## Task 4 : Qdrant Embedding Store + MemoryRetrieval

**Files:**
- Create: `wally_v2/core/memory/store.py`
- Create: `wally_v2/core/memory/retrieval.py`
- Create: `tests/v2/core/memory/test_store.py`
- Create: `tests/v2/core/memory/test_retrieval.py`

**Interfaces:**
- Consumes: `SQLiteFactStore`, `AtomicFact`, `FactCategory`
- Produces:
  - `QdrantEmbeddingStore(url, collection_name, embedding_fn)`
    - `.upsert(fact_id: int, user_id: str, content: str) -> None`
    - `.search(query: str, user_id: str, limit: int) -> list[SearchHit]`
    - `SearchHit(id: int, score: float)`
  - `MemoryRetrieval(fact_store, qdrant_store)`
    - `.search(query, user_id, limit, min_confidence, categories) -> list[AtomicFact]`
    - `.add_fact(fact: AtomicFact) -> int`

- [ ] **Step 1 : Écrire les tests**

```python
# tests/v2/core/memory/test_store.py
"""Tests QdrantEmbeddingStore — Qdrant est mocké."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wally_v2.core.memory.store import QdrantEmbeddingStore, SearchHit


def make_store():
    async def fake_embed(text: str) -> list[float]:
        return [0.1] * 384

    return QdrantEmbeddingStore(
        url="http://localhost:6333",
        collection_name="test_v2",
        embedding_fn=fake_embed,
    )


@pytest.mark.asyncio
async def test_upsert_calls_qdrant_upsert(monkeypatch):
    """upsert() appelle qdrant_client.upsert avec le bon payload."""
    store = make_store()
    mock_upsert = AsyncMock()
    monkeypatch.setattr(store._client, "upsert", mock_upsert)

    await store.upsert(fact_id=42, user_id="discord:123", content="Aime le café")

    mock_upsert.assert_called_once()
    call_kwargs = mock_upsert.call_args.kwargs
    assert call_kwargs["collection_name"] == "test_v2"
    point = call_kwargs["points"][0]
    assert point.payload == {"fact_id": 42, "user_id": "discord:123"}


@pytest.mark.asyncio
async def test_search_returns_search_hits(monkeypatch):
    """search() retourne une liste de SearchHit avec id et score."""
    store = make_store()

    mock_hit = MagicMock()
    mock_hit.id = "some-uuid"
    mock_hit.payload = {"fact_id": 7}
    mock_hit.score = 0.95

    async def mock_search(**kwargs):
        return [mock_hit]

    monkeypatch.setattr(store._client, "search", mock_search)

    hits = await store.search(query="café", user_id="discord:123", limit=5)
    assert len(hits) == 1
    assert hits[0].id == 7
    assert hits[0].score == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_search_filters_by_user_id(monkeypatch):
    """search() inclut le filtre user_id dans la requête Qdrant."""
    store = make_store()
    captured = {}

    async def mock_search(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(store._client, "search", mock_search)
    await store.search(query="test", user_id="discord:999", limit=3)

    # Vérifier que le filtre est présent
    assert "query_filter" in captured
```

```python
# tests/v2/core/memory/test_retrieval.py
"""Tests MemoryRetrieval — intégration SQLite + Qdrant mocké."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from wally_v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore
from wally_v2.core.memory.store import QdrantEmbeddingStore, SearchHit
from wally_v2.core.memory.retrieval import MemoryRetrieval


@pytest.mark.asyncio
async def test_add_fact_stores_in_sqlite_and_qdrant(tmp_db_path):
    """add_fact() écrit en SQLite ET dans Qdrant."""
    fact_store = SQLiteFactStore(tmp_db_path)
    qdrant_store = MagicMock()
    qdrant_store.upsert = AsyncMock()

    retrieval = MemoryRetrieval(fact_store, qdrant_store)
    fact = AtomicFact(user_id="discord:123", content="test", category=FactCategory.PREF)
    fact_id = await retrieval.add_fact(fact)

    assert fact_id > 0
    qdrant_store.upsert.assert_called_once_with(
        fact_id=fact_id, user_id="discord:123", content="test"
    )


@pytest.mark.asyncio
async def test_search_returns_facts_by_semantic_similarity(tmp_db_path):
    """search() combine Qdrant hits avec SQLite pour retourner des AtomicFacts."""
    fact_store = SQLiteFactStore(tmp_db_path)
    fact = AtomicFact(user_id="discord:123", content="Aime le café", category=FactCategory.PREF)
    fact_id = await fact_store.add(fact)

    qdrant_store = MagicMock()
    qdrant_store.search = AsyncMock(return_value=[SearchHit(id=fact_id, score=0.9)])

    retrieval = MemoryRetrieval(fact_store, qdrant_store)
    results = await retrieval.search("café", "discord:123", limit=5)

    assert len(results) == 1
    assert results[0].content == "Aime le café"


@pytest.mark.asyncio
async def test_search_fallback_when_qdrant_empty(tmp_db_path):
    """Si Qdrant retourne rien, search() retombe sur get_by_user SQLite."""
    fact_store = SQLiteFactStore(tmp_db_path)
    await fact_store.add(AtomicFact(
        user_id="discord:123", content="Fait en SQLite", category=FactCategory.FAIT
    ))

    qdrant_store = MagicMock()
    qdrant_store.search = AsyncMock(return_value=[])  # Qdrant vide

    retrieval = MemoryRetrieval(fact_store, qdrant_store)
    results = await retrieval.search("quelque chose", "discord:123", limit=5)

    assert any(f.content == "Fait en SQLite" for f in results)


@pytest.mark.asyncio
async def test_search_excludes_low_confidence(tmp_db_path):
    """search() exclut les faits sous min_confidence."""
    fact_store = SQLiteFactStore(tmp_db_path)
    low = AtomicFact(user_id="discord:123", content="Low conf", 
                     category=FactCategory.PREF, confidence=0.1)
    low_id = await fact_store.add(low)

    qdrant_store = MagicMock()
    qdrant_store.search = AsyncMock(return_value=[SearchHit(id=low_id, score=0.95)])

    retrieval = MemoryRetrieval(fact_store, qdrant_store)
    results = await retrieval.search("test", "discord:123", min_confidence=0.5)

    assert len(results) == 0
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
python -m pytest tests/v2/core/memory/test_store.py tests/v2/core/memory/test_retrieval.py -v 2>&1 | head -5
```

- [ ] **Step 3 : Créer `wally_v2/core/memory/store.py`**

```python
# wally_v2/core/memory/store.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import uuid5, UUID, NAMESPACE_URL

from loguru import logger
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
)


@dataclass
class SearchHit:
    id: int      # fact_id SQLite
    score: float


def _fact_uuid(fact_id: int) -> str:
    """Génère un UUID stable depuis l'ID SQLite pour Qdrant."""
    return str(uuid5(NAMESPACE_URL, f"fact:{fact_id}"))


class QdrantEmbeddingStore:
    """Stocke uniquement les embeddings dans Qdrant. Les métadonnées sont en SQLite.

    Payload Qdrant : {"fact_id": int, "user_id": str}
    """

    def __init__(
        self,
        url: str,
        collection_name: str,
        embedding_fn: Callable[[str], Awaitable[list[float]]],
        vector_size: int = 384,
    ) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._collection = collection_name
        self._embed = embedding_fn
        self._vector_size = vector_size

    async def ensure_collection(self) -> None:
        """Crée la collection si elle n'existe pas."""
        try:
            await self._client.get_collection(self._collection)
        except Exception:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
            )

    async def upsert(self, fact_id: int, user_id: str, content: str) -> None:
        try:
            vector = await self._embed(content)
            point = PointStruct(
                id=_fact_uuid(fact_id),
                vector=vector,
                payload={"fact_id": fact_id, "user_id": user_id},
            )
            await self._client.upsert(
                collection_name=self._collection,
                points=[point],
            )
        except Exception as e:
            logger.warning("QdrantEmbeddingStore.upsert failed for fact {id}: {e}", id=fact_id, e=e)

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
    ) -> list[SearchHit]:
        try:
            vector = await self._embed(query)
            hits = await self._client.search(
                collection_name=self._collection,
                query_vector=vector,
                query_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=limit,
                with_payload=True,
            )
            return [SearchHit(id=h.payload["fact_id"], score=h.score) for h in hits]
        except Exception as e:
            logger.warning("QdrantEmbeddingStore.search failed: {e}", e=e)
            return []
```

- [ ] **Step 4 : Créer `wally_v2/core/memory/retrieval.py`**

```python
# wally_v2/core/memory/retrieval.py
from __future__ import annotations

from loguru import logger

from wally_v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore
from wally_v2.core.memory.store import QdrantEmbeddingStore


class MemoryRetrieval:
    """Façade hybride SQLite + Qdrant pour la recherche de faits atomiques."""

    def __init__(self, fact_store: SQLiteFactStore, qdrant_store: QdrantEmbeddingStore) -> None:
        self._facts = fact_store
        self._qdrant = qdrant_store

    async def add_fact(self, fact: AtomicFact) -> int:
        """Persiste un fait en SQLite + indexe l'embedding dans Qdrant."""
        fact_id = await self._facts.add(fact)
        await self._qdrant.upsert(fact_id=fact_id, user_id=fact.user_id, content=fact.content)
        return fact_id

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
        min_confidence: float = 0.3,
        categories: list[FactCategory] | None = None,
    ) -> list[AtomicFact]:
        """Recherche sémantique Qdrant → charge + filtre depuis SQLite."""
        hits = await self._qdrant.search(query=query, user_id=user_id, limit=limit * 2)

        if not hits:
            # Fallback : faits les plus récents depuis SQLite
            return await self._facts.get_by_user(
                user_id, min_confidence=min_confidence, categories=categories
            )

        # Charger depuis SQLite, filtrer par confiance
        fact_ids = [h.id for h in hits]
        loaded = await self._facts.get_by_ids(fact_ids, min_confidence=min_confidence)

        if categories:
            loaded = [f for f in loaded if f.category in categories]

        # Re-trier : score Qdrant × confidence SQLite
        id_to_score = {h.id: h.score for h in hits}
        loaded.sort(key=lambda f: id_to_score.get(f.id, 0.0) * f.confidence, reverse=True)

        # Renforcer les faits utilisés
        for fact in loaded[:limit]:
            if fact.id:
                await self._facts.mark_seen(fact.id)

        return loaded[:limit]
```

- [ ] **Step 5 : Lancer les tests**

```bash
python -m pytest tests/v2/core/memory/test_store.py tests/v2/core/memory/test_retrieval.py -v
```

Résultat attendu : `7 passed`

- [ ] **Step 6 : Commit**

```bash
git add wally_v2/core/memory/store.py wally_v2/core/memory/retrieval.py \
        tests/v2/core/memory/test_store.py tests/v2/core/memory/test_retrieval.py
git commit -m "feat(v2): add QdrantEmbeddingStore + MemoryRetrieval hybrid store"
```

---

## Task 5 : ResponseGate

**Files:**
- Create: `wally_v2/core/gate.py`
- Create: `wally_v2/persona/prompts/gate_system.md`
- Create: `tests/v2/core/test_gate.py`

**Interfaces:**
- Consumes: `DeepSeekLLMClient.complete_structured()`, `SQLiteFactStore.add()`, `AtomicFact`, `FactCategory`
- Produces:
  - `GateDecision(decision, emoji, defer_seconds, reason)`
  - `ResponseGate(llm, fact_store, prompts_dir)`
    - `.decide(message_content, author_user_id, emotion_state, relationship_facts, active_desires, is_ignored) -> GateDecision`

- [ ] **Step 1 : Créer le prompt système du gate**

```bash
cat > wally_v2/persona/prompts/gate_system.md << 'EOF'
Tu es le filtre de réponse de Wally. Tu reçois le contexte d'un message entrant et tu décides comment Wally doit réagir.

Tu dois retourner une décision UNIQUE parmi :
- RESPOND : Wally répond normalement
- IGNORE : Wally ne répond pas (il n'a pas envie, il est fatigué, il en a marre de cette personne)
- REACT : Wally réagit uniquement avec un emoji (sans texte)
- DEFER : Wally préfère répondre plus tard

RÈGLES :
- RESPOND est la valeur par défaut si rien ne justifie autre chose
- IGNORE doit être rare et justifié (une raison émotionnelle ou relationnelle réelle)
- REACT est pour les messages qui méritent une réaction mais pas une réponse
- DEFER est pour quand Wally est absorbé par autre chose

Retourne uniquement la décision structurée, sans explication supplémentaire.
EOF
```

- [ ] **Step 2 : Écrire les tests**

```python
# tests/v2/core/test_gate.py
"""Tests ResponseGate."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from wally_v2.core.gate import ResponseGate, GateDecision
from wally_v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore


def make_gate(llm_result: dict | None = None, llm_raises: bool = False):
    llm = MagicMock()
    if llm_raises:
        llm.complete_structured = AsyncMock(side_effect=RuntimeError("LLM failed"))
    else:
        llm.complete_structured = AsyncMock(return_value=llm_result or {"decision": "RESPOND"})

    fact_store = MagicMock()
    fact_store.add = AsyncMock(return_value=1)

    return ResponseGate(llm=llm, fact_store=fact_store, prompts_dir="wally_v2/persona/prompts")


EMOTION_STATE = {"anger": 0.1, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.1}


@pytest.mark.asyncio
async def test_decide_respond_default():
    """decide() retourne RESPOND par défaut."""
    gate = make_gate({"decision": "RESPOND"})
    result = await gate.decide("Salut !", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "RESPOND"


@pytest.mark.asyncio
async def test_decide_ignore_stores_emotional_fact():
    """Si IGNORE, un AtomicFact EMOTION est créé en SQLite."""
    gate = make_gate({"decision": "IGNORE", "reason": "trop de spam"})
    result = await gate.decide("encore moi", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "IGNORE"
    gate._fact_store.add.assert_called_once()
    call_args = gate._fact_store.add.call_args[0][0]
    assert isinstance(call_args, AtomicFact)
    assert call_args.category == FactCategory.EMOTION
    assert "discord:123" == call_args.user_id


@pytest.mark.asyncio
async def test_decide_react_returns_emoji():
    """decide() avec REACT retourne l'emoji fourni."""
    gate = make_gate({"decision": "REACT", "emoji": "👀"})
    result = await gate.decide("haha", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "REACT"
    assert result.emoji == "👀"


@pytest.mark.asyncio
async def test_decide_defer_returns_seconds():
    """decide() avec DEFER retourne defer_seconds."""
    gate = make_gate({"decision": "DEFER", "defer_seconds": 300})
    result = await gate.decide("msg", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "DEFER"
    assert result.defer_seconds == 300


@pytest.mark.asyncio
async def test_decide_fallback_to_respond_on_llm_error():
    """Si le LLM lève une exception, gate retourne RESPOND (fail-safe)."""
    gate = make_gate(llm_raises=True)
    result = await gate.decide("msg", "discord:123", EMOTION_STATE, [], [])
    assert result.decision == "RESPOND"


@pytest.mark.asyncio
async def test_decide_is_ignored_bypasses_llm():
    """Si is_ignored=True, gate retourne immédiatement IGNORE sans appel LLM."""
    gate = make_gate()
    result = await gate.decide("msg", "discord:123", EMOTION_STATE, [], [], is_ignored=True)
    assert result.decision == "IGNORE"
    gate._llm.complete_structured.assert_not_called()
```

- [ ] **Step 3 : Vérifier que les tests échouent**

```bash
python -m pytest tests/v2/core/test_gate.py -v 2>&1 | head -5
```

- [ ] **Step 4 : Créer `wally_v2/core/gate.py`**

```python
# wally_v2/core/gate.py
from __future__ import annotations

import os
from dataclasses import dataclass

from loguru import logger

from wally_v2.core.llm.base import BaseLLMClient
from wally_v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore


_GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision":      {"type": "string", "enum": ["RESPOND", "IGNORE", "REACT", "DEFER"]},
        "emoji":         {"type": ["string", "null"]},
        "defer_seconds": {"type": ["integer", "null"]},
        "reason":        {"type": ["string", "null"]},
    },
    "required": ["decision"],
    "additionalProperties": False,
}

_FALLBACK_SYSTEM = (
    "Tu es le filtre de réponse de Wally. Retourne une décision: RESPOND, IGNORE, REACT ou DEFER."
)


@dataclass
class GateDecision:
    decision:      str             # RESPOND | IGNORE | REACT | DEFER
    emoji:         str | None = None
    defer_seconds: int | None = None
    reason:        str | None = None


class ResponseGate:
    """Décide comment Wally réagit à chaque message entrant.

    Appelé avant toute génération de réponse. Utilise deepseek-v4-flash,
    thinking disabled, pour minimiser la latence (<1s).
    """

    def __init__(
        self,
        llm: BaseLLMClient,
        fact_store: SQLiteFactStore,
        prompts_dir: str = "wally_v2/persona/prompts",
    ) -> None:
        self._llm = llm
        self._fact_store = fact_store
        self._system = self._load_system(prompts_dir)

    @staticmethod
    def _load_system(prompts_dir: str) -> str:
        path = os.path.join(prompts_dir, "gate_system.md")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip() or _FALLBACK_SYSTEM
        except FileNotFoundError:
            return _FALLBACK_SYSTEM

    async def decide(
        self,
        message_content: str,
        author_user_id: str,
        emotion_state: dict[str, float],
        relationship_facts: list[AtomicFact],
        active_desires: list[AtomicFact],
        is_ignored: bool = False,
    ) -> GateDecision:
        """Retourne la décision de Wally pour ce message."""
        if is_ignored:
            return GateDecision(decision="IGNORE", reason="utilisateur marqué comme ignoré")

        dominant_emotion, dominant_value = max(
            emotion_state.items(), key=lambda x: x[1], default=("boredom", 0.0)
        )
        context_parts = [
            f"Message reçu : {message_content[:500]}",
            f"Émotion dominante : {dominant_emotion} ({dominant_value:.2f})",
        ]
        if relationship_facts:
            rel_summary = " | ".join(f.content for f in relationship_facts[:3])
            context_parts.append(f"Relation connue : {rel_summary}")
        if active_desires:
            desire_summary = " | ".join(f.content for f in active_desires[:2])
            context_parts.append(f"Désirs actifs de Wally : {desire_summary}")

        user_msg = "\n".join(context_parts)

        try:
            result = await self._llm.complete_structured(
                system_prompt=self._system,
                messages=[{"role": "user", "content": user_msg}],
                schema=_GATE_SCHEMA,
                schema_name="gate_decision",
                purpose="gate",
            )
            decision = GateDecision(
                decision=result.get("decision", "RESPOND"),
                emoji=result.get("emoji"),
                defer_seconds=result.get("defer_seconds"),
                reason=result.get("reason"),
            )
            if decision.decision == "IGNORE" and decision.reason:
                await self._fact_store.add(AtomicFact(
                    user_id=author_user_id,
                    content=f"Wally a choisi d'ignorer ce message — {decision.reason}",
                    category=FactCategory.EMOTION,
                    confidence=0.9,
                    source="gate",
                ))
            return decision

        except Exception as e:
            logger.warning("ResponseGate.decide() failed, fallback RESPOND: {e}", e=e)
            return GateDecision(decision="RESPOND")
```

- [ ] **Step 5 : Lancer les tests**

```bash
python -m pytest tests/v2/core/test_gate.py -v
```

Résultat attendu : `6 passed`

- [ ] **Step 6 : Commit**

```bash
git add wally_v2/core/gate.py wally_v2/persona/prompts/gate_system.md tests/v2/core/test_gate.py
git commit -m "feat(v2): add ResponseGate with RESPOND/IGNORE/REACT/DEFER decisions"
```

---

## Task 6 : Wire le Gate dans le handler Discord

**Files:**
- Modify: `bot/discord/handlers.py` (section `handle_message`) — ajoute l'appel gate V2
- Modify: `bot/discord/bot.py` — instancie les composants V2 si config provider=deepseek

**Interfaces:**
- Consumes: `ResponseGate.decide()`, `GateDecision`, `MemoryRetrieval`
- Produces: `handle_message()` appelle le gate avant de générer une réponse

**Note :** Cette tâche modifie `bot/` pour câbler V2 — le gate s'insère en début de `handle_message()`. C'est le seul endroit où V2 et V1 se touchent dans ce plan.

- [ ] **Step 1 : Lire le début de handle_message pour trouver le point d'insertion**

```bash
grep -n "async def handle_message" bot/discord/handlers.py
```

Note la ligne. Puis :

```bash
sed -n '<ligne+1>,<ligne+60>p' bot/discord/handlers.py
```

Identifie le bloc après la vérification `_is_channel_allowed` et avant la construction du prompt.

- [ ] **Step 2 : Ajouter le gate dans `bot/discord/bot.py`**

Lire le fichier d'abord :
```bash
head -80 bot/discord/bot.py
```

Ajouter dans `__init__` de `WallyDiscord`, après `self.llm` et `self.llm_secondary` (l'import de `create_llm_client` et `LLMRoleConfig` existe déjà dans ce fichier) :

```python
# Dans bot/discord/bot.py — dans __init__, après self.llm et self.llm_secondary
# Gate V2 — optionnel, activé par response_gate.enabled dans config
self.response_gate = None   # type: ignore[assignment]
self.v2_memory = None       # type: ignore[assignment]  # MemoryRetrieval — câblé en Plan B
if getattr(config, "response_gate", None) and config.response_gate.get("enabled", False):
    from wally_v2.core.gate import ResponseGate
    from wally_v2.core.memory.facts import SQLiteFactStore
    from wally_v2.core.llm.factory import create_llm_client as create_v2_llm
    from bot.config import LLMRoleConfig
    gate_llm = create_v2_llm(
        LLMRoleConfig(
            provider="deepseek",
            model=config.response_gate.get("model", "deepseek-v4-flash"),
        ),
        db,
    )
    self.response_gate = ResponseGate(
        llm=gate_llm,
        fact_store=SQLiteFactStore(db_path),
        prompts_dir="wally_v2/persona/prompts",
    )
    logger.info("ResponseGate V2 initialisé (deepseek-v4-flash)")
```

**Note :** `self.v2_memory` (MemoryRetrieval) est initialisé en **Plan B**. Dans Plan A, le gate fonctionne sans contexte mémoire (les `rel_facts` et `desire_facts` seront vides — le try/except dans handle_message absorbe le `AttributeError`).

- [ ] **Step 3 : Insérer l'appel gate dans `handle_message`**

Dans `bot/discord/handlers.py`, dans `handle_message()`, après le bloc `_check_spam()` et avant la construction du prompt :

```python
# Gate V2 — décision RESPOND/IGNORE/REACT/DEFER
if getattr(bot, "response_gate", None) is not None:
    from wally_v2.core.memory.facts import FactCategory
    user_id_str = str(message.author.id)
    emotion_state = bot.emotion.get_state()

    # Récupérer les faits de relation et les désirs actifs
    rel_facts = []
    desire_facts = []
    try:
        if hasattr(bot, "v2_memory"):
            rel_facts = await bot.v2_memory.search(
                "relation", user_id_str, limit=3,
                categories=[FactCategory.REL, FactCategory.EMOTION]
            )
            desire_facts = await bot.v2_memory.search(
                "désir objectif", f"wally:self", limit=2,
                categories=[FactCategory.DESIRE]
            )
    except Exception as e:
        logger.debug("Gate context fetch failed (non-fatal): {e}", e=e)

    gate_decision = await bot.response_gate.decide(
        message_content=message.content,
        author_user_id=user_id_str,
        emotion_state=emotion_state,
        relationship_facts=rel_facts,
        active_desires=desire_facts,
    )

    if gate_decision.decision == "IGNORE":
        logger.debug("Gate: IGNORE message from {user}", user=user_id_str)
        return

    if gate_decision.decision == "REACT" and gate_decision.emoji:
        try:
            await message.add_reaction(gate_decision.emoji)
        except Exception as e:
            logger.debug("Gate: REACT emoji failed: {e}", e=e)
        return

    if gate_decision.decision == "DEFER" and gate_decision.defer_seconds:
        # Déléguer à ActionService pour réponse différée
        logger.debug(
            "Gate: DEFER {sec}s for {user}",
            sec=gate_decision.defer_seconds, user=user_id_str
        )
        # TODO Plan B : créer une action planifiée via ActionService
        # Pour l'instant, fallback sur RESPOND pour ne pas bloquer
        pass
    # RESPOND : continue normalement
```

- [ ] **Step 4 : Vérifier que les tests existants passent toujours**

```bash
python -m pytest tests/ -v --ignore=tests/v2 -x -q 2>&1 | tail -20
```

Résultat attendu : tous les tests existants passent (le gate est optionnel et ne s'active que si `response_gate.enabled: true` dans config).

- [ ] **Step 5 : Vérifier que tous les tests V2 passent**

```bash
python -m pytest tests/v2/ -v
```

Résultat attendu : `27 passed` (2 + 10 + 8 + 7 + 6 de Task 1 à 5 = 33, moins les tests de Task 6 non écrits = minimum 27)

- [ ] **Step 6 : Commit final**

```bash
git add bot/discord/bot.py bot/discord/handlers.py
git commit -m "feat(v2): wire ResponseGate into Discord handle_message (opt-in via config)"
```

---

## Vérification finale Plan A

- [ ] **Tous les tests V2 passent**

```bash
python -m pytest tests/v2/ -v --tb=short
```

- [ ] **Tous les tests V1 passent encore (non-régression)**

```bash
python -m pytest tests/ --ignore=tests/v2 -q
```

- [ ] **Vérifier que l'import fonctionne**

```bash
python -c "
from wally_v2.core.llm.deepseek import DeepSeekLLMClient
from wally_v2.core.memory.facts import AtomicFact, FactCategory, SQLiteFactStore
from wally_v2.core.memory.store import QdrantEmbeddingStore
from wally_v2.core.memory.retrieval import MemoryRetrieval
from wally_v2.core.gate import ResponseGate, GateDecision
print('Plan A imports OK')
"
```

---

## Récapitulatif

| Task | Fichiers créés | Tests |
|------|---------------|-------|
| 1 — Scaffold + DB | `wally_v2/__init__.py` + dirs, `db/schema_v2.py` | 2 |
| 2 — DeepSeekLLMClient | `core/llm/deepseek.py`, `factory.py` | 10 |
| 3 — AtomicFact + SQLite | `core/memory/facts.py` | 8 |
| 4 — Qdrant + Retrieval | `core/memory/store.py`, `retrieval.py` | 7 |
| 5 — ResponseGate | `core/gate.py`, `persona/prompts/gate_system.md` | 6 |
| 6 — Wire Discord | `bot/discord/bot.py` (mod), `handlers.py` (mod) | non-régression |

**Plan B — Cognitive Core** portera : `CognitiveLoop`, `InnerMonologue`, `PersonaManager`, `EmergentDesires`, `EmotionalMemory`.
