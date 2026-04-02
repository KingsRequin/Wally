# Langfuse Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Intégrer Langfuse self-hosted pour tracer toutes les conversations et appels LLM de Wally, et remplacer le système de coûts SQLite existant.

**Architecture:** Langfuse + Postgres ajoutés dans docker-compose. Module bot/core/tracing.py expose des helpers no-op-safe. Les handlers Discord/Twitch créent des traces, les providers LLM créent des generations. L'onglet Coûts du panel admin est remplacé par un iframe Langfuse via proxy FastAPI.

**Tech Stack:** Langfuse v3 (self-hosted), langfuse SDK Python, httpx (proxy), PostgreSQL 16

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| docker-compose.yml | Modify | Ajouter services langfuse-db + langfuse |
| .env.example | Create | Template des variables Langfuse |
| requirements.txt | Modify | Ajouter langfuse |
| bot/core/tracing.py | Create | Singleton Langfuse, helpers trace/generation/span |
| bot/main.py | Modify | Init/shutdown tracing |
| bot/core/llm/base.py | Modify | Ajouter param trace aux signatures |
| bot/core/llm/openai_client.py | Modify | Remplacer log_cost par create_generation |
| bot/core/llm/claude_client.py | Modify | Remplacer log_cost par create_generation |
| bot/discord/handlers.py | Modify | Créer trace au début de _respond, passer aux LLM |
| bot/twitch/handlers.py | Modify | Même pattern que Discord |
| bot/dashboard/routes/langfuse_proxy.py | Create | Proxy reverse vers Langfuse |
| bot/dashboard/app.py | Modify | Retirer costs router/task, ajouter langfuse proxy |
| bot/dashboard/static/index.html | Modify | Remplacer onglet Coûts par Langfuse |
| bot/dashboard/static/app.js | Modify | Supprimer code costs, ajouter tab Langfuse |
| bot/dashboard/routes/costs.py | Delete | Plus nécessaire |

---

### Task 1: Infrastructure Docker — Langfuse + Postgres

**Files:**
- Modify: docker-compose.yml
- Create: .env.example

- [ ] **Step 1: Ajouter les services dans docker-compose.yml**

Ajouter avant le service wally:

```yaml
  langfuse-db:
    image: postgres:16-alpine
    container_name: wally-langfuse-db
    networks:
      - wally-net
    environment:
      - POSTGRES_USER=langfuse
      - POSTGRES_PASSWORD=${LANGFUSE_DB_PASSWORD:-langfuse_secret}
      - POSTGRES_DB=langfuse
    volumes:
      - ./data/langfuse-db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  langfuse:
    image: langfuse/langfuse:3
    container_name: wally-langfuse
    networks:
      - wally-net
    depends_on:
      langfuse-db:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql://langfuse:${LANGFUSE_DB_PASSWORD:-langfuse_secret}@langfuse-db:5432/langfuse
      - NEXTAUTH_URL=http://langfuse:3000
      - NEXTAUTH_SECRET=${LANGFUSE_NEXTAUTH_SECRET}
      - SALT=${LANGFUSE_SALT}
      - LANGFUSE_INIT_ORG_ID=wally
      - LANGFUSE_INIT_ORG_NAME=Wally
      - LANGFUSE_INIT_PROJECT_ID=wally-bot
      - LANGFUSE_INIT_PROJECT_NAME=Wally Bot
      - LANGFUSE_INIT_PROJECT_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
      - LANGFUSE_INIT_PROJECT_SECRET_KEY=${LANGFUSE_SECRET_KEY}
      - LANGFUSE_INIT_USER_EMAIL=${LANGFUSE_INIT_USER_EMAIL:-admin@wally.local}
      - LANGFUSE_INIT_USER_PASSWORD=${LANGFUSE_INIT_USER_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:3000/api/public/health || exit 1"]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 30s
    restart: unless-stopped
```

Note: ne PAS ajouter langfuse dans depends_on de wally — le tracing est optionnel et Langfuse peut prendre 30s+ au premier boot.

Aussi ajouter ./data/langfuse-db dans le init-perms volumes et command pour les permissions.

- [ ] **Step 2: Créer .env.example avec les variables Langfuse**

