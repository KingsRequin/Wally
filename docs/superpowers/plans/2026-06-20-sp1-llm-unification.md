# SP1 — LLM Layer Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the duplicated LLM layer into a single home (`bot/core/llm/`) with DeepSeek as the only text provider, OpenAI kept solely for image generation, and no fallback.

**Architecture:** Move `deepseek.py` from `wally_v2/core/llm/` into `bot/core/llm/`, delete the entire `wally_v2/core/llm/` package (duplicate `base.py`, redundant `factory.py`, `fallback.py`), delete `claude_client.py`, and repoint every importer at `bot.core.llm`. The factory becomes deepseek-only for text and raises on any other text provider.

**Tech Stack:** Python 3.12, asyncio, pytest, openai SDK (DeepSeek uses OpenAI-compatible API + OpenAI for images).

## Global Constraints

- Text LLM = **DeepSeek only**. `create_llm_client` raises `ValueError` on any other text provider.
- OpenAI (`OpenAILLMClient`) is **kept** but used **only** for `image_client` (gpt-image-1.5), constructed directly in `bot/bootstrap.py` — never via the factory.
- **No fallback.** `fallback.py`, the `llm.fallback` config section, and `LLMConfig.fallback` are removed.
- Single LLM home: `bot/core/llm/`. The package `wally_v2/core/llm/` is deleted entirely.
- Logging via `loguru` only. Never `print()` / `import logging`.
- NO SEMANTIC SEARCH: when removing a symbol, grep separately for direct calls, imports, string literals, re-exports, tests/mocks.
- Run V2 suite with: `python3 -m pytest tests/v2/ -q` (binary is `python3`, not `python`).

---

### Task 1: Migrate DeepSeek client into `bot/core/llm/`

**Files:**
- Create: `bot/core/llm/deepseek.py` (verbatim copy of `wally_v2/core/llm/deepseek.py`, one import line changed)
- Modify: `bot/core/llm/factory.py:54` (deepseek import → local)
- Modify: `wally_v2/core/llm/factory.py:20` (deepseek import → `bot.core.llm.deepseek`)
- Modify: `tests/v2/core/llm/test_deepseek_client.py:6-7` (imports → `bot.core.llm.deepseek` / `bot.core.llm.base`)
- Delete: `wally_v2/core/llm/deepseek.py`

**Interfaces:**
- Consumes: `bot.core.llm.base.BaseLLMClient`, `FALLBACK_RESPONSE` (identical to the deleted `wally_v2.core.llm.base`).
- Produces: `bot.core.llm.deepseek.DeepSeekLLMClient(model, db, temperature=1.0, max_tokens=2048, thinking_type="disabled", thinking_effort="low", max_tool_iters=6)`.

- [ ] **Step 1: Copy the file**

```bash
cp wally_v2/core/llm/deepseek.py bot/core/llm/deepseek.py
```

- [ ] **Step 2: Fix the internal import and header comment in `bot/core/llm/deepseek.py`**

Change line 1 and line 11:

```python
# bot/core/llm/deepseek.py
```

```python
from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE
```

- [ ] **Step 3: Point `bot/core/llm/factory.py` at the local deepseek module**

In `bot/core/llm/factory.py`, the deepseek branch currently reads `from wally_v2.core.llm.deepseek import DeepSeekLLMClient`. Change it to:

```python
        from bot.core.llm.deepseek import DeepSeekLLMClient
```

- [ ] **Step 4: Point `wally_v2/core/llm/factory.py` at the local deepseek module**

In `wally_v2/core/llm/factory.py:20`, change:

```python
        from bot.core.llm.deepseek import DeepSeekLLMClient
```

- [ ] **Step 5: Repoint the deepseek test imports**

In `tests/v2/core/llm/test_deepseek_client.py`, change lines 6-7:

```python
from bot.core.llm.deepseek import DeepSeekLLMClient
from bot.core.llm.base import FALLBACK_RESPONSE
```

- [ ] **Step 6: Delete the old client**

```bash
git rm wally_v2/core/llm/deepseek.py
```

- [ ] **Step 7: Run the deepseek test**

Run: `python3 -m pytest tests/v2/core/llm/test_deepseek_client.py -q`
Expected: PASS (same count as before the move).

- [ ] **Step 8: Commit**

```bash
git add bot/core/llm/deepseek.py bot/core/llm/factory.py wally_v2/core/llm/factory.py tests/v2/core/llm/test_deepseek_client.py
git commit -m "refactor(sp1): move DeepSeek client into bot/core/llm/"
```

---

