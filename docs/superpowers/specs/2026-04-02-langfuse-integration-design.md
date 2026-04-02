# Langfuse Integration — Spec

## Objectif

Intégrer Langfuse (self-hosted) pour le traçage complet des conversations et appels LLM de Wally. Remplace le système de coûts actuel (SQLite `log_cost` + onglet Coûts du panel admin).

## Contexte

Wally utilise 2 providers LLM (OpenAI, Claude) via `bot/core/llm/`. Chaque appel logge ses coûts dans SQLite via `log_cost()`. L'onglet Coûts du panel admin affiche des résumés, graphes et breakdowns. Ce système est remplacé par Langfuse qui offre du traçage complet (prompts, réponses, tokens, latences, coûts) + une UI native.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Discord /  │────▶│   Wally Bot  │────▶│  Langfuse   │
│   Twitch    │     │  (tracing.py)│     │  (port 3000)│
└─────────────┘     └──────────────┘     └──────┬──────┘
                           │                     │
                    ┌──────┴──────┐        ┌─────┴─────┐
                    │ OpenAI/Claude│        │ Postgres  │
                    │   APIs       │        │ (langfuse)│
                    └──────────────┘        └───────────┘
```

Le panel admin accède à Langfuse via un proxy FastAPI interne (même tunnel Cloudflare).

---

## 1. Infrastructure Docker

### Services ajoutés dans `docker-compose.yml`

**`langfuse-db`** — Postgres 16 dédié :
- Image : `postgres:16-alpine`
- Volume : `./data/langfuse-db:/var/lib/postgresql/data`
- Réseau : `wally-net`
- Port : non exposé (interne uniquement)
- Credentials via `.env` : `LANGFUSE_DB_PASSWORD`

**`langfuse`** — Serveur Langfuse v3 :
- Image : `langfuse/langfuse:3`
- Dépend de : `langfuse-db`
- Réseau : `wally-net`
- Port : non exposé (interne uniquement, accès via proxy FastAPI)
- Variables d'environnement :
  - `DATABASE_URL=postgresql://langfuse:${LANGFUSE_DB_PASSWORD}@langfuse-db:5432/langfuse`
  - `NEXTAUTH_URL=http://langfuse:3000`
  - `NEXTAUTH_SECRET` (généré, dans `.env`)
  - `SALT` (généré, dans `.env`)
  - `LANGFUSE_INIT_ORG_ID=wally`
  - `LANGFUSE_INIT_ORG_NAME=Wally`
  - `LANGFUSE_INIT_PROJECT_ID=wally-bot`
  - `LANGFUSE_INIT_PROJECT_NAME=Wally Bot`
  - `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` (dans `.env`)
  - `LANGFUSE_INIT_PROJECT_SECRET_KEY` (dans `.env`)
  - `LANGFUSE_INIT_USER_EMAIL` (dans `.env`)
  - `LANGFUSE_INIT_USER_PASSWORD` (dans `.env`)

**Wally** — `depends_on` mis à jour pour inclure `langfuse`.

### Variables `.env` ajoutées

```env
# Langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://langfuse:3000
LANGFUSE_DB_PASSWORD=langfuse_secret
NEXTAUTH_SECRET=<random-32-chars>
LANGFUSE_SALT=<random-32-chars>
LANGFUSE_INIT_USER_EMAIL=admin@wally.local
LANGFUSE_INIT_USER_PASSWORD=<password>
```

---

## 2. Module de traçage — `bot/core/tracing.py`

### Responsabilité

Singleton qui initialise le client Langfuse au boot et expose des helpers pour créer traces et spans. Si les clés Langfuse ne sont pas dans `.env`, le module est inactif (no-op) — aucun crash.

### Interface

```python
# Initialisation (appelé dans main.py)
init_tracing() -> None

# Créer une trace pour un message utilisateur
create_trace(
    name: str,
    user_id: str,
    platform: str,
    channel_id: str,
    metadata: dict | None = None,
) -> Trace | None

# Créer une generation (appel LLM) dans une trace
create_generation(
    trace: Trace,
    name: str,
    model: str,
    input: list[dict],       # messages
    output: str,             # réponse
    usage: dict,             # {"input": N, "output": M, "total": N+M}
    metadata: dict | None,
) -> None

# Créer un span (opération non-LLM) dans une trace
create_span(
    trace: Trace,
    name: str,
    input: dict | None = None,
    output: dict | None = None,
    metadata: dict | None = None,
) -> None

# Flush (appelé au shutdown)
shutdown_tracing() -> None
```

### Comportement quand désactivé

Si `LANGFUSE_PUBLIC_KEY` ou `LANGFUSE_SECRET_KEY` ne sont pas définis :
- `init_tracing()` logge un warning et n'initialise rien
- `create_trace()` retourne `None`
- `create_generation()` et `create_span()` sont des no-op si trace est `None`
- Aucune dépendance au runtime — le bot fonctionne normalement sans Langfuse

---

## 3. Instrumentation des handlers

### Discord (`bot/discord/handlers.py`)

Au début du traitement d'un message (dans `on_message` ou l'équivalent), créer une trace :

```python
trace = create_trace(
    name=f"discord:message",
    user_id=str(message.author.id),
    platform="discord",
    channel_id=str(message.channel.id),
    metadata={"emotion_state": emotion.get_state(), "author": display_name},
)
```

Passer `trace` aux fonctions qui font des appels LLM.

### Twitch (`bot/twitch/handlers.py`)

Même pattern — trace créée au début du traitement de chaque message.

### Propagation