```
# Langfuse (observabilité LLM)
LANGFUSE_PUBLIC_KEY=pk-lf-change-me
LANGFUSE_SECRET_KEY=sk-lf-change-me
LANGFUSE_HOST=http://langfuse:3000
LANGFUSE_DB_PASSWORD=langfuse_secret
LANGFUSE_NEXTAUTH_SECRET=change-me-random-32-chars
LANGFUSE_SALT=change-me-random-32-chars
LANGFUSE_INIT_USER_EMAIL=admin@wally.local
LANGFUSE_INIT_USER_PASSWORD=change-me
```

- [ ] **Step 3: Ajouter les variables réelles au .env**

Générer les secrets et ajouter au .env existant:

```bash
python3 -c "import secrets; print('LANGFUSE_NEXTAUTH_SECRET=' + secrets.token_hex(32))"
python3 -c "import secrets; print('LANGFUSE_SALT=' + secrets.token_hex(32))"
python3 -c "import secrets; print('LANGFUSE_PUBLIC_KEY=pk-lf-' + secrets.token_hex(16))"
python3 -c "import secrets; print('LANGFUSE_SECRET_KEY=sk-lf-' + secrets.token_hex(16))"
```

Ajouter les lignes générées + les autres variables au .env.

- [ ] **Step 4: Tester que Langfuse démarre**

```bash
docker compose up -d langfuse-db langfuse
docker compose logs langfuse --tail 20
```

Expected: Langfuse démarre, crée les tables, affiche "Ready".

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "infra: add Langfuse + Postgres to docker-compose"
```

---

### Task 2: Module de traçage — bot/core/tracing.py

**Files:**
- Create: bot/core/tracing.py
- Modify: requirements.txt

- [ ] **Step 1: Ajouter langfuse aux dépendances**

Ajouter dans requirements.txt:

```
langfuse>=2.0.0
```

- [ ] **Step 2: Créer bot/core/tracing.py**

```python
"""Langfuse tracing integration — no-op safe when unconfigured."""
from __future__ import annotations

import os
from typing import Any

from loguru import logger

_langfuse: Any = None
_enabled = False


def init_tracing() -> None:
    """Initialize Langfuse client. No-op if keys are missing."""
    global _langfuse, _enabled

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")

    if not public_key or not secret_key:
        logger.info("Langfuse tracing disabled (LANGFUSE_PUBLIC_KEY/SECRET_KEY not set)")
        return

    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        _enabled = True
        logger.info("Langfuse tracing enabled — host={host}", host=host)
    except Exception as exc:
        logger.warning("Langfuse init failed: {e}", e=exc)


def shutdown_tracing() -> None:
    """Flush pending traces and shutdown."""
    if _langfuse is not None:
        try:
            _langfuse.flush()
        except Exception as exc:
            logger.debug("Langfuse flush error: {e}", e=exc)


def create_trace(
    name: str,
    user_id: str | None = None,
    platform: str | None = None,
    channel_id: str | None = None,
    metadata: dict | None = None,
) -> Any | None:
    """Create a Langfuse trace. Returns None if tracing is disabled."""
    if not _enabled or _langfuse is None:
        return None
    try:
        meta = metadata or {}
        if platform:
            meta["platform"] = platform
        if channel_id:
            meta["channel_id"] = channel_id
        return _langfuse.trace(
            name=name,
            user_id=user_id,
            metadata=meta,
        )
    except Exception as exc:
        logger.debug("Langfuse create_trace error: {e}", e=exc)
        return None


def create_generation(
    trace: Any,
    name: str,
    model: str,
    input: Any = None,
    output: str | None = None,
    usage: dict | None = None,
    metadata: dict | None = None,
) -> None:
    """Log an LLM generation (call) within a trace. No-op if trace is None."""
    if trace is None:
        return
    try:
        trace.generation(
            name=name,
            model=model,
            input=input,
            output=output,
            usage=usage,
            metadata=metadata,
        )
    except Exception as exc:
        logger.debug("Langfuse create_generation error: {e}", e=exc)


def create_span(
    trace: Any,
    name: str,
    input: Any = None,
    output: Any = None,
    metadata: dict | None = None,
) -> None:
    """Log a non-LLM operation span within a trace. No-op if trace is None."""
    if trace is None:
        return
    try:
        trace.span(
            name=name,
            input=input,
            output=output,
            metadata=metadata,
        )
    except Exception as exc:
        logger.debug("Langfuse create_span error: {e}", e=exc)