### Task 2: Make the factory DeepSeek-only and delete Claude

**Files:**
- Modify: `bot/core/llm/factory.py` (remove claude + openai text branches, deepseek-only, raise otherwise)
- Modify: `bot/core/llm/__init__.py` (drop `ClaudeLLMClient` lazy export)
- Delete: `bot/core/llm/claude_client.py`
- Delete: `tests/test_claude_client.py`
- Test: `tests/test_llm_factory.py` (new)

**Interfaces:**
- Consumes: `bot.core.llm.deepseek.DeepSeekLLMClient` (Task 1), `bot.config.LLMRoleConfig`.
- Produces: `create_llm_client(llm_config, db) -> DeepSeekLLMClient`; raises `ValueError` if `llm_config.provider.lower() != "deepseek"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_factory.py`:

```python
import pytest

from bot.config import LLMRoleConfig
from bot.core.llm.factory import create_llm_client
from bot.core.llm.deepseek import DeepSeekLLMClient


def test_factory_returns_deepseek_for_deepseek_provider():
    client = create_llm_client(LLMRoleConfig(provider="deepseek", model="deepseek-v4-pro"), db=None)
    assert isinstance(client, DeepSeekLLMClient)


def test_factory_raises_on_non_deepseek_text_provider():
    with pytest.raises(ValueError):
        create_llm_client(LLMRoleConfig(provider="openai", model="gpt-5-nano"), db=None)
    with pytest.raises(ValueError):
        create_llm_client(LLMRoleConfig(provider="claude", model="claude-haiku-4-5-20251001"), db=None)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_llm_factory.py -q`
Expected: FAIL — `test_factory_raises_on_non_deepseek_text_provider` fails because the current factory still builds claude/openai clients.

- [ ] **Step 3: Rewrite `bot/core/llm/factory.py`**

Replace the entire file with:

```python
# bot/core/llm/factory.py
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from bot.core.llm.base import BaseLLMClient

if TYPE_CHECKING:
    from bot.config import LLMRoleConfig
    from bot.db.database import Database


def create_llm_client(llm_config: "LLMRoleConfig", db: "Database") -> BaseLLMClient:
    """Instantiate the text LLM client. DeepSeek is the only supported text provider.

    OpenAI is reserved for image generation and is constructed directly in
    bot/bootstrap.py — never through this factory.
    """
    provider = llm_config.provider.lower()

    if provider == "deepseek":
        from bot.core.llm.deepseek import DeepSeekLLMClient
        client = DeepSeekLLMClient(
            model=llm_config.model,
            db=db,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )
        logger.info(
            "Created DeepSeekLLMClient — model={model}, temp={temp}",
            model=llm_config.model, temp=llm_config.temperature,
        )
        return client

    raise ValueError(
        f"Unknown text LLM provider: {provider!r}. Only 'deepseek' is supported "
        "(OpenAI is image-only, constructed directly in bootstrap)."
    )
```

- [ ] **Step 4: Drop the `ClaudeLLMClient` lazy export in `bot/core/llm/__init__.py`**

Replace the file with:

```python
# bot/core/llm/__init__.py
from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE, FALLBACK_IMAGE_RESPONSE

__all__ = [
    "BaseLLMClient",
    "FALLBACK_RESPONSE",
    "FALLBACK_IMAGE_RESPONSE",
    "OpenAILLMClient",
    "create_llm_client",
]


def __getattr__(name: str):
    # Lazy imports to avoid circular dependencies and heavy SDK loads at import time
    if name == "OpenAILLMClient":
        from bot.core.llm.openai_client import OpenAILLMClient
        return OpenAILLMClient
    if name == "create_llm_client":
        from bot.core.llm.factory import create_llm_client
        return create_llm_client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

- [ ] **Step 5: Delete Claude client and its test**

```bash
git rm bot/core/llm/claude_client.py tests/test_claude_client.py
```

- [ ] **Step 6: Run the factory test**

Run: `python3 -m pytest tests/test_llm_factory.py -q`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add bot/core/llm/factory.py bot/core/llm/__init__.py tests/test_llm_factory.py
git commit -m "refactor(sp1): factory is deepseek-only for text, remove Claude client"
```

---

### Task 3: Remove the fallback mechanism

**Files:**
- Modify: `bot/bootstrap.py:90-97` (remove the FallbackLLMClient block)
- Modify: `bot/config.py` (remove `LLMConfig.fallback` field + parse + save)
- Modify: `config.yaml` (remove `llm.fallback` section)
- Delete: `wally_v2/core/llm/fallback.py`