Le `trace` est passé comme paramètre optionnel. Les fonctions qui ne reçoivent pas de trace (appels internes, cron, etc.) fonctionnent sans traçage — pas de regression.

---

## 4. Instrumentation des providers LLM

### Modifications de `BaseLLMClient`

Ajouter un paramètre optionnel `trace=None` à chaque méthode :

```python
async def complete(
    self, system_prompt, messages, purpose="response",
    image_urls=None, user_id=None, max_tokens=None,
    trace=None,  # ← nouveau
) -> str:
```

### Dans `OpenAILLMClient` et `ClaudeLLMClient`

Après chaque appel API réussi (là où `log_cost` était appelé), appeler `create_generation()` avec :
- `name` : le `purpose` (response, fact_extraction, session_summary, etc.)
- `model` : le model ID
- `input` : les messages envoyés
- `output` : la réponse générée
- `usage` : tokens input/output
- `metadata` : `{"purpose": purpose, "user_id": user_id, "temperature": self._temperature}`

### Suppression de `log_cost`

Les appels `await self._db.log_cost(...)` sont supprimés de tous les providers :
- `bot/core/llm/openai_client.py` : 7 occurrences (lines 205, 285, 421, 509, 600, 678, 791)
- `bot/core/llm/claude_client.py` : 2 occurrences (lines 196, 443)

Note : `generate_image()` dans openai_client logge aussi des coûts — instrumentation identique.

---

## 5. Instrumentation des services secondaires

### Memory search (`bot/core/memory.py`)

Span `memory:search` avec : query, nombre de résultats, score top match.

### Emotion analysis (`bot/core/emotion.py`)

Span `emotion:update` avec : état avant, delta appliqué, état après.

### Graph ingestion (`bot/core/graph.py`)

Span `graph:add_episode` avec : contenu envoyé, entités/edges extraits.

### Fact extraction (`bot/core/fact_extractor.py`)

La fact extraction appelle déjà `complete_structured()` — elle sera tracée automatiquement via le paramètre `trace` propagé.

---

## 6. Suppression du système de coûts

### Fichiers / code supprimé

| Élément | Fichier | Action |
|---------|---------|--------|
| Route costs | `bot/dashboard/routes/costs.py` | Supprimer le fichier |
| Router include | `bot/dashboard/app.py:144` | Retirer `costs.router` |
| Cost notification task | `bot/dashboard/app.py:97,102,112,245-265` | Supprimer la task et ses refs |
| JS cost functions | `bot/dashboard/static/app.js` | Supprimer : `renderCostsTab`, `loadCosts`, `drawCostGraph`, `drawFeaturePie`, `loadCostsByFeature`, `loadCostPrices`, `loadCostLogs`, `setCostRange`, `renderCostBreakdown`, `renderCostUsers`, `updateCostAlertBar`, `updateCostBadge`, `pollCostsBadge`, `switchCostsSubTab`, `_costsSubTab`, `_costsLogsPage`, `_costGraphMeta`, `_costRafPending` |
| Sidebar item Coûts | `bot/dashboard/static/index.html` | Supprimer le `<a data-tab="admin-costs">` et le `<div id="tab-admin-costs">` |
| CSS costs | `bot/dashboard/static/style.css` | Supprimer les styles `.cost-*` |

### Code conservé (dans DB, nettoyage ultérieur)

Les méthodes DB `log_cost`, `get_cost_stats`, etc. dans `database.py` sont conservées pour l'instant (pas de migration de schéma). Elles ne seront simplement plus appelées. On pourra les supprimer dans un nettoyage futur.

---

## 7. Panel admin — Onglet Langfuse

### Proxy FastAPI

Nouveau fichier `bot/dashboard/routes/langfuse_proxy.py` :

- Route catch-all : `GET/POST/PUT/DELETE /api/admin/langfuse/{path:path}`
- Proxie vers `http://langfuse:3000/{path}` avec `httpx.AsyncClient`
- Authentifié par le Bearer token admin (middleware existant)
- Headers CORS/frame adaptés pour permettre l'iframe

### Sidebar

Remplacement de l'item "Coûts" par "Langfuse" dans `index.html` avec une icône chart/analytics.

### Tab content

```html
<div class="tab-content" id="tab-admin-langfuse">
  <iframe id="langfuse-frame" src="/api/admin/langfuse/"
          style="width:100%;height:calc(100vh - 60px);border:none;border-radius:8px">
  </iframe>
</div>
```

Le JS `showTab('admin-langfuse')` charge/rafraîchit l'iframe.

---

## 8. Initialisation au boot

Dans `bot/main.py` :

```python
from bot.core.tracing import init_tracing, shutdown_tracing

# Au démarrage
init_tracing()

# Au shutdown
shutdown_tracing()
```

Langfuse flush ses données de manière asynchrone — `shutdown_tracing()` appelle `langfuse.flush()` pour s'assurer que les dernières traces sont envoyées.

---

## Dépendances Python ajoutées

- `langfuse>=2.0.0` — SDK Python Langfuse
- `httpx>=0.27.0` — pour le proxy FastAPI vers Langfuse (probablement déjà présent)

---

## Hors périmètre

- Migration des données de coûts historiques SQLite → Langfuse (les données existantes restent dans SQLite, on ne les importe pas)
- Alertes de coûts via Langfuse (le `cost_alert_threshold` est conservé dans la config mais non branché)
- Dashboard public Langfuse — accès admin uniquement
- Scoring/evaluation dans Langfuse — peut être ajouté plus tard
- Prompt management via Langfuse — Wally garde ses propres templates dans `persona/prompts/`