```

- [ ] **Step 3: Commit**

```bash
git add bot/core/tracing.py requirements.txt
git commit -m "feat: add Langfuse tracing module (no-op safe)"
```

---

### Task 3: Init tracing au boot

**Files:**
- Modify: bot/main.py

- [ ] **Step 1: Ajouter init_tracing dans main.py**

Ajouter l'import:

```python
from bot.core.tracing import init_tracing, shutdown_tracing
```

Après la création de la Database et avant la création des LLM clients, appeler:

```python
init_tracing()
```

Dans le bloc finally ou atexit, ajouter:

```python
shutdown_tracing()
```

- [ ] **Step 2: Commit**

```bash
git add bot/main.py
git commit -m "feat: init/shutdown Langfuse tracing at boot"
```

---

### Task 4: Ajouter trace aux signatures LLM

**Files:**
- Modify: bot/core/llm/base.py
- Modify: bot/core/llm/openai_client.py
- Modify: bot/core/llm/claude_client.py

- [ ] **Step 1: Ajouter trace=None à BaseLLMClient**

Dans bot/core/llm/base.py, ajouter le paramètre `trace: Any = None` aux 3 méthodes abstraites (complete, complete_with_tools, complete_structured). Ajouter `from typing import Any` à l'import.

- [ ] **Step 2: Ajouter trace aux signatures dans openai_client.py**

Ajouter `trace=None` à toutes les méthodes publiques (complete, complete_with_tools, complete_structured) et les méthodes internes (_complete_responses_api, _complete_with_tools_responses, _complete_with_tools_chat). Propager trace aux appels internes.

- [ ] **Step 3: Ajouter trace aux signatures dans claude_client.py**

Même chose — ajouter `trace=None` aux méthodes publiques et les propager.

- [ ] **Step 4: Commit**

```bash
git add bot/core/llm/base.py bot/core/llm/openai_client.py bot/core/llm/claude_client.py
git commit -m "feat: add trace parameter to LLM client signatures"
```

---

### Task 5: Remplacer log_cost par Langfuse generations dans OpenAI client

**Files:**
- Modify: bot/core/llm/openai_client.py

- [ ] **Step 1: Ajouter l'import tracing**

```python
from bot.core.tracing import create_generation
```

- [ ] **Step 2: Remplacer les 7 appels log_cost par create_generation**

Pour chaque occurrence de `await self._db.log_cost(...)`, le remplacer par un appel create_generation(). Pattern:

Avant (exemple dans complete()):
```python
await self._db.log_cost(self._model, usage.prompt_tokens, usage.completion_tokens, cost, purpose, user_id=user_id)
```

Après:
```python
create_generation(
    trace,
    name=purpose,
    model=self._model,
    input=messages,
    output=text,
    usage={"input": usage.prompt_tokens, "output": usage.completion_tokens, "total": usage.prompt_tokens + usage.completion_tokens},
    metadata={"purpose": purpose, "user_id": user_id, "temperature": self._temperature},
)
```

Appliquer ce pattern aux 7 emplacements:
1. _complete_responses_api() (line ~205)
2. complete() Chat Completions (line ~285)
3. _complete_with_tools_responses() (line ~421)
4. _complete_with_tools_chat() (line ~509)
5. complete_structured() Responses API (line ~600)
6. complete_structured() Chat Completions (line ~678)
7. generate_image() (line ~791) — usage {"input": 0, "output": 0}, ajouter cost_usd dans metadata

- [ ] **Step 3: Commit**

```bash
git add bot/core/llm/openai_client.py
git commit -m "feat: replace log_cost with Langfuse generations in OpenAI client"
```

---

### Task 6: Remplacer log_cost par Langfuse generations dans Claude client

**Files:**
- Modify: bot/core/llm/claude_client.py

- [ ] **Step 1: Ajouter l'import tracing**

```python
from bot.core.tracing import create_generation
```

- [ ] **Step 2: Remplacer les 2 appels log_cost**

Dans _log_usage() (line ~196) et complete_with_tools() (line ~443), remplacer self._db.log_cost() par create_generation() avec le même pattern que Task 5.

La méthode _log_usage() doit aussi recevoir les paramètres trace, messages, output pour créer la generation.

- [ ] **Step 3: Commit**

```bash
git add bot/core/llm/claude_client.py
git commit -m "feat: replace log_cost with Langfuse generations in Claude client"
```

---

### Task 7: Instrumenter les handlers Discord

**Files:**
- Modify: bot/discord/handlers.py

- [ ] **Step 1: Ajouter l'import tracing**

```python
from bot.core.tracing import create_trace, create_span
```

- [ ] **Step 2: Créer la trace dans _respond()**

Au tout début de _respond() (after `await message.add_reaction`), ajouter:

```python
trace = create_trace(
    name="discord:message",
    user_id=f"discord:{user_id}",
    platform="discord",
    channel_id=str(message.channel.id),
    metadata={
        "author": _author_label(message.author),
        "emotion_state": bot.emotion.get_state(),
        "guild": message.guild.name if message.guild else None,
    },
)
```

- [ ] **Step 3: Passer trace aux appels LLM**

Modifier les appels LLM dans _respond() (lines ~977-988):

```python
if tools:
    reply, tools_called = await bot.llm.complete_with_tools(
        system_prompt, openai_messages, tools, _tool_executor,
        purpose="discord_response",
        image_urls=image_urls or None,
        user_id=f"discord:{message.author.id}",
        trace=trace,
    )