**Interfaces:**
- Consumes: `bot.config.LLMConfig` (no longer has `fallback`).
- Produces: `bootstrap.build_core_services` returns `primary_llm`/`secondary_llm` as bare `DeepSeekLLMClient` (no wrapper).

- [ ] **Step 1: Remove the fallback block in `bot/bootstrap.py`**

Delete these lines (currently after `secondary_llm = create_llm_client(config.llm.secondary, db)`):

```python
    # Fallback LLM (autre provider) : si le primaire est down, on bascule
    if config.llm.fallback is not None:
        from wally_v2.core.llm.fallback import FallbackLLMClient
        fb_client = create_llm_client(config.llm.fallback, db)
        primary_llm = FallbackLLMClient(primary_llm, fb_client)
        secondary_llm = FallbackLLMClient(secondary_llm, fb_client)
        logger.info("Fallback LLM activé — secours: {}/{}",
                    config.llm.fallback.provider, config.llm.fallback.model)
```

So the section reads only:

```python
    # ── LLM clients ───────────────────────────────────────────────────────────
    primary_llm = create_llm_client(config.llm.primary, db)
    secondary_llm = create_llm_client(config.llm.secondary, db)
    # Image client is always OpenAI (Claude/DeepSeek have no image generation API)
    image_client = OpenAILLMClient(
        model=config.llm.primary.model,  # model irrelevant for images
        db=db,
    )
```

- [ ] **Step 2: Remove `fallback` from `LLMConfig` in `bot/config.py`**

Change the dataclass back to:

```python
@dataclass
class LLMConfig:
    primary: LLMRoleConfig
    secondary: LLMRoleConfig
```

- [ ] **Step 3: Remove fallback parsing in `_build_llm_config`**

In `bot/config.py`, the `if "llm" in raw:` branch must return without fallback:

```python
        if "llm" in raw:
            llm_raw = raw["llm"]
            return LLMConfig(
                primary=LLMRoleConfig(**llm_raw["primary"]),
                secondary=LLMRoleConfig(**llm_raw["secondary"]),
            )
```

(Remove the `fb_raw = llm_raw.get("fallback")` line and the `fallback=...` kwarg.)

- [ ] **Step 4: Confirm `save()` does not serialize fallback**

`Config.save()` serializes `asdict(self.llm)`. Since `LLMConfig` no longer has a `fallback` field, `asdict` will not emit it. No change needed beyond Step 2. Verify by reading the `save()` method — it must not reference `self.llm.fallback` anywhere.

- [ ] **Step 5: Remove the `llm.fallback` section from `config.yaml`**

Delete this block under `llm:`:

```yaml
  fallback:
    max_tokens: 8192
    model: claude-haiku-4-5-20251001
    provider: claude
    temperature: 0.8
    thinking_type: disabled
```

- [ ] **Step 6: Delete `fallback.py`**

```bash
git rm wally_v2/core/llm/fallback.py
```

- [ ] **Step 7: Verify config loads**

Run: `python3 -c "from bot.config import Config; c = Config.load('config.yaml'); print(c.llm.primary.provider, c.llm.secondary.provider)"`
Expected: prints `deepseek deepseek`, no AttributeError, no reference to fallback.

- [ ] **Step 8: Commit**

```bash
git add bot/bootstrap.py bot/config.py config.yaml
git commit -m "refactor(sp1): remove LLM fallback mechanism"
```

---

### Task 4: Repoint `wally_v2` at `bot.core.llm` and delete `wally_v2/core/llm/`

**Files:**
- Modify: `wally_v2/core/gate.py:9` (import → `bot.core.llm.base`)
- Modify: `bot/discord/bot.py:87,113` (`create_v2_llm` → `bot.core.llm.factory`)
- Delete: `wally_v2/core/llm/base.py`, `wally_v2/core/llm/factory.py`, `wally_v2/core/llm/__init__.py` (whole package)

**Interfaces:**
- Consumes: `bot.core.llm.base.BaseLLMClient`, `bot.core.llm.factory.create_llm_client` (Tasks 1-2).
- Produces: `wally_v2` no longer contains an `llm` subpackage; all LLM access goes through `bot.core.llm`.

- [ ] **Step 1: Repoint `wally_v2/core/gate.py`**

Change line 9:

```python
from bot.core.llm.base import BaseLLMClient
```

- [ ] **Step 2: Repoint both `create_v2_llm` imports in `bot/discord/bot.py`**

At line 87 and line 113, change:

```python
            from bot.core.llm.factory import create_llm_client as create_v2_llm
```

- [ ] **Step 3: Grep for any remaining `wally_v2.core.llm` references**