else:
    reply = await bot.llm.complete(
        system_prompt, openai_messages, purpose="discord_response",
        image_urls=image_urls or None,
        user_id=f"discord:{message.author.id}",
        trace=trace,
    )
```

- [ ] **Step 4: Ajouter des spans pour memory et graph**

Après le memory.search() (line ~687):
```python
create_span(trace, name="memory:search", input={"query": message.content}, output={"context_length": len(mem_context or "")})
```

Après le graph.search() (line ~786):
```python
create_span(trace, name="graph:search", input={"query": message.content}, output={"facts_count": len(facts) if facts else 0})
```

- [ ] **Step 5: Commit**

```bash
git add bot/discord/handlers.py
git commit -m "feat: instrument Discord handler with Langfuse traces"
```

---

### Task 8: Instrumenter les handlers Twitch

**Files:**
- Modify: bot/twitch/handlers.py

- [ ] **Step 1: Ajouter l'import tracing et créer la trace**

Même pattern que Discord — create_trace() au début du handler, passer trace=trace aux appels bot.llm.complete() et bot.llm.complete_with_tools().

Chercher les appels LLM dans le fichier (lignes ~391 et ~397) et ajouter trace=trace.

- [ ] **Step 2: Commit**

```bash
git add bot/twitch/handlers.py
git commit -m "feat: instrument Twitch handler with Langfuse traces"
```

---

### Task 9: Proxy Langfuse dans le panel admin

**Files:**
- Create: bot/dashboard/routes/langfuse_proxy.py
- Modify: bot/dashboard/app.py

- [ ] **Step 1: Créer le proxy reverse**

Créer bot/dashboard/routes/langfuse_proxy.py — un routeur FastAPI qui proxie toutes les requêtes vers le serveur Langfuse interne (http://langfuse:3000). Le proxy doit:
- Accepter GET/POST/PUT/DELETE/PATCH sur /langfuse/{path:path}
- Forward la requête avec httpx.AsyncClient
- Retirer les headers hop-by-hop + x-frame-options + content-security-policy (pour permettre l'iframe)
- Retourner 502 si Langfuse est indisponible

- [ ] **Step 2: Enregistrer le proxy dans app.py**

Ajouter l'import langfuse_proxy et le router dans create_dashboard_app():

```python
app.include_router(langfuse_proxy.router, prefix="/api/admin")
```

- [ ] **Step 3: Supprimer le costs router et la notification task de app.py**

Retirer costs de l'import, retirer app.include_router(costs.router), supprimer _cost_notification_task et toutes ses refs (asyncio.create_task, cancel, await).

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/routes/langfuse_proxy.py bot/dashboard/app.py
git commit -m "feat: add Langfuse proxy route, remove costs router"
```

---

### Task 10: Supprimer le fichier costs.py

**Files:**
- Delete: bot/dashboard/routes/costs.py

- [ ] **Step 1: Supprimer le fichier**

```bash
rm bot/dashboard/routes/costs.py
```

- [ ] **Step 2: Commit**

```bash
git add -u bot/dashboard/routes/costs.py
git commit -m "chore: delete costs.py route file"
```