Run: `grep -rn "wally_v2.core.llm" --include="*.py" . | grep -v __pycache__`
Expected: only the files inside `wally_v2/core/llm/` itself (about to be deleted). If any OTHER file matches, fix it before continuing.

- [ ] **Step 4: Delete the package**

```bash
git rm -r wally_v2/core/llm/
```

- [ ] **Step 5: Verify the package is gone and imports fail**

Run: `python3 -c "import wally_v2.core.llm" 2>&1 | tail -1`
Expected: `ModuleNotFoundError: No module named 'wally_v2.core.llm'`.

Run: `python3 -c "from bot.core.llm.deepseek import DeepSeekLLMClient; from wally_v2.core.gate import ResponseGate; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 6: Run the full V2 suite**

Run: `python3 -m pytest tests/v2/ -q`
Expected: PASS (deepseek test now under new import path; no fallback test exists).

- [ ] **Step 7: Commit**

```bash
git add wally_v2/core/gate.py bot/discord/bot.py
git rm -r wally_v2/core/llm/
git commit -m "refactor(sp1): wally_v2 uses bot.core.llm, delete wally_v2/core/llm package"
```

---

### Task 5: Integration verification — clean grep + startup

**Files:**
- No code changes (verification + any residual fix surfaced here).

**Interfaces:**
- Consumes: everything from Tasks 1-4.

- [ ] **Step 1: Grep for every removed/forbidden symbol**

Run each separately:

```bash
grep -rn "wally_v2.core.llm" --include="*.py" . | grep -v __pycache__
grep -rn "claude_client\|ClaudeLLMClient" --include="*.py" . | grep -v __pycache__
grep -rn "FallbackLLMClient" --include="*.py" . | grep -v __pycache__
grep -rn "llm.fallback\|\.fallback" --include="*.py" bot/ wally_v2/ | grep -v __pycache__
```

Expected: zero matches for all four. Any match is a defect — fix and re-run.

- [ ] **Step 2: Run the full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: V2 suite green; the pre-existing 2 V1 failures noted in project memory remain the only failures (no NEW failures, no import errors from the LLM changes).

- [ ] **Step 3: Rebuild and restart the bot**

```bash
docker compose build wally && docker compose up -d --force-recreate wally
```

- [ ] **Step 4: Verify startup logs**

Run: `sleep 8 && docker logs wally-bot --since 30s 2>&1 | grep -E "DeepSeek|LLM clients|ResponseGate|CognitiveLoop|image|ERROR|Traceback|ImportError"`

Expected:
- `Created DeepSeekLLMClient` for primary + secondary
- `LLM clients created — primary: DeepSeekLLMClient, secondary: DeepSeekLLMClient`
- `ResponseGate V2 initialisé` and `CognitiveLoop V2 initialisée`
- NO `ImportError`, NO `Traceback`, NO `FallbackLLMClient`

- [ ] **Step 5: Confirm image client intact**

Run: `docker logs wally-bot --since 60s 2>&1 | grep -iE "OpenAILLMClient|image_client|Created OpenAI"`
Expected: an OpenAI client is still constructed for images (image_client). If image generation has a separate init log, confirm it appears.

- [ ] **Step 6: Final commit (if Step 1 surfaced fixes)**

```bash
git add -A
git commit -m "refactor(sp1): final LLM unification cleanup"
```

If no fixes were needed, skip this commit.

---

## Self-Review

**Spec coverage:**
- Decision 1 (DeepSeek-only text, remove claude) → Task 2 ✓
- Decision 2 (OpenAI images only) → Task 3 Step 1 keeps `image_client`; factory never builds openai (Task 2) ✓
- Decision 3 (no fallback) → Task 3 ✓
- Decision 4 (single home bot/core/llm/, delete wally_v2/core/llm/) → Tasks 1 + 4 ✓
- Config changes (provider deepseek, drop fallback, keep openai: legacy) → Task 3 ✓
- Importer rewiring table → Tasks 1, 2, 4 ✓
- Grep verification → Task 4 Step 3 + Task 5 Step 1 ✓
- Startup + /wally imagine intact → Task 5 ✓

**Placeholder scan:** none — every code step shows full code.

**Type consistency:** `create_llm_client(llm_config, db)` signature consistent across Tasks 1-4; `DeepSeekLLMClient(model, db, temperature, max_tokens)` consistent with the factory call.

**Note:** `config.yaml` already has `llm.primary.provider: deepseek` and `llm.secondary.provider: deepseek` from earlier this session — Task 3 only removes the fallback section.