---

### Task 11: Panel admin — Remplacer onglet Coûts par Langfuse

**Files:**
- Modify: bot/dashboard/static/index.html
- Modify: bot/dashboard/static/app.js

- [ ] **Step 1: Remplacer l'item sidebar dans index.html**

Remplacer le lien admin-costs par admin-langfuse avec une icône chart. Supprimer le badge coûts. Remplacer tab-admin-costs par tab-admin-langfuse.

- [ ] **Step 2: Supprimer le code JS des coûts dans app.js**

Supprimer toutes les fonctions costs: renderCostsTab, switchCostsSubTab, loadCosts, setCostRange, drawCostGraph, renderCostBreakdown, renderCostUsers, updateCostAlertBar, updateCostBadge, drawFeaturePie, loadCostsByFeature, loadCostPrices, loadCostLogs, pollCostsBadge. Plus les variables _costsSubTab, _costGraphMeta, _costRafPending, _costsLogsPage.

Dans showTab(), remplacer le trigger admin-costs par admin-langfuse. Supprimer pollCostsBadge() de showTab() et enterAdmin().

- [ ] **Step 3: Ajouter la fonction renderLangfuseTab() dans app.js**

```javascript
function renderLangfuseTab() {
  var el = document.getElementById('tab-admin-langfuse');
  if (!el) return;
  if (el.querySelector('iframe')) return;
  var iframe = document.createElement('iframe');
  iframe.id = 'langfuse-frame';
  iframe.src = '/api/admin/langfuse/';
  iframe.style.cssText = 'width:100%;height:calc(100vh - 80px);border:none;border-radius:8px;background:var(--bg-surface)';
  el.appendChild(iframe);
}
```

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/app.js
git commit -m "feat: replace Costs tab with Langfuse iframe in admin panel"
```

---

### Task 12: Supprimer les styles CSS costs

**Files:**
- Modify: bot/dashboard/static/style.css

- [ ] **Step 1: Supprimer les classes .cost-***

Supprimer toutes les sections CSS contenant cost-kpis, cost-kpi, cost-alert-bar, cost-range-btn.

- [ ] **Step 2: Commit**

```bash
git add bot/dashboard/static/style.css
git commit -m "chore: remove cost-related CSS"
```

---

### Task 13: Test et validation

**Files:** Aucun (testing only)

- [ ] **Step 1: Rebuild et redémarrer tout le stack**

```bash
docker compose build wally && docker compose up -d
```

- [ ] **Step 2: Vérifier que Langfuse est accessible**

```bash
curl -s http://localhost:3000/api/public/health
```

Expected: status OK ou similaire.

- [ ] **Step 3: Vérifier le proxy depuis le panel admin**

```bash
curl -s -H "Authorization: Bearer <token>" http://localhost:8080/api/admin/langfuse/api/public/health
```

Expected: status OK.

- [ ] **Step 4: Vérifier l'onglet Langfuse dans le navigateur**

Ouvrir http://<host-ip>:8080/admin et cliquer sur l'onglet Langfuse.
Expected: l'UI Langfuse s'affiche dans l'iframe.

- [ ] **Step 5: Envoyer un message Discord et vérifier la trace dans Langfuse**

Envoyer un message au bot sur Discord, puis dans l'UI Langfuse, vérifier qu'une trace apparaît avec le nom "discord:message", le user_id, et une generation avec le model et tokens.

- [ ] **Step 6: Vérifier que l'onglet Coûts est bien supprimé**

```bash
curl -s http://localhost:8080/static/app.js | grep -c "renderCostsTab"
```

Expected: 0

- [ ] **Step 7: Vérifier que le bot fonctionne sans Langfuse**

```bash
docker compose stop langfuse langfuse-db
# Envoyer un message Discord — le bot doit répondre normalement
docker compose start langfuse-db langfuse
```

- [ ] **Step 8: Commit final si ajustements**

```bash
git add -A && git commit -m "fix: post-Langfuse integration adjustments"
```

---

## Execution Order

Tasks 1-3: Infrastructure + module tracing (séquentielles)
Tasks 4-6: Instrumentation LLM (séquentielles — les signatures doivent être modifiées avant)
Tasks 7-8: Instrumentation handlers (parallélisables)
Tasks 9-12: Panel admin (séquentielles)
Task 13: Validation finale
